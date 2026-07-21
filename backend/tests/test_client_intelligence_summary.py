"""Focused tests for the Client Intelligence authorized-scope summary API."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.security import CurrentUser
from app.db.models import AppRole, CommunicationStatus, Project, ProjectStatus
from app.main import app
from app.schemas.client_intelligence import (
    ClientIntelligenceSummaryRead,
    CsatSummaryMetric,
    DeliveryConfidenceSummaryMetric,
    QueryResponseSummaryMetric,
    ReportsSummaryMetric,
    SummaryMetricAvailability,
)
from app.services.client_intelligence import (
    CLIENT_INTERACTION_AGENT_NAME,
    LIMITATION_CSAT_SCORE_OUT_OF_RANGE,
    LIMITATION_DELIVERY_CONFIDENCE_COVERAGE_PARTIAL,
    LIMITATION_NO_AUTHORIZED_PROJECTS,
    LIMITATION_QUERY_LATENCY_MISSING_OR_INVALID,
    LIMITATION_REPORT_SENT_APPROVAL_PROVENANCE_INCOMPLETE,
    _aggregate_csat,
    _aggregate_delivery_confidence,
    _aggregate_query_response,
    _aggregate_reports,
    build_client_intelligence_summary,
)
from app.services.scoping import scoped_project_query
from tests.conftest import ORG_A, FakeResult, FakeSession, override_user

_SUMMARY_PATH = "/api/v1/client-intelligence/summary"
PROJECT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECT_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PROJECT_OTHER = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class QueueResult(FakeResult):
    def one(self) -> Any:
        if self._value is not None:
            return self._value
        if self._items:
            return self._items[0]
        raise AssertionError("no queued result for .one()")


class SummarySession(FakeSession):
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = list(results or [])
        self.executed: list[Any] = []
        self.add_calls = 0
        self.commit_calls = 0
        self.flush_calls = 0

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        self.add_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def flush(self) -> None:
        self.flush_calls += 1

    async def execute(self, statement: Any = None, *_args: Any, **_kwargs: Any) -> QueueResult:
        self.executed.append(statement)
        if not self._results:
            return QueueResult(items=[])
        next_result = self._results.pop(0)
        if isinstance(next_result, QueueResult):
            return next_result
        if isinstance(next_result, list):
            return QueueResult(items=next_result)
        return QueueResult(value=next_result)


def _project(project_id: UUID = PROJECT_A, org_id: UUID = ORG_A) -> Project:
    return Project(
        id=project_id,
        org_id=org_id,
        name=f"Project {project_id.hex[:4]}",
        status=ProjectStatus.ACTIVE,
        description=None,
    )


def _compiled_values(statement: Any) -> list[Any]:
    values: list[Any] = []

    def _collect(value: Any) -> None:
        if isinstance(value, list | tuple | set | frozenset):
            for item in value:
                _collect(item)
            return
        values.append(value)
        enum_value = getattr(value, "value", None)
        if enum_value is not None:
            values.append(enum_value)

    for value in statement.compile().params.values():
        _collect(value)
    return values


def _summary_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "delivery_confidence": {
            "availability": "available",
            "average_score_pct": "87.50",
            "covered_project_count": 2,
            "eligible_project_count": 2,
            "limitations": [],
        },
        "reports": {
            "availability": "available",
            "drafted_count": 2,
            "approved_count": 3,
            "eligible_record_count": 5,
            "limitations": [],
        },
        "query_response": {
            "availability": "available",
            "average_latency_ms": 850,
            "sample_size": 4,
            "limitations": [],
        },
        "csat": {
            "availability": "available",
            "average_score": "4.5",
            "sample_size": 8,
            "scale_max": 5,
            "limitations": [],
        },
        "authorized_project_count": 2,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


def test_openapi_registers_summary_route_once() -> None:
    schema = app.openapi()
    path = "/api/v1/client-intelligence/summary"
    assert path in schema["paths"]
    assert list(schema["paths"][path].keys()) == ["get"]


@pytest.mark.asyncio
async def test_summary_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get(_SUMMARY_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_client_role_forbidden(
    api_client: AsyncClient,
    client_a: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(client_a)
    called = False

    async def _forbidden(*_args: Any, **_kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_summary",
        _forbidden,
    )
    response = await api_client.get(_SUMMARY_PATH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("user_fixture", ["delivery_manager", "bsg_leadership", "super_admin"])
async def test_allowed_roles_receive_summary(
    api_client: AsyncClient,
    user_fixture: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = request.getfixturevalue(user_fixture)
    override_user(user)
    summary = ClientIntelligenceSummaryRead.model_validate(_summary_payload())

    async def _summary(*_args: Any, **_kwargs: Any) -> ClientIntelligenceSummaryRead:
        return summary

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_summary",
        _summary,
    )
    response = await api_client.get(_SUMMARY_PATH)
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["delivery_confidence"]["average_score_pct"] == "87.50"
    assert body["reports"]["drafted_count"] == 2
    assert body["query_response"]["average_latency_ms"] == 850
    assert body["csat"]["average_score"] == "4.5"
    assert "submitted_by" not in str(body)
    assert "query_text" not in str(body)
    assert "answer_text" not in str(body)


@pytest.mark.asyncio
async def test_project_scoped_summary_passes_authorized_project_id(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)
    captured: dict[str, Any] = {}
    payload = _summary_payload(
        delivery_confidence={
            "availability": "available",
            "average_score_pct": "90.00",
            "covered_project_count": 1,
            "eligible_project_count": 1,
            "limitations": [],
        },
        authorized_project_count=1,
    )
    summary = ClientIntelligenceSummaryRead.model_validate(payload)

    async def _summary(
        *_args: Any,
        project_id: UUID | None = None,
        **_kwargs: Any,
    ) -> ClientIntelligenceSummaryRead:
        captured["project_id"] = project_id
        return summary

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_summary",
        _summary,
    )
    response = await api_client.get(
        _SUMMARY_PATH,
        params={"project_id": str(PROJECT_A)},
    )
    assert response.status_code == 200
    assert captured["project_id"] == PROJECT_A
    assert response.json()["data"]["authorized_project_count"] == 1


@pytest.mark.asyncio
async def test_no_visible_projects_returns_empty_no_data(
    delivery_manager: CurrentUser,
) -> None:
    session = SummarySession(results=[[]])
    result = await build_client_intelligence_summary(session, delivery_manager)
    assert result.authorized_project_count == 0
    assert result.delivery_confidence.availability == SummaryMetricAvailability.NO_DATA
    assert result.delivery_confidence.average_score_pct is None
    assert result.reports.availability == SummaryMetricAvailability.NO_DATA
    assert result.query_response.availability == SummaryMetricAvailability.NO_DATA
    assert result.csat.availability == SummaryMetricAvailability.NO_DATA
    assert LIMITATION_NO_AUTHORIZED_PROJECTS in result.reports.limitations
    assert result.reports.drafted_count == 0
    assert result.query_response.average_latency_ms is None
    assert result.csat.average_score is None
    assert len(session.executed) == 1
    assert session.add_calls == 0
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_organization_isolation_uses_scoped_projects(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visible = [_project(PROJECT_A, ORG_A)]
    session = SummarySession(
        results=[
            visible,
            SimpleNamespace(
                drafted_count=1,
                approved_count=0,
                eligible_record_count=1,
                sent_missing_approval=0,
            ),
            SimpleNamespace(
                average_latency_ms=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            ),
            SimpleNamespace(
                average_score=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            ),
        ]
    )
    captured: dict[str, Any] = {}

    async def _report(_session: Any, project_ids: list[UUID]):
        captured["project_ids"] = project_ids
        return ReportsSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            drafted_count=1,
            approved_count=0,
            eligible_record_count=1,
            limitations=[],
        )

    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_delivery_confidence",
        AsyncMock(
            return_value=DeliveryConfidenceSummaryMetric(
                availability=SummaryMetricAvailability.AVAILABLE,
                average_score_pct=Decimal("90.00"),
                covered_project_count=1,
                eligible_project_count=1,
                limitations=[],
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_reports",
        _report,
    )
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_query_response",
        AsyncMock(
            return_value=QueryResponseSummaryMetric(
                availability=SummaryMetricAvailability.NO_DATA,
                average_latency_ms=None,
                sample_size=0,
                limitations=[],
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_csat",
        AsyncMock(
            return_value=CsatSummaryMetric(
                availability=SummaryMetricAvailability.NO_DATA,
                average_score=None,
                sample_size=0,
                scale_max=5,
                limitations=[],
            )
        ),
    )
    result = await build_client_intelligence_summary(session, delivery_manager)
    assert captured["project_ids"] == [PROJECT_A]
    assert PROJECT_OTHER not in captured["project_ids"]
    assert result.authorized_project_count == 1


@pytest.mark.asyncio
async def test_authorized_project_subset_aggregation(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visible = [_project(PROJECT_A), _project(PROJECT_B)]
    session = SummarySession(results=[visible])
    seen: list[list[UUID]] = []

    async def _capture(_session: Any, project_ids: list[UUID]):
        seen.append(list(project_ids))
        return ReportsSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=[],
        )

    monkeypatch.setattr("app.services.client_intelligence._aggregate_reports", _capture)
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_delivery_confidence",
        AsyncMock(
            return_value=DeliveryConfidenceSummaryMetric(
                availability=SummaryMetricAvailability.AVAILABLE,
                average_score_pct=Decimal("85.00"),
                covered_project_count=2,
                eligible_project_count=2,
                limitations=[],
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_query_response",
        AsyncMock(
            return_value=QueryResponseSummaryMetric(
                availability=SummaryMetricAvailability.NO_DATA,
                average_latency_ms=None,
                sample_size=0,
                limitations=[],
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_csat",
        AsyncMock(
            return_value=CsatSummaryMetric(
                availability=SummaryMetricAvailability.NO_DATA,
                average_score=None,
                sample_size=0,
                scale_max=5,
                limitations=[],
            )
        ),
    )
    await build_client_intelligence_summary(session, delivery_manager)
    assert seen == [[PROJECT_A, PROJECT_B]]


@pytest.mark.asyncio
async def test_project_scoped_summary_authorizes_and_aggregates_only_that_project(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SummarySession()
    visible_project = _project(PROJECT_A)
    get_visible = AsyncMock(return_value=visible_project)
    seen: list[list[UUID]] = []

    async def _confidence(_session: Any, project_ids: list[UUID]):
        seen.append(list(project_ids))
        return DeliveryConfidenceSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            average_score_pct=Decimal("92.00"),
            covered_project_count=1,
            eligible_project_count=1,
            limitations=[],
        )

    async def _reports(_session: Any, project_ids: list[UUID]):
        seen.append(list(project_ids))
        return ReportsSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=[],
        )

    async def _query(_session: Any, project_ids: list[UUID]):
        seen.append(list(project_ids))
        return QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_latency_ms=None,
            sample_size=0,
            limitations=[],
        )

    async def _csat(_session: Any, project_ids: list[UUID]):
        seen.append(list(project_ids))
        return CsatSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=[],
        )

    monkeypatch.setattr("app.services.client_intelligence.get_visible_project", get_visible)
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_delivery_confidence",
        _confidence,
    )
    monkeypatch.setattr("app.services.client_intelligence._aggregate_reports", _reports)
    monkeypatch.setattr(
        "app.services.client_intelligence._aggregate_query_response",
        _query,
    )
    monkeypatch.setattr("app.services.client_intelligence._aggregate_csat", _csat)

    result = await build_client_intelligence_summary(
        session,
        delivery_manager,
        project_id=PROJECT_A,
    )

    get_visible.assert_awaited_once_with(session, PROJECT_A, delivery_manager)
    assert seen == [[PROJECT_A], [PROJECT_A], [PROJECT_A], [PROJECT_A]]
    assert result.authorized_project_count == 1


@pytest.mark.asyncio
async def test_delivery_confidence_uses_latest_score_per_authorized_project() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score_pct=Decimal("87.50"),
                covered_project_count=2,
                detected_project_count=2,
                invalid_project_count=0,
            )
        ]
    )
    result = await _aggregate_delivery_confidence(
        session,
        [PROJECT_A, PROJECT_B],
    )
    assert result.availability == SummaryMetricAvailability.AVAILABLE
    assert result.average_score_pct == Decimal("87.50")
    assert result.covered_project_count == 2
    assert result.eligible_project_count == 2
    assert result.limitations == []

    statement = session.executed[0]
    rendered = str(statement.compile())
    values = _compiled_values(statement)
    assert "delivery_confidence_scores.project_id IN" in rendered
    assert "row_number() OVER" in rendered
    assert "PARTITION BY delivery_confidence_scores.project_id" in rendered
    assert PROJECT_A in values
    assert PROJECT_B in values


@pytest.mark.asyncio
async def test_delivery_confidence_partial_coverage_is_truthful() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score_pct=Decimal("91.25"),
                covered_project_count=1,
                detected_project_count=1,
                invalid_project_count=0,
            )
        ]
    )
    result = await _aggregate_delivery_confidence(
        session,
        [PROJECT_A, PROJECT_B],
    )
    assert result.availability == SummaryMetricAvailability.PARTIAL
    assert result.average_score_pct == Decimal("91.25")
    assert result.covered_project_count == 1
    assert result.eligible_project_count == 2
    assert LIMITATION_DELIVERY_CONFIDENCE_COVERAGE_PARTIAL in result.limitations


@pytest.mark.asyncio
async def test_delivery_confidence_without_scores_is_no_data() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score_pct=None,
                covered_project_count=0,
                detected_project_count=0,
                invalid_project_count=0,
            )
        ]
    )
    result = await _aggregate_delivery_confidence(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.NO_DATA
    assert result.average_score_pct is None
    assert result.covered_project_count == 0
    assert result.eligible_project_count == 1


@pytest.mark.asyncio
async def test_report_lifecycle_counts() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                drafted_count=2,
                approved_count=3,
                eligible_record_count=5,
                sent_missing_approval=0,
            )
        ]
    )
    result = await _aggregate_reports(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.AVAILABLE
    assert result.drafted_count == 2
    assert result.approved_count == 3
    assert result.eligible_record_count == 5
    assert result.limitations == []


@pytest.mark.asyncio
async def test_report_query_filters_client_interaction_agent() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                drafted_count=0,
                approved_count=0,
                eligible_record_count=0,
                sent_missing_approval=0,
            )
        ]
    )
    await _aggregate_reports(session, [PROJECT_A])
    rendered = str(session.executed[0].compile())
    values = _compiled_values(session.executed[0])
    assert "client_communications" in rendered
    assert "client_communications.status !=" in rendered
    assert PROJECT_A in values
    assert CLIENT_INTERACTION_AGENT_NAME in values
    assert CommunicationStatus.REJECTED.value in values


@pytest.mark.asyncio
async def test_query_statement_retains_project_agent_and_non_null_scope() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_latency_ms=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            )
        ]
    )
    await _aggregate_query_response(session, [PROJECT_A, PROJECT_B])
    statement = session.executed[0]
    rendered = str(statement.compile())
    values = _compiled_values(statement)
    assert "agent_queries.project_id IN" in rendered
    assert "agent_queries.agent_name =" in rendered
    assert "agent_queries.project_id IS NOT NULL" in rendered
    assert PROJECT_A in values
    assert PROJECT_B in values
    assert CLIENT_INTERACTION_AGENT_NAME in values


@pytest.mark.asyncio
async def test_csat_statement_retains_authorized_project_scope() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            )
        ]
    )
    await _aggregate_csat(session, [PROJECT_B])
    statement = session.executed[0]
    rendered = str(statement.compile())
    values = _compiled_values(statement)
    assert "client_csat_scores.project_id IN" in rendered
    assert PROJECT_B in values
    assert PROJECT_A not in values


def test_scoped_project_query_excludes_deleted_projects(
    delivery_manager: CurrentUser,
) -> None:
    statement = scoped_project_query(delivery_manager)
    rendered = str(statement.compile())
    values = _compiled_values(statement)
    assert "projects.deleted_at IS NULL" in rendered
    assert "projects.org_id =" in rendered
    assert delivery_manager.org_id in values


@pytest.mark.asyncio
async def test_narrowed_project_set_reaches_all_real_aggregate_statements(
    delivery_manager: CurrentUser,
) -> None:
    session = SummarySession(
        results=[
            [_project(PROJECT_B)],
            SimpleNamespace(
                average_score_pct=Decimal("88.00"),
                covered_project_count=1,
                detected_project_count=1,
                invalid_project_count=0,
            ),
            SimpleNamespace(
                drafted_count=0,
                approved_count=0,
                eligible_record_count=0,
                sent_missing_approval=0,
            ),
            SimpleNamespace(
                average_latency_ms=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            ),
            SimpleNamespace(
                average_score=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            ),
        ]
    )
    result = await build_client_intelligence_summary(session, delivery_manager)
    assert result.authorized_project_count == 1
    assert len(session.executed) == 5
    for statement in session.executed[1:]:
        values = _compiled_values(statement)
        assert PROJECT_B in values
        assert PROJECT_A not in values


@pytest.mark.asyncio
async def test_report_sent_missing_approval_is_partial() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                drafted_count=0,
                approved_count=1,
                eligible_record_count=1,
                sent_missing_approval=1,
            )
        ]
    )
    result = await _aggregate_reports(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.PARTIAL
    assert LIMITATION_REPORT_SENT_APPROVAL_PROVENANCE_INCOMPLETE in result.limitations


@pytest.mark.asyncio
async def test_query_latency_average_and_sample_size() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_latency_ms=850.4,
                sample_size=2,
                detected_count=2,
                invalid_count=0,
            )
        ]
    )
    result = await _aggregate_query_response(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.AVAILABLE
    assert result.average_latency_ms == 850
    assert result.sample_size == 2


@pytest.mark.asyncio
async def test_query_excludes_invalid_rows_and_marks_partial() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_latency_ms=1000.0,
                sample_size=1,
                detected_count=3,
                invalid_count=2,
            )
        ]
    )
    result = await _aggregate_query_response(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.PARTIAL
    assert result.average_latency_ms == 1000
    assert result.sample_size == 1
    assert LIMITATION_QUERY_LATENCY_MISSING_OR_INVALID in result.limitations


@pytest.mark.asyncio
async def test_query_empty_dataset_is_no_data() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_latency_ms=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            )
        ]
    )
    result = await _aggregate_query_response(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.NO_DATA
    assert result.average_latency_ms is None
    assert result.sample_size == 0


@pytest.mark.asyncio
async def test_csat_average_and_sample_size() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score=Decimal("4.55"),
                sample_size=2,
                detected_count=2,
                invalid_count=0,
            )
        ]
    )
    result = await _aggregate_csat(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.AVAILABLE
    assert result.average_score == Decimal("4.6")
    assert result.sample_size == 2
    assert result.scale_max == 5


@pytest.mark.asyncio
async def test_csat_empty_dataset_is_no_data() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score=None,
                sample_size=0,
                detected_count=0,
                invalid_count=0,
            )
        ]
    )
    result = await _aggregate_csat(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.NO_DATA
    assert result.average_score is None


@pytest.mark.asyncio
async def test_csat_invalid_rows_are_partial() -> None:
    session = SummarySession(
        results=[
            SimpleNamespace(
                average_score=Decimal("4.0"),
                sample_size=1,
                detected_count=2,
                invalid_count=1,
            )
        ]
    )
    result = await _aggregate_csat(session, [PROJECT_A])
    assert result.availability == SummaryMetricAvailability.PARTIAL
    assert LIMITATION_CSAT_SCORE_OUT_OF_RANGE in result.limitations


def test_model_rejects_invented_no_data_values() -> None:
    with pytest.raises(ValidationError):
        ReportsSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            drafted_count=1,
            approved_count=0,
            eligible_record_count=1,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.NO_DATA,
            average_latency_ms=10,
            sample_size=1,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        CsatSummaryMetric(
            availability=SummaryMetricAvailability.UNAVAILABLE,
            average_score=Decimal("4.0"),
            sample_size=1,
            scale_max=5,
            limitations=[],
        )


def test_model_rejects_out_of_range_and_negative_values() -> None:
    with pytest.raises(ValidationError):
        QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            average_latency_ms=-1,
            sample_size=1,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        CsatSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            average_score=Decimal("5.1"),
            sample_size=1,
            scale_max=5,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        ReportsSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            drafted_count=3,
            approved_count=3,
            eligible_record_count=5,
            limitations=[],
        )


def test_available_metrics_require_positive_calculated_populations() -> None:
    with pytest.raises(ValidationError):
        ReportsSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            average_latency_ms=None,
            sample_size=0,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        CsatSummaryMetric(
            availability=SummaryMetricAvailability.AVAILABLE,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=[],
        )


def test_partial_without_calculation_requires_limitation() -> None:
    with pytest.raises(ValidationError):
        ReportsSummaryMetric(
            availability=SummaryMetricAvailability.PARTIAL,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.PARTIAL,
            average_latency_ms=None,
            sample_size=0,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        CsatSummaryMetric(
            availability=SummaryMetricAvailability.PARTIAL,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=[],
        )


def test_unavailable_metrics_require_deterministic_limitation() -> None:
    with pytest.raises(ValidationError):
        ReportsSummaryMetric(
            availability=SummaryMetricAvailability.UNAVAILABLE,
            drafted_count=0,
            approved_count=0,
            eligible_record_count=0,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        QueryResponseSummaryMetric(
            availability=SummaryMetricAvailability.UNAVAILABLE,
            average_latency_ms=None,
            sample_size=0,
            limitations=[],
        )
    with pytest.raises(ValidationError):
        CsatSummaryMetric(
            availability=SummaryMetricAvailability.UNAVAILABLE,
            average_score=None,
            sample_size=0,
            scale_max=5,
            limitations=[],
        )


def test_limitations_are_trimmed_unique_and_canonically_ordered() -> None:
    metric = QueryResponseSummaryMetric(
        availability=SummaryMetricAvailability.PARTIAL,
        average_latency_ms=100,
        sample_size=1,
        limitations=[" Z_REASON ", "A_REASON", "Z_REASON"],
    )
    assert metric.limitations == ["A_REASON", "Z_REASON"]


def test_summary_serialization_is_deterministic_and_privacy_safe() -> None:
    left = ClientIntelligenceSummaryRead.model_validate(_summary_payload())
    right = ClientIntelligenceSummaryRead.model_validate(_summary_payload())
    assert left.model_dump(mode="json") == right.model_dump(mode="json")
    payload = left.model_dump(mode="json")
    assert payload["reports"]["limitations"] == []
    assert "comment" not in str(payload)
    assert "submitted_by" not in str(payload)
    assert "user_id" not in str(payload)


@pytest.mark.asyncio
async def test_summary_service_is_read_only(delivery_manager: CurrentUser) -> None:
    session = SummarySession(results=[[]])
    await build_client_intelligence_summary(session, delivery_manager)
    assert session.add_calls == 0
    assert session.commit_calls == 0
    assert session.flush_calls == 0
