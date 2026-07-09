"""API-level smoke tests for quality routes."""

import pytest
from httpx import AsyncClient

PROJECT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_quality_dashboard_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/api/v1/projects/{PROJECT_ID}/quality-dashboard")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_quality_scan_requires_auth(api_client: AsyncClient) -> None:
    """POST /internal/quality-scan must reject unauthenticated requests."""
    response = await api_client.post("/api/v1/internal/quality-scan")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_quality_summary_requires_auth(api_client: AsyncClient) -> None:
    """GET /projects/{id}/quality-summary must reject unauthenticated requests."""
    response = await api_client.get(f"/api/v1/projects/{PROJECT_ID}/quality-summary")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_leadership_quality_portfolio_requires_auth(api_client: AsyncClient) -> None:
    """GET /leadership/quality-portfolio must reject unauthenticated requests."""
    response = await api_client.get("/api/v1/leadership/quality-portfolio")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_calibration_brief_requires_auth(api_client: AsyncClient) -> None:
    project_id = "00000000-0000-0000-0000-000000000001"
    response = await api_client.get(f"/api/v1/projects/{project_id}/calibration-brief")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_inter_agent_signals_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/inter-agent-signals")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_resolve_risk_alert_requires_auth(api_client: AsyncClient) -> None:
    alert_id = "00000000-0000-0000-0000-000000000099"
    response = await api_client.patch(
        f"/api/v1/risk-alerts/{alert_id}/resolve",
        json={"resolution_summary": "test"},
    )
    assert response.status_code == 401
