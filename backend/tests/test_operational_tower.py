import pytest
from httpx import AsyncClient

from tests.conftest import override_user


@pytest.mark.anyio
async def test_operational_tower_returns_valid_payload(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/operational-tower")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # All sections present with the shapes the dashboard consumes.
    assert set(data["kpis"]) == {
        "activeProjects",
        "scheduleConfidence",
        "openEscalations",
        "avgQualityScore",
        "totalProjects",
    }
    assert data["kpis"]["activeProjects"] == 0
    assert data["riskTrend"] == {"series": [], "data": []}
    for key in ("qualityTrend", "utilization", "alerts",
                "recommendations", "milestones", "activity"):
        assert data[key] == []
    # Health distribution always exposes the three portfolio buckets.
    assert [h["name"] for h in data["healthDistribution"]] == ["On Track", "At Risk", "Critical"]
    assert all(h["value"] == 0 for h in data["healthDistribution"])
    assert data["criticalEscalations"] == 0


@pytest.mark.anyio
async def test_executive_summary_empty(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/executive-summary")
    assert resp.status_code == 200
    assert resp.json()["data"] is None
