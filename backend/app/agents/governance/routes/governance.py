from uuid import UUID
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.agents.governance.routes import (
    actions,
    analytics,
    dependencies,
    escalations,
    jobs,
    recommendation_effectiveness,
    recommendation_optimization,
    register,
    scope,
    weekly_summaries,
)
from app.agents.governance.schemas.governance import (
    CharterKnowledgeLinkRead,
    CharterPublicationActionRequest,
    CharterPublicationEventRead,
    CharterPublicationStatusRead,
    CharterPublicationVersionRead,
    ConvertRecommendationToActionRequest,
    ConvertRecommendationToEscalationRequest,
    GovernanceAIRecommendationDismissRequest,
    GovernanceAIRecommendationFeedbackRead,
    GovernanceAIRecommendationFeedbackRequest,
    GovernanceAIRecommendationGenerateRequest,
    GovernanceAIRecommendationListRead,
    GovernanceAIRecommendationRead,
    GovernanceBootstrapRead,
    GovernanceJobStartRead,
    GovernanceProjectSheetRead,
    GovernanceRecommendationConversionRead,
    ProjectCharterGenerateRequest,
    ProjectChartersPanelRead,
    ProjectCharterRead,
    ProjectCharterUpdate,
)
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
    build_project_charter_read_with_metrics,
    get_project_charters_panel_data,
    get_project_charter_or_404,
    list_project_charters_page,
    update_project_charter_draft,
)
from app.agents.governance.services.dashboard_service import get_governance_bootstrap
from app.agents.governance.services.governance_charter_publish_service import (
    PUBLISH_ROLES,
    get_charter_knowledge_link,
    get_publication_versions,
    get_publish_status,
    list_charter_publication_timeline,
    maybe_auto_publish_after_approval,
    publish_charter,
    republish_charter,
    retry_publication,
    unpublish_charter,
)
from app.agents.governance.services.job_service import (
    JOB_AI_RECOMMENDATION,
    JOB_CHARTER,
    enqueue_governance_job,
)
from app.agents.governance.services.project_sheet_service import get_governance_project_sheet
from app.agents.governance.services.recommendation_service import (
    _to_read,
    can_generate_ai_recommendations,
    convert_governance_recommendation_to_action,
    convert_governance_recommendation_to_escalation,
    dismiss_governance_ai_recommendation,
    get_governance_ai_recommendation,
    list_governance_ai_recommendation_conversions,
    list_governance_ai_recommendations,
    submit_governance_ai_recommendation_feedback,
)
from app.agents.governance.timing import get_governance_timer, instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.config import get_settings
from app.core.security import CurrentUser, require_role
from app.db.models import (
    AppRole,
    Project,
)
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.services.scoping import get_visible_project

router = APIRouter(tags=["governance"])

READ_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN, AppRole.CLIENT)
WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)
SUMMARY_WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
SUMMARY_EXPORT_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
CHARTER_PUBLISH_ROLES = tuple(PUBLISH_ROLES)
AI_RECOMMENDATION_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
MONITORING_ROLES = (AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


def _pagination(total: int, limit: int, offset: int, item_count: int) -> Pagination:
    return Pagination(
        limit=limit,
        offset=offset,
        total=total,
        items=item_count,
        has_more=offset + item_count < total,
    )


@router.get("/governance/bootstrap", response_model=DataResponse[GovernanceBootstrapRead])
async def governance_bootstrap(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceBootstrapRead]:
    return DataResponse(data=await get_governance_bootstrap(session, current_user))


@router.get(
    "/governance/project-sheet/{project_id}",
    response_model=DataResponse[GovernanceProjectSheetRead],
)
async def governance_project_sheet(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceProjectSheetRead]:
    response = DataResponse(
        data=await get_governance_project_sheet(
            session,
            current_user,
            project_id=project_id,
        )
    )
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(response_bytes=len(response.model_dump_json().encode("utf-8")))
    return response


@router.get(
    "/governance/project-charters",
    response_model=ListResponse[ProjectCharterRead],
)
async def list_governance_project_charters(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    project_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    include_detail: bool = True,
) -> ListResponse[ProjectCharterRead]:
    page = await list_project_charters_page(
        session,
        current_user,
        project_id=project_id,
        limit=limit,
        offset=offset,
        include_detail=include_detail,
    )
    response = ListResponse(
        data=page.items,
        pagination=Pagination(
            limit=page.limit,
            offset=page.offset,
            items=len(page.items),
            has_more=page.has_more,
        ),
    )
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            response_bytes=len(response.model_dump_json().encode("utf-8")),
            returned_row_count=len(page.items),
        )
    return response


