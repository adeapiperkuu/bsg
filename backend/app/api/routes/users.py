from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, User
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import UserCreate, UserRead, UserUpdate
from app.services.users import assert_can_view_user, create_user, deactivate_user, get_user_or_404, update_user

router = APIRouter(tags=["users"])


@router.get("/users", response_model=ListResponse[UserRead])
async def list_users(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[UserRead]:
    query = select(User).where(User.deleted_at.is_(None)).order_by(User.email)
    if current_user.role == AppRole.DELIVERY_MANAGER:
        query = query.where(User.org_id == current_user.org_id)
    rows = (await session.execute(query)).scalars()
    return ListResponse(data=[UserRead.model_validate(row) for row in rows], pagination=Pagination(limit=100))


@router.get("/users/{user_id}", response_model=DataResponse[UserRead])
async def get_user(user_id: UUID, session: SessionDep, current_user: UserDep) -> DataResponse[UserRead]:
    user = await get_user_or_404(session, user_id)
    assert_can_view_user(current_user, user)
    return DataResponse(data=UserRead.model_validate(user))


@router.post("/users", response_model=DataResponse[UserRead])
async def create_user_route(
    payload: UserCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[UserRead]:
    user = await create_user(session, current_user, payload)
    return DataResponse(data=UserRead.model_validate(user))


@router.patch("/users/{user_id}", response_model=DataResponse[UserRead])
async def update_user_route(
    user_id: UUID,
    payload: UserUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[UserRead]:
    user = await get_user_or_404(session, user_id)
    user = await update_user(session, current_user, user, payload)
    return DataResponse(data=UserRead.model_validate(user))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_route(
    user_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> Response:
    user = await get_user_or_404(session, user_id)
    await deactivate_user(session, current_user, user)
    return Response(status_code=204)
