from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.client_intelligence import (
    ClientDashboardRead,
    ClientIntelligenceOverviewRead,
    ClientIntelligenceQueryHistoryRead,
    ClientIntelligenceQueryRead,
    ClientIntelligenceQuestionCreate,
    ClientIntelligenceReportHistoryRead,
    ClientIntelligenceReportStatus,
    ClientIntelligenceSummaryRead,
    ClientMasterRowRead,
    DeliveryConfidenceHistoryRead,
)
from app.agents.client_intelligence.go_live_contracts import GoLiveAssessment
from app.agents.client_intelligence.readiness_contracts import ReadinessAssessment
from app.agents.client_intelligence.recommendations import ReadinessRecommendationSet
from app.schemas.client_intelligence_reporting import (
    ClientReportApprovalRead,
    ClientReportDeliveryRead,
    ClientReportPackageRead,
    ClientReportScheduleCreate,
    ClientReportScheduleRead,
    ClientReportScheduleUpdate,
    ReportBuilderExportRequest,
    ReportDraftGenerateRequest,
    ReportGovernanceTransitionRequest,
)
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.services.client_intelligence import (
    DELIVERY_CONFIDENCE_HISTORY_LIMIT,
    QUERY_HISTORY_DEFAULT_LIMIT,
    QUERY_HISTORY_MAX_LIMIT,
    REPORT_HISTORY_DEFAULT_LIMIT,
    REPORT_HISTORY_MAX_LIMIT,
    build_client_dashboard,
    build_client_intelligence_overview,
    build_client_intelligence_query_history,
    build_client_intelligence_report_history,
    build_client_intelligence_summary,
    build_client_master,
    build_delivery_confidence_history,
    build_go_live_assessment,
    build_project_readiness,
    build_readiness_recommendations,
    create_client_intelligence_query,
)
from app.services import client_intelligence_reporting as reporting_service

router = APIRouter(tags=["client-intelligence"])

_InternalRoleDep = Annotated[
    CurrentUser,
    Depends(
        require_role(
            AppRole.DELIVERY_MANAGER,
            AppRole.BSG_LEADERSHIP,
            AppRole.SUPER_ADMIN,
        )
    ),
]

_MutationRoleDep = Annotated[
    CurrentUser,
    Depends(
        require_role(
            AppRole.DELIVERY_MANAGER,
            AppRole.SUPER_ADMIN,
        )
    ),
]


@router.get(
    "/client-intelligence/summary",
    response_model=DataResponse[ClientIntelligenceSummaryRead],
)
async def get_client_intelligence_summary(
    session: SessionDep,
    current_user: _InternalRoleDep,
    project_id: Annotated[UUID | None, Query()] = None,
) -> DataResponse[ClientIntelligenceSummaryRead]:
    summary = await build_client_intelligence_summary(
        session,
        current_user,
        project_id=project_id,
    )
    return DataResponse(data=summary)


