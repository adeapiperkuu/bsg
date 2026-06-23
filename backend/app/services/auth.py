from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ApiError


class SupabaseAuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.supabase_url.rstrip("/")

    def _service_headers(self) -> dict[str, str]:
        key = self._settings.supabase_service_role_key
        return {"apikey": key, "Authorization": f"Bearer {key}"}

    async def find_auth_user_by_email(self, email: str) -> dict[str, Any] | None:
        email_lower = email.lower()
        page = 1
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                response = await client.get(
                    f"{self._base}/auth/v1/admin/users",
                    headers=self._service_headers(),
                    params={"page": page, "per_page": 200},
                )
                if response.status_code >= 400:
                    return None
                users = response.json().get("users", [])
                for user in users:
                    if str(user.get("email", "")).lower() == email_lower:
                        return user
                if not users or len(users) < 200:
                    return None
                page += 1

    async def update_auth_user(
        self,
        user_id: str,
        *,
        password: str | None = None,
        email_confirm: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"email_confirm": email_confirm}
        if password is not None:
            payload["password"] = password
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                f"{self._base}/auth/v1/admin/users/{user_id}",
                headers=self._service_headers(),
                json=payload,
            )
            if response.status_code >= 400:
                detail = response.json() if response.content else {}
                message = detail.get("msg") or detail.get("message") or "Unable to update auth user."
                raise ApiError(400, "AUTH_USER_UPDATE_FAILED", message)
            return response.json()

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
                error_code = detail.get("error_code", "")
                if error_code == "email_exists" or "already been registered" in message.lower():
                    raise ApiError(
                        409,
                        "AUTH_EMAIL_EXISTS",
                        "This email is already registered in Supabase Auth. "
                        "Use the admin console to link it to a platform profile, or remove it under "
                        "Authentication → Users in the Supabase dashboard.",
                    )
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
