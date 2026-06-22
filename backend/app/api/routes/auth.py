from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.config import Settings, get_settings
from app.core.cookies import REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, extract_access_token, get_optional_current_user
from app.db.models import User
from app.schemas.common import DataResponse
from app.schemas.domain import AuthSessionRead
from app.services.auth import SupabaseAuthService

router = APIRouter(tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/login", response_model=DataResponse[AuthSessionRead])
async def login(
    payload: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: Settings = Depends(get_settings),
) -> DataResponse[AuthSessionRead]:
    auth = SupabaseAuthService(settings)
    tokens = await auth.login(payload.email, payload.password)
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    user_id = UUID(str(tokens["user"]["id"]))

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.deleted_at is not None or not user.is_active:
        raise ApiError(403, "USER_INACTIVE", "This user account is not active.")

    set_auth_cookies(response, settings, access_token=access_token, refresh_token=refresh_token)
    return DataResponse(
        data=AuthSessionRead(id=user.id, email=user.email, role=user.role, full_name=user.full_name)
    )


@router.post("/auth/refresh", response_model=DataResponse[AuthSessionRead])
async def refresh_session(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: Settings = Depends(get_settings),
) -> DataResponse[AuthSessionRead]:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token is None:
        raise ApiError(401, "AUTH_REQUIRED", "Missing refresh token.")

    auth = SupabaseAuthService(settings)
    tokens = await auth.refresh(refresh_token)
    access_token = tokens["access_token"]
    new_refresh = tokens.get("refresh_token", refresh_token)
    user_id = UUID(str(tokens["user"]["id"]))

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.deleted_at is not None or not user.is_active:
        raise ApiError(403, "USER_INACTIVE", "This user account is not active.")

    set_auth_cookies(response, settings, access_token=access_token, refresh_token=new_refresh)
    return DataResponse(
        data=AuthSessionRead(id=user.id, email=user.email, role=user.role, full_name=user.full_name)
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: CurrentUser | None = Depends(get_optional_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    token = extract_access_token(request, credentials)
    if token is not None:
        try:
            await SupabaseAuthService(settings).logout(token)
        except ApiError:
            pass
    clear_auth_cookies(response, settings)
    _ = current_user
    return Response(status_code=204)
