from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, Milestone, Program, Project
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import MilestoneRead, ProjectCreate, ProjectRead, ProjectUpdate
from app.services.scoping import get_visible_project, scoped_project_query

router = APIRouter(tags=["projects"])


async def _resolve_program_for_org(
    session: AsyncSession,
    *,
    program_id: UUID | None,
    org_id: UUID,
) -> UUID | None:
    if program_id is None:
        return None
    program = (
        await session.execute(
            select(Program).where(
                Program.id == program_id,
                Program.org_id == org_id,
                Program.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if program is None:
        raise ApiError(400, "VALIDATION_ERROR", "Selected project was not found in this organisation.")
    return program.id


@router.get("/projects", response_model=ListResponse[ProjectRead])
async def list_projects(session: SessionDep, current_user: UserDep, limit: LimitQuery = 50) -> ListResponse[ProjectRead]:
    # Order by name (matching dashboard_service.get_portfolio_data) so the truncated
    # `limit` window is deterministic. Without ORDER BY, Postgres may return a different
    # subset and ordering per request, so callers that render row N or default to the
    # first row cannot rely on either being stable. Tie-break on id to keep the window
    # total when two projects share a name.
    rows = (
        await session.execute(
            scoped_project_query(current_user)
            .order_by(Project.name.asc(), Project.id.asc())
            .limit(limit)
        )
    ).scalars()
    return ListResponse(data=[ProjectRead.model_validate(row) for row in rows], pagination=Pagination(limit=limit))


@router.post("/projects", response_model=DataResponse[ProjectRead])
async def create_project(
    payload: ProjectCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectRead]:
    org_id = payload.org_id if current_user.role == AppRole.SUPER_ADMIN and payload.org_id else current_user.org_id
    data = payload.model_dump(exclude={"org_id"})
    data["program_id"] = await _resolve_program_for_org(
        session, program_id=payload.program_id, org_id=org_id
    )
    project = Project(org_id=org_id, **data)
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
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectRead]:
    project = await get_visible_project(session, project_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "program_id" in data:
        data["program_id"] = await _resolve_program_for_org(
            session, program_id=data["program_id"], org_id=project.org_id
        )
    for key, value in data.items():
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
