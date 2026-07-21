"""Deterministic PM daily operational briefing sections.

Pure functions only: no I/O, no LLM. AI may restate these facts but must not invent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from app.agents.delivery.contracts import DeliveryTrafficLight

ConfidenceDirection = Literal["up", "down", "flat", "insufficient_data"]

_ACTIVE = frozenset({"open", "acknowledged"})
_COMPLETED = frozenset({"completed"})
_OVERDUE = frozenset({"missed", "at_risk"})
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
MODEL_VERSION = "operational_briefing_v1"


def build_operational_briefing(
    *,
    as_of_date: date,
    traffic_light: DeliveryTrafficLight | str,
    confidence: float,
    previous_confidence: float | None,
    has_sufficient_data: bool,
    latest_throughput: Mapping[str, Any] | None,
    previous_throughput: Mapping[str, Any] | None,
    daily_target_units: int | None,
    milestones: Sequence[Mapping[str, Any]],
    risks: Sequence[Mapping[str, Any]],
    bottlenecks: Sequence[Mapping[str, Any]],
    root_cause_summary: Mapping[str, Any] | None,
    pm_actions: Sequence[Mapping[str, Any]],
    milestone_warning_window_days: int,
    overnight_lookback_days: int = 1,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble grounded briefing sections from Delivery + root-cause + PM actions."""
    status = _normalize_light(traffic_light)
    overnight_since = as_of_date - timedelta(days=max(0, overnight_lookback_days))
    overnight = _overnight_changes(
        as_of_date=as_of_date,
        overnight_since=overnight_since,
        latest_throughput=latest_throughput,
        previous_throughput=previous_throughput,
        daily_target_units=daily_target_units,
        risks=risks,
        bottlenecks=bottlenecks,
    )
    movement = _confidence_movement(
        confidence=confidence,
        previous_confidence=previous_confidence,
        has_sufficient_data=has_sufficient_data,
        root_cause_summary=root_cause_summary,
    )
    new_risks = _new_risks(risks, overnight_since=overnight_since, as_of_date=as_of_date)
    priorities = _top_priorities(
        root_cause_summary=root_cause_summary,
        bottlenecks=bottlenecks,
        risks=risks,
    )
    due_soon = _milestones_due_soon(
        milestones,
        as_of_date=as_of_date,
        warning_window_days=milestone_warning_window_days,
    )
    recommended = _recommended_actions(pm_actions)
    narrative = _deterministic_narrative(
        status=status,
        confidence=confidence,
        has_sufficient_data=has_sufficient_data,
        overnight=overnight,
        movement=movement,
        new_risks=new_risks,
        priorities=priorities,
        due_soon=due_soon,
        recommended=recommended,
    )
    return {
        "as_of": as_of_date.isoformat(),
        "traffic_light": status,
        "headline": _headline(status=status, has_sufficient_data=has_sufficient_data),
        "overnight_changes": overnight,
        "confidence_movement": movement,
        "new_risks": new_risks,
        "top_priorities": priorities,
        "milestones_due_soon": due_soon,
        "recommended_pm_actions": recommended,
        "root_cause_summary": dict(root_cause_summary) if root_cause_summary else None,
        "narrative": narrative,
        "ai_generated": False,
        "model_version": MODEL_VERSION,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
    }


def _normalize_light(value: DeliveryTrafficLight | str) -> str:
    raw = str(value).lower()
    if raw in {"green", "yellow", "red"}:
        return raw
    return "yellow"


