"""Aggregated data provider for the Operational Tower dashboard.

Assembles every deterministic section of the dashboard in a single request using
batched, index-friendly queries (no N+1 fan-out). The AI-authored executive summary
is served separately (get_executive_summary) so the dashboard never blocks on — or
regenerates — an LLM call during load.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.dashboard_service import get_portfolio_data
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    DeliveryConfidenceScore,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceSummaryStatus,
    GovernanceWeeklySummary,
    Milestone,
    MilestoneStatus,
    MitigationRecommendation,
    Notification,
    Project,
    ProjectStatus,
    QualitySnapshot,
    RiskAlert,
    RiskTier,
    Team,
    UtilizationSnapshot,
)
from app.services.scoping import scoped_project_query

# Health / traffic-light palette — kept identical to the dashboard's existing colors.
_HEALTH_META = {
    "green": ("On Track", "#22c55e"),
    "yellow": ("At Risk", "#f59e0b"),
    "red": ("Critical", "#ef4444"),
}
_INSUFFICIENT_META = ("Insufficient Data", "#6b7280")
_INFLIGHT_STATUSES = frozenset({ProjectStatus.ACTIVE, ProjectStatus.RAMPING})
_RISK_TREND_COLORS = ["#22c55e", "#f59e0b", "#ef4444", "#3b82f6"]

_TIER_RANK = {
    RiskTier.CRITICAL: 0,
    RiskTier.HIGH: 1,
    RiskTier.MEDIUM: 2,
    RiskTier.LOW: 3,
}
_TIER_LABEL = {
    RiskTier.CRITICAL: "Critical",
    RiskTier.HIGH: "High",
    RiskTier.MEDIUM: "Medium",
    RiskTier.LOW: "Low",
}
_MILESTONE_STATUS_LABEL = {
    MilestoneStatus.PENDING: "Pending",
    MilestoneStatus.ON_TRACK: "On Track",
    MilestoneStatus.AT_RISK: "At Risk",
    MilestoneStatus.COMPLETED: "Completed",
    MilestoneStatus.MISSED: "Critical",
}
_SEVERITY_LABEL = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}

RISK_TREND_WEEKS = 8
QUALITY_TREND_WEEKS = 12
RISK_TREND_MAX_SERIES = 4


def _iso_week_label(day: date) -> str:
    return f"W{day.isocalendar().week}"


def _traffic_light(dashboard: dict[str, Any]) -> str:
    value = str(dashboard.get("traffic_light", "")).lower()
    return value if value in _HEALTH_META else "green"


def select_inflight_projects(projects: list[Project]) -> list[Project]:
    """Return only projects that count toward active risk (active / ramping)."""
    return [p for p in projects if p.status in _INFLIGHT_STATUSES]


async def get_operational_tower(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Return every deterministic Operational Tower section in one payload.

    Every section is scoped to the projects visible to `current_user` via
    `scoped_project_query` (a PM/leadership user sees only their own organisation;
    a client sees only assigned projects). Risk-oriented sections are further limited
    to in-flight projects so completed work never contributes to active risk.
    """
    projects = list((await session.execute(scoped_project_query(current_user))).scalars())
    project_names = {p.id: p.name for p in projects}

    inflight_projects = select_inflight_projects(projects)
    inflight_ids = [p.id for p in inflight_projects]

    portfolio = await get_portfolio_data(
        session=session, current_user=current_user, projects=inflight_projects
    )

    kpis, health = _summarize_portfolio(projects, portfolio)

    quality_trend, avg_quality = await _quality_trend_and_avg(session, inflight_ids)
    kpis["avgQualityScore"] = avg_quality

    open_escalations, critical_escalations = await _escalation_counts(session, inflight_ids)
    kpis["openEscalations"] = open_escalations

    return {
        "kpis": kpis,
        "healthDistribution": health,
        "riskTrend": await _risk_trend(session, inflight_ids, project_names),
        "qualityTrend": quality_trend,
        "utilization": await _utilization(session, inflight_ids),
        "alerts": await _critical_alerts(session, inflight_ids, project_names),
        "recommendations": await _recommendations(session, inflight_ids),
        "milestones": await _upcoming_milestones(session, inflight_ids, project_names),
        "activity": await _recent_activity(session, current_user),
        "criticalEscalations": critical_escalations,
    }


