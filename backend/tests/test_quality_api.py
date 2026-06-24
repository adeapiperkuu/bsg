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
