"""DEVELOPMENT_PLAN.md Workstream F (closes F6): only delivery_manager and
super_admin may reach the audit-export endpoints -- client and bsg_leadership
must not, per 13. Security & Compliance.md §11.4's access list.
"""

import pytest
from httpx import AsyncClient

from app.core.security import CurrentUser
from app.db.models import AppRole
from tests.conftest import client_a, delivery_manager, override_user, super_admin

ENDPOINTS = ("/api/v1/admin/audit/agent-queries", "/api/v1/admin/audit/communications")


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    from uuid import uuid4

    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.asyncio
async def test_delivery_manager_can_reach_audit_export(api_client: AsyncClient, delivery_manager, path: str) -> None:
    """DM must pass the require_role gate -- with FakeSession the count query
    then 500s (no scalar_one() on the shared fake result), but that's a
    downstream data-layer limitation of the test double, not an RBAC rejection."""
    override_user(delivery_manager)
    response = await api_client.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code != 403


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.asyncio
async def test_super_admin_can_reach_audit_export(api_client: AsyncClient, super_admin, path: str) -> None:
    override_user(super_admin)
    response = await api_client.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code != 403


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.asyncio
async def test_client_cannot_reach_audit_export(api_client: AsyncClient, client_a, path: str) -> None:
    override_user(client_a)
    response = await api_client.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.asyncio
async def test_bsg_leadership_cannot_reach_audit_export(
    api_client: AsyncClient, bsg_leadership: CurrentUser, path: str
) -> None:
    override_user(bsg_leadership)
    response = await api_client.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