def _summarize_portfolio(
    projects: list[Project], portfolio: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    active = sum(1 for p in projects if p.status == ProjectStatus.ACTIVE)

    confidences: list[float] = []
    counts: dict[str, int] = {"green": 0, "yellow": 0, "red": 0}
    insufficient = 0
    for entry in portfolio.get("projects", []):
        dashboard = entry["dashboard"]
        has_data = dashboard.get("overview", {}).get("has_sufficient_data", True)
        if not has_data:
            insufficient += 1
            continue
        counts[_traffic_light(dashboard)] += 1
        confidences.append(float(dashboard.get("confidence", 0)))

    schedule_confidence = round(sum(confidences) / len(confidences)) if confidences else None
    total = sum(counts.values()) + insufficient

    health = [
        {"name": _HEALTH_META[key][0], "value": counts[key], "color": _HEALTH_META[key][1]}
        for key in ("green", "yellow", "red")
    ]
    if insufficient:
        health.append(
            {"name": _INSUFFICIENT_META[0], "value": insufficient, "color": _INSUFFICIENT_META[1]}
        )
    kpis = {
        "activeProjects": active,
        "scheduleConfidence": schedule_confidence,
        "totalProjects": total,
        # openEscalations / avgQualityScore are filled in by the caller.
        "openEscalations": 0,
        "avgQualityScore": None,
    }
    return kpis, health


async def _risk_trend(
    session: AsyncSession,
    project_ids: list[UUID],
    project_names: dict[UUID, str],
) -> dict[str, Any]:
    """Per-project weekly delivery risk (100 − confidence) over the last N ISO weeks."""
    empty = {"series": [], "data": []}
    if not project_ids:
        return empty

    # Compare the raw timestamp rather than wrapping it in date(): a function call on the
    # column is not sargable, so Postgres cannot use the (project_id, created_at) index and
    # falls back to filtering every score row for these projects.
    since = datetime.combine(
        date.today() - timedelta(weeks=RISK_TREND_WEEKS), time.min, tzinfo=timezone.utc
    )
    rows = (
        await session.execute(
            select(
                DeliveryConfidenceScore.project_id,
                DeliveryConfidenceScore.created_at,
                DeliveryConfidenceScore.score_pct,
            )
            .where(
                DeliveryConfidenceScore.project_id.in_(project_ids),
                DeliveryConfidenceScore.created_at >= since,
            )
            .order_by(DeliveryConfidenceScore.created_at.asc())
        )
    ).all()
    if not rows:
        return empty

    # week label -> project_id -> list of risk values (averaged per bucket)
    buckets: dict[str, dict[UUID, list[float]]] = defaultdict(lambda: defaultdict(list))
    week_order: list[str] = []
    per_project_points: dict[UUID, int] = defaultdict(int)
    for project_id, created_at, score in rows:
        label = _iso_week_label(created_at.date())
        if label not in buckets:
            week_order.append(label)
        risk = max(0.0, 100.0 - float(score))
        buckets[label][project_id].append(risk)
        per_project_points[project_id] += 1

    top_projects = sorted(
        per_project_points, key=lambda pid: per_project_points[pid], reverse=True
    )[:RISK_TREND_MAX_SERIES]

    series = [
        {"name": project_names.get(pid, "Project"), "color": _RISK_TREND_COLORS[i]}
        for i, pid in enumerate(top_projects)
    ]
    data: list[dict[str, Any]] = []
    for label in week_order:
        point: dict[str, Any] = {"week": label}
        for pid in top_projects:
            values = buckets[label].get(pid)
            if values:
                point[project_names.get(pid, "Project")] = round(sum(values) / len(values))
        data.append(point)

    return {"series": series, "data": data}


async def _quality_trend_and_avg(
    session: AsyncSession,
    project_ids: list[UUID],
) -> tuple[list[dict[str, Any]], float | None]:
    """Portfolio-blended gold accuracy + mean IAA per ISO week (last N weeks)."""
    if not project_ids:
        return [], None

    # Only the newest QUALITY_TREND_WEEKS buckets are ever rendered, so resolve which weeks
    # those are first and fetch only their rows. Filtering on project_id alone pulled every
    # snapshot ever written for the portfolio and discarded all but the tail in Python,
    # which grew without bound as history accumulated. Selecting the weeks from the data
    # (rather than cutting at today - 12 weeks) keeps the existing behaviour: the chart
    # shows the last 12 weeks that have data, even if the newest snapshot is older.
    recent_weeks = (
        select(QualitySnapshot.iso_year, QualitySnapshot.iso_week)
        .where(QualitySnapshot.project_id.in_(project_ids))
        .distinct()
        .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
        .limit(QUALITY_TREND_WEEKS)
    )
    rows = (
        await session.execute(
            select(
                QualitySnapshot.iso_year,
                QualitySnapshot.iso_week,
                QualitySnapshot.gold_set_accuracy_pct,
                QualitySnapshot.iaa_krippendorff_alpha,
                QualitySnapshot.evaluated_item_count,
            )
            .where(
                QualitySnapshot.project_id.in_(project_ids),
                tuple_(QualitySnapshot.iso_year, QualitySnapshot.iso_week).in_(recent_weeks),
            )
            .order_by(QualitySnapshot.iso_year.asc(), QualitySnapshot.iso_week.asc())
        )
    ).all()
    if not rows:
        return [], None

    # (year, week) -> accumulators
    acc: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"gold_weight": 0.0, "gold_sum": 0.0, "iaa_sum": 0.0, "iaa_n": 0.0}
    )
    for iso_year, iso_week, gold, iaa, items in rows:
        bucket = acc[(iso_year, iso_week)]
        weight = float(items) if items else 1.0
        if gold is not None:
            bucket["gold_weight"] += weight
            bucket["gold_sum"] += float(gold) * weight
        if iaa is not None:
            bucket["iaa_sum"] += float(iaa)
            bucket["iaa_n"] += 1

    ordered = sorted(acc.keys())[-QUALITY_TREND_WEEKS:]
    trend: list[dict[str, Any]] = []
    for year, week in ordered:
        bucket = acc[(year, week)]
        gold = (
            round(bucket["gold_sum"] / bucket["gold_weight"], 1)
            if bucket["gold_weight"]
            else None
        )
        iaa = round(bucket["iaa_sum"] / bucket["iaa_n"], 3) if bucket["iaa_n"] else None
        trend.append({"week": f"W{week}", "goldAccuracy": gold, "iaa": iaa})

    latest = trend[-1]["goldAccuracy"] if trend else None
    return trend, latest


