"""Compatibility adapters for existing agent services.

These helpers preserve legacy DTO shapes while routing pure formula steps through
the shared KPI semantic layer / formula helpers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import TypeVar

from app.core.security import CurrentUser
from app.kpis.contracts import CalculatorResult, EvaluationContext
from app.kpis.formulas import (
    average_by_getter,
    average_utilization_pct,
    count_truthy,
    sla_adherence_from_counts,
    summary_metric_availability,
)
from app.kpis.registry import get_kpi_registry

T = TypeVar("T")

# Re-exports for agent modules — single import surface.
average_quality_metric = average_by_getter
format_avg_utilization_pct = average_utilization_pct
count_active_drift_alerts = count_truthy
governance_sla_from_counts = sla_adherence_from_counts
client_metric_availability = summary_metric_availability


def run_registered_calculator(
    calculator_key: str,
    *,
    current_user: CurrentUser,
    inputs: dict,
    org_id=None,
    project_id=None,
) -> CalculatorResult:
    """Synchronously invoke a registered calculator (for unit/regression adapters)."""
    registry = get_kpi_registry()
    calculator = registry.get_calculator(calculator_key)
    if calculator is None:
        raise KeyError(f"Unknown calculator_key: {calculator_key}")
    context = EvaluationContext(
        current_user=current_user,
        org_id=org_id,
        project_id=project_id,
        inputs=inputs,
        include_explainability=False,
    )
    result = calculator(context)
    if hasattr(result, "__await__"):
        raise TypeError(f"Calculator {calculator_key} is async; use evaluate_kpi instead")
    return result  # type: ignore[return-value]


def quality_dashboard_kpi_values(
    latest_week_snaps: Sequence[T],
    *,
    gold_getter: Callable[[T], Decimal | float | int | None],
    iaa_getter: Callable[[T], Decimal | float | int | None],
    rework_getter: Callable[[T], Decimal | float | int | None],
    drift_getter: Callable[[T], bool],
) -> dict[str, Decimal | int | None]:
    """Assemble Quality dashboard KPI numeric fields via shared formulas."""
    return {
        "gold_set_accuracy_pct": average_by_getter(latest_week_snaps, gold_getter),
        "iaa_krippendorff_alpha": average_by_getter(latest_week_snaps, iaa_getter),
        "rework_rate_pct": average_by_getter(latest_week_snaps, rework_getter),
        "active_drift_alerts": count_truthy(drift_getter(snap) for snap in latest_week_snaps),
    }
