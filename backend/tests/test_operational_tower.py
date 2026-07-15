import pytest
from httpx import AsyncClient

from tests.conftest import override_user

# The tower is served as independent sections so the dashboard can fetch them in parallel and
# paint each as it lands. Each is asserted separately: the contract is one endpoint per
# section, not one payload.


@pytest.mark.anyio
async def test_tower_pulse_returns_valid_payload(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/operational-tower/pulse")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["activeProjects"] == 0
    assert data["totalProjects"] == 0
    assert data["avgQualityScore"] is None
    assert data["riskTrend"] == {"series": [], "data": []}
    assert data["qualityTrend"] == []
    assert data["alerts"] == []


@pytest.mark.anyio
async def test_tower_escalations_returns_valid_payload(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/operational-tower/escalations")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["openEscalations"] == 0
    assert data["criticalEscalations"] == 0


@pytest.mark.anyio
async def test_tower_health_returns_valid_payload(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/operational-tower/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["scheduleConfidence"] is None
    # Health distribution always exposes the three portfolio buckets.
    assert [h["name"] for h in data["healthDistribution"]] == ["On Track", "At Risk", "Critical"]
    assert all(h["value"] == 0 for h in data["healthDistribution"])


@pytest.mark.anyio
async def test_tower_work_returns_valid_payload(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/operational-tower/work")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["recommendations"] == []
    assert data["milestones"] == []


@pytest.mark.anyio
async def test_tower_activity_returns_valid_payload(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/operational-tower/activity")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["utilization"] == []
    assert data["activity"] == []


@pytest.mark.anyio
async def test_executive_summary_empty(api_client: AsyncClient, delivery_manager):
    override_user(delivery_manager)
    resp = await api_client.get("/api/v1/dashboard/executive-summary")
    assert resp.status_code == 200
    assert resp.json()["data"] is None
