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


def _auth_email_taken(exc: ApiError) -> bool:
    return exc.code in {"AUTH_EMAIL_EXISTS", "AUTH_USER_CREATE_FAILED"} and (
        exc.code == "AUTH_EMAIL_EXISTS"
        or "already been registered" in exc.message.lower()
        or "email_exists" in exc.message.lower()
    )


async def _ensure_auth_user(auth: SupabaseAuthService, email: str, password: str) -> UUID:
    try:
        auth_user = await auth.create_auth_user(email, password)
        return UUID(str(auth_user["id"]))
    except ApiError as exc:
        if not _auth_email_taken(exc):
            raise
        existing = await auth.find_auth_user_by_email(email)
        if existing is None:
            raise ApiError(
                409,
                "AUTH_EMAIL_EXISTS",
                "This email is already registered in Supabase Auth but could not be located for linking.",
            ) from exc
        await auth.update_auth_user(str(existing["id"]), password=password)
        return UUID(str(existing["id"]))


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

    existing_active = (
        await session.execute(
            select(User).where(User.email == payload.email, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        raise ApiError(
            409,
            "EMAIL_ALREADY_EXISTS",
            "A platform user with this email already exists. Check the Users list in the admin console.",
        )

    settings = get_settings()
    auth = SupabaseAuthService(settings)
    user_id = await _ensure_auth_user(auth, payload.email, payload.password)

    stale_profile = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if stale_profile is not None:
        await session.delete(stale_profile)
        await session.flush()

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
        if stale_profile is None:
            await auth.delete_auth_user(str(user_id))
        raise
    await session.refresh(user)
    return user


async def update_user(session: AsyncSession, actor: CurrentUser, user: User, payload: UserUpdate) -> User:
    if actor.role != AppRole.SUPER_ADMIN:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
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

    if password:
        settings = get_settings()
        auth = SupabaseAuthService(settings)
        await auth.update_auth_user(str(user.id), password=password)

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
