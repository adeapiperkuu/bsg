"""Focused tests for Client Intelligence Approved & Sent report history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, CommunicationStatus, CommunicationType
from app.db.session import get_db_session
from app.main import app
from app.schemas.client_intelligence import (
    ClientIntelligenceReportHistoryItem,
    ClientIntelligenceReportHistoryRead,
    ClientIntelligenceReportStatus,
    ReportProvenanceAvailability,
)
from app.services import client_intelligence as client_intelligence_service
from app.services.client_intelligence import (
    _APPROVED_STATUSES,
    CLIENT_INTERACTION_AGENT_NAME,
    LIMITATION_REPORT_APPROVED_AT_MISSING,
    LIMITATION_REPORT_APPROVED_BODY_MISSING,
    LIMITATION_REPORT_APPROVER_MISSING,
    LIMITATION_REPORT_HISTORY_TIMESTAMP_FALLBACK,
    LIMITATION_REPORT_REVIEW_PROVENANCE_INCOMPLETE,
    LIMITATION_REPORT_SENT_AT_MISSING,
    REPORT_HISTORY_MAX_LIMIT,
    _aggregate_reports,
    _assess_report_provenance,
    _report_history_base_filters,
    build_client_intelligence_report_history,
)
from tests.conftest import FakeResult, FakeSession, override_user

ORG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ORG_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PROJECT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
OTHER_PROJECT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
GUESSED_PROJECT_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
REPORTS_PATH = f"/api/v1/projects/{PROJECT_ID}/client-intelligence/reports"


def _user(
    *,
    role: AppRole = AppRole.DELIVERY_MANAGER,
    org_id: UUID = ORG_ID,
) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _row(**overrides: Any) -> SimpleNamespace:
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    base = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "org_id": ORG_ID,
        "comm_type": CommunicationType.WEEKLY_SUMMARY,
        "subject": "Weekly Client Update",
        "body_draft": "Draft body must not appear.",
        "body_approved": "Approved body for the client.",
        "status": CommunicationStatus.APPROVED,
        "drafted_by_agent": CLIENT_INTERACTION_AGENT_NAME,
        "reviewed_by": uuid4(),
        "reviewed_at": now - timedelta(hours=2),
        "approved_by": uuid4(),
        "approved_at": now - timedelta(hours=1),
        "sent_at": None,
        "created_at": now - timedelta(days=1),
        "updated_at": now,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _compile(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


class ReportHistoryResult(FakeResult):
    def __init__(
        self,
        *,
        value: Any = None,
        items: list[Any] | None = None,
    ) -> None:
        super().__init__(value=value, items=items or [])

    def one(self) -> Any:
        return self._value


class ReportHistorySession(FakeSession):
    def __init__(self, queue: list[ReportHistoryResult] | None = None) -> None:
        self.queue = list(queue or [])
        self.executed: list[Any] = []
        self.compiled: list[str] = []
        self.mutation_calls: list[str] = []

    async def execute(self, statement: Any = None, *_args: Any, **_kwargs: Any) -> Any:
        self.executed.append(statement)
        if statement is not None:
            self.compiled.append(_compile(statement))
        if not self.queue:
            return ReportHistoryResult(value=0, items=[])
        return self.queue.pop(0)

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        self.mutation_calls.append("add")

    async def flush(self, *_args: Any, **_kwargs: Any) -> None:
        self.mutation_calls.append("flush")

    async def commit(self) -> None:
        self.mutation_calls.append("commit")

    async def delete(self, *_args: Any, **_kwargs: Any) -> None:
        self.mutation_calls.append("delete")


def _sql_uuid(value: UUID) -> str:
    return str(value).replace("-", "")


def test_openapi_registers_report_history_route() -> None:
    schema = app.openapi()
    path = "/api/v1/projects/{project_id}/client-intelligence/reports"
    assert path in schema["paths"]
    assert "get" in schema["paths"][path]


def test_report_history_item_rejects_draft_body_as_approved() -> None:
    with pytest.raises(ValidationError):
        ClientIntelligenceReportHistoryItem(
            communication_id=uuid4(),
            project_id=PROJECT_ID,
            report_type="weekly_summary",
            subject="Subject",
            approved_body=None,
            status=ClientIntelligenceReportStatus.APPROVED,
            provenance_availability=ReportProvenanceAvailability.COMPLETE,
            limitations=[],
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
            updated_at=datetime(2026, 7, 16, tzinfo=UTC),
            approved_by=uuid4(),
            approved_at=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_report_history_contracts_reject_inconsistent_availability() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    with pytest.raises(ValidationError):
        ClientIntelligenceReportHistoryItem(
            communication_id=uuid4(),
            project_id=PROJECT_ID,
            report_type="weekly_summary",
            subject="Subject",
            approved_body="Body",
            status=ClientIntelligenceReportStatus.APPROVED,
            provenance_availability=ReportProvenanceAvailability.COMPLETE,
            limitations=[LIMITATION_REPORT_APPROVER_MISSING],
            created_at=now,
            updated_at=now,
            approved_by=uuid4(),
            approved_at=now,
        )
    with pytest.raises(ValidationError):
        ClientIntelligenceReportHistoryItem(
            communication_id=uuid4(),
            project_id=PROJECT_ID,
            report_type="weekly_summary",
            subject="Subject",
            approved_body="Body",
            status=ClientIntelligenceReportStatus.APPROVED,
            provenance_availability=ReportProvenanceAvailability.UNAVAILABLE,
            limitations=[LIMITATION_REPORT_APPROVED_BODY_MISSING],
            created_at=now,
            updated_at=now,
        )
    with pytest.raises(ValidationError):
        ClientIntelligenceReportHistoryItem(
            communication_id=uuid4(),
            project_id=PROJECT_ID,
            report_type="weekly_summary",
            subject="Subject",
            approved_body=None,
            status=ClientIntelligenceReportStatus.APPROVED,
            provenance_availability=ReportProvenanceAvailability.PARTIAL,
            limitations=[LIMITATION_REPORT_APPROVED_BODY_MISSING],
            created_at=now,
            updated_at=now,
        )


def test_assess_complete_approved_and_sent_provenance() -> None:
    approved = _row()
    availability, body, limitations, history_at = _assess_report_provenance(approved)
    assert availability == ReportProvenanceAvailability.COMPLETE
    assert body == "Approved body for the client."
    assert limitations == []
    assert history_at == approved.approved_at

    sent = _row(
        status=CommunicationStatus.SENT,
        sent_at=datetime(2026, 7, 16, 15, tzinfo=UTC),
    )
    availability, body, limitations, history_at = _assess_report_provenance(sent)
    assert availability == ReportProvenanceAvailability.COMPLETE
    assert history_at == sent.sent_at
    assert limitations == []


def test_assess_every_stable_limitation_code() -> None:
    unavailable = _row(body_approved=None, body_draft="Draft body must not appear.")
    availability, body, limitations, history_at = _assess_report_provenance(unavailable)
    assert availability == ReportProvenanceAvailability.UNAVAILABLE
    assert body is None
    assert LIMITATION_REPORT_APPROVED_BODY_MISSING in limitations
    assert "Draft body" not in (body or "")

    missing_approver = _row(approved_by=None)
    availability, body, limitations, history_at = _assess_report_provenance(missing_approver)
    assert availability == ReportProvenanceAvailability.PARTIAL
    assert body == "Approved body for the client."
    assert LIMITATION_REPORT_APPROVER_MISSING in limitations
    assert history_at == missing_approver.approved_at

    missing_approved_at = _row(approved_at=None)
    availability, body, limitations, history_at = _assess_report_provenance(missing_approved_at)
    assert availability == ReportProvenanceAvailability.PARTIAL
    assert LIMITATION_REPORT_APPROVED_AT_MISSING in limitations
    assert LIMITATION_REPORT_HISTORY_TIMESTAMP_FALLBACK in limitations
    assert history_at is None

    missing_review = _row(reviewed_by=None, reviewed_at=None)
    availability, body, limitations, history_at = _assess_report_provenance(missing_review)
    assert availability == ReportProvenanceAvailability.PARTIAL
    assert LIMITATION_REPORT_REVIEW_PROVENANCE_INCOMPLETE in limitations

    missing_sent_at = _row(status=CommunicationStatus.SENT, sent_at=None)
    availability, body, limitations, history_at = _assess_report_provenance(missing_sent_at)
    assert availability == ReportProvenanceAvailability.PARTIAL
    assert LIMITATION_REPORT_SENT_AT_MISSING in limitations
    assert LIMITATION_REPORT_HISTORY_TIMESTAMP_FALLBACK in limitations
    assert history_at is None


def test_naive_timestamps_are_not_treated_as_genuine_provenance() -> None:
    row = _row(
        approved_at=datetime(2026, 7, 16, 13),
        reviewed_at=datetime(2026, 7, 16, 12),
        sent_at=None,
    )
    availability, body, limitations, history_at = _assess_report_provenance(row)
    assert body == "Approved body for the client."
    assert availability == ReportProvenanceAvailability.PARTIAL
    assert LIMITATION_REPORT_APPROVED_AT_MISSING in limitations
    assert history_at is None


def test_report_history_and_summary_share_canonical_status_agent_predicates() -> None:
    assert _APPROVED_STATUSES == (
        CommunicationStatus.APPROVED,
        CommunicationStatus.SENT,
    )
    filters = _report_history_base_filters(PROJECT_ID, None)
    compiled = " AND ".join(_compile(clause) for clause in filters)
    assert _sql_uuid(PROJECT_ID) in compiled
    assert CLIENT_INTERACTION_AGENT_NAME in compiled
    assert "status IN ('approved', 'sent')" in compiled or (
        "approved" in compiled and "sent" in compiled and "status" in compiled
    )
    status_clause = compiled.lower()
    assert "in_review" not in status_clause
    assert "rejected" not in status_clause
    assert "status in ('draft'" not in status_clause.replace(" ", "")


@pytest.mark.asyncio
async def test_build_report_history_sql_predicates_ordering_and_no_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = [
        _row(
            id=UUID("22222222-2222-4222-8222-222222222222"),
            approved_at=datetime(2026, 7, 16, 14, tzinfo=UTC),
        ),
        _row(
            id=UUID("11111111-1111-4111-8111-111111111111"),
            approved_at=datetime(2026, 7, 16, 14, tzinfo=UTC),
        ),
    ]
    evidence = [
        SimpleNamespace(
            id=uuid4(),
            communication_id=page[0].id,
            source_table="throughput_snapshots",
            source_row_id=uuid4(),
            description="Evidence A",
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
    ]
    session = ReportHistorySession(
        [
            ReportHistoryResult(value=2),
            ReportHistoryResult(items=page),
            ReportHistoryResult(items=evidence),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(client_intelligence_service, "get_visible_project", _visible)
    history = await build_client_intelligence_report_history(
        session,
        _user(),
        PROJECT_ID,
        limit=20,
        offset=0,
    )
    assert history.total == 2
    assert len(history.items) == 2
    assert len(session.compiled) == 3
    assert session.mutation_calls == []

    count_sql, page_sql, evidence_sql = session.compiled
    for sql in (count_sql, page_sql):
        assert _sql_uuid(PROJECT_ID) in sql
        assert CLIENT_INTERACTION_AGENT_NAME in sql
        where_sql = sql.lower().split("where", 1)[-1]
        assert "status in ('approved', 'sent')" in where_sql.replace(" ", "") or (
            "'approved'" in where_sql and "'sent'" in where_sql
        )
        assert "in_review" not in where_sql
        assert "status in ('draft'" not in where_sql.replace(" ", "")
        assert "status in ('rejected'" not in where_sql.replace(" ", "")

    assert "order by" in page_sql.lower()
    assert "created_at" in page_sql.lower()
    assert "approved_at" in page_sql.lower() or "sent_at" in page_sql.lower()
    assert "id" in page_sql.lower()
    assert _sql_uuid(page[0].id) in evidence_sql or str(page[0].id) in evidence_sql
    assert _sql_uuid(page[1].id) in evidence_sql or str(page[1].id) in evidence_sql
    assert "ffffffff-ffff-4fff-8fff-ffffffffffff" not in evidence_sql
    assert all(item.approved_body == "Approved body for the client." for item in history.items)
    assert all("Draft body" not in (item.approved_body or "") for item in history.items)


@pytest.mark.asyncio
async def test_status_filter_applied_identically_to_count_and_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ReportHistorySession(
        [
            ReportHistoryResult(value=1),
            ReportHistoryResult(
                items=[
                    _row(
                        status=CommunicationStatus.SENT,
                        sent_at=datetime(2026, 7, 16, 15, tzinfo=UTC),
                    )
                ]
            ),
            ReportHistoryResult(items=[]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(client_intelligence_service, "get_visible_project", _visible)
    history = await build_client_intelligence_report_history(
        session,
        _user(),
        PROJECT_ID,
        status_filter=ClientIntelligenceReportStatus.SENT,
    )
    assert history.total == 1
    assert history.status_filter == ClientIntelligenceReportStatus.SENT
    count_sql, page_sql, _evidence_sql = session.compiled
    where_count = count_sql.lower().split("where", 1)[-1].replace(" ", "")
    where_page = page_sql.lower().split("where", 1)[-1].replace(" ", "")
    assert "statusin('sent')" in where_count or "status='sent'" in where_count
    assert "statusin('sent')" in where_page or "status='sent'" in where_page
    assert "statusin('approved'" not in where_count
    assert "statusin('approved'" not in where_page


@pytest.mark.asyncio
async def test_missing_lifecycle_timestamp_keeps_history_at_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(approved_at=None, created_at=datetime(2026, 7, 10, tzinfo=UTC))
    session = ReportHistorySession(
        [
            ReportHistoryResult(value=1),
            ReportHistoryResult(items=[row]),
            ReportHistoryResult(items=[]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(client_intelligence_service, "get_visible_project", _visible)
    history = await build_client_intelligence_report_history(
        session,
        _user(),
        PROJECT_ID,
    )
    assert history.items[0].history_at is None
    assert history.items[0].approved_at is None
    assert LIMITATION_REPORT_HISTORY_TIMESTAMP_FALLBACK in history.items[0].limitations
    assert "coalesce" in session.compiled[1].lower()
    assert "created_at" in session.compiled[1].lower()


@pytest.mark.asyncio
async def test_empty_history_returns_truthful_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ReportHistorySession(
        [
            ReportHistoryResult(value=0),
            ReportHistoryResult(items=[]),
            ReportHistoryResult(items=[]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(client_intelligence_service, "get_visible_project", _visible)
    history = await build_client_intelligence_report_history(
        session,
        _user(),
        PROJECT_ID,
    )
    assert history.total == 0
    assert history.items == []
    assert history.has_more is False
    # Empty page still issues count + page; evidence skipped when no IDs.
    assert len(session.compiled) == 2
    assert session.mutation_calls == []


@pytest.mark.asyncio
async def test_build_report_history_rejects_limit_above_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(client_intelligence_service, "get_visible_project", _visible)
    with pytest.raises(ApiError) as exc:
        await build_client_intelligence_report_history(
            ReportHistorySession([]),
            _user(),
            PROJECT_ID,
            limit=REPORT_HISTORY_MAX_LIMIT + 1,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_report_history_endpoint_rbac(
    api_client: AsyncClient,
    client_a: CurrentUser,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = ClientIntelligenceReportHistoryRead(
        project_id=PROJECT_ID,
        items=[],
        limit=20,
        offset=0,
        total=0,
        has_more=False,
        status_filter=None,
    )

    async def _history(*_args: Any, **_kwargs: Any) -> Any:
        return empty

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_report_history",
        _history,
    )

    override_user(client_a)
    response = await api_client.get(REPORTS_PATH)
    assert response.status_code == 403

    for role_user in (
        delivery_manager,
        _user(role=AppRole.BSG_LEADERSHIP),
        _user(role=AppRole.SUPER_ADMIN),
    ):
        override_user(role_user)
        response = await api_client.get(REPORTS_PATH)
        assert response.status_code == 200
        assert response.json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_report_history_endpoint_status_filter_and_unknown(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _history(*_args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return ClientIntelligenceReportHistoryRead(
            project_id=PROJECT_ID,
            items=[],
            limit=kwargs.get("limit", 20),
            offset=kwargs.get("offset", 0),
            total=0,
            has_more=False,
            status_filter=kwargs.get("status_filter"),
        )

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_report_history",
        _history,
    )
    override_user(delivery_manager)
    response = await api_client.get(f"{REPORTS_PATH}?status=sent&limit=10&offset=0")
    assert response.status_code == 200
    assert captured["status_filter"] == ClientIntelligenceReportStatus.SENT
    assert captured["limit"] == 10

    response = await api_client.get(f"{REPORTS_PATH}?status=draft")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_report_history_uses_real_project_scoping_for_missing_and_cross_org(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
) -> None:
    """Do not mock the service; exercise get_visible_project via the route session."""

    class ScopingSession(FakeSession):
        def __init__(self, project: Any | None) -> None:
            self.project = project

        async def execute(self, statement: Any = None, *_args: Any, **_kwargs: Any) -> Any:
            return ReportHistoryResult(value=self.project)

    async def _missing_project() -> Any:
        yield ScopingSession(None)

    override_user(delivery_manager)
    app.dependency_overrides[get_db_session] = _missing_project
    try:
        response = await api_client.get(
            f"/api/v1/projects/{GUESSED_PROJECT_ID}/client-intelligence/reports"
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    foreign = SimpleNamespace(id=OTHER_PROJECT_ID, org_id=OTHER_ORG_ID)

    async def _foreign_project() -> Any:
        yield ScopingSession(foreign)

    app.dependency_overrides[get_db_session] = _foreign_project
    try:
        response = await api_client.get(
            f"/api/v1/projects/{OTHER_PROJECT_ID}/client-intelligence/reports"
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
async def test_report_history_total_reconciles_with_reports_summary_from_same_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row(id=UUID("11111111-1111-4111-8111-111111111111"), status=CommunicationStatus.APPROVED),
        _row(
            id=UUID("22222222-2222-4222-8222-222222222222"),
            status=CommunicationStatus.SENT,
            sent_at=datetime(2026, 7, 16, 16, tzinfo=UTC),
        ),
        _row(
            id=UUID("33333333-3333-4333-8333-333333333333"),
            status=CommunicationStatus.DRAFT,
        ),
        _row(
            id=UUID("44444444-4444-4444-8444-444444444444"),
            status=CommunicationStatus.IN_REVIEW,
        ),
        _row(
            id=UUID("55555555-5555-4555-8555-555555555555"),
            status=CommunicationStatus.REJECTED,
        ),
        _row(
            id=UUID("66666666-6666-4666-8666-666666666666"),
            drafted_by_agent="delivery_performance_agent",
            status=CommunicationStatus.APPROVED,
        ),
        _row(
            id=UUID("77777777-7777-4777-8777-777777777777"),
            project_id=OTHER_PROJECT_ID,
            status=CommunicationStatus.APPROVED,
        ),
    ]

    class SnapshotSession(ReportHistorySession):
        def __init__(self) -> None:
            super().__init__([])
            self.mode = "history"

        async def execute(self, statement: Any = None, *_args: Any, **_kwargs: Any) -> Any:
            self.executed.append(statement)
            compiled = _compile(statement) if statement is not None else ""
            self.compiled.append(compiled)
            lower = compiled.lower()

            if self.mode == "summary":
                eligible = [
                    row
                    for row in rows
                    if row.project_id == PROJECT_ID
                    and row.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME
                    and row.status != CommunicationStatus.REJECTED
                ]
                approved = [
                    row
                    for row in rows
                    if row.project_id == PROJECT_ID
                    and row.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME
                    and row.status in _APPROVED_STATUSES
                ]
                drafted = [
                    row
                    for row in rows
                    if row.project_id == PROJECT_ID
                    and row.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME
                    and row.status
                    in (
                        CommunicationStatus.DRAFT,
                        CommunicationStatus.IN_REVIEW,
                    )
                ]
                return ReportHistoryResult(
                    value=SimpleNamespace(
                        drafted_count=len(drafted),
                        approved_count=len(approved),
                        eligible_record_count=len(eligible),
                        sent_missing_approval=0,
                    )
                )

            matching = [
                row
                for row in rows
                if row.project_id == PROJECT_ID
                and row.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME
                and row.status in _APPROVED_STATUSES
            ]
            if "count(" in lower:
                return ReportHistoryResult(value=len(matching))
            if "communication_evidence" in lower:
                return ReportHistoryResult(items=[])
            return ReportHistoryResult(items=matching)

    session = SnapshotSession()

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID, org_id=ORG_ID)

    monkeypatch.setattr(client_intelligence_service, "get_visible_project", _visible)
    history = await build_client_intelligence_report_history(
        session,
        _user(),
        PROJECT_ID,
        status_filter=None,
    )
    session.mode = "summary"
    summary = await _aggregate_reports(session, [PROJECT_ID])
    assert history.total == 2
    assert summary.approved_count == 2
    assert history.total == summary.approved_count
    assert {item.status for item in history.items} == {
        ClientIntelligenceReportStatus.APPROVED,
        ClientIntelligenceReportStatus.SENT,
    }