@router.get(
    "/client-intelligence/master",
    response_model=ListResponse[ClientMasterRowRead],
)
async def get_client_master(
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> ListResponse[ClientMasterRowRead]:
    rows = await build_client_master(session, current_user)
    return ListResponse(
        data=rows,
        pagination=Pagination(limit=100),
    )


@router.get(
    "/projects/{project_id}/client-intelligence/overview",
    response_model=DataResponse[ClientIntelligenceOverviewRead],
)
async def get_client_intelligence_overview(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    as_of: Annotated[date | None, Query()] = None,
) -> DataResponse[ClientIntelligenceOverviewRead]:
    overview = await build_client_intelligence_overview(
        session,
        current_user,
        project_id,
        as_of=as_of,
    )
    return DataResponse(data=overview)


@router.get(
    "/projects/{project_id}/client-intelligence/dashboard",
    response_model=DataResponse[ClientDashboardRead],
)
async def get_client_dashboard(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    as_of: Annotated[date | None, Query()] = None,
) -> DataResponse[ClientDashboardRead]:
    dashboard = await build_client_dashboard(
        session,
        current_user,
        project_id,
        as_of=as_of,
    )
    return DataResponse(data=dashboard)


@router.get(
    "/projects/{project_id}/client-intelligence/readiness",
    response_model=DataResponse[ReadinessAssessment],
)
async def get_project_readiness(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    as_of: Annotated[date | None, Query()] = None,
) -> DataResponse[ReadinessAssessment]:
    readiness = await build_project_readiness(
        session, current_user, project_id, as_of=as_of
    )
    return DataResponse(data=readiness)


@router.post(
    "/projects/{project_id}/client-intelligence/readiness/assess",
    response_model=DataResponse[ReadinessAssessment],
)
async def assess_project_readiness_route(
    project_id: UUID,
    session: SessionDep,
    current_user: _MutationRoleDep,
    as_of: Annotated[date | None, Query()] = None,
) -> DataResponse[ReadinessAssessment]:
    readiness = await build_project_readiness(
        session, current_user, project_id, as_of=as_of
    )
    return DataResponse(data=readiness)


@router.get(
    "/projects/{project_id}/client-intelligence/go-live",
    response_model=DataResponse[GoLiveAssessment],
)
async def get_go_live_readiness(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    as_of: Annotated[date | None, Query()] = None,
) -> DataResponse[GoLiveAssessment]:
    assessment = await build_go_live_assessment(
        session, current_user, project_id, as_of=as_of
    )
    return DataResponse(data=assessment)


@router.get(
    "/projects/{project_id}/client-intelligence/recommendations",
    response_model=DataResponse[ReadinessRecommendationSet],
)
async def get_readiness_recommendations(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    as_of: Annotated[date | None, Query()] = None,
) -> DataResponse[ReadinessRecommendationSet]:
    recommendations = await build_readiness_recommendations(
        session, current_user, project_id, as_of=as_of
    )
    return DataResponse(data=recommendations)


@router.get(
    "/projects/{project_id}/client-intelligence/report-schedules",
    response_model=ListResponse[ClientReportScheduleRead],
)
async def list_client_report_schedules(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> ListResponse[ClientReportScheduleRead]:
    rows = await reporting_service.list_report_schedules(
        session, current_user, project_id
    )
    return ListResponse(data=rows, pagination=Pagination(limit=20))


@router.post(
    "/projects/{project_id}/client-intelligence/report-schedules",
    response_model=DataResponse[ClientReportScheduleRead],
)
async def upsert_client_report_schedule(
    project_id: UUID,
    payload: ClientReportScheduleCreate,
    session: SessionDep,
    current_user: _MutationRoleDep,
) -> DataResponse[ClientReportScheduleRead]:
    row = await reporting_service.upsert_report_schedule(
        session, current_user, project_id, payload
    )
    await session.commit()
    return DataResponse(data=row)


@router.patch(
    "/client-intelligence/report-schedules/{schedule_id}",
    response_model=DataResponse[ClientReportScheduleRead],
)
async def patch_client_report_schedule(
    schedule_id: UUID,
    payload: ClientReportScheduleUpdate,
    session: SessionDep,
    current_user: _MutationRoleDep,
) -> DataResponse[ClientReportScheduleRead]:
    row = await reporting_service.update_report_schedule(
        session, current_user, schedule_id, payload
    )
    await session.commit()
    return DataResponse(data=row)


@router.post(
    "/projects/{project_id}/client-intelligence/report-packages/draft",
    response_model=DataResponse[ClientReportPackageRead],
)
async def draft_client_report_package(
    project_id: UUID,
    payload: ReportDraftGenerateRequest,
    session: SessionDep,
    current_user: _MutationRoleDep,
) -> DataResponse[ClientReportPackageRead]:
    package = await reporting_service.generate_scheduled_report_draft(
        session,
        current_user,
        project_id,
        cadence=payload.cadence,
        schedule_id=payload.schedule_id,
        title=payload.title,
        sections=payload.sections or None,
    )
    await session.commit()
    return DataResponse(data=package)


@router.post(
    "/projects/{project_id}/client-intelligence/report-schedules/run-due",
    response_model=ListResponse[ClientReportPackageRead],
)
async def run_due_client_report_schedules(
    project_id: UUID,
    session: SessionDep,
    current_user: _MutationRoleDep,
) -> ListResponse[ClientReportPackageRead]:
    packages = await reporting_service.run_due_report_schedules(
        session, current_user, project_id
    )
    await session.commit()
    return ListResponse(data=packages, pagination=Pagination(limit=50))


@router.get(
    "/projects/{project_id}/client-intelligence/report-packages",
    response_model=ListResponse[ClientReportPackageRead],
)
async def list_client_report_packages(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ListResponse[ClientReportPackageRead]:
    rows = await reporting_service.list_report_packages(
        session, current_user, project_id, limit=limit
    )
    return ListResponse(data=rows, pagination=Pagination(limit=limit))


@router.get(
    "/client-intelligence/report-packages/{package_id}",
    response_model=DataResponse[ClientReportPackageRead],
)
async def get_client_report_package(
    package_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> DataResponse[ClientReportPackageRead]:
    package = await reporting_service.get_report_package(
        session, current_user, package_id
    )
    return DataResponse(data=package)


@router.get(
    "/client-intelligence/report-packages/{package_id}/approvals",
    response_model=ListResponse[ClientReportApprovalRead],
)
async def list_client_report_approvals(
    package_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> ListResponse[ClientReportApprovalRead]:
    rows = await reporting_service.list_report_approvals(
        session, current_user, package_id
    )
    return ListResponse(data=rows, pagination=Pagination(limit=100))


@router.get(
    "/client-intelligence/report-packages/{package_id}/deliveries",
    response_model=ListResponse[ClientReportDeliveryRead],
)
async def list_client_report_deliveries(
    package_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> ListResponse[ClientReportDeliveryRead]:
    rows = await reporting_service.list_report_deliveries(
        session, current_user, package_id
    )
    return ListResponse(data=rows, pagination=Pagination(limit=50))


@router.post(
    "/client-intelligence/report-packages/{package_id}/governance",
    response_model=DataResponse[ClientReportPackageRead],
)
async def transition_client_report_governance(
    package_id: UUID,
    payload: ReportGovernanceTransitionRequest,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> DataResponse[ClientReportPackageRead]:
    package = await reporting_service.transition_report_governance(
        session, current_user, package_id, payload
    )
    await session.commit()
    return DataResponse(data=package)


@router.post(
    "/client-intelligence/report-packages/{package_id}/export",
)
async def export_client_report_package(
    package_id: UUID,
    payload: ReportBuilderExportRequest,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> Response:
    content, media_type, extension, package = await reporting_service.export_report_package(
        session, current_user, package_id, payload
    )
    filename = f"client-report-{package.id}.{extension}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/projects/{project_id}/client-intelligence/delivery-confidence-history",
    response_model=DataResponse[DeliveryConfidenceHistoryRead],
)
async def get_delivery_confidence_history(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    limit: Annotated[
        int,
        Query(ge=1, le=DELIVERY_CONFIDENCE_HISTORY_LIMIT),
    ] = DELIVERY_CONFIDENCE_HISTORY_LIMIT,
) -> DataResponse[DeliveryConfidenceHistoryRead]:
    history = await build_delivery_confidence_history(
        session,
        current_user,
        project_id,
        limit=limit,
    )
    return DataResponse(data=history)


@router.get(
    "/projects/{project_id}/client-intelligence/reports",
    response_model=DataResponse[ClientIntelligenceReportHistoryRead],
)
async def get_client_intelligence_report_history(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    limit: Annotated[
        int,
        Query(ge=1, le=REPORT_HISTORY_MAX_LIMIT),
    ] = REPORT_HISTORY_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[ClientIntelligenceReportStatus | None, Query()] = None,
) -> DataResponse[ClientIntelligenceReportHistoryRead]:
    history = await build_client_intelligence_report_history(
        session,
        current_user,
        project_id,
        limit=limit,
        offset=offset,
        status_filter=status,
    )
    return DataResponse(data=history)


@router.post(
    "/projects/{project_id}/client-intelligence/queries",
    response_model=DataResponse[ClientIntelligenceQueryRead],
)
async def create_client_intelligence_query_route(
    project_id: UUID,
    payload: ClientIntelligenceQuestionCreate,
    session: SessionDep,
    current_user: _InternalRoleDep,
) -> DataResponse[ClientIntelligenceQueryRead]:
    result = await create_client_intelligence_query(
        session,
        current_user,
        project_id,
        question=payload.question,
    )
    await session.commit()
    return DataResponse(data=result)


@router.get(
    "/projects/{project_id}/client-intelligence/queries",
    response_model=DataResponse[ClientIntelligenceQueryHistoryRead],
)
async def get_client_intelligence_query_history(
    project_id: UUID,
    session: SessionDep,
    current_user: _InternalRoleDep,
    limit: Annotated[
        int,
        Query(ge=1, le=QUERY_HISTORY_MAX_LIMIT),
    ] = QUERY_HISTORY_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DataResponse[ClientIntelligenceQueryHistoryRead]:
    history = await build_client_intelligence_query_history(
        session,
        current_user,
        project_id,
        limit=limit,
        offset=offset,
    )
    return DataResponse(data=history)
