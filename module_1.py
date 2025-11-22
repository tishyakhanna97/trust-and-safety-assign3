from typing import Dict, List
import re


class DonationIntentClassifier:
    """
    Donation intent detector.
    Currently uses a rule-based heuristic since no training data is available.
    Later replace `predict()` with a fine-tuned transformer model.
    """

    # Simple keyword dictionary to approximate donation-related phrasing
    donation_keywords: List[str] = [
        "donate",
        "donation",
        "fundraiser",
        "fundraising",
        "gofundme",
        "gofund.me",
        "venmo",
        "paypal",
        "cashapp",
        "cashtag",
        "zelle",
        "help us raise",
        "help me raise",
        "raising money",
        "support us",
        "support me",
        "chip in",
        "please help",
        "send help",
        "any amount helps",
    ]

    # Optional: phrase-level patterns (captures payment handles / links)
    payment_patterns: List[re.Pattern] = [
        re.compile(r"\b\$[a-zA-Z0-9_]+\b"),          # $cashtag
        re.compile(r"(venmo\.com|paypal\.me)\/\S+"), # venmo/paypal links
        re.compile(r"https?:\/\/\S*(gofundme|donate)\S*"),
    ]

    def predict(self, text: str) -> Dict:
        """
        Rule-based donation intent detector.
        Replace this with a trained ML classifier when data becomes available.
        """
        lowered = text.lower()

        # keyword hits
        kw_hit = any(kw in lowered for kw in self.donation_keywords)

        # pattern hits
        pattern_hit = any(p.search(lowered) for p in self.payment_patterns)

        score = 0.0
        if kw_hit:
            score += 0.6
        if pattern_hit:
            score += 0.4

        # clamp
        score = min(score, 1.0)

        return {
            "is_donation_related": score > 0.5,
            "confidence": round(score, 2),
            "signals": {
                "keyword_match": kw_hit,
                "pattern_match": pattern_hit,
            },
        }