async def _utilization(
    session: AsyncSession,
    project_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Latest utilization snapshot per team, labelled '<Site> · <Domain>'."""
    if not project_ids:
        return []

    row_number = (
        func.row_number()
        .over(
            partition_by=UtilizationSnapshot.team_id,
            order_by=UtilizationSnapshot.snapshot_date.desc(),
        )
        .label("rn")
    )
    ranked = (
        select(UtilizationSnapshot.id.label("snap_id"), row_number)
        .where(
            UtilizationSnapshot.project_id.in_(project_ids),
            UtilizationSnapshot.team_id.is_not(None),
            UtilizationSnapshot.deleted_at.is_(None),
        )
        .subquery()
    )
    rows = (
        await session.execute(
            select(Team, UtilizationSnapshot.utilization_pct)
            .join(ranked, UtilizationSnapshot.id == ranked.c.snap_id)
            .join(Team, Team.id == UtilizationSnapshot.team_id)
            .where(ranked.c.rn == 1)
            .order_by(UtilizationSnapshot.utilization_pct.desc())
        )
    ).all()

    result: list[dict[str, Any]] = []
    for team, util in rows:
        site = str(team.site.value if hasattr(team.site, "value") else team.site).title()
        result.append({"team": f"{site} · {team.domain}", "value": round(float(util))})
    return result


async def _critical_alerts(
    session: AsyncSession,
    project_ids: list[UUID],
    project_names: dict[UUID, str],
) -> list[dict[str, Any]]:
    """Top open risk alerts across the portfolio, most severe first."""
    if not project_ids:
        return []

    rows = list(
        (
            await session.execute(
                select(RiskAlert)
                .where(
                    RiskAlert.project_id.in_(project_ids),
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(RiskAlert.created_at.desc())
            )
        ).scalars()
    )
    rows.sort(key=lambda a: (_TIER_RANK.get(a.risk_tier, 9), -a.created_at.timestamp()))

    return [
        {
            "sev": _TIER_LABEL.get(alert.risk_tier, "Warning"),
            "project": project_names.get(alert.project_id, "Project"),
            "desc": alert.detail or alert.title,
            "ts": alert.created_at.isoformat(),
        }
        for alert in rows[:5]
    ]


async def _recommendations(
    session: AsyncSession,
    project_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Pending AI mitigation recommendations (genuinely model-generated)."""
    if not project_ids:
        return []

    from app.db.models import RecommendationStatus

    rows = list(
        (
            await session.execute(
                select(MitigationRecommendation, RiskAlert.contributing_causes)
                .outerjoin(RiskAlert, RiskAlert.id == MitigationRecommendation.source_risk_id)
                .where(
                    MitigationRecommendation.project_id.in_(project_ids),
                    MitigationRecommendation.deleted_at.is_(None),
                    MitigationRecommendation.status == RecommendationStatus.PENDING,
                )
                .order_by(MitigationRecommendation.confidence_score.desc())
                .limit(6)
            )
        ).all()
    )

    result: list[dict[str, Any]] = []
    for rec, causes in rows:
        evidence = len(causes) if isinstance(causes, dict) else (1 if rec.source_risk_id else 0)
        result.append(
            {
                "title": rec.title,
                "confidence": round(float(rec.confidence_score) * 100),
                "evidence": evidence,
                "priority": _SEVERITY_LABEL.get(
                    str(getattr(rec.severity, "value", rec.severity)), "Medium"
                ),
            }
        )
    return result


async def _upcoming_milestones(
    session: AsyncSession,
    project_ids: list[UUID],
    project_names: dict[UUID, str],
) -> list[dict[str, Any]]:
    """Next milestones across the portfolio with their latest confidence score."""
    if not project_ids:
        return []

    today = date.today()
    milestones = list(
        (
            await session.execute(
                select(Milestone)
                .where(
                    Milestone.project_id.in_(project_ids),
                    Milestone.deleted_at.is_(None),
                    Milestone.planned_date >= today,
                    Milestone.status != MilestoneStatus.COMPLETED,
                )
                .order_by(Milestone.planned_date.asc())
                .limit(8)
            )
        ).scalars()
    )
    if not milestones:
        return []

    milestone_ids = [m.id for m in milestones]
    row_number = (
        func.row_number()
        .over(
            partition_by=DeliveryConfidenceScore.milestone_id,
            order_by=DeliveryConfidenceScore.created_at.desc(),
        )
        .label("rn")
    )
    ranked = (
        select(DeliveryConfidenceScore.id.label("score_id"), row_number)
        .where(DeliveryConfidenceScore.milestone_id.in_(milestone_ids))
        .subquery()
    )
    conf_rows = (
        await session.execute(
            select(DeliveryConfidenceScore)
            .join(ranked, DeliveryConfidenceScore.id == ranked.c.score_id)
            .where(ranked.c.rn == 1)
        )
    ).scalars()
    confidence_by_milestone = {c.milestone_id: c for c in conf_rows}

    result: list[dict[str, Any]] = []
    for m in milestones:
        conf = confidence_by_milestone.get(m.id)
        status = conf.status if conf is not None else m.status
        result.append(
            {
                "project": project_names.get(m.project_id, "Project"),
                "name": m.name,
                "due": m.planned_date.isoformat(),
                "confidence": round(float(conf.score_pct)) if conf is not None else None,
                "status": _MILESTONE_STATUS_LABEL.get(status, "Pending"),
            }
        )
    return result


async def _recent_activity(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[dict[str, Any]]:
    """Most recent operational notifications for the current user."""
    rows = list(
        (
            await session.execute(
                select(Notification)
                .where(Notification.user_id == current_user.id)
                .order_by(Notification.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    return [
        {
            "ts": n.created_at.isoformat(),
            "actor": _notification_actor(n),
            "text": n.title,
        }
        for n in rows
    ]


def _notification_actor(notification: Notification) -> str:
    kind = str(getattr(notification.notification_type, "value", notification.notification_type))
    mapping = {
        "risk_alert": "Delivery Agent",
        "quality_drift_detected": "Quality Agent",
        "skill_gap_detected": "Workforce Agent",
        "calibration_required": "Quality Agent",
        "sop_ambiguity_flagged": "Quality Agent",
        "communication_pending": "Governance Agent",
        "milestone_at_risk": "Delivery Agent",
    }
    return mapping.get(kind, "System")


async def _escalation_counts(
    session: AsyncSession,
    project_ids: list[UUID],
) -> tuple[int, int]:
    """(open escalations, critical open escalations) across the portfolio."""
    if not project_ids:
        return 0, 0

    open_statuses = [
        GovernanceEscalationStatus.OPEN,
        GovernanceEscalationStatus.IN_PROGRESS,
    ]
    total = (
        await session.execute(
            select(func.count(GovernanceEscalation.id)).where(
                GovernanceEscalation.project_id.in_(project_ids),
                GovernanceEscalation.deleted_at.is_(None),
                GovernanceEscalation.status.in_(open_statuses),
            )
        )
    ).scalar_one()
    critical = (
        await session.execute(
            select(func.count(GovernanceEscalation.id)).where(
                GovernanceEscalation.project_id.in_(project_ids),
                GovernanceEscalation.deleted_at.is_(None),
                GovernanceEscalation.status.in_(open_statuses),
                GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
            )
        )
    ).scalar_one()
    return int(total), int(critical)


_ORG_WIDE_ROLES = frozenset(
    {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
)


async def get_executive_summary(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[str, Any] | None:
    """Return the latest stored (AI-authored) executive summary for the caller's portfolio.

    Scoped to the caller's own organisation and only served to org-wide roles, so the
    summary never reflects another organisation's or another portfolio's projects. Never
    regenerates — it only reads what was already produced.
    """
    if current_user.role not in _ORG_WIDE_ROLES:
        return None

    in_scope = (
        await session.execute(scoped_project_query(current_user).limit(1))
    ).scalars().all()
    if not in_scope:
        return None

    row = (
        await session.execute(
            select(GovernanceWeeklySummary)
            .where(GovernanceWeeklySummary.org_id == current_user.org_id)
            .order_by(GovernanceWeeklySummary.summary_week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    return {
        "text": row.summary_text,
        "week": row.summary_week.isoformat(),
        "generated_by_ai": bool(row.generated_by_ai),
        "status": str(getattr(row.status, "value", row.status)),
        "approved": row.status == GovernanceSummaryStatus.APPROVED,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
