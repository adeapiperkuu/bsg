from datetime import date
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from app.agents.governance.routes import jobs
from app.agents.governance.schemas.governance import (
    GovernanceJobStartRead,
    GovernanceWeeklySummaryCreate,
    GovernanceWeeklySummaryGenerateRequest,
    GovernanceWeeklySummaryListRead,
    GovernanceWeeklySummaryRead,
    GovernanceWeeklySummaryUpdate,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.charter_export import (
    CharterExportDocument,
    generate_charter_docx,
    generate_charter_pdf,
)
from app.agents.governance.services.governance_service import (
    approve_weekly_summary,
    create_weekly_summary,
    get_weekly_summary_by_id,
    list_weekly_summaries,
    update_weekly_summary_draft,
)
from app.agents.governance.services.job_service import (
    JOB_WEEKLY_SUMMARY,
    enqueue_governance_job,
)
from app.agents.governance.services.summary_service import (
    build_weekly_summary_list_reads,
    build_weekly_summary_read,
    get_latest_weekly_summary_read_cached,
    monday_of_week,
)
from app.agents.governance.timing import get_governance_timer, instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse, ListResponse, Pagination

router = APIRouter(tags=["governance"])

READ_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
    AppRole.CLIENT,
)
SUMMARY_WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
SUMMARY_EXPORT_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


@router.get(
    "/governance/weekly-summary", response_model=DataResponse[GovernanceWeeklySummaryRead | None]
)
async def get_weekly_summary(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead | None]:
    cached = await get_latest_weekly_summary_read_cached(session, current_user)
    if cached.read is None:
        timer = get_governance_timer()
        if timer is not None:
            timer.record_meta(
                execute_count=cached.execute_count,
                cache_hit=cached.cache_hit,
                detail_fetch_ms=cached.detail_fetch_ms,
                returned_row_count=0,
            )
        return DataResponse(data=None)
    read = cached.read
    response = DataResponse(data=read)
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            execute_count=cached.execute_count,
            cache_hit=cached.cache_hit,
            detail_fetch_ms=cached.detail_fetch_ms,
            enrichment_ms=cached.enrichment_ms,
            returned_row_count=1,
            response_bytes=len(response.model_dump_json().encode("utf-8")),
        )
    return response


@router.get(
    "/governance/weekly-summaries",
    response_model=ListResponse[GovernanceWeeklySummaryRead | GovernanceWeeklySummaryListRead],
)
async def list_governance_weekly_summaries(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    pagination: Pagination = Depends(),
    include_detail: bool = True,
) -> ListResponse[GovernanceWeeklySummaryRead | GovernanceWeeklySummaryListRead]:
    row_fetch_started = perf_counter()
    rows = await list_weekly_summaries(
        session,
        current_user,
        limit=pagination.limit,
        include_detail=include_detail,
    )
    row_fetch_ms = round((perf_counter() - row_fetch_started) * 1000, 1)
    enrichment_started = perf_counter()
    if include_detail:
        full_reads = [await build_weekly_summary_read(session, row) for row in rows]
        reads: list[GovernanceWeeklySummaryRead | GovernanceWeeklySummaryListRead] = full_reads
        enrichment_executes = sum(
            1 + len(read.evidence_links) + (1 if read.approved_by else 0) for read in full_reads
        )
    else:
        reads = await build_weekly_summary_list_reads(session, rows)
        enrichment_executes = 0 if not rows else 1 + int(any(read.approved_by for read in reads))
    enrichment_ms = round((perf_counter() - enrichment_started) * 1000, 1)
    response = ListResponse(
        data=reads,
        pagination=Pagination(
            limit=pagination.limit,
            offset=pagination.offset,
            total=len(reads),
            items=len(reads),
        ),
    )
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            execute_count=1 + enrichment_executes,
            cache_hit=False,
            limit=pagination.limit,
            offset=pagination.offset,
            list_row_fetch_ms=row_fetch_ms,
            enrichment_ms=enrichment_ms,
            returned_row_count=len(reads),
            response_bytes=len(response.model_dump_json().encode("utf-8")),
        )
    return response


def _safe_weekly_summary_filename(summary_week: date, extension: str) -> str:
    return f"governance_weekly_summary_{summary_week.isoformat()}.{extension}"


