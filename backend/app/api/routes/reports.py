"""Phase 18.3 Cross-Agent Reporting Framework HTTP API."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
from app.db.models import (
    AppRole,
    ReportApprovalEvent,
    ReportExport,
    ReportInstance,
    ReportJob,
    ReportSchedule,
    ReportTemplate,
)
from app.reports.contracts import ReportBuildContext
from app.reports.engine import build_report
from app.reports.exports import create_report_export
from app.reports.jobs import enqueue_report_job
from app.reports.permissions import (
    can_approve_report,
    can_mutate_report,
    can_view_report,
    can_view_template,
)
from app.reports.registry import get_report_registry, load_templates, resolve_template
from app.reports.storage import load_report_bytes
from app.reports.workflows import (
    approve_report,
    distribute_report,
    reject_report,
    submit_for_review,
)
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.reports import (
    ReportApprovalEventRead,
    ReportExportRead,
    ReportGenerateRequest,
    ReportInstanceListItem,
    ReportInstanceRead,
    ReportJobStartRead,
    ReportPreviewRead,
    ReportScheduleCreate,
    ReportScheduleRead,
    ReportScheduleUpdate,
    ReportSectionPayload,
    ReportTemplateCreate,
    ReportTemplateRead,
    ReportTemplateUpdate,
)

router = APIRouter(prefix="/reports", tags=["reports"])

_Mutator = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN))
_Approver = Depends(
    require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
)


def _assert_org(current_user: CurrentUser, org_id: UUID | None) -> UUID:
    resolved = org_id or current_user.org_id
    if current_user.role != AppRole.SUPER_ADMIN and resolved != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot access another organisation.")
    return resolved


async def _get_report_or_404(
    session: SessionDep,
    current_user: CurrentUser,
    report_id: UUID,
) -> ReportInstance:
    report = await session.get(ReportInstance, report_id)
    if report is None or not can_view_report(report, current_user):
        raise ApiError(404, "NOT_FOUND", "Report was not found.")
    return report


@router.get("/templates", response_model=ListResponse[ReportTemplateRead])
async def list_report_templates(
    session: SessionDep,
    current_user: UserDep,
    domain: Annotated[str | None, Query()] = None,
    audience: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = "active",
) -> ListResponse[ReportTemplateRead]:
    rows = await load_templates(session, org_id=current_user.org_id)
    filtered = []
    for row in rows:
        if status and row.status != status:
            continue
        if domain and row.domain != domain:
            continue
        if audience and row.audience != audience:
            continue
        if can_view_template(row, current_user):
            filtered.append(ReportTemplateRead.model_validate(row))
    return ListResponse(
        data=filtered,
        pagination=Pagination(limit=max(len(filtered), 1), total=len(filtered)),
    )


@router.get("/templates/{template_id}", response_model=DataResponse[ReportTemplateRead])
async def get_report_template(
    template_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[ReportTemplateRead]:
    row = await session.get(ReportTemplate, template_id)
    if row is None or not can_view_template(row, current_user):
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    return DataResponse(data=ReportTemplateRead.model_validate(row))


@router.post("/templates", response_model=DataResponse[ReportTemplateRead], status_code=201)
async def create_report_template(
    payload: ReportTemplateCreate,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportTemplateRead]:
    org_id = _assert_org(current_user, payload.org_id)
    registry = get_report_registry()
    registry.validate_section_config([s.model_dump() for s in payload.section_config])
    row = ReportTemplate(
        org_id=org_id if current_user.role != AppRole.SUPER_ADMIN or payload.org_id else org_id,
        template_key=payload.template_key,
        name=payload.name,
        description=payload.description,
        audience=payload.audience,
        domain=payload.domain,
        version=payload.version,
        status=payload.status,
        section_config=[s.model_dump() for s in payload.section_config],
        export_formats=list(payload.export_formats),
        requires_approval=payload.requires_approval,
        allowed_roles=list(payload.allowed_roles)
        or ["delivery_manager", "bsg_leadership", "super_admin"],
        is_client_visible=payload.is_client_visible,
        created_by=current_user.id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=ReportTemplateRead.model_validate(row))


@router.patch("/templates/{template_id}", response_model=DataResponse[ReportTemplateRead])
async def update_report_template(
    template_id: UUID,
    payload: ReportTemplateUpdate,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportTemplateRead]:
    row = await session.get(ReportTemplate, template_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    if current_user.role != AppRole.SUPER_ADMIN and row.org_id != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot update this template.")
    data = payload.model_dump(exclude_unset=True)
    if "section_config" in data and data["section_config"] is not None:
        get_report_registry().validate_section_config(data["section_config"])
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=ReportTemplateRead.model_validate(row))


@router.post(
    "/templates/{template_id}/activate",
    response_model=DataResponse[ReportTemplateRead],
)
async def activate_report_template(
    template_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportTemplateRead]:
    row = await session.get(ReportTemplate, template_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    if current_user.role != AppRole.SUPER_ADMIN and row.org_id not in (
        None,
        current_user.org_id,
    ):
        raise ApiError(403, "FORBIDDEN", "Cannot activate this template.")
    row.status = "active"
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=ReportTemplateRead.model_validate(row))


@router.post(
    "/templates/{template_id}/archive",
    response_model=DataResponse[ReportTemplateRead],
)
async def archive_report_template(
    template_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportTemplateRead]:
    row = await session.get(ReportTemplate, template_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    if current_user.role != AppRole.SUPER_ADMIN and row.org_id != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot archive this template.")
    row.status = "archived"
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=ReportTemplateRead.model_validate(row))


@router.get("", response_model=ListResponse[ReportInstanceListItem])
async def list_reports(
    session: SessionDep,
    current_user: UserDep,
    status: Annotated[str | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    template_key: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListResponse[ReportInstanceListItem]:
    stmt = select(ReportInstance)
    if current_user.role == AppRole.CLIENT:
        stmt = stmt.where(
            ReportInstance.org_id == current_user.org_id,
            ReportInstance.status == "distributed",
            ReportInstance.audience == "client",
        )
    elif current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(ReportInstance.org_id == current_user.org_id)
    if status:
        stmt = stmt.where(ReportInstance.status == status)
    if domain:
        stmt = stmt.where(ReportInstance.domain == domain)
    if project_id:
        stmt = stmt.where(ReportInstance.project_id == project_id)
    if template_key:
        stmt = stmt.where(ReportInstance.template_key == template_key)
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(ReportInstance.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars()
    )
    data = [
        ReportInstanceListItem.model_validate(row)
        for row in rows
        if can_view_report(row, current_user)
    ]
    return ListResponse(data=data, pagination=Pagination(limit=limit, offset=offset, total=total))


@router.get("/{report_id}", response_model=DataResponse[ReportInstanceRead])
async def get_report(
    report_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[ReportInstanceRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    return DataResponse(data=ReportInstanceRead.model_validate(report))


@router.get("/{report_id}/preview", response_model=DataResponse[ReportPreviewRead])
async def preview_report(
    report_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[ReportPreviewRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    template = await session.get(ReportTemplate, report.template_id)
    if template is None:
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    sections = [
        ReportSectionPayload.model_validate(section)
        for section in (report.content_payload or {}).get("sections", [])
    ]
    return DataResponse(
        data=ReportPreviewRead(
            template=ReportTemplateRead.model_validate(template),
            title=report.title,
            body_markdown=report.body_markdown or "",
            sections=sections,
            limitations=list(report.limitations or []),
            evidence_fingerprint=report.evidence_fingerprint,
            has_ai_sections=report.has_ai_sections,
            requires_approval=bool(template.requires_approval or report.has_ai_sections),
        )
    )


@router.post("/generate", response_model=DataResponse[ReportJobStartRead], status_code=202)
async def generate_report(
    payload: ReportGenerateRequest,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportJobStartRead]:
    template = await resolve_template(
        session,
        payload.template_key,
        version=payload.template_version,
        org_id=current_user.org_id,
    )
    if template is None or not can_view_template(template, current_user):
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    idem = payload.idempotency_key or (
        f"generate:{current_user.org_id}:{payload.template_key}:"
        f"{payload.project_id}:{payload.period_start}:{payload.period_end}"
    )
    job = await enqueue_report_job(
        session,
        org_id=current_user.org_id,
        project_id=payload.project_id,
        job_type="on_demand_generate",
        idempotency_key=idem,
        template_id=template.id,
        request_payload={
            "template_key": payload.template_key,
            "template_version": payload.template_version or template.version,
            "project_id": str(payload.project_id) if payload.project_id else None,
            "period_start": payload.period_start.isoformat() if payload.period_start else None,
            "period_end": payload.period_end.isoformat() if payload.period_end else None,
            "title": payload.title,
            "section_options": payload.section_options,
            "requested_by": str(current_user.id),
            "generation_mode": payload.generation_mode,
        },
    )
    await session.commit()
    await session.refresh(job)
    return DataResponse(data=ReportJobStartRead.model_validate(job))


@router.post("/generate/sync", response_model=DataResponse[ReportInstanceRead])
async def generate_report_sync(
    payload: ReportGenerateRequest,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportInstanceRead]:
    """Synchronous generation for interactive builders (still creates a draft only)."""
    template = await resolve_template(
        session,
        payload.template_key,
        version=payload.template_version,
        org_id=current_user.org_id,
    )
    if template is None or not can_view_template(template, current_user):
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    report = await build_report(
        session,
        current_user,
        template,
        ReportBuildContext(
            org_id=current_user.org_id,
            project_id=payload.project_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            title=payload.title,
            generation_mode=payload.generation_mode,
            idempotency_key=payload.idempotency_key,
        ),
        section_options=payload.section_options,
    )
    await session.commit()
    await session.refresh(report)
    return DataResponse(data=ReportInstanceRead.model_validate(report))


@router.post("/{report_id}/regenerate", response_model=DataResponse[ReportJobStartRead], status_code=202)
async def regenerate_report(
    report_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportJobStartRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    if not can_mutate_report(report, current_user):
        raise ApiError(403, "FORBIDDEN", "Cannot regenerate this report.")
    job = await enqueue_report_job(
        session,
        org_id=report.org_id,
        project_id=report.project_id,
        job_type="regenerate",
        idempotency_key=f"regenerate:{report.id}:{report.updated_at.isoformat()}",
        report_instance_id=report.id,
        template_id=report.template_id,
        request_payload={
            "source_report_id": str(report.id),
            "template_key": report.template_key,
            "template_version": report.template_version,
            "project_id": str(report.project_id) if report.project_id else None,
            "period_start": report.period_start.isoformat() if report.period_start else None,
            "period_end": report.period_end.isoformat() if report.period_end else None,
            "title": report.title,
            "requested_by": str(current_user.id),
        },
    )
    await session.commit()
    await session.refresh(job)
    return DataResponse(data=ReportJobStartRead.model_validate(job))


@router.get("/jobs/{job_id}", response_model=DataResponse[ReportJobStartRead])
async def get_report_job(
    job_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[ReportJobStartRead]:
    job = await session.get(ReportJob, job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Report job was not found.")
    if current_user.role != AppRole.SUPER_ADMIN and job.org_id != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot access this job.")
    return DataResponse(data=ReportJobStartRead.model_validate(job))


@router.post("/{report_id}/submit", response_model=DataResponse[ReportInstanceRead])
async def submit_report(
    report_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportInstanceRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    report = await submit_for_review(session, report, current_user)
    await session.commit()
    await session.refresh(report)
    return DataResponse(data=ReportInstanceRead.model_validate(report))


@router.post("/{report_id}/approve", response_model=DataResponse[ReportInstanceRead])
async def approve_report_route(
    report_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Approver],
) -> DataResponse[ReportInstanceRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    if not can_approve_report(report, current_user):
        raise ApiError(403, "FORBIDDEN", "Cannot approve this report.")
    report = await approve_report(session, report, current_user)
    await session.commit()
    await session.refresh(report)
    return DataResponse(data=ReportInstanceRead.model_validate(report))


@router.post("/{report_id}/reject", response_model=DataResponse[ReportInstanceRead])
async def reject_report_route(
    report_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Approver],
    reason: Annotated[str, Query(min_length=1)],
) -> DataResponse[ReportInstanceRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    report = await reject_report(session, report, current_user, reason=reason)
    await session.commit()
    await session.refresh(report)
    return DataResponse(data=ReportInstanceRead.model_validate(report))


@router.post("/{report_id}/distribute", response_model=DataResponse[ReportInstanceRead])
async def distribute_report_route(
    report_id: UUID,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportInstanceRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    report = await distribute_report(session, report, current_user)
    await session.commit()
    await session.refresh(report)
    return DataResponse(data=ReportInstanceRead.model_validate(report))


@router.get(
    "/{report_id}/approvals",
    response_model=ListResponse[ReportApprovalEventRead],
)
async def list_report_approvals(
    report_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> ListResponse[ReportApprovalEventRead]:
    await _get_report_or_404(session, current_user, report_id)
    if current_user.role == AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Clients cannot view approval history.")
    rows = list(
        (
            await session.execute(
                select(ReportApprovalEvent)
                .where(ReportApprovalEvent.report_instance_id == report_id)
                .order_by(ReportApprovalEvent.created_at.asc())
            )
        ).scalars()
    )
    data = [ReportApprovalEventRead.model_validate(row) for row in rows]
    return ListResponse(data=data, pagination=Pagination(limit=max(len(data), 1), total=len(data)))


@router.post(
    "/{report_id}/exports/{format}",
    response_model=DataResponse[ReportExportRead],
)
async def request_report_export(
    report_id: UUID,
    format: Literal["pdf", "docx", "json", "csv"],
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportExportRead]:
    report = await _get_report_or_404(session, current_user, report_id)
    export = await create_report_export(session, report, format)
    await session.commit()
    await session.refresh(export)
    return DataResponse(data=ReportExportRead.model_validate(export))


@router.get("/{report_id}/exports", response_model=ListResponse[ReportExportRead])
async def list_report_exports(
    report_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> ListResponse[ReportExportRead]:
    await _get_report_or_404(session, current_user, report_id)
    rows = list(
        (
            await session.execute(
                select(ReportExport)
                .where(ReportExport.report_instance_id == report_id)
                .order_by(ReportExport.generated_at.desc())
            )
        ).scalars()
    )
    data = [ReportExportRead.model_validate(row) for row in rows]
    return ListResponse(data=data, pagination=Pagination(limit=max(len(data), 1), total=len(data)))


@router.get("/{report_id}/exports/{export_id}/download")
async def download_report_export(
    report_id: UUID,
    export_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> Response:
    await _get_report_or_404(session, current_user, report_id)
    export = await session.get(ReportExport, export_id)
    if export is None or export.report_instance_id != report_id:
        raise ApiError(404, "NOT_FOUND", "Export was not found.")
    content = await load_report_bytes(
        storage_backend=export.storage_backend,
        storage_path=export.storage_path,
    )
    return Response(
        content=content,
        media_type=export.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.file_name}"',
        },
    )


@router.get("/schedules", response_model=ListResponse[ReportScheduleRead])
async def list_report_schedules(
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Approver],
) -> ListResponse[ReportScheduleRead]:
    stmt = select(ReportSchedule)
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(ReportSchedule.org_id == current_user.org_id)
    rows = list(
        (await session.execute(stmt.order_by(ReportSchedule.created_at.desc()))).scalars()
    )
    data = [ReportScheduleRead.model_validate(row) for row in rows]
    return ListResponse(data=data, pagination=Pagination(limit=max(len(data), 1), total=len(data)))


@router.post("/schedules", response_model=DataResponse[ReportScheduleRead], status_code=201)
async def create_report_schedule(
    payload: ReportScheduleCreate,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportScheduleRead]:
    if payload.create_as_status != "draft":
        raise ApiError(422, "INVALID_SCHEDULE", "Schedules may only create drafts.")
    template = await session.get(ReportTemplate, payload.template_id)
    if template is None or not can_view_template(template, current_user):
        raise ApiError(404, "NOT_FOUND", "Report template was not found.")
    row = ReportSchedule(
        org_id=current_user.org_id,
        project_id=payload.project_id,
        template_id=payload.template_id,
        interval=payload.interval,
        is_enabled=payload.is_enabled,
        create_as_status="draft",
        audience=payload.audience,
        config=payload.config,
        next_run_at=payload.next_run_at,
        created_by=current_user.id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=ReportScheduleRead.model_validate(row))


@router.patch("/schedules/{schedule_id}", response_model=DataResponse[ReportScheduleRead])
async def update_report_schedule(
    schedule_id: UUID,
    payload: ReportScheduleUpdate,
    session: SessionDep,
    current_user: Annotated[CurrentUser, _Mutator],
) -> DataResponse[ReportScheduleRead]:
    row = await session.get(ReportSchedule, schedule_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Schedule was not found.")
    if current_user.role != AppRole.SUPER_ADMIN and row.org_id != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot update this schedule.")
    data = payload.model_dump(exclude_unset=True)
    if data.get("create_as_status") not in (None, "draft"):
        raise ApiError(422, "INVALID_SCHEDULE", "Schedules may only create drafts.")
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=ReportScheduleRead.model_validate(row))
