from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.security import CurrentUser, require_role
from app.db.models import Annotator, AppRole, Team
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import AnnotatorCreate, AnnotatorRead, AnnotatorUpdate, TeamCreate, TeamRead, TeamUpdate
from app.services.scoping import get_visible_project
from app.services.workforce import (
    create_annotator,
    create_team,
    get_annotator_or_404,
    get_team_or_404,
    soft_delete_annotator,
    soft_delete_team,
    update_annotator,
    update_team,
)

router = APIRouter(tags=["workforce"])


@router.get("/projects/{project_id}/teams", response_model=ListResponse[TeamRead])
async def list_teams(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    limit: LimitQuery = 100,
) -> ListResponse[TeamRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(Team)
            .where(Team.project_id == project.id, Team.deleted_at.is_(None))
            .order_by(Team.name)
            .limit(limit)
        )
    ).scalars()
    return ListResponse(
        data=[TeamRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/projects/{project_id}/teams", response_model=DataResponse[TeamRead])
async def create_team_route(
    project_id: UUID,
    payload: TeamCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TeamRead]:
    project = await get_visible_project(session, project_id, current_user)
    team = await create_team(session, project, payload)
    await session.commit()
    await session.refresh(team)
    return DataResponse(data=TeamRead.model_validate(team))


@router.patch("/teams/{team_id}", response_model=DataResponse[TeamRead])
async def update_team_route(
    team_id: UUID,
    payload: TeamUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TeamRead]:
    team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
    team = await update_team(session, team, payload)
    await session.commit()
    await session.refresh(team)
    return DataResponse(data=TeamRead.model_validate(team))


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team_route(
    team_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
    await soft_delete_team(session, team)
    await session.commit()
    return Response(status_code=204)


@router.get("/teams/{team_id}/annotators", response_model=ListResponse[AnnotatorRead])
async def list_annotators(
    team_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[AnnotatorRead]:
    team = await get_team_or_404(session, team_id, current_user)
    rows = (
        await session.execute(
            select(Annotator)
            .where(Annotator.team_id == team.id, Annotator.deleted_at.is_(None))
            .order_by(Annotator.full_name)
            .limit(limit)
        )
    ).scalars()
    return ListResponse(
        data=[AnnotatorRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/teams/{team_id}/annotators", response_model=DataResponse[AnnotatorRead])
async def create_annotator_route(
    team_id: UUID,
    payload: AnnotatorCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[AnnotatorRead]:
    team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
    annotator = await create_annotator(session, team, payload)
    await session.commit()
    await session.refresh(annotator)
    return DataResponse(data=AnnotatorRead.model_validate(annotator))


@router.patch("/annotators/{annotator_id}", response_model=DataResponse[AnnotatorRead])
async def update_annotator_route(
    annotator_id: UUID,
    payload: AnnotatorUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[AnnotatorRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    annotator = await update_annotator(session, annotator, payload, current_user=current_user)
    await session.commit()
    await session.refresh(annotator)
    return DataResponse(data=AnnotatorRead.model_validate(annotator))


@router.delete("/annotators/{annotator_id}", status_code=204)
async def delete_annotator_route(
    annotator_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    await soft_delete_annotator(session, annotator)
    await session.commit()
    return Response(status_code=204)
