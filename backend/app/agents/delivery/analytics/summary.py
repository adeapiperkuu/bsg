"""Deterministic structured delivery summary helpers.

Pure functions only: no I/O, no LLM calls, no session access. Given the same
inputs, output fields other than ``generated_at`` are identical.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from app.agents.delivery.analytics.confidence import TrendDirection, calculate_trend_direction
from app.agents.delivery.analytics.milestones import select_current_milestone
from app.agents.delivery.contracts import DeliveryTrafficLight

RiskSeverity = Literal["low", "medium", "high", "critical"]

_SEVERITY_RANK: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_HEADLINES: dict[str, str] = {
    "green": "Delivery on track",
    "yellow": "Delivery needs attention",
    "red": "Delivery at risk",
}

_ACTIVE_BOTTLENECK_STATUSES = frozenset({"open", "acknowledged"})
_COMPLETED_MILESTONE_STATUSES = frozenset({"completed"})
_OVERDUE_MILESTONE_STATUSES = frozenset({"missed", "at_risk"})


def build_structured_summary(
    *,
    as_of_date: date,
    traffic_light: DeliveryTrafficLight | str,
    confidence: Decimal | float,
    risk_score: Decimal | float,
    risk_tier: str,
    rolling_windows: Sequence[int],
    flat_tolerance_pct: Decimal,
    latest_throughput: Mapping[str, Any] | None,
    previous_throughput: Mapping[str, Any] | None,
    daily_target_units: int | None,
    milestones: Sequence[Mapping[str, Any]],
    risks: Sequence[Mapping[str, Any]],
    bottlenecks: Sequence[Mapping[str, Any]],
    has_sufficient_data: bool,
    quality_snapshot: Mapping[str, Any] | None,
    milestone_warning_window_days: int,
    stale_after_days: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a client-safe deterministic structured delivery summary."""
    status = _normalize_traffic_light(traffic_light)
    trend = calculate_trend_direction(
        list(rolling_windows),
        flat_tolerance_pct=flat_tolerance_pct,
    )
    active_bottlenecks = [
        item
        for item in bottlenecks
        if str(item.get("status", "")).lower() in _ACTIVE_BOTTLENECK_STATUSES
    ]
    overdue_milestones = _overdue_milestones(milestones, as_of_date=as_of_date)
    due_soon = _milestones_due_soon(
        milestones,
        as_of_date=as_of_date,
        warning_window_days=milestone_warning_window_days,
    )

    return {
        "status": status,
        "headline": _headline(status=status, has_sufficient_data=has_sufficient_data),
        "key_facts": _key_facts(
            confidence=confidence,
            risk_score=risk_score,
            risk_tier=risk_tier,
            trend=trend,
            latest_throughput=latest_throughput,
            daily_target_units=daily_target_units,
            milestones=milestones,
            as_of_date=as_of_date,
            open_risk_count=len(risks),
            active_bottleneck_count=len(active_bottlenecks),
            overdue_milestones=overdue_milestones,
            has_sufficient_data=has_sufficient_data,
        ),
        "risks": _risk_lines(risks),
        "delivery_changes": _delivery_changes(
            latest_throughput=latest_throughput,
            previous_throughput=previous_throughput,
            daily_target_units=daily_target_units,
            due_soon=due_soon,
            overdue_milestones=overdue_milestones,
            risks=risks,
            as_of_date=as_of_date,
            active_bottlenecks=active_bottlenecks,
        ),
        "bottleneck_summary": {
            "active_count": len(active_bottlenecks),
            "highest_severity": _highest_severity(active_bottlenecks),
        },
        "data_quality": _data_quality_warnings(
            has_sufficient_data=has_sufficient_data,
            latest_throughput=latest_throughput,
            daily_target_units=daily_target_units,
            quality_snapshot=quality_snapshot,
            as_of_date=as_of_date,
            stale_after_days=stale_after_days,
        ),
        "generated_at": generated_at or datetime.now(UTC),
    }


def _normalize_traffic_light(value: DeliveryTrafficLight | str) -> DeliveryTrafficLight:
    normalized = str(value).lower()
    if normalized not in {"green", "yellow", "red"}:
        raise ValueError(f"Unsupported traffic light value: {value!r}")
    return normalized  # type: ignore[return-value]


