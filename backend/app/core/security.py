from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.db.models import AppRole, User
from app.db.session import get_db_session

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    org_id: UUID
    email: str
    role: AppRole
    is_active: bool


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentUser:
    if credentials is None:
        raise ApiError(401, "AUTH_REQUIRED", "Missing bearer token.")

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": False},
        )
        subject = UUID(str(payload["sub"]))
    except Exception as exc:
        raise ApiError(401, "INVALID_TOKEN", "Token cannot be verified.") from exc

    result = await session.execute(select(User).where(User.id == subject, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "Token cannot be matched to an active user.")
    if not user.is_active:
        raise ApiError(403, "USER_INACTIVE", "This user account is not active.")

    return CurrentUser(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*allowed_roles: AppRole):
    async def dependency(current_user: CurrentUserDep) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
        return current_user

    return dependency


def can_read_all_orgs(role: AppRole) -> bool:
    return role in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
