"""Quality KPI calculators."""

from __future__ import annotations

from decimal import Decimal

from app.kpis.contracts import CalculatorResult, EvaluationContext, RegisteredKpi
from app.kpis.formulas import average_numeric, count_truthy
from app.kpis.registry import KpiRegistry


def _values(context: EvaluationContext, key: str) -> list[Decimal | float | int | None]:
    raw = context.inputs.get(key)
    if raw is None:
        return []
    if isinstance(raw, list | tuple):
        return list(raw)
    return [raw]


def calculate_gold_set_accuracy(context: EvaluationContext) -> CalculatorResult:
    avg = average_numeric(_values(context, "gold_set_accuracy_pct_values"))
    if avg is None and "gold_set_accuracy_pct" in context.inputs:
        avg = average_numeric([context.inputs.get("gold_set_accuracy_pct")])
    if avg is None:
        return CalculatorResult(status="no_data")
    return CalculatorResult(
        status="ok",
        numeric_value=avg,
        provenance={"calculator": "quality.gold_set_accuracy.v1", "sample_size": len(_values(context, "gold_set_accuracy_pct_values") or [1])},
        explainability={
            "summary": "Averages non-null gold-set accuracy values from the latest snapshot per team."
        },
    )


def calculate_iaa(context: EvaluationContext) -> CalculatorResult:
    avg = average_numeric(_values(context, "iaa_krippendorff_alpha_values"))
    if avg is None and "iaa_krippendorff_alpha" in context.inputs:
        avg = average_numeric([context.inputs.get("iaa_krippendorff_alpha")])
    if avg is None:
        return CalculatorResult(status="no_data")
    return CalculatorResult(
        status="ok",
        numeric_value=avg,
        provenance={"calculator": "quality.iaa.v1"},
        explainability={"summary": "Averages non-null IAA values from the latest snapshot per team."},
    )


def calculate_rework_rate(context: EvaluationContext) -> CalculatorResult:
    avg = average_numeric(_values(context, "rework_rate_pct_values"))
    if avg is None and "rework_rate_pct" in context.inputs:
        avg = average_numeric([context.inputs.get("rework_rate_pct")])
    if avg is None:
        return CalculatorResult(status="no_data")
    return CalculatorResult(
        status="ok",
        numeric_value=avg,
        provenance={"calculator": "quality.rework_rate.v1"},
        explainability={
            "summary": "Averages non-null rework rates from the latest snapshot per team."
        },
    )


def calculate_active_drift_alerts(context: EvaluationContext) -> CalculatorResult:
    flags = context.inputs.get("has_drift_alert_flags")
    if flags is None and "active_drift_alerts" in context.inputs:
        return CalculatorResult(
            status="ok",
            numeric_value=Decimal(str(context.inputs["active_drift_alerts"])),
            provenance={"calculator": "quality.active_drift_alerts.v1", "source": "passthrough"},
        )
    if flags is None:
        return CalculatorResult(status="no_data")
    count = count_truthy(bool(flag) for flag in flags)
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(count),
        provenance={"calculator": "quality.active_drift_alerts.v1"},
        explainability={
            "summary": "Counts teams with an active drift flag on their latest snapshot."
        },
    )


def register(registry: KpiRegistry) -> None:
    registry.register(
        RegisteredKpi(
            kpi_key="quality.gold_set_accuracy",
            version="1.0.0",
            name="Gold-set accuracy",
            description="Mean gold-set accuracy across latest per-team quality snapshots.",
            owner_agent="quality",
            scope="project",
            calculator_key="quality.gold_set_accuracy.v1",
            unit="percent",
            formula_description="average(latest_per_team.gold_set_accuracy_pct)",
            source_fields=("quality_snapshots.gold_set_accuracy_pct",),
            default_thresholds={"green_min": 96, "amber_min": 94, "red_min": 92},
            explainability={
                "summary": "Averages non-null gold-set accuracy values from the latest snapshot per team."
            },
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,
            metric_config_key="gold_set_accuracy",
        ),
        calculate_gold_set_accuracy,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="quality.iaa",
            version="1.0.0",
            name="Inter-annotator agreement",
            description="Mean Krippendorff alpha across latest per-team quality snapshots.",
            owner_agent="quality",
            scope="project",
            calculator_key="quality.iaa.v1",
            unit="ratio",
            formula_description="average(latest_per_team.iaa_krippendorff_alpha)",
            source_fields=("quality_snapshots.iaa_krippendorff_alpha",),
            default_thresholds={"green_min": 0.90, "amber_min": 0.85, "red_min": 0.80},
            explainability={
                "summary": "Averages non-null IAA values from the latest snapshot per team."
            },
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
            metric_config_key="iaa_krippendorff_alpha",
        ),
        calculate_iaa,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="quality.rework_rate",
            version="1.0.0",
            name="Rework rate",
            description="Mean rework rate across latest per-team quality snapshots.",
            owner_agent="quality",
            scope="project",
            calculator_key="quality.rework_rate.v1",
            unit="percent",
            trend_direction="lower_is_better",
            formula_description="average(latest_per_team.rework_rate_pct)",
            source_fields=("quality_snapshots.rework_rate_pct",),
            default_thresholds={"green_max": 3, "amber_max": 4, "red_max": 6},
            explainability={
                "summary": "Averages non-null rework rates from the latest snapshot per team."
            },
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,
            metric_config_key="rework_rate",
        ),
        calculate_rework_rate,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="quality.active_drift_alerts",
            version="1.0.0",
            name="Active drift alerts",
            description="Count of latest per-team quality snapshots currently flagged for drift.",
            owner_agent="quality",
            scope="project",
            calculator_key="quality.active_drift_alerts.v1",
            unit="count",
            trend_direction="lower_is_better",
            refresh_frequency="realtime",
            formula_description="count(latest_per_team.has_drift_alert)",
            source_fields=("quality_snapshots.has_drift_alert",),
            explainability={
                "summary": "Counts teams with an active drift flag on their latest snapshot."
            },
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
        ),
        calculate_active_drift_alerts,
    )
