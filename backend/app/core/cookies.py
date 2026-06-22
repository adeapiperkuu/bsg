import secrets
from datetime import timedelta

from fastapi import Response

from app.core.config import Settings

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"

ACCESS_MAX_AGE = int(timedelta(hours=1).total_seconds())
REFRESH_MAX_AGE = int(timedelta(days=60).total_seconds())
CSRF_MAX_AGE = REFRESH_MAX_AGE


def _cookie_kwargs(settings: Settings, *, max_age: int, path: str = "/") -> dict:
    return {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "max_age": max_age,
        "path": path,
    }


def set_auth_cookies(
    response: Response,
    settings: Settings,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str | None = None,
) -> str:
    token = csrf_token or secrets.token_urlsafe(32)
    response.set_cookie(ACCESS_COOKIE, access_token, **_cookie_kwargs(settings, max_age=ACCESS_MAX_AGE))
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        **_cookie_kwargs(settings, max_age=REFRESH_MAX_AGE, path="/api/v1/auth"),
    )
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=CSRF_MAX_AGE,
        path="/",
    )
    return token


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (ACCESS_COOKIE, "/"),
        (REFRESH_COOKIE, "/api/v1/auth"),
        (CSRF_COOKIE, "/"),
    ):
        response.delete_cookie(
            name,
            path=path,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
        )
