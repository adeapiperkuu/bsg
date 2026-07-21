"""Workforce Optimization API routes (Phase 16)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.core.field_permissions import authorize_fields
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse
from app.schemas.domain import WorkforceOptimizationRead
from app.services.scoping import get_visible_project
from app.services.workforce_optimization import build_workforce_optimization

router = APIRouter()

_READ_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


@router.get(
    "/projects/{project_id}/workforce-optimization",
    response_model=DataResponse[WorkforceOptimizationRead],
)
async def get_workforce_optimization_route(
    project_id: UUID,
    session: SessionDep,
    skill_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> DataResponse[WorkforceOptimizationRead]:
    project = await get_visible_project(session, project_id, current_user)
    optimization = await build_workforce_optimization(
        session,
        project,
        current_user,
        skill_id=skill_id,
    )
    # Phase 19.1 — strip unauthorized fields before the response leaves the API.
    filtered = authorize_fields(
        optimization,
        current_user.role,
        domain="workforce_optimization",
    )
    return DataResponse(data=WorkforceOptimizationRead.model_validate(filtered))
