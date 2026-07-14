"""Pins the resolved F3 decision (DEVELOPMENT_PLAN.md Workstream D): drafting a
client communication is a delivery_manager/super_admin action performed
through their own request-scoped session, not a service_role-only path. See
the `client_communications` note in `docs/10. DB Schema.md` §7/§9 for the
full decision record.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import CurrentUser
from app.db.models import AppRole
from tests.conftest import client_a, delivery_manager, override_user, super_admin


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


async def _post_draft(api_client: AsyncClient) -> int:
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/communications/draft",
        json={"comm_type": "weekly_summary", "subject": "Weekly update"},
        headers={"Authorization": "Bearer test-token"},
    )
    return response.status_code


@pytest.mark.asyncio
async def test_delivery_manager_can_reach_draft_creation(api_client: AsyncClient, delivery_manager) -> None:
    """DM must pass the require_role gate -- with FakeSession the project lookup
    then 404s, but that's a downstream data error, not an RBAC rejection."""
    override_user(delivery_manager)
    assert await _post_draft(api_client) != 403


@pytest.mark.asyncio
async def test_super_admin_can_reach_draft_creation(api_client: AsyncClient, super_admin) -> None:
    override_user(super_admin)
    assert await _post_draft(api_client) != 403


@pytest.mark.asyncio
async def test_client_cannot_draft_communications(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/communications/draft",
        json={"comm_type": "weekly_summary", "subject": "Weekly update"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_bsg_leadership_cannot_draft_communications(api_client: AsyncClient, bsg_leadership) -> None:
    override_user(bsg_leadership)
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/communications/draft",
        json={"comm_type": "weekly_summary", "subject": "Weekly update"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
