from app.api.deps import SessionDep, UserDep
from app.schemas.common import DataResponse
from app.schemas.domain import (
    DashboardSummaryRead,
    ExecutiveSummaryRead,
    TowerActivityRead,
    TowerEscalationsRead,
    TowerHealthRead,
    TowerPulseRead,
    TowerWorkRead,
)
from app.services.dashboard import get_dashboard_summary
from app.services.operational_tower import (
    get_executive_summary,
    get_tower_activity,
    get_tower_escalations,
    get_tower_health,
    get_tower_pulse,
    get_tower_work,
)
from fastapi import APIRouter

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DataResponse[DashboardSummaryRead])
async def dashboard_summary(session: SessionDep, current_user: UserDep) -> DataResponse[DashboardSummaryRead]:
    summary = await get_dashboard_summary(session, current_user)
    return DataResponse(data=summary)


@router.get("/dashboard/operational-tower/pulse", response_model=DataResponse[TowerPulseRead])
async def operational_tower_pulse(session: SessionDep, current_user: UserDep) -> DataResponse[TowerPulseRead]:
    """Project counts, quality/risk trends and open alerts — the first content to paint."""
    data = await get_tower_pulse(session, current_user)
    return DataResponse(data=TowerPulseRead.model_validate(data))


@router.get("/dashboard/operational-tower/escalations", response_model=DataResponse[TowerEscalationsRead])
async def operational_tower_escalations(session: SessionDep, current_user: UserDep) -> DataResponse[TowerEscalationsRead]:
    """Open / critical escalation counts."""
    data = await get_tower_escalations(session, current_user)
    return DataResponse(data=TowerEscalationsRead.model_validate(data))


@router.get("/dashboard/operational-tower/work", response_model=DataResponse[TowerWorkRead])
async def operational_tower_work(session: SessionDep, current_user: UserDep) -> DataResponse[TowerWorkRead]:
    """Pending AI recommendations and upcoming milestones."""
    data = await get_tower_work(session, current_user)
    return DataResponse(data=TowerWorkRead.model_validate(data))


@router.get("/dashboard/operational-tower/activity", response_model=DataResponse[TowerActivityRead])
async def operational_tower_activity(session: SessionDep, current_user: UserDep) -> DataResponse[TowerActivityRead]:
    """Team utilization and the recent activity feed."""
    data = await get_tower_activity(session, current_user)
    return DataResponse(data=TowerActivityRead.model_validate(data))


@router.get("/dashboard/operational-tower/health", response_model=DataResponse[TowerHealthRead])
async def operational_tower_health(session: SessionDep, current_user: UserDep) -> DataResponse[TowerHealthRead]:
    """Portfolio health distribution + schedule confidence. Slowest: runs the scoring pipeline."""
    data = await get_tower_health(session, current_user)
    return DataResponse(data=TowerHealthRead.model_validate(data))


@router.get("/dashboard/executive-summary", response_model=DataResponse[ExecutiveSummaryRead | None])
async def executive_summary(session: SessionDep, current_user: UserDep) -> DataResponse[ExecutiveSummaryRead | None]:
    """Latest stored AI executive summary. Loaded separately so it never blocks the dashboard."""
    data = await get_executive_summary(session, current_user)
    return DataResponse(data=ExecutiveSummaryRead.model_validate(data) if data else None)
