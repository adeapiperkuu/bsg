from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ApiError


class SupabaseAuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.supabase_url.rstrip("/")

    async def login(self, email: str, password: str) -> dict[str, Any]:
        return await self._token_request(
            {"email": email, "password": password},
            apikey=self._settings.supabase_anon_key,
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token_request(
            {"refresh_token": refresh_token},
            apikey=self._settings.supabase_anon_key,
        )

    async def logout(self, access_token: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/v1/logout",
                headers={
                    "apikey": self._settings.supabase_anon_key,
                    "Authorization": f"Bearer {access_token}",
                },
            )
            if response.status_code >= 400:
                raise ApiError(400, "LOGOUT_FAILED", "Unable to revoke the current session.")

    async def create_auth_user(self, email: str, password: str, *, email_confirm: bool = True) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/v1/admin/users",
                headers={
                    "apikey": self._settings.supabase_service_role_key,
                    "Authorization": f"Bearer {self._settings.supabase_service_role_key}",
                },
                json={"email": email, "password": password, "email_confirm": email_confirm},
            )
            if response.status_code >= 400:
                detail = response.json() if response.content else {}
                message = detail.get("msg") or detail.get("message") or "Unable to create auth user."
                raise ApiError(400, "AUTH_USER_CREATE_FAILED", message)
            return response.json()

    async def delete_auth_user(self, user_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{self._base}/auth/v1/admin/users/{user_id}",
                headers={
                    "apikey": self._settings.supabase_service_role_key,
                    "Authorization": f"Bearer {self._settings.supabase_service_role_key}",
                },
            )
            if response.status_code >= 400:
                raise ApiError(400, "AUTH_USER_DELETE_FAILED", "Unable to delete auth user.")

    async def _token_request(self, payload: dict[str, str], *, apikey: str) -> dict[str, Any]:
        grant_type = payload.pop("grant_type", "password")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/v1/token?grant_type={grant_type}",
                headers={"apikey": apikey, "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code >= 400:
                detail = response.json() if response.content else {}
                message = detail.get("error_description") or detail.get("msg") or "Invalid email or password."
                raise ApiError(401, "INVALID_CREDENTIALS", message)
            return response.json()
