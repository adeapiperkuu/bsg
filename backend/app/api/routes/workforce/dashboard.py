from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse
from app.schemas.domain import ProjectWorkforceDashboardRead
from app.services.scoping import get_visible_project
from app.services.workforce_dashboard import get_project_workforce_dashboard

router = APIRouter()


@router.get(
    "/projects/{project_id}/workforce-dashboard",
    response_model=DataResponse[ProjectWorkforceDashboardRead],
)
async def get_project_workforce_dashboard_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
) -> DataResponse[ProjectWorkforceDashboardRead]:
    project = await get_visible_project(session, project_id, current_user)
    dashboard = await get_project_workforce_dashboard(session, project, current_user)
    return DataResponse(data=dashboard)
