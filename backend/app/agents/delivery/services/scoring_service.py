"""Compose deterministic delivery analytics into dashboard output."""

from datetime import date
from decimal import Decimal
from typing import Any

from app.agents.delivery.analytics.confidence import (
    calculate_confidence as analytics_calculate_confidence,
)
from app.agents.delivery.analytics.risk import (
    build_contributing_causes,
    calculate_risk as analytics_calculate_risk,
    classify_risk_tier,
)
from app.agents.delivery.analytics.status import calculate_status as analytics_calculate_status

CONFIDENCE_THRESHOLD = Decimal("80.00")
WARNING_WINDOW_DAYS = 14


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value))


def _rolling_windows(snapshots: list[dict[str, Any]]) -> list[int]:
    snapshots_asc = list(reversed(snapshots))
    windows: list[int] = []
    for index, snapshot in enumerate(snapshots_asc):
        rolling_7day_units = snapshot.get("rolling_7day_units")
        if rolling_7day_units is not None:
            windows.append(int(rolling_7day_units))
            continue

        window = snapshots_asc[max(0, index - 6) : index + 1]
        windows.append(sum(int(item["units_completed"]) for item in window))

    return windows[-3:]


def _latest_rolling_units(snapshots: list[dict[str, Any]]) -> int | None:
    if not snapshots:
        return None
    latest = snapshots[0]
    if latest.get("rolling_7day_units") is not None:
        return int(latest["rolling_7day_units"])
    return sum(int(snapshot["units_completed"]) for snapshot in snapshots[:7])


def _throughput_decline_pct(windows: list[int]) -> Decimal:
    if len(windows) < 2:
        return Decimal("0.00")

    previous = windows[-2]
    current = windows[-1]
    if previous <= 0 or current >= previous:
        return Decimal("0.00")

    return ((Decimal(previous - current) / Decimal(previous)) * Decimal("100")).quantize(
        Decimal("0.01")
    )


def _current_milestone(
    milestones: list[dict[str, Any]],
    *,
    as_of_date: date,
) -> dict[str, Any] | None:
    active = [
        milestone
        for milestone in milestones
        if milestone.get("actual_date") is None and milestone.get("status") != "completed"
    ]
    if not active:
        return milestones[-1] if milestones else None

    upcoming = [milestone for milestone in active if milestone["planned_date"] >= as_of_date]
    if upcoming:
        return min(upcoming, key=lambda milestone: milestone["planned_date"])
    return max(active, key=lambda milestone: milestone["planned_date"])


def calculate_confidence(raw_data: dict[str, Any]) -> Decimal:
    """Calculate confidence from aggregated raw delivery data."""
    snapshots = raw_data["throughput_snapshots"]
    return analytics_calculate_confidence(
        rolling_7day_units=_latest_rolling_units(snapshots),
        daily_target_units=raw_data["project"].get("daily_target_units"),
        rolling_windows=_rolling_windows(snapshots),
    )


def calculate_risk(raw_data: dict[str, Any], confidence: Decimal) -> Decimal:
    """Calculate delivery risk from aggregated raw delivery data."""
    snapshots = raw_data["throughput_snapshots"]
    milestones = raw_data["milestones"]
    current_milestone = _current_milestone(milestones, as_of_date=raw_data["as_of_date"])
    days_until_milestone = (
        (current_milestone["planned_date"] - raw_data["as_of_date"]).days
        if current_milestone is not None
        else None
    )
    throughput_decline_pct = _throughput_decline_pct(_rolling_windows(snapshots))
    quality_snapshot = raw_data.get("quality_snapshot")

    return analytics_calculate_risk(
        confidence_score_pct=confidence,
        throughput_decline_pct=throughput_decline_pct,
        is_throughput_declining=throughput_decline_pct > Decimal("0.00"),
        days_until_milestone=days_until_milestone,
        open_bottleneck_count=len(raw_data["bottlenecks"]),
        has_quality_drift=bool(quality_snapshot and quality_snapshot.get("has_drift_alert")),
        rework_rate_pct=quality_snapshot.get("rework_rate_pct") if quality_snapshot else None,
        on_track_threshold=CONFIDENCE_THRESHOLD,
        warning_window_days=WARNING_WINDOW_DAYS,
    )


def calculate_status(raw_data: dict[str, Any], confidence: Decimal, risk: Decimal) -> str:
    """Calculate traffic-light status from deterministic analytics outputs."""
    current_milestone = _current_milestone(raw_data["milestones"], as_of_date=raw_data["as_of_date"])
    return analytics_calculate_status(
        confidence=confidence,
        risk_score=risk,
        open_bottleneck_count=len(raw_data["bottlenecks"]),
        milestone_status=current_milestone.get("status") if current_milestone else None,
        open_risk_tiers=[risk_item["risk_tier"] for risk_item in raw_data["risks"]],
    )


def build_dashboard_response(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Prepare the final deterministic dashboard payload."""
    confidence = calculate_confidence(raw_data)
    risk = calculate_risk(raw_data, confidence)
    traffic_light = calculate_status(raw_data, confidence, risk)
    latest_snapshot = raw_data["throughput_snapshots"][0] if raw_data["throughput_snapshots"] else None
    current_milestone = _current_milestone(raw_data["milestones"], as_of_date=raw_data["as_of_date"])
    risk_tier = classify_risk_tier(risk)

    overview = {
        "project": raw_data["project"],
        "latest_throughput": latest_snapshot,
        "current_milestone": current_milestone,
        "open_risk_count": len(raw_data["risks"]),
        "open_bottleneck_count": len(raw_data["bottlenecks"]),
        "calculated_risk": {
            "score": float(risk),
            "tier": risk_tier,
            "contributing_causes": build_contributing_causes(
                confidence_score_pct=confidence,
                throughput_decline_pct=_throughput_decline_pct(
                    _rolling_windows(raw_data["throughput_snapshots"])
                ),
                is_throughput_declining=_throughput_decline_pct(
                    _rolling_windows(raw_data["throughput_snapshots"])
                )
                > Decimal("0.00"),
                days_until_milestone=(
                    (current_milestone["planned_date"] - raw_data["as_of_date"]).days
                    if current_milestone
                    else None
                ),
                open_bottleneck_count=len(raw_data["bottlenecks"]),
            ),
        },
    }

    return {
        "overview": overview,
        "milestones": raw_data["milestones"],
        "confidence": float(confidence),
        "risks": raw_data["risks"],
        "bottlenecks": raw_data["bottlenecks"],
        "traffic_light": traffic_light,
        "daily_summary": None,
    }
