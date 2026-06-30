from uuid import UUID

from fastapi import APIRouter, Depends, Response
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
    GovernanceWeeklySummaryCreate,
    GovernanceWeeklySummaryGenerateRequest,
    GovernanceWeeklySummaryRead,
    GovernanceWeeklySummaryUpdate,
    ProjectCharterGenerateRequest,
    ProjectCharterRead,
    ProjectCharterUpdate,
    ProjectDependencyCreate,
    ProjectDependencyRead,
    ProjectDependencyUpdate,
    ProjectScopeStateRead,
    ProjectScopeStateUpdate,
    PromoteRiskAlertRequest,
)
from app.agents.governance.services.charter_export import generate_simple_docx
from app.agents.governance.services.charter_service import (
    approve_project_charter,
    archive_project_charter,
    build_project_charter_read,
    generate_project_charter,
    get_project_charter_or_404,
    list_project_charters,
    update_project_charter_draft,
)
from app.agents.governance.services.dashboard_service import get_governance_bootstrap
from app.agents.governance.services.delivery_integration import promote_risk_alert_to_escalation
from app.agents.governance.services.governance_service import (
    approve_weekly_summary,
    create_action,
    create_dependency,
    create_escalation,
    create_weekly_summary,
    get_latest_weekly_summary,
    get_scope_state_for_project,
    get_weekly_summary_by_id,
    list_weekly_summaries,
    load_project_names,
    load_user_names,
    resolve_dependency,
    scoped_actions_query,
    scoped_dependencies_query,
    scoped_escalations_query,
    soft_delete_action,
    soft_delete_dependency,
    soft_delete_escalation,
    update_action,
    update_dependency,
    update_escalation,
    update_scope_state,
    update_weekly_summary_draft,
)
from app.agents.governance.services.summary_service import (
    build_weekly_summary_read,
    generate_weekly_governance_summary,
)
from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, Project
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.services.pdf_export import generate_simple_pdf

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
        source_type=payload.source_type,
        source_id=payload.source_id,
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
        linked_knowledge_document_id=payload.linked_knowledge_document_id,
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
        linked_charter_document_id=payload.linked_charter_document_id,
    )
    return DataResponse(data=ProjectScopeStateRead.model_validate(scope, from_attributes=True))


@router.get(
    "/governance/project-charters",
    response_model=ListResponse[ProjectCharterRead],
)
async def list_governance_project_charters(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    project_id: UUID | None = None,
    limit: int = 50,
) -> ListResponse[ProjectCharterRead]:
    rows = await list_project_charters(
        session,
        current_user,
        project_id=project_id,
        limit=limit,
    )
    reads = [await build_project_charter_read(session, row) for row in rows]
    return ListResponse(data=reads, pagination=Pagination(limit=limit))


