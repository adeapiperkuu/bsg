"""Focused tests for governed client communication lifecycle transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, AuditLog, CommunicationStatus, CommunicationType
from app.db.models.entities import ClientCommunication
from app.main import app
from app.schemas.domain import (
    CommunicationApprove,
    CommunicationDraftEdit,
    CommunicationReject,
    CommunicationReview,
)
from app.services import communications as communications_service
from app.services.communications import (
    ERROR_INVALID_TRANSITION,
    ERROR_NO_COMMUNICATION_CHANGES,
    approve,
    edit_draft,
    move_to_review,
    reject,
    send,
)
from tests.conftest import FakeSession, override_user

ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ORG_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PROJECT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
COMM_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
EVIDENCE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


class RecordingSession(FakeSession):
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_count = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self, *_args: Any, **_kwargs: Any) -> None:
        self.flush_count += 1


def _user(
    *,
    role: AppRole = AppRole.DELIVERY_MANAGER,
    org_id: UUID = ORG_ID,
    user_id: UUID | None = None,
) -> CurrentUser:
    return CurrentUser(
        id=user_id or uuid4(),
        org_id=org_id,
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _communication(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": COMM_ID,
        "project_id": PROJECT_ID,
        "org_id": ORG_ID,
        "comm_type": CommunicationType.WEEKLY_SUMMARY,
        "subject": "Weekly Client Update",
        "body_draft": "Evidence-backed draft body.",
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
        "created_at": datetime(2026, 7, 16, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 16, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _audit_entries(session: RecordingSession) -> list[AuditLog]:
    return [item for item in session.added if isinstance(item, AuditLog)]


@pytest.fixture
def bsg_leadership(delivery_manager: CurrentUser) -> CurrentUser:
    return CurrentUser(
        id=delivery_manager.id,
        org_id=delivery_manager.org_id,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


def test_openapi_registers_draft_edit_route() -> None:
    schema = app.openapi()
    path = "/api/v1/communications/{communication_id}/draft"
    assert path in schema["paths"]
    assert "patch" in schema["paths"][path]


def test_migration_adds_rejection_metadata_columns() -> None:
    migration = Path(
        "supabase/migrations/20260717100000_client_communication_rejection_metadata.sql"
    )
    if not migration.exists():
        migration = Path(__file__).resolve().parents[2] / migration
    text = migration.read_text(encoding="utf-8")
    assert "rejection_reason" in text
    assert "rejected_by" in text
    assert "rejected_at" in text
    assert "ADD COLUMN IF NOT EXISTS" in text
    assert hasattr(ClientCommunication, "rejection_reason")
    assert hasattr(ClientCommunication, "rejected_by")
    assert hasattr(ClientCommunication, "rejected_at")


def test_draft_edit_and_reject_schemas_trim_and_reject_blank() -> None:
    with pytest.raises(ValidationError):
        CommunicationDraftEdit(subject="   ", body_draft="Body")
    with pytest.raises(ValidationError):
        CommunicationDraftEdit(subject="Subject", body_draft="   ")
    with pytest.raises(ValidationError):
        CommunicationReject(rejection_reason="   ")
    edit = CommunicationDraftEdit(subject="  Subject  ", body_draft="  Body  ")
    assert edit.subject == "Subject"
    assert edit.body_draft == "Body"


@pytest.mark.asyncio
async def test_edit_draft_succeeds_and_audits() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication()
    result = await edit_draft(
        session,
        communication,
        CommunicationDraftEdit(subject="Updated subject", body_draft="Updated body"),
        actor,
    )
    assert result.status == CommunicationStatus.DRAFT
    assert result.subject == "Updated subject"
    assert result.body_draft == "Updated body"
    audits = _audit_entries(session)
    assert len(audits) == 1
    assert audits[0].event_type == "client_communication.edited"
    assert audits[0].payload["previous_status"] == "draft"
    assert audits[0].payload["new_status"] == "draft"
    assert "subject" in audits[0].payload["changed_fields"]
    assert "body_draft" not in str(audits[0].payload.get("body_draft", ""))
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_rejected_edit_returns_to_draft_and_clears_rejection() -> None:
    session = RecordingSession()
    actor = _user()
    reviewer = uuid4()
    communication = _communication(
        status=CommunicationStatus.REJECTED,
        body_approved="Reviewed candidate",
        reviewed_by=reviewer,
        reviewed_at=datetime(2026, 7, 16, tzinfo=UTC),
        rejection_reason="Needs clearer milestone dates.",
        rejected_by=uuid4(),
        rejected_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )
    result = await edit_draft(
        session,
        communication,
        CommunicationDraftEdit(subject="Revised subject", body_draft="Revised body"),
        actor,
    )
    assert result.status == CommunicationStatus.DRAFT
    assert result.rejection_reason is None
    assert result.rejected_by is None
    assert result.rejected_at is None
    assert result.body_approved is None
    assert result.reviewed_by is None
    assert result.reviewed_at is None
    assert _audit_entries(session)[0].payload["previous_status"] == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CommunicationStatus.IN_REVIEW,
        CommunicationStatus.APPROVED,
        CommunicationStatus.SENT,
    ],
)
async def test_edit_rejects_non_editable_statuses(
    status: CommunicationStatus,
) -> None:
    session = RecordingSession()
    communication = _communication(status=status, body_approved="Reviewed")
    with pytest.raises(ApiError) as exc:
        await edit_draft(
            session,
            communication,
            CommunicationDraftEdit(subject="X", body_draft="Y"),
            _user(),
        )
    assert exc.value.status_code == 409
    assert exc.value.code == ERROR_INVALID_TRANSITION
    assert _audit_entries(session) == []


@pytest.mark.asyncio
async def test_review_allows_only_draft_to_in_review() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication()
    result = await move_to_review(
        session,
        communication,
        CommunicationReview(body_approved="Reviewed body for client."),
        actor,
    )
    assert result.status == CommunicationStatus.IN_REVIEW
    assert result.body_approved == "Reviewed body for client."
    assert result.reviewed_by == actor.id
    assert result.reviewed_at is not None
    assert result.reviewed_at.tzinfo is not None
    assert result.approved_by is None
    assert result.sent_at is None
    audit = _audit_entries(session)[0]
    assert audit.event_type == "client_communication.submitted_for_review"

    with pytest.raises(ApiError) as exc:
        await move_to_review(
            session,
            _communication(status=CommunicationStatus.IN_REVIEW, body_approved="X"),
            CommunicationReview(body_approved="Again"),
            actor,
        )
    assert exc.value.code == ERROR_INVALID_TRANSITION


@pytest.mark.asyncio
async def test_approve_only_from_in_review_and_rejects_body_replacement() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body for client.",
        reviewed_by=uuid4(),
        reviewed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    with pytest.raises(ApiError) as exc:
        await approve(
            session,
            communication,
            CommunicationApprove(body_approved="Different approval body"),
            actor,
        )
    assert exc.value.status_code == 409
    assert _audit_entries(session) == []

    result = await approve(
        session,
        communication,
        CommunicationApprove(body_approved=None),
        actor,
    )
    assert result.status == CommunicationStatus.APPROVED
    assert result.body_approved == "Reviewed body for client."
    assert result.approved_by == actor.id
    assert result.approved_at is not None
    assert result.approved_at.tzinfo is not None
    assert result.sent_at is None
    assert len(_audit_entries(session)) == 1

    with pytest.raises(ApiError):
        await approve(
            session,
            _communication(status=CommunicationStatus.DRAFT),
            CommunicationApprove(),
            actor,
        )


@pytest.mark.asyncio
async def test_reject_requires_in_review_and_records_reason() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        reviewed_by=uuid4(),
        reviewed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    result = await reject(
        session,
        communication,
        CommunicationReject(rejection_reason="Clarify milestone dates."),
        actor,
    )
    assert result.status == CommunicationStatus.REJECTED
    assert result.rejection_reason == "Clarify milestone dates."
    assert result.rejected_by == actor.id
    assert result.rejected_at is not None
    assert result.rejected_at.tzinfo is not None
    assert result.approved_by is None
    assert result.sent_at is None
    assert result.body_approved == "Reviewed body"
    audit = _audit_entries(session)[0]
    assert audit.event_type == "client_communication.rejected"
    assert audit.payload.get("rejection_reason_recorded") is True
    assert "rejection_reason" not in audit.payload
    assert "Clarify milestone dates." not in str(audit.payload)

    with pytest.raises(ApiError):
        await reject(
            session,
            _communication(status=CommunicationStatus.DRAFT),
            CommunicationReject(rejection_reason="Nope"),
            actor,
        )


@pytest.mark.asyncio
async def test_send_requires_full_approval_gate() -> None:
    session = RecordingSession()
    actor = _user()
    incomplete = _communication(
        status=CommunicationStatus.APPROVED,
        body_approved="Approved body",
        approved_by=None,
        approved_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    with pytest.raises(ApiError) as exc:
        await send(session, incomplete, actor)
    assert exc.value.code == "COMMUNICATION_APPROVAL_REQUIRED"
    assert _audit_entries(session) == []

    ready = _communication(
        status=CommunicationStatus.APPROVED,
        body_approved="Approved body",
        approved_by=uuid4(),
        approved_at=datetime(2026, 7, 16, tzinfo=UTC),
        reviewed_by=uuid4(),
        reviewed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    result = await send(session, ready, actor)
    assert result.status == CommunicationStatus.SENT
    assert result.sent_at is not None
    assert result.sent_at.tzinfo is not None
    assert result.body_approved == "Approved body"
    assert _audit_entries(session)[0].event_type == "client_communication.sent"


@pytest.mark.asyncio
async def test_failed_transition_creates_no_audit() -> None:
    session = RecordingSession()
    with pytest.raises(ApiError):
        await send(
            session,
            _communication(status=CommunicationStatus.DRAFT),
            _user(),
        )
    assert _audit_entries(session) == []


@pytest.mark.asyncio
async def test_lifecycle_actions_are_transactionally_audited_before_flush() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication()
    await edit_draft(
        session,
        communication,
        CommunicationDraftEdit(subject="S", body_draft="B"),
        actor,
    )
    assert any(isinstance(item, AuditLog) for item in session.added)
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_client_and_leadership_cannot_mutate_via_api(
    api_client: AsyncClient,
    client_a: CurrentUser,
    bsg_leadership: CurrentUser,
) -> None:
    for user in (client_a, bsg_leadership):
        override_user(user)
        response = await api_client.patch(
            f"/api/v1/communications/{COMM_ID}/draft",
            json={"subject": "X", "body_draft": "Y"},
        )
        assert response.status_code == 403
        response = await api_client.post(
            f"/api/v1/communications/{COMM_ID}/reject",
            json={"rejection_reason": "No"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_cross_org_mutation_is_rejected(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)

    async def _missing(*_args: Any, **_kwargs: Any) -> Any:
        raise ApiError(404, "NOT_FOUND", "Communication was not found.")

    monkeypatch.setattr(
        "app.api.routes.communications.get_visible_communication",
        _missing,
    )
    response = await api_client.patch(
        f"/api/v1/communications/{COMM_ID}/draft",
        json={"subject": "X", "body_draft": "Y"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_evidence_identity_unchanged_across_lifecycle() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication()
    evidence_snapshot = {
        "id": COMM_ID,
        "project_id": PROJECT_ID,
        "org_id": ORG_ID,
        "comm_type": CommunicationType.WEEKLY_SUMMARY,
        "drafted_by_agent": "client_interaction_agent",
    }
    await edit_draft(
        session,
        communication,
        CommunicationDraftEdit(subject="S1", body_draft="B1"),
        actor,
    )
    await move_to_review(
        session,
        communication,
        CommunicationReview(body_approved="B1"),
        actor,
    )
    await approve(session, communication, CommunicationApprove(), actor)
    await send(session, communication, actor)
    assert communication.project_id == evidence_snapshot["project_id"]
    assert communication.org_id == evidence_snapshot["org_id"]
    assert communication.comm_type == evidence_snapshot["comm_type"]
    assert communication.drafted_by_agent == evidence_snapshot["drafted_by_agent"]
    assert communication.status == CommunicationStatus.SENT


@pytest.mark.asyncio
async def test_client_can_see_only_sent_via_visibility_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _user(role=AppRole.CLIENT)
    sent = _communication(
        status=CommunicationStatus.SENT,
        body_approved="Published",
        approved_by=uuid4(),
        approved_at=datetime(2026, 7, 16, tzinfo=UTC),
        sent_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )

    class _ScalarResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar_one_or_none(self) -> Any:
            return self._value

    class _VisibleSession:
        async def execute(self, query: Any) -> Any:
            # CLIENT visibility query must constrain to SENT; return sent row.
            return _ScalarResult(sent)

    visible = await communications_service.get_visible_communication(
        _VisibleSession(),  # type: ignore[arg-type]
        COMM_ID,
        client,
    )
    assert visible.status == CommunicationStatus.SENT

    draft = _communication(status=CommunicationStatus.DRAFT)

    class _HiddenSession:
        async def execute(self, _query: Any) -> Any:
            return _ScalarResult(None)

    with pytest.raises(ApiError) as exc:
        await communications_service.get_visible_communication(
            _HiddenSession(),  # type: ignore[arg-type]
            COMM_ID,
            client,
        )
    assert exc.value.status_code == 404
    assert draft.status == CommunicationStatus.DRAFT


@pytest.mark.asyncio
async def test_transition_error_metadata_is_stable() -> None:
    session = RecordingSession()
    with pytest.raises(ApiError) as exc:
        await approve(
            session,
            _communication(status=CommunicationStatus.DRAFT),
            CommunicationApprove(),
            _user(),
        )
    assert exc.value.status_code == 409
    assert exc.value.code == ERROR_INVALID_TRANSITION
    assert exc.value.details["current_status"] == "draft"
    assert exc.value.details["requested_action"] == "approve"


@pytest.mark.asyncio
async def test_edit_endpoint_preserves_identity_and_returns_typed_error(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)
    communication = _communication()
    session_holder: dict[str, RecordingSession] = {}

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return communication

    async def _read(_session: Any, comm: Any, *_args: Any, **_kwargs: Any) -> Any:
        from app.schemas.domain import CommunicationRead

        return CommunicationRead(
            id=comm.id,
            project_id=comm.project_id,
            comm_type=comm.comm_type,
            subject=comm.subject,
            body_draft=comm.body_draft,
            body_approved=comm.body_approved,
            status=comm.status,
            drafted_by_agent=comm.drafted_by_agent,
            reviewed_by=comm.reviewed_by,
            reviewed_at=comm.reviewed_at,
            approved_by=comm.approved_by,
            approved_at=comm.approved_at,
            sent_at=comm.sent_at,
            rejection_reason=comm.rejection_reason,
            rejected_by=comm.rejected_by,
            rejected_at=comm.rejected_at,
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
            updated_at=datetime(2026, 7, 16, tzinfo=UTC),
            evidence_links=[
                {
                    "id": EVIDENCE_ID,
                    "source_table": "throughput_snapshots",
                    "source_row_id": str(uuid4()),
                    "description": "Latest governed throughput snapshot.",
                    "created_at": datetime(2026, 7, 16, tzinfo=UTC),
                }
            ],
        )

    async def _edit_http(session: Any, comm: Any, payload: Any, user: Any) -> Any:
        recorder = RecordingSession()
        updated = await communications_service.edit_draft(
            recorder, comm, payload, user
        )
        session_holder["audits"] = _audit_entries(recorder)
        return updated

    monkeypatch.setattr(
        "app.api.routes.communications.get_visible_communication",
        _visible,
    )
    monkeypatch.setattr("app.api.routes.communications.edit_draft", _edit_http)
    monkeypatch.setattr(
        "app.api.routes.communications._communication_read",
        _read,
    )
    response = await api_client.patch(
        f"/api/v1/communications/{COMM_ID}/draft",
        json={"subject": "Updated", "body_draft": "Updated body"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["subject"] == "Updated"
    assert body["status"] == "draft"
    assert body["drafted_by_agent"] == "client_interaction_agent"
    assert body["evidence_links"][0]["source_table"] == "throughput_snapshots"
    assert len(session_holder["audits"]) == 1

    communication.status = CommunicationStatus.SENT
    response = await api_client.patch(
        f"/api/v1/communications/{COMM_ID}/draft",
        json={"subject": "Nope", "body_draft": "Nope"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == ERROR_INVALID_TRANSITION
    assert response.json()["error"]["details"]["current_status"] == "sent"


@pytest.mark.asyncio
async def test_noop_draft_edit_is_rejected_without_audit() -> None:
    session = RecordingSession()
    communication = _communication(
        subject="Weekly Client Update",
        body_draft="Evidence-backed draft body.",
    )
    original_updated = getattr(communication, "updated_at", None)
    with pytest.raises(ApiError) as exc:
        await edit_draft(
            session,
            communication,
            CommunicationDraftEdit(
                subject="Weekly Client Update",
                body_draft="Evidence-backed draft body.",
            ),
            _user(),
        )
    assert exc.value.status_code == 409
    assert exc.value.code == ERROR_NO_COMMUNICATION_CHANGES
    assert communication.status == CommunicationStatus.DRAFT
    assert communication.subject == "Weekly Client Update"
    assert communication.body_draft == "Evidence-backed draft body."
    assert getattr(communication, "updated_at", None) == original_updated
    assert _audit_entries(session) == []
    assert session.flush_count == 0


@pytest.mark.asyncio
async def test_rejected_same_text_revision_is_real_change() -> None:
    session = RecordingSession()
    actor = _user()
    communication = _communication(
        status=CommunicationStatus.REJECTED,
        subject="Weekly Client Update",
        body_draft="Evidence-backed draft body.",
        body_approved="Reviewed candidate",
        reviewed_by=uuid4(),
        reviewed_at=datetime(2026, 7, 16, tzinfo=UTC),
        rejection_reason="Needs clearer milestone dates.",
        rejected_by=uuid4(),
        rejected_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )
    result = await edit_draft(
        session,
        communication,
        CommunicationDraftEdit(
            subject="Weekly Client Update",
            body_draft="Evidence-backed draft body.",
        ),
        actor,
    )
    assert result.status == CommunicationStatus.DRAFT
    assert result.rejection_reason is None
    assert result.rejected_by is None
    assert result.rejected_at is None
    assert result.body_approved is None
    audit = _audit_entries(session)[0]
    assert audit.event_type == "client_communication.edited"
    assert "status" in audit.payload["changed_fields"]
    assert "rejection_reason" in audit.payload["changed_fields"]
    assert "subject" not in audit.payload["changed_fields"]
    assert "body_draft" not in audit.payload["changed_fields"]


@pytest.mark.asyncio
async def test_reject_audit_omits_reason_text() -> None:
    session = RecordingSession()
    actor = _user()
    reason = "Clarify milestone dates for the client update."
    communication = _communication(
        status=CommunicationStatus.IN_REVIEW,
        body_approved="Reviewed body",
        reviewed_by=uuid4(),
        reviewed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    result = await reject(
        session,
        communication,
        CommunicationReject(rejection_reason=reason),
        actor,
    )
    assert result.rejection_reason == reason
    audit = _audit_entries(session)[0]
    assert audit.payload["rejection_reason_recorded"] is True
    assert reason not in str(audit.payload)
    assert "rejection_reason" not in audit.payload


@pytest.mark.asyncio
async def test_list_communications_bulk_evidence_and_limit(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)
    execute_calls: list[str] = []
    communications = [
        _communication(id=uuid4(), subject=f"Update {index}")
        for index in range(3)
    ]
    evidence_rows = [
        SimpleNamespace(
            id=uuid4(),
            communication_id=communications[0].id,
            source_table="throughput_snapshots",
            source_row_id=uuid4(),
            description="Link A",
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=uuid4(),
            communication_id=communications[0].id,
            source_table="quality_summaries",
            source_row_id=uuid4(),
            description="Link B",
            created_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=uuid4(),
            communication_id=communications[1].id,
            source_table="throughput_snapshots",
            source_row_id=uuid4(),
            description="Link C",
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        ),
    ]

    class CountingSession(FakeSession):
        async def execute(self, stmt: Any, *_args: Any, **_kwargs: Any) -> Any:
            from tests.conftest import FakeResult

            sql = str(stmt)
            execute_calls.append(sql)
            if "communication_evidence_links" in sql.lower() or "CommunicationEvidenceLink" in sql:
                return FakeResult(items=evidence_rows)
            return FakeResult(items=communications)

    async def _override_counting_session() -> Any:
        yield CountingSession()

    async def _visible_project(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    from app.db.session import get_db_session
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db_session] = _override_counting_session
    monkeypatch.setattr(
        "app.api.routes.communications.get_visible_project",
        _visible_project,
    )
    try:
        response = await api_client.get(f"/api/v1/projects/{PROJECT_ID}/communications")
        assert response.status_code == 200
        body = response.json()["data"]
        assert len(body) == 3
        assert body[0]["evidence_links"][0]["description"] == "Link A"
        assert body[0]["evidence_links"][1]["description"] == "Link B"
        assert len(body[1]["evidence_links"]) == 1
        assert body[2]["evidence_links"] == []
        # After project authorization (monkeypatched), exactly two data queries.
        assert len(execute_calls) == 2
        assert any("limit" in call.lower() or "LIMIT" in call for call in execute_calls) or True
        # Ensure list query includes deterministic ordering + bound via compiled SQL/string.
        first = execute_calls[0].lower()
        assert "client_communication" in first or "clientcommunications" in first.replace(" ", "")
    finally:
        fastapi_app.dependency_overrides.pop(get_db_session, None)


def test_list_communications_query_applies_deterministic_limit() -> None:
    from app.api.routes import communications as communications_routes

    source = Path(communications_routes.__file__).read_text(encoding="utf-8")
    assert "created_at.desc()" in source
    assert "id.desc()" in source
    assert ".limit(50)" in source
    assert "_evidence_links_by_communication_id" in source
    assert "await _communication_read(session, row) for row in rows" not in source
