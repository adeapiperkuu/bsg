"""Delivery KPI calculators — wrap existing analytics formulas."""

from __future__ import annotations

from decimal import Decimal

from app.agents.delivery.analytics.confidence import calculate_confidence
from app.agents.delivery.analytics.risk import calculate_risk
from app.agents.delivery.analytics.status import calculate_status
from app.kpis.contracts import CalculatorResult, EvaluationContext, KpiDependencySpec, RegisteredKpi
from app.kpis.registry import KpiRegistry


def _decimal_input(context: EvaluationContext, key: str, default: Decimal | None = None) -> Decimal | None:
    raw = context.inputs.get(key, default)
    if raw is None:
        return None
    return Decimal(str(raw))


def calculate_delivery_confidence(context: EvaluationContext) -> CalculatorResult:
    rolling = context.inputs.get("rolling_7day_units")
    target = context.inputs.get("daily_target_units")
    windows = context.inputs.get("rolling_windows") or ()
    flat_tolerance = _decimal_input(context, "flat_tolerance_pct", Decimal("5.00"))
    if rolling is None and target is None and "confidence_score_pct" in context.inputs:
        value = _decimal_input(context, "confidence_score_pct")
        if value is None:
            return CalculatorResult(status="no_data")
        return CalculatorResult(
            status="ok",
            numeric_value=value,
            provenance={"source": "inputs.confidence_score_pct"},
            explainability={"summary": "Passthrough delivery confidence from provided inputs."},
        )
    score = calculate_confidence(
        None if rolling is None else int(rolling),
        None if target is None else int(target),
        tuple(windows),
        flat_tolerance_pct=flat_tolerance or Decimal("5.00"),
    )
    return CalculatorResult(
        status="ok",
        numeric_value=score,
        provenance={
            "calculator": "delivery.confidence.v1",
            "rolling_7day_units": rolling,
            "daily_target_units": target,
        },
        explainability={
            "summary": "Compares recent throughput to the expected window output and adjusts for trend."
        },
    )


def calculate_delivery_risk(context: EvaluationContext) -> CalculatorResult:
    confidence = _decimal_input(context, "confidence_score_pct")
    if confidence is None:
        return CalculatorResult(status="no_data", explainability={"summary": "Confidence score required."})
    risk_kwargs: dict = {
        "confidence_score_pct": confidence,
        "throughput_decline_pct": _decimal_input(context, "throughput_decline_pct", Decimal("0"))
        or Decimal("0"),
        "is_throughput_declining": bool(context.inputs.get("is_throughput_declining", False)),
        "days_until_milestone": context.inputs.get("days_until_milestone"),
        "open_bottleneck_count": int(context.inputs.get("open_bottleneck_count") or 0),
        "has_quality_drift": bool(context.inputs.get("has_quality_drift", False)),
        "rework_rate_pct": _decimal_input(context, "rework_rate_pct"),
    }
    on_track = _decimal_input(context, "on_track_threshold")
    if on_track is not None:
        risk_kwargs["on_track_threshold"] = on_track
    warning_window = context.inputs.get("warning_window_days")
    if warning_window is not None:
        risk_kwargs["warning_window_days"] = int(warning_window)
    score = calculate_risk(**risk_kwargs)
    return CalculatorResult(
        status="ok",
        numeric_value=score,
        provenance={"calculator": "delivery.risk.v1", "confidence_score_pct": str(confidence)},
        explainability={"summary": "Aggregates delivery risk drivers into a single score."},
    )


