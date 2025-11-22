from typing import List, Dict, Optional


class DonationIntentClassifier:
    """
    Placeholder module for the donation intent model.
    Replace the heuristic with your ML model.
    """

    donation_keywords = [
        "donate",
        "fundraiser",
        "gofundme",
        "venmo",
        "paypal",
        "cashapp",
        "help us raise",
        "raising money",
        "support us",
    ]

    def predict(self, text: str) -> Dict:
        """
        Return donation intent (heuristic for now).
        Replace with DistilBERT or RoBERTa classifier.
        """
        lowered = text.lower()
        hit = any(kw in lowered for kw in self.donation_keywords)
        return {
            "is_donation_related": hit,
            "confidence": 0.75 if hit else 0.10,
        }