async def _weekly_summary_export_payload(
    session: SessionDep,
    summary_id: UUID,
    current_user: CurrentUser,
) -> tuple[GovernanceWeeklySummaryRead, CharterExportDocument]:
    summary = await get_weekly_summary_by_id(session, summary_id, current_user)
    read = await build_weekly_summary_read(session, summary)
    metadata = [
        ("Reporting Week", read.summary_week.strftime("%b %d, %Y")),
        ("Status", read.status.value.replace("_", " ").title()),
        ("Generated", read.created_at.strftime("%b %d, %Y %H:%M UTC")),
        ("Generated By", "Governance AI" if read.generated_by_ai else "Governance Team"),
        (
            "Approved",
            read.approved_at.strftime("%b %d, %Y %H:%M UTC") if read.approved_at else "Pending",
        ),
        ("Approved By", read.approved_by_name or "Pending"),
        ("Evidence Items", str(len(read.evidence_links))),
    ]
    return read, CharterExportDocument(
        title=f"Weekly Governance Summary - {read.summary_week.strftime('%b %d, %Y')}",
        metadata=metadata,
        markdown=read.summary_text,
    )


@router.get("/governance/weekly-summary/{summary_id}/export.pdf")
async def export_governance_weekly_summary_pdf(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*SUMMARY_EXPORT_ROLES)),
) -> Response:
    read, document = await _weekly_summary_export_payload(session, summary_id, current_user)
    filename = _safe_weekly_summary_filename(read.summary_week, "pdf")
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.exported",
        org_id=read.org_id,
        source_table="governance_weekly_summaries",
        source_id=read.id,
        metadata={"format": "pdf", "summary_week": read.summary_week.isoformat()},
    )
    await session.commit()
    return Response(
        content=generate_charter_pdf(document),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/governance/weekly-summary/{summary_id}/export.docx")
async def export_governance_weekly_summary_docx(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*SUMMARY_EXPORT_ROLES)),
) -> Response:
    read, document = await _weekly_summary_export_payload(session, summary_id, current_user)
    filename = _safe_weekly_summary_filename(read.summary_week, "docx")
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.exported",
        org_id=read.org_id,
        source_table="governance_weekly_summaries",
        source_id=read.id,
        metadata={"format": "docx", "summary_week": read.summary_week.isoformat()},
    )
    await session.commit()
    return Response(
        content=generate_charter_docx(document),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/governance/weekly-summary/{summary_id}",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def get_governance_weekly_summary_by_id(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    started = perf_counter()
    summary = await get_weekly_summary_by_id(session, summary_id, current_user)
    detail_fetch_ms = round((perf_counter() - started) * 1000, 1)
    enrichment_started = perf_counter()
    read = await build_weekly_summary_read(session, summary)
    enrichment_ms = round((perf_counter() - enrichment_started) * 1000, 1)
    response = DataResponse(data=read)
    timer = get_governance_timer()
    if timer is not None:
        timer.record_meta(
            execute_count=2 + len(read.evidence_links) + (1 if read.approved_by else 0),
            cache_hit=False,
            detail_fetch_ms=detail_fetch_ms,
            enrichment_ms=enrichment_ms,
            returned_row_count=1,
            response_bytes=len(response.model_dump_json().encode("utf-8")),
        )
    return response


@router.post(
    "/governance/weekly-summary/generate",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def generate_governance_weekly_summary(
    payload: GovernanceWeeklySummaryGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*SUMMARY_WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobStartRead]:
    if current_user.org_id is None:
        raise HTTPException(status_code=400, detail="Organisation context is required.")
    week = monday_of_week(payload.summary_week)
    job, deduplicated = await enqueue_governance_job(
        session,
        current_user,
        job_type=JOB_WEEKLY_SUMMARY,
        org_id=current_user.org_id,
        project_id=None,
        payload={"summary_week": week.isoformat(), "strategy_version": "weekly-summary-v1"},
    )
    return DataResponse(data=jobs.job_start(job, deduplicated))


@router.patch(
    "/governance/weekly-summary/{summary_id}",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def patch_governance_weekly_summary(
    summary_id: UUID,
    payload: GovernanceWeeklySummaryUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*SUMMARY_WRITE_ROLES)),
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
    current_user: CurrentUser = Depends(require_role(*SUMMARY_WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await approve_weekly_summary(session, summary_id, current_user)
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post("/governance/weekly-summary", response_model=DataResponse[GovernanceWeeklySummaryRead])
async def post_weekly_summary(
    payload: GovernanceWeeklySummaryCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*SUMMARY_WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await create_weekly_summary(
        session,
        current_user,
        summary_week=payload.summary_week,
        summary_text=payload.summary_text,
        evidence_links=payload.evidence_links,
    )
    return DataResponse(data=await build_weekly_summary_read(session, summary))


instrument_governance_routes(router)
