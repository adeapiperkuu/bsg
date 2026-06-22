import json
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.cookies import ACCESS_COOKIE
from app.core.exceptions import ApiError
from app.core.jwt_utils import decode_access_token
from app.db.models import AppRole, User
from app.db.rls import set_rls_context
from app.db.session import get_db_session

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    org_id: UUID
    email: str
    role: AppRole
    is_active: bool
    access_token: str | None = None


def extract_access_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(ACCESS_COOKIE)


async def _load_user(session: AsyncSession, subject: UUID, access_token: str | None) -> CurrentUser:
    result = await session.execute(select(User).where(User.id == subject))
    user = result.scalar_one_or_none()
    if user is None or user.deleted_at is not None:
        raise ApiError(403, "USER_INACTIVE", "This user account is not active.")
    if not user.is_active:
        raise ApiError(403, "USER_INACTIVE", "This user account is not active.")
    if access_token:
        await set_rls_context(session, json.dumps({"sub": str(subject)}))
    return CurrentUser(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        access_token=access_token,
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentUser:
    token = extract_access_token(request, credentials)
    if token is None:
        raise ApiError(401, "AUTH_REQUIRED", "Missing bearer token.")

    settings = get_settings()
    try:
        payload = decode_access_token(token, settings)
        subject = UUID(str(payload["sub"]))
    except Exception as exc:
        raise ApiError(401, "INVALID_TOKEN", "Token cannot be verified.") from exc

    return await _load_user(session, subject, token)


async def get_optional_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentUser | None:
    token = extract_access_token(request, credentials)
    if token is None:
        return None
    settings = get_settings()
    try:
        payload = decode_access_token(token, settings)
        subject = UUID(str(payload["sub"]))
    except Exception:
        return None
    try:
        return await _load_user(session, subject, token)
    except ApiError:
        return None


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*allowed_roles: AppRole):
    async def dependency(current_user: CurrentUserDep) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
        return current_user

    return dependency


def can_read_all_orgs(role: AppRole) -> bool:
    return role in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
