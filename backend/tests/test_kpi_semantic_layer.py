"""Unit tests for the Phase 18.1 KPI semantic registry and calculators."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.kpis.contracts import EvaluationContext, KpiDependencySpec, RegisteredKpi
from app.kpis.formulas import (
    average_by_getter,
    average_utilization_pct,
    sla_adherence_from_counts,
    summary_metric_availability,
)
from app.kpis.registry import KpiRegistry, KpiRegistryError, get_kpi_registry, reset_kpi_registry_for_tests


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="kpi@test.local",
        role=role,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    reset_kpi_registry_for_tests()
    yield
    reset_kpi_registry_for_tests()


def test_registry_loads_canonical_providers() -> None:
    registry = get_kpi_registry()
    keys = {kpi.kpi_key for kpi in registry.list_kpis()}
    assert "delivery.confidence" in keys
    assert "quality.gold_set_accuracy" in keys
    assert "workforce.avg_utilization" in keys
    assert "governance.sla_adherence" in keys
    assert "tower.schedule_confidence" in keys
    assert "client.summary_metric_availability" in keys


def test_duplicate_registration_rejected() -> None:
    registry = KpiRegistry()

    def calc(_ctx: EvaluationContext):
        from app.kpis.contracts import CalculatorResult

        return CalculatorResult(status="ok", numeric_value=Decimal("1"))

    kpi = RegisteredKpi(
        kpi_key="demo.kpi",
        version="1.0.0",
        name="Demo",
        description="demo",
        owner_agent="shared",
        scope="org",
        calculator_key="demo.kpi.v1",
    )
    registry.register(kpi, calc)
    with pytest.raises(KpiRegistryError, match="Duplicate"):
        registry.register(kpi, calc)


def test_dependency_cycle_rejected() -> None:
    registry = KpiRegistry()

    def calc(_ctx: EvaluationContext):
        from app.kpis.contracts import CalculatorResult

        return CalculatorResult(status="ok", numeric_value=Decimal("1"))

    registry.register(
        RegisteredKpi(
            kpi_key="a",
            version="1.0.0",
            name="A",
            description="",
            owner_agent="shared",
            scope="org",
            calculator_key="a.v1",
            dependencies=(KpiDependencySpec(depends_on_kpi_key="b"),),
        ),
        calc,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="b",
            version="1.0.0",
            name="B",
            description="",
            owner_agent="shared",
            scope="org",
            calculator_key="b.v1",
            dependencies=(KpiDependencySpec(depends_on_kpi_key="a"),),
        ),
        calc,
    )
    with pytest.raises(KpiRegistryError, match="cycle"):
        registry.validate_dependencies()


def test_delivery_confidence_calculator_matches_analytics() -> None:
    from app.agents.delivery.analytics.confidence import calculate_confidence
    from app.kpis.providers.delivery import calculate_delivery_confidence

    expected = calculate_confidence(70, 10, (60, 70))
    result = calculate_delivery_confidence(
        EvaluationContext(
            current_user=_user(),
            org_id=uuid4(),
            inputs={
                "rolling_7day_units": 70,
                "daily_target_units": 10,
                "rolling_windows": (60, 70),
            },
        )
    )
    assert result.status == "ok"
    assert result.numeric_value == expected


def test_quality_average_helper_matches_legacy_semantics() -> None:
    class Snap:
        def __init__(self, value):
            self.value = value

    snaps = [Snap(Decimal("96")), Snap(None), Snap(Decimal("94"))]
    assert average_by_getter(snaps, lambda s: s.value) == Decimal("95")


def test_workforce_utilization_helper_formats_like_dashboard() -> None:
    assert average_utilization_pct([Decimal("80"), Decimal("90")]) == "85.0"
    assert average_utilization_pct([]) is None


def test_governance_sla_empty_window_is_100() -> None:
    assert sla_adherence_from_counts(0, 0) == 100.0
    assert sla_adherence_from_counts(9, 10) == 90.0


def test_client_availability_mapping() -> None:
    assert summary_metric_availability(has_evidence=False, has_score=False) == "unavailable"
    assert summary_metric_availability(has_evidence=True, has_score=False) == "no_data"
    assert summary_metric_availability(has_evidence=True, has_score=True) == "available"
    assert (
        summary_metric_availability(has_evidence=True, has_score=True, is_partial=True)
        == "partial"
    )


@pytest.mark.asyncio
async def test_evaluate_kpi_with_inputs() -> None:
    from app.kpis.evaluation import evaluate_kpi

    result = await evaluate_kpi(
        None,
        _user(),
        "delivery.confidence",
        inputs={
            "rolling_7day_units": 70,
            "daily_target_units": 10,
            "rolling_windows": [60, 70],
        },
    )
    assert result.status == "ok"
    assert result.numeric_value is not None
    assert result.calculator_key == "delivery.confidence.v1"


@pytest.mark.asyncio
async def test_historical_as_of_without_version_returns_no_data() -> None:
    from datetime import UTC, datetime

    from app.kpis.evaluation import evaluate_kpi

    result = await evaluate_kpi(
        None,
        _user(),
        "delivery.confidence",
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        inputs={"confidence_score_pct": 80},
    )
    assert result.status == "no_data"


@pytest.mark.asyncio
async def test_client_cannot_evaluate_internal_kpi() -> None:
    from app.core.exceptions import ApiError
    from app.kpis.evaluation import evaluate_kpi

    with pytest.raises(ApiError) as exc:
        await evaluate_kpi(
            None,
            _user(AppRole.CLIENT),
            "delivery.risk",
            inputs={"confidence_score_pct": 70},
        )
    assert exc.value.status_code == 403
