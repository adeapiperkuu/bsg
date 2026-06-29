"""Pure milestone selection helpers for the Delivery Performance Agent."""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from app.agents.delivery.analytics.confidence import ON_TRACK_THRESHOLD

MilestoneLifecycleStatus = Literal["pending", "on_track", "at_risk", "completed", "missed"]


def select_current_milestone(
    milestones: Sequence[Mapping[str, object]],
    *,
    as_of_date: date,
) -> Mapping[str, object] | None:
    """Return the active milestone used for delivery risk and status scoring."""
    active = [
        milestone
        for milestone in milestones
        if milestone.get("actual_date") is None and milestone.get("status") != "completed"
    ]
    if not active:
        return milestones[-1] if milestones else None

    upcoming = [
        milestone
        for milestone in active
        if milestone["planned_date"] >= as_of_date
    ]
    if upcoming:
        return min(upcoming, key=lambda milestone: milestone["planned_date"])
    return max(active, key=lambda milestone: milestone["planned_date"])


def resolve_milestone_status(
    *,
    current_status: str,
    planned_date: date,
    actual_date: date | None,
    as_of_date: date,
    confidence_score_pct: Decimal,
    on_track_threshold: Decimal = ON_TRACK_THRESHOLD,
) -> MilestoneLifecycleStatus:
    """Derive the next milestone lifecycle status from delivery analytics outputs."""
    normalized_status = current_status.lower()

    if actual_date is not None:
        return "missed" if actual_date > planned_date else "completed"

    if normalized_status == "completed":
        return "completed"

    if as_of_date > planned_date:
        return "missed"

    if confidence_score_pct >= on_track_threshold:
        return "on_track"

    return "at_risk"
