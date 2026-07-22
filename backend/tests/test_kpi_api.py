"""API contract tests for Phase 18.1 KPI Semantic Layer endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.kpis.registry import reset_kpi_registry_for_tests
from app.main import app
from tests.conftest import override_user


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    reset_kpi_registry_for_tests()
    yield
    reset_kpi_registry_for_tests()


def _dm() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="dm@test.local",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _client_user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="client@test.local",
        role=AppRole.CLIENT,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_kpis_openapi_paths_registered() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/kpis" in paths
    assert "/api/v1/kpis/{kpi_id}" in paths
    assert "/api/v1/kpis/{kpi_id}/calculation" in paths
    assert "/api/v1/kpis/{kpi_id}/evaluate" in paths
    assert "/api/v1/kpis/evaluate" in paths


@pytest.mark.asyncio
async def test_list_kpis_returns_catalog(api_client) -> None:
    override_user(_dm())
    response = await api_client.get(
        "/api/v1/kpis",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    keys = {item["kpi_key"] for item in body["data"]}
    assert "delivery.confidence" in keys
    assert "quality.gold_set_accuracy" in keys


@pytest.mark.asyncio
async def test_get_kpi_calculation_metadata(api_client) -> None:
    override_user(_dm())
    response = await api_client.get(
        "/api/v1/kpis/delivery.confidence/calculation",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["calculator_key"] == "delivery.confidence.v1"
    assert data["formula_description"]
    assert "thresholds" in data


@pytest.mark.asyncio
async def test_evaluate_kpi_with_inputs(api_client) -> None:
    override_user(_dm())
    response = await api_client.post(
        "/api/v1/kpis/delivery.confidence/evaluate",
        headers={"Authorization": "Bearer test-token"},
        json={
            "inputs": {
                "rolling_7day_units": 70,
                "daily_target_units": 10,
                "rolling_windows": [60, 70],
            }
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["numeric_value"] is not None


@pytest.mark.asyncio
async def test_batch_evaluate_kpis(api_client) -> None:
    override_user(_dm())
    response = await api_client.post(
        "/api/v1/kpis/evaluate",
        headers={"Authorization": "Bearer test-token"},
        json={
            "kpi_ids": ["delivery.confidence", "delivery.risk"],
            "inputs": {
                "rolling_7day_units": 70,
                "daily_target_units": 10,
                "rolling_windows": [60, 70],
                "confidence_score_pct": 80,
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    assert {item["kpi_key"] for item in data} == {
        "delivery.confidence",
        "delivery.risk",
    }


@pytest.mark.asyncio
async def test_client_catalog_hides_internal_kpis(api_client) -> None:
    override_user(_client_user())
    response = await api_client.get(
        "/api/v1/kpis",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    keys = {item["kpi_key"] for item in response.json()["data"]}
    assert "delivery.confidence" in keys
    assert "delivery.risk" not in keys


@pytest.mark.asyncio
async def test_cross_org_evaluate_forbidden_for_dm(api_client) -> None:
    override_user(_dm())
    response = await api_client.post(
        "/api/v1/kpis/workforce.avg_utilization/evaluate",
        headers={"Authorization": "Bearer test-token"},
        json={"org_id": str(uuid4()), "inputs": {"utilization_pct_values": [80, 90]}},
    )
    assert response.status_code == 403
