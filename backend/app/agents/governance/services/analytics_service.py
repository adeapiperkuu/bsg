from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from uuid import UUID

from sqlalchemy import and_, func, or_, select
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
from app.agents.governance.services.dashboard_service import (
    _fetch_action_kpis,
    _overdue_action_filter,
)
from app.agents.governance.services.governance_service import (
    _apply_org_filter,
    assert_can_read_governance,
    can_read_internal_governance,
)
from app.agents.governance.timing import governance_db_timed
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    Project,
    ProjectDependency,
    ProjectScopeState,
)
from app.services.scoping import scoped_project_query

RANGE_DAY_OPTIONS = {7, 30, 90, 365}
OPEN_ESCALATION_STATUSES = {
    GovernanceEscalationStatus.OPEN,
    GovernanceEscalationStatus.IN_PROGRESS,
}
ANALYTICS_CACHE_TTL = timedelta(minutes=3)
_analytics_cache: dict[
    tuple[UUID | None, str, UUID, int],
    tuple[datetime, GovernanceAnalyticsRead],
] = {}


def _analytics_cache_key(
    current_user: CurrentUser,
    days: int,
) -> tuple[UUID | None, str, UUID, int]:
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id
    return (org_id, current_user.role.value, current_user.id, days)


def _clamp_range(days: int) -> int:
    if days in RANGE_DAY_OPTIONS:
        return days
    return 30


def _trend_window_start(*, today: date, days: int) -> datetime:
    start = today - timedelta(days=days - 1)
    return datetime.combine(start, datetime.min.time(), tzinfo=UTC)


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


@dataclass(frozen=True)
class _ProjectMetrics:
    open_dependencies: int = 0
    blocking_dependencies: int = 0
    open_escalations: int = 0
    critical_escalations: int = 0
    overdue_actions: int = 0
    pending_scope_revisions: int = 0


async def _fetch_dependency_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, tuple[int, int]]:
    if not can_read_internal_governance(current_user):
        return {}
    stmt = (
        select(
            ProjectDependency.project_id,
            func.count()
            .filter(ProjectDependency.status != GovernanceDependencyStatus.RESOLVED)
            .label("open"),
            func.count()
            .filter(ProjectDependency.status == GovernanceDependencyStatus.BLOCKING)
            .label("blocking"),
        )
        .where(ProjectDependency.deleted_at.is_(None))
        .group_by(ProjectDependency.project_id)
    )
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {
        row.project_id: (int(row.open or 0), int(row.blocking or 0))
        for row in rows
    }


async def _fetch_escalation_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, tuple[int, int]]:
    stmt = (
        select(
            GovernanceEscalation.project_id,
            func.count().label("open"),
            func.count()
            .filter(GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL)
            .label("critical"),
        )
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
        )
        .group_by(GovernanceEscalation.project_id)
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {
        row.project_id: (int(row.open or 0), int(row.critical or 0))
        for row in rows
    }


async def _fetch_overdue_action_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> dict[UUID, int]:
    if not can_read_internal_governance(current_user):
        return {}
    stmt = (
        select(
            GovernanceAction.project_id,
            func.count().label("overdue"),
        )
        .where(GovernanceAction.deleted_at.is_(None))
        .where(_overdue_action_filter(today))
        .group_by(GovernanceAction.project_id)
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {row.project_id: int(row.overdue or 0) for row in rows}


async def _fetch_pending_scope_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, int]:
    if not can_read_internal_governance(current_user):
        return {}
    stmt = (
        select(
            ProjectScopeState.project_id,
            func.count().label("pending"),
        )
        .where(
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
        )
        .group_by(ProjectScopeState.project_id)
    )
    stmt = _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {row.project_id: int(row.pending or 0) for row in rows}


