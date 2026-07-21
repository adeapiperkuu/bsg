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

    def _bearer_headers(self, access_token: str) -> dict[str, str]:
        return {"apikey": self._settings.supabase_anon_key, "Authorization": f"Bearer {access_token}"}

    async def get_user(self, access_token: str) -> dict[str, Any]:
        """GET /auth/v1/user -- includes a `factors` array (id/factor_type/status)
        for the current session's user, used to decide enroll vs. challenge."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self._base}/auth/v1/user",
                headers=self._bearer_headers(access_token),
            )
            if response.status_code >= 400:
                raise ApiError(401, "INVALID_TOKEN", "Unable to load the current user from Supabase Auth.")
            return response.json()

    async def enroll_totp_factor(self, access_token: str, *, friendly_name: str) -> dict[str, Any]:
        """POST /auth/v1/factors -- DEVELOPMENT_PLAN.md Workstream E.

        NOTE: this request/response shape is built from Supabase's documented
        enroll/challenge/verify flow (supabase.com/docs/guides/auth/auth-mfa/totp)
        and has not been verified against a live sandbox -- see the
        `mfa_required_roles` setting's docstring. Verify with one real account
        before relying on this.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/v1/factors",
                headers=self._bearer_headers(access_token),
                json={"factor_type": "totp", "friendly_name": friendly_name},
            )
            if response.status_code >= 400:
                detail = response.json() if response.content else {}
                message = detail.get("error_description") or detail.get("msg") or "Unable to enroll MFA factor."
                raise ApiError(400, "MFA_ENROLL_FAILED", message)
            return response.json()

    async def create_mfa_challenge(self, access_token: str, factor_id: str) -> dict[str, Any]:
        """POST /auth/v1/factors/{factor_id}/challenge"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/v1/factors/{factor_id}/challenge",
                headers=self._bearer_headers(access_token),
            )
            if response.status_code >= 400:
                detail = response.json() if response.content else {}
                message = detail.get("error_description") or detail.get("msg") or "Unable to create MFA challenge."
                raise ApiError(400, "MFA_CHALLENGE_FAILED", message)
            return response.json()

    async def verify_mfa_challenge(
        self, access_token: str, factor_id: str, *, challenge_id: str, code: str
    ) -> dict[str, Any]:
        """POST /auth/v1/factors/{factor_id}/verify -- on success returns a new
        session (access_token/refresh_token/user) at aal2, same shape as the
        password-grant /token response. Also activates the factor if this was
        its first successful verification (enrollment)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/v1/factors/{factor_id}/verify",
                headers=self._bearer_headers(access_token),
                json={"challenge_id": challenge_id, "code": code},
            )
            if response.status_code >= 400:
                detail = response.json() if response.content else {}
                message = detail.get("error_description") or detail.get("msg") or "Invalid or expired MFA code."
                raise ApiError(401, "MFA_VERIFY_FAILED", message)
            return response.json()

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
