"""
policy_proposal_labeler.py — Final Integrated Version (2025)

This system performs end-to-end donation-related detection for Bluesky posts:
1. Fuzzy-match donation intent
2. Extract in text URLs, embeded URLs, QR code URLs, payment handles
3. Classify endpoints using:
       - charity_sites.json domain match
       - keyword-based donation heuristics
4. Verify organizational identity (account > endpoint)
5. Final label assembly:
       donation_related,
       contains_payment_mechanism,
       verified_org,
       verified_type:{account|endpoint|none}
"""

import os
import re
import csv
import json
import argparse
import urllib.parse
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional
from io import BytesIO
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from PIL import Image
from pyzbar.pyzbar import decode as qr_decode
from atproto import Client, models
from atproto_client.models.com.atproto.admin.defs import RepoRef
from atproto_client.models.com.atproto.repo.strong_ref import Main


# ============================================
# Environment setup
# ============================================
load_dotenv(override=True)
USERNAME = os.getenv("USERNAME")
PW = os.getenv("PW")
# GOOGLE_WEBRISK_API_KEY = os.getenv("GOOGLE_WEBRISK_API_KEY")

# Load charity_sites.json
with open("charity-sites.json", "r", encoding="utf-8") as f:
    CHARITY_DB = json.load(f)


# ============================================
# Utils
# ============================================
def did_from_handle(handle: str) -> str:
    """Resolve DID from handle."""
    return requests.get(
        "https://bsky.social/xrpc/com.atproto.identity.resolveHandle",
        params={"handle": handle},
        timeout=10,
    ).json()["did"]


def post_from_url(client: Client, url: str):
    """Retrieve Bluesky post from public URL."""
    parts = url.split("/")
    rkey = parts[-1]
    handle = parts[-3]
    return client.get_post(rkey, handle)


def extract_did_from_uri(uri: str) -> str:
    """Given at://did:.../post/xxx → return did."""
    parts = uri.split("/")
    if len(parts) < 3:
        return ""
    return parts[2]


def get_author_from_did(client, did: str) -> Optional[Dict[str, Any]]:
    """Resolve DID → full actor profile."""
    if not did:
        return None
    try:
        p = client.app.bsky.actor.get_profile({"actor": did})
        return {
            "did": p.did,
            "handle": p.handle,
            "display_name": getattr(p, "displayName", None),
            "description": getattr(p, "description", None),
            "verification": getattr(p, "verification", None),
        }
    except:
        return None


# ======================================================================
# MODULE 1 — Fuzzy Donation Intent Classifier
# ======================================================================
class DonationIntentClassifier:
    donation_keywords = [
        "donate", "donation", "fundraising", "gofundme", 
        "paypal", "cashapp", "cashtag", "venmo",
        "zelle", "charity", "charity", "gofund"
    ]

    phrase_keywords = [
        "please help",
        "help out",
        "any amount helps",
        "need your support",
        "help my family",
        "raise fund",
        "raise money",
        "need help",
        "medical bills",
        "please donate"
    ]


    # url_patterns = [
    #     re.compile(r"https?://\S*(donate|fund|support)\S*", re.IGNORECASE)
    # ]

    def fuzzy_contains(self, text: str, keywords: List[str], threshold=0.8) -> bool:
        """
        Fuzzy match: any token with similarity >= threshold is considered matched.
        No external dependencies.
        """
        tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        for t in tokens:
            for kw in keywords:
                if SequenceMatcher(None, t, kw).ratio() >= threshold:
                    return True
        return False
    
    def phrase_contains(self, text: str) -> bool:
        return any(phrase in text for phrase in self.phrase_keywords)

    def predict(self, text: str):
        t = text.lower()
        fuzzy_kw = self.fuzzy_contains(t, self.donation_keywords)
        phrase_kw = self.phrase_contains(t)
        # url_signal = any(p.search(t) for p in self.url_patterns)

        score = 0.6 * fuzzy_kw + 0.6 * phrase_kw #+ 0.4 * url_signal

        return {
            "donation_related": score > 0.5,
            "confidence": score,
            "signals": {"fuzzy_kw": fuzzy_kw, "phrase_kw": phrase_kw},
        }