def _headline(*, status: str, has_sufficient_data: bool) -> str:
    if not has_sufficient_data:
        return "Insufficient delivery activity to brief"
    return {
        "green": "Delivery on track — morning briefing",
        "yellow": "Delivery needs attention — morning briefing",
        "red": "Delivery at risk — morning briefing",
    }.get(status, "Morning operational briefing")


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _overnight_changes(
    *,
    as_of_date: date,
    overnight_since: date,
    latest_throughput: Mapping[str, Any] | None,
    previous_throughput: Mapping[str, Any] | None,
    daily_target_units: int | None,
    risks: Sequence[Mapping[str, Any]],
    bottlenecks: Sequence[Mapping[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if latest_throughput is not None and previous_throughput is not None:
        delta = int(latest_throughput["units_completed"]) - int(
            previous_throughput["units_completed"]
        )
        sign = "+" if delta > 0 else ""
        lines.append(
            f"Throughput changed {sign}{delta} units vs prior snapshot "
            f"({_fmt_date(previous_throughput.get('snapshot_date'))} → "
            f"{_fmt_date(latest_throughput.get('snapshot_date'))})"
        )
    elif latest_throughput is not None:
        lines.append(
            f"Latest throughput {int(latest_throughput['units_completed'])} units "
            f"on {_fmt_date(latest_throughput.get('snapshot_date'))} "
            "(no prior snapshot for overnight delta)"
        )

    if latest_throughput is not None and daily_target_units and daily_target_units > 0:
        units = int(latest_throughput["units_completed"])
        variance = units - daily_target_units
        sign = "+" if variance > 0 else ""
        lines.append(
            f"Throughput vs daily target: {sign}{variance} units "
            f"({units}/{daily_target_units})"
        )

    for risk in _sorted_risks(risks):
        created = _as_date(risk.get("created_at"))
        if created is not None and overnight_since <= created <= as_of_date:
            lines.append(
                f"Risk opened: {risk.get('title', 'Untitled')} "
                f"({str(risk.get('risk_tier', 'unknown')).lower()})"
            )

    for bottleneck in _sorted_bottlenecks(bottlenecks):
        if str(bottleneck.get("status", "")).lower() not in _ACTIVE:
            continue
        created = _as_date(bottleneck.get("created_at"))
        if created is not None and overnight_since <= created <= as_of_date:
            lines.append(
                f"Bottleneck opened: {bottleneck.get('title', 'Untitled')} "
                f"({str(bottleneck.get('severity') or 'medium').lower()})"
            )

    return lines


def _confidence_movement(
    *,
    confidence: float,
    previous_confidence: float | None,
    has_sufficient_data: bool,
    root_cause_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    drivers: list[str] = []
    if root_cause_summary:
        loss = root_cause_summary.get("confidence_loss")
        if loss is not None:
            drivers.append(f"Confidence loss vs on-track threshold: {float(loss):.1f} pts")
        for cause in list(root_cause_summary.get("top_causes") or [])[:3]:
            if not isinstance(cause, Mapping):
                continue
            label = cause.get("label") or cause.get("factor") or "Unknown cause"
            impact = cause.get("impact_percent")
            explanation = cause.get("explanation")
            if impact is not None:
                line = f"{label}: {float(impact):.1f}% of loss"
            else:
                line = str(label)
            if explanation:
                line = f"{line} — {explanation}"
            drivers.append(line)

    if not has_sufficient_data:
        return {
            "current": float(confidence),
            "previous": previous_confidence,
            "delta": None,
            "direction": "insufficient_data",
            "drivers": drivers,
        }

    if previous_confidence is None:
        return {
            "current": float(confidence),
            "previous": None,
            "delta": None,
            "direction": "insufficient_data",
            "drivers": drivers,
        }

    delta = float(confidence) - float(previous_confidence)
    if abs(delta) <= 1.0:
        direction: ConfidenceDirection = "flat"
    else:
        direction = "up" if delta > 0 else "down"
    return {
        "current": float(confidence),
        "previous": float(previous_confidence),
        "delta": round(delta, 2),
        "direction": direction,
        "drivers": drivers,
    }


def _new_risks(
    risks: Sequence[Mapping[str, Any]],
    *,
    overnight_since: date,
    as_of_date: date,
) -> list[str]:
    lines: list[str] = []
    for risk in _sorted_risks(risks):
        status = str(risk.get("status", "")).lower()
        if status not in _ACTIVE:
            continue
        created = _as_date(risk.get("created_at"))
        if created is None or not (overnight_since <= created <= as_of_date):
            continue
        lines.append(
            f"{str(risk.get('risk_tier', 'unknown')).lower()}: "
            f"{risk.get('title', 'Untitled risk')}"
        )
    return lines


def _top_priorities(
    *,
    root_cause_summary: Mapping[str, Any] | None,
    bottlenecks: Sequence[Mapping[str, Any]],
    risks: Sequence[Mapping[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if root_cause_summary:
        for cause in list(root_cause_summary.get("top_causes") or [])[:3]:
            if not isinstance(cause, Mapping):
                continue
            label = cause.get("label") or cause.get("factor") or "Root cause"
            impact = cause.get("impact_percent")
            if impact is not None:
                lines.append(f"Address {label} ({float(impact):.1f}% of confidence loss)")
            else:
                lines.append(f"Address {label}")

    for bottleneck in _sorted_bottlenecks(bottlenecks)[:2]:
        if str(bottleneck.get("status", "")).lower() not in _ACTIVE:
            continue
        lines.append(
            f"Clear bottleneck: {bottleneck.get('title', 'Untitled')} "
            f"({str(bottleneck.get('severity') or 'medium').lower()})"
        )

    if not lines:
        for risk in _sorted_risks(risks)[:2]:
            if str(risk.get("status", "")).lower() not in _ACTIVE:
                continue
            lines.append(
                f"Mitigate risk: {risk.get('title', 'Untitled')} "
                f"({str(risk.get('risk_tier', 'unknown')).lower()})"
            )
    return lines[:5]


def _milestones_due_soon(
    milestones: Sequence[Mapping[str, Any]],
    *,
    as_of_date: date,
    warning_window_days: int,
) -> list[str]:
    if warning_window_days <= 0:
        return []
    lines: list[str] = []
    rows: list[tuple[date, str]] = []
    for milestone in milestones:
        status = str(milestone.get("status", "")).lower()
        if status in _COMPLETED | {"missed"}:
            continue
        planned = _as_date(milestone.get("planned_date"))
        if planned is None:
            continue
        days = (planned - as_of_date).days
        if days < 0 or status in _OVERDUE:
            rows.append(
                (
                    planned,
                    f"Overdue: {milestone.get('name', 'Milestone')} "
                    f"(planned {_fmt_date(planned)}, {status})",
                )
            )
        elif days <= warning_window_days:
            rows.append(
                (
                    planned,
                    f"{milestone.get('name', 'Milestone')} due in {days} day(s) "
                    f"({status})",
                )
            )
    rows.sort(key=lambda item: (item[0], item[1].lower()))
    for _, line in rows:
        lines.append(line)
    return lines


def _recommended_actions(pm_actions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    recommended: list[dict[str, Any]] = []
    for action in pm_actions:
        status = str(action.get("status", "todo")).lower()
        if status != "todo":
            continue
        recommended.append(
            {
                "rank": int(action.get("rank") or len(recommended) + 1),
                "title": str(action.get("title") or "Untitled action"),
                "urgency": str(action.get("urgency") or "medium"),
                "estimated_impact_points": float(action.get("estimated_impact_points") or 0),
                "due_date": str(action.get("due_date") or ""),
                "rationale": str(
                    action.get("ai_rationale")
                    or action.get("deterministic_rationale")
                    or ""
                ),
                "root_cause_factor": action.get("root_cause_factor"),
            }
        )
        if len(recommended) >= 5:
            break
    return recommended


def _deterministic_narrative(
    *,
    status: str,
    confidence: float,
    has_sufficient_data: bool,
    overnight: Sequence[str],
    movement: Mapping[str, Any],
    new_risks: Sequence[str],
    priorities: Sequence[str],
    due_soon: Sequence[str],
    recommended: Sequence[Mapping[str, Any]],
) -> str:
    if not has_sufficient_data:
        return (
            "Insufficient delivery activity to summarize. "
            "Add throughput history, then refresh root causes and today's plan."
        )
    parts = [
        f"Status is {status} at {confidence:.0f}% schedule confidence.",
    ]
    direction = movement.get("direction")
    if direction in {"up", "down", "flat"} and movement.get("previous") is not None:
        delta = movement.get("delta")
        sign = "+" if isinstance(delta, (int, float)) and delta > 0 else ""
        parts.append(
            f"Confidence is {direction} "
            f"({movement['previous']:.0f}% → {movement['current']:.0f}%"
            f"{f', {sign}{delta}' if delta is not None else ''})."
        )
    drivers = list(movement.get("drivers") or [])
    if drivers:
        parts.append(f"Primary drivers: {drivers[0]}")
    if overnight:
        parts.append(f"Overnight: {overnight[0]}")
    if new_risks:
        parts.append(f"New risk: {new_risks[0]}")
    if priorities:
        parts.append(f"Top priority: {priorities[0]}")
    if due_soon:
        parts.append(f"Milestone pressure: {due_soon[0]}")
    if recommended:
        parts.append(f"Recommended PM action: {recommended[0].get('title')}")
    return " ".join(parts)


def _sorted_risks(risks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        risks,
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("risk_tier", "")).lower(), 0),
            str(item.get("title", "")).lower(),
        ),
    )


def _sorted_bottlenecks(bottlenecks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        bottlenecks,
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("severity", "")).lower(), 0),
            str(item.get("title", "")).lower(),
        ),
    )


def _fmt_date(value: Any) -> str:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else "unknown"
