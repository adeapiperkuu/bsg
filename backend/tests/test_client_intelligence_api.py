"""API and service tests for the internal Client Intelligence overview endpoint."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.agents.client_intelligence import (
    ClientEvidencePack,
    EvidencePackValidationResult,
    EvidenceVisibility,
    assess_delivery_confidence,
    assess_delivery_trend,
    assess_project_health,
    assess_risk_transparency,
)
from app.agents.client_intelligence.delivery_trend_contracts import (
    LIMITATION_DEVIATION_POLICY_UNAVAILABLE,
    LIMITATION_PLAN_SERIES_UNAVAILABLE,
)
from app.agents.client_intelligence.evidence_validation import EvidencePackIntegrityError
from app.agents.client_intelligence.health_contracts import ProjectHealthStatus
from app.agents.client_intelligence.project_health import LIMITATION_POLICY_UNAVAILABLE
from app.agents.client_intelligence.risk_transparency_contracts import (
    LIMITATION_RISK_POLICY_UNAVAILABLE,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, Project
from app.main import app
from app.services.client_intelligence import (
    build_client_intelligence_overview,
    resolve_effective_as_of,
)
from tests.conftest import ORG_A, FakeSession, override_user
from tests.test_client_intelligence_delivery_confidence import (
    _complete_pack,
    _with_domain_facts,
)
from tests.test_client_intelligence_project_health import _base_pack

PROJECT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_OVERVIEW_PATH = f"/api/v1/projects/{PROJECT_ID}/client-intelligence/overview"


def _overview_ready_pack() -> ClientEvidencePack:
    return _with_domain_facts(_complete_pack(), throughput=True)


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


class TrackingSession(FakeSession):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.add_calls = 0
        self.commit_calls = 0
        self.flush_calls = 0

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        self.add_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def flush(self) -> None:
        self.flush_calls += 1


def _project(org_id: UUID = ORG_A) -> Project:
    return Project(
        id=PROJECT_ID,
        org_id=org_id,
        name="Aurora",
        status="active",
        description="internal",
    )


def _overview_from_pack(pack: ClientEvidencePack):
    return {
        "project": pack.project,
        "reporting_period": pack.reporting_period,
        "as_of": pack.reporting_period.as_of,
        "generated_at": pack.generated_at,
        "visibility_mode": pack.visibility_mode,
        "source_fingerprint": pack.source_fingerprint,
        "overall_data_quality": pack.overall_data_quality,
        "data_quality": pack.data_quality,
        "source_limitations": list(pack.limitations),
        "visibility_limitations": pack.visibility_limitations,
        "project_health": assess_project_health(pack, policy=None),
        "delivery_confidence": assess_delivery_confidence(pack, explanation_policy=None),
        "risk_transparency": assess_risk_transparency(pack, policy=None),
        "delivery_trend": assess_delivery_trend(pack, policy=None),
    }


def test_openapi_registers_overview_route_once() -> None:
    schema = app.openapi()
    path = "/api/v1/projects/{project_id}/client-intelligence/overview"
    assert path in schema["paths"]
    get_ops = schema["paths"][path]
    assert list(get_ops.keys()) == ["get"]
    response_schema = (
        get_ops["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert "ClientIntelligenceOverviewRead" in str(response_schema)


@pytest.mark.asyncio
async def test_overview_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get(_OVERVIEW_PATH)
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
        "app.api.routes.client_intelligence.build_client_intelligence_overview",
        _forbidden,
    )
    response = await api_client.get(_OVERVIEW_PATH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_fixture",
    ["delivery_manager", "bsg_leadership", "super_admin"],
)
async def test_allowed_roles_receive_200(
    api_client: AsyncClient,
    user_fixture: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = request.getfixturevalue(user_fixture)
    override_user(user)
    pack = _overview_ready_pack()
    overview = _overview_from_pack(pack)

    async def _overview(*_args: Any, **_kwargs: Any):
        from app.schemas.client_intelligence import ClientIntelligenceOverviewRead

        return ClientIntelligenceOverviewRead(**overview)

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_overview",
        _overview,
    )
    response = await api_client.get(_OVERVIEW_PATH)
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["project"]["project_id"] == str(pack.project.project_id)
    assert body["project_health"]["status"] == ProjectHealthStatus.INSUFFICIENT.value
    assert body["delivery_confidence"]["org_id"] == str(pack.project.org_id)
    assert body["risk_transparency"]["source_fingerprint"] == pack.source_fingerprint
    assert body["delivery_trend"]["source_fingerprint"] == pack.source_fingerprint
    assert "evidence" not in body
    assert "delivery" not in body
    assert "knowledge" not in body


@pytest.mark.asyncio
async def test_missing_project_returns_404(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)

    async def _missing(*_args: Any, **_kwargs: Any):
        raise ApiError(404, "NOT_FOUND", "Project was not found.", {"project_id": str(PROJECT_ID)})

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_overview",
        _missing,
    )
    response = await api_client.get(_OVERVIEW_PATH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cross_org_access_returns_403(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(delivery_manager)

    async def _forbidden(*_args: Any, **_kwargs: Any):
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    monkeypatch.setattr(
        "app.api.routes.client_intelligence.build_client_intelligence_overview",
        _forbidden,
    )
    response = await api_client.get(_OVERVIEW_PATH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_malformed_as_of_returns_422(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(_OVERVIEW_PATH, params={"as_of": "not-a-date"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_future_as_of_rejected(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(_OVERVIEW_PATH, params={"as_of": "2099-01-01"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FUTURE_AS_OF_NOT_ALLOWED"


def test_resolve_effective_as_of_defaults_to_today_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.client_intelligence.datetime",
        type(
            "Frozen",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
                )
            },
        ),
    )
    assert resolve_effective_as_of(None) == date(2026, 6, 18)


@pytest.mark.asyncio
async def test_service_builds_pack_once_and_passes_as_of(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _overview_ready_pack()
    build_mock = AsyncMock(return_value=pack)
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        build_mock,
    )
    session = TrackingSession()
    effective = date(2026, 6, 17)
    await build_client_intelligence_overview(
        session,
        delivery_manager,
        pack.project.project_id,
        as_of=effective,
    )
    build_mock.assert_awaited_once()
    assert build_mock.await_args.kwargs["as_of"] == effective
    assert build_mock.await_args.kwargs["visibility_mode"] == EvidenceVisibility.INTERNAL


@pytest.mark.asyncio
async def test_service_engines_receive_same_pack_instance(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _overview_ready_pack()
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(return_value=pack),
    )
    seen: list[int] = []

    def _wrap(fn):
        def _inner(p: ClientEvidencePack, **kwargs: Any):
            seen.append(id(p))
            return fn(p, **kwargs)

        return _inner

    monkeypatch.setattr(
        "app.services.client_intelligence.assess_project_health",
        _wrap(assess_project_health),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence.assess_delivery_confidence",
        _wrap(assess_delivery_confidence),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence.assess_risk_transparency",
        _wrap(assess_risk_transparency),
    )
    monkeypatch.setattr(
        "app.services.client_intelligence.assess_delivery_trend",
        _wrap(assess_delivery_trend),
    )
    await build_client_intelligence_overview(
        TrackingSession(),
        delivery_manager,
        pack.project.project_id,
    )
    assert len(seen) == 4
    assert len(set(seen)) == 1
    assert seen[0] == id(pack)


@pytest.mark.asyncio
async def test_service_calls_engines_without_policies(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _overview_ready_pack()
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(return_value=pack),
    )
    from unittest.mock import MagicMock

    health = MagicMock(side_effect=lambda p, **kw: assess_project_health(p, **kw))
    confidence = MagicMock(side_effect=lambda p, **kw: assess_delivery_confidence(p, **kw))
    risk = MagicMock(side_effect=lambda p, **kw: assess_risk_transparency(p, **kw))
    trend = MagicMock(side_effect=lambda p, **kw: assess_delivery_trend(p, **kw))
    monkeypatch.setattr("app.services.client_intelligence.assess_project_health", health)
    monkeypatch.setattr(
        "app.services.client_intelligence.assess_delivery_confidence", confidence
    )
    monkeypatch.setattr("app.services.client_intelligence.assess_risk_transparency", risk)
    monkeypatch.setattr("app.services.client_intelligence.assess_delivery_trend", trend)

    await build_client_intelligence_overview(
        TrackingSession(), delivery_manager, pack.project.project_id
    )

    health.assert_called_once_with(pack, policy=None)
    confidence.assert_called_once_with(pack, explanation_policy=None)
    risk.assert_called_once_with(pack, policy=None)
    trend.assert_called_once_with(pack, policy=None)


@pytest.mark.asyncio
async def test_missing_policy_sections_return_successful_data(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _overview_ready_pack()
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(return_value=pack),
    )
    overview = await build_client_intelligence_overview(
        TrackingSession(), delivery_manager, pack.project.project_id
    )
    assert overview.project_health.status == ProjectHealthStatus.INSUFFICIENT
    assert LIMITATION_POLICY_UNAVAILABLE in overview.project_health.limitations
    assert LIMITATION_RISK_POLICY_UNAVAILABLE in overview.risk_transparency.limitations
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE in overview.delivery_trend.limitations
    assert LIMITATION_PLAN_SERIES_UNAVAILABLE in overview.delivery_trend.limitations
    assert overview.delivery_confidence.org_id == pack.project.org_id


@pytest.mark.asyncio
async def test_overview_preserves_structured_limitation_separation(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _base_pack(limitations=["PACK_SOURCE_LIMIT"])
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(return_value=pack),
    )
    overview = await build_client_intelligence_overview(
        TrackingSession(), delivery_manager, pack.project.project_id
    )
    assert "PACK_SOURCE_LIMIT" in overview.source_limitations
    assert isinstance(overview.visibility_limitations, list)
    assert isinstance(overview.data_quality, list)
    assert overview.project_health.limitations != overview.source_limitations


@pytest.mark.asyncio
async def test_integrity_failure_maps_to_sanitized_api_error(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(
            side_effect=EvidencePackIntegrityError(
                EvidencePackValidationResult(is_valid=False, errors=[])
            )
        ),
    )
    with pytest.raises(ApiError) as exc:
        await build_client_intelligence_overview(
            TrackingSession(), delivery_manager, PROJECT_ID
        )
    assert exc.value.status_code == 422
    assert exc.value.code == "CLIENT_INTELLIGENCE_INTEGRITY_ERROR"
    assert exc.value.message == (
        "Client Intelligence could not be assembled from the available governed evidence."
    )


@pytest.mark.asyncio
async def test_unexpected_exception_is_not_swallowed(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(side_effect=RuntimeError("SECRET_INTERNAL_DETAIL")),
    )
    with pytest.raises(RuntimeError, match="SECRET_INTERNAL_DETAIL"):
        await build_client_intelligence_overview(
            TrackingSession(), delivery_manager, PROJECT_ID
        )


@pytest.mark.asyncio
async def test_service_performs_no_persistence(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _overview_ready_pack()
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(return_value=pack),
    )
    session = TrackingSession()
    await build_client_intelligence_overview(
        session, delivery_manager, pack.project.project_id
    )
    assert session.add_calls == 0
    assert session.commit_calls == 0
    assert session.flush_calls == 0


@pytest.mark.asyncio
async def test_overview_response_serializes_without_raw_pack(
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _overview_ready_pack()
    monkeypatch.setattr(
        "app.services.client_intelligence.build_client_evidence_pack",
        AsyncMock(return_value=pack),
    )
    overview = await build_client_intelligence_overview(
        TrackingSession(), delivery_manager, pack.project.project_id
    )
    payload = overview.model_dump(mode="json")
    assert payload["source_fingerprint"] == pack.source_fingerprint
    assert payload["as_of"] == pack.reporting_period.as_of.isoformat()
    assert "throughput_series" not in str(payload)
    assert "untrusted_text" not in str(payload)
    assert "chunks" not in payload