@router.get(
    "/governance/project-charters/panel",
    response_model=DataResponse[ProjectChartersPanelRead],
)
async def get_governance_project_charters_panel(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    project_id: UUID | None = None,
    selected_charter_id: UUID | None = None,
    limit: int = 5,
    offset: int = 0,
) -> DataResponse[ProjectChartersPanelRead]:
    panel = await get_project_charters_panel_data(
        session,
        current_user,
        project_id=project_id,
        selected_charter_id=selected_charter_id,
        limit=limit,
        offset=offset,
    )
    response = DataResponse(
        data=ProjectChartersPanelRead(
            charters=panel.charters,
            selected_charter=panel.selected_charter,
            limit=panel.limit,
            offset=panel.offset,
            has_more=panel.has_more,
        )
    )
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            execute_count=panel.db_executes,
            cache_hit=panel.cache_hit,
            limit=panel.limit,
            offset=panel.offset,
            list_row_fetch_ms=panel.list_row_fetch_ms,
            detail_fetch_ms=panel.detail_fetch_ms,
            enrichment_ms=panel.enrichment_ms,
            returned_row_count=len(panel.charters),
            response_bytes=len(response.model_dump_json().encode("utf-8")),
        )
    return response


@router.get(
    "/governance/project-charters/{charter_id}",
    response_model=DataResponse[ProjectCharterRead],
)
async def get_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    started = perf_counter()
    charter = await get_project_charter_or_404(session, charter_id, current_user)
    read, enrichment_executes = await build_project_charter_read_with_metrics(session, charter)
    response = DataResponse(data=read)
    timer = get_governance_timer()
    if timer is not None:
        base_executes = 2 if current_user.role == AppRole.CLIENT else 1
        timer.record_meta(
            execute_count=base_executes + enrichment_executes,
            detail_fetch_ms=round((perf_counter() - started) * 1000, 1),
            returned_row_count=1,
            response_bytes=len(response.model_dump_json().encode("utf-8")),
        )
    return response


