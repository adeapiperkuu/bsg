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


async def _count_query(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _compute_sla_adherence_pct(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    window_start: date,
) -> float:
    if not can_read_internal_governance(current_user):
        return 100.0

    stmt = select(GovernanceAction).where(
        GovernanceAction.deleted_at.is_(None),
        GovernanceAction.status == GovernanceActionStatus.COMPLETED,
        GovernanceAction.completed_at.is_not(None),
        func.date(GovernanceAction.completed_at) >= window_start,
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    completed = list((await session.execute(stmt)).scalars())
    if not completed:
        return 100.0

    on_time = 0
    for action in completed:
        if action.due_date is None:
            on_time += 1
            continue
        if action.completed_at is not None and action.completed_at.date() <= action.due_date:
            on_time += 1
    return round((on_time / len(completed)) * 100.0, 1)


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

    if can_read_internal_governance(current_user):
        actions_base = select(func.count()).select_from(GovernanceAction).where(
            GovernanceAction.deleted_at.is_(None)
        )
        actions_base = _apply_org_filter(actions_base, GovernanceAction.org_id, current_user)
        open_actions = await _count_query(
            session,
            actions_base.where(_open_action_filter(today)),
        )
        overdue_actions = await _count_query(
            session,
            actions_base.where(_overdue_action_filter(today)),
        )

        deps_base = select(func.count()).select_from(ProjectDependency).where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
        )
        deps_base = _apply_org_filter(deps_base, ProjectDependency.org_id, current_user)
        blocking_dependencies = await _count_query(session, deps_base)

        scope_base = select(func.count()).select_from(ProjectScopeState).where(
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
        )
        scope_base = _apply_org_filter(scope_base, ProjectScopeState.org_id, current_user)
        pending_scope = await _count_query(session, scope_base)

    esc_base = select(func.count()).select_from(GovernanceEscalation).where(
        GovernanceEscalation.deleted_at.is_(None),
        GovernanceEscalation.status.in_(
            {GovernanceEscalationStatus.OPEN, GovernanceEscalationStatus.IN_PROGRESS}
        ),
    )
    esc_base = _apply_org_filter(esc_base, GovernanceEscalation.org_id, current_user)
    if current_user.role == AppRole.CLIENT:
        project_ids = await _client_project_ids(session, current_user)
        if not project_ids:
            open_escalations = 0
            critical_escalations = 0
        else:
            esc_base = esc_base.where(GovernanceEscalation.project_id.in_(project_ids))
            open_escalations = await _count_query(session, esc_base)
            critical_escalations = await _count_query(
                session,
                esc_base.where(
                    GovernanceEscalation.severity.in_(
                        {
                            GovernanceEscalationSeverity.HIGH,
                            GovernanceEscalationSeverity.CRITICAL,
                        }
                    )
                ),
            )
    else:
        open_escalations = await _count_query(session, esc_base)
        critical_escalations = await _count_query(
            session,
            esc_base.where(
                GovernanceEscalation.severity.in_(
                    {
                        GovernanceEscalationSeverity.HIGH,
                        GovernanceEscalationSeverity.CRITICAL,
                    }
                )
            ),
        )

    sla_adherence_pct = await _compute_sla_adherence_pct(
        session,
        current_user,
        today=today,
        window_start=window_start,
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
