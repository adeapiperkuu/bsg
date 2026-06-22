from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, Organisation, User
from app.schemas.domain import UserCreate, UserUpdate
from app.services.auth import SupabaseAuthService


async def get_user_or_404(session: AsyncSession, user_id: UUID) -> User:
    user = (
        await session.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None:
        raise ApiError(404, "NOT_FOUND", "User was not found.")
    return user


def assert_can_view_user(actor: CurrentUser, user: User) -> None:
    if actor.role == AppRole.SUPER_ADMIN or actor.role == AppRole.BSG_LEADERSHIP:
        return
    if actor.role == AppRole.DELIVERY_MANAGER and user.org_id == actor.org_id:
        return
    if actor.id == user.id:
        return
    raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")


async def create_user(session: AsyncSession, actor: CurrentUser, payload: UserCreate) -> User:
    if actor.role != AppRole.SUPER_ADMIN:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    org = (
        await session.execute(
            select(Organisation).where(
                Organisation.id == payload.org_id,
                Organisation.deleted_at.is_(None),
                Organisation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise ApiError(404, "NOT_FOUND", "Organisation was not found.")

    settings = get_settings()
    auth = SupabaseAuthService(settings)
    auth_user = await auth.create_auth_user(payload.email, payload.password)
    user_id = UUID(str(auth_user["id"]))

    user = User(
        id=user_id,
        org_id=payload.org_id,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await auth.delete_auth_user(str(user_id))
        raise
    await session.refresh(user)
    return user


async def update_user(session: AsyncSession, actor: CurrentUser, user: User, payload: UserUpdate) -> User:
    if actor.role != AppRole.SUPER_ADMIN:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    data = payload.model_dump(exclude_unset=True)
    if "org_id" in data:
        org = (
            await session.execute(
                select(Organisation).where(
                    Organisation.id == data["org_id"],
                    Organisation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if org is None:
            raise ApiError(404, "NOT_FOUND", "Organisation was not found.")

    for key, value in data.items():
        setattr(user, key, value)
    await session.commit()
    await session.refresh(user)
    return user


async def deactivate_user(session: AsyncSession, actor: CurrentUser, user: User) -> User:
    if actor.role != AppRole.SUPER_ADMIN:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    user.is_active = False
    user.deleted_at = datetime.now(timezone.utc)
    await session.commit()

    settings: Settings = get_settings()
    auth = SupabaseAuthService(settings)
    try:
        await auth.delete_auth_user(str(user.id))
    except ApiError:
        pass

    await session.refresh(user)
    return user
