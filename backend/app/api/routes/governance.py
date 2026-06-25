from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents.governance.dependencies import create_project_dependency, list_project_dependencies
from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, Project
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    GovernanceDashboardRead,
    ProjectDependencyCreate,
    ProjectDependencyRead,
)
from app.services.governance import get_governance_dashboard
from app.services.scoping import get_visible_project

router = APIRouter(tags=["governance"])


@router.get("/governance/dashboard", response_model=DataResponse[GovernanceDashboardRead])
async def governance_dashboard(
    session: SessionDep,
    current_user: UserDep,
    project_id: UUID = Query(...),
) -> DataResponse[GovernanceDashboardRead]:
    project = await get_visible_project(session, project_id, current_user)
    dashboard = await get_governance_dashboard(session, project, current_user)
    return DataResponse(data=dashboard)


@router.get("/projects/{project_id}/dependencies", response_model=ListResponse[ProjectDependencyRead])
async def get_dependencies(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> ListResponse[ProjectDependencyRead]:
    project = await get_visible_project(session, project_id, current_user)
    deps = await list_project_dependencies(session, project.id)
    return ListResponse(
        data=[ProjectDependencyRead.model_validate(d) for d in deps],
        pagination=Pagination(limit=50),
    )


@router.post("/projects/{project_id}/dependencies", response_model=DataResponse[ProjectDependencyRead])
async def add_dependency(
    project_id: UUID,
    payload: ProjectDependencyCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectDependencyRead]:
    project = await get_visible_project(session, project_id, current_user)
    target = (
        await session.execute(
            select(Project).where(Project.id == payload.to_project_id, Project.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if target is None or (current_user.role != AppRole.SUPER_ADMIN and target.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Target project was not found.")

    dep = await create_project_dependency(
        session,
        project,
        to_project_id=payload.to_project_id,
        dependency_type=payload.dependency_type,
        due_date=payload.due_date,
        notes=payload.notes,
    )
    await session.commit()
    await session.refresh(dep)
    return DataResponse(data=ProjectDependencyRead.model_validate(dep))
