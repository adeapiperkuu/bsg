from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceBootstrapRead,
    GovernanceKpisRead,
)
from app.agents.governance.services.governance_service import (
    _apply_org_filter,
    assert_can_read_governance,
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
    ProjectAssignment,
    ProjectDependency,
    ProjectScopeState,
)

logger = logging.getLogger(__name__)

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


def _action_kpi_subquery(
    current_user: CurrentUser,
    *,
    today: date,
    window_start: date,
):
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
    return _apply_org_filter(stmt, GovernanceAction.org_id, current_user).subquery(
        "bootstrap_action_kpis"
    )


def _blocking_dependencies_scalar(current_user: CurrentUser):
    stmt = (
        select(func.count())
        .select_from(ProjectDependency)
        .where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
        )
    )
    return _apply_org_filter(stmt, ProjectDependency.org_id, current_user).scalar_subquery()


def _pending_scope_scalar(current_user: CurrentUser):
    stmt = (
        select(func.count())
        .select_from(ProjectScopeState)
        .where(
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
        )
    )
    return _apply_org_filter(stmt, ProjectScopeState.org_id, current_user).scalar_subquery()


def _escalation_kpi_subquery(
    current_user: CurrentUser,
    *,
    project_ids: Select | None = None,
):
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
    return stmt.subquery("bootstrap_escalation_kpis")


def _client_assignment_ids_select(current_user: CurrentUser) -> Select:
    return select(ProjectAssignment.project_id).where(
        ProjectAssignment.user_id == current_user.id,
        ProjectAssignment.is_active.is_(True),
        ProjectAssignment.deleted_at.is_(None),
        ProjectAssignment.org_id == current_user.org_id,
    )


def _kpis_from_row(row) -> GovernanceKpisRead:
    blocking_dependencies = int(row.blocking_dependencies or 0)
    pending_scope = int(row.pending_scope or 0)
    critical_escalations = int(row.critical_escalations or 0)
    return GovernanceKpisRead(
        open_actions=int(row.open_actions or 0),
        overdue_actions=int(row.overdue_actions or 0),
        open_escalations=int(row.open_escalations or 0),
        blocking_dependencies=blocking_dependencies,
        at_risk_items=blocking_dependencies + pending_scope + critical_escalations,
        sla_adherence_pct=_sla_adherence_from_counts(
            int(row.on_time_completed or 0),
            int(row.total_completed or 0),
        ),
    )


async def _fetch_bootstrap_kpis_bundle(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    window_start: date,
) -> GovernanceKpisRead:
    """Load all bootstrap KPI counts in one DB round trip."""
    if current_user.role == AppRole.CLIENT:
        escalation_kpis = _escalation_kpi_subquery(
            current_user,
            project_ids=_client_assignment_ids_select(current_user),
        )
        stmt = select(
            escalation_kpis.c.open_escalations,
            escalation_kpis.c.critical_escalations,
        ).select_from(escalation_kpis)
        row = (await session.execute(stmt)).one()
        critical_escalations = int(row.critical_escalations or 0)
        return GovernanceKpisRead(
            open_actions=0,
            overdue_actions=0,
            open_escalations=int(row.open_escalations or 0),
            blocking_dependencies=0,
            at_risk_items=critical_escalations,
            sla_adherence_pct=100.0,
        )

    action_kpis = _action_kpi_subquery(
        current_user,
        today=today,
        window_start=window_start,
    )
    escalation_kpis = _escalation_kpi_subquery(current_user)
    stmt = select(
        select(action_kpis.c.open_actions)
        .select_from(action_kpis)
        .scalar_subquery()
        .label("open_actions"),
        select(action_kpis.c.overdue_actions)
        .select_from(action_kpis)
        .scalar_subquery()
        .label("overdue_actions"),
        select(action_kpis.c.on_time_completed)
        .select_from(action_kpis)
        .scalar_subquery()
        .label("on_time_completed"),
        select(action_kpis.c.total_completed)
        .select_from(action_kpis)
        .scalar_subquery()
        .label("total_completed"),
        _blocking_dependencies_scalar(current_user).label("blocking_dependencies"),
        _pending_scope_scalar(current_user).label("pending_scope"),
        select(escalation_kpis.c.open_escalations)
        .select_from(escalation_kpis)
        .scalar_subquery()
        .label("open_escalations"),
        select(escalation_kpis.c.critical_escalations)
        .select_from(escalation_kpis)
        .scalar_subquery()
        .label("critical_escalations"),
    )
    row = (await session.execute(stmt)).one()
    return _kpis_from_row(row)


async def compute_governance_kpis(
    session: AsyncSession,
    current_user: CurrentUser,
) -> GovernanceKpisRead:
    today = datetime.now(UTC).date()
    window_start = today - timedelta(days=90)
    return await _fetch_bootstrap_kpis_bundle(
        session,
        current_user,
        today=today,
        window_start=window_start,
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

    started = perf_counter()
    kpis = await compute_governance_kpis(session, current_user)
    elapsed_ms = round((perf_counter() - started) * 1000, 1)
    if elapsed_ms >= 150:
        logger.info(
            "governance_bootstrap_profile total_ms=%s db_executes=1 role=%s org_id=%s",
            elapsed_ms,
            current_user.role.value,
            str(current_user.org_id) if current_user.org_id else None,
        )

    _bootstrap_kpi_cache[cache_key] = (now, kpis)
    return GovernanceBootstrapRead(kpis=kpis)


compute_governance_kpis = governance_db_timed(compute_governance_kpis)
get_governance_bootstrap = governance_db_timed(get_governance_bootstrap)
