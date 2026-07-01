import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.agents.governance.analytics.sla import dependency_overdue_days, effective_action_status
from app.agents.governance.schemas.governance import (
    GovernanceActionCreate,
    GovernanceActionRead,
    GovernanceActionUpdate,
    GovernanceAnalyticsRead,
    GovernanceBootstrapRead,
    GovernanceCharterReferenceRead,
    GovernanceEscalationCreate,
    GovernanceEscalationRead,
    GovernanceEscalationUpdate,
    GovernanceMonitoringRead,
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
from app.agents.governance.services.analytics_service import get_governance_analytics
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.charter_export import (
    CharterExportDocument,
    generate_charter_docx,
    generate_charter_pdf,
)
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
from app.agents.governance.services.knowledge_link_service import list_approved_charter_references
from app.agents.governance.services.delivery_integration import promote_risk_alert_to_escalation
from app.agents.governance.services.governance_service import (
    approve_weekly_summary,
    can_read_internal_governance,
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
    scoped_scope_states_query,
    soft_delete_action,
    soft_delete_dependency,
    soft_delete_escalation,
    update_action,
    update_dependency,
    update_escalation,
    update_scope_state,
    update_weekly_summary_draft,
)
from app.agents.governance.services.monitoring_service import get_governance_monitoring
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
MONITORING_ROLES = (AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


@router.get("/governance/bootstrap", response_model=DataResponse[GovernanceBootstrapRead])
async def governance_bootstrap(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceBootstrapRead]:
    return DataResponse(data=await get_governance_bootstrap(session, current_user))


@router.get(
    "/governance/charter-references",
    response_model=ListResponse[GovernanceCharterReferenceRead],
)
async def list_governance_charter_references(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[GovernanceCharterReferenceRead]:
    if not can_read_internal_governance(current_user):
        return ListResponse(data=[], pagination=Pagination(limit=0))
    refs = await list_approved_charter_references(session, current_user)
    return ListResponse(data=refs, pagination=Pagination(limit=len(refs)))


@router.get("/governance/analytics", response_model=DataResponse[GovernanceAnalyticsRead])
async def governance_analytics(
    session: SessionDep,
    days: int = 30,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsRead]:
    return DataResponse(data=await get_governance_analytics(session, current_user, days=days))


@router.get("/governance/monitoring", response_model=DataResponse[GovernanceMonitoringRead])
async def governance_monitoring(
    session: SessionDep,
    window_hours: int = 24,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
) -> DataResponse[GovernanceMonitoringRead]:
    return DataResponse(
        data=await get_governance_monitoring(
            session,
            current_user,
            window_hours=window_hours,
        )
    )


def _analytics_csv(data: GovernanceAnalyticsRead) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "project", "metric", "value", "evidence"])
    for project in data.portfolio_risk_ranking:
        writer.writerow(
            [
                "portfolio_risk_ranking",
                project.project_name,
                "governance_health_score",
                project.score,
                "; ".join(item.label for item in project.evidence),
            ]
        )
    for recommendation in data.recommendations:
        writer.writerow(
            [
                "recommendation",
                recommendation.project_name or "",
                recommendation.title,
                recommendation.detail,
                "; ".join(item.label for item in recommendation.evidence),
            ]
        )
    return output.getvalue()


@router.get("/governance/analytics/export.csv")
async def export_governance_analytics_csv(
    session: SessionDep,
    days: int = 30,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    data = await get_governance_analytics(session, current_user, days=days)
    await log_governance_event(
        session,
        current_user,
        event_type="dashboard.exported",
        org_id=current_user.org_id,
        source_table="governance_analytics",
        metadata={"format": "csv", "days": data.date_range_days},
    )
    await session.commit()
    return Response(
        content=_analytics_csv(data),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="governance_analytics_{data.date_range_days}d.csv"'
            )
        },
    )


@router.get("/governance/analytics/export.pdf")
async def export_governance_analytics_pdf(
    session: SessionDep,
    days: int = 30,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    data = await get_governance_analytics(session, current_user, days=days)
    body = (
        f"Generated: {data.generated_at.isoformat()}\n"
        f"Range: {data.date_range_days} days\n\n"
        f"Portfolio Score: {data.kpis.portfolio_score}\n"
        f"Projects at Risk: {data.kpis.projects_at_risk}\n"
        f"Blocking Dependencies: {data.kpis.blocking_dependencies}\n"
        f"Critical Escalations: {data.kpis.critical_escalations}\n"
        f"Governance SLA: {data.kpis.governance_sla_pct}%\n\n"
        "Portfolio Risk Ranking\n"
        + "\n".join(
            f"- {project.project_name}: score={project.score}, risk={project.risk_level}"
            for project in data.portfolio_risk_ranking[:10]
        )
        + "\n\nRecommendations\n"
        + "\n".join(
            f"- {item.project_name or 'Portfolio'}: {item.title} ({item.priority})"
            for item in data.recommendations
        )
    )
    await log_governance_event(
        session,
        current_user,
        event_type="dashboard.exported",
        org_id=current_user.org_id,
        source_table="governance_analytics",
        metadata={"format": "pdf", "days": data.date_range_days},
    )
    await session.commit()
    return Response(
        content=generate_simple_pdf("Governance Analytics", body),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="governance_analytics_{data.date_range_days}d.pdf"'
            )
        },
    )


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


