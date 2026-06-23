"""Pure risk analytics for the Delivery Performance Agent."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

RiskTier = Literal["low", "medium", "high", "critical"]

PERCENT = Decimal("100")
ZERO = Decimal("0")


def quantize_probability(value: Decimal) -> Decimal:
    """Return a probability percentage rounded to two decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp_probability(value: Decimal) -> Decimal:
    """Clamp a probability percentage into the inclusive 0-100 range."""
    return quantize_probability(max(ZERO, min(PERCENT, value)))


def confidence_risk_component(
    confidence_score_pct: Decimal,
    *,
    on_track_threshold: Decimal = Decimal("80.00"),
) -> Decimal:
    """Convert confidence shortfall into a risk contribution."""
    if confidence_score_pct >= on_track_threshold:
        return ZERO

    shortfall = on_track_threshold - confidence_score_pct
    return min(Decimal("35.00"), shortfall * Decimal("1.25"))


def throughput_risk_component(
    *,
    throughput_decline_pct: Decimal = ZERO,
    is_declining: bool = False,
) -> Decimal:
    """Convert throughput decline into a risk contribution."""
    if not is_declining:
        return ZERO
    return min(Decimal("25.00"), max(ZERO, throughput_decline_pct) * Decimal("0.75"))


def milestone_risk_component(
    *,
    days_until_milestone: int | None,
    warning_window_days: int = 14,
) -> Decimal:
    """Increase risk as an incomplete milestone approaches or passes its planned date."""
    if days_until_milestone is None:
        return ZERO
    if days_until_milestone < 0:
        return Decimal("30.00")
    if warning_window_days <= 0 or days_until_milestone > warning_window_days:
        return ZERO

    urgency_ratio = Decimal(warning_window_days - days_until_milestone) / Decimal(
        warning_window_days
    )
    return urgency_ratio * Decimal("20.00")


def bottleneck_risk_component(open_bottleneck_count: int = 0) -> Decimal:
    """Convert open bottlenecks into a capped risk contribution."""
    if open_bottleneck_count <= 0:
        return ZERO
    return min(Decimal("15.00"), Decimal(open_bottleneck_count) * Decimal("5.00"))


def quality_risk_component(
    *,
    has_quality_drift: bool = False,
    rework_rate_pct: Decimal | None = None,
) -> Decimal:
    """Convert optional quality drift into a delivery risk contribution."""
    if not has_quality_drift:
        return ZERO
    if rework_rate_pct is None:
        return Decimal("5.00")
    return min(Decimal("15.00"), Decimal("5.00") + max(ZERO, rework_rate_pct) / Decimal("2"))


def calculate_risk(
    *,
    confidence_score_pct: Decimal,
    throughput_decline_pct: Decimal = ZERO,
    is_throughput_declining: bool = False,
    days_until_milestone: int | None = None,
    open_bottleneck_count: int = 0,
    has_quality_drift: bool = False,
    rework_rate_pct: Decimal | None = None,
    on_track_threshold: Decimal = Decimal("80.00"),
    warning_window_days: int = 14,
) -> Decimal:
    """Calculate delivery slippage probability from deterministic risk components."""
    probability = (
        confidence_risk_component(
            confidence_score_pct,
            on_track_threshold=on_track_threshold,
        )
        + throughput_risk_component(
            throughput_decline_pct=throughput_decline_pct,
            is_declining=is_throughput_declining,
        )
        + milestone_risk_component(
            days_until_milestone=days_until_milestone,
            warning_window_days=warning_window_days,
        )
        + bottleneck_risk_component(open_bottleneck_count)
        + quality_risk_component(
            has_quality_drift=has_quality_drift,
            rework_rate_pct=rework_rate_pct,
        )
    )
    return clamp_probability(probability)


def calculate_slippage_probability(
    *,
    confidence_score_pct: Decimal,
    throughput_decline_pct: Decimal = ZERO,
    is_throughput_declining: bool = False,
    days_until_milestone: int | None = None,
    open_bottleneck_count: int = 0,
    has_quality_drift: bool = False,
    rework_rate_pct: Decimal | None = None,
    on_track_threshold: Decimal = Decimal("80.00"),
    warning_window_days: int = 14,
) -> Decimal:
    """Backward-compatible alias for the core risk calculation."""
    return calculate_risk(
        confidence_score_pct=confidence_score_pct,
        throughput_decline_pct=throughput_decline_pct,
        is_throughput_declining=is_throughput_declining,
        days_until_milestone=days_until_milestone,
        open_bottleneck_count=open_bottleneck_count,
        has_quality_drift=has_quality_drift,
        rework_rate_pct=rework_rate_pct,
        on_track_threshold=on_track_threshold,
        warning_window_days=warning_window_days,
    )


def classify_risk_tier(
    slippage_probability: Decimal,
    *,
    medium_threshold: Decimal = Decimal("30.00"),
    high_threshold: Decimal = Decimal("60.00"),
    critical_threshold: Decimal = Decimal("85.00"),
) -> RiskTier:
    """Map slippage probability to the platform risk-tier vocabulary."""
    if slippage_probability >= critical_threshold:
        return "critical"
    if slippage_probability >= high_threshold:
        return "high"
    if slippage_probability >= medium_threshold:
        return "medium"
    return "low"


def build_contributing_causes(
    *,
    confidence_score_pct: Decimal,
    throughput_decline_pct: Decimal = ZERO,
    is_throughput_declining: bool = False,
    days_until_milestone: int | None = None,
    open_bottleneck_count: int = 0,
    has_quality_drift: bool = False,
    rework_rate_pct: Decimal | None = None,
    on_track_threshold: Decimal = Decimal("80.00"),
) -> dict[str, float]:
    """Return normalized cause values suitable for structured risk metadata."""
    causes: dict[str, float] = {}

    confidence_component = confidence_risk_component(
        confidence_score_pct,
        on_track_threshold=on_track_threshold,
    )
    if confidence_component > ZERO:
        causes["confidence_shortfall"] = float(confidence_component)

    throughput_component = throughput_risk_component(
        throughput_decline_pct=throughput_decline_pct,
        is_declining=is_throughput_declining,
    )
    if throughput_component > ZERO:
        causes["throughput_decline"] = float(throughput_component)

    milestone_component = milestone_risk_component(days_until_milestone=days_until_milestone)
    if milestone_component > ZERO:
        causes["milestone_urgency"] = float(milestone_component)

    bottleneck_component = bottleneck_risk_component(open_bottleneck_count)
    if bottleneck_component > ZERO:
        causes["open_bottlenecks"] = float(bottleneck_component)

    quality_component = quality_risk_component(
        has_quality_drift=has_quality_drift,
        rework_rate_pct=rework_rate_pct,
    )
    if quality_component > ZERO:
        causes["quality_drift"] = float(quality_component)

    return causes