def _merge_project_metrics(
    project_id: UUID,
    *,
    dependency_counts: dict[UUID, tuple[int, int]],
    escalation_counts: dict[UUID, tuple[int, int]],
    overdue_actions: dict[UUID, int],
    pending_scopes: dict[UUID, int],
) -> _ProjectMetrics:
    dep_open, dep_blocking = dependency_counts.get(project_id, (0, 0))
    esc_open, esc_critical = escalation_counts.get(project_id, (0, 0))
    return _ProjectMetrics(
        open_dependencies=dep_open,
        blocking_dependencies=dep_blocking,
        open_escalations=esc_open,
        critical_escalations=esc_critical,
        overdue_actions=overdue_actions.get(project_id, 0),
        pending_scope_revisions=pending_scopes.get(project_id, 0),
    )


async def _fetch_enum_counter(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    model,
    enum_column,
    org_column,
) -> Counter[str]:
    stmt = (
        select(enum_column, func.count().label("count"))
        .where(model.deleted_at.is_(None))
        .group_by(enum_column)
    )
    stmt = _apply_org_filter(stmt, org_column, current_user)
    rows = (await session.execute(stmt)).all()
    return Counter({_enum_value(row[0]): int(row.count or 0) for row in rows})


async def _fetch_action_status_counter(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> Counter[str]:
    if not can_read_internal_governance(current_user):
        return Counter()
    stmt = (
        select(
            func.count()
            .filter(GovernanceAction.status == GovernanceActionStatus.COMPLETED)
            .label("completed"),
            func.count()
            .filter(
                and_(
                    GovernanceAction.status == GovernanceActionStatus.IN_PROGRESS,
                    ~_overdue_action_filter(today),
                )
            )
            .label("in_progress"),
            func.count()
            .filter(
                and_(
                    GovernanceAction.status == GovernanceActionStatus.OPEN,
                    ~_overdue_action_filter(today),
                )
            )
            .label("open"),
            func.count().filter(_overdue_action_filter(today)).label("overdue"),
        )
        .select_from(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None))
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    row = (await session.execute(stmt)).one()
    return Counter(
        {
            "completed": int(row.completed or 0),
            "in_progress": int(row.in_progress or 0),
            "open": int(row.open or 0),
            "overdue": int(row.overdue or 0),
        }
    )


async def _fetch_inventory_totals(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> tuple[int, int, int, int, int, float]:
    """Return open deps, blocking deps, critical esc, pending scope, overdue actions, sla pct."""
    if not can_read_internal_governance(current_user):
        return 0, 0, 0, 0, 0, 100.0

    open_dep_stmt = select(func.count()).select_from(ProjectDependency).where(
        ProjectDependency.deleted_at.is_(None),
        ProjectDependency.status != GovernanceDependencyStatus.RESOLVED,
    )
    open_dep_stmt = _apply_org_filter(open_dep_stmt, ProjectDependency.org_id, current_user)

    blocking_stmt = select(func.count()).select_from(ProjectDependency).where(
        ProjectDependency.deleted_at.is_(None),
        ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
    )
    blocking_stmt = _apply_org_filter(blocking_stmt, ProjectDependency.org_id, current_user)

    critical_stmt = select(func.count()).select_from(GovernanceEscalation).where(
        GovernanceEscalation.deleted_at.is_(None),
        GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
        GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
    )
    critical_stmt = _apply_org_filter(critical_stmt, GovernanceEscalation.org_id, current_user)

    pending_stmt = select(func.count()).select_from(ProjectScopeState).where(
        ProjectScopeState.deleted_at.is_(None),
        ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
    )
    pending_stmt = _apply_org_filter(pending_stmt, ProjectScopeState.org_id, current_user)

    overdue_stmt = select(func.count()).select_from(GovernanceAction).where(
        GovernanceAction.deleted_at.is_(None),
        _overdue_action_filter(today),
    )
    overdue_stmt = _apply_org_filter(overdue_stmt, GovernanceAction.org_id, current_user)

    totals_stmt = select(
        open_dep_stmt.scalar_subquery().label("open_dependencies"),
        blocking_stmt.scalar_subquery().label("blocking_dependencies"),
        critical_stmt.scalar_subquery().label("critical_escalations"),
        pending_stmt.scalar_subquery().label("pending_scope"),
        overdue_stmt.scalar_subquery().label("overdue_actions"),
    )
    totals = (await session.execute(totals_stmt)).one()

    _, _, sla_pct = await _fetch_action_kpis(
        session,
        current_user,
        today=today,
        window_start=today - timedelta(days=90),
    )

    return (
        int(totals.open_dependencies or 0),
        int(totals.blocking_dependencies or 0),
        int(totals.critical_escalations or 0),
        int(totals.pending_scope or 0),
        int(totals.overdue_actions or 0),
        sla_pct,
    )


async def _fetch_open_action_count(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> int:
    if not can_read_internal_governance(current_user):
        return 0
    open_filter = or_(
        GovernanceAction.status.in_(
            {
                GovernanceActionStatus.OPEN,
                GovernanceActionStatus.IN_PROGRESS,
                GovernanceActionStatus.OVERDUE,
            }
        ),
        _overdue_action_filter(today),
    )
    stmt = (
        select(func.count())
        .select_from(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None), open_filter)
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _fetch_resolution_averages(
    session: AsyncSession,
    current_user: CurrentUser,
) -> tuple[float | None, float | None, float | None]:
    if not can_read_internal_governance(current_user):
        return None, None, None

    dep_stmt = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    ProjectDependency.resolved_at - ProjectDependency.created_at,
                )
                / 86400.0
            )
        )
        .select_from(ProjectDependency)
        .where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.resolved_at.is_not(None),
            ProjectDependency.created_at.is_not(None),
        )
    )
    dep_stmt = _apply_org_filter(dep_stmt, ProjectDependency.org_id, current_user)

    esc_stmt = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    GovernanceEscalation.resolved_at - GovernanceEscalation.raised_at,
                )
                / 86400.0
            )
        )
        .select_from(GovernanceEscalation)
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.resolved_at.is_not(None),
            GovernanceEscalation.raised_at.is_not(None),
        )
    )
    esc_stmt = _apply_org_filter(esc_stmt, GovernanceEscalation.org_id, current_user)

    action_stmt = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    GovernanceAction.completed_at - GovernanceAction.created_at,
                )
                / 86400.0
            )
        )
        .select_from(GovernanceAction)
        .where(
            GovernanceAction.deleted_at.is_(None),
            GovernanceAction.completed_at.is_not(None),
            GovernanceAction.created_at.is_not(None),
        )
    )
    action_stmt = _apply_org_filter(action_stmt, GovernanceAction.org_id, current_user)

    stmt = select(
        dep_stmt.scalar_subquery().label("dependency_days"),
        esc_stmt.scalar_subquery().label("escalation_days"),
        action_stmt.scalar_subquery().label("action_days"),
    )
    row = (await session.execute(stmt)).one()
    return (
        round(float(row.dependency_days), 1) if row.dependency_days is not None else None,
        round(float(row.escalation_days), 1) if row.escalation_days is not None else None,
        round(float(row.action_days), 1) if row.action_days is not None else None,
    )