@router.get(
    "/governance/project-charters/{charter_id}",
    response_model=DataResponse[ProjectCharterRead],
)
async def get_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await get_project_charter_or_404(session, charter_id, current_user)
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/generate",
    response_model=DataResponse[ProjectCharterRead],
)
async def generate_governance_project_charter(
    payload: ProjectCharterGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await generate_project_charter(
        session,
        current_user,
        project_id=payload.project_id,
        visibility=payload.visibility,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.patch(
    "/governance/project-charters/{charter_id}",
    response_model=DataResponse[ProjectCharterRead],
)
async def patch_governance_project_charter(
    charter_id: UUID,
    payload: ProjectCharterUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await update_project_charter_draft(
        session,
        charter_id,
        current_user,
        generated_text=payload.generated_text,
        visibility=payload.visibility,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/approve",
    response_model=DataResponse[ProjectCharterRead],
)
async def approve_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await approve_project_charter(session, charter_id, current_user)
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/archive",
    response_model=DataResponse[ProjectCharterRead],
)
async def archive_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await archive_project_charter(session, charter_id, current_user)
    return DataResponse(data=await build_project_charter_read(session, charter))


def _safe_charter_filename(project_name: str, version: str, extension: str) -> str:
    safe_project = "".join(ch if ch.isalnum() else "_" for ch in project_name).strip("_")
    safe_project = safe_project or "project"
    safe_version = "".join(ch if ch.isalnum() else "_" for ch in version).strip("_")
    return f"{safe_project}_charter_{safe_version}.{extension}"


async def _charter_export_payload(
    session: SessionDep,
    charter_id: UUID,
    current_user: CurrentUser,
) -> tuple[ProjectCharterRead, str]:
    charter = await get_project_charter_or_404(session, charter_id, current_user)
    read = await build_project_charter_read(session, charter)
    project = (
        await session.execute(select(Project).where(Project.id == charter.project_id))
    ).scalar_one_or_none()
    project_name = project.name if project else read.project_name or "Project"
    title = f"{project_name} Project Charter {read.version}"
    appendix = "\n\nEvidence Appendix\n" + "\n".join(
        f"- [{link.source_type}] {link.label or link.source_id}"
        f"{' - ' + link.detail if link.detail else ''}"
        for link in read.evidence_links
    )
    body = (
        f"Project: {project_name}\n"
        f"Version: {read.version}\n"
        f"Status: {read.status.value}\n"
        f"Generated: {read.created_at.isoformat()}\n"
        f"Approved: {read.approved_at.isoformat() if read.approved_at else 'Pending'}\n"
        f"Approved by: {read.approved_by_name or 'Pending'}\n\n"
        f"{read.generated_text}"
        f"{appendix if read.evidence_links else ''}"
    )
    return read, f"{title}\n\n{body}"


@router.get("/governance/project-charters/{charter_id}/export.pdf")
async def export_governance_project_charter_pdf(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    read, body = await _charter_export_payload(session, charter_id, current_user)
    filename = _safe_charter_filename(read.project_name or "project", read.version, "pdf")
    return Response(
        content=generate_simple_pdf(f"Project Charter {read.version}", body),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/governance/project-charters/{charter_id}/export.docx")
async def export_governance_project_charter_docx(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    read, body = await _charter_export_payload(session, charter_id, current_user)
    filename = _safe_charter_filename(read.project_name or "project", read.version, "docx")
    return Response(
        content=generate_simple_docx(f"Project Charter {read.version}", body),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.get(
    "/governance/weekly-summaries",
    response_model=ListResponse[GovernanceWeeklySummaryRead],
)
async def list_governance_weekly_summaries(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    pagination: Pagination = Depends(),
) -> ListResponse[GovernanceWeeklySummaryRead]:
    rows = await list_weekly_summaries(session, current_user, limit=pagination.limit)
    reads = [await build_weekly_summary_read(session, row) for row in rows]
    return ListResponse(data=reads, meta={"total": len(reads)})


@router.get(
    "/governance/weekly-summary/{summary_id}",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def get_governance_weekly_summary_by_id(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await get_weekly_summary_by_id(session, summary_id, current_user)
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post(
    "/governance/weekly-summary/generate",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def generate_governance_weekly_summary(
    payload: GovernanceWeeklySummaryGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await generate_weekly_governance_summary(
        session,
        current_user,
        summary_week=payload.summary_week,
    )
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.patch(
    "/governance/weekly-summary/{summary_id}",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def patch_governance_weekly_summary(
    summary_id: UUID,
    payload: GovernanceWeeklySummaryUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await update_weekly_summary_draft(
        session,
        summary_id,
        current_user,
        summary_text=payload.summary_text,
    )
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post(
    "/governance/weekly-summary/{summary_id}/approve",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def approve_governance_weekly_summary(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await approve_weekly_summary(session, summary_id, current_user)
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post(
    "/governance/escalations/promote-from-risk-alert",
    response_model=DataResponse[GovernanceEscalationRead],
)
async def promote_escalation_from_risk_alert(
    payload: PromoteRiskAlertRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await promote_risk_alert_to_escalation(
        session,
        current_user,
        risk_alert_id=payload.risk_alert_id,
    )
    return DataResponse(
        data=GovernanceEscalationRead.model_validate(escalation, from_attributes=True)
    )


@router.delete("/dependencies/{dependency_id}", status_code=204)
async def delete_dependency(
    dependency_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_dependency(session, dependency_id, current_user)
    return Response(status_code=204)


@router.delete("/governance/escalations/{escalation_id}", status_code=204)
async def delete_escalation(
    escalation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_escalation(session, escalation_id, current_user)
    return Response(status_code=204)


@router.delete("/governance/actions/{action_id}", status_code=204)
async def delete_action(
    action_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_action(session, action_id, current_user)
    return Response(status_code=204)


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
    return DataResponse(data=await build_weekly_summary_read(session, summary))
