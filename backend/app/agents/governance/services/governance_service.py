from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.services.audit_service import (
    governance_snapshot,
    log_governance_event,
)
from app.agents.governance.services.notification_service import create_governance_notification
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
    dep.resolved_at = datetime.now(timezone.utc)
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
    dep.deleted_at = datetime.now(timezone.utc)
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
        escalation.resolved_at = datetime.now(timezone.utc)
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
    escalation.deleted_at = datetime.now(timezone.utc)
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
        action.completed_at = datetime.now(timezone.utc)
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
    action.deleted_at = datetime.now(timezone.utc)
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
    summary.approved_at = datetime.now(timezone.utc)
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
