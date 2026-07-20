"""Tests for client sent-only communications archive."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, CommunicationStatus, CommunicationType
from app.schemas.domain import CommunicationListItem, CommunicationRead
from app.services.communications import (
    list_client_sent_communications,
    sanitize_communication_read_for_client,
)
from tests.conftest import FakeSession, override_user


def _client() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="client@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )


def _dm() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def test_sanitize_strips_internal_client_fields() -> None:
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    data = CommunicationRead(
        id=uuid4(),
        project_id=uuid4(),
        comm_type=CommunicationType.WEEKLY_SUMMARY,
        subject="Weekly",
        body_draft="Draft secret",
        body_approved="Approved public body",
        status=CommunicationStatus.SENT,
        drafted_by_agent="client_interaction_agent",
        reviewed_by=None,
        reviewed_at=None,
        approved_by=None,
        approved_at=None,
        sent_at=now,
        created_at=now,
        updated_at=now,
        evidence_links=[],
        generation_mode="fallback",
        generation_warning="AI unavailable",
    )
    sanitized = sanitize_communication_read_for_client(data)
    assert sanitized.generation_mode is None
    assert sanitized.generation_warning is None
    assert sanitized.evidence_links == []
    assert sanitized.body_draft == "Approved public body"
    assert sanitized.body_approved == "Approved public body"


@pytest.mark.asyncio
async def test_list_client_sent_rejects_non_client() -> None:
    with pytest.raises(ApiError) as exc:
        await list_client_sent_communications(FakeSession(), _dm())  # type: ignore[arg-type]
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_list_client_sent_query_forces_sent_status() -> None:
    import inspect

    from app.services import communications as svc

    source = inspect.getsource(svc.list_client_sent_communications)
    assert "CommunicationStatus.SENT" in source
    assert "ProjectAssignment" in source
    assert "DRAFT" not in source
    assert "body_draft" not in source
    assert "body_approved" not in source


@pytest.mark.asyncio
async def test_client_archive_route_returns_list(api_client, client_a) -> None:
    override_user(client_a)
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    item = CommunicationListItem(
        id=uuid4(),
        project_id=uuid4(),
        project_name="Helios",
        org_id=uuid4(),
        org_name="Helios Org",
        comm_type=CommunicationType.WEEKLY_SUMMARY,
        subject="Weekly Delivery Summary — Helios",
        status=CommunicationStatus.SENT,
        created_at=now,
        updated_at=now,
        sent_at=now,
        evidence_link_count=0,
    )
    with patch(
        "app.api.routes.communications.list_client_sent_communications",
        AsyncMock(
            return_value=SimpleNamespace(
                items=[item],
                total=1,
                limit=30,
                offset=0,
                db_ms=12.0,
            )
        ),
    ):
        response = await api_client.get(
            "/api/v1/client/communications",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["data"]) == 1
    assert payload["data"][0]["status"] == "sent"
    assert "body_draft" not in payload["data"][0]
    assert "body_approved" not in payload["data"][0]


@pytest.mark.asyncio
async def test_client_archive_forbidden_for_dm(api_client, delivery_manager) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/client/communications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_project_list_rejects_client_status_param(api_client, client_a) -> None:
    override_user(client_a)
    project_id = uuid4()
    with patch(
        "app.api.routes.communications.get_visible_project",
        AsyncMock(return_value=SimpleNamespace(id=project_id, org_id=client_a.org_id)),
    ):
        response = await api_client.get(
            f"/api/v1/projects/{project_id}/communications",
            params={"status": "draft"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_client_cannot_approve(api_client, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/communications/{uuid4()}/approve",
        json={},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
