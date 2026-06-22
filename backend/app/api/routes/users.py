from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.security import require_role
from app.db.models import AppRole, User
from app.schemas.common import ListResponse, Pagination
from app.schemas.domain import UserRead

router = APIRouter(tags=["users"])


@router.get("/users", response_model=ListResponse[UserRead])
async def list_users(
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[UserRead]:
    query = select(User).where(User.deleted_at.is_(None)).order_by(User.email)
    if current_user.role == AppRole.DELIVERY_MANAGER:
        query = query.where(User.org_id == current_user.org_id)
    rows = (await session.execute(query)).scalars()
    return ListResponse(data=[UserRead.model_validate(row) for row in rows], pagination=Pagination(limit=100))
