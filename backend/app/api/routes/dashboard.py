from app.api.deps import SessionDep, UserDep
from app.schemas.common import DataResponse
from app.schemas.domain import (
    DashboardSummaryRead,
    ExecutiveSummaryRead,
    OperationalTowerRead,
)
from app.services.dashboard import get_dashboard_summary
from app.services.operational_tower import get_executive_summary, get_operational_tower
from fastapi import APIRouter

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DataResponse[DashboardSummaryRead])
async def dashboard_summary(session: SessionDep, current_user: UserDep) -> DataResponse[DashboardSummaryRead]:
    summary = await get_dashboard_summary(session, current_user)
    return DataResponse(data=summary)


@router.get("/dashboard/operational-tower", response_model=DataResponse[OperationalTowerRead])
async def operational_tower(session: SessionDep, current_user: UserDep) -> DataResponse[OperationalTowerRead]:
    """Every deterministic Operational Tower section in one optimized payload."""
    data = await get_operational_tower(session, current_user)
    return DataResponse(data=OperationalTowerRead.model_validate(data))


@router.get("/dashboard/executive-summary", response_model=DataResponse[ExecutiveSummaryRead | None])
async def executive_summary(session: SessionDep, current_user: UserDep) -> DataResponse[ExecutiveSummaryRead | None]:
    """Latest stored AI executive summary. Loaded separately so it never blocks the dashboard."""
    data = await get_executive_summary(session, current_user)
    return DataResponse(data=ExecutiveSummaryRead.model_validate(data) if data else None)
