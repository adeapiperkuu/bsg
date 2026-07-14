from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID

from sqlalchemy import String, and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.constants import (
    CACHE_SHAPE_FIRST_PAINT_UNFILTERED,
    CACHE_SHAPE_LEGACY_FIRST_PAGE,
    CACHE_SHAPE_UNCACHED_FILTERED,
    CACHE_SHAPE_UNCACHED_LIMIT,
    CACHE_SHAPE_UNCACHED_OFFSET,
    GOVERNANCE_FIRST_PAINT_LIMIT,
    GOVERNANCE_FIRST_PAINT_OFFSET,
    REGISTER_CACHEABLE_LIMITS,
)
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
from app.agents.governance.timing import get_governance_timer, governance_db_timed
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceScopeStatus,
    Project,
    ProjectGovernanceSummary,
    ProjectScopeState,
)
from app.services.scoping import scoped_project_query

logger = logging.getLogger(__name__)

REGISTER_LIST_CACHE_TTL = timedelta(seconds=60)
_register_list_cache: dict[
    tuple[UUID | None, str, UUID, int, int],
    tuple[datetime, PaginatedGovernanceRows],
] = {}


def _register_cache_key(
    current_user: CurrentUser,
    *,
    limit: int,
    offset: int,
) -> tuple[UUID | None, str, UUID, int, int]:
    """Isolate by org, role, and user.

    DM/leadership share org-wide project visibility; clients are assignment-scoped via
    scoped_project_query, so user_id is required. Super admin uses org_id=None.
    """
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id
    return (org_id, current_user.role.value, current_user.id, limit, offset)


def _register_has_filters(*, project_id, status, search) -> bool:
    return project_id is not None or status is not None or search is not None


def _register_cache_shape(*, limit: int, offset: int, project_id, status, search) -> str:
    if offset != GOVERNANCE_FIRST_PAINT_OFFSET:
        return CACHE_SHAPE_UNCACHED_OFFSET
    if _register_has_filters(project_id=project_id, status=status, search=search):
        return CACHE_SHAPE_UNCACHED_FILTERED
    if limit == GOVERNANCE_FIRST_PAINT_LIMIT:
        return CACHE_SHAPE_FIRST_PAINT_UNFILTERED
    if limit in {25, 50}:
        return CACHE_SHAPE_LEGACY_FIRST_PAGE
    return CACHE_SHAPE_UNCACHED_LIMIT


def _is_default_register_cacheable(
    *,
    limit: int,
    offset: int,
    project_id,
    status,
    search,
) -> bool:
    return (
        offset == GOVERNANCE_FIRST_PAINT_OFFSET
        and not _register_has_filters(project_id=project_id, status=status, search=search)
        and limit in REGISTER_CACHEABLE_LIMITS
    )


def invalidate_register_list_cache() -> int:
    removed = len(_register_list_cache)
    _register_list_cache.clear()
    return removed


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
    )
    cache_shape = _register_cache_shape(
        limit=filters.limit,
        offset=filters.offset,
        project_id=filters.project_id,
        status=filters.status,
        search=filters.search,
    )
    now = datetime.now(UTC)
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            limit=filters.limit,
            offset=filters.offset,
            cache_eligible=cacheable,
            cache_shape=cache_shape,
            filtered=_register_has_filters(
                project_id=filters.project_id,
                status=filters.status,
                search=filters.search,
            ),
        )
    if cacheable:
        cached = _register_list_cache.get(cache_key)
        if cached and now - cached[0] < REGISTER_LIST_CACHE_TTL:
            if timer is not None:
                timer.record_meta(
                    execute_count=0,
                    cache_hit=True,
                    cache_scope="user_access",
                )
            return replace(cached[1], db_executes=0)

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

    if timer is not None:
        timer.record_meta(
            execute_count=db_executes,
            cache_hit=False,
            cache_scope="user_access",
        )

    elapsed_ms = round((perf_counter() - started) * 1000, 1)
    if elapsed_ms >= 200:
        logger.info(
            "governance_register_list_profile total_ms=%s db_executes=%s row_count=%s "
            "limit=%s offset=%s cached=%s cache_shape=%s",
            elapsed_ms,
            db_executes,
            len(items),
            filters.limit,
            filters.offset,
            False,
            cache_shape,
        )

    return result


list_governance_register_page = governance_db_timed(list_governance_register_page)
