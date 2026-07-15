from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.agents.governance.schemas.governance import GovernanceJobRead, GovernanceJobStartRead
from app.agents.governance.services.job_export_service import resolve_export_path
from app.agents.governance.services.job_service import (
    ACTIVE_STATUSES,
    JOB_ANALYTICS_EXPORT,
    TRANSIENT_CODES,
    cancel_governance_job,
    get_governance_job,
    list_governance_jobs,
    retry_governance_job,
)
from app.agents.governance.timing import instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, GovernanceJob, GovernanceJobStatus
from app.schemas.common import DataResponse, ListResponse, Pagination

router = APIRouter(tags=["governance"])

AI_RECOMMENDATION_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
)


def _job_read(job: GovernanceJob) -> GovernanceJobRead:
    result = dict(job.result_data or {}) if job.result_data else None
    if result:
        result.pop("storage_path", None)
    return GovernanceJobRead(
        id=job.id,
        org_id=job.org_id,
        project_id=job.project_id,
        job_type=job.job_type,
        status=job.status,
        progress_stage=job.progress_stage,
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        requested_at=job.requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        next_attempt_at=job.next_attempt_at,
        retryable=job.status == GovernanceJobStatus.FAILED and job.error_code in TRANSIENT_CODES,
        cancellable=job.status in ACTIVE_STATUSES,
        error_code=job.error_code,
        error_message=job.error_message,
        result_record_type=job.result_record_type,
        result_record_id=job.result_record_id,
        result=result,
    )


def job_start(job: GovernanceJob, deduplicated: bool) -> GovernanceJobStartRead:
    return GovernanceJobStartRead(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        deduplicated=deduplicated,
    )


@router.get("/governance/jobs/{job_id}", response_model=DataResponse[GovernanceJobRead])
async def get_governance_background_job(
    job_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceJobRead]:
    return DataResponse(data=_job_read(await get_governance_job(session, current_user, job_id)))


@router.get("/governance/jobs", response_model=ListResponse[GovernanceJobRead])
async def list_governance_background_jobs(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    job_type: str | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    active_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
) -> ListResponse[GovernanceJobRead]:
    rows = await list_governance_jobs(
        session,
        current_user,
        job_type=job_type,
        project_id=project_id,
        active_only=active_only,
        limit=limit,
    )
    return ListResponse(data=[_job_read(row) for row in rows], pagination=Pagination(limit=limit))


@router.post(
    "/governance/jobs/{job_id}/cancel",
    response_model=DataResponse[GovernanceJobRead],
)
async def cancel_governance_background_job(
    job_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobRead]:
    return DataResponse(data=_job_read(await cancel_governance_job(session, current_user, job_id)))


@router.post(
    "/governance/jobs/{job_id}/retry",
    response_model=DataResponse[GovernanceJobRead],
    status_code=202,
)
async def retry_governance_background_job(
    job_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobRead]:
    return DataResponse(data=_job_read(await retry_governance_job(session, current_user, job_id)))


@router.get("/governance/jobs/{job_id}/download")
async def download_governance_background_job(
    job_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> FileResponse:
    job = await get_governance_job(session, current_user, job_id)
    if job.status != GovernanceJobStatus.SUCCEEDED or job.job_type != JOB_ANALYTICS_EXPORT:
        raise HTTPException(status_code=409, detail="Export is not ready.")
    path, file_name, content_type = resolve_export_path(job.result_data)
    return FileResponse(path, media_type=content_type, filename=file_name)


instrument_governance_routes(router)