async def _fetch_trend_dependencies(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[ProjectDependency]:
    if not can_read_internal_governance(current_user):
        return []
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(ProjectDependency).where(
        ProjectDependency.deleted_at.is_(None),
        or_(
            ProjectDependency.status != GovernanceDependencyStatus.RESOLVED,
            ProjectDependency.resolved_at >= window_start,
            ProjectDependency.created_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_trend_escalations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[GovernanceEscalation]:
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(GovernanceEscalation).where(
        GovernanceEscalation.deleted_at.is_(None),
        or_(
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
            GovernanceEscalation.resolved_at >= window_start,
            GovernanceEscalation.raised_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_trend_actions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[GovernanceAction]:
    if not can_read_internal_governance(current_user):
        return []
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(GovernanceAction).where(
        GovernanceAction.deleted_at.is_(None),
        or_(
            GovernanceAction.status != GovernanceActionStatus.COMPLETED,
            GovernanceAction.completed_at >= window_start,
            GovernanceAction.created_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_trend_scopes(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[ProjectScopeState]:
    if not can_read_internal_governance(current_user):
        return []
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(ProjectScopeState).where(
        ProjectScopeState.deleted_at.is_(None),
        or_(
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
            ProjectScopeState.updated_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_blocking_dependencies(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[ProjectDependency]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = (
        select(ProjectDependency)
        .where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
        )
        .order_by(ProjectDependency.created_at.desc())
    )
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_critical_escalations(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceEscalation]:
    stmt = (
        select(GovernanceEscalation)
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
            GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
        )
        .order_by(GovernanceEscalation.raised_at.desc())
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_overdue_actions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> list[GovernanceAction]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = (
        select(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None), _overdue_action_filter(today))
        .order_by(GovernanceAction.due_date.asc())
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_project_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_ids: list[UUID],
    project_names: dict[UUID, str],
) -> dict[UUID, list[GovernanceEvidenceRead]]:
    if not project_ids or not can_read_internal_governance(current_user):
        return {}

    blocking_stmt = (
        select(ProjectDependency)
        .where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
            ProjectDependency.project_id.in_(project_ids),
        )
        .order_by(ProjectDependency.created_at.desc())
    )
    blocking_stmt = _apply_org_filter(blocking_stmt, ProjectDependency.org_id, current_user)
    blocking = list((await session.execute(blocking_stmt)).scalars())

    critical_stmt = (
        select(GovernanceEscalation)
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
            GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
            GovernanceEscalation.project_id.in_(project_ids),
        )
        .order_by(GovernanceEscalation.raised_at.desc())
    )
    critical_stmt = _apply_org_filter(critical_stmt, GovernanceEscalation.org_id, current_user)
    critical = list((await session.execute(critical_stmt)).scalars())

    evidence_by_project: dict[UUID, list[GovernanceEvidenceRead]] = defaultdict(list)
    for dep in blocking:
        if len(evidence_by_project[dep.project_id]) >= 3:
            continue
        evidence_by_project[dep.project_id].append(
            _evidence(
                "dependency",
                dep.title,
                source_id=dep.id,
                detail=f"status={_enum_value(dep.status)}, overdue_days={dependency_overdue_days(dep)}",
                project_id=dep.project_id,
                project_name=project_names.get(dep.project_id),
            )
        )
    for esc in critical:
        if len(evidence_by_project[esc.project_id]) >= 3:
            continue
        evidence_by_project[esc.project_id].append(
            _evidence(
                "escalation",
                esc.title,
                source_id=esc.id,
                detail=f"severity={_enum_value(esc.severity)}, status={_enum_value(esc.status)}",
                project_id=esc.project_id,
                project_name=project_names.get(esc.project_id),
            )
        )
    return evidence_by_project


async def _fetch_recent_activity(
    session: AsyncSession,
    current_user: CurrentUser,
    project_names: dict[UUID, str],
) -> list[GovernanceEvidenceRead]:
    rows: list[tuple[datetime, GovernanceEvidenceRead]] = []

    if can_read_internal_governance(current_user):
        dep_stmt = (
            select(ProjectDependency)
            .where(ProjectDependency.deleted_at.is_(None), ProjectDependency.created_at.is_not(None))
            .order_by(ProjectDependency.created_at.desc())
            .limit(8)
        )
        dep_stmt = _apply_org_filter(dep_stmt, ProjectDependency.org_id, current_user)
        for dep in (await session.execute(dep_stmt)).scalars():
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

        action_stmt = (
            select(GovernanceAction)
            .where(GovernanceAction.deleted_at.is_(None), GovernanceAction.created_at.is_not(None))
            .order_by(GovernanceAction.created_at.desc())
            .limit(8)
        )
        action_stmt = _apply_org_filter(action_stmt, GovernanceAction.org_id, current_user)
        for action in (await session.execute(action_stmt)).scalars():
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

    esc_stmt = (
        select(GovernanceEscalation)
        .where(GovernanceEscalation.deleted_at.is_(None), GovernanceEscalation.raised_at.is_not(None))
        .order_by(GovernanceEscalation.raised_at.desc())
        .limit(8)
    )
    esc_stmt = _apply_org_filter(esc_stmt, GovernanceEscalation.org_id, current_user)
    for esc in (await session.execute(esc_stmt)).scalars():
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

    return [item for _, item in sorted(rows, key=lambda row: row[0], reverse=True)[:8]]


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


def _score_project_from_metrics(
    project: Project,
    metrics: _ProjectMetrics,
    *,
    delivery_signal: dict | None,
    evidence: list[GovernanceEvidenceRead] | None = None,
) -> GovernanceHealthProjectRead:
    project_id = project.id
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

    non_critical_open = max(0, metrics.open_escalations - metrics.critical_escalations)
    penalty = (
        metrics.blocking_dependencies * 12
        + metrics.critical_escalations * 16
        + non_critical_open * 8
        + metrics.overdue_actions * 7
        + metrics.pending_scope_revisions * 9
        + _delivery_penalty(delivery_confidence, delivery_traffic)
        + (8 if quality_risk else 0)
    )
    score = max(0, min(100, 100 - penalty))
    priority = (
        metrics.critical_escalations * 30
        + metrics.blocking_dependencies * 20
        + metrics.overdue_actions * 10
        + metrics.pending_scope_revisions * 10
        + (15 if delivery_traffic == "red" else 7 if delivery_traffic == "yellow" else 0)
    )

    project_evidence = list(evidence or [])
    if delivery_dashboard and delivery_traffic in {"red", "yellow"}:
        project_evidence.append(
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
        blocking_dependencies=metrics.blocking_dependencies,
        open_dependencies=metrics.open_dependencies,
        open_escalations=metrics.open_escalations,
        critical_escalations=metrics.critical_escalations,
        overdue_actions=metrics.overdue_actions,
        pending_scope_revisions=metrics.pending_scope_revisions,
        delivery_confidence=delivery_confidence,
        delivery_traffic_light=delivery_traffic,
        quality_risk=quality_risk,
        workforce_risk=None,
        trend="stable",
        evidence=project_evidence,
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


async def get_governance_analytics(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
) -> GovernanceAnalyticsRead:
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    cache_key = _analytics_cache_key(current_user, effective_days)
    now = datetime.now(UTC)
    cached = _analytics_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
        return cached[1]

    today = now.date()
    projects = list(
        (
            await session.execute(scoped_project_query(current_user).order_by(Project.name.asc()))
        ).scalars()
    )
    project_names = {project.id: project.name for project in projects}

    dependency_counts = await _fetch_dependency_counts_by_project(session, current_user)
    escalation_counts = await _fetch_escalation_counts_by_project(session, current_user)
    overdue_by_project = await _fetch_overdue_action_counts_by_project(
        session, current_user, today=today
    )
    pending_by_project = await _fetch_pending_scope_counts_by_project(session, current_user)

    can_see_internal = can_read_internal_governance(current_user)
    delivery_by_project: dict[UUID, dict] = {}
    if can_see_internal and current_user.role != AppRole.CLIENT:
        portfolio = await get_portfolio_data(session=session, current_user=current_user)
        delivery_by_project = {
            row["project_id"]: row for row in portfolio.get("projects", [])
        }

    project_health: list[GovernanceHealthProjectRead] = []
    for project in projects:
        metrics = _merge_project_metrics(
            project.id,
            dependency_counts=dependency_counts,
            escalation_counts=escalation_counts,
            overdue_actions=overdue_by_project,
            pending_scopes=pending_by_project,
        )
        project_health.append(
            _score_project_from_metrics(
                project,
                metrics,
                delivery_signal=delivery_by_project.get(project.id),
            )
        )

    ranking = sorted(project_health, key=lambda row: (row.score, -row.priority, row.project_name))
    top_project_ids = [row.project_id for row in ranking[:10]]
    evidence_by_project = await _fetch_project_evidence(
        session,
        current_user,
        project_ids=top_project_ids,
        project_names=project_names,
    )
    if evidence_by_project:
        enriched: list[GovernanceHealthProjectRead] = []
        for row in project_health:
            fetched = evidence_by_project.get(row.project_id, [])
            if not fetched:
                enriched.append(row)
                continue
            delivery_evidence = [
                item for item in row.evidence if item.source_type == "delivery_signal"
            ]
            enriched.append(row.model_copy(update={"evidence": fetched + delivery_evidence}))
        project_health = enriched
        ranking = sorted(
            project_health, key=lambda row: (row.score, -row.priority, row.project_name)
        )

    (
        open_dependencies,
        blocking_dependencies_count,
        critical_escalations_count,
        pending_scope_count,
        overdue_actions_count,
        governance_sla_pct,
    ) = await _fetch_inventory_totals(session, current_user, today=today)
    open_actions_count = await _fetch_open_action_count(session, current_user, today=today)
    dep_resolution_avg, esc_resolution_avg, action_completion_avg = await _fetch_resolution_averages(
        session, current_user
    )

    trend_dependencies = await _fetch_trend_dependencies(
        session, current_user, today=today, days=effective_days
    )
    trend_escalations = await _fetch_trend_escalations(
        session, current_user, today=today, days=effective_days
    )
    trend_actions = await _fetch_trend_actions(
        session, current_user, today=today, days=effective_days
    )
    trend_scopes = await _fetch_trend_scopes(
        session, current_user, today=today, days=effective_days
    )
    trends = _build_trends(
        days=effective_days,
        project_health=project_health,
        dependencies=trend_dependencies,
        escalations=trend_escalations,
        actions=trend_actions,
        scopes=trend_scopes,
    )

    dep_type_counter = await _fetch_enum_counter(
        session,
        current_user,
        model=ProjectDependency,
        enum_column=ProjectDependency.dependency_type,
        org_column=ProjectDependency.org_id,
    )
    esc_severity_counter = await _fetch_enum_counter(
        session,
        current_user,
        model=GovernanceEscalation,
        enum_column=GovernanceEscalation.severity,
        org_column=GovernanceEscalation.org_id,
    )
    action_status_counter = await _fetch_action_status_counter(
        session, current_user, today=today
    )

    blocking_dependencies = await _fetch_blocking_dependencies(session, current_user)
    critical_escalations = await _fetch_critical_escalations(session, current_user)
    overdue_actions = await _fetch_overdue_actions(session, current_user, today=today)
    recent_activity = await _fetch_recent_activity(session, current_user, project_names)

    portfolio_score = round(mean([row.score for row in project_health])) if project_health else 100
    green = sum(1 for row in project_health if row.score >= 75)
    amber = sum(1 for row in project_health if 40 <= row.score < 75)
    red = sum(1 for row in project_health if row.score < 40)

    charts = {
        "dependencies_by_type": _chart_points(
            dep_type_counter,
            [
                ("client_action", "Client"),
                ("internal", "Internal"),
                ("external", "External"),
            ],
        ),
        "escalations_by_severity": _chart_points(
            esc_severity_counter,
            [
                ("low", "Low"),
                ("medium", "Medium"),
                ("high", "High"),
                ("critical", "Critical"),
            ],
        ),
        "actions_by_status": _chart_points(
            action_status_counter,
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
        blocking_dependencies=blocking_dependencies_count,
        critical_escalations=critical_escalations_count,
        pending_scope_approvals=pending_scope_count,
        upcoming_governance_meetings=0,
        governance_sla_pct=governance_sla_pct,
        avg_dependency_resolution_days=dep_resolution_avg,
        avg_escalation_resolution_days=esc_resolution_avg,
        avg_action_completion_days=action_completion_avg,
        open_dependencies=open_dependencies,
        open_actions=open_actions_count,
        overdue_actions=overdue_actions_count,
        projects_red=red,
        projects_amber=amber,
        projects_green=green,
        weekly_trend=round(recent_health - prior_health, 1),
        monthly_trend=0.0,
    )

    analytics = GovernanceAnalyticsRead(
        generated_at=datetime.now(UTC),
        date_range_days=effective_days,
        kpis=kpis,
        project_health=project_health,
        portfolio_risk_ranking=ranking,
        insights=_build_insights(
            project_health,
            blocking_dependencies,
            critical_escalations,
            overdue_actions,
        ),
        recommendations=_build_recommendations(ranking),
        trends=trends,
        charts=charts,
        recent_activity=recent_activity,
        export_sections=[
            "KPIs",
            "Charts",
            "Executive Insights",
            "Governance Health",
            "Evidence Appendix",
        ],
    )
    _analytics_cache[cache_key] = (now, analytics)
    return analytics


get_governance_analytics = governance_db_timed(get_governance_analytics)
