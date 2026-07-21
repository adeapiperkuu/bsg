"""Focused tests for the live Client Master project navigator."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.main import app
from app.schemas.client_intelligence import (
    ClientMasterHealthAvailability,
    ClientMasterRowRead,
)
from app.services import client_intelligence as client_intelligence_service
from app.services.client_intelligence import build_client_master
from tests.conftest import FakeResult, FakeSession, override_user

MASTER_PATH = "/api/v1/client-intelligence/master"
PROJECT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class MasterResult(FakeResult):
    def all(self) -> list[Any]:
        return list(self._items)


class MasterSession(FakeSession):
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.executed: list[Any] = []

    async def execute(
        self,
        statement: Any = None,
        *_args: Any,
        **_kwargs: Any,
    ) -> MasterResult:
        self.executed.append(statement)
        return MasterResult(items=self.rows)


def _row() -> ClientMasterRowRead:
    return ClientMasterRowRead(
        project_id=PROJECT_ID,
        project_name="Northwind Content Shield",
        health_status=None,
        health_availability=ClientMasterHealthAvailability.NOT_ASSESSED,
        confidence_score_pct=Decimal("97.02"),
        last_report_at=datetime(2026, 7, 16, 10, 30, tzinfo=UTC),
        next_milestone_date=date(2026, 8, 15),
        csat_average=Decimal("4.5"),
        csat_sample_size=3,
        draft_count=1,
    )


@pytest.fixture
def bsg_leadership(delivery_manager: CurrentUser) -> CurrentUser:
    return CurrentUser(
        id=delivery_manager.id,
        org_id=delivery_manager.org_id,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


def test_openapi_registers_client_master_route_once() -> None:
    schema = app.openapi()
    assert MASTER_PATH in schema["paths"]
    assert list(schema["paths"][MASTER_PATH].keys()) == ["get"]


@pytest.mark.asyncio
async def test_client_master_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get(MASTER_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_client_role_cannot_read_internal_master(
    api_client: AsyncClient,
    client_a: CurrentUser,
) -> None:
    override_user(client_a)
    response = await api_client.get(MASTER_PATH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_fixture",
    ["delivery_manager", "bsg_leadership", "super_admin"],
)
async def test_internal_roles_receive_live_master_rows(
    api_client: AsyncClient,
    user_fixture: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(request.getfixturevalue(user_fixture))

    async def _master(*_args: Any, **_kwargs: Any) -> list[ClientMasterRowRead]:
        return [_row()]

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_master",
        _master,
    )
    response = await api_client.get(MASTER_PATH)
    assert response.status_code == 200
    body = response.json()["data"][0]
    assert body["project_id"] == str(PROJECT_ID)
    assert body["health_status"] is None
    assert body["health_availability"] == "not_assessed"
    assert body["confidence_score_pct"] == "97.02"
    assert body["csat_average"] == "4.5"
    assert body["draft_count"] == 1


@pytest.mark.asyncio
async def test_master_service_maps_one_aggregate_query(
    delivery_manager: CurrentUser,
) -> None:
    session = MasterSession(
        [
            SimpleNamespace(
                project_id=PROJECT_ID,
                project_name="Northwind Content Shield",
                confidence_score_pct=Decimal("97.019"),
                last_report_at=datetime(2026, 7, 16, 10, 30, tzinfo=UTC),
                next_milestone_date=date(2026, 8, 15),
                csat_average=Decimal("4.466"),
                csat_sample_size=3,
                draft_count=1,
            )
        ]
    )
    rows = await build_client_master(session, delivery_manager)
    assert len(session.executed) == 1
    compiled = str(session.executed[0]).lower()
    assert "health_status" not in compiled
    assert rows == [
        ClientMasterRowRead(
            project_id=PROJECT_ID,
            project_name="Northwind Content Shield",
            health_status=None,
            health_availability=ClientMasterHealthAvailability.NOT_ASSESSED,
            confidence_score_pct=Decimal("97.02"),
            last_report_at=datetime(2026, 7, 16, 10, 30, tzinfo=UTC),
            next_milestone_date=date(2026, 8, 15),
            csat_average=Decimal("4.5"),
            csat_sample_size=3,
            draft_count=1,
        )
    ]


@pytest.mark.asyncio
async def test_master_health_never_sourced_from_delivery_confidence_status(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confidence score remains Delivery-owned; Health stays not_assessed."""
    overview_calls = {"count": 0}
    health_calls = {"count": 0}
    pack_calls = {"count": 0}

    async def _forbidden_overview(*_args: Any, **_kwargs: Any) -> Any:
        overview_calls["count"] += 1
        raise AssertionError("build_client_master must not call overview")

    def _forbidden_health(*_args: Any, **_kwargs: Any) -> Any:
        health_calls["count"] += 1
        raise AssertionError("build_client_master must not assess project health")

    async def _forbidden_pack(*_args: Any, **_kwargs: Any) -> Any:
        pack_calls["count"] += 1
        raise AssertionError("build_client_master must not build evidence packs")

    monkeypatch.setattr(
        client_intelligence_service,
        "build_client_intelligence_overview",
        _forbidden_overview,
    )
    monkeypatch.setattr(
        client_intelligence_service,
        "assess_project_health",
        _forbidden_health,
    )
    monkeypatch.setattr(
        client_intelligence_service,
        "build_client_evidence_pack",
        _forbidden_pack,
    )

    session = MasterSession(
        [
            SimpleNamespace(
                project_id=PROJECT_ID,
                project_name="Northwind Content Shield",
                # Former defect: DeliveryConfidenceScore.status = on_track was
                # mapped into health_status. Service must ignore that source.
                confidence_score_pct=Decimal("88.50"),
                last_report_at=None,
                next_milestone_date=None,
                csat_average=None,
                csat_sample_size=0,
                draft_count=0,
            )
        ]
    )
    rows = await build_client_master(session, delivery_manager)
    assert len(session.executed) == 1
    assert overview_calls["count"] == 0
    assert health_calls["count"] == 0
    assert pack_calls["count"] == 0
    assert len(rows) == 1
    assert rows[0].health_status is None
    assert rows[0].health_availability == ClientMasterHealthAvailability.NOT_ASSESSED
    assert rows[0].confidence_score_pct == Decimal("88.50")


