from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.dashboard_service import get_portfolio_data
from app.agents.governance.analytics.sla import (
    calculate_sla_adherence_pct,
    dependency_overdue_days,
    effective_action_status,
)
from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsKpisRead,
    GovernanceAnalyticsRead,
    GovernanceChartPointRead,
    GovernanceEvidenceRead,
    GovernanceHealthProjectRead,
    GovernanceInsightRead,
    GovernanceRecommendationRead,
    GovernanceTrendPointRead,
)
from app.agents.governance.services.governance_service import (
    assert_can_read_governance,
    can_read_internal_governance,
    scoped_actions_query,
    scoped_dependencies_query,
    scoped_escalations_query,
    scoped_scope_states_query,
)
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAction,
    GovernanceDependencyStatus,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    Project,
)
from app.services.scoping import scoped_project_query


RANGE_DAY_OPTIONS = {7, 30, 90, 365}
OPEN_ESCALATION_STATUSES = {
    GovernanceEscalationStatus.OPEN,
    GovernanceEscalationStatus.IN_PROGRESS,
}
OPEN_ACTION_STATUSES = {"open", "in_progress", "overdue"}


def _clamp_range(days: int) -> int:
    if days in RANGE_DAY_OPTIONS:
        return days
    return 30


def _risk_level(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "healthy"
    if score >= 60:
        return "moderate_risk"
    if score >= 40:
        return "high_risk"
    return "critical"


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _dt(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC)


def _days_between(start: datetime | date | None, end: datetime | date | None) -> float | None:
    start_dt = _dt(start)
    end_dt = _dt(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0.0, round((end_dt - start_dt).total_seconds() / 86400, 1))


def _evidence(
    source_type: str,
    label: str,
    *,
    source_id: UUID | None = None,
    detail: str | None = None,
    project_id: UUID | None = None,
    project_name: str | None = None,
) -> GovernanceEvidenceRead:
    return GovernanceEvidenceRead(
        source_type=source_type,
        source_id=str(source_id) if source_id else None,
        label=label,
        detail=detail,
        project_id=project_id,
        project_name=project_name,
    )


def _chart_points(counter: Counter[str], labels: list[tuple[str, str]]) -> list[GovernanceChartPointRead]:
    return [
        GovernanceChartPointRead(label=label, value=float(counter.get(key, 0)))
        for key, label in labels
    ]


def _delivery_penalty(confidence: float | None, traffic: str | None) -> int:
    if traffic == "red":
        return 14
    if traffic == "yellow":
        return 7
    if confidence is not None and confidence < 40:
        return 10
    if confidence is not None and confidence < 65:
        return 5
    return 0


def _score_project(
    project: Project,
    *,
    dependencies: list,
    escalations: list,
    actions: list[GovernanceAction],
    scopes: list,
    delivery_signal: dict | None,
) -> GovernanceHealthProjectRead:
    project_id = project.id
    open_dependencies = [
        dep for dep in dependencies if dep.status != GovernanceDependencyStatus.RESOLVED
    ]
    blocking_dependencies = [
        dep for dep in dependencies if dep.status == GovernanceDependencyStatus.BLOCKING
    ]
    open_escalations = [esc for esc in escalations if esc.status in OPEN_ESCALATION_STATUSES]
    critical_escalations = [
        esc
        for esc in open_escalations
        if esc.severity == GovernanceEscalationSeverity.CRITICAL
    ]
    overdue_actions = [action for action in actions if effective_action_status(action).value == "overdue"]
    pending_scopes = [
        scope for scope in scopes if scope.scope_status == GovernanceScopeStatus.PENDING_REVISION
    ]
    delivery_dashboard = delivery_signal.get("dashboard") if delivery_signal else None
    delivery_confidence = (
        float(delivery_dashboard.get("confidence"))
        if delivery_dashboard and delivery_dashboard.get("confidence") is not None
        else None
    )
    delivery_traffic = delivery_dashboard.get("traffic_light") if delivery_dashboard else None
    quality_snapshot = None
    if delivery_dashboard:
        quality_snapshot = (delivery_dashboard.get("overview") or {}).get("quality_snapshot")
    quality_risk = "elevated" if quality_snapshot and quality_snapshot.get("has_drift_alert") else None

    penalty = (
        len(blocking_dependencies) * 12
        + len(critical_escalations) * 16
        + max(0, len(open_escalations) - len(critical_escalations)) * 8
        + len(overdue_actions) * 7
        + len(pending_scopes) * 9
        + _delivery_penalty(delivery_confidence, delivery_traffic)
        + (8 if quality_risk else 0)
    )
    score = max(0, min(100, 100 - penalty))
    priority = (
        len(critical_escalations) * 30
        + len(blocking_dependencies) * 20
        + len(overdue_actions) * 10
        + len(pending_scopes) * 10
        + (15 if delivery_traffic == "red" else 7 if delivery_traffic == "yellow" else 0)
    )
    evidence = []
    evidence.extend(
        _evidence(
            "dependency",
            dep.title,
            source_id=dep.id,
            detail=f"status={_enum_value(dep.status)}, overdue_days={dependency_overdue_days(dep)}",
            project_id=project_id,
            project_name=project.name,
        )
        for dep in blocking_dependencies[:3]
    )
    evidence.extend(
        _evidence(
            "escalation",
            esc.title,
            source_id=esc.id,
            detail=f"severity={_enum_value(esc.severity)}, status={_enum_value(esc.status)}",
            project_id=project_id,
            project_name=project.name,
        )
        for esc in critical_escalations[:3]
    )
    if delivery_dashboard and delivery_traffic in {"red", "yellow"}:
        evidence.append(
            _evidence(
                "delivery_signal",
                "Delivery confidence",
                detail=f"confidence={delivery_confidence}, traffic_light={delivery_traffic}",
                project_id=project_id,
                project_name=project.name,
            )
        )

    return GovernanceHealthProjectRead(
        project_id=project_id,
        project_name=project.name,
        score=score,
        risk_level=_risk_level(score),
        priority=priority,
        blocking_dependencies=len(blocking_dependencies),
        open_dependencies=len(open_dependencies),
        open_escalations=len(open_escalations),
        critical_escalations=len(critical_escalations),
        overdue_actions=len(overdue_actions),
        pending_scope_revisions=len(pending_scopes),
        delivery_confidence=delivery_confidence,
        delivery_traffic_light=delivery_traffic,
        quality_risk=quality_risk,
        workforce_risk=None,
        trend="stable",
        evidence=evidence,
    )


def _build_insights(
    project_health: list[GovernanceHealthProjectRead],
    dependencies: list,
    escalations: list,
    actions: list[GovernanceAction],
) -> list[GovernanceInsightRead]:
    insights: list[GovernanceInsightRead] = []
    critical_projects = [project for project in project_health if project.risk_level == "critical"]
    high_risk_projects = [
        project for project in project_health if project.risk_level in {"critical", "high_risk"}
    ]
    blocking = [dep for dep in dependencies if dep.status == GovernanceDependencyStatus.BLOCKING]
    critical_escalations = [
        esc
        for esc in escalations
        if esc.status in OPEN_ESCALATION_STATUSES
        and esc.severity == GovernanceEscalationSeverity.CRITICAL
    ]
    overdue_actions = [action for action in actions if effective_action_status(action).value == "overdue"]

    if critical_projects:
        evidence = [
            _evidence(
                "governance_health",
                project.project_name,
                detail=f"score={project.score}, risk_level={project.risk_level}",
                project_id=project.project_id,
                project_name=project.project_name,
            )
            for project in critical_projects[:3]
        ]
        insights.append(
            GovernanceInsightRead(
                title=f"{len(critical_projects)} project(s) are in critical governance status",
                detail="Leadership attention is required because their health scores are below 40.",
                severity="critical",
                evidence=evidence,
            )
        )
    elif high_risk_projects:
        evidence = [
            _evidence(
                "governance_health",
                project.project_name,
                detail=f"score={project.score}, risk_level={project.risk_level}",
                project_id=project.project_id,
                project_name=project.project_name,
            )
            for project in high_risk_projects[:3]
        ]
        insights.append(
            GovernanceInsightRead(
                title=f"{len(high_risk_projects)} project(s) need governance attention",
                detail="These projects have high-risk or critical governance health scores.",
                severity="high",
                evidence=evidence,
            )
        )

    if blocking:
        dep_types = Counter(_enum_value(dep.dependency_type) for dep in blocking)
        top_type, count = dep_types.most_common(1)[0]
        insights.append(
            GovernanceInsightRead(
                title=f"{top_type.replace('_', ' ').title()} dependencies are the largest blocker group",
                detail=f"{count} blocking dependencies are currently classified as {top_type}.",
                severity="high",
                evidence=[
                    _evidence(
                        "dependency",
                        dep.title,
                        source_id=dep.id,
                        detail=f"type={_enum_value(dep.dependency_type)}, status={_enum_value(dep.status)}",
                        project_id=dep.project_id,
                    )
                    for dep in blocking
                    if _enum_value(dep.dependency_type) == top_type
                ][:3],
            )
        )

    if critical_escalations:
        insights.append(
            GovernanceInsightRead(
                title=f"{len(critical_escalations)} critical escalation(s) remain open",
                detail="Critical escalations are the strongest current governance health penalty.",
                severity="critical",
                evidence=[
                    _evidence(
                        "escalation",
                        esc.title,
                        source_id=esc.id,
                        detail=f"severity={_enum_value(esc.severity)}, status={_enum_value(esc.status)}",
                        project_id=esc.project_id,
                    )
                    for esc in critical_escalations[:3]
                ],
            )
        )

    if overdue_actions:
        insights.append(
            GovernanceInsightRead(
                title=f"{len(overdue_actions)} governance action(s) are overdue",
                detail="Overdue actions reduce SLA adherence and increase portfolio governance risk.",
                severity="medium",
                evidence=[
                    _evidence(
                        "action",
                        action.title,
                        source_id=action.id,
                        detail=f"due_date={action.due_date}, status={effective_action_status(action).value}",
                        project_id=action.project_id,
                    )
                    for action in overdue_actions[:3]
                ],
            )
        )

    return [insight for insight in insights if insight.evidence]


def _build_recommendations(
    ranking: list[GovernanceHealthProjectRead],
) -> list[GovernanceRecommendationRead]:
    recommendations: list[GovernanceRecommendationRead] = []
    for project in ranking[:5]:
        if project.critical_escalations:
            recommendations.append(
                GovernanceRecommendationRead(
                    title="Escalate critical governance decisions to leadership",
                    detail="Critical escalations are open and materially lowering governance health.",
                    priority="critical",
                    project_id=project.project_id,
                    project_name=project.project_name,
                    evidence=project.evidence[:3],
                )
            )
        elif project.blocking_dependencies:
            recommendations.append(
                GovernanceRecommendationRead(
                    title="Assign owners and decision dates to blocking dependencies",
                    detail="Blocking dependencies are the primary governance risk driver for this project.",
                    priority="high",
                    project_id=project.project_id,
                    project_name=project.project_name,
                    evidence=project.evidence[:3],
                )
            )
        elif project.pending_scope_revisions:
            recommendations.append(
                GovernanceRecommendationRead(
                    title="Review pending scope revision",
                    detail="Scope is pending revision and should be confirmed against current delivery commitments.",
                    priority="medium",
                    project_id=project.project_id,
                    project_name=project.project_name,
                    evidence=project.evidence[:3],
                )
            )
    return [item for item in recommendations if item.evidence]


def _bucket_date(value: datetime | date | None, start: date, end: date) -> date | None:
    value_dt = _dt(value)
    if value_dt is None:
        return None
    value_date = value_dt.date()
    if start <= value_date <= end:
        return value_date
    return None


def _build_trends(
    *,
    days: int,
    project_health: list[GovernanceHealthProjectRead],
    dependencies: list,
    escalations: list,
    actions: list[GovernanceAction],
    scopes: list,
) -> list[GovernanceTrendPointRead]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    points: list[GovernanceTrendPointRead] = []
    portfolio_health = round(mean([project.score for project in project_health]), 1) if project_health else 100.0
    sla = calculate_sla_adherence_pct(actions)
    for offset in range(days):
        day = start + timedelta(days=offset)
        created_deps = [dep for dep in dependencies if _bucket_date(dep.created_at, day, day) == day]
        resolved_deps = [dep for dep in dependencies if _bucket_date(dep.resolved_at, day, day) == day]
        created_escalations = [
            esc for esc in escalations if _bucket_date(esc.raised_at, day, day) == day
        ]
        resolved_escalations = [
            esc for esc in escalations if _bucket_date(esc.resolved_at, day, day) == day
        ]
        created_actions = [action for action in actions if _bucket_date(action.created_at, day, day) == day]
        completed_actions = [
            action for action in actions if _bucket_date(action.completed_at, day, day) == day
        ]
        updated_scopes = [scope for scope in scopes if _bucket_date(scope.updated_at, day, day) == day]
        points.append(
            GovernanceTrendPointRead(
                date=day,
                open_dependencies=sum(
                    1
                    for dep in dependencies
                    if dep.status != GovernanceDependencyStatus.RESOLVED
                    and _dt(dep.created_at)
                    and _dt(dep.created_at).date() <= day
                ),
                resolved_dependencies=len(resolved_deps),
                blocking_dependencies=sum(
                    1 for dep in created_deps if dep.status == GovernanceDependencyStatus.BLOCKING
                ),
                escalations_created=len(created_escalations),
                escalations_resolved=len(resolved_escalations),
                critical_escalations=sum(
                    1 for esc in created_escalations if esc.severity == GovernanceEscalationSeverity.CRITICAL
                ),
                actions_created=len(created_actions),
                actions_completed=len(completed_actions),
                overdue_actions=sum(
                    1
                    for action in actions
                    if action.due_date is not None
                    and action.due_date <= day
                    and effective_action_status(action).value != "completed"
                ),
                scope_revisions=sum(
                    1
                    for scope in updated_scopes
                    if scope.scope_status == GovernanceScopeStatus.PENDING_REVISION
                ),
                scope_approvals=sum(
                    1 for scope in updated_scopes if scope.scope_status == GovernanceScopeStatus.APPROVED
                ),
                locked_scope=sum(
                    1 for scope in updated_scopes if scope.scope_status == GovernanceScopeStatus.LOCKED
                ),
                portfolio_health=portfolio_health,
                sla_adherence_pct=sla,
            )
        )
    return points


def _recent_activity(
    dependencies: list,
    escalations: list,
    actions: list[GovernanceAction],
    project_names: dict[UUID, str],
) -> list[GovernanceEvidenceRead]:
    rows: list[tuple[datetime, GovernanceEvidenceRead]] = []
    for dep in dependencies:
        if dep.created_at:
            rows.append(
                (
                    dep.created_at,
                    _evidence(
                        "dependency",
                        dep.title,
                        source_id=dep.id,
                        detail=f"status={_enum_value(dep.status)}",
                        project_id=dep.project_id,
                        project_name=project_names.get(dep.project_id),
                    ),
                )
            )
    for esc in escalations:
        if esc.raised_at:
            rows.append(
                (
                    esc.raised_at,
                    _evidence(
                        "escalation",
                        esc.title,
                        source_id=esc.id,
                        detail=f"severity={_enum_value(esc.severity)}",
                        project_id=esc.project_id,
                        project_name=project_names.get(esc.project_id),
                    ),
                )
            )
    for action in actions:
        if action.created_at:
            rows.append(
                (
                    action.created_at,
                    _evidence(
                        "action",
                        action.title,
                        source_id=action.id,
                        detail=f"status={effective_action_status(action).value}",
                        project_id=action.project_id,
                        project_name=project_names.get(action.project_id),
                    ),
                )
            )
    return [item for _, item in sorted(rows, key=lambda row: row[0], reverse=True)[:8]]


async def get_governance_analytics(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
) -> GovernanceAnalyticsRead:
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    projects = list(
        (
            await session.execute(scoped_project_query(current_user).order_by(Project.name.asc()))
        ).scalars()
    )
    dependencies = await scoped_dependencies_query(session, current_user)
    actions = await scoped_actions_query(session, current_user)
    escalations = await scoped_escalations_query(session, current_user)
    scopes = await scoped_scope_states_query(session, current_user)

    can_see_internal = can_read_internal_governance(current_user)
    delivery_by_project: dict[UUID, dict] = {}
    if can_see_internal and current_user.role != AppRole.CLIENT:
        portfolio = await get_portfolio_data(session=session, current_user=current_user)
        delivery_by_project = {
            row["project_id"]: row for row in portfolio.get("projects", [])
        }

    deps_by_project = defaultdict(list)
    actions_by_project = defaultdict(list)
    escalations_by_project = defaultdict(list)
    scopes_by_project = defaultdict(list)
    for dep in dependencies:
        deps_by_project[dep.project_id].append(dep)
    for action in actions:
        actions_by_project[action.project_id].append(action)
    for escalation in escalations:
        escalations_by_project[escalation.project_id].append(escalation)
    for scope in scopes:
        scopes_by_project[scope.project_id].append(scope)

    project_health = [
        _score_project(
            project,
            dependencies=deps_by_project.get(project.id, []),
            escalations=escalations_by_project.get(project.id, []),
            actions=actions_by_project.get(project.id, []),
            scopes=scopes_by_project.get(project.id, []),
            delivery_signal=delivery_by_project.get(project.id),
        )
        for project in projects
    ]
    ranking = sorted(project_health, key=lambda row: (row.score, -row.priority, row.project_name))

    open_dependencies = [
        dep for dep in dependencies if dep.status != GovernanceDependencyStatus.RESOLVED
    ]
    blocking_dependencies = [
        dep for dep in dependencies if dep.status == GovernanceDependencyStatus.BLOCKING
    ]
    critical_escalations = [
        esc
        for esc in escalations
        if esc.status in OPEN_ESCALATION_STATUSES
        and esc.severity == GovernanceEscalationSeverity.CRITICAL
    ]
    pending_scopes = [
        scope for scope in scopes if scope.scope_status == GovernanceScopeStatus.PENDING_REVISION
    ]
    overdue_actions = [action for action in actions if effective_action_status(action).value == "overdue"]
    completed_actions = [action for action in actions if action.completed_at is not None]
    resolved_dependencies = [dep for dep in dependencies if dep.resolved_at is not None]
    resolved_escalations = [esc for esc in escalations if esc.resolved_at is not None]
    project_names = {project.id: project.name for project in projects}

    portfolio_score = round(mean([row.score for row in project_health])) if project_health else 100
    green = sum(1 for row in project_health if row.score >= 75)
    amber = sum(1 for row in project_health if 40 <= row.score < 75)
    red = sum(1 for row in project_health if row.score < 40)
    trends = _build_trends(
        days=effective_days,
        project_health=project_health,
        dependencies=dependencies,
        escalations=escalations,
        actions=actions,
        scopes=scopes,
    )

    charts = {
        "dependencies_by_type": _chart_points(
            Counter(_enum_value(dep.dependency_type) for dep in dependencies),
            [
                ("client_action", "Client"),
                ("internal", "Internal"),
                ("external", "External"),
            ],
        ),
        "escalations_by_severity": _chart_points(
            Counter(_enum_value(esc.severity) for esc in escalations),
            [
                ("low", "Low"),
                ("medium", "Medium"),
                ("high", "High"),
                ("critical", "Critical"),
            ],
        ),
        "actions_by_status": _chart_points(
            Counter(effective_action_status(action).value for action in actions),
            [
                ("open", "Open"),
                ("in_progress", "In Progress"),
                ("completed", "Completed"),
                ("overdue", "Overdue"),
            ],
        ),
        "health_distribution": _chart_points(
            Counter(row.risk_level for row in project_health),
            [
                ("excellent", "Excellent"),
                ("healthy", "Healthy"),
                ("moderate_risk", "Moderate"),
                ("high_risk", "High Risk"),
                ("critical", "Critical"),
            ],
        ),
        "most_active_projects": [
            GovernanceChartPointRead(
                label=project.project_name,
                value=float(
                    project.open_dependencies
                    + project.open_escalations
                    + project.overdue_actions
                    + project.pending_scope_revisions
                ),
                secondary_value=float(project.score),
            )
            for project in sorted(project_health, key=lambda row: row.priority, reverse=True)[:8]
        ],
    }

    dependency_resolution_days = [
        days
        for days in (_days_between(dep.created_at, dep.resolved_at) for dep in resolved_dependencies)
        if days is not None
    ]
    escalation_resolution_days = [
        days
        for days in (_days_between(esc.raised_at, esc.resolved_at) for esc in resolved_escalations)
        if days is not None
    ]
    action_completion_days = [
        days
        for days in (_days_between(action.created_at, action.completed_at) for action in completed_actions)
        if days is not None
    ]

    recent_trend = trends[-7:] if len(trends) >= 7 else trends
    prior_trend = trends[-14:-7] if len(trends) >= 14 else []
    recent_health = mean([point.portfolio_health for point in recent_trend]) if recent_trend else portfolio_score
    prior_health = mean([point.portfolio_health for point in prior_trend]) if prior_trend else recent_health

    kpis = GovernanceAnalyticsKpisRead(
        portfolio_score=portfolio_score,
        projects_at_risk=sum(1 for row in project_health if row.score < 60),
        leadership_attention_projects=sum(
            1
            for row in project_health
            if row.critical_escalations or row.blocking_dependencies or row.score < 60
        ),
        blocking_dependencies=len(blocking_dependencies),
        critical_escalations=len(critical_escalations),
        pending_scope_approvals=len(pending_scopes),
        upcoming_governance_meetings=0,
        governance_sla_pct=calculate_sla_adherence_pct(actions),
        avg_dependency_resolution_days=round(mean(dependency_resolution_days), 1)
        if dependency_resolution_days
        else None,
        avg_escalation_resolution_days=round(mean(escalation_resolution_days), 1)
        if escalation_resolution_days
        else None,
        avg_action_completion_days=round(mean(action_completion_days), 1)
        if action_completion_days
        else None,
        open_dependencies=len(open_dependencies),
        open_actions=sum(1 for action in actions if effective_action_status(action).value in OPEN_ACTION_STATUSES),
        overdue_actions=len(overdue_actions),
        projects_red=red,
        projects_amber=amber,
        projects_green=green,
        weekly_trend=round(recent_health - prior_health, 1),
        monthly_trend=0.0,
    )

    return GovernanceAnalyticsRead(
        generated_at=datetime.now(UTC),
        date_range_days=effective_days,
        kpis=kpis,
        project_health=project_health,
        portfolio_risk_ranking=ranking,
        insights=_build_insights(project_health, dependencies, escalations, actions),
        recommendations=_build_recommendations(ranking),
        trends=trends,
        charts=charts,
        recent_activity=_recent_activity(dependencies, escalations, actions, project_names),
        export_sections=[
            "KPIs",
            "Charts",
            "Executive Insights",
            "Governance Health",
            "Evidence Appendix",
        ],
    )
