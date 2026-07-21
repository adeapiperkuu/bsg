"""DEVELOPMENT_PLAN.md Workstream E: MFA-gated login.

Mocks every Supabase Auth HTTP call (SupabaseAuthService methods) -- these
tests validate this app's control flow, not Supabase's actual MFA REST API
shape, which hasn't been verified against a live sandbox (see
`mfa_required_roles`'s docstring in app/core/config.py). Enforcement is off
by default (`mfa_required_roles=""`); these tests explicitly opt in per-test
via a `get_settings` dependency override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.db.models import AppRole, User
from app.db.session import get_db_session
from app.main import app
from app.services.auth import SupabaseAuthService


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql://postgres:pass@localhost:5432/postgres",
        "supabase_url": "https://example.supabase.co",
        "supabase_anon_key": "anon-key",
        "supabase_service_role_key": "service-key",
        "secret_key": "test-secret-key",
        "environment": "dev",
        "allowed_origins": "http://localhost:5173",
        "supabase_jwt_secret": None,
        "auth_cookie_secure": False,
        "mfa_required_roles": "",
    }
    values.update(overrides)
    return Settings(**values)


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _UserLookupSession:
    """Returns `user` for any `select(User)...` query -- enough for the
    login/mfa routes' `select(User).where(User.id == user_id)` lookup."""

    def __init__(self, user: User) -> None:
        self._user = user

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        return _FakeResult(self._user)

    async def commit(self) -> None:
        return None


def _user(role: AppRole) -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        full_name="Test User",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


class _SessionSlot:
    """Mutable holder so the FastAPI dependency override can be configured
    per-test (set_user) after the app-level override is already installed."""

    session: _UserLookupSession | None = None


@pytest.fixture
async def mfa_client(monkeypatch: pytest.MonkeyPatch):
    slot = _SessionSlot()

    async def _override_session():
        yield slot.session

    app.dependency_overrides[get_db_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, slot
    app.dependency_overrides.clear()


def _set_user(slot: _SessionSlot, user: User) -> None:
    slot.session = _UserLookupSession(user)


@pytest.mark.asyncio
async def test_login_unaffected_when_mfa_not_required(mfa_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, override_session = mfa_client
    user = _user(AppRole.DELIVERY_MANAGER)
    _set_user(override_session, user)
    app.dependency_overrides[get_settings] = lambda: _settings(mfa_required_roles="")

    async def _login(self, email, password):
        return {"access_token": "tok", "refresh_token": "ref", "user": {"id": str(user.id), "factors": []}}

    monkeypatch.setattr(SupabaseAuthService, "login", _login)

    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "x"})
    assert response.status_code == 200
    body = response.json()["data"]
    assert "mfa_required" not in body
    assert body["id"] == str(user.id)
    assert "access_token" in response.cookies


@pytest.mark.asyncio
async def test_login_requires_enrollment_when_no_verified_factor(mfa_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, override_session = mfa_client
    user = _user(AppRole.DELIVERY_MANAGER)
    _set_user(override_session, user)
    app.dependency_overrides[get_settings] = lambda: _settings(
        mfa_required_roles="delivery_manager,bsg_leadership,super_admin"
    )

    async def _login(self, email, password):
        return {"access_token": "pending-tok", "refresh_token": "ref", "user": {"id": str(user.id), "factors": []}}

    monkeypatch.setattr(SupabaseAuthService, "login", _login)

    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "x"})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["mfa_required"] is True
    assert body["stage"] == "enroll"
    assert body["pending_token"] == "pending-tok"
    assert body["factor_id"] is None
    assert "access_token" not in response.cookies


@pytest.mark.asyncio
async def test_login_requires_challenge_when_factor_already_verified(
    mfa_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, override_session = mfa_client
    user = _user(AppRole.SUPER_ADMIN)
    _set_user(override_session, user)
    app.dependency_overrides[get_settings] = lambda: _settings(mfa_required_roles="super_admin")

    async def _login(self, email, password):
        return {
            "access_token": "pending-tok",
            "refresh_token": "ref",
            "user": {
                "id": str(user.id),
                "factors": [{"id": "factor-1", "factor_type": "totp", "status": "verified"}],
            },
        }

    monkeypatch.setattr(SupabaseAuthService, "login", _login)

    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "x"})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["mfa_required"] is True
    assert body["stage"] == "challenge"
    assert body["factor_id"] == "factor-1"
    assert "access_token" not in response.cookies


