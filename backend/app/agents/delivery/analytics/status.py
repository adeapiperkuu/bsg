"""Pure traffic-light analytics for the Delivery Performance Agent."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

TrafficLightStatus = Literal["green", "yellow", "red"]


def calculate_status(
    *,
    confidence: Decimal,
    risk_score: Decimal,
    open_bottleneck_count: int = 0,
    milestone_status: str | None = None,
    yellow_confidence_threshold: Decimal = Decimal("80.00"),
    red_confidence_threshold: Decimal = Decimal("50.00"),
    yellow_risk_threshold: Decimal = Decimal("30.00"),
    red_risk_threshold: Decimal = Decimal("85.00"),
    open_risk_tiers: Sequence[str] | None = None,
) -> TrafficLightStatus:
    """Derive dashboard traffic-light status from deterministic scoring outputs."""
    risk_tiers = {tier.lower() for tier in open_risk_tiers or ()}
    normalized_milestone_status = milestone_status.lower() if milestone_status else None

    if (
        confidence < red_confidence_threshold
        or risk_score >= red_risk_threshold
        or "critical" in risk_tiers
        or normalized_milestone_status == "missed"
    ):
        return "red"

    if (
        confidence < yellow_confidence_threshold
        or risk_score >= yellow_risk_threshold
        or risk_tiers.intersection({"medium", "high"})
        or open_bottleneck_count > 0
    ):
        return "yellow"

    return "green"
