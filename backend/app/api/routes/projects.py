from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.security import require_role
from app.db.models import AppRole, Milestone, Project
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import MilestoneRead, ProjectCreate, ProjectRead, ProjectUpdate
from app.services.scoping import get_visible_project, scoped_project_query

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=ListResponse[ProjectRead])
async def list_projects(session: SessionDep, current_user: UserDep, limit: LimitQuery = 50) -> ListResponse[ProjectRead]:
    rows = (await session.execute(scoped_project_query(current_user).limit(limit))).scalars()
    return ListResponse(data=[ProjectRead.model_validate(row) for row in rows], pagination=Pagination(limit=limit))


@router.post("/projects", response_model=DataResponse[ProjectRead])
async def create_project(
    payload: ProjectCreate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectRead]:
    project = Project(org_id=current_user.org_id, **payload.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return DataResponse(data=ProjectRead.model_validate(project))


@router.get("/projects/{project_id}", response_model=DataResponse[ProjectRead])
async def get_project(project_id: UUID, session: SessionDep, current_user: UserDep) -> DataResponse[ProjectRead]:
    return DataResponse(data=ProjectRead.model_validate(await get_visible_project(session, project_id, current_user)))


@router.patch("/projects/{project_id}", response_model=DataResponse[ProjectRead])
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectRead]:
    project = await get_visible_project(session, project_id, current_user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await session.commit()
    await session.refresh(project)
    return DataResponse(data=ProjectRead.model_validate(project))


@router.get("/projects/{project_id}/milestones", response_model=ListResponse[MilestoneRead])
async def list_milestones(project_id: UUID, session: SessionDep, current_user: UserDep) -> ListResponse[MilestoneRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(Milestone)
            .where(Milestone.project_id == project.id, Milestone.deleted_at.is_(None))
            .order_by(Milestone.planned_date)
        )
    ).scalars()
    return ListResponse(data=[MilestoneRead.model_validate(row) for row in rows], pagination=Pagination(limit=100))
