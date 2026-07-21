"""Phase 5: communication lifecycle transitions (edit / review / approve / reject / send).

Post-merge these assert the governed lifecycle semantics:
draft -> in_review -> approved -> sent, with reject only from in_review.
Detailed audit/fingerprint coverage lives in test_communication_lifecycle.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, CommunicationStatus, CommunicationType
from app.schemas.domain import CommunicationApprove, CommunicationReject, CommunicationReview
from app.services.communications import (
    ERROR_INVALID_TRANSITION,
    approve,
    move_to_review,
    reject,
    send,
    update_communication_content,
)
from tests.conftest import FakeSession, override_user


class _Session(FakeSession):
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self, *_args: object, **_kwargs: object) -> None:
        return None


def _user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _comm(**overrides: object) -> SimpleNamespace:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid4(),
        "project_id": uuid4(),
        "org_id": uuid4(),
        "comm_type": CommunicationType.WEEKLY_SUMMARY,
        "subject": "Weekly Delivery Summary — Helios",
        "body_draft": "Draft body",
        "body_approved": None,
        "status": CommunicationStatus.DRAFT,
        "drafted_by_agent": "client_interaction_agent",
        "reviewed_by": None,
        "reviewed_at": None,
        "approved_by": None,
        "approved_at": None,
        "sent_at": None,
        "rejection_reason": None,
        "rejected_by": None,
        "rejected_at": None,
        "evidence_source_fingerprint": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_edit_allowed_for_draft_updates_body_draft() -> None:
    session = _Session()
    communication = _comm(status=CommunicationStatus.DRAFT, body_draft="Old")
    updated = await update_communication_content(
        session,  # type: ignore[arg-type]
        communication,  # type: ignore[arg-type]
        subject="New subject",
        body="Edited draft",
    )
    assert updated.subject == "New subject"
    assert updated.body_draft == "Edited draft"
    assert updated.status == CommunicationStatus.DRAFT


@pytest.mark.asyncio
async def test_edit_allowed_for_in_review_updates_body_approved() -> None:
    session = _Session()
    communication = _comm(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
    )
    updated = await update_communication_content(
        session,  # type: ignore[arg-type]
        communication,  # type: ignore[arg-type]
        subject=None,
        body="Revised for review",
    )
    assert updated.body_approved == "Revised for review"
    assert updated.status == CommunicationStatus.IN_REVIEW


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CommunicationStatus.APPROVED,
        CommunicationStatus.SENT,
        CommunicationStatus.REJECTED,
    ],
)
async def test_edit_denied_for_terminal_statuses(status: CommunicationStatus) -> None:
    with pytest.raises(ApiError) as exc:
        await update_communication_content(
            _Session(),  # type: ignore[arg-type]
            _comm(status=status),  # type: ignore[arg-type]
            subject=None,
            body="Nope",
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "INVALID_COMMUNICATION_TRANSITION"


@pytest.mark.asyncio
async def test_approve_only_from_in_review() -> None:
    user = _user()
    communication = _comm(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        reviewed_by=uuid4(),
        reviewed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    result = await approve(
        _Session(),  # type: ignore[arg-type]
        communication,  # type: ignore[arg-type]
        CommunicationApprove(body_approved=None),
        user,
    )
    assert result.status == CommunicationStatus.APPROVED
    assert result.body_approved == "Reviewed body"
    assert result.approved_by == user.id
    assert result.sent_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CommunicationStatus.DRAFT,
        CommunicationStatus.APPROVED,
        CommunicationStatus.SENT,
        CommunicationStatus.REJECTED,
    ],
)
async def test_approve_denied_from_invalid_status(status: CommunicationStatus) -> None:
    with pytest.raises(ApiError) as exc:
        await approve(
            _Session(),  # type: ignore[arg-type]
            _comm(status=status, body_approved="x"),  # type: ignore[arg-type]
            CommunicationApprove(),
            _user(),
        )
    assert exc.value.status_code == 409
    assert exc.value.code == ERROR_INVALID_TRANSITION


@pytest.mark.asyncio
async def test_reject_permitted_only_from_in_review() -> None:
    payload = CommunicationReject(rejection_reason="Needs clearer milestones.")
    result = await reject(
        _Session(),  # type: ignore[arg-type]
        _comm(status=CommunicationStatus.IN_REVIEW, body_approved="Reviewed"),  # type: ignore[arg-type]
        payload,
        _user(),
    )
    assert result.status == CommunicationStatus.REJECTED
    assert result.rejection_reason == "Needs clearer milestones."

    for status in (
        CommunicationStatus.DRAFT,
        CommunicationStatus.APPROVED,
        CommunicationStatus.SENT,
        CommunicationStatus.REJECTED,
    ):
        with pytest.raises(ApiError) as exc:
            await reject(
                _Session(),  # type: ignore[arg-type]
                _comm(status=status),  # type: ignore[arg-type]
                payload,
                _user(),
            )
        assert exc.value.code == ERROR_INVALID_TRANSITION


@pytest.mark.asyncio
async def test_send_only_from_approved() -> None:
    approved = _comm(
        status=CommunicationStatus.APPROVED,
        body_approved="Ready",
        approved_by=uuid4(),
        approved_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    result = await send(_Session(), approved, _user())  # type: ignore[arg-type]
    assert result.status == CommunicationStatus.SENT
    assert result.sent_at is not None


@pytest.mark.asyncio
async def test_send_draft_rejected() -> None:
    with pytest.raises(ApiError) as exc:
        await send(_Session(), _comm(status=CommunicationStatus.DRAFT), _user())  # type: ignore[arg-type]
    assert exc.value.status_code == 409
    assert exc.value.code == ERROR_INVALID_TRANSITION


@pytest.mark.asyncio
async def test_duplicate_send_is_idempotent() -> None:
    sent_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    communication = _comm(
        status=CommunicationStatus.SENT,
        body_approved="Published",
        approved_by=uuid4(),
        sent_at=sent_at,
    )
    result = await send(_Session(), communication, _user())  # type: ignore[arg-type]
    assert result.status == CommunicationStatus.SENT
    assert result.sent_at == sent_at


@pytest.mark.asyncio
async def test_send_rejected_report_denied() -> None:
    with pytest.raises(ApiError) as exc:
        await send(_Session(), _comm(status=CommunicationStatus.REJECTED), _user())  # type: ignore[arg-type]
    assert exc.value.code == ERROR_INVALID_TRANSITION


@pytest.mark.asyncio
async def test_review_submits_to_in_review() -> None:
    user = _user()
    communication = _comm(status=CommunicationStatus.DRAFT)
    result = await move_to_review(
        _Session(),  # type: ignore[arg-type]
        communication,  # type: ignore[arg-type]
        CommunicationReview(body_approved="Ready for review"),
        user,
    )
    assert result.status == CommunicationStatus.IN_REVIEW
    assert result.body_approved == "Ready for review"
    assert result.reviewed_by == user.id


@pytest.mark.asyncio
async def test_review_denied_for_approved() -> None:
    with pytest.raises(ApiError) as exc:
        await move_to_review(
            _Session(),  # type: ignore[arg-type]
            _comm(status=CommunicationStatus.APPROVED, body_approved="x"),  # type: ignore[arg-type]
            CommunicationReview(body_approved="x"),
            _user(),
        )
    assert exc.value.code == ERROR_INVALID_TRANSITION


@pytest.mark.asyncio
async def test_client_list_route_filters_to_sent_only(api_client, client_a) -> None:
    """Clients must only see sent communications on project-scoped list."""
    override_user(client_a)
    project_id = uuid4()

    with patch(
        "app.api.routes.communications.get_visible_project",
        AsyncMock(return_value=SimpleNamespace(id=project_id, org_id=client_a.org_id)),
    ):
        response = await api_client.get(
            f"/api/v1/projects/{project_id}/communications",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_cross_org_mutation_denied_via_visibility(api_client, delivery_manager) -> None:
    override_user(delivery_manager)
    with patch(
        "app.api.routes.communications.get_visible_communication",
        AsyncMock(side_effect=ApiError(404, "NOT_FOUND", "Communication was not found.")),
    ):
        response = await api_client.post(
            f"/api/v1/communications/{uuid4()}/approve",
            json={"body_approved": "x"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 404


def test_list_communications_source_enforces_sent_for_clients() -> None:
    import inspect

    from app.api.routes import communications as routes

    source = inspect.getsource(routes.list_communications)
    assert "CommunicationStatus.SENT" in source
    assert "AppRole.CLIENT" in source
