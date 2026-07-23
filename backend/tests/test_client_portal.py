from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.main import app
from app.schemas.client_portal import ClientChangeRequestRead
from tests.conftest import override_user

PROJECT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def test_openapi_registers_client_portal_routes() -> None:
    schema = app.openapi()
    assert f"/api/v1/client/projects/{{project_id}}/dashboard" in schema["paths"]
    assert f"/api/v1/client/projects/{{project_id}}/change-requests" in schema["paths"]
    assert f"/api/v1/client/reports/{{communication_id}}/download/{{format}}" in schema["paths"]


@pytest.mark.asyncio
async def test_client_can_submit_change_request(
    api_client: AsyncClient,
    client_a: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)

    async def _create(*_args, **_kwargs) -> ClientChangeRequestRead:
        return ClientChangeRequestRead(
            id=uuid4(),
            project_id=PROJECT_ID,
            title="Add regional approval",
            description="Add a regional approval step before release.",
            business_justification="Required for local compliance.",
            priority="high",
            status="submitted",
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(
        "app.api.routes.client_portal.create_client_change_request",
        _create,
    )
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/client/projects/{PROJECT_ID}/change-requests",
        json={
            "title": "Add regional approval",
            "description": "Add a regional approval step before release.",
            "business_justification": "Required for local compliance.",
            "priority": "high",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["status"] == "submitted"


@pytest.mark.asyncio
async def test_internal_user_cannot_submit_client_change_request(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
) -> None:
    assert delivery_manager.role == AppRole.DELIVERY_MANAGER
    override_user(delivery_manager)
    response = await api_client.post(
        f"/api/v1/client/projects/{PROJECT_ID}/change-requests",
        json={
            "title": "Add regional approval",
            "description": "Add a regional approval step before release.",
            "priority": "medium",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_csv_download_is_a_real_attachment(
    api_client: AsyncClient,
    client_a: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    communication_id = uuid4()
    now = datetime(2026, 7, 23, tzinfo=UTC)

    async def _get_report(*_args, **_kwargs):
        return SimpleNamespace(
            id=communication_id,
            subject="Weekly Delivery Update",
            comm_type=SimpleNamespace(value="weekly_summary"),
            body_approved="Milestone A completed.",
            body_draft="Draft content",
            sent_at=now,
            updated_at=now,
        )

    monkeypatch.setattr("app.api.routes.client_portal._get_sent_report", _get_report)
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/client/reports/{communication_id}/download/csv"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].endswith(
        'filename="Weekly-Delivery-Update.csv"'
    )
    assert "Milestone A completed." in response.text