def calculate_delivery_traffic_light(context: EvaluationContext) -> CalculatorResult:
    confidence = _decimal_input(context, "confidence")
    risk_score = _decimal_input(context, "risk_score")
    if confidence is None or risk_score is None:
        return CalculatorResult(status="no_data")
    status = calculate_status(
        confidence=confidence,
        risk_score=risk_score,
        open_bottleneck_count=int(context.inputs.get("open_bottleneck_count") or 0),
        milestone_status=context.inputs.get("milestone_status"),
        yellow_confidence_threshold=_decimal_input(context, "yellow_confidence_threshold")
        or Decimal("80.00"),
        red_confidence_threshold=_decimal_input(context, "red_confidence_threshold")
        or Decimal("50.00"),
        yellow_risk_threshold=_decimal_input(context, "yellow_risk_threshold") or Decimal("30.00"),
        red_risk_threshold=_decimal_input(context, "red_risk_threshold") or Decimal("85.00"),
        open_risk_tiers=context.inputs.get("open_risk_tiers"),
    )
    return CalculatorResult(
        status="ok",
        text_value=status,
        provenance={"calculator": "delivery.traffic_light.v1"},
        explainability={"summary": "Applies configured traffic-light rules to confidence and risk."},
    )


def register(registry: KpiRegistry) -> None:
    registry.register(
        RegisteredKpi(
            kpi_key="delivery.confidence",
            version="1.0.0",
            name="Delivery confidence",
            description="Likelihood a milestone remains on track based on throughput vs target and trend.",
            owner_agent="delivery",
            scope="project",
            calculator_key="delivery.confidence.v1",
            unit="percent",
            trend_direction="higher_is_better",
            formula_description="clamp(variance_ratio * 100 + trend_adjustment)",
            source_fields=(
                "throughput_snapshots.rolling_7day_units",
                "projects.daily_target_units",
            ),
            default_thresholds={"on_track": 80, "critical": 50},
            explainability={
                "summary": "Compares recent throughput to the expected window output and adjusts for trend."
            },
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,
            metric_config_key="delivery_confidence",
        ),
        calculate_delivery_confidence,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="delivery.risk",
            version="1.0.0",
            name="Delivery risk",
            description="Composite delivery risk score from confidence and operational signals.",
            owner_agent="delivery",
            scope="project",
            calculator_key="delivery.risk.v1",
            unit="percent",
            trend_direction="lower_is_better",
            formula_description="weighted risk contributions clamped to 0-100",
            source_fields=(
                "delivery_confidence_scores.score_pct",
                "bottlenecks",
                "quality_snapshots.rework_rate_pct",
            ),
            default_thresholds={"medium": 30, "high": 60, "critical": 85},
            explainability={"summary": "Aggregates delivery risk drivers into a single score."},
            allowed_roles=("super_admin", "bsg_leadership", "delivery_manager"),
            dependencies=(
                KpiDependencySpec(depends_on_kpi_key="delivery.confidence", depends_on_version="1.0.0"),
            ),
            metric_config_key="delivery_risk",
        ),
        calculate_delivery_risk,
    )
    registry.register(
        RegisteredKpi(
            kpi_key="delivery.traffic_light",
            version="1.0.0",
            name="Delivery traffic light",
            description="Deterministic green/yellow/red status from confidence, risk, and flags.",
            owner_agent="delivery",
            scope="project",
            calculator_key="delivery.traffic_light.v1",
            unit="enum",
            trend_direction="neutral",
            formula_description="rule cascade: red overrides yellow overrides green",
            source_fields=(
                "delivery.confidence",
                "delivery.risk",
                "bottlenecks",
                "milestones.status",
            ),
            explainability={
                "summary": "Applies configured traffic-light rules to confidence and risk."
            },
            allowed_roles=(
                "super_admin",
                "bsg_leadership",
                "delivery_manager",
                "client",
            ),
            is_client_visible=True,
            dependencies=(
                KpiDependencySpec(depends_on_kpi_key="delivery.confidence", depends_on_version="1.0.0"),
                KpiDependencySpec(depends_on_kpi_key="delivery.risk", depends_on_version="1.0.0"),
            ),
            metric_config_key="delivery_traffic_light",
        ),
        calculate_delivery_traffic_light,
    )
