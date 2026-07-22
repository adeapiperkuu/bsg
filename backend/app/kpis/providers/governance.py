"""Governance KPI calculators."""

from __future__ import annotations

from decimal import Decimal

from app.agents.governance.analytics.sla import (
    calculate_sla_adherence_pct,
    count_open_actions,
    count_open_escalations,
)
from app.kpis.contracts import CalculatorResult, EvaluationContext, RegisteredKpi
from app.kpis.formulas import sla_adherence_from_counts
from app.kpis.registry import KpiRegistry


def calculate_sla_adherence(context: EvaluationContext) -> CalculatorResult:
    if "on_time_completed" in context.inputs and "total_completed" in context.inputs:
        value = sla_adherence_from_counts(
            int(context.inputs.get("on_time_completed") or 0),
            int(context.inputs.get("total_completed") or 0),
        )
        return CalculatorResult(
            status="ok",
            numeric_value=Decimal(str(value)),
            provenance={"calculator": "governance.sla_adherence.v1", "path": "counts"},
            explainability={
                "summary": "Measures on-time completion of governance actions over a 90-day window."
            },
        )
    actions = context.inputs.get("actions")
    if actions is None:
        return CalculatorResult(status="no_data")
    value = calculate_sla_adherence_pct(list(actions), today=context.inputs.get("today"))
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(str(value)),
        provenance={"calculator": "governance.sla_adherence.v1", "path": "actions"},
        explainability={
            "summary": "Measures on-time completion of governance actions over a 90-day window."
        },
    )


def calculate_open_actions(context: EvaluationContext) -> CalculatorResult:
    if "open_actions" in context.inputs:
        return CalculatorResult(
            status="ok",
            numeric_value=Decimal(str(context.inputs["open_actions"])),
            provenance={"source": "passthrough"},
        )
    actions = context.inputs.get("actions")
    if actions is None:
        return CalculatorResult(status="no_data")
    value = count_open_actions(list(actions), today=context.inputs.get("today"))
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(value),
        provenance={"calculator": "governance.open_actions.v1"},
        explainability={"summary": "Counts actionable open governance items."},
    )


def calculate_open_escalations(context: EvaluationContext) -> CalculatorResult:
    if "open_escalations" in context.inputs:
        return CalculatorResult(
            status="ok",
            numeric_value=Decimal(str(context.inputs["open_escalations"])),
            provenance={"source": "passthrough"},
        )
    escalations = context.inputs.get("escalations")
    if escalations is None:
        return CalculatorResult(status="no_data")
    value = count_open_escalations(list(escalations))
    return CalculatorResult(
        status="ok",
        numeric_value=Decimal(value),
        provenance={"calculator": "governance.open_escalations.v1"},
        explainability={"summary": "Counts unresolved governance escalations."},
    )


def register(registry: KpiRegistry) -> None:
    registry.register(
        RegisteredKpi(
            kpi_key="governance.sla_adherence",
            version="1.0.0",
            name="Governance SLA adherence",
            description="Percentage of completed actions closed on or before due date in the last 90 days.",
            owner_agent="governance",
            scope="org",
            calculator_key="governance.sla_adherence.v1",
            unit="percent",
            refresh_frequency="daily",
            formula_description="on_time_completed / total_completed * 100 (empty => 100)",
            source_fields=(
                "governance_actions.status",
                "governance_actions.due_date",
                "governance_actions.completed_at",
            ),
            explainability={
                "summary": "Measures on-time completion of governance actions over a 90-day window."
            },
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,
        ),
        calculate_sla_adherence,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="governance.open_actions",
            version="1.0.0",
            name="Open governance actions",
            description="Count of open, in-progress, or overdue governance actions.",
            owner_agent="governance",
            scope="org",
            calculator_key="governance.open_actions.v1",
            unit="count",
            trend_direction="lower_is_better",
            refresh_frequency="realtime",
            formula_description="count(open|in_progress|overdue actions)",
            source_fields=("governance_actions.status", "governance_actions.due_date"),
            explainability={"summary": "Counts actionable open governance items."},
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
        ),
        calculate_open_actions,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="governance.open_escalations",
            version="1.0.0",
            name="Open governance escalations",
            description="Count of open or in-progress governance escalations.",
            owner_agent="governance",
            scope="org",
            calculator_key="governance.open_escalations.v1",
            unit="count",
            trend_direction="lower_is_better",
            refresh_frequency="realtime",
            formula_description="count(open|in_progress escalations)",
            source_fields=("governance_escalations.status",),
            explainability={"summary": "Counts unresolved governance escalations."},
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,
        ),
        calculate_open_escalations,
    )
