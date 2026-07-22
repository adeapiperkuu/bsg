"""Workforce KPI calculators."""

from __future__ import annotations

from decimal import Decimal

from app.kpis.contracts import CalculatorResult, EvaluationContext, RegisteredKpi
from app.kpis.formulas import average_utilization_pct
from app.kpis.registry import KpiRegistry


def calculate_avg_utilization(context: EvaluationContext) -> CalculatorResult:
    values = context.inputs.get("utilization_pct_values")
    if values is None and "avg_utilization_pct" in context.inputs:
        raw = context.inputs["avg_utilization_pct"]
        text = None if raw is None else str(raw)
        numeric = None if text is None else Decimal(text)
        return CalculatorResult(
            status="ok" if text is not None else "no_data",
            numeric_value=numeric,
            text_value=text,
            provenance={"source": "passthrough"},
        )
    if not isinstance(values, list | tuple):
        return CalculatorResult(status="no_data")
    text = average_utilization_pct(list(values))
    if text is None:
        return CalculatorResult(status="no_data")
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(text),
        text_value=text,
        provenance={"calculator": "workforce.avg_utilization.v1", "sample_size": len(values)},
        explainability={
            "summary": "Averages latest utilization percentages across tracked teams."
        },
    )


def register(registry: KpiRegistry) -> None:
    registry.register(
        RegisteredKpi(
            kpi_key="workforce.avg_utilization",
            version="1.0.0",
            name="Average workforce utilization",
            description="Mean utilization across latest team utilization snapshots.",
            owner_agent="workforce",
            scope="org",
            calculator_key="workforce.avg_utilization.v1",
            unit="percent",
            trend_direction="neutral",
            refresh_frequency="weekly",
            formula_description="round(mean(utilization_pct), 1)",
            source_fields=("workforce_utilization_snapshots.utilization_pct",),
            explainability={
                "summary": "Averages latest utilization percentages across tracked teams."
            },
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
        ),
        calculate_avg_utilization,
    )
