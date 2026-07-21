from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.client_intelligence import (
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
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.services.client_intelligence import (
    DELIVERY_CONFIDENCE_HISTORY_LIMIT,
    QUERY_HISTORY_DEFAULT_LIMIT,
    QUERY_HISTORY_MAX_LIMIT,
    REPORT_HISTORY_DEFAULT_LIMIT,
    REPORT_HISTORY_MAX_LIMIT,
    build_client_intelligence_overview,
    build_client_intelligence_query_history,
    build_client_intelligence_report_history,
    build_client_intelligence_summary,
    build_client_master,
    build_delivery_confidence_history,
    create_client_intelligence_query,
)

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