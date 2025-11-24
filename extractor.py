import re
import io
import json
import difflib
import requests
from typing import List, Dict, Optional
from PIL import Image
from pyzbar.pyzbar import decode


class EndpointExtractor:

    # ===========================================
    # INITIALIZATION
    # ===========================================
    def __init__(self, charity_json_path="charity-sites.json", google_api_key=None): # I haven't set the API yet

        # Load known charity / crowdfunding sites
        try:
            with open(charity_json_path, "r") as f:
                self.charity_sites = json.load(f)   # dict: domain → metadata dict
        except:
            self.charity_sites = {}

        self.google_api_key = google_api_key

    # ===========================================
    # REGEX PATTERNS
    # ===========================================
    protocol_url_pattern = re.compile(r"(https?://[^\s]+)")
    bare_domain_pattern = re.compile(
        r"\b(?:www\.)?(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,15}(?:/[^\s]*)?\b"
    )

    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,15}")
    cashapp_pattern = re.compile(r"\$[A-Za-z0-9_]+")
    venmo_raw_pattern = re.compile(r"@[A-Za-z0-9_]+")

    intent_keywords = [
        "donate", "donation", "fund", "support", "help", "charity",
        "tip", "payment", "send money", "zelle", "paypal",
        "cashapp", "venmo"
    ]

    payment_keywords = [
        "donate", "donation", "fund", "funding", "support",
        "checkout", "pay", "payment", "tip", "charity"
    ]

    venmo_context_words = ["venmo", "donate", "pay"]

    suspicious_prefix = ["pay", "secure", "donate", "donation", "fund", "payment"]

    # ===========================================
    # HELPERS
    # ===========================================
    def _context_window(self, text, token, window=12):
        idx = text.find(token)
        if idx == -1:
            return ""
        return text[max(0, idx - window) : min(len(text), idx + len(token) + window)]

    # ===========================================
    # Extract URLs
    # ===========================================
    def extract_urls(self, text: str) -> List[str]:
        urls = set()

        email_domains = set()
        for email in self.email_pattern.findall(text):
            domain = email.split("@")[1].lower()
            email_domains.add(domain)

        TRAILING_PUNCT = ".,!?);:\"'·）】】）"

        for raw in self.protocol_url_pattern.findall(text):
            
            while raw and raw[-1] in TRAILING_PUNCT:
                raw = raw[:-1]

            raw = raw.rstrip("/")
            urls.add(raw)

        # extract bare domain
        for raw in self.bare_domain_pattern.findall(text):

            domain_only = raw.split("/")[0].lower()

            if domain_only in email_domains:
                continue

            # prepend https://
            if not raw.startswith("http"):
                raw = "https://" + raw

            while raw and raw[-1] in TRAILING_PUNCT:
                raw = raw[:-1]

            raw = raw.rstrip("/")
            urls.add(raw)

        return list(urls)

    # ===========================================
    # Analyze URL using charity metadata
    # ===========================================
    def analyze_url(self, url: str) -> Dict:

        url_lower = url.lower()

        # extract domain
        try:
            domain = url_lower.split("//", 1)[1].split("/", 1)[0]
        except:
            domain = url_lower

        # path donation signal
        path_signal = any(kw in url_lower for kw in self.payment_keywords)

        # fuzzy match with charity_sites keys
        best_match = difflib.get_close_matches(
            domain, self.charity_sites.keys(), n=1, cutoff=0.75
        )

        charity_info = None
        score = 0

        if best_match:
            best_domain = best_match[0]
            charity_info = self.charity_sites[best_domain]
            score = difflib.SequenceMatcher(None, domain, best_domain).ratio()

        return {
            "url": url,
            "domain": domain,
            "charity_info": charity_info,   # full metadata dict
            "match_score": score,
            "path_signal": path_signal
        }

    # ===========================================
    # Web Risk check
    # ===========================================
    def check_webrisk(self, url: str) -> Dict:

        if not self.google_api_key:
            return {"malicious": False}

        endpoint = (
            "https://webrisk.googleapis.com/v1/uris:search?"
            f"key={self.google_api_key}&uri={url}"
        )

        try:
            resp = requests.get(endpoint)
            data = resp.json()

            if "threat" in data:
                return {
                    "malicious": True,
                    "threatTypes": data["threat"]["threatTypes"],
                    "raw": data
                }

            return {"malicious": False}

        except:
            return {"malicious": False}

    # ===========================================
    # Payment handles
    # ===========================================
    def extract_payment_handles(self, text: str) -> List[Dict]:

        results = []

        # PayPal/Zelle email
        for email in self.email_pattern.findall(text):
            ctx = self._context_window(text, email, 15)
            if any(k in ctx.lower() for k in self.intent_keywords):
                results.append({
                    "type": "payment",
                    "provider": "paypal/zelle (email)",
                    "value": email,
                    "source": "text"
                })

        # CashApp
        for h in self.cashapp_pattern.findall(text):
            results.append({
                "type": "payment",
                "provider": "cashapp",
                "value": h,
                "source": "text"
            })

        # Venmo @handle
        for h in self.venmo_raw_pattern.findall(text):
            ctx = self._context_window(text, h, 10)
            if any(w in ctx.lower() for w in self.venmo_context_words):
                results.append({
                    "type": "payment",
                    "provider": "venmo",
                    "value": h,
                    "source": "text"
                })

        return results

    # ===========================================
    # Unknown payment domain detection
    # ===========================================
    def detect_unknown_payment(self, analyzed: Dict, text: str) -> Optional[Dict]:

        url = analyzed["url"]
        domain = analyzed["domain"]

        # path lookup
        if analyzed["path_signal"]:
            return {
                "type": "payment",
                "provider": "unknown-payment",
                "signal": "path_keyword",
                "value": url
            }

        # semantic intent
        ctx = self._context_window(text, url, 20)
        if any(k in ctx.lower() for k in self.intent_keywords):
            return {
                "type": "payment",
                "provider": "unknown-payment",
                "signal": "semantic_context",
                "value": url
            }

        # suspicious domain prefix
        if any(domain.startswith(pfx) for pfx in self.suspicious_prefix):
            return {
                "type": "payment",
                "provider": "unknown-payment",
                "signal": "domain_prefix",
                "value": url
            }

        return None

    # ===========================================
    # QR recognition
    # ===========================================
    def extract_qr_urls(self, post) -> List[str]:

        urls = []

        if not hasattr(post, "embed") or not hasattr(post.embed, "images"):
            return urls

        for img in post.embed.images:
            try:
                pil_img = Image.open(io.BytesIO(img.fullsize))
                decoded = decode(pil_img)

                for obj in decoded:
                    data = obj.data.decode("utf-8")
                    if data.startswith(("http", "pay", "app")):
                        urls.append(data)
            except:
                continue

        return urls

    # ===========================================
    # MASTER RUN METHOD
    # ===========================================
    def run(self, text: str, post=None) -> List[Dict]:

        results = []

        urls = self.extract_urls(text)

        for url in urls:

            analyzed = self.analyze_url(url)

            # Known charity / crowdfunding domain
            if analyzed["match_score"] >= 0.85 and analyzed["charity_info"]:

                results.append({
                    "type": "charity",
                    "domain": analyzed["domain"],
                    "value": url,
                    "metadata": analyzed["charity_info"],
                    "signal": "domain_match"
                })
                continue

            # Web Risk malicious check
            risk = self.check_webrisk(url)
            if risk["malicious"]:
                results.append({
                    "type": "payment",
                    "provider": "unknown-payment",
                    "signal": "web_risk_malicious",
                    "value": url,
                    "risk": risk
                })
                continue

            # Unknown payment / suspicious donation
            maybe = self.detect_unknown_payment(analyzed, text)
            if maybe:
                results.append(maybe)
                continue

            # Ordinary URL
            results.append({
                "type": "url",
                "provider": "unknown",
                "value": url
            })

        # Handles
        for p in self.extract_payment_handles(text):
            results.append(p)

        # QR
        if post:
            for qr_url in self.extract_qr_urls(post):
                analyzed = self.analyze_url(qr_url)
                results.append({
                    "type": "qr",
                    "value": qr_url,
                    "charity_info": analyzed["charity_info"]
                })

        return results