def _headline(*, status: DeliveryTrafficLight, has_sufficient_data: bool) -> str:
    if not has_sufficient_data:
        return "Insufficient delivery data"
    return _HEADLINES[status]


def _key_facts(
    *,
    confidence: Decimal | float,
    risk_score: Decimal | float,
    risk_tier: str,
    trend: TrendDirection,
    latest_throughput: Mapping[str, Any] | None,
    daily_target_units: int | None,
    milestones: Sequence[Mapping[str, Any]],
    as_of_date: date,
    open_risk_count: int,
    active_bottleneck_count: int,
    overdue_milestones: Sequence[Mapping[str, Any]],
    has_sufficient_data: bool,
) -> list[str]:
    facts: list[str] = [
        f"Confidence score: {_format_score(confidence)}%",
        f"Risk score: {_format_score(risk_score)} ({risk_tier})",
        f"Throughput trend: {trend}",
    ]

    if latest_throughput is not None:
        facts.append(
            "Latest throughput: "
            f"{int(latest_throughput['units_completed'])} units on "
            f"{_format_date(latest_throughput.get('snapshot_date'))}"
        )
    else:
        facts.append("Latest throughput: none")

    if daily_target_units is not None:
        facts.append(f"Daily target: {int(daily_target_units)} units")

    current = select_current_milestone(milestones, as_of_date=as_of_date)
    if current is None:
        facts.append("Current milestone: none")
    else:
        facts.append(f"Current milestone: {current['name']} ({str(current['status']).lower()})")

    facts.append(f"Active risks: {open_risk_count}")
    facts.append(f"Active bottlenecks: {active_bottleneck_count}")
    facts.append(f"Overdue milestones: {len(overdue_milestones)}")
    if not has_sufficient_data:
        facts.append("Data sufficiency: insufficient throughput history")
    return facts


def _risk_lines(risks: Sequence[Mapping[str, Any]]) -> list[str]:
    ordered = sorted(
        risks,
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("risk_tier", "")).lower(), 0),
            str(item.get("title", "")).lower(),
            str(item.get("id", "")),
        ),
    )
    return [
        f"{str(item.get('risk_tier', 'unknown')).lower()}: {item.get('title', 'Untitled risk')}"
        for item in ordered
    ]


def _delivery_changes(
    *,
    latest_throughput: Mapping[str, Any] | None,
    previous_throughput: Mapping[str, Any] | None,
    daily_target_units: int | None,
    due_soon: Sequence[Mapping[str, Any]],
    overdue_milestones: Sequence[Mapping[str, Any]],
    risks: Sequence[Mapping[str, Any]],
    as_of_date: date,
    active_bottlenecks: Sequence[Mapping[str, Any]],
) -> list[str]:
    changes: list[str] = []

    if latest_throughput is not None and previous_throughput is not None:
        delta = int(latest_throughput["units_completed"]) - int(
            previous_throughput["units_completed"]
        )
        sign = "+" if delta > 0 else ""
        changes.append(
            "Throughput change vs prior snapshot: "
            f"{sign}{delta} units "
            f"({_format_date(previous_throughput.get('snapshot_date'))} → "
            f"{_format_date(latest_throughput.get('snapshot_date'))})"
        )
    elif latest_throughput is not None:
        changes.append("Throughput change vs prior snapshot: unavailable (single snapshot)")

    if latest_throughput is not None and daily_target_units is not None and daily_target_units > 0:
        units = int(latest_throughput["units_completed"])
        variance = units - daily_target_units
        sign = "+" if variance > 0 else ""
        changes.append(
            f"Throughput vs daily target: {sign}{variance} units " f"({units}/{daily_target_units})"
        )

    for milestone in overdue_milestones:
        changes.append(
            f"Overdue milestone: {milestone['name']} "
            f"(planned {_format_date(milestone.get('planned_date'))}, "
            f"{str(milestone.get('status')).lower()})"
        )

    for milestone in due_soon:
        days = (milestone["planned_date"] - as_of_date).days
        changes.append(
            f"Milestone due soon: {milestone['name']} in {days} day(s) "
            f"({str(milestone.get('status')).lower()})"
        )

    for risk in sorted(
        risks,
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("risk_tier", "")).lower(), 0),
            str(item.get("title", "")).lower(),
        ),
    ):
        created_at = risk.get("created_at")
        if created_at is not None and _as_date(created_at) == as_of_date:
            changes.append(
                f"Risk opened today: {risk.get('title', 'Untitled risk')} "
                f"({str(risk.get('risk_tier', 'unknown')).lower()})"
            )

    for bottleneck in sorted(
        active_bottlenecks,
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("severity", "")).lower(), 0),
            str(item.get("title", "")).lower(),
        ),
    ):
        created_at = bottleneck.get("created_at")
        if created_at is not None and _as_date(created_at) == as_of_date:
            changes.append(
                f"Bottleneck opened today: {bottleneck.get('title', 'Untitled bottleneck')}"
            )

    return changes


