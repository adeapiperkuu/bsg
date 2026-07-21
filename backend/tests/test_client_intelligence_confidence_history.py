"""Focused tests for project-scoped Delivery Confidence history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.security import CurrentUser
from app.db.models import AppRole, MilestoneStatus
from app.main import app
from app.schemas.client_intelligence import (
    DeliveryConfidenceCurrentScoreAvailability,
    DeliveryConfidenceHistoryAvailability,
    DeliveryConfidenceHistoryPoint,
    DeliveryConfidenceHistoryRead,
)
from app.services import client_intelligence as client_intelligence_service
from app.services.client_intelligence import (
    DELIVERY_CONFIDENCE_HISTORY_LIMIT,
    LIMITATION_DELIVERY_CONFIDENCE_HISTORY_TRUNCATED,
    LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE,
    LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE,
    build_delivery_confidence_history,
)
from tests.conftest import FakeResult, FakeSession, override_user

PROJECT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_PROJECT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
HISTORY_PATH = (
    "/api/v1/projects/{project_id}/client-intelligence/delivery-confidence-history"
)
HISTORY_PATH_CONCRETE = (
    f"/api/v1/projects/{PROJECT_ID}/client-intelligence/delivery-confidence-history"
)


class HistoryResult(FakeResult):
    def __init__(
        self,
        *,
        items: list[Any] | None = None,
        one_row: Any | None = None,
        scalars_items: list[Any] | None = None,
        scalar_value: Any = None,
    ) -> None:
        super().__init__(value=scalar_value, items=items or [])
        self._one_row = one_row
        self._scalars_items = scalars_items

    def one(self) -> Any:
        if self._one_row is not None:
            return self._one_row
        return super().one()

    def scalars(self) -> Any:
        if self._scalars_items is not None:
            return SimpleNamespace(all=lambda: list(self._scalars_items))
        return super().scalars()


class HistorySession(FakeSession):
    """Queues count, canonical latest, then optional valid-point results."""

    def __init__(self, queue: list[HistoryResult]) -> None:
        self.queue = list(queue)
        self.executed: list[Any] = []

    async def execute(
        self,
        statement: Any = None,
        *_args: Any,
        **_kwargs: Any,
    ) -> HistoryResult:
        self.executed.append(statement)
        if not self.queue:
            raise AssertionError("unexpected execute with empty result queue")
        return self.queue.pop(0)


def _score_row(
    *,
    score: str,
    created_at: datetime,
    row_id: UUID | None = None,
    project_id: UUID = PROJECT_ID,
    status: MilestoneStatus = MilestoneStatus.ON_TRACK,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id or uuid4(),
        project_id=project_id,
        milestone_id=uuid4(),
        score_pct=Decimal(score),
        status=status,
        created_at=created_at,
    )


def _counts(*, total: int, valid: int, invalid: int) -> HistoryResult:
    return HistoryResult(
        one_row=SimpleNamespace(
            total_rows=total, valid_count=valid, invalid_count=invalid
        )
    )


def _latest(row: Any) -> HistoryResult:
    return HistoryResult(scalar_value=row)


def _points(rows: list[Any]) -> HistoryResult:
    return HistoryResult(scalars_items=rows)


@pytest.fixture
def bsg_leadership(delivery_manager: CurrentUser) -> CurrentUser:
    return CurrentUser(
        id=delivery_manager.id,
        org_id=delivery_manager.org_id,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


def test_openapi_registers_confidence_history_route_once() -> None:
    schema = app.openapi()
    assert HISTORY_PATH in schema["paths"]
    assert list(schema["paths"][HISTORY_PATH].keys()) == ["get"]


@pytest.mark.asyncio
async def test_confidence_history_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get(HISTORY_PATH_CONCRETE)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_client_role_cannot_read_confidence_history(
    api_client: AsyncClient,
    client_a: CurrentUser,
) -> None:
    override_user(client_a)
    response = await api_client.get(HISTORY_PATH_CONCRETE)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_fixture",
    ["delivery_manager", "bsg_leadership", "super_admin"],
)
async def test_internal_roles_receive_confidence_history(
    api_client: AsyncClient,
    user_fixture: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(request.getfixturevalue(user_fixture))
    point_id = uuid4()
    point = DeliveryConfidenceHistoryPoint(
        source_row_id=point_id,
        project_id=PROJECT_ID,
        milestone_id=uuid4(),
        score_pct=Decimal("88.50"),
        confidence_status="on_track",
        observed_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )

    async def _history(*_args: Any, **_kwargs: Any) -> DeliveryConfidenceHistoryRead:
        return DeliveryConfidenceHistoryRead(
            project_id=PROJECT_ID,
            availability=DeliveryConfidenceHistoryAvailability.AVAILABLE,
            points=[point],
            returned_point_count=1,
            total_valid_point_count=1,
            limitations=[],
            current_score_availability=DeliveryConfidenceCurrentScoreAvailability.AVAILABLE,
            current_source_row_id=point_id,
            latest_history_point_is_current=True,
        )

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_delivery_confidence_history",
        _history,
    )
    response = await api_client.get(HISTORY_PATH_CONCRETE)
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["project_id"] == str(PROJECT_ID)
    assert body["availability"] == "available"
    assert body["latest_history_point_is_current"] is True
    assert body["current_score_availability"] == "available"
    assert body["points"][0]["score_pct"] == "88.50"


@pytest.mark.asyncio
async def test_unauthorized_project_is_rejected(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)

    async def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        from app.core.exceptions import ApiError

        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    monkeypatch.setattr(
        "app.services.client_intelligence.get_visible_project",
        _forbidden,
    )
    response = await api_client.get(HISTORY_PATH_CONCRETE)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_history_service_returns_only_project_valid_points(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    older_id = UUID("11111111-1111-4111-8111-111111111111")
    newer_id = UUID("22222222-2222-4222-8222-222222222222")
    newer = _score_row(
        score="90.00", created_at=base + timedelta(days=2), row_id=newer_id
    )
    older = _score_row(score="80.25", created_at=base, row_id=older_id)
    session = HistorySession(
        [
            _counts(total=2, valid=2, invalid=0),
            _latest(newer),
            _points([newer, older]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    overview_calls = {"count": 0}
    pack_calls = {"count": 0}

    async def _no_overview(*_args: Any, **_kwargs: Any) -> Any:
        overview_calls["count"] += 1
        raise AssertionError("history must not build overview")

    async def _no_pack(*_args: Any, **_kwargs: Any) -> Any:
        pack_calls["count"] += 1
        raise AssertionError("history must not build evidence pack")

    monkeypatch.setattr(
        client_intelligence_service,
        "build_client_intelligence_overview",
        _no_overview,
    )
    monkeypatch.setattr(
        client_intelligence_service,
        "build_client_evidence_pack",
        _no_pack,
    )

    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert len(session.executed) == 3
    assert overview_calls["count"] == 0
    assert pack_calls["count"] == 0
    assert result.availability == DeliveryConfidenceHistoryAvailability.AVAILABLE
    assert result.returned_point_count == 2
    assert result.current_score_availability == (
        DeliveryConfidenceCurrentScoreAvailability.AVAILABLE
    )
    assert result.current_source_row_id == newer_id
    assert result.latest_history_point_is_current is True
    assert [point.score_pct for point in result.points] == [
        Decimal("80.25"),
        Decimal("90.00"),
    ]


@pytest.mark.asyncio
async def test_empty_history_returns_no_data_and_missing_current(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = HistorySession([_counts(total=0, valid=0, invalid=0)])

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert len(session.executed) == 1
    assert result.availability == DeliveryConfidenceHistoryAvailability.NO_DATA
    assert result.current_score_availability == (
        DeliveryConfidenceCurrentScoreAvailability.MISSING
    )
    assert result.current_source_row_id is None
    assert result.latest_history_point_is_current is False
    assert result.points == []


@pytest.mark.asyncio
async def test_newest_valid_marks_history_point_as_current(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    latest_valid = _score_row(
        score="91.10",
        created_at=base + timedelta(days=1),
        status=MilestoneStatus.AT_RISK,
    )
    older = _score_row(score="70.00", created_at=base)
    session = HistorySession(
        [
            _counts(total=2, valid=2, invalid=0),
            _latest(latest_valid),
            _points([latest_valid, older]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert result.points[-1].source_row_id == latest_valid.id
    assert result.current_source_row_id == latest_valid.id
    assert result.latest_history_point_is_current is True
    assert result.current_score_availability == (
        DeliveryConfidenceCurrentScoreAvailability.AVAILABLE
    )


@pytest.mark.asyncio
async def test_newest_invalid_keeps_older_history_non_current(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    older_valid = _score_row(score="80.00", created_at=base)
    newest_invalid = _score_row(
        score="150.00", created_at=base + timedelta(days=1)
    )
    session = HistorySession(
        [
            _counts(total=2, valid=1, invalid=1),
            _latest(newest_invalid),
            _points([older_valid]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert result.availability == DeliveryConfidenceHistoryAvailability.PARTIAL
    assert result.current_score_availability == (
        DeliveryConfidenceCurrentScoreAvailability.INVALID
    )
    assert result.current_source_row_id == newest_invalid.id
    assert result.latest_history_point_is_current is False
    assert [point.score_pct for point in result.points] == [Decimal("80.00")]
    assert all(point.score_pct <= Decimal("100") for point in result.points)
    assert (
        LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE in result.limitations
    )
    assert LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE in result.limitations


@pytest.mark.asyncio
async def test_all_rows_invalid_returns_no_points(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    newest_invalid = _score_row(
        score="-5.00",
        created_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )
    session = HistorySession(
        [
            _counts(total=2, valid=0, invalid=2),
            _latest(newest_invalid),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert len(session.executed) == 2
    assert result.points == []
    assert result.returned_point_count == 0
    assert result.availability == DeliveryConfidenceHistoryAvailability.PARTIAL
    assert result.current_score_availability == (
        DeliveryConfidenceCurrentScoreAvailability.INVALID
    )
    assert result.current_source_row_id == newest_invalid.id
    assert result.latest_history_point_is_current is False
    assert (
        LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE in result.limitations
    )


@pytest.mark.asyncio
async def test_invalid_scores_excluded_as_partial(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    valid = _score_row(score="72.50", created_at=base)
    session = HistorySession(
        [
            _counts(total=3, valid=1, invalid=2),
            _latest(valid),
            _points([valid]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert result.availability == DeliveryConfidenceHistoryAvailability.PARTIAL
    assert result.latest_history_point_is_current is True
    assert LIMITATION_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE in result.limitations


@pytest.mark.asyncio
async def test_truncated_history_returns_most_recent_partial(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    latest = _score_row(score="95.00", created_at=base + timedelta(days=4))
    previous = _score_row(score="90.00", created_at=base + timedelta(days=3))
    session = HistorySession(
        [
            _counts(total=5, valid=5, invalid=0),
            _latest(latest),
            _points([latest, previous]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID, limit=2
    )
    assert result.availability == DeliveryConfidenceHistoryAvailability.PARTIAL
    assert result.latest_history_point_is_current is True
    assert result.returned_point_count == 2
    assert result.total_valid_point_count == 5
    assert LIMITATION_DELIVERY_CONFIDENCE_HISTORY_TRUNCATED in result.limitations


@pytest.mark.asyncio
async def test_points_ordered_chronologically_with_uuid_tiebreak(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    same_time = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    lower_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    higher_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    higher = _score_row(score="70.00", created_at=same_time, row_id=higher_id)
    lower = _score_row(score="60.00", created_at=same_time, row_id=lower_id)
    session = HistorySession(
        [
            _counts(total=2, valid=2, invalid=0),
            _latest(higher),
            _points([higher, lower]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert [point.source_row_id for point in result.points] == [lower_id, higher_id]
    assert result.latest_history_point_is_current is True


@pytest.mark.asyncio
async def test_decimal_precision_preserved(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _score_row(
        score="87.65",
        created_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )
    session = HistorySession(
        [
            _counts(total=1, valid=1, invalid=0),
            _latest(row),
            _points([row]),
        ]
    )

    async def _visible(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(id=PROJECT_ID)

    monkeypatch.setattr(
        client_intelligence_service, "get_visible_project", _visible
    )
    result = await build_delivery_confidence_history(
        session, delivery_manager, PROJECT_ID
    )
    assert result.points[0].score_pct == Decimal("87.65")
    assert str(result.points[0].score_pct) == "87.65"


def test_naive_observed_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DeliveryConfidenceHistoryPoint(
            source_row_id=uuid4(),
            project_id=PROJECT_ID,
            milestone_id=uuid4(),
            score_pct=Decimal("50.00"),
            confidence_status="on_track",
            observed_at=datetime(2026, 7, 15, 12, 0),
        )


def test_history_contract_rejects_invalid_combinations() -> None:
    point_id = uuid4()
    point = DeliveryConfidenceHistoryPoint(
        source_row_id=point_id,
        project_id=PROJECT_ID,
        milestone_id=uuid4(),
        score_pct=Decimal("50.00"),
        confidence_status="on_track",
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        DeliveryConfidenceHistoryRead(
            project_id=PROJECT_ID,
            availability=DeliveryConfidenceHistoryAvailability.AVAILABLE,
            points=[point],
            returned_point_count=1,
            total_valid_point_count=1,
            limitations=["SHOULD_NOT_BE_HERE"],
            current_score_availability=DeliveryConfidenceCurrentScoreAvailability.AVAILABLE,
            current_source_row_id=point_id,
            latest_history_point_is_current=True,
        )
    with pytest.raises(ValidationError):
        DeliveryConfidenceHistoryRead(
            project_id=PROJECT_ID,
            availability=DeliveryConfidenceHistoryAvailability.PARTIAL,
            points=[point],
            returned_point_count=1,
            total_valid_point_count=1,
            limitations=[LIMITATION_LATEST_DELIVERY_CONFIDENCE_SCORE_OUT_OF_RANGE],
            current_score_availability=DeliveryConfidenceCurrentScoreAvailability.INVALID,
            current_source_row_id=uuid4(),
            latest_history_point_is_current=True,
        )
    with pytest.raises(ValidationError):
        DeliveryConfidenceHistoryRead(
            project_id=PROJECT_ID,
            availability=DeliveryConfidenceHistoryAvailability.NO_DATA,
            points=[],
            returned_point_count=0,
            total_valid_point_count=0,
            limitations=[],
            current_score_availability=DeliveryConfidenceCurrentScoreAvailability.MISSING,
            current_source_row_id=None,
            latest_history_point_is_current=True,
        )


def test_history_limit_constant_is_bounded() -> None:
    assert DELIVERY_CONFIDENCE_HISTORY_LIMIT == 30
