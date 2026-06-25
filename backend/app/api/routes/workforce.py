from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, UserDep
from app.core.security import require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import SmeAllocationRead, WorkforceDashboardRead
from app.services.workforce import get_sme_allocation, get_workforce_dashboard

router = APIRouter(tags=["workforce"])


@router.get("/workforce/dashboard", response_model=DataResponse[WorkforceDashboardRead])
async def workforce_dashboard(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[WorkforceDashboardRead]:
    dashboard = await get_workforce_dashboard(session, current_user)
    return DataResponse(data=dashboard)


@router.get("/workforce/skill-matrix", response_model=DataResponse[WorkforceDashboardRead])
async def workforce_skill_matrix(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[WorkforceDashboardRead]:
    dashboard = await get_workforce_dashboard(session, current_user)
    return DataResponse(
        data=WorkforceDashboardRead(
            kpis=dashboard.kpis,
            skill_matrix=dashboard.skill_matrix,
            skill_gap_signals=dashboard.skill_gap_signals,
        )
    )


@router.get("/workforce/sme-allocation", response_model=ListResponse[SmeAllocationRead])
async def workforce_sme_allocation(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[SmeAllocationRead]:
    rows = await get_sme_allocation(session, current_user.org_id)
    return ListResponse(data=rows, pagination=Pagination(limit=100))