# ======================================================================
# MODULE 2 — Endpoint Extractor (Only Extraction + Mechanism Classification)
# ======================================================================
class EndpointExtractor:
    protocol_url_pattern = re.compile(r"https?://[^\s]+")
    bare_domain_pattern = re.compile(
        r"\b(?:www\.)?(?:[a-zA-Z0-9-]+\.)+[A-Za-z]{2,15}(?:/[^\s]*)?\b"
    )
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,15}")
    cashapp_pattern = re.compile(r"\$[A-Za-z][A-Za-z0-9_]+")

    trailing = ".,!?);:\"'"

    donation_path_kw = {
        "donate", "donation", "donating", 
        "fund", "fundraising", "support",
        "give", "relief", "help"
    }

    # known_personal_domains = {
    #     "paypal.me", "paypal.com", "venmo.com", "cash.app"
    # }

    # -------------------------------------------------------------
    # Normalize domain
    # -------------------------------------------------------------
    def _normalize_domain(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host


    # -------------------------------------------------------------
    # Extract URLs from facets
    # -------------------------------------------------------------
    def extract_urls_from_facets(self, post) -> List[str]:
        urls = []
        facets = getattr(post.value, "facets", None)
        if not facets:
            return urls

        for facet in facets:
            feats = getattr(facet, "features", None)
            if not feats:
                continue
            for feat in feats:
                # app.bsky.richtext.facet#link
                uri = getattr(feat, "uri", None)
                if uri:
                    urls.append(uri)

        return urls


    # -------------------------------------------------------------
    # Extract URLs with regex from text
    # -------------------------------------------------------------
    def extract_urls(self, text: str) -> List[str]:
        urls = set()

        email_domains = {e.split("@")[1].lower() for e in self.email_pattern.findall(text)}

        # URLs with http/https
        for raw in self.protocol_url_pattern.findall(text):
            cleaned = raw.rstrip(self.trailing).rstrip("/")
            urls.add(cleaned)

        # Bare domains
        for raw in self.bare_domain_pattern.findall(text):
            domain_only = raw.split("/")[0].lower()
            if domain_only in email_domains:
                continue
            cleaned = raw.rstrip(self.trailing).rstrip("/")
            if not cleaned.startswith(("http://", "https://")):
                cleaned = "https://" + cleaned
            urls.add(cleaned)

        return list(urls)

    
    # -------------------------------------------------------------
    # Extract URLs from embed blocks
    # -------------------------------------------------------------
    def extract_urls_from_embed(self, post) -> List[str]:
        urls = []
        embed = getattr(post, "embed", None)
        if not embed:
            return urls

        # Case 1: external embed
        external = getattr(embed, "external", None)
        if external:
            uri = getattr(external, "uri", None)
            if uri:
                urls.append(uri)

        # Case 2: recordWithMedia
        recordwm = getattr(embed, "record", None)
        if recordwm:
            rec = getattr(recordwm, "record", None)
            if rec:
                ext2 = getattr(rec, "external", None)
                if ext2:
                    uri2 = getattr(ext2, "uri", None)
                    if uri2:
                        urls.append(uri2)

        # Case 3: quoted post
        record = getattr(embed, "record", None)
        if record:
            rec_inner = getattr(record, "record", None)
            if rec_inner:
                ext3 = getattr(rec_inner, "external", None)
                if ext3:
                    uri3 = getattr(ext3, "uri", None)
                    if uri3:
                        urls.append(uri3)

        return list(dict.fromkeys(urls))


    # -------------------------------------------------------------
    # Extract QR URLs 
    # -------------------------------------------------------------
    def extract_qr_urls(self, post) -> List[str]:
        results = []
        embed = getattr(post, "embed", None)
        if not embed:
            return results
        imgs = getattr(embed, "images", None)
        if not imgs:
            return results

        for im in imgs:
            url = getattr(im, "fullsize", None) or getattr(im, "thumb", None)
            if not url:
                continue
            try:
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
                img = Image.open(BytesIO(resp.content))
                decoded = qr_decode(img)
                for q in decoded:
                    text = q.data.decode("utf-8", errors="ignore").strip()
                    sub_urls = self.extract_urls(text)
                    results.extend(sub_urls)
            except:
                continue

        return list(dict.fromkeys(results))


    # -------------------------------------------------------------
    # Payment handles
    # -------------------------------------------------------------
    def extract_payment_handles(self, text: str) -> List[Dict]:
        results = []

        # PayPal/Zelle email-style
        for email in self.email_pattern.findall(text):
            results.append({
                "mechanism": "payment_handle",
                "value": email
            })

        # CashApp handles
        for h in self.cashapp_pattern.findall(text):
            results.append({
                "mechanism": "payment_handle",
                "value": h
            })

        return results


    # -------------------------------------------------------------
    # Classify URL 
    # -------------------------------------------------------------
    def classify_url(self, url: str) -> Dict:
        domain = self._normalize_domain(url)
        parsed = urlparse(url)
        path = parsed.path.lower()
        netloc = parsed.netloc.lower()

        # ---- Case 1: charity_sites.json ----
        if domain in CHARITY_DB:
            info = CHARITY_DB[domain]
            return {
                "mechanism": (
                    "payment_link" if info.get("category") == "p2p_payment"
                    else "fundraising_website"
                ),
                "domain": domain,
                "value": url,
                "in_charity_db": True,
                "recipient_type": info.get("recipient_type", None)
            }

        # ---- Case 2: donation keyword path ----
        path_norm = re.sub(r"[^a-z]", "", path)
        netloc_norm = re.sub(r"[^a-z]", "", netloc)

        if any(kw in path_norm for kw in self.donation_path_kw) or \
           any(kw in netloc_norm for kw in self.donation_path_kw):
            return {
                "mechanism": "fundraising_website",
                "domain": domain,
                "value": url,
                "in_charity_db": False,
                "recipient_type": None
            }

        # ---- fallback ----
        return {
            "mechanism": "unsure",
            "domain": domain,
            "value": url,
            "in_charity_db": False,
            "recipient_type": None
        }


    # -------------------------------------------------------------
    # Run extractor
    # -------------------------------------------------------------
    def run(self, text: str, post) -> Dict:

        urls_text = self.extract_urls(text)
        urls_embed = self.extract_urls_from_embed(post)
        urls_facets = self.extract_urls_from_facets(post)
        urls_qr = self.extract_qr_urls(post)

        urls_all = list(dict.fromkeys(urls_text + urls_embed + urls_facets + urls_qr))

        handles = self.extract_payment_handles(text)

        endpoints = []

        # URL classification with new fields
        for u in urls_all:
            endpoints.append(self.classify_url(u))

        # QR code override
        for q in urls_qr:
            endpoints.append({
                "mechanism": "qrcode",
                "domain": "other",
                "value": q,
                "in_charity_db": False,
                "recipient_type": None
            })

        # Payment handles
        for h in handles:
            endpoints.append({
                "mechanism": "payment_handle",
                "domain": "other",
                "value": h["value"],
                "in_charity_db": False,
                "recipient_type": None
            })

        # Detect mechanisms
        mechanisms_present = {
            e["mechanism"] for e in endpoints if e["mechanism"] not in ["unsure"]
        }

        contains_payment = "yes" if mechanisms_present else "no"

        mechanisms_list = (
            list(mechanisms_present) if contains_payment == "yes" else "no"
        )

        return {
            "contains_payment_mechanism": contains_payment,
            "mechanisms": mechanisms_list,
            "endpoints": endpoints   
        }




# ======================================================================
# MODULE 3+4 — OrgVerifier (account-level and endpoint-level)
# ======================================================================
class OrgVerifier:

    def parse_official_verification(self, v):
        """Bluesky official DNS/domain verification."""
        if not v:
            return False
        try:
            return v.verified_status == "valid"
        except:
            return False

    def parse_trusted_verification(self, v):
        """Bluesky trusted verifier."""
        if not v:
            return False
        try:
            return v.trusted_verifier_status in ("valid", "trusted")
        except:
            return False

    def verify(self, profile, url_info_list):
        """
        Return:
        {
            "verified_org": yes/domain/no,           # endpoint-level
            "verified_type": official/trusted/none          # account-level 
        }
        """

        # ============================================================
        # 1. Account-level verification (official/trusted)
        # ============================================================
        verified_type = "none"

        if profile:

            official = self.parse_official_verification(profile.get("verification"))
            trusted = self.parse_trusted_verification(profile.get("verification"))

            if official:
                verified_type = "official"

            elif trusted:
                verified_type = "trusted"

        # ============================================================
        # 2. Endpoint-level verification (URL level)
        # ============================================================
        found_org_endpoint = False
        found_dot_org = False

        for info in url_info_list:
            domain = info.get("domain", "")
            in_db = info.get("in_charity_db", False)
            recipient = info.get("recipient_type", None)

            # (A) JSON + organizational → yes
            if in_db and recipient == "organizational":
                found_org_endpoint = True
                break

            # (B) domain is .org but not in DB → unsure
            if domain.endswith(".org") and not in_db:
                found_dot_org = True

        if found_org_endpoint:
            verified_org = "yes"
        elif found_dot_org:
            verified_org = "domain"
        else:
            verified_org = "no"

        # ============================================================
        # Final output (account-level & endpoint-level)
        # ============================================================
        return {
            "verified_org": verified_org,
            "verified_type": verified_type
        }


# ======================================================================
# MODULE 6-7 — Google WebRisk Scam Checker
# ======================================================================
# class WebRiskChecker:
#     def __init__(self, api_key):
#         self.api_key = api_key

#     def check(self, url: str):
#         """
#         Return:
#         {
#             "malicious": True/False,
#             "threat_types": [...]
#         }
#         Only check if WebRisk key exists.
#         """
#         if not self.api_key:
#             return {"malicious": False, "threat_types": []}

#         encoded = urllib.parse.quote(url, safe="")
#         endpoint = (
#             f"https://webrisk.googleapis.com/v1/uris:search?key={self.api_key}&uri={encoded}"
#         )

#         try:
#             r = requests.get(endpoint, timeout=4)
#             data = r.json()
#             if "threat" in data:
#                 return {
#                     "malicious": True,
#                     "threat_types": data["threat"].get("threatTypes", []),
#                 }
#             return {"malicious": False, "threat_types": []}
#         except:
#             return {"malicious": False, "threat_types": []}

#     def should_scan(self, info: Dict) -> bool:
#         """
#         Per your instruction:
#         - Scan if category = personal_payment
#         - Scan if category = unknown_org (non-whitelist .org)
#         - Scan if category = keyword_donation_url
#         """
#         cat = info["category"]
#         return cat in {"personal_payment", "unknown_org", "keyword_donation_url"}


# ======================================================================
# MODULE 8 — LabelAssembler
# ======================================================================
class LabelAssembler:
    def assemble(self, intent, endpoints, verification):
        labels = []

        # -----------------------------------------------------
        # 1. donation_related / donation:not_related
        # -----------------------------------------------------
        donation_related = (
            "donation:related"
            if intent["donation_related"]
            else "donation:not_related"
        )
        labels.append(donation_related)

        # -----------------------------------------------------
        # 2. payment:yes / payment:no
        # -----------------------------------------------------
        payment_flag = (
            "payment:yes"
            if endpoints["contains_payment_mechanism"] == "yes"
            else "payment:no"
        )
        labels.append(payment_flag)

        # -----------------------------------------------------
        # 3. mechanism + domain
        # -----------------------------------------------------
        if endpoints["contains_payment_mechanism"] == "yes":

            # mechanisms = list, choose the *dominant* or join safely
            mech_list = endpoints.get("mechanisms", [])
            if isinstance(mech_list, list):
                mech_str = "".join(mech_list) if mech_list else "none"
            else:
                mech_str = mech_list

            # pick the first non-other endpoint for domain
            mech_domain_str = "none"
            for ep in endpoints["endpoints"]:
                if ep["mechanism"] != "other":
                    mech_domain_str = ep.get("domain", "none")
                    break
        else:
            mech_str = "none"
            mech_domain_str = "none"

        labels.append(f"mechanism:{mech_str}")
        labels.append(f"domain:{mech_domain_str}")

        # -----------------------------------------------------
        # 4. verified_org (endpoint-level)
        # -----------------------------------------------------
        labels.append(f"verified_org:{verification['verified_org']}")

        # -----------------------------------------------------
        # 5. verified_type (account-level trusted/official/none)
        # -----------------------------------------------------
        labels.append(f"verified_type:{verification['verified_type']}")

        return labels


# ============================================================
# Apply Label to Post / Account (Provided Starter)
# ============================================================
def label_account(client: Client, handle: str, label_value: List[str]):
    did = did_from_handle(handle)
    data = models.ToolsOzoneModerationEmitEvent.Data(
        created_by=client.me.did,
        event=models.ToolsOzoneModerationDefs.ModEventLabel(
            create_label_vals=label_value,
            negate_label_vals=[],
        ),
        subject=RepoRef(did=did),
        subject_blob_cids=[],
    )
    return client.tools.ozone.moderation.emit_event(data)


def label_post(
    client: Client, labeler_client: Client, post_url: str, label_value: List[str]
):
    post = post_from_url(client, post_url)
    post_ref = Main(cid=post.cid, uri=post.uri)

    data = models.ToolsOzoneModerationEmitEvent.Data(
        created_by=client.me.did,
        event=models.ToolsOzoneModerationDefs.ModEventLabel(
            create_label_vals=label_value,
            negate_label_vals=[],
        ),
        subject=post_ref,
        subject_blob_cids=[],
    )
    return labeler_client.tools.ozone.moderation.emit_event(data)

def parse_labels_list(labels):
    """
    Convert list of labels:
        ["donation:related", "payment:yes", "mechanism:fundraising_website", ...]
    Into a dictionary.
    """
    parsed = {
        "donation": "not_related",
        "payment": "no",
        "mechanism": "none",
        "domain": "none",
        "verified_org": "no",
        "verified_type": "none",
    }

    for label in labels:
        if label.startswith("donation:"):
            parsed["donation"] = label.split(":", 1)[1]

        elif label.startswith("payment:"):
            parsed["payment"] = label.split(":", 1)[1]

        elif label.startswith("mechanism:"):
            parsed["mechanism"] = label.split(":", 1)[1]

        elif label.startswith("domain:"):
            parsed["domain"] = label.split(":", 1)[1]

        elif label.startswith("verified_org:"):
            parsed["verified_org"] = label.split(":", 1)[1]

        elif label.startswith("verified_type:"):
            parsed["verified_type"] = label.split(":", 1)[1]

    return parsed


# ============================================================
# MAIN PIPELINE EXECUTION
# ============================================================
def run_pipeline_on_post(client, labeler_client, post_url):
    post = post_from_url(client, post_url)
    author = get_author_from_did(client, did=extract_did_from_uri(post.uri))
    text = post.value.text
    if author:
        actor = author["handle"]

    # Initialize modules
    intent_model = DonationIntentClassifier()
    extractor = EndpointExtractor()
    verifier = OrgVerifier()
    assembler = LabelAssembler()

    # --- Pipeline Steps ---
    intent = intent_model.predict(text)
    if not intent["donation_related"]:
        return ["donation:not_related"]

    endpoints = extractor.run(text, post)

    verification = verifier.verify(author, endpoints["endpoints"])

    return assembler.assemble(intent, endpoints, verification)


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv_path", default="data.csv")
    parser.add_argument(
        "--apply_labels",
        action="store_true",
        help="If set, send labels to the labeler; otherwise just print them.",
    )
    parser.add_argument(
        "--output_csv",
        default="post_with_preds.csv",
        help="New CSV with ground truth + model predictions.",
    )
    args = parser.parse_args()

    client = Client()
    client.login(USERNAME, PW)
    did = did_from_handle(USERNAME)
    labeler_client = client.with_proxy("atproto_labeler", did)

    with open(args.csv_path, "r", encoding="utf-8", newline="") as f_in, open(
        args.output_csv, "w", encoding="utf-8", newline=""
    ) as f_out:

        reader = csv.DictReader(f_in)
        base_fields = list(reader.fieldnames or [])

        # predicted columns (same schema, but prefixed so you can compare)
        pred_fields = [
            "pred_donation_related",
            "pred_contains_payment_mechanism",
            "pred_payment_mechanism",
            "pred_verified_org",
            "pred_verified_type",
            "pred_domain"
        ]


        fieldnames = base_fields + [f for f in pred_fields if f not in base_fields]
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            # copy over existing values unchanged
            # pick URL from either "source_url" or "url"
            url = (row.get("source_url") or row.get("url") or "").strip()

            if not url:
                # no URL → just write row with empty preds
                for pf in pred_fields:
                    row.setdefault(pf, "")
                writer.writerow(row)
                continue
            labels = {}
            try:
                labels = run_pipeline_on_post(client, labeler_client, url)
            except Exception as e:
                print(e)
                print(f"Failed for this url, skipping {url}")
                continue
            print(f"{url} -> {labels}")

            # Convert list-style labels → dict fields
            parsed = parse_labels_list(labels)


            row["pred_donation_related"] = parsed["donation"]
            row["pred_contains_payment_mechanism"] = parsed["payment"]
            row["pred_payment_mechanism"] = parsed["mechanism"]
            row["pred_verified_org"] = parsed["verified_org"]
            row["pred_verified_type"] = parsed["verified_type"]
            row["pred_domain"] = parsed["domain"]

            writer.writerow(row)

            if args.apply_labels:
                result = label_post(client, labeler_client, url, labels)
                print("  applied:", result)



if __name__ == "__main__":
    main()
