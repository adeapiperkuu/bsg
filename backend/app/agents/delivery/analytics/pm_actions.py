"""Pure PM daily action ranking from deterministic Delivery evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from app.agents.delivery.analytics.root_cause import FACTOR_LABELS, ZERO, quantize_pct

MODEL_VERSION = "pm_daily_action_v1"
Urgency = Literal["low", "medium", "high", "critical"]
SourceType = Literal["root_cause_factor", "risk_alert", "bottleneck", "mitigation", "milestone"]

ROOT_CAUSE_ACTIONS: dict[str, tuple[str, str]] = {
    "review_turnaround": (
        "Clear review backlog today",
        "Reduce pending reviews and turnaround time that are driving confidence loss.",
    ),
    "rework": (
        "Contain rework spike",
        "Pause high-rework streams and trigger a focused quality check before more volume lands.",
    ),
    "capacity": (
        "Restore delivery capacity",
        "Close the planned-vs-available gap and reallocate headcount to the critical path.",
    ),
    "absenteeism": (
        "Cover absenteeism shortfall",
        "Confirm coverage for absent FTE and protect milestone-critical workstreams.",
    ),
    "queue": (
        "Drain aging backlog",
        "Pull aging items forward and cap new intake until congestion eases.",
    ),
    "blocked_work": (
        "Unblock aging work",
        "Assign owners to each active blocker and run a same-day stand-down.",
    ),
    "dependency_delays": (
        "Escalate blocked dependencies",
        "Chase external/internal dependency owners with a same-day response deadline.",
    ),
    "milestone_slippage": (
        "Protect at-risk milestone",
        "Re-sequence work to the next milestone date and communicate trade-offs.",
    ),
    "quality_regression": (
        "Arrest quality regression",
        "Tighten review gates and run a targeted gold-set/calibration pass.",
    ),
    "scope_volatility": (
        "Freeze volatile scope",
        "Lock change intake for today and re-baseline only approved delta.",
    ),
}

URGENCY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass(frozen=True, slots=True)
class PlannedActionCandidate:
    source_type: SourceType
    source_key: str
    title: str
    description: str
    deterministic_rationale: str
    urgency: Urgency
    estimated_impact_points: Decimal
    due_date: date
    root_cause_factor: str | None
    mitigation_recommendation_id: str | None
    evidence_json: dict[str, Any]
    score: Decimal


def urgency_from_impact(impact_points: Decimal, *, severity: str | None = None) -> Urgency:
    abs_impact = abs(impact_points)
    if severity in {"critical"} or abs_impact >= Decimal("10"):
        return "critical"
    if severity in {"high"} or abs_impact >= Decimal("6"):
        return "high"
    if severity in {"medium"} or abs_impact >= Decimal("3"):
        return "medium"
    return "low"


def due_date_for_urgency(plan_date: date, urgency: Urgency) -> date:
    if urgency == "critical":
        return plan_date
    if urgency == "high":
        return plan_date + timedelta(days=1)
    if urgency == "medium":
        return plan_date + timedelta(days=3)
    return plan_date + timedelta(days=5)


def build_candidates_from_root_causes(
    *,
    plan_date: date,
    factors: list[dict[str, Any]],
) -> list[PlannedActionCandidate]:
    candidates: list[PlannedActionCandidate] = []
    for factor in factors:
        impact_pct = Decimal(str(factor.get("impact_percent") or 0))
        impact_pts = abs(Decimal(str(factor.get("impact_points") or 0)))
        if impact_pct <= ZERO and impact_pts <= ZERO:
            continue
        key = str(factor.get("factor") or "")
        if not key:
            continue
        title, description = ROOT_CAUSE_ACTIONS.get(
            key,
            (
                f"Address {FACTOR_LABELS.get(key, key)}",
                factor.get("explanation") or "Act on the top confidence-loss contributor.",
            ),
        )
        urgency = urgency_from_impact(impact_pts, severity=str(factor.get("severity") or ""))
        rationale = (
            f"{FACTOR_LABELS.get(key, key)} contributes {quantize_pct(impact_pct)}% of today's "
            f"confidence loss ({quantize_pct(impact_pts)} pts). "
            f"{factor.get('explanation') or ''}".strip()
        )
        score = impact_pts * Decimal("10") + (Decimal("40") - Decimal(URGENCY_RANK[urgency]) * 10)
        candidates.append(
            PlannedActionCandidate(
                source_type="root_cause_factor",
                source_key=f"root_cause:{key}",
                title=title,
                description=description,
                deterministic_rationale=rationale,
                urgency=urgency,
                estimated_impact_points=quantize_pct(impact_pts),
                due_date=due_date_for_urgency(plan_date, urgency),
                root_cause_factor=key,
                mitigation_recommendation_id=None,
                evidence_json={
                    "factor": key,
                    "impact_percent": float(quantize_pct(impact_pct)),
                    "impact_points": float(quantize_pct(impact_pts)),
                    "severity": factor.get("severity"),
                    "evidence": factor.get("evidence_json") or {},
                },
                score=score,
            )
        )
    return candidates


def build_candidates_from_bottlenecks(
    *,
    plan_date: date,
    bottlenecks: list[dict[str, Any]],
) -> list[PlannedActionCandidate]:
    candidates: list[PlannedActionCandidate] = []
    for item in bottlenecks:
        bid = str(item.get("id") or item.get("source_key") or "")
        if not bid:
            continue
        severity = str(item.get("severity") or "medium")
        urgency = urgency_from_impact(
            Decimal("8") if severity in {"critical", "high"} else Decimal("3"),
            severity=severity,
        )
        impact = Decimal("8.00") if urgency in {"critical", "high"} else Decimal("3.00")
        title = f"Resolve bottleneck: {item.get('title') or 'Untitled'}"
        rationale = (
            f"Active {severity} bottleneck remains open"
            + (f": {item.get('detail')}" if item.get("detail") else ".")
        )
        score = impact * Decimal("8") + (Decimal("30") - Decimal(URGENCY_RANK[urgency]) * 8)
        candidates.append(
            PlannedActionCandidate(
                source_type="bottleneck",
                source_key=f"bottleneck:{bid}",
                title=title[:300],
                description="Assign an owner and clear the blocker before end of due date.",
                deterministic_rationale=rationale[:4000],
                urgency=urgency,
                estimated_impact_points=impact,
                due_date=due_date_for_urgency(plan_date, urgency),
                root_cause_factor="blocked_work",
                mitigation_recommendation_id=None,
                evidence_json={
                    "bottleneck_id": bid,
                    "severity": severity,
                    "title": item.get("title"),
                },
                score=score,
            )
        )
    return candidates


def build_candidates_from_mitigations(
    *,
    plan_date: date,
    mitigations: list[dict[str, Any]],
) -> list[PlannedActionCandidate]:
    candidates: list[PlannedActionCandidate] = []
    for item in mitigations:
        mid = str(item.get("id") or "")
        if not mid:
            continue
        severity = str(item.get("severity") or "medium")
        urgency = urgency_from_impact(
            Decimal("7") if severity == "high" else Decimal("3"),
            severity="high" if severity == "high" else "medium",
        )
        impact = Decimal("7.00") if severity == "high" else Decimal("3.00")
        title = f"Advance mitigation: {item.get('title') or 'Untitled'}"
        rationale = (
            "Pending mitigation recommendation is still open and ranked for today's focus."
        )
        score = impact * Decimal("7") + (Decimal("25") - Decimal(URGENCY_RANK[urgency]) * 7)
        candidates.append(
            PlannedActionCandidate(
                source_type="mitigation",
                source_key=f"mitigation:{mid}",
                title=title[:300],
                description=str(item.get("description") or "Execute the accepted mitigation path.")[
                    :4000
                ],
                deterministic_rationale=rationale,
                urgency=urgency,
                estimated_impact_points=impact,
                due_date=due_date_for_urgency(plan_date, urgency),
                root_cause_factor=None,
                mitigation_recommendation_id=mid,
                evidence_json={
                    "mitigation_recommendation_id": mid,
                    "severity": severity,
                    "status": item.get("status"),
                },
                score=score,
            )
        )
    return candidates


def build_candidates_from_milestones(
    *,
    plan_date: date,
    overdue_count: int,
    days_until_milestone: int | None,
) -> list[PlannedActionCandidate]:
    if overdue_count <= 0 and (days_until_milestone is None or days_until_milestone > 7):
        return []
    urgency: Urgency = "critical" if overdue_count > 0 or (
        days_until_milestone is not None and days_until_milestone < 0
    ) else "high"
    impact = Decimal("9.00") if urgency == "critical" else Decimal("5.00")
    rationale = (
        f"{overdue_count} overdue milestone(s)"
        if overdue_count > 0
        else f"Current milestone is {days_until_milestone} day(s) away."
    )
    return [
        PlannedActionCandidate(
            source_type="milestone",
            source_key="milestone:current",
            title="Protect milestone date",
            description="Confirm critical-path owners and remove non-essential work for today.",
            deterministic_rationale=rationale,
            urgency=urgency,
            estimated_impact_points=impact,
            due_date=due_date_for_urgency(plan_date, urgency),
            root_cause_factor="milestone_slippage",
            mitigation_recommendation_id=None,
            evidence_json={
                "overdue_count": overdue_count,
                "days_until_milestone": days_until_milestone,
            },
            score=impact * Decimal("9") + Decimal("35"),
        )
    ]


def rank_daily_actions(
    candidates: list[PlannedActionCandidate],
    *,
    limit: int = 8,
) -> list[PlannedActionCandidate]:
    """Deduplicate by source_key and return priority-ranked actions."""
    best: dict[str, PlannedActionCandidate] = {}
    for candidate in candidates:
        existing = best.get(candidate.source_key)
        if existing is None or candidate.score > existing.score:
            best[candidate.source_key] = candidate
    ranked = sorted(
        best.values(),
        key=lambda item: (URGENCY_RANK[item.urgency], -item.score, item.title),
    )
    return ranked[: max(1, limit)]