@router.post(
    "/governance/project-charters/generate",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def generate_governance_project_charter(
    payload: ProjectCharterGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobStartRead]:
    project = await get_visible_project(session, payload.project_id, current_user)
    job_payload = payload.model_dump(mode="json")
    job_payload["source_version"] = "governance-evidence-v1"
    job, deduplicated = await enqueue_governance_job(
        session,
        current_user,
        job_type=JOB_CHARTER,
        org_id=project.org_id,
        project_id=payload.project_id,
        payload=job_payload,
    )
    return DataResponse(data=jobs.job_start(job, deduplicated))


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
    # Auto-publish is best-effort; approval is already committed and never rolled back.
    charter = await maybe_auto_publish_after_approval(session, current_user, charter)
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/publish",
    response_model=DataResponse[ProjectCharterRead],
)
async def publish_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await publish_charter(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/republish",
    response_model=DataResponse[ProjectCharterRead],
)
async def republish_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await republish_charter(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/retry-publication",
    response_model=DataResponse[ProjectCharterRead],
)
async def retry_governance_project_charter_publication(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await retry_publication(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/unpublish",
    response_model=DataResponse[ProjectCharterRead],
)
async def unpublish_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await unpublish_charter(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.get(
    "/governance/project-charters/{charter_id}/publication-status",
    response_model=DataResponse[CharterPublicationStatusRead],
)
async def get_governance_project_charter_publication_status(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[CharterPublicationStatusRead]:
    status = await get_publish_status(session, current_user, charter_id)
    return DataResponse(data=CharterPublicationStatusRead.model_validate(status))


@router.get(
    "/governance/project-charters/{charter_id}/knowledge",
    response_model=DataResponse[CharterKnowledgeLinkRead],
)
async def get_governance_project_charter_knowledge(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[CharterKnowledgeLinkRead]:
    link = await get_charter_knowledge_link(session, current_user, charter_id)
    return DataResponse(data=CharterKnowledgeLinkRead.model_validate(link))


@router.get(
    "/governance/project-charters/{charter_id}/versions",
    response_model=ListResponse[CharterPublicationVersionRead],
)
async def get_governance_project_charter_versions(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[CharterPublicationVersionRead]:
    versions = await get_publication_versions(session, current_user, charter_id)
    reads = [CharterPublicationVersionRead.model_validate(row) for row in versions]
    return ListResponse(data=reads, pagination=Pagination(limit=len(reads), items=len(reads)))


@router.get(
    "/governance/project-charters/{charter_id}/publication-timeline",
    response_model=ListResponse[CharterPublicationEventRead],
)
async def get_governance_project_charter_publication_timeline(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[CharterPublicationEventRead]:
    events = await list_charter_publication_timeline(session, current_user, charter_id)
    reads = [
        CharterPublicationEventRead.model_validate(event, from_attributes=True) for event in events
    ]
    return ListResponse(data=reads, pagination=Pagination(limit=len(reads), items=len(reads)))


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
    "/governance/ai-recommendations",
    response_model=DataResponse[GovernanceAIRecommendationListRead],
)
async def get_governance_ai_recommendations(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    project_id: UUID | None = Query(default=None),
    scope: str = Query(default="project"),
    status: str | None = Query(default="active"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DataResponse[GovernanceAIRecommendationListRead]:
    from app.db.models import (
        GovernanceAIRecommendationScope,
        GovernanceAIRecommendationStatus,
    )

    scope_enum = GovernanceAIRecommendationScope(scope)
    status_enum = GovernanceAIRecommendationStatus(status) if status else None
    data = await list_governance_ai_recommendations(
        session,
        current_user,
        project_id=project_id,
        scope=scope_enum,
        status=status_enum,
        limit=limit,
        offset=offset,
        include_rule_based=False,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/ai-recommendations/{recommendation_id}",
    response_model=DataResponse[GovernanceAIRecommendationRead],
)
async def get_one_governance_ai_recommendation(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceAIRecommendationRead]:
    from app.agents.governance.services.governance_service import load_project_names

    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    names = await load_project_names(session, {row.project_id} if row.project_id else set())
    return DataResponse(
        data=_to_read(
            row,
            project_name=names.get(row.project_id) if row.project_id else None,
            can_generate=can_generate_ai_recommendations(current_user),
        )
    )


@router.post(
    "/governance/ai-recommendations/generate",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def post_generate_governance_ai_recommendations(
    payload: GovernanceAIRecommendationGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobStartRead]:
    if payload.scope.value == "portfolio" and current_user.role not in {
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
    }:
        raise HTTPException(
            status_code=403, detail="Portfolio recommendations require leadership access."
        )
    project = (
        await get_visible_project(session, payload.project_id, current_user)
        if payload.project_id
        else None
    )
    org_id = project.org_id if project else current_user.org_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organisation context is required.")
    settings = get_settings()
    job_payload = payload.model_dump(mode="json")
    job_payload.update(
        {
            "prompt_version": settings.governance_ai_recommendation_prompt_version,
            "strategy_version": settings.governance_recommendation_strategy_version,
        }
    )
    job, deduplicated = await enqueue_governance_job(
        session,
        current_user,
        job_type=JOB_AI_RECOMMENDATION,
        org_id=org_id,
        project_id=payload.project_id,
        payload=job_payload,
    )
    return DataResponse(data=jobs.job_start(job, deduplicated))


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/regenerate",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def post_regenerate_governance_ai_recommendation(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobStartRead]:
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    settings = get_settings()
    job, deduplicated = await enqueue_governance_job(
        session,
        current_user,
        job_type=JOB_AI_RECOMMENDATION,
        org_id=row.org_id,
        project_id=row.project_id,
        payload={
            "project_id": str(row.project_id) if row.project_id else None,
            "scope": row.scope.value,
            "force": True,
            "source_recommendation_id": str(row.id),
            "prompt_version": settings.governance_ai_recommendation_prompt_version,
            "strategy_version": settings.governance_recommendation_strategy_version,
        },
    )
    return DataResponse(data=jobs.job_start(job, deduplicated))


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/dismiss",
    response_model=DataResponse[GovernanceAIRecommendationRead],
)
async def post_dismiss_governance_ai_recommendation(
    recommendation_id: UUID,
    payload: GovernanceAIRecommendationDismissRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationRead]:
    data = await dismiss_governance_ai_recommendation(
        session,
        current_user,
        recommendation_id,
        reason=payload.reason,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/feedback",
    response_model=DataResponse[GovernanceAIRecommendationFeedbackRead],
)
async def post_governance_ai_recommendation_feedback(
    recommendation_id: UUID,
    payload: GovernanceAIRecommendationFeedbackRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationFeedbackRead]:
    data = await submit_governance_ai_recommendation_feedback(
        session,
        current_user,
        recommendation_id,
        helpful=payload.helpful,
        reason=payload.reason,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/convert/action",
    response_model=DataResponse[GovernanceRecommendationConversionRead],
)
async def post_convert_governance_ai_recommendation_to_action(
    recommendation_id: UUID,
    payload: ConvertRecommendationToActionRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationConversionRead]:
    data = await convert_governance_recommendation_to_action(
        session,
        current_user,
        recommendation_id,
        payload,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/convert/escalation",
    response_model=DataResponse[GovernanceRecommendationConversionRead],
)
async def post_convert_governance_ai_recommendation_to_escalation(
    recommendation_id: UUID,
    payload: ConvertRecommendationToEscalationRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationConversionRead]:
    data = await convert_governance_recommendation_to_escalation(
        session,
        current_user,
        recommendation_id,
        payload,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/ai-recommendations/{recommendation_id}/conversions",
    response_model=DataResponse[list[GovernanceRecommendationConversionRead]],
)
async def get_governance_ai_recommendation_conversions(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[list[GovernanceRecommendationConversionRead]]:
    data = await list_governance_ai_recommendation_conversions(
        session,
        current_user,
        recommendation_id,
    )
    return DataResponse(data=data)


router.include_router(jobs.router)
router.include_router(analytics.router)
router.include_router(register.router)
router.include_router(dependencies.router)
router.include_router(actions.router)
router.include_router(escalations.router)
router.include_router(scope.router)
router.include_router(weekly_summaries.router)
router.include_router(recommendation_effectiveness.router)
router.include_router(recommendation_optimization.router)

instrument_governance_routes(router)
