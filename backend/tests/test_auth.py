import pytest
from httpx import AsyncClient

from app.core.permissions import permissions_for_role
from app.db.models import AppRole
from app.schemas.domain import MePermissions


def test_permissions_for_super_admin() -> None:
    perms = permissions_for_role(AppRole.SUPER_ADMIN)
    assert perms.can_manage_users is True
    assert perms.can_manage_organisations is True
    assert perms.can_manage_metric_configurations is True


def test_permissions_for_client() -> None:
    perms = permissions_for_role(AppRole.CLIENT)
    assert perms == MePermissions()


def test_permissions_for_delivery_manager() -> None:
    perms = permissions_for_role(AppRole.DELIVERY_MANAGER)
    assert perms.can_manage_projects is True
    assert perms.can_approve_communications is True
    assert perms.can_manage_users is False


@pytest.mark.asyncio
async def test_health_unauthenticated(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_me_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_csrf_blocks_cookie_mutation_without_token(api_client: AsyncClient) -> None:
    api_client.cookies.set("access_token", "fake")
    response = await api_client.post("/api/v1/users", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"
