from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import and_, func, literal, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import GovernanceRegisterRowRead
from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
    _bounded_list_filters,
    _execute_paginated_rows,
    can_read_internal_governance,
)
from app.agents.governance.services.project_governance_summary_service import (
    ensure_org_time_sensitive_summary_counts,
)
from app.agents.governance.timing import governance_db_timed
from app.core.security import CurrentUser
from app.db.models import (
    GovernanceScopeStatus,
    Project,
    ProjectGovernanceSummary,
    ProjectScopeState,
)
from app.services.scoping import scoped_project_query

logger = logging.getLogger(__name__)

REGISTER_LIST_CACHE_TTL = timedelta(seconds=60)
_register_list_cache: dict[
    tuple[str, str | None, str | None, str | None, int, int],
    tuple[datetime, PaginatedGovernanceRows],
] = {}


def _register_cache_key(
    current_user: CurrentUser,
    *,
    limit: int,
    offset: int,
    project_id,
    status,
    search,
) -> tuple[str, str | None, str | None, str | None, int, int]:
    return (
        str(current_user.id),
        str(project_id) if project_id is not None else None,
        status,
        search,
        limit,
        offset,
    )


def _is_default_register_cacheable(
    *,
    limit: int,
    offset: int,
    project_id,
    status,
    search,
) -> bool:
    return (
        offset == 0
        and project_id is None
        and status is None
        and search is None
        and limit in {25, 50}
    )


def invalidate_register_list_cache() -> None:
    _register_list_cache.clear()


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


async def list_governance_register_page(
    session: AsyncSession,
    current_user: CurrentUser,
    **raw_filters,
) -> PaginatedGovernanceRows:
    filters = _bounded_list_filters(**raw_filters)
    today = datetime.now(UTC).date()
    can_internal = can_read_internal_governance(current_user)
    cacheable = _is_default_register_cacheable(
        limit=filters.limit,
        offset=filters.offset,
        project_id=filters.project_id,
        status=filters.status,
        search=filters.search,
    )
    cache_key = _register_cache_key(
        current_user,
        limit=filters.limit,
        offset=filters.offset,
        project_id=filters.project_id,
        status=filters.status,
        search=filters.search,
    )
    now = datetime.now(UTC)
    if cacheable:
        cached = _register_list_cache.get(cache_key)
        if cached and now - cached[0] < REGISTER_LIST_CACHE_TTL:
            return cached[1]

    started = perf_counter()
    db_executes = 0
    if current_user.org_id is not None:
        db_executes += await ensure_org_time_sensitive_summary_counts(
            session, current_user.org_id, today=today
        )

    visible_projects = scoped_project_query(current_user).subquery()
    summary = ProjectGovernanceSummary

    open_deps = (
        func.coalesce(summary.open_dependencies_count, 0) if can_internal else literal(0)
    )
    blocking_deps = (
        func.coalesce(summary.blocked_dependencies_count, 0) if can_internal else literal(0)
    )
    blocking_overdue = (
        func.coalesce(summary.blocking_overdue_dependencies_count, 0)
        if can_internal
        else literal(0)
    )
    open_actions = func.coalesce(summary.open_actions_count, 0) if can_internal else literal(0)
    overdue_actions = (
        func.coalesce(summary.overdue_actions_count, 0) if can_internal else literal(0)
    )
    open_escalations = func.coalesce(summary.open_escalations_count, 0)
    critical_escalations = func.coalesce(summary.critical_escalations_count, 0)

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
        .outerjoin(
            summary,
            and_(
                summary.project_id == Project.id,
                summary.org_id == Project.org_id,
            ),
        )
    )

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

    count_stmt = (
        select(func.count())
        .select_from(Project)
        .join(visible_projects, visible_projects.c.id == Project.id)
    )
    if filters.project_id is not None:
        count_stmt = count_stmt.where(Project.id == filters.project_id)
    if filters.status is not None:
        count_stmt = count_stmt.join(
            ProjectScopeState,
            and_(
                ProjectScopeState.project_id == Project.id,
                ProjectScopeState.deleted_at.is_(None),
            ),
        ).where(ProjectScopeState.scope_status == filters.status)
    if filters.search is not None:
        pattern = f"%{filters.search.lower()}%"
        count_stmt = count_stmt.where(
            or_(
                func.lower(Project.name).like(pattern),
                func.lower(func.cast(Project.id, String)).like(pattern),
            )
        )

    page = await _execute_paginated_rows(
        session,
        stmt,
        limit=filters.limit,
        offset=filters.offset,
        count_stmt=count_stmt,
    )
    db_executes += page.db_executes

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
    result = PaginatedGovernanceRows(
        items=items,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        db_executes=db_executes,
    )

    if cacheable:
        _register_list_cache[cache_key] = (now, result)

    elapsed_ms = round((perf_counter() - started) * 1000, 1)
    if elapsed_ms >= 200:
        logger.info(
            "governance_register_list_profile total_ms=%s db_executes=%s row_count=%s "
            "limit=%s offset=%s cached=%s",
            elapsed_ms,
            db_executes,
            len(items),
            filters.limit,
            filters.offset,
            False,
        )

    return result


list_governance_register_page = governance_db_timed(list_governance_register_page)
