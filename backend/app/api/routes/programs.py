from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, Program, Project
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import ProgramCreate, ProgramRead, ProgramUpdate
from app.services.scoping import scoped_project_query

router = APIRouter(tags=["programs"])


def scoped_program_query(current_user: CurrentUser):
    query = select(Program).where(Program.deleted_at.is_(None))
    if current_user.role == AppRole.SUPER_ADMIN:
        return query
    if current_user.role in {AppRole.DELIVERY_MANAGER, AppRole.CLIENT}:
        return query.where(Program.org_id == current_user.org_id)
    if current_user.role == AppRole.BSG_LEADERSHIP:
        return query
    return query.where(Program.id.is_(None))


async def get_visible_program(
    session: AsyncSession,
    program_id: UUID,
    current_user: CurrentUser,
) -> Program:
    program = (
        await session.execute(
            scoped_program_query(current_user).where(Program.id == program_id)
        )
    ).scalar_one_or_none()
    if program is None:
        raise ApiError(404, "NOT_FOUND", "Project was not found.")
    return program


def _to_read(program: Program, scope_count: int = 0) -> ProgramRead:
    return ProgramRead(
        id=program.id,
        org_id=program.org_id,
        name=program.name,
        description=program.description,
        created_at=program.created_at,
        updated_at=program.updated_at,
        scope_count=scope_count,
    )


@router.get("/programs", response_model=ListResponse[ProgramRead])
async def list_programs(
    session: SessionDep,
    current_user: UserDep,
    limit: LimitQuery = 100,
) -> ListResponse[ProgramRead]:
    programs = list(
        (
            await session.execute(
                scoped_program_query(current_user).order_by(Program.name.asc(), Program.id.asc()).limit(limit)
            )
        ).scalars()
    )
    if not programs:
        return ListResponse(data=[], pagination=Pagination(limit=limit))

    program_ids = [p.id for p in programs]
    # Scope counts only for projects the caller can see.
    visible_projects = scoped_project_query(current_user).where(
        Project.program_id.in_(program_ids),
        Project.deleted_at.is_(None),
    ).subquery()
    counts = {
        row.program_id: int(row.cnt)
        for row in (
            await session.execute(
                select(visible_projects.c.program_id, func.count().label("cnt"))
                .select_from(visible_projects)
                .group_by(visible_projects.c.program_id)
            )
        ).all()
        if row.program_id is not None
    }
    return ListResponse(
        data=[_to_read(p, counts.get(p.id, 0)) for p in programs],
        pagination=Pagination(limit=limit),
    )


@router.post("/programs", response_model=DataResponse[ProgramRead])
async def create_program(
    payload: ProgramCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProgramRead]:
    org_id = payload.org_id if current_user.role == AppRole.SUPER_ADMIN and payload.org_id else current_user.org_id
    if org_id is None:
        raise ApiError(400, "VALIDATION_ERROR", "Organisation is required.")

    name = payload.name.strip()
    if not name:
        raise ApiError(400, "VALIDATION_ERROR", "Project name is required.")

    existing = (
        await session.execute(
            select(Program).where(
                Program.org_id == org_id,
                func.lower(Program.name) == name.lower(),
                Program.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "CONFLICT", "A project with this name already exists.")

    program = Program(org_id=org_id, name=name, description=payload.description)
    session.add(program)
    await session.commit()
    await session.refresh(program)
    return DataResponse(data=_to_read(program, 0))


@router.get("/programs/{program_id}", response_model=DataResponse[ProgramRead])
async def get_program(
    program_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[ProgramRead]:
    program = await get_visible_program(session, program_id, current_user)
    count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.program_id == program.id,
                    Project.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        or 0
    )
    return DataResponse(data=_to_read(program, count))


@router.patch("/programs/{program_id}", response_model=DataResponse[ProgramRead])
async def update_program(
    program_id: UUID,
    payload: ProgramUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProgramRead]:
    program = await get_visible_program(session, program_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        name = data["name"].strip()
        if not name:
            raise ApiError(400, "VALIDATION_ERROR", "Project name is required.")
        data["name"] = name
    for key, value in data.items():
        setattr(program, key, value)
    await session.commit()
    await session.refresh(program)
    return DataResponse(data=_to_read(program))
