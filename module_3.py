from typing import List, Dict, Any, Optional
from urllib.parse import urlparse


class VerificationSystem:
    """
    Account-level, Post-level, Endpoint-level verification logic.
    """

    VERIFIED_ORG_DOMAINS = {
        "redcross.org",
        "unicef.org",
        "justgiving.com",
        "givebutter.com",
        # add more as needed
    }

    ORG_KEYWORDS = [
        "official",
        "nonprofit",
        "charity",
        "registered charity",
        "501(c)(3)",
        "ngo",
    ]

    def _normalize_domain(self, url: str) -> Optional[str]:
        """
        Extract a normalized domain from a URL (strip scheme, path, and leading www.).
        """
        if not url:
            return None

        # Ensure scheme so urlparse works consistently
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)
        host = parsed.netloc.lower()

        if host.startswith("www."):
            host = host[4:]

        return host or None

    def _handle_to_domain(self, actor_handle: str) -> Optional[str]:
        """
        For Bluesky handles, custom domains may map directly to org domains.
        e.g. 'donations.redcross.org' or 'unicef.org'.
        """
        if not actor_handle:
            return None

        h = actor_handle.lower()
        # Handles can be 'name.domain' or full domains; this keeps the full thing
        if "@" in h:
            h = h.split("@", 1)[-1]

        return h

    def _is_verified_org_domain(self, domain: Optional[str]) -> bool:
        if not domain:
            return False
        domain = domain.lower()
        # direct match or subdomain match
        return any(
            domain == d or domain.endswith("." + d) for d in self.VERIFIED_ORG_DOMAINS
        )

    def verify_account(self, client, actor_handle: str) -> Dict[str, Any]:
        """
        Use Bluesky profile API + handle domain to check if the account
        looks like a verified org (heuristic).
        Expects `client.get_profile(handle)` to return a dict-like profile.
        """
        profile = client.get_profile(actor_handle)  # your wrapper around ATProto
        did = profile.get("did") if isinstance(profile, dict) else None

        # 1) Domain-based heuristic: orgs often use their own domain as handle.
        handle_domain = self._handle_to_domain(actor_handle)
        domain_verified = self._is_verified_org_domain(handle_domain)

        # 2) Profile text heuristic: claims like "official account of <org>".
        display_name = (profile.get("displayName") or "").lower() if isinstance(profile, dict) else ""
        description = (profile.get("description") or "").lower() if isinstance(profile, dict) else ""

        text = display_name + " " + description
        claims_official = any(kw in text for kw in self.ORG_KEYWORDS)

        poster_verified_org = domain_verified or claims_official

        return {
            "poster_verified_org": poster_verified_org,
            "profile_did": did,
            "handle_domain_verified": domain_verified,
            "claims_official_in_profile": claims_official,
        }

    def verify_post_claims(self, text: str) -> Dict[str, Any]:
        """
        NLP-ish heuristic to detect 'claim of official / nonprofit status' in a post.
        Replace with a classifier later.
        """
        lowered = (text or "").lower()

        claim_keywords = [
            "official account of",
            "official fundraiser",
            "we are a registered charity",
            "registered charity",
            "nonprofit organization",
            "non-profit organization",
            "501(c)(3)",
            "tax deductible",
        ]

        claim_hits = [kw for kw in claim_keywords if kw in lowered]
        has_claim = len(claim_hits) > 0

        confidence = 0.75 if has_claim else 0.05

        return {
            "post_claims_verified_org": has_claim,
            "confidence": confidence,
            "matched_phrases": claim_hits,
        }

    def verify_endpoint(self, endpoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        endpoints: list of dicts like:
        - {"type": "url", "url": "https://www.redcross.org/donate"}
        - {"type": "cashapp", "handle": "$someuser"}
        - {"type": "venmo", "handle": "@someuser"}
        """
        verified: List[Dict[str, Any]] = []

        for ep in endpoints:
            ep_type = ep.get("type")

            if ep_type == "url":
                raw_url = ep.get("url", "")
                domain = self._normalize_domain(raw_url)
                is_verified_domain = self._is_verified_org_domain(domain)

                verified.append(
                    {
                        "type": "url",
                        "url": raw_url,
                        "domain": domain,
                        "domain_verified": is_verified_domain,
                        "final_verdict": (
                            "fully_verified" if is_verified_domain else "unverified"
                        ),
                    }
                )

            elif ep_type in ["cashapp", "venmo"]:
                # Peer-to-peer endpoints: by default treat as unverified.
                verified.append(
                    {
                        "type": ep_type,
                        "handle": ep.get("handle"),
                        "domain_verified": False,
                        "final_verdict": "peer_to_peer_unverified",
                    }
                )

            else:
                # Unknown endpoint type; return as-is but flagged as unverified.
                verified.append(
                    {
                        "type": ep_type,
                        "raw": ep,
                        "domain_verified": False,
                        "final_verdict": "unknown_unverified",
                    }
                )

        return verified
