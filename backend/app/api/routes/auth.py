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
from app.schemas.domain import (
    AuthSessionRead,
    MfaChallengeRead,
    MfaChallengeRequest,
    MfaEnrollRead,
    MfaEnrollRequest,
    MfaRequiredRead,
    MfaVerifyRequest,
)
from app.services.auth import SupabaseAuthService

router = APIRouter(tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _has_verified_totp_factor(user_payload: dict) -> str | None:
    """Returns the factor id of the first verified TOTP factor, or None."""
    for factor in user_payload.get("factors") or []:
        if factor.get("factor_type") == "totp" and factor.get("status") == "verified":
            return str(factor.get("id"))
    return None


def _extract_pending_bearer(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    """MFA enroll/challenge/verify run against a pending, not-yet-cookied
    session -- callers must send it as `Authorization: Bearer <pending_token>`,
    never as a cookie (see MfaRequiredRead's docstring)."""
    token = extract_access_token(request, credentials)
    if token is None:
        raise ApiError(401, "AUTH_REQUIRED", "Missing pending MFA session token.")
    return token


@router.post("/auth/login", response_model=DataResponse[AuthSessionRead | MfaRequiredRead])
async def login(
    payload: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: Settings = Depends(get_settings),
) -> DataResponse[AuthSessionRead | MfaRequiredRead]:
    auth = SupabaseAuthService(settings)
    tokens = await auth.login(payload.email, payload.password)
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    user_id = UUID(str(tokens["user"]["id"]))

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.deleted_at is not None or not user.is_active:
        raise ApiError(403, "USER_INACTIVE", "This user account is not active.")

    if user.role.value in settings.mfa_required_role_values:
        factor_id = _has_verified_totp_factor(tokens.get("user") or {})
        return DataResponse(
            data=MfaRequiredRead(
                stage="challenge" if factor_id else "enroll",
                pending_token=access_token,
                factor_id=factor_id,
            )
        )

    set_auth_cookies(response, settings, access_token=access_token, refresh_token=refresh_token)
    return DataResponse(
        data=AuthSessionRead(id=user.id, email=user.email, role=user.role, full_name=user.full_name)
    )


@router.post("/auth/mfa/enroll", response_model=DataResponse[MfaEnrollRead])
async def mfa_enroll(
    payload: MfaEnrollRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> DataResponse[MfaEnrollRead]:
    """Step 1 of DEVELOPMENT_PLAN.md Workstream E's enrollment flow -- only
    reachable with the `pending_token` from a `stage: "enroll"` login response."""
    pending_token = _extract_pending_bearer(request, credentials)
    auth = SupabaseAuthService(settings)
    factor = await auth.enroll_totp_factor(pending_token, friendly_name=payload.friendly_name)
    totp = factor.get("totp") or {}
    return DataResponse(
        data=MfaEnrollRead(factor_id=str(factor["id"]), qr_code=totp.get("qr_code", ""), secret=totp.get("secret", ""))
    )


@router.post("/auth/mfa/challenge", response_model=DataResponse[MfaChallengeRead])
async def mfa_challenge(
    payload: MfaChallengeRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> DataResponse[MfaChallengeRead]:
    """Step 2: request a challenge for a factor -- called for both a
    freshly-enrolled factor (to activate it) and a returning, already-verified
    factor (to complete a normal login)."""
    pending_token = _extract_pending_bearer(request, credentials)
    auth = SupabaseAuthService(settings)
    challenge = await auth.create_mfa_challenge(pending_token, payload.factor_id)
    return DataResponse(data=MfaChallengeRead(factor_id=payload.factor_id, challenge_id=str(challenge["id"])))


@router.post("/auth/mfa/verify", response_model=DataResponse[AuthSessionRead])
async def mfa_verify(
    payload: MfaVerifyRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> DataResponse[AuthSessionRead]:
    """Step 3: verify the code. On success this both activates the factor (if
    it was newly enrolled) and elevates the session to aal2 -- only now do we
    set the real auth cookies and consider login complete."""
    pending_token = _extract_pending_bearer(request, credentials)
    auth = SupabaseAuthService(settings)
    new_session = await auth.verify_mfa_challenge(
        pending_token, payload.factor_id, challenge_id=payload.challenge_id, code=payload.code
    )
    access_token = new_session["access_token"]
    refresh_token = new_session["refresh_token"]
    user_id = UUID(str(new_session["user"]["id"]))

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
    _ = current_user
    response = Response(status_code=204)
    clear_auth_cookies(response, settings)
    return response
