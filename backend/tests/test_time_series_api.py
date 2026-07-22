"""API contract tests for Phase 18.2 time-series routes (OpenAPI presence)."""

from __future__ import annotations

from app.main import app


def test_time_series_openapi_paths_registered() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/kpis/{kpi_key}/history" in paths
    assert "/api/v1/kpis/{kpi_key}/latest" in paths
    assert "/api/v1/kpis/{kpi_key}/trend" in paths
    assert "/api/v1/kpis/{kpi_key}/series" in paths
    assert "/api/v1/kpis/{kpi_key}/compare" in paths
    assert "/api/v1/kpis/{kpi_key}/forecast" in paths
    assert "/api/v1/time-series/dimensions" in paths
    assert "/api/v1/time-series/recommendations" in paths
    assert "/api/v1/time-series/recommendations/{subject_id}/timeline" in paths


def test_openapi_includes_forecast_and_evaluate() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/kpis/{kpi_key}/forecast" in paths
    assert "/api/v1/time-series/recommendations" in paths
    assert "/api/v1/kpis/{kpi_id}/evaluate" in paths
