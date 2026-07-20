"""Phase 15.1 Delivery root-cause intelligence tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.agents.delivery.analytics.root_cause import (
    FACTOR_LABELS,
    allocate_confidence_loss,
    build_factor_signals,
    confidence_loss,
    root_cause_summary_for_ai,
    signal_absenteeism,
    signal_rework,
    trend_direction,
)
from app.agents.delivery.configuration import (
    DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS,
    DeliveryRootCauseWeights,
    ROOT_CAUSE_FACTOR_KEYS,
    invalidate_delivery_root_cause_weights_cache,
    validate_delivery_root_cause_config,
)
from app.core.security import CurrentUser
from app.db.models import AppRole
from tests.conftest import client_a, delivery_manager, override_user, super_admin

ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_default_weights_normalize_to_one() -> None:
    weights = DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.weights
    assert set(weights) == set(ROOT_CAUSE_FACTOR_KEYS)
    total = sum(weights.values(), Decimal("0"))
    assert abs(total - Decimal("1")) <= Decimal("0.0001")


def test_weight_validation_rejects_negative() -> None:
    with pytest.raises(ValueError):
        validate_delivery_root_cause_config(
            {"weights": {**{k: 0.1 for k in ROOT_CAUSE_FACTOR_KEYS}, "rework": -1}}
        )


def test_weight_custom_payload_normalizes() -> None:
    cfg = DeliveryRootCauseWeights.model_validate(
        {
            "weights": {key: 1 for key in ROOT_CAUSE_FACTOR_KEYS},
            "severity_medium_points": 2,
            "severity_high_points": 5,
            "severity_critical_points": 9,
        }
    )
    assert abs(sum(cfg.weights.values(), Decimal("0")) - Decimal("1")) <= Decimal("0.0001")


def test_confidence_loss_zero_when_on_track() -> None:
    assert confidence_loss(Decimal("85"), on_track_threshold=Decimal("80")) == Decimal("0")


def test_confidence_loss_below_threshold() -> None:
    assert confidence_loss(Decimal("72"), on_track_threshold=Decimal("80")) == Decimal("8.00")


def test_unavailable_absenteeism_signal() -> None:
    signal = signal_absenteeism()
    assert signal.data_available is False
    assert signal.severity_signal == Decimal("0")


def test_rework_evidence_shape() -> None:
    signal = signal_rework(rework_rate_pct=Decimal("18"))
    assert signal.data_available is True
    assert signal.severity_signal > 0
    assert "rework_rate_pct" in signal.inputs


def test_allocate_impact_sums_to_confidence_loss() -> None:
    signals = build_factor_signals(
        bottlenecks=[
            {"title": "Review queue backlog", "severity": "high", "source_key": "review-1"}
        ],
        rework_rate_pct=Decimal("20"),
        headcount_decline_pct=Decimal("15"),
        throughput_decline_pct=Decimal("10"),
        throughput_shortfall_pct=Decimal("25"),
        days_until_milestone=3,
        overdue_milestone_count=1,
        has_quality_drift=True,
        warning_window_days=14,
    )
    breakdown = allocate_confidence_loss(
        overall_confidence=Decimal("72"),
        on_track_threshold=Decimal("80"),
        weights=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.weights,
        signals=signals,
        severity_medium_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_medium_points,
        severity_high_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_high_points,
        severity_critical_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_critical_points,
    )
    assert breakdown.confidence_loss == Decimal("8.00")
    points_sum = sum((f.impact_points for f in breakdown.factors), Decimal("0"))
    assert abs(points_sum + breakdown.confidence_loss) <= Decimal("0.05")
    contributing = [f for f in breakdown.factors if f.impact_percent > 0]
    assert contributing
    pct_sum = sum((f.impact_percent for f in contributing), Decimal("0"))
    assert abs(pct_sum - Decimal("100")) <= Decimal("0.05")
    for factor in breakdown.factors:
        evidence = factor.evidence_json
        assert "why" in evidence
        assert "calculation" in evidence
        assert "affected_kpis" in evidence
        assert "data_available" in evidence


def test_allocate_zero_loss_all_zero_impacts() -> None:
    signals = build_factor_signals(
        bottlenecks=[],
        rework_rate_pct=None,
        headcount_decline_pct=None,
        throughput_decline_pct=Decimal("0"),
        throughput_shortfall_pct=None,
        days_until_milestone=None,
        overdue_milestone_count=0,
        has_quality_drift=False,
        warning_window_days=14,
    )
    breakdown = allocate_confidence_loss(
        overall_confidence=Decimal("90"),
        on_track_threshold=Decimal("80"),
        weights=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.weights,
        signals=signals,
        severity_medium_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_medium_points,
        severity_high_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_high_points,
        severity_critical_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_critical_points,
    )
    assert breakdown.confidence_loss == Decimal("0")
    assert all(f.impact_points == Decimal("0") for f in breakdown.factors)


def test_trend_direction_helpers() -> None:
    assert trend_direction(Decimal("20"), Decimal("10")) == "up"
    assert trend_direction(Decimal("5"), Decimal("15")) == "down"
    assert trend_direction(Decimal("10"), Decimal("10.5")) == "flat"
    assert trend_direction(None, Decimal("10")) == "insufficient_data"


def test_ai_summary_uses_deterministic_causes_only() -> None:
    signals = build_factor_signals(
        bottlenecks=[{"title": "Review delay", "severity": "critical", "source_key": "x"}],
        rework_rate_pct=Decimal("25"),
        headcount_decline_pct=Decimal("10"),
        throughput_decline_pct=Decimal("5"),
        throughput_shortfall_pct=Decimal("10"),
        days_until_milestone=2,
        overdue_milestone_count=0,
        has_quality_drift=False,
        warning_window_days=14,
    )
    breakdown = allocate_confidence_loss(
        overall_confidence=Decimal("70"),
        on_track_threshold=Decimal("80"),
        weights=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.weights,
        signals=signals,
        severity_medium_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_medium_points,
        severity_high_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_high_points,
        severity_critical_points=DEFAULT_DELIVERY_ROOT_CAUSE_WEIGHTS.severity_critical_points,
    )
    summary = root_cause_summary_for_ai(breakdown, limit=3)
    assert "top_causes" in summary
    assert len(summary["top_causes"]) <= 3
    for cause in summary["top_causes"]:
        assert cause["factor"] in FACTOR_LABELS


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_ID,
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_root_cause_analytics_rbac_client_forbidden(
    api_client: AsyncClient, client_a
) -> None:
    override_user(client_a)
    response = await api_client.get(
        "/api/v1/delivery/root-causes",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_root_cause_analytics_rbac_dm_allowed(
    api_client: AsyncClient, delivery_manager
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        "/api/v1/delivery/root-causes",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_root_cause_trends_rbac_leadership_allowed(
    api_client: AsyncClient, bsg_leadership
) -> None:
    override_user(bsg_leadership)
    response = await api_client.get(
        "/api/v1/delivery/root-causes/trends",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_recalculate_rbac_client_forbidden(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/delivery/projects/{PROJECT_ID}/recalculate-root-causes",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_recalculate_rbac_dm_not_forbidden_by_role(
    api_client: AsyncClient, delivery_manager
) -> None:
    override_user(delivery_manager)
    response = await api_client.post(
        f"/api/v1/delivery/projects/{PROJECT_ID}/recalculate-root-causes",
        headers={"Authorization": "Bearer test-token"},
    )
    # FakeSession may 404/500 on project load; role gate must not 403.
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_project_root_causes_client_not_role_blocked(
    api_client: AsyncClient, client_a
) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/delivery/projects/{PROJECT_ID}/root-causes",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code != 403


def test_invalidate_root_cause_cache() -> None:
    invalidate_delivery_root_cause_weights_cache()
    invalidate_delivery_root_cause_weights_cache(ORG_ID)
