"""Pure confidence analytics for the Delivery Performance Agent."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

ConfidenceStatus = Literal["on_track", "at_risk"]
TrendDirection = Literal["improving", "flat", "declining", "unknown"]

ON_TRACK_THRESHOLD = Decimal("80.00")
PERCENT = Decimal("100")
ZERO = Decimal("0")


def quantize_percent(value: Decimal) -> Decimal:
    """Return a percentage rounded to two decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp_percent(value: Decimal) -> Decimal:
    """Clamp a percentage into the inclusive 0-100 range."""
    return quantize_percent(max(ZERO, min(PERCENT, value)))


def calculate_variance_ratio(
    rolling_7day_units: int | None,
    daily_target_units: int | None,
    *,
    window_days: int = 7,
) -> Decimal:
    """Compare recent throughput against the expected output for the same window."""
    if rolling_7day_units is None or daily_target_units is None:
        return ZERO
    if rolling_7day_units <= 0 or daily_target_units <= 0 or window_days <= 0:
        return ZERO

    expected_units = Decimal(daily_target_units * window_days)
    return Decimal(rolling_7day_units) / expected_units


def calculate_trend_direction(
    rolling_windows: Sequence[int | None],
    *,
    flat_tolerance_pct: Decimal = Decimal("5.00"),
) -> TrendDirection:
    """Classify recent rolling-window movement as improving, flat, or declining."""
    values = [value for value in rolling_windows if value is not None]
    if len(values) < 2:
        return "unknown"

    first = values[0]
    last = values[-1]
    if first <= 0:
        if last > 0:
            return "improving"
        return "flat"

    movement_pct = (Decimal(last - first) / Decimal(first)) * PERCENT
    if abs(movement_pct) <= flat_tolerance_pct:
        return "flat"
    if movement_pct > ZERO:
        return "improving"
    return "declining"


def trend_adjustment_pct(trend_direction: TrendDirection) -> Decimal:
    """Return a small confidence adjustment for recent throughput direction."""
    if trend_direction == "improving":
        return Decimal("5.00")
    if trend_direction == "declining":
        return Decimal("-10.00")
    return ZERO


def calculate_confidence(
    rolling_7day_units: int | None,
    daily_target_units: int | None,
    rolling_windows: Sequence[int | None] = (),
) -> Decimal:
    """Calculate delivery confidence from recent throughput and target pace."""
    variance_ratio = calculate_variance_ratio(rolling_7day_units, daily_target_units)
    trend_direction = calculate_trend_direction(rolling_windows)
    base_score = variance_ratio * PERCENT
    return clamp_percent(base_score + trend_adjustment_pct(trend_direction))


def calculate_confidence_score(
    rolling_7day_units: int | None,
    daily_target_units: int | None,
    rolling_windows: Sequence[int | None] = (),
) -> Decimal:
    """Backward-compatible alias for the core confidence calculation."""
    return calculate_confidence(rolling_7day_units, daily_target_units, rolling_windows)


def has_sufficient_throughput_data(rolling_7day_units: int | None) -> bool:
    """Return False when a project has no throughput snapshot history at all.

    `rolling_7day_units` is None only when there are zero throughput snapshots
    (see `latest_rolling_units`), which is distinct from a low but real score —
    callers must not present a 0% confidence / red status as a health signal
    when this returns False.
    """
    return rolling_7day_units is not None


def classify_confidence_status(
    score_pct: Decimal,
    *,
    on_track_threshold: Decimal = ON_TRACK_THRESHOLD,
) -> ConfidenceStatus:
    """Map a confidence score to the delivery milestone status vocabulary."""
    return "on_track" if score_pct >= on_track_threshold else "at_risk"


def forecast_completion_date(
    *,
    as_of_date: date,
    remaining_units: int | None,
    rolling_7day_units: int | None,
) -> date | None:
    """Estimate completion date from remaining work and recent delivery pace."""
    if remaining_units is None or remaining_units <= 0:
        return as_of_date
    if rolling_7day_units is None or rolling_7day_units <= 0:
        return None

    daily_pace = Decimal(rolling_7day_units) / Decimal(7)
    days_remaining = (Decimal(remaining_units) / daily_pace).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    return as_of_date + timedelta(days=max(1, int(days_remaining)))
