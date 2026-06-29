from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.agents.governance.analytics.sla import dependency_overdue_days, effective_action_status
from app.agents.governance.schemas.governance import (
    GovernanceActionCreate,
    GovernanceActionRead,
    GovernanceActionUpdate,
    GovernanceBootstrapRead,
    GovernanceEscalationCreate,
    GovernanceEscalationRead,
    GovernanceEscalationUpdate,
    GovernanceEvidenceLinkRead,
    GovernanceWeeklySummaryCreate,
    GovernanceWeeklySummaryRead,
    ProjectDependencyCreate,
    ProjectDependencyRead,
    ProjectDependencyUpdate,
    ProjectScopeStateRead,
    ProjectScopeStateUpdate,
)
from app.agents.governance.services.dashboard_service import get_governance_bootstrap
from app.agents.governance.services.governance_service import (
    create_action,
    create_dependency,
    create_escalation,
    create_weekly_summary,
    get_latest_weekly_summary,
    get_scope_state_for_project,
    load_project_names,
    load_user_names,
    resolve_dependency,
    scoped_actions_query,
    scoped_dependencies_query,
    scoped_escalations_query,
    update_action,
    update_dependency,
    update_escalation,
    update_scope_state,
)
from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, GovernanceEvidenceLink, GovernanceSummaryStatus
from app.schemas.common import DataResponse, ListResponse, Pagination

router = APIRouter(tags=["governance"])

READ_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN, AppRole.CLIENT)
WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)


@router.get("/governance/bootstrap", response_model=DataResponse[GovernanceBootstrapRead])
async def governance_bootstrap(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceBootstrapRead]:
    return DataResponse(data=await get_governance_bootstrap(session, current_user))


@router.get(
    "/projects/{project_id}/dependencies", response_model=ListResponse[ProjectDependencyRead]
)
async def list_project_dependencies(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[ProjectDependencyRead]:
    deps = [
        d
        for d in await scoped_dependencies_query(session, current_user)
        if d.project_id == project_id
    ]
    project_names = await load_project_names(session, {project_id})
    user_names = await load_user_names(session, {d.owner_id for d in deps if d.owner_id})
    data = [
        ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={
                "overdue_days": dependency_overdue_days(dep),
                "project_name": project_names.get(project_id),
                "owner_name": user_names.get(dep.owner_id) if dep.owner_id else None,
            }
        )
        for dep in deps
    ]
    return ListResponse(data=data, pagination=Pagination(limit=len(data)))


@router.post(
    "/projects/{project_id}/dependencies", response_model=DataResponse[ProjectDependencyRead]
)
async def create_project_dependency(
    project_id: UUID,
    payload: ProjectDependencyCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await create_dependency(
        session,
        project_id,
        current_user,
        title=payload.title,
        description=payload.description,
        dependency_type=payload.dependency_type,
        owner_id=payload.owner_id,
        due_date=payload.due_date,
        status=payload.status,
    )
    return DataResponse(
        data=ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={"overdue_days": dependency_overdue_days(dep)}
        )
    )


