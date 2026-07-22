"""Client Intelligence KPI calculators (availability semantics only)."""

from __future__ import annotations

from app.kpis.contracts import CalculatorResult, EvaluationContext, RegisteredKpi
from app.kpis.formulas import summary_metric_availability
from app.kpis.registry import KpiRegistry


def calculate_summary_metric_availability(context: EvaluationContext) -> CalculatorResult:
    availability = summary_metric_availability(
        has_evidence=bool(context.inputs.get("has_evidence", False)),
        has_score=bool(context.inputs.get("has_score", False)),
        is_partial=bool(context.inputs.get("is_partial", False)),
    )
    return CalculatorResult(
        status="ok",
        text_value=availability,
        provenance={"calculator": "client.summary_metric_availability.v1"},
        explainability={
            "summary": "Maps evidence presence to summary metric availability without inventing scores."
        },
    )


def register(registry: KpiRegistry) -> None:
    registry.register(
        RegisteredKpi(
            kpi_key="client.summary_metric_availability",
            version="1.0.0",
            name="Client summary metric availability",
            description="Whether a client-visible summary metric has sufficient evidence to display.",
            owner_agent="client_intelligence",
            scope="project",
            calculator_key="client.summary_metric_availability.v1",
            unit="enum",
            trend_direction="neutral",
            formula_description="available|partial|no_data|unavailable from evidence presence",
            source_fields=("client_intelligence evidence packs",),
            explainability={
                "summary": "Maps evidence presence to summary metric availability without inventing scores."
            },
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,

        ),
        calculate_summary_metric_availability,
    )