def _data_quality_warnings(
    *,
    has_sufficient_data: bool,
    latest_throughput: Mapping[str, Any] | None,
    daily_target_units: int | None,
    quality_snapshot: Mapping[str, Any] | None,
    as_of_date: date,
    stale_after_days: int,
) -> list[str]:
    warnings: list[str] = []
    if not has_sufficient_data:
        warnings.append("missing_throughput_history")
    if daily_target_units is None or daily_target_units <= 0:
        warnings.append("missing_daily_target")
    if latest_throughput is not None:
        snapshot_date = _as_date(latest_throughput.get("snapshot_date"))
        if snapshot_date is not None and (as_of_date - snapshot_date).days > stale_after_days:
            warnings.append("stale_throughput_data")
    if quality_snapshot and quality_snapshot.get("has_drift_alert"):
        warnings.append("quality_drift_signal")
    return warnings


def _highest_severity(
    bottlenecks: Sequence[Mapping[str, Any]],
) -> RiskSeverity | None:
    if not bottlenecks:
        return None
    ranked = max(
        (
            (
                _SEVERITY_RANK.get(str(item.get("severity", "")).lower(), 0),
                str(item.get("severity", "")).lower(),
            )
            for item in bottlenecks
        ),
        key=lambda pair: pair[0],
    )
    severity = ranked[1]
    if severity not in _SEVERITY_RANK:
        return None
    return severity  # type: ignore[return-value]


def _overdue_milestones(
    milestones: Sequence[Mapping[str, Any]],
    *,
    as_of_date: date,
) -> list[Mapping[str, Any]]:
    overdue: list[Mapping[str, Any]] = []
    for milestone in milestones:
        status = str(milestone.get("status", "")).lower()
        if status in _COMPLETED_MILESTONE_STATUSES:
            continue
        planned = _as_date(milestone.get("planned_date"))
        if planned is None:
            continue
        if status in _OVERDUE_MILESTONE_STATUSES or planned < as_of_date:
            overdue.append(milestone)
    return sorted(
        overdue,
        key=lambda item: (
            _as_date(item.get("planned_date")) or date.max,
            str(item.get("name", "")).lower(),
        ),
    )


def _milestones_due_soon(
    milestones: Sequence[Mapping[str, Any]],
    *,
    as_of_date: date,
    warning_window_days: int,
) -> list[Mapping[str, Any]]:
    if warning_window_days <= 0:
        return []
    due_soon: list[Mapping[str, Any]] = []
    for milestone in milestones:
        status = str(milestone.get("status", "")).lower()
        if status in _COMPLETED_MILESTONE_STATUSES | {"missed"}:
            continue
        planned = _as_date(milestone.get("planned_date"))
        if planned is None:
            continue
        days = (planned - as_of_date).days
        if 0 <= days <= warning_window_days:
            due_soon.append(milestone)
    return sorted(
        due_soon,
        key=lambda item: (
            _as_date(item.get("planned_date")) or date.max,
            str(item.get("name", "")).lower(),
        ),
    )


def _format_score(value: Decimal | float) -> str:
    quantized = Decimal(str(value)).quantize(Decimal("0.01"))
    text = format(quantized, "f")
    if text.endswith(".00"):
        return text[:-3]
    return text.rstrip("0").rstrip(".") if "." in text else text


def _format_date(value: Any) -> str:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed is not None else "unknown"


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])
