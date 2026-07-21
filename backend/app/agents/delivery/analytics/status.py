"""Pure traffic-light analytics for the Delivery Performance Agent."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from app.agents.delivery.analytics.confidence import ON_TRACK_THRESHOLD

TrafficLightStatus = Literal["green", "yellow", "red"]


def calculate_status(
    *,
    confidence: Decimal,
    risk_score: Decimal,
    open_bottleneck_count: int = 0,
    milestone_status: str | None = None,
    yellow_confidence_threshold: Decimal = ON_TRACK_THRESHOLD,
    red_confidence_threshold: Decimal = Decimal("50.00"),
    yellow_risk_threshold: Decimal = Decimal("30.00"),
    red_risk_threshold: Decimal = Decimal("85.00"),
    open_risk_tiers: Sequence[str] | None = None,
    red_on_critical_confidence: bool = True,
    red_on_critical_risk: bool = True,
    red_on_critical_open_risk: bool = True,
    red_on_missed_milestone: bool = True,
    yellow_on_warning_confidence: bool = True,
    yellow_on_warning_risk: bool = True,
    yellow_on_warning_open_risk: bool = True,
    yellow_on_open_bottleneck: bool = True,
) -> TrafficLightStatus:
    """Derive dashboard traffic-light status from deterministic scoring outputs."""
    risk_tiers = {tier.lower() for tier in open_risk_tiers or ()}
    normalized_milestone_status = milestone_status.lower() if milestone_status else None

    if (
        (red_on_critical_confidence and confidence < red_confidence_threshold)
        or (red_on_critical_risk and risk_score >= red_risk_threshold)
        or (red_on_critical_open_risk and "critical" in risk_tiers)
        or (red_on_missed_milestone and normalized_milestone_status == "missed")
    ):
        return "red"

    if (
        (yellow_on_warning_confidence and confidence < yellow_confidence_threshold)
        or (yellow_on_warning_risk and risk_score >= yellow_risk_threshold)
        or (yellow_on_warning_open_risk and bool(risk_tiers.intersection({"medium", "high"})))
        or (yellow_on_open_bottleneck and open_bottleneck_count > 0)
    ):
        return "yellow"

    return "green"
