"""Operational Tower composite KPI calculators."""

from __future__ import annotations

from decimal import Decimal

from app.kpis.contracts import CalculatorResult, EvaluationContext, KpiDependencySpec, RegisteredKpi
from app.kpis.formulas import average_numeric, mean_optional_floats
from app.kpis.registry import KpiRegistry


def calculate_schedule_confidence(context: EvaluationContext) -> CalculatorResult:
    if "schedule_confidence" in context.inputs:
        raw = context.inputs["schedule_confidence"]
        if raw is None:
            return CalculatorResult(status="no_data")
        return CalculatorResult(
            status="ok",
            numeric_value=Decimal(str(raw)),
            provenance={"source": "passthrough"},
        )
    values = context.inputs.get("confidence_pct_values") or []
    avg = average_numeric(values)
    if avg is None:
        return CalculatorResult(status="no_data")
    # Tower exposes scheduleConfidence as an int percentage.
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(int(round(float(avg)))),
        provenance={"calculator": "tower.schedule_confidence.v1"},
        explainability={"summary": "Averages delivery confidence across the visible portfolio."},
    )


def calculate_avg_quality_score(context: EvaluationContext) -> CalculatorResult:
    if "avg_quality_score" in context.inputs:
        raw = context.inputs["avg_quality_score"]
        if raw is None:
            return CalculatorResult(status="no_data")
        return CalculatorResult(
            status="ok",
            numeric_value=Decimal(str(raw)),
            provenance={"source": "passthrough"},
        )
    values = context.inputs.get("gold_set_accuracy_pct_values") or []
    avg = mean_optional_floats(
        [None if value is None else float(value) for value in values]
    )
    if avg is None:
        return CalculatorResult(status="no_data")
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(str(avg)),
        provenance={"calculator": "tower.avg_quality_score.v1"},
        explainability={"summary": "Averages gold-set accuracy across visible projects."},
    )


def register(registry: KpiRegistry) -> None:
    registry.register(
        RegisteredKpi(
            kpi_key="tower.schedule_confidence",
            version="1.0.0",
            name="Tower schedule confidence",
            description="Portfolio schedule confidence composite used by Operational Tower.",
            owner_agent="tower",
            scope="org",
            calculator_key="tower.schedule_confidence.v1",
            unit="percent",
            formula_description="mean(delivery confidence across visible portfolio)",
            source_fields=("delivery_confidence_scores.score_pct",),
            default_thresholds={"on_track": 80},
            explainability={
                "summary": "Averages delivery confidence across the visible portfolio."
            },
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
            dependencies=(
                KpiDependencySpec(depends_on_kpi_key="delivery.confidence", depends_on_version="1.0.0"),
            ),
        ),
        calculate_schedule_confidence,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="tower.avg_quality_score",
            version="1.0.0",
            name="Tower average quality score",
            description="Portfolio average gold-set accuracy used by Operational Tower.",
            owner_agent="tower",
            scope="org",
            calculator_key="tower.avg_quality_score.v1",
            unit="percent",
            formula_description="mean(quality_snapshots.gold_set_accuracy_pct)",
            source_fields=("quality_snapshots.gold_set_accuracy_pct",),
            explainability={"summary": "Averages gold-set accuracy across visible projects."},
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
            dependencies=(
                KpiDependencySpec(
                    depends_on_kpi_key="quality.gold_set_accuracy",
                    depends_on_version="1.0.0",
                ),
            ),
        ),
        calculate_avg_quality_score,
    )
