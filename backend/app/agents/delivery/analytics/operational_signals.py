"""Pure severity derivation from Phase 15.2 operational snapshots."""

from __future__ import annotations

from decimal import Decimal

from app.agents.delivery.analytics.root_cause import ZERO, clamp_pct, quantize_pct

PERCENT = Decimal("100")


def timesheet_underfill_severity(
    *,
    hours_logged: Decimal,
    expected_hours: Decimal | None,
) -> Decimal | None:
    """Return 0-100 severity when expected hours are known and underfilled."""
    if expected_hours is None or expected_hours <= ZERO:
        return None
    if hours_logged >= expected_hours:
        return ZERO
    underfill = (expected_hours - hours_logged) / expected_hours * PERCENT
    return clamp_pct(underfill)


def absenteeism_severity(*, absence_rate_pct: Decimal) -> Decimal:
    """Map absence rate into 0-100 severity (2× rate, capped)."""
    return clamp_pct(max(ZERO, absence_rate_pct) * Decimal("2"))


def review_queue_severity(
    *,
    pending_count: int,
    avg_turnaround_hours: Decimal,
    sla_breach_count: int = 0,
    target_turnaround_hours: Decimal = Decimal("24"),
) -> Decimal:
    """Combine pending volume, turnaround, and SLA breaches."""
    pending_part = min(Decimal("40"), Decimal(max(0, pending_count)) * Decimal("4"))
    if target_turnaround_hours <= ZERO:
        turnaround_part = ZERO
    else:
        ratio = avg_turnaround_hours / target_turnaround_hours
        turnaround_part = min(Decimal("40"), max(ZERO, (ratio - Decimal("1")) * Decimal("40")))
    sla_part = min(Decimal("20"), Decimal(max(0, sla_breach_count)) * Decimal("5"))
    return clamp_pct(pending_part + turnaround_part + sla_part)


def backlog_queue_severity(
    *,
    item_count: int,
    aging_item_count: int,
    oldest_item_age_days: int,
) -> Decimal:
    """Combine backlog size, aging share, and oldest age."""
    size_part = min(Decimal("35"), Decimal(max(0, item_count)) * Decimal("0.5"))
    aging_part = min(Decimal("40"), Decimal(max(0, aging_item_count)) * Decimal("4"))
    age_part = min(Decimal("25"), Decimal(max(0, oldest_item_age_days)) * Decimal("0.5"))
    return clamp_pct(size_part + aging_part + age_part)


def capacity_shortage_severity(
    *,
    planned_capacity_hours: Decimal,
    available_capacity_hours: Decimal,
) -> Decimal | None:
    """Shortage as percent of planned capacity."""
    if planned_capacity_hours <= ZERO:
        return None
    shortage = planned_capacity_hours - available_capacity_hours
    if shortage <= ZERO:
        return ZERO
    return clamp_pct(shortage / planned_capacity_hours * PERCENT)


def team_availability_severity(
    *,
    available_headcount: int,
    planned_headcount: int,
) -> Decimal | None:
    """Unavailability as percent of planned headcount."""
    if planned_headcount <= 0:
        return None
    missing = planned_headcount - available_headcount
    if missing <= 0:
        return ZERO
    return clamp_pct(Decimal(missing) / Decimal(planned_headcount) * PERCENT)


def combine_max(*values: Decimal | None) -> Decimal | None:
    """Return the strongest available severity, or None if all missing."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    return quantize_pct(max(present))
