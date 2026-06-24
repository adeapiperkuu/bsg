"""Pure throughput window and trend helpers for the Delivery Performance Agent."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP

from app.agents.delivery.analytics.confidence import PERCENT, ZERO

DEFAULT_ROLLING_WINDOW_DAYS = 7
DEFAULT_ROLLING_HISTORY_COUNT = 3


def sum_recent_units_completed(units_completed_values: Sequence[int]) -> int | None:
    """Return the sum of caller-bounded daily throughput values."""
    if not units_completed_values:
        return None
    return sum(units_completed_values)


def rolling_windows_from_snapshots(
    snapshots: Sequence[Mapping[str, object]],
    *,
    window_days: int = DEFAULT_ROLLING_WINDOW_DAYS,
    history_count: int = DEFAULT_ROLLING_HISTORY_COUNT,
) -> list[int]:
    """Build recent rolling-window totals from descending throughput snapshots."""
    snapshots_asc = list(reversed(snapshots))
    windows: list[int] = []
    for index, snapshot in enumerate(snapshots_asc):
        rolling_7day_units = snapshot.get("rolling_7day_units")
        if rolling_7day_units is not None:
            windows.append(int(rolling_7day_units))
            continue

        window = snapshots_asc[max(0, index - (window_days - 1)) : index + 1]
        windows.append(
            sum(int(item["units_completed"]) for item in window)
        )

    return windows[-history_count:]


def latest_rolling_units(
    snapshots: Sequence[Mapping[str, object]],
    *,
    window_days: int = DEFAULT_ROLLING_WINDOW_DAYS,
) -> int | None:
    """Return the latest rolling throughput total for confidence scoring."""
    if not snapshots:
        return None

    latest = snapshots[0]
    rolling_7day_units = latest.get("rolling_7day_units")
    if rolling_7day_units is not None:
        return int(rolling_7day_units)

    return sum(
        int(snapshot["units_completed"])
        for snapshot in snapshots[:window_days]
    )


def throughput_decline_pct(windows: Sequence[int]) -> Decimal:
    """Measure percentage decline between the last two rolling windows."""
    if len(windows) < 2:
        return ZERO

    previous = windows[-2]
    current = windows[-1]
    if previous <= 0 or current >= previous:
        return ZERO

    return (
        (Decimal(previous - current) / Decimal(previous)) * PERCENT
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