@router.patch("/dependencies/{dependency_id}", response_model=DataResponse[ProjectDependencyRead])
async def patch_dependency(
    dependency_id: UUID,
    payload: ProjectDependencyUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await update_dependency(
        session,
        dependency_id,
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    return DataResponse(
        data=ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={"overdue_days": dependency_overdue_days(dep)}
        )
    )


@router.post(
    "/dependencies/{dependency_id}/resolve", response_model=DataResponse[ProjectDependencyRead]
)
async def resolve_project_dependency(
    dependency_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await resolve_dependency(session, dependency_id, current_user)
    return DataResponse(
        data=ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={"overdue_days": 0}
        )
    )


@router.get("/governance/escalations", response_model=ListResponse[GovernanceEscalationRead])
async def list_escalations(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[GovernanceEscalationRead]:
    escalations = await scoped_escalations_query(session, current_user)
    project_names = await load_project_names(session, {e.project_id for e in escalations})
    user_ids = {
        *(e.raised_by for e in escalations if e.raised_by),
        *(e.assigned_to for e in escalations if e.assigned_to),
    }
    user_names = await load_user_names(session, user_ids)
    data = [
        GovernanceEscalationRead.model_validate(esc, from_attributes=True).model_copy(
            update={
                "project_name": project_names.get(esc.project_id),
                "raised_by_name": user_names.get(esc.raised_by) if esc.raised_by else None,
                "assigned_to_name": user_names.get(esc.assigned_to) if esc.assigned_to else None,
            }
        )
        for esc in escalations
    ]
    return ListResponse(data=data, pagination=Pagination(limit=len(data)))


@router.post("/governance/escalations", response_model=DataResponse[GovernanceEscalationRead])
async def create_governance_escalation(
    payload: GovernanceEscalationCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await create_escalation(
        session,
        current_user,
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        status=payload.status,
        assigned_to=payload.assigned_to,
    )
    return DataResponse(
        data=GovernanceEscalationRead.model_validate(escalation, from_attributes=True)
    )


@router.patch(
    "/governance/escalations/{escalation_id}", response_model=DataResponse[GovernanceEscalationRead]
)
async def patch_escalation(
    escalation_id: UUID,
    payload: GovernanceEscalationUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await update_escalation(
        session,
        escalation_id,
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    return DataResponse(
        data=GovernanceEscalationRead.model_validate(escalation, from_attributes=True)
    )


@router.get("/governance/actions", response_model=ListResponse[GovernanceActionRead])
async def list_governance_actions(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[GovernanceActionRead]:
    actions = await scoped_actions_query(session, current_user)
    project_names = await load_project_names(session, {a.project_id for a in actions})
    user_names = await load_user_names(session, {a.owner_id for a in actions if a.owner_id})
    data = [
        GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
            update={
                "status": effective_action_status(action),
                "project_name": project_names.get(action.project_id),
                "owner_name": user_names.get(action.owner_id) if action.owner_id else None,
            }
        )
        for action in actions
    ]
    return ListResponse(data=data, pagination=Pagination(limit=len(data)))


@router.post("/governance/actions", response_model=DataResponse[GovernanceActionRead])
async def create_governance_action(
    payload: GovernanceActionCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceActionRead]:
    action = await create_action(
        session,
        current_user,
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        owner_id=payload.owner_id,
        due_date=payload.due_date,
        status=payload.status,
    )
    return DataResponse(
        data=GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
            update={"status": effective_action_status(action)}
        )
    )


@router.patch("/governance/actions/{action_id}", response_model=DataResponse[GovernanceActionRead])
async def patch_governance_action(
    action_id: UUID,
    payload: GovernanceActionUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceActionRead]:
    action = await update_action(
        session,
        action_id,
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    return DataResponse(
        data=GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
            update={"status": effective_action_status(action)}
        )
    )


@router.get("/projects/{project_id}/scope", response_model=DataResponse[ProjectScopeStateRead])
async def get_project_scope(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[ProjectScopeStateRead]:
    scope = await get_scope_state_for_project(session, project_id, current_user)
    return DataResponse(data=ProjectScopeStateRead.model_validate(scope, from_attributes=True))


@router.patch("/projects/{project_id}/scope", response_model=DataResponse[ProjectScopeStateRead])
async def patch_project_scope(
    project_id: UUID,
    payload: ProjectScopeStateUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectScopeStateRead]:
    scope = await update_scope_state(
        session,
        project_id,
        current_user,
        scope_status=payload.scope_status,
        version_label=payload.version_label,
        notes=payload.notes,
    )
    return DataResponse(data=ProjectScopeStateRead.model_validate(scope, from_attributes=True))


@router.get(
    "/governance/weekly-summary", response_model=DataResponse[GovernanceWeeklySummaryRead | None]
)
async def get_weekly_summary(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead | None]:
    summary = await get_latest_weekly_summary(session, current_user)
    if summary is None:
        return DataResponse(data=None)
    if current_user.role == AppRole.CLIENT and summary.status != GovernanceSummaryStatus.APPROVED:
        return DataResponse(data=None)
    evidence_rows = (
        (
            await session.execute(
                select(GovernanceEvidenceLink).where(
                    GovernanceEvidenceLink.summary_id == summary.id
                )
            )
        )
        .scalars()
        .all()
    )
    return DataResponse(
        data=GovernanceWeeklySummaryRead.model_validate(summary, from_attributes=True).model_copy(
            update={
                "evidence_links": [
                    GovernanceEvidenceLinkRead.model_validate(row, from_attributes=True)
                    for row in evidence_rows
                ],
            }
        )
    )


@router.post("/governance/weekly-summary", response_model=DataResponse[GovernanceWeeklySummaryRead])
async def post_weekly_summary(
    payload: GovernanceWeeklySummaryCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await create_weekly_summary(
        session,
        current_user,
        summary_week=payload.summary_week,
        summary_text=payload.summary_text,
        evidence_links=payload.evidence_links,
    )
    evidence_rows = (
        (
            await session.execute(
                select(GovernanceEvidenceLink).where(
                    GovernanceEvidenceLink.summary_id == summary.id
                )
            )
        )
        .scalars()
        .all()
    )
    return DataResponse(
        data=GovernanceWeeklySummaryRead.model_validate(summary, from_attributes=True).model_copy(
            update={
                "evidence_links": [
                    GovernanceEvidenceLinkRead.model_validate(row, from_attributes=True)
                    for row in evidence_rows
                ],
            }
        )
    )