@pytest.mark.asyncio
async def test_client_role_never_gated_even_if_misconfigured(mfa_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defense-in-depth: `client` should never appear in mfa_required_roles by
    the plan's own scope, but confirm a role simply not present in the set is
    unaffected even with other roles configured."""
    client_, override_session = mfa_client
    user = _user(AppRole.CLIENT)
    _set_user(override_session, user)
    app.dependency_overrides[get_settings] = lambda: _settings(
        mfa_required_roles="delivery_manager,bsg_leadership,super_admin"
    )

    async def _login(self, email, password):
        return {"access_token": "tok", "refresh_token": "ref", "user": {"id": str(user.id), "factors": []}}

    monkeypatch.setattr(SupabaseAuthService, "login", _login)

    response = await client_.post("/api/v1/auth/login", json={"email": user.email, "password": "x"})
    assert response.status_code == 200
    assert "mfa_required" not in response.json()["data"]
    assert "access_token" in response.cookies


@pytest.mark.asyncio
async def test_full_enroll_challenge_verify_flow_completes_login(
    mfa_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, override_session = mfa_client
    user = _user(AppRole.DELIVERY_MANAGER)
    _set_user(override_session, user)
    app.dependency_overrides[get_settings] = lambda: _settings(mfa_required_roles="delivery_manager")

    async def _login(self, email, password):
        return {"access_token": "pending-tok", "refresh_token": "ref", "user": {"id": str(user.id), "factors": []}}

    async def _enroll(self, access_token, *, friendly_name):
        assert access_token == "pending-tok"
        return {"id": "factor-1", "totp": {"qr_code": "<svg>...</svg>", "secret": "BASE32SECRET"}}

    async def _challenge(self, access_token, factor_id):
        assert access_token == "pending-tok"
        assert factor_id == "factor-1"
        return {"id": "challenge-1"}

    async def _verify(self, access_token, factor_id, *, challenge_id, code):
        assert access_token == "pending-tok"
        assert factor_id == "factor-1"
        assert challenge_id == "challenge-1"
        assert code == "123456"
        return {"access_token": "real-tok", "refresh_token": "real-ref", "user": {"id": str(user.id)}}

    monkeypatch.setattr(SupabaseAuthService, "login", _login)
    monkeypatch.setattr(SupabaseAuthService, "enroll_totp_factor", _enroll)
    monkeypatch.setattr(SupabaseAuthService, "create_mfa_challenge", _challenge)
    monkeypatch.setattr(SupabaseAuthService, "verify_mfa_challenge", _verify)

    login_response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "x"})
    pending_token = login_response.json()["data"]["pending_token"]
    assert login_response.json()["data"]["stage"] == "enroll"

    headers = {"Authorization": f"Bearer {pending_token}"}
    enroll_response = await client.post("/api/v1/auth/mfa/enroll", json={}, headers=headers)
    assert enroll_response.status_code == 200
    factor_id = enroll_response.json()["data"]["factor_id"]
    assert factor_id == "factor-1"
    assert enroll_response.json()["data"]["secret"] == "BASE32SECRET"

    challenge_response = await client.post(
        "/api/v1/auth/mfa/challenge", json={"factor_id": factor_id}, headers=headers
    )
    assert challenge_response.status_code == 200
    challenge_id = challenge_response.json()["data"]["challenge_id"]
    assert challenge_id == "challenge-1"

    verify_response = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"factor_id": factor_id, "challenge_id": challenge_id, "code": "123456"},
        headers=headers,
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["data"]["id"] == str(user.id)
    assert "access_token" in verify_response.cookies


@pytest.mark.asyncio
async def test_mfa_endpoints_require_pending_bearer_token(mfa_client) -> None:
    client, _ = mfa_client
    response = await client.post("/api/v1/auth/mfa/enroll", json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
