from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.permissions import permissions_for_role
from app.core.security import require_role
from app.db.models import AppRole, Notification, Organisation, User
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import MeRead, NotificationRead, NotificationUpdate, OrganisationSummary
from app.services.users import assert_can_view_user, create_user, deactivate_user, get_user_or_404, update_user
from app.schemas.domain import UserCreate, UserRead, UserUpdate

router = APIRouter(tags=["me"])


@router.get("/me", response_model=DataResponse[MeRead])
async def get_me(session: SessionDep, current_user: UserDep) -> DataResponse[MeRead]:
    user = (await session.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
    if user is None:
        raise ApiError(404, "NOT_FOUND", "User was not found.")

    org = (
        await session.execute(select(Organisation).where(Organisation.id == user.org_id))
    ).scalar_one_or_none()

    data = MeRead.model_validate(user)
    if org is not None:
        data.organisation = OrganisationSummary.model_validate(org)
    data.permissions = permissions_for_role(current_user.role)
    return DataResponse(data=data)


@router.get("/me/notifications", response_model=ListResponse[NotificationRead])
async def list_my_notifications(session: SessionDep, current_user: UserDep, limit: int = 50) -> ListResponse[NotificationRead]:
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return ListResponse(data=[NotificationRead.model_validate(row) for row in rows], pagination=Pagination(limit=limit))


@router.patch("/me/notifications/{notification_id}", response_model=DataResponse[NotificationRead])
async def update_my_notification(
    notification_id: UUID,
    payload: NotificationUpdate,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[NotificationRead]:
    notification = (
        await session.execute(
            select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if notification is None:
        raise ApiError(404, "NOT_FOUND", "Notification was not found.")
    notification.is_read = payload.is_read
    await session.commit()
    await session.refresh(notification)
    return DataResponse(data=NotificationRead.model_validate(notification))
