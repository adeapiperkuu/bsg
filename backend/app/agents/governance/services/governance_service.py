from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.agents.governance.analytics.sla import (
    dependency_overdue_days,
    dependency_overdue_days_for,
    effective_action_status,
    effective_action_status_for,
)
from app.agents.governance.schemas.governance import (
    GovernanceActionListRead,
    GovernanceActionRead,
    GovernanceEscalationListRead,
    GovernanceEscalationRead,
    ProjectDependencyListRead,
    ProjectDependencyRead,
)
from app.agents.governance.services.audit_service import (
    governance_snapshot,
    log_governance_event,
)
from app.agents.governance.timing import governance_db_timed
from app.agents.governance.services.notification_service import create_governance_notification
from app.agents.governance.services.project_governance_summary_service import (
    refresh_project_governance_summary,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceEvidenceLink,
    GovernanceScopeStatus,
    GovernanceSummaryStatus,
    GovernanceWeeklySummary,
    Project,
    ProjectAssignment,
    ProjectDependency,
    ProjectScopeState,
    User,
)
from app.services.scoping import get_visible_project

GOVERNANCE_READ_ROLES = {
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
    AppRole.CLIENT,
}
GOVERNANCE_WRITE_ROLES = {AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN}
DEPENDENCY_AUDIT_FIELDS = (
    "title",
    "description",
    "dependency_type",
    "owner_id",
    "due_date",
    "status",
    "resolved_at",
    "resolved_by",
    "deleted_at",
)
ESCALATION_AUDIT_FIELDS = (
    "title",
    "description",
    "severity",
    "status",
    "assigned_to",
    "resolved_at",
    "source_type",
    "source_id",
    "deleted_at",
)
ACTION_AUDIT_FIELDS = (
    "title",
    "description",
    "owner_id",
    "due_date",
    "status",
    "completed_at",
    "linked_knowledge_document_id",
    "deleted_at",
)
SCOPE_AUDIT_FIELDS = (
    "scope_status",
    "version_label",
    "notes",
    "linked_charter_document_id",
)
SUMMARY_AUDIT_FIELDS = (
    "summary_week",
    "summary_text",
    "status",
    "generated_by_ai",
    "approved_by",
    "approved_at",
)


@dataclass(frozen=True)
class GovernanceListFilters:
    limit: int = 50
    offset: int = 0
    project_id: UUID | None = None
    status: str | None = None
    severity: str | None = None
    dependency_type: str | None = None
    owner_id: UUID | None = None
    assigned_to: UUID | None = None
    search: str | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True)
class PaginatedGovernanceRows:
    items: list
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


