from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import GovernanceRegisterRowRead
from app.agents.governance.services.dashboard_service import _overdue_action_filter
from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
    _apply_org_filter,
    _bounded_list_filters,
    _client_project_ids,
    _execute_paginated_rows,
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


def _compute_register_health(
    *,
    scope_status: GovernanceScopeStatus | None,
    critical_escalations: int,
    blocking_overdue_dependencies: int,
    open_escalations: int,
    overdue_actions: int,
) -> str:
    if critical_escalations > 0 or blocking_overdue_dependencies > 0:
        return "red"
    if (
        open_escalations > 0
        or scope_status == GovernanceScopeStatus.PENDING_REVISION
        or overdue_actions > 0
    ):
        return "amber"
    return "green"


def _dependency_stats_subquery(current_user: CurrentUser, *, today: date):
    stmt = (
        select(
            ProjectDependency.project_id.label("project_id"),
            func.count()
            .filter(
                ProjectDependency.status.in_(
                    {
                        GovernanceDependencyStatus.OPEN,
                        GovernanceDependencyStatus.BLOCKING,
                    }
                )
            )
            .label("open_dependencies"),
            func.count()
            .filter(ProjectDependency.status == GovernanceDependencyStatus.BLOCKING)
            .label("blocking_dependencies"),
            func.count()
            .filter(
                and_(
                    ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
                    ProjectDependency.due_date.is_not(None),
                    ProjectDependency.due_date < today,
                )
            )
            .label("blocking_overdue_dependencies"),
        )
        .where(ProjectDependency.deleted_at.is_(None))
        .group_by(ProjectDependency.project_id)
    )
    return _apply_org_filter(stmt, ProjectDependency.org_id, current_user).subquery()


def _action_stats_subquery(current_user: CurrentUser, *, today: date):
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
        select(
            GovernanceAction.project_id.label("project_id"),
            func.count().filter(open_filter).label("open_actions"),
            func.count().filter(_overdue_action_filter(today)).label("overdue_actions"),
        )
        .where(GovernanceAction.deleted_at.is_(None))
        .group_by(GovernanceAction.project_id)
    )
    return _apply_org_filter(stmt, GovernanceAction.org_id, current_user).subquery()


def _escalation_stats_subquery(current_user: CurrentUser):
    open_filter = GovernanceEscalation.status.in_(
        {GovernanceEscalationStatus.OPEN, GovernanceEscalationStatus.IN_PROGRESS}
    )
    stmt = (
        select(
            GovernanceEscalation.project_id.label("project_id"),
            func.count().filter(open_filter).label("open_escalations"),
            func.count()
            .filter(
                and_(
                    open_filter,
                    GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
                )
            )
            .label("critical_escalations"),
        )
        .where(GovernanceEscalation.deleted_at.is_(None))
        .group_by(GovernanceEscalation.project_id)
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    return stmt.subquery()


async def list_governance_register_page(
    session: AsyncSession,
    current_user: CurrentUser,
    **raw_filters,
) -> PaginatedGovernanceRows:
    filters = _bounded_list_filters(**raw_filters)
    today = datetime.now(UTC).date()
    can_internal = can_read_internal_governance(current_user)

    visible_projects = scoped_project_query(current_user).subquery()
    dep_stats = _dependency_stats_subquery(current_user, today=today) if can_internal else None
    action_stats = _action_stats_subquery(current_user, today=today) if can_internal else None
    esc_stats = _escalation_stats_subquery(current_user)

    open_deps = (
        func.coalesce(dep_stats.c.open_dependencies, 0) if dep_stats is not None else 0
    )
    blocking_deps = (
        func.coalesce(dep_stats.c.blocking_dependencies, 0) if dep_stats is not None else 0
    )
    blocking_overdue = (
        func.coalesce(dep_stats.c.blocking_overdue_dependencies, 0)
        if dep_stats is not None
        else 0
    )
    open_actions = func.coalesce(action_stats.c.open_actions, 0) if action_stats is not None else 0
    overdue_actions = (
        func.coalesce(action_stats.c.overdue_actions, 0) if action_stats is not None else 0
    )
    open_escalations = func.coalesce(esc_stats.c.open_escalations, 0)
    critical_escalations = func.coalesce(esc_stats.c.critical_escalations, 0)

    stmt = (
        select(
            Project.id.label("project_id"),
            Project.name.label("project_name"),
            ProjectScopeState.scope_status.label("scope_status"),
            ProjectScopeState.version_label.label("scope_version"),
            open_deps.label("open_dependencies"),
            blocking_deps.label("blocking_dependencies"),
            blocking_overdue.label("blocking_overdue_dependencies"),
            open_actions.label("open_actions"),
            overdue_actions.label("overdue_actions"),
            open_escalations.label("open_escalations"),
            critical_escalations.label("critical_escalations"),
        )
        .select_from(Project)
        .join(visible_projects, visible_projects.c.id == Project.id)
        .outerjoin(
            ProjectScopeState,
            and_(
                ProjectScopeState.project_id == Project.id,
                ProjectScopeState.deleted_at.is_(None),
            ),
        )
        .outerjoin(esc_stats, esc_stats.c.project_id == Project.id)
    )

    if can_internal:
        assert dep_stats is not None and action_stats is not None
        stmt = stmt.outerjoin(dep_stats, dep_stats.c.project_id == Project.id).outerjoin(
            action_stats, action_stats.c.project_id == Project.id
        )

    if current_user.role == AppRole.CLIENT:
        project_ids = await _client_project_ids(session, current_user)
        if not project_ids:
            return PaginatedGovernanceRows(items=[], total=0, limit=filters.limit, offset=filters.offset)
        stmt = stmt.where(Project.id.in_(project_ids))

    if filters.project_id is not None:
        stmt = stmt.where(Project.id == filters.project_id)
    if filters.status is not None:
        stmt = stmt.where(ProjectScopeState.scope_status == filters.status)
    if filters.search is not None:
        pattern = f"%{filters.search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Project.name).like(pattern),
                func.lower(func.cast(Project.id, String)).like(pattern),
            )
        )

    stmt = stmt.order_by(Project.name.asc())
    page = await _execute_paginated_rows(session, stmt, limit=filters.limit, offset=filters.offset)

    items = [
        GovernanceRegisterRowRead(
            project_id=row.project_id,
            project_name=row.project_name,
            scope_status=row.scope_status,
            scope_version=row.scope_version,
            open_dependencies=int(row.open_dependencies or 0),
            blocking_dependencies=int(row.blocking_dependencies or 0),
            open_actions=int(row.open_actions or 0),
            open_escalations=int(row.open_escalations or 0),
            health=_compute_register_health(
                scope_status=row.scope_status,
                critical_escalations=int(row.critical_escalations or 0),
                blocking_overdue_dependencies=int(row.blocking_overdue_dependencies or 0),
                open_escalations=int(row.open_escalations or 0),
                overdue_actions=int(row.overdue_actions or 0),
            ),
        )
        for row in page.items
    ]
    return PaginatedGovernanceRows(
        items=items,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


list_governance_register_page = governance_db_timed(list_governance_register_page)
