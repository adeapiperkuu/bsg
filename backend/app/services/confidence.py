from decimal import Decimal


def delivery_status_for_score(score_pct: Decimal, on_track_threshold: Decimal = Decimal("80.00")) -> str:
    return "on_track" if score_pct >= on_track_threshold else "at_risk"