def _bounded_list_filters(
    *,
    limit: int = 50,
    offset: int = 0,
    project_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    dependency_type: str | None = None,
    owner_id: UUID | None = None,
    assigned_to: UUID | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> GovernanceListFilters:
    return GovernanceListFilters(
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        project_id=project_id,
        status=status.strip() if status and status.strip() else None,
        severity=severity.strip() if severity and severity.strip() else None,
        dependency_type=dependency_type.strip() if dependency_type and dependency_type.strip() else None,
        owner_id=owner_id,
        assigned_to=assigned_to,
        search=search.strip() if search and search.strip() else None,
        date_from=date_from,
        date_to=date_to,
    )


def assert_can_read_governance(current_user: CurrentUser) -> None:
    if current_user.role not in GOVERNANCE_READ_ROLES:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")


def assert_can_write_governance(current_user: CurrentUser) -> None:
    if current_user.role not in GOVERNANCE_WRITE_ROLES:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")


def can_read_internal_governance(current_user: CurrentUser) -> bool:
    return current_user.role in {
        AppRole.DELIVERY_MANAGER,
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
    }


def _org_filter(current_user: CurrentUser) -> UUID | None:
    if current_user.role == AppRole.SUPER_ADMIN:
        return None
    return current_user.org_id


def _apply_org_filter(stmt: Select, model_org_column, current_user: CurrentUser) -> Select:
    org_id = _org_filter(current_user)
    if org_id is not None:
        stmt = stmt.where(model_org_column == org_id)
    return stmt


async def _client_project_ids(session: AsyncSession, current_user: CurrentUser) -> list[UUID]:
    rows = (
        (
            await session.execute(
                select(ProjectAssignment.project_id).where(
                    ProjectAssignment.user_id == current_user.id,
                    ProjectAssignment.is_active.is_(True),
                    ProjectAssignment.deleted_at.is_(None),
                    ProjectAssignment.org_id == current_user.org_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def scoped_dependencies_query(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[ProjectDependency]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = select(ProjectDependency).where(ProjectDependency.deleted_at.is_(None))
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    return list((await session.execute(stmt.order_by(ProjectDependency.due_date.asc()))).scalars())


async def scoped_actions_query(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceAction]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = select(GovernanceAction).where(GovernanceAction.deleted_at.is_(None))
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    return list((await session.execute(stmt.order_by(GovernanceAction.due_date.asc()))).scalars())


async def scoped_escalations_query(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceEscalation]:
    stmt = select(GovernanceEscalation).where(GovernanceEscalation.deleted_at.is_(None))
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    if current_user.role == AppRole.CLIENT:
        project_ids = await _client_project_ids(session, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(GovernanceEscalation.project_id.in_(project_ids))
    return list(
        (await session.execute(stmt.order_by(GovernanceEscalation.raised_at.desc()))).scalars()
    )


async def scoped_scope_states_query(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[ProjectScopeState]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = select(ProjectScopeState).where(ProjectScopeState.deleted_at.is_(None))
    stmt = _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _execute_paginated_rows(
    session: AsyncSession,
    stmt: Select,
    *,
    limit: int,
    offset: int,
    count_stmt: Select,
) -> PaginatedGovernanceRows:
    total = int((await session.execute(count_stmt)).scalar_one())
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
    if not rows:
        return PaginatedGovernanceRows(items=[], total=total, limit=limit, offset=offset)
    return PaginatedGovernanceRows(items=rows, total=total, limit=limit, offset=offset)


def _dependency_count_stmt(current_user: CurrentUser) -> Select:
    stmt = (
        select(func.count())
        .select_from(ProjectDependency)
        .where(ProjectDependency.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, ProjectDependency.org_id, current_user)


def _action_count_stmt(current_user: CurrentUser) -> Select:
    stmt = (
        select(func.count())
        .select_from(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, GovernanceAction.org_id, current_user)


def _escalation_count_stmt(current_user: CurrentUser) -> Select:
    stmt = (
        select(func.count())
        .select_from(GovernanceEscalation)
        .where(GovernanceEscalation.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)


def _scope_state_count_stmt(current_user: CurrentUser) -> Select:
    stmt = (
        select(func.count())
        .select_from(ProjectScopeState)
        .where(ProjectScopeState.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)


def _apply_dependency_page_filters(stmt: Select, filters: GovernanceListFilters) -> Select:
    if filters.project_id is not None:
        stmt = stmt.where(ProjectDependency.project_id == filters.project_id)
    if filters.status is not None:
        stmt = stmt.where(ProjectDependency.status == filters.status)
    if filters.dependency_type is not None:
        stmt = stmt.where(ProjectDependency.dependency_type == filters.dependency_type)
    if filters.owner_id is not None:
        stmt = stmt.where(ProjectDependency.owner_id == filters.owner_id)
    if filters.search is not None:
        stmt = stmt.where(_search_filter(ProjectDependency, filters.search))
    if filters.date_from is not None:
        stmt = stmt.where(ProjectDependency.due_date >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(ProjectDependency.due_date <= filters.date_to)
    return stmt


def _apply_action_page_filters(stmt: Select, filters: GovernanceListFilters) -> Select:
    if filters.project_id is not None:
        stmt = stmt.where(GovernanceAction.project_id == filters.project_id)
    if filters.status is not None:
        stmt = stmt.where(GovernanceAction.status == filters.status)
    if filters.owner_id is not None:
        stmt = stmt.where(GovernanceAction.owner_id == filters.owner_id)
    if filters.search is not None:
        stmt = stmt.where(_search_filter(GovernanceAction, filters.search))
    if filters.date_from is not None:
        stmt = stmt.where(GovernanceAction.due_date >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(GovernanceAction.due_date <= filters.date_to)
    return stmt


def _apply_escalation_page_filters(stmt: Select, filters: GovernanceListFilters) -> Select:
    if filters.project_id is not None:
        stmt = stmt.where(GovernanceEscalation.project_id == filters.project_id)
    if filters.status is not None:
        stmt = stmt.where(GovernanceEscalation.status == filters.status)
    if filters.severity is not None:
        stmt = stmt.where(GovernanceEscalation.severity == filters.severity)
    if filters.assigned_to is not None:
        stmt = stmt.where(GovernanceEscalation.assigned_to == filters.assigned_to)
    if filters.search is not None:
        stmt = stmt.where(_search_filter(GovernanceEscalation, filters.search))
    if filters.date_from is not None:
        stmt = stmt.where(func.date(GovernanceEscalation.raised_at) >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(func.date(GovernanceEscalation.raised_at) <= filters.date_to)
    return stmt


def _apply_scope_state_page_filters(stmt: Select, filters: GovernanceListFilters) -> Select:
    if filters.project_id is not None:
        stmt = stmt.where(ProjectScopeState.project_id == filters.project_id)
    if filters.status is not None:
        stmt = stmt.where(ProjectScopeState.scope_status == filters.status)
    if filters.search is not None:
        stmt = stmt.where(_search_filter(ProjectScopeState, filters.search))
    if filters.date_from is not None:
        stmt = stmt.where(func.date(ProjectScopeState.updated_at) >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(func.date(ProjectScopeState.updated_at) <= filters.date_to)
    return stmt


def _dependency_list_stmt(current_user: CurrentUser) -> Select:
    owner = aliased(User)
    stmt = (
        select(
            ProjectDependency.id,
            ProjectDependency.project_id,
            ProjectDependency.title,
            ProjectDependency.dependency_type,
            ProjectDependency.owner_id,
            ProjectDependency.due_date,
            ProjectDependency.status,
            Project.name.label("project_name"),
            func.coalesce(owner.full_name, owner.email).label("owner_name"),
        )
        .join(Project, Project.id == ProjectDependency.project_id)
        .outerjoin(owner, owner.id == ProjectDependency.owner_id)
        .where(ProjectDependency.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, ProjectDependency.org_id, current_user)


def _action_list_stmt(current_user: CurrentUser) -> Select:
    owner = aliased(User)
    stmt = (
        select(
            GovernanceAction.id,
            GovernanceAction.project_id,
            GovernanceAction.title,
            GovernanceAction.owner_id,
            GovernanceAction.due_date,
            GovernanceAction.status,
            Project.name.label("project_name"),
            func.coalesce(owner.full_name, owner.email).label("owner_name"),
        )
        .join(Project, Project.id == GovernanceAction.project_id)
        .outerjoin(owner, owner.id == GovernanceAction.owner_id)
        .where(GovernanceAction.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, GovernanceAction.org_id, current_user)


def _escalation_list_stmt(current_user: CurrentUser) -> Select:
    assignee = aliased(User)
    raiser = aliased(User)
    stmt = (
        select(
            GovernanceEscalation.id,
            GovernanceEscalation.project_id,
            GovernanceEscalation.title,
            GovernanceEscalation.severity,
            GovernanceEscalation.status,
            GovernanceEscalation.raised_at,
            GovernanceEscalation.source_type,
            GovernanceEscalation.source_id,
            Project.name.label("project_name"),
            func.coalesce(raiser.full_name, raiser.email).label("raised_by_name"),
            func.coalesce(assignee.full_name, assignee.email).label("assigned_to_name"),
        )
        .join(Project, Project.id == GovernanceEscalation.project_id)
        .outerjoin(raiser, raiser.id == GovernanceEscalation.raised_by)
        .outerjoin(assignee, assignee.id == GovernanceEscalation.assigned_to)
        .where(GovernanceEscalation.deleted_at.is_(None))
    )
    return _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)


def map_dependency_list_row(row) -> ProjectDependencyListRead:
    return ProjectDependencyListRead(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        dependency_type=row.dependency_type,
        owner_id=row.owner_id,
        due_date=row.due_date,
        status=row.status,
        overdue_days=dependency_overdue_days_for(row.due_date, row.status),
        project_name=row.project_name,
        owner_name=row.owner_name,
    )


def map_action_list_row(row) -> GovernanceActionListRead:
    return GovernanceActionListRead(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        owner_id=row.owner_id,
        due_date=row.due_date,
        status=effective_action_status_for(row.status, row.due_date),
        project_name=row.project_name,
        owner_name=row.owner_name,
    )


def map_escalation_list_row(row) -> GovernanceEscalationListRead:
    return GovernanceEscalationListRead(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        severity=row.severity,
        status=row.status,
        raised_at=row.raised_at,
        source_type=row.source_type,
        source_id=row.source_id,
        project_name=row.project_name,
        raised_by_name=row.raised_by_name,
        assigned_to_name=row.assigned_to_name,
    )


async def enriched_dependency_read(
    session: AsyncSession,
    dep: ProjectDependency,
) -> ProjectDependencyRead:
    owner = aliased(User)
    row = (
        await session.execute(
            select(
                Project.name.label("project_name"),
                func.coalesce(owner.full_name, owner.email).label("owner_name"),
            )
            .select_from(Project)
            .outerjoin(owner, owner.id == dep.owner_id)
            .where(Project.id == dep.project_id)
        )
    ).one()
    return ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
        update={
            "overdue_days": dependency_overdue_days(dep),
            "project_name": row.project_name,
            "owner_name": row.owner_name,
        }
    )


async def enriched_action_read(
    session: AsyncSession,
    action: GovernanceAction,
) -> GovernanceActionRead:
    owner = aliased(User)
    row = (
        await session.execute(
            select(
                Project.name.label("project_name"),
                func.coalesce(owner.full_name, owner.email).label("owner_name"),
            )
            .select_from(Project)
            .outerjoin(owner, owner.id == action.owner_id)
            .where(Project.id == action.project_id)
        )
    ).one()
    return GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
        update={
            "status": effective_action_status(action),
            "project_name": row.project_name,
            "owner_name": row.owner_name,
        }
    )


async def enriched_escalation_read(
    session: AsyncSession,
    escalation: GovernanceEscalation,
) -> GovernanceEscalationRead:
    assignee = aliased(User)
    raiser = aliased(User)
    row = (
        await session.execute(
            select(
                Project.name.label("project_name"),
                func.coalesce(raiser.full_name, raiser.email).label("raised_by_name"),
                func.coalesce(assignee.full_name, assignee.email).label("assigned_to_name"),
            )
            .select_from(Project)
            .outerjoin(raiser, raiser.id == escalation.raised_by)
            .outerjoin(assignee, assignee.id == escalation.assigned_to)
            .where(Project.id == escalation.project_id)
        )
    ).one()
    return GovernanceEscalationRead.model_validate(escalation, from_attributes=True).model_copy(
        update={
            "project_name": row.project_name,
            "raised_by_name": row.raised_by_name,
            "assigned_to_name": row.assigned_to_name,
        }
    )


def _search_filter(model, search: str):
    pattern = f"%{search}%"
    fields = [model.title.ilike(pattern)]
    description = getattr(model, "description", None)
    notes = getattr(model, "notes", None)
    version_label = getattr(model, "version_label", None)
    if description is not None:
        fields.append(description.ilike(pattern))
    if notes is not None:
        fields.append(notes.ilike(pattern))
    if version_label is not None:
        fields.append(version_label.ilike(pattern))
    return or_(*fields)


async def list_governance_dependencies_page(
    session: AsyncSession,
    current_user: CurrentUser,
    **raw_filters,
) -> PaginatedGovernanceRows:
    if not can_read_internal_governance(current_user):
        filters = _bounded_list_filters(**raw_filters)
        return PaginatedGovernanceRows(items=[], total=0, limit=filters.limit, offset=filters.offset)
    filters = _bounded_list_filters(**raw_filters)
    stmt = _dependency_list_stmt(current_user)
    count_stmt = _dependency_count_stmt(current_user)
    stmt = _apply_dependency_page_filters(stmt, filters)
    count_stmt = _apply_dependency_page_filters(count_stmt, filters)
    stmt = stmt.order_by(ProjectDependency.due_date.asc().nulls_last(), ProjectDependency.created_at.desc())
    return await _execute_paginated_rows(
        session, stmt, limit=filters.limit, offset=filters.offset, count_stmt=count_stmt
    )


async def list_governance_actions_page(
    session: AsyncSession,
    current_user: CurrentUser,
    **raw_filters,
) -> PaginatedGovernanceRows:
    if not can_read_internal_governance(current_user):
        filters = _bounded_list_filters(**raw_filters)
        return PaginatedGovernanceRows(items=[], total=0, limit=filters.limit, offset=filters.offset)
    filters = _bounded_list_filters(**raw_filters)
    stmt = _action_list_stmt(current_user)
    count_stmt = _action_count_stmt(current_user)
    stmt = _apply_action_page_filters(stmt, filters)
    count_stmt = _apply_action_page_filters(count_stmt, filters)
    stmt = stmt.order_by(GovernanceAction.due_date.asc().nulls_last(), GovernanceAction.created_at.desc())
    return await _execute_paginated_rows(
        session, stmt, limit=filters.limit, offset=filters.offset, count_stmt=count_stmt
    )


async def list_governance_escalations_page(
    session: AsyncSession,
    current_user: CurrentUser,
    **raw_filters,
) -> PaginatedGovernanceRows:
    filters = _bounded_list_filters(**raw_filters)
    stmt = _escalation_list_stmt(current_user)
    count_stmt = _escalation_count_stmt(current_user)
    if current_user.role == AppRole.CLIENT:
        project_ids = await _client_project_ids(session, current_user)
        if not project_ids:
            return PaginatedGovernanceRows(items=[], total=0, limit=filters.limit, offset=filters.offset)
        stmt = stmt.where(GovernanceEscalation.project_id.in_(project_ids))
        count_stmt = count_stmt.where(GovernanceEscalation.project_id.in_(project_ids))
    stmt = _apply_escalation_page_filters(stmt, filters)
    count_stmt = _apply_escalation_page_filters(count_stmt, filters)
    stmt = stmt.order_by(GovernanceEscalation.raised_at.desc(), GovernanceEscalation.created_at.desc())
    return await _execute_paginated_rows(
        session, stmt, limit=filters.limit, offset=filters.offset, count_stmt=count_stmt
    )


async def list_governance_scope_states_page(
    session: AsyncSession,
    current_user: CurrentUser,
    **raw_filters,
) -> PaginatedGovernanceRows:
    if not can_read_internal_governance(current_user):
        filters = _bounded_list_filters(**raw_filters)
        return PaginatedGovernanceRows(items=[], total=0, limit=filters.limit, offset=filters.offset)
    filters = _bounded_list_filters(**raw_filters)
    stmt = select(ProjectScopeState).where(ProjectScopeState.deleted_at.is_(None))
    stmt = _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)
    count_stmt = _scope_state_count_stmt(current_user)
    stmt = _apply_scope_state_page_filters(stmt, filters)
    count_stmt = _apply_scope_state_page_filters(count_stmt, filters)
    stmt = stmt.order_by(ProjectScopeState.updated_at.desc(), ProjectScopeState.created_at.desc())
    return await _execute_paginated_rows(
        session, stmt, limit=filters.limit, offset=filters.offset, count_stmt=count_stmt
    )


async def get_dependency_or_404(
    session: AsyncSession,
    dependency_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> ProjectDependency:
    if for_mutation:
        assert_can_write_governance(current_user)
    else:
        assert_can_read_governance(current_user)
        if not can_read_internal_governance(current_user):
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    stmt = select(ProjectDependency).where(
        ProjectDependency.id == dependency_id,
        ProjectDependency.deleted_at.is_(None),
    )
    org_id = _org_filter(current_user)
    if org_id is not None:
        stmt = stmt.where(ProjectDependency.org_id == org_id)

    dep = (await session.execute(stmt)).scalar_one_or_none()
    if dep is None:
        raise ApiError(
            404, "NOT_FOUND", "Dependency was not found.", {"dependency_id": str(dependency_id)}
        )
    return dep


async def get_escalation_or_404(
    session: AsyncSession,
    escalation_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> GovernanceEscalation:
    if for_mutation:
        assert_can_write_governance(current_user)
    else:
        assert_can_read_governance(current_user)

    stmt = select(GovernanceEscalation).where(
        GovernanceEscalation.id == escalation_id,
        GovernanceEscalation.deleted_at.is_(None),
    )
    org_id = _org_filter(current_user)
    if org_id is not None:
        stmt = stmt.where(GovernanceEscalation.org_id == org_id)

    escalation = (await session.execute(stmt)).scalar_one_or_none()
    if escalation is None:
        raise ApiError(
            404, "NOT_FOUND", "Escalation was not found.", {"escalation_id": str(escalation_id)}
        )

    if current_user.role == AppRole.CLIENT:
        project_ids = await _client_project_ids(session, current_user)
        if escalation.project_id not in project_ids:
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    return escalation


async def get_action_or_404(
    session: AsyncSession,
    action_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> GovernanceAction:
    if for_mutation:
        assert_can_write_governance(current_user)
    else:
        assert_can_read_governance(current_user)
        if not can_read_internal_governance(current_user):
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    stmt = select(GovernanceAction).where(
        GovernanceAction.id == action_id,
        GovernanceAction.deleted_at.is_(None),
    )
    org_id = _org_filter(current_user)
    if org_id is not None:
        stmt = stmt.where(GovernanceAction.org_id == org_id)

    action = (await session.execute(stmt)).scalar_one_or_none()
    if action is None:
        raise ApiError(
            404, "NOT_FOUND", "Governance action was not found.", {"action_id": str(action_id)}
        )
    return action


async def get_scope_state_for_project(
    session: AsyncSession,
    project_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> ProjectScopeState:
    if for_mutation:
        assert_can_write_governance(current_user)
    else:
        assert_can_read_governance(current_user)
        if not can_read_internal_governance(current_user):
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    await get_visible_project(session, project_id, current_user)

    stmt = select(ProjectScopeState).where(
        ProjectScopeState.project_id == project_id,
        ProjectScopeState.deleted_at.is_(None),
    )
    org_id = _org_filter(current_user)
    if org_id is not None:
        stmt = stmt.where(ProjectScopeState.org_id == org_id)

    scope = (await session.execute(stmt)).scalar_one_or_none()
    if scope is None:
        raise ApiError(
            404, "NOT_FOUND", "Scope state was not found.", {"project_id": str(project_id)}
        )
    return scope


async def create_dependency(
    session: AsyncSession,
    project_id: UUID,
    current_user: CurrentUser,
    *,
    title: str,
    description: str | None,
    dependency_type,
    owner_id: UUID | None,
    due_date,
    status,
) -> ProjectDependency:
    assert_can_write_governance(current_user)
    project = await get_visible_project(session, project_id, current_user)
    dep = ProjectDependency(
        org_id=project.org_id,
        project_id=project.id,
        title=title,
        description=description,
        dependency_type=dependency_type,
        owner_id=owner_id,
        due_date=due_date,
        status=status,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(dep)
    await session.flush()
    await log_governance_event(
        session,
        current_user,
        event_type="dependency.created",
        org_id=dep.org_id,
        project_id=dep.project_id,
        source_table="project_dependencies",
        source_id=dep.id,
        new_values=governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS),
    )
    if dep.status == GovernanceDependencyStatus.BLOCKING:
        await create_governance_notification(
            session,
            current_user,
            org_id=dep.org_id,
            project_id=dep.project_id,
            title="Blocking dependency created",
            body=dep.title,
            source_table="project_dependencies",
            source_row_id=dep.id,
        )
    await refresh_project_governance_summary(session, dep.org_id, dep.project_id)
    await session.commit()
    await session.refresh(dep)
    return dep


async def update_dependency(
    session: AsyncSession,
    dependency_id: UUID,
    current_user: CurrentUser,
    **fields,
) -> ProjectDependency:
    dep = await get_dependency_or_404(session, dependency_id, current_user, for_mutation=True)
    previous = governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS)
    for key, value in fields.items():
        if value is not None and hasattr(dep, key):
            setattr(dep, key, value)
    dep.updated_by = current_user.id
    await log_governance_event(
        session,
        current_user,
        event_type="dependency.updated",
        org_id=dep.org_id,
        project_id=dep.project_id,
        source_table="project_dependencies",
        source_id=dep.id,
        previous_values=previous,
        new_values=governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(session, dep.org_id, dep.project_id)
    await session.commit()
    await session.refresh(dep)
    return dep


async def resolve_dependency(
    session: AsyncSession,
    dependency_id: UUID,
    current_user: CurrentUser,
) -> ProjectDependency:
    dep = await get_dependency_or_404(session, dependency_id, current_user, for_mutation=True)
    previous = governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS)
    dep.status = GovernanceDependencyStatus.RESOLVED
    dep.resolved_at = datetime.now(UTC)
    dep.resolved_by = current_user.id
    dep.updated_by = current_user.id
    await log_governance_event(
        session,
        current_user,
        event_type="dependency.resolved",
        org_id=dep.org_id,
        project_id=dep.project_id,
        source_table="project_dependencies",
        source_id=dep.id,
        previous_values=previous,
        new_values=governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(session, dep.org_id, dep.project_id)
    await session.commit()
    await session.refresh(dep)
    return dep


async def soft_delete_dependency(
    session: AsyncSession,
    dependency_id: UUID,
    current_user: CurrentUser,
) -> None:
    dep = await get_dependency_or_404(session, dependency_id, current_user, for_mutation=True)
    previous = governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS)
    dep.deleted_at = datetime.now(UTC)
    dep.updated_by = current_user.id
    await log_governance_event(
        session,
        current_user,
        event_type="dependency.archived",
        org_id=dep.org_id,
        project_id=dep.project_id,
        source_table="project_dependencies",
        source_id=dep.id,
        previous_values=previous,
        new_values=governance_snapshot(dep, DEPENDENCY_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(session, dep.org_id, dep.project_id)
    await session.commit()


async def create_escalation(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID,
    title: str,
    description: str | None,
    severity,
    status,
    assigned_to: UUID | None,
    source_type=None,
    source_id: UUID | None = None,
) -> GovernanceEscalation:
    assert_can_write_governance(current_user)
    project = await get_visible_project(session, project_id, current_user)
    escalation = GovernanceEscalation(
        org_id=project.org_id,
        project_id=project.id,
        title=title,
        description=description,
        severity=severity,
        status=status,
        raised_by=current_user.id,
        assigned_to=assigned_to,
        source_type=source_type,
        source_id=source_id,
    )
    session.add(escalation)
    await session.flush()
    await log_governance_event(
        session,
        current_user,
        event_type="escalation.created",
        org_id=escalation.org_id,
        project_id=escalation.project_id,
        source_table="governance_escalations",
        source_id=escalation.id,
        new_values=governance_snapshot(escalation, ESCALATION_AUDIT_FIELDS),
    )
    if escalation.severity == GovernanceEscalationSeverity.CRITICAL:
        await create_governance_notification(
            session,
            current_user,
            org_id=escalation.org_id,
            project_id=escalation.project_id,
            title="Critical escalation created",
            body=escalation.title,
            source_table="governance_escalations",
            source_row_id=escalation.id,
        )
    await refresh_project_governance_summary(
        session, escalation.org_id, escalation.project_id
    )
    await session.commit()
    await session.refresh(escalation)
    return escalation


async def update_escalation(
    session: AsyncSession,
    escalation_id: UUID,
    current_user: CurrentUser,
    **fields,
) -> GovernanceEscalation:
    escalation = await get_escalation_or_404(
        session, escalation_id, current_user, for_mutation=True
    )
    previous = governance_snapshot(escalation, ESCALATION_AUDIT_FIELDS)
    for key, value in fields.items():
        if value is not None and hasattr(escalation, key):
            setattr(escalation, key, value)
    if (
        fields.get("status") == GovernanceEscalationStatus.RESOLVED
        and escalation.resolved_at is None
    ):
        escalation.resolved_at = datetime.now(UTC)
    event_type = (
        "escalation.resolved"
        if fields.get("status") == GovernanceEscalationStatus.RESOLVED
        else "escalation.updated"
    )
    await log_governance_event(
        session,
        current_user,
        event_type=event_type,
        org_id=escalation.org_id,
        project_id=escalation.project_id,
        source_table="governance_escalations",
        source_id=escalation.id,
        previous_values=previous,
        new_values=governance_snapshot(escalation, ESCALATION_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(
        session, escalation.org_id, escalation.project_id
    )
    await session.commit()
    await session.refresh(escalation)
    return escalation


async def soft_delete_escalation(
    session: AsyncSession,
    escalation_id: UUID,
    current_user: CurrentUser,
) -> None:
    escalation = await get_escalation_or_404(
        session, escalation_id, current_user, for_mutation=True
    )
    previous = governance_snapshot(escalation, ESCALATION_AUDIT_FIELDS)
    escalation.deleted_at = datetime.now(UTC)
    await log_governance_event(
        session,
        current_user,
        event_type="escalation.archived",
        org_id=escalation.org_id,
        project_id=escalation.project_id,
        source_table="governance_escalations",
        source_id=escalation.id,
        previous_values=previous,
        new_values=governance_snapshot(escalation, ESCALATION_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(
        session, escalation.org_id, escalation.project_id
    )
    await session.commit()


async def create_action(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID,
    title: str,
    description: str | None,
    owner_id: UUID | None,
    due_date,
    status,
    linked_knowledge_document_id: UUID | None = None,
) -> GovernanceAction:
    assert_can_write_governance(current_user)
    project = await get_visible_project(session, project_id, current_user)
    action = GovernanceAction(
        org_id=project.org_id,
        project_id=project.id,
        title=title,
        description=description,
        owner_id=owner_id,
        due_date=due_date,
        status=status,
        linked_knowledge_document_id=linked_knowledge_document_id,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(action)
    await session.flush()
    await log_governance_event(
        session,
        current_user,
        event_type="action.created",
        org_id=action.org_id,
        project_id=action.project_id,
        source_table="governance_actions",
        source_id=action.id,
        new_values=governance_snapshot(action, ACTION_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(session, action.org_id, action.project_id)
    await session.commit()
    await session.refresh(action)
    return action


async def update_action(
    session: AsyncSession,
    action_id: UUID,
    current_user: CurrentUser,
    **fields,
) -> GovernanceAction:
    action = await get_action_or_404(session, action_id, current_user, for_mutation=True)
    previous = governance_snapshot(action, ACTION_AUDIT_FIELDS)
    for key, value in fields.items():
        if key in fields and hasattr(action, key):
            setattr(action, key, value)
    if fields.get("status") == GovernanceActionStatus.COMPLETED and action.completed_at is None:
        action.completed_at = datetime.now(UTC)
    action.updated_by = current_user.id
    event_type = (
        "action.completed"
        if fields.get("status") == GovernanceActionStatus.COMPLETED
        else "action.updated"
    )
    await log_governance_event(
        session,
        current_user,
        event_type=event_type,
        org_id=action.org_id,
        project_id=action.project_id,
        source_table="governance_actions",
        source_id=action.id,
        previous_values=previous,
        new_values=governance_snapshot(action, ACTION_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(session, action.org_id, action.project_id)
    await session.commit()
    await session.refresh(action)
    return action


async def soft_delete_action(
    session: AsyncSession,
    action_id: UUID,
    current_user: CurrentUser,
) -> None:
    action = await get_action_or_404(session, action_id, current_user, for_mutation=True)
    previous = governance_snapshot(action, ACTION_AUDIT_FIELDS)
    action.deleted_at = datetime.now(UTC)
    action.updated_by = current_user.id
    await log_governance_event(
        session,
        current_user,
        event_type="action.archived",
        org_id=action.org_id,
        project_id=action.project_id,
        source_table="governance_actions",
        source_id=action.id,
        previous_values=previous,
        new_values=governance_snapshot(action, ACTION_AUDIT_FIELDS),
    )
    await refresh_project_governance_summary(session, action.org_id, action.project_id)
    await session.commit()


async def update_scope_state(
    session: AsyncSession,
    project_id: UUID,
    current_user: CurrentUser,
    *,
    scope_status=None,
    version_label: str | None = None,
    notes: str | None = None,
    linked_charter_document_id: UUID | None = None,
) -> ProjectScopeState:
    assert_can_write_governance(current_user)
    project = await get_visible_project(session, project_id, current_user)

    scope = (
        await session.execute(
            select(ProjectScopeState).where(
                ProjectScopeState.project_id == project_id,
                ProjectScopeState.org_id == project.org_id,
                ProjectScopeState.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if scope is None:
        scope = ProjectScopeState(
            org_id=project.org_id,
            project_id=project.id,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        session.add(scope)
        previous = None
    else:
        previous = governance_snapshot(scope, SCOPE_AUDIT_FIELDS)

    if scope_status is not None:
        scope.scope_status = scope_status
    if version_label is not None:
        scope.version_label = version_label
    if notes is not None:
        scope.notes = notes
    if linked_charter_document_id is not None:
        scope.linked_charter_document_id = linked_charter_document_id
    scope.updated_by = current_user.id
    await session.flush()
    await log_governance_event(
        session,
        current_user,
        event_type="scope.updated",
        org_id=scope.org_id,
        project_id=scope.project_id,
        source_table="project_scope_states",
        source_id=scope.id,
        previous_values=previous,
        new_values=governance_snapshot(scope, SCOPE_AUDIT_FIELDS),
    )
    if scope.scope_status == GovernanceScopeStatus.PENDING_REVISION:
        await create_governance_notification(
            session,
            current_user,
            org_id=scope.org_id,
            project_id=scope.project_id,
            title="Scope awaiting approval",
            body=f"Scope version {scope.version_label} is pending revision.",
            source_table="project_scope_states",
            source_row_id=scope.id,
        )
    await refresh_project_governance_summary(session, scope.org_id, scope.project_id)
    await session.commit()
    await session.refresh(scope)
    return scope


async def create_weekly_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    summary_week,
    summary_text: str,
    evidence_links: list,
) -> GovernanceWeeklySummary:
    assert_can_write_governance(current_user)
    org_id = current_user.org_id
    summary = GovernanceWeeklySummary(
        org_id=org_id,
        summary_week=summary_week,
        summary_text=summary_text,
        status=GovernanceSummaryStatus.DRAFT,
        generated_by_ai=False,
    )
    session.add(summary)
    await session.flush()
    for link in evidence_links:
        session.add(
            GovernanceEvidenceLink(
                org_id=org_id,
                summary_id=summary.id,
                source_type=link.source_type,
                source_id=link.source_id,
            )
        )
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.created",
        org_id=summary.org_id,
        source_table="governance_weekly_summaries",
        source_id=summary.id,
        new_values=governance_snapshot(summary, SUMMARY_AUDIT_FIELDS),
        metadata={"evidence_link_count": len(evidence_links)},
    )
    await session.commit()
    await session.refresh(summary)
    return summary


def _leadership_sees_summary_only_if_approved(
    current_user: CurrentUser,
    summary: GovernanceWeeklySummary,
) -> bool:
    restricted_to_approved = current_user.role in {AppRole.BSG_LEADERSHIP, AppRole.CLIENT}
    return not (restricted_to_approved and summary.status != GovernanceSummaryStatus.APPROVED)


async def get_weekly_summary_by_id(
    session: AsyncSession,
    summary_id: UUID,
    current_user: CurrentUser,
) -> GovernanceWeeklySummary:
    assert_can_read_governance(current_user)
    stmt = select(GovernanceWeeklySummary).where(GovernanceWeeklySummary.id == summary_id)
    stmt = _apply_org_filter(stmt, GovernanceWeeklySummary.org_id, current_user)
    summary = (await session.execute(stmt)).scalar_one_or_none()
    if summary is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Weekly summary was not found.",
            {"summary_id": str(summary_id)},
        )
    if not _leadership_sees_summary_only_if_approved(current_user, summary):
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
    return summary


async def list_weekly_summaries(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    limit: int = 20,
) -> list[GovernanceWeeklySummary]:
    assert_can_read_governance(current_user)
    if current_user.role == AppRole.CLIENT:
        return []
    stmt = select(GovernanceWeeklySummary)
    stmt = _apply_org_filter(stmt, GovernanceWeeklySummary.org_id, current_user)
    if current_user.role == AppRole.BSG_LEADERSHIP:
        stmt = stmt.where(GovernanceWeeklySummary.status == GovernanceSummaryStatus.APPROVED)
    stmt = stmt.order_by(GovernanceWeeklySummary.summary_week.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def update_weekly_summary_draft(
    session: AsyncSession,
    summary_id: UUID,
    current_user: CurrentUser,
    *,
    summary_text: str,
) -> GovernanceWeeklySummary:
    assert_can_write_governance(current_user)
    summary = await get_weekly_summary_by_id(session, summary_id, current_user)
    if summary.status != GovernanceSummaryStatus.DRAFT:
        raise ApiError(409, "SUMMARY_NOT_EDITABLE", "Only draft summaries can be edited.")
    previous = governance_snapshot(summary, SUMMARY_AUDIT_FIELDS)
    summary.summary_text = summary_text
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.updated",
        org_id=summary.org_id,
        source_table="governance_weekly_summaries",
        source_id=summary.id,
        previous_values=previous,
        new_values=governance_snapshot(summary, SUMMARY_AUDIT_FIELDS),
    )
    await session.commit()
    await session.refresh(summary)
    return summary


async def approve_weekly_summary(
    session: AsyncSession,
    summary_id: UUID,
    current_user: CurrentUser,
) -> GovernanceWeeklySummary:
    assert_can_write_governance(current_user)
    summary = await get_weekly_summary_by_id(session, summary_id, current_user)
    if summary.status != GovernanceSummaryStatus.DRAFT:
        raise ApiError(409, "SUMMARY_NOT_APPROVABLE", "Only draft summaries can be approved.")
    previous = governance_snapshot(summary, SUMMARY_AUDIT_FIELDS)
    summary.status = GovernanceSummaryStatus.APPROVED
    summary.approved_by = current_user.id
    summary.approved_at = datetime.now(UTC)
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.approved",
        org_id=summary.org_id,
        source_table="governance_weekly_summaries",
        source_id=summary.id,
        previous_values=previous,
        new_values=governance_snapshot(summary, SUMMARY_AUDIT_FIELDS),
    )
    await session.commit()
    await session.refresh(summary)
    return summary


async def get_latest_weekly_summary(
    session: AsyncSession,
    current_user: CurrentUser,
) -> GovernanceWeeklySummary | None:
    assert_can_read_governance(current_user)
    stmt = select(GovernanceWeeklySummary).order_by(GovernanceWeeklySummary.summary_week.desc())
    stmt = _apply_org_filter(stmt, GovernanceWeeklySummary.org_id, current_user)
    if current_user.role == AppRole.CLIENT:
        return None
    summary = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if summary is None:
        return None
    if not _leadership_sees_summary_only_if_approved(current_user, summary):
        return None
    return summary


async def load_user_names(session: AsyncSession, user_ids: set[UUID]) -> dict[UUID, str]:
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(user_ids))
        )
    ).all()
    return {row.id: (row.full_name or row.email) for row in rows}


async def load_project_names(session: AsyncSession, project_ids: set[UUID]) -> dict[UUID, str]:
    if not project_ids:
        return {}
    rows = (
        await session.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
    ).all()
    return {row.id: row.name for row in rows}


_GOVERNANCE_DB_TIMED = (
    "list_governance_dependencies_page",
    "list_governance_actions_page",
    "list_governance_escalations_page",
    "list_governance_scope_states_page",
    "_client_project_ids",
    "_execute_paginated_rows",
    "load_user_names",
    "load_project_names",
    "get_dependency_or_404",
    "get_escalation_or_404",
    "get_action_or_404",
    "enriched_dependency_read",
    "enriched_action_read",
    "enriched_escalation_read",
    "get_scope_state_for_project",
    "create_dependency",
    "update_dependency",
    "resolve_dependency",
    "soft_delete_dependency",
    "create_escalation",
    "update_escalation",
    "soft_delete_escalation",
    "create_action",
    "update_action",
    "soft_delete_action",
    "update_scope_state",
    "create_weekly_summary",
    "get_weekly_summary_by_id",
    "list_weekly_summaries",
    "update_weekly_summary_draft",
    "approve_weekly_summary",
    "get_latest_weekly_summary",
)
for _name in _GOVERNANCE_DB_TIMED:
    globals()[_name] = governance_db_timed(globals()[_name])
