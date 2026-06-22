from decimal import Decimal

from app.services.confidence import delivery_status_for_score


def classify_delivery_confidence(score_pct: Decimal) -> str:
    return delivery_status_for_score(score_pct)
