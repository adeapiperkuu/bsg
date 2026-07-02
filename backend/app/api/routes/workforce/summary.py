from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse
from app.schemas.domain import ProjectWorkforceSummaryRead
from app.services.scoping import get_visible_project
from app.services.workforce import get_project_workforce_summary

router = APIRouter()


@router.get(
    "/projects/{project_id}/workforce-summary",
    response_model=DataResponse[ProjectWorkforceSummaryRead],
)
async def get_project_workforce_summary_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
) -> DataResponse[ProjectWorkforceSummaryRead]:
    project = await get_visible_project(session, project_id, current_user)
    summary = await get_project_workforce_summary(session, project, current_user)
    return DataResponse(data=summary)
