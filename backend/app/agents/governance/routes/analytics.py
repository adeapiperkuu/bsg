from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.governance.routes import jobs
from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsDetailRead,
    GovernanceAnalyticsExportJobRequest,
    GovernanceAnalyticsRead,
    GovernanceAnalyticsSummaryRead,
    GovernanceJobStartRead,
    GovernanceMonitoringRead,
)
from app.agents.governance.services.analytics_service import (
    get_governance_analytics,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.agents.governance.services.job_service import (
    JOB_ANALYTICS_EXPORT,
    enqueue_governance_job,
)
from app.agents.governance.services.monitoring_service import get_governance_monitoring
from app.agents.governance.timing import instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse
from app.services.scoping import get_visible_project

router = APIRouter(tags=["governance"])

READ_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
    AppRole.CLIENT,
)
AI_RECOMMENDATION_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
)
MONITORING_ROLES = (AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


async def _enqueue_analytics_export_job(
    payload: GovernanceAnalyticsExportJobRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> DataResponse[GovernanceJobStartRead]:
    project = (
        await get_visible_project(session, payload.project_id, current_user)
        if payload.project_id
        else None
    )
    org_id = project.org_id if project else current_user.org_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organisation context is required.")
    job, deduplicated = await enqueue_governance_job(
        session,
        current_user,
        job_type=JOB_ANALYTICS_EXPORT,
        org_id=org_id,
        project_id=payload.project_id,
        payload=payload.model_dump(mode="json"),
    )
    return DataResponse(data=jobs.job_start(job, deduplicated))


@router.get(
    "/governance/analytics/summary", response_model=DataResponse[GovernanceAnalyticsSummaryRead]
)
async def governance_analytics_summary(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsSummaryRead]:
    return DataResponse(
        data=await get_governance_analytics_summary(
            session,
            current_user,
            days=days,
            project_id=project_id,
            vertical=vertical,
        )
    )


@router.get(
    "/governance/analytics/detail", response_model=DataResponse[GovernanceAnalyticsDetailRead]
)
async def governance_analytics_detail(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsDetailRead]:
    return DataResponse(
        data=await get_governance_analytics_detail(
            session,
            current_user,
            days=days,
            project_id=project_id,
            vertical=vertical,
        )
    )


@router.get("/governance/analytics", response_model=DataResponse[GovernanceAnalyticsRead])
async def governance_analytics(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsRead]:
    # TODO(deprecate): Monolithic analytics payload. The live /governance UI uses
    # GET /governance/analytics/summary + GET /governance/analytics/detail instead.
    # Keep this route for backward compatibility until external callers are confirmed gone.
    return DataResponse(
        data=await get_governance_analytics(
            session,
            current_user,
            days=days,
            project_id=project_id,
            vertical=vertical,
        )
    )


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


@router.get(
    "/governance/analytics/export.csv",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def export_governance_analytics_csv(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceJobStartRead]:
    return await _enqueue_analytics_export_job(
        GovernanceAnalyticsExportJobRequest(
            days=days, project_id=project_id, vertical=vertical, format="csv"
        ),
        session,
        current_user,
    )


@router.get(
    "/governance/analytics/export.pdf",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def export_governance_analytics_pdf(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceJobStartRead]:
    return await _enqueue_analytics_export_job(
        GovernanceAnalyticsExportJobRequest(
            days=days, project_id=project_id, vertical=vertical, format="pdf"
        ),
        session,
        current_user,
    )


@router.post(
    "/governance/analytics/exports",
    response_model=DataResponse[GovernanceJobStartRead],
    status_code=202,
)
async def start_governance_analytics_export(
    payload: GovernanceAnalyticsExportJobRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceJobStartRead]:
    return await _enqueue_analytics_export_job(payload, session, current_user)


instrument_governance_routes(router)