def test_master_row_rejects_invented_health_states() -> None:
    with pytest.raises(ValidationError):
        ClientMasterRowRead(
            project_id=PROJECT_ID,
            project_name="Northwind Content Shield",
            health_status="on_track",  # type: ignore[arg-type]
            health_availability=ClientMasterHealthAvailability.NOT_ASSESSED,
            confidence_score_pct=Decimal("97.02"),
            csat_sample_size=0,
            draft_count=0,
        )
    with pytest.raises(ValidationError):
        ClientMasterRowRead(
            project_id=PROJECT_ID,
            project_name="Northwind Content Shield",
            health_status="at_risk",  # type: ignore[arg-type]
            health_availability=ClientMasterHealthAvailability.NOT_ASSESSED,
            confidence_score_pct=None,
            csat_sample_size=0,
            draft_count=0,
        )
    with pytest.raises(ValidationError):
        ClientMasterRowRead(
            project_id=PROJECT_ID,
            project_name="Northwind Content Shield",
            health_status="green",
            health_availability=ClientMasterHealthAvailability.NOT_ASSESSED,
            confidence_score_pct=None,
            csat_sample_size=0,
            draft_count=0,
        )


def test_master_row_rejects_unknown_health_availability() -> None:
    with pytest.raises(ValidationError):
        ClientMasterRowRead(
            project_id=PROJECT_ID,
            project_name="Northwind Content Shield",
            health_status=None,
            health_availability="available",  # type: ignore[arg-type]
            confidence_score_pct=None,
            csat_sample_size=0,
            draft_count=0,
        )