@router.get("/governance/dependencies", response_model=ListResponse[ProjectDependencyRead])
async def list_governance_dependencies(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[ProjectDependencyRead]:
    deps = await scoped_dependencies_query(session, current_user)
    project_names = await load_project_names(session, {d.project_id for d in deps})
    user_names = await load_user_names(session, {d.owner_id for d in deps if d.owner_id})
    data = [
        ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={
                "overdue_days": dependency_overdue_days(dep),
                "project_name": project_names.get(dep.project_id),
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


@router.get("/governance/scope-states", response_model=ListResponse[ProjectScopeStateRead])
async def list_governance_scope_states(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[ProjectScopeStateRead]:
    scopes = await scoped_scope_states_query(session, current_user)
    data = [ProjectScopeStateRead.model_validate(scope, from_attributes=True) for scope in scopes]
    return ListResponse(data=data, pagination=Pagination(limit=len(data)))


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
    await log_governance_event(
        session,
        current_user,
        event_type="charter.generated",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={
            "version": charter.version,
            "status": charter.status.value,
            "generated_by_ai": charter.generated_by_ai,
            "visibility": charter.visibility.value,
        },
    )
    await session.commit()
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
    await log_governance_event(
        session,
        current_user,
        event_type="charter.updated",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={"version": charter.version, "status": charter.status.value},
    )
    await session.commit()
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
    await log_governance_event(
        session,
        current_user,
        event_type="charter.approved",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={"version": charter.version, "status": charter.status.value},
    )
    await session.commit()
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
    await log_governance_event(
        session,
        current_user,
        event_type="charter.archived",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={"version": charter.version, "status": charter.status.value},
    )
    await session.commit()
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
) -> tuple[ProjectCharterRead, CharterExportDocument]:
    charter = await get_project_charter_or_404(session, charter_id, current_user)
    read = await build_project_charter_read(session, charter)
    project = (
        await session.execute(select(Project).where(Project.id == charter.project_id))
    ).scalar_one_or_none()
    project_name = project.name if project else read.project_name or "Project"
    title = f"{project_name} Project Charter {read.version}"
    metadata = [
        ("Project", project_name),
        ("Version", read.version),
        ("Status", read.status.value.replace("_", " ").title()),
        ("Generated", read.created_at.strftime("%b %d, %Y")),
        ("Visibility", read.visibility.value.replace("_", " ").title()),
    ]
    if read.generated_by_ai:
        metadata.append(("Generated By", "AI"))
    metadata.extend(
        [
            ("Approved", read.approved_at.strftime("%b %d, %Y") if read.approved_at else "Pending"),
            ("Approved By", read.approved_by_name or "Pending"),
        ]
    )
    return read, CharterExportDocument(
        title=title,
        metadata=metadata,
        markdown=read.generated_text,
    )


@router.get("/governance/project-charters/{charter_id}/export.pdf")
async def export_governance_project_charter_pdf(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    read, document = await _charter_export_payload(session, charter_id, current_user)
    filename = _safe_charter_filename(read.project_name or "project", read.version, "pdf")
    await log_governance_event(
        session,
        current_user,
        event_type="charter.exported",
        org_id=read.org_id,
        project_id=read.project_id,
        source_table="project_charters",
        source_id=read.id,
        metadata={"format": "pdf", "version": read.version},
    )
    await session.commit()
    return Response(
        content=generate_charter_pdf(document),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/governance/project-charters/{charter_id}/export.docx")
async def export_governance_project_charter_docx(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    read, document = await _charter_export_payload(session, charter_id, current_user)
    filename = _safe_charter_filename(read.project_name or "project", read.version, "docx")
    await log_governance_event(
        session,
        current_user,
        event_type="charter.exported",
        org_id=read.org_id,
        project_id=read.project_id,
        source_table="project_charters",
        source_id=read.id,
        metadata={"format": "docx", "version": read.version},
    )
    await session.commit()
    return Response(
        content=generate_charter_docx(document),
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
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.generated",
        org_id=summary.org_id,
        source_table="governance_weekly_summaries",
        source_id=summary.id,
        new_values={
            "summary_week": summary.summary_week.isoformat(),
            "status": summary.status.value,
            "generated_by_ai": summary.generated_by_ai,
        },
    )
    await session.commit()
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
    await log_governance_event(
        session,
        current_user,
        event_type="escalation.promoted_from_delivery_risk",
        org_id=escalation.org_id,
        project_id=escalation.project_id,
        source_table="governance_escalations",
        source_id=escalation.id,
        new_values={
            "title": escalation.title,
            "severity": escalation.severity.value,
            "status": escalation.status.value,
            "source_type": escalation.source_type.value if escalation.source_type else None,
            "source_id": str(escalation.source_id) if escalation.source_id else None,
        },
    )
    await session.commit()
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
