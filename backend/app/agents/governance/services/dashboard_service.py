from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceBootstrapRead,
    GovernanceKpisRead,
)
from app.agents.governance.services.governance_service import (
    _apply_org_filter,
    _client_project_ids,
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
    ProjectDependency,
    ProjectScopeState,
)

BOOTSTRAP_CACHE_TTL = timedelta(minutes=3)
_bootstrap_kpi_cache: dict[tuple[UUID | None, str, UUID], tuple[datetime, GovernanceKpisRead]] = {}


def _bootstrap_cache_key(current_user: CurrentUser) -> tuple[UUID | None, str, UUID]:
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id
    return (org_id, current_user.role.value, current_user.id)


def _open_action_filter(today: date):
    return or_(
        GovernanceAction.status.in_(
            {
                GovernanceActionStatus.OPEN,
                GovernanceActionStatus.IN_PROGRESS,
                GovernanceActionStatus.OVERDUE,
            }
        ),
        and_(
            GovernanceAction.status != GovernanceActionStatus.COMPLETED,
            GovernanceAction.due_date.is_not(None),
            GovernanceAction.due_date < today,
        ),
    )


def _overdue_action_filter(today: date):
    return or_(
        GovernanceAction.status == GovernanceActionStatus.OVERDUE,
        and_(
            GovernanceAction.status != GovernanceActionStatus.COMPLETED,
            GovernanceAction.due_date.is_not(None),
            GovernanceAction.due_date < today,
        ),
    )


def _completed_sla_window_filter(window_start: date):
    return and_(
        GovernanceAction.status == GovernanceActionStatus.COMPLETED,
        GovernanceAction.completed_at.is_not(None),
        func.date(GovernanceAction.completed_at) >= window_start,
    )


def _on_time_completed_filter(window_start: date):
    return and_(
        _completed_sla_window_filter(window_start),
        or_(
            GovernanceAction.due_date.is_(None),
            func.date(GovernanceAction.completed_at) <= GovernanceAction.due_date,
        ),
    )


def _sla_adherence_from_counts(on_time: int, total: int) -> float:
    if total == 0:
        return 100.0
    return round((on_time / total) * 100.0, 1)


async def _fetch_action_kpis(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    window_start: date,
) -> tuple[int, int, float]:
    stmt = (
        select(
            func.count().filter(_open_action_filter(today)).label("open_actions"),
            func.count().filter(_overdue_action_filter(today)).label("overdue_actions"),
            func.count()
            .filter(_on_time_completed_filter(window_start))
            .label("on_time_completed"),
            func.count()
            .filter(_completed_sla_window_filter(window_start))
            .label("total_completed"),
        )
        .select_from(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None))
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    row = (await session.execute(stmt)).one()
    return (
        int(row.open_actions or 0),
        int(row.overdue_actions or 0),
        _sla_adherence_from_counts(
            int(row.on_time_completed or 0),
            int(row.total_completed or 0),
        ),
    )


async def _fetch_inventory_kpis(
    session: AsyncSession,
    current_user: CurrentUser,
) -> tuple[int, int]:
    blocking_stmt = select(func.count()).select_from(ProjectDependency).where(
        ProjectDependency.deleted_at.is_(None),
        ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
    )
    blocking_stmt = _apply_org_filter(blocking_stmt, ProjectDependency.org_id, current_user)

    pending_stmt = select(func.count()).select_from(ProjectScopeState).where(
        ProjectScopeState.deleted_at.is_(None),
        ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
    )
    pending_stmt = _apply_org_filter(pending_stmt, ProjectScopeState.org_id, current_user)

    stmt = select(
        blocking_stmt.scalar_subquery().label("blocking_dependencies"),
        pending_stmt.scalar_subquery().label("pending_scope"),
    )
    row = (await session.execute(stmt)).one()
    return int(row.blocking_dependencies or 0), int(row.pending_scope or 0)


async def _fetch_escalation_kpis(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_ids: list[UUID] | None = None,
) -> tuple[int, int]:
    if project_ids is not None and not project_ids:
        return 0, 0

    stmt = (
        select(
            func.count().label("open_escalations"),
            func.count()
            .filter(
                GovernanceEscalation.severity.in_(
                    {
                        GovernanceEscalationSeverity.HIGH,
                        GovernanceEscalationSeverity.CRITICAL,
                    }
                )
            )
            .label("critical_escalations"),
        )
        .select_from(GovernanceEscalation)
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(
                {GovernanceEscalationStatus.OPEN, GovernanceEscalationStatus.IN_PROGRESS}
            ),
        )
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    if project_ids is not None:
        stmt = stmt.where(GovernanceEscalation.project_id.in_(project_ids))

    row = (await session.execute(stmt)).one()
    return int(row.open_escalations or 0), int(row.critical_escalations or 0)


async def compute_governance_kpis(
    session: AsyncSession,
    current_user: CurrentUser,
) -> GovernanceKpisRead:
    today = datetime.now(UTC).date()
    window_start = today - timedelta(days=90)

    open_actions = 0
    overdue_actions = 0
    blocking_dependencies = 0
    pending_scope = 0
    sla_adherence_pct = 100.0

    if can_read_internal_governance(current_user):
        open_actions, overdue_actions, sla_adherence_pct = await _fetch_action_kpis(
            session,
            current_user,
            today=today,
            window_start=window_start,
        )
        blocking_dependencies, pending_scope = await _fetch_inventory_kpis(session, current_user)

    if current_user.role == AppRole.CLIENT:
        project_ids = await _client_project_ids(session, current_user)
        open_escalations, critical_escalations = await _fetch_escalation_kpis(
            session,
            current_user,
            project_ids=project_ids,
        )
    else:
        open_escalations, critical_escalations = await _fetch_escalation_kpis(
            session,
            current_user,
        )

    return GovernanceKpisRead(
        open_actions=open_actions,
        overdue_actions=overdue_actions,
        open_escalations=open_escalations,
        blocking_dependencies=blocking_dependencies,
        at_risk_items=blocking_dependencies + pending_scope + critical_escalations,
        sla_adherence_pct=sla_adherence_pct,
    )


async def get_governance_bootstrap(
    session: AsyncSession,
    current_user: CurrentUser,
) -> GovernanceBootstrapRead:
    assert_can_read_governance(current_user)

    cache_key = _bootstrap_cache_key(current_user)
    cached = _bootstrap_kpi_cache.get(cache_key)
    now = datetime.now(UTC)
    if cached and now - cached[0] < BOOTSTRAP_CACHE_TTL:
        return GovernanceBootstrapRead(kpis=cached[1])

    kpis = await compute_governance_kpis(session, current_user)
    _bootstrap_kpi_cache[cache_key] = (now, kpis)
    return GovernanceBootstrapRead(kpis=kpis)


compute_governance_kpis = governance_db_timed(compute_governance_kpis)
get_governance_bootstrap = governance_db_timed(get_governance_bootstrap)
