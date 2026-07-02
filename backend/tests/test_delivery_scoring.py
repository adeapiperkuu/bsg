"""Regression coverage for the Delivery Performance Agent scoring engine.

Focuses on deterministic pure functions (confidence, risk, status, recommendation
copy) plus the insufficient-data and scoring-failure-visibility behaviors added
during production hardening.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.delivery.analytics.confidence import (
    ON_TRACK_THRESHOLD,
    calculate_confidence,
    calculate_trend_direction,
    calculate_variance_ratio,
    classify_confidence_status,
    has_sufficient_throughput_data,
)
from app.agents.delivery.analytics.risk import (
    bottleneck_risk_component,
    calculate_risk,
    classify_risk_tier,
    confidence_risk_component,
    milestone_risk_component,
    quality_risk_component,
    throughput_risk_component,
)
from app.agents.delivery.analytics.status import calculate_status
from app.agents.delivery.events.domain_events import HandlerRunSummary
from app.agents.delivery.events.event_bus import EventBus, HandlerExecutionResult
from app.agents.delivery.services.recommendation_service import (
    _confidence_from_risk,
    _map_risk_tier_to_severity,
    generate_mitigation_copy,
)
from app.agents.delivery.services.scoring_service import (
    ScoringContext,
    _build_run_result,
    _ScoringComputeResult,
    compute_delivery_scores,
)
from app.db.models import AlertType, Project, RecommendationSeverity, RiskAlert, RiskTier

# ---------------------------------------------------------------------------
# Confidence calculations
# ---------------------------------------------------------------------------


def test_calculate_variance_ratio_on_pace() -> None:
    assert calculate_variance_ratio(70, 10) == Decimal("1")


def test_calculate_variance_ratio_missing_inputs_is_zero() -> None:
    assert calculate_variance_ratio(None, 10) == Decimal("0")
    assert calculate_variance_ratio(70, None) == Decimal("0")
    assert calculate_variance_ratio(0, 10) == Decimal("0")


def test_calculate_trend_direction_requires_two_points() -> None:
    assert calculate_trend_direction([]) == "unknown"
    assert calculate_trend_direction([50]) == "unknown"


def test_calculate_trend_direction_improving_and_declining() -> None:
    assert calculate_trend_direction([50, 70]) == "improving"
    assert calculate_trend_direction([70, 50]) == "declining"
    assert calculate_trend_direction([50, 51]) == "flat"


def test_calculate_confidence_on_pace_with_flat_trend() -> None:
    # variance ratio 1.0 -> 100%, flat trend adjustment 0
    score = calculate_confidence(70, 10, rolling_windows=[70, 71])
    assert score == Decimal("100.00")


def test_calculate_confidence_applies_declining_trend_penalty() -> None:
    on_pace = calculate_confidence(70, 10, rolling_windows=[70, 71])
    declining = calculate_confidence(70, 10, rolling_windows=[100, 70])
    assert declining < on_pace


def test_calculate_confidence_clamped_to_100() -> None:
    assert calculate_confidence(1000, 10) == Decimal("100.00")


def test_classify_confidence_status_thresholds() -> None:
    assert classify_confidence_status(ON_TRACK_THRESHOLD) == "on_track"
    assert classify_confidence_status(ON_TRACK_THRESHOLD - Decimal("0.01")) == "at_risk"


# ---------------------------------------------------------------------------
# Insufficient-data behavior
# ---------------------------------------------------------------------------


def test_has_sufficient_throughput_data_false_when_no_snapshots() -> None:
    assert has_sufficient_throughput_data(None) is False


def test_has_sufficient_throughput_data_true_when_any_value_present() -> None:
    # Zero is a real (low) throughput reading, not "no data" — the project has history.
    assert has_sufficient_throughput_data(0) is True
    assert has_sufficient_throughput_data(42) is True


# ---------------------------------------------------------------------------
# Risk calculations
# ---------------------------------------------------------------------------


def test_confidence_risk_component_zero_when_on_track() -> None:
    assert confidence_risk_component(Decimal("90.00")) == Decimal("0")


def test_confidence_risk_component_scales_with_shortfall_and_is_capped() -> None:
    assert confidence_risk_component(Decimal("70.00")) == Decimal("12.50")
    assert confidence_risk_component(Decimal("0.00")) == Decimal("35.00")


def test_throughput_risk_component_requires_declining_flag() -> None:
    decline_pct = Decimal("50")
    not_declining = throughput_risk_component(
        throughput_decline_pct=decline_pct, is_declining=False
    )
    declining = throughput_risk_component(throughput_decline_pct=decline_pct, is_declining=True)
    assert not_declining == Decimal("0")
    assert declining == Decimal("25.00")


def test_milestone_risk_component_overdue_is_max() -> None:
    assert milestone_risk_component(days_until_milestone=-1) == Decimal("30.00")


def test_milestone_risk_component_outside_warning_window_is_zero() -> None:
    assert milestone_risk_component(days_until_milestone=30) == Decimal("0")


def test_milestone_risk_component_none_is_zero() -> None:
    assert milestone_risk_component(days_until_milestone=None) == Decimal("0")


def test_bottleneck_risk_component_capped() -> None:
    assert bottleneck_risk_component(0) == Decimal("0")
    assert bottleneck_risk_component(10) == Decimal("15.00")


def test_quality_risk_component_default_when_rework_missing() -> None:
    assert quality_risk_component(has_quality_drift=True, rework_rate_pct=None) == Decimal("5.00")


def test_calculate_risk_clamped_to_100() -> None:
    risk = calculate_risk(
        confidence_score_pct=Decimal("0.00"),
        throughput_decline_pct=Decimal("100"),
        is_throughput_declining=True,
        days_until_milestone=-5,
        open_bottleneck_count=10,
        has_quality_drift=True,
        rework_rate_pct=Decimal("40"),
    )
    assert risk == Decimal("100.00")


def test_calculate_risk_zero_when_healthy() -> None:
    risk = calculate_risk(confidence_score_pct=Decimal("100.00"))
    assert risk == Decimal("0.00")


def test_classify_risk_tier_thresholds() -> None:
    assert classify_risk_tier(Decimal("10")) == "low"
    assert classify_risk_tier(Decimal("30")) == "medium"
    assert classify_risk_tier(Decimal("60")) == "high"
    assert classify_risk_tier(Decimal("85")) == "critical"


# ---------------------------------------------------------------------------
# Traffic-light / status logic
# ---------------------------------------------------------------------------


def test_calculate_status_green_when_healthy() -> None:
    status = calculate_status(confidence=Decimal("95"), risk_score=Decimal("5"))
    assert status == "green"


def test_calculate_status_red_below_hard_confidence_floor() -> None:
    status = calculate_status(confidence=Decimal("40"), risk_score=Decimal("5"))
    assert status == "red"


def test_calculate_status_red_on_critical_risk_tier() -> None:
    status = calculate_status(
        confidence=Decimal("95"), risk_score=Decimal("5"), open_risk_tiers=["critical"]
    )
    assert status == "red"


def test_calculate_status_red_on_missed_milestone() -> None:
    status = calculate_status(
        confidence=Decimal("95"), risk_score=Decimal("5"), milestone_status="missed"
    )
    assert status == "red"


def test_calculate_status_yellow_below_on_track_threshold() -> None:
    status = calculate_status(confidence=Decimal("70"), risk_score=Decimal("5"))
    assert status == "yellow"


def test_calculate_status_yellow_with_open_bottleneck() -> None:
    status = calculate_status(
        confidence=Decimal("95"), risk_score=Decimal("5"), open_bottleneck_count=1
    )
    assert status == "yellow"


# ---------------------------------------------------------------------------
# Recommendation scoring
# ---------------------------------------------------------------------------


def _risk_alert(
    *, tier: RiskTier, slippage: Decimal | None, causes: dict | None = None
) -> RiskAlert:
    return RiskAlert(
        id=uuid4(),
        project_id=uuid4(),
        org_id=uuid4(),
        alert_type=AlertType.DELIVERY_RISK,
        risk_tier=tier,
        title="Delivery slippage risk",
        detail="detail",
        slippage_probability=slippage,
        contributing_causes=causes,
    )


def test_map_risk_tier_to_severity() -> None:
    assert _map_risk_tier_to_severity(RiskTier.CRITICAL) == RecommendationSeverity.HIGH
    assert _map_risk_tier_to_severity(RiskTier.HIGH) == RecommendationSeverity.HIGH
    assert _map_risk_tier_to_severity(RiskTier.MEDIUM) == RecommendationSeverity.MEDIUM
    assert _map_risk_tier_to_severity(RiskTier.LOW) == RecommendationSeverity.LOW


def test_confidence_from_risk_uses_actual_slippage_when_present() -> None:
    risk = _risk_alert(tier=RiskTier.HIGH, slippage=Decimal("0.777"))
    assert _confidence_from_risk(risk) == Decimal("0.777")


def test_confidence_from_risk_falls_back_to_tier_default() -> None:
    risk = _risk_alert(tier=RiskTier.CRITICAL, slippage=None)
    assert _confidence_from_risk(risk) == Decimal("0.900")


def test_generate_mitigation_copy_uses_top_contributing_cause() -> None:
    risk = _risk_alert(
        tier=RiskTier.HIGH,
        slippage=Decimal("0.8"),
        causes={"throughput_decline": 25.0, "open_bottlenecks": 5.0},
    )
    title, description = generate_mitigation_copy(risk)
    assert title == "Stabilize weekly throughput"
    assert "Delivery slippage risk" in description


def test_generate_mitigation_copy_falls_back_to_alert_type_when_no_causes() -> None:
    risk = _risk_alert(tier=RiskTier.HIGH, slippage=Decimal("0.8"), causes=None)
    title, _description = generate_mitigation_copy(risk)
    assert title == "Mitigate delivery slippage"


# ---------------------------------------------------------------------------
# Scoring failure visibility (event bus)
# ---------------------------------------------------------------------------


class _FakeEvent:
    pass


@pytest.mark.asyncio
async def test_event_bus_reports_handler_failure_without_raising() -> None:
    bus = EventBus()

    async def _failing_handler(_session, _event):
        raise RuntimeError("boom")

    bus.subscribe(_FakeEvent, _failing_handler)

    class _FakeSession:
        def begin_nested(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return None

                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False  # let the exception propagate to EventBus.emit's try/except

            return _Ctx()

    results = await bus.emit(_FakeSession(), _FakeEvent())

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error_type == "RuntimeError"
    assert "boom" in (results[0].error or "")


def _project(org_id=None) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name="Test Project",
        vertical="medical",
        status="active",
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
    )


def _no_data_raw_data() -> dict:
    return {
        "as_of_date": date(2026, 6, 1),
        "project": {"daily_target_units": 10},
        "milestones": [],
        "throughput_snapshots": [],
        "risks": [],
        "bottlenecks": [],
        "quality_snapshot": None,
    }


def test_compute_delivery_scores_flags_insufficient_data_with_no_throughput_history() -> None:
    context = ScoringContext.from_raw_data(_no_data_raw_data())
    scores = compute_delivery_scores(context)
    assert scores.has_sufficient_data is False
    assert scores.confidence == Decimal("0.00")


def test_compute_delivery_scores_has_sufficient_data_with_throughput_history() -> None:
    raw = _no_data_raw_data()
    raw["throughput_snapshots"] = [{"rolling_7day_units": 70, "units_completed": 10}]
    context = ScoringContext.from_raw_data(raw)
    scores = compute_delivery_scores(context)
    assert scores.has_sufficient_data is True


def test_build_run_result_marks_scoring_failed_when_a_handler_raises() -> None:
    """A handler-level exception must surface as scoring_status='failed', never as a
    silently-successful run — this is what upsert_throughput_snapshot exposes to the
    throughput ingestion API response."""
    project = _project()
    context = ScoringContext.from_raw_data(_no_data_raw_data())
    scores = compute_delivery_scores(context)
    compute_result = _ScoringComputeResult(resolved_project=project, scores=scores, event=None)
    handler_results = [
        HandlerExecutionResult(
            handler="handle_delivery_scored",
            success=False,
            result=None,
            error="boom",
            error_type="RuntimeError",
        ),
    ]

    run_result = _build_run_result(compute_result, date(2026, 6, 1), handler_results)

    assert run_result.scoring_status == "failed"
    assert run_result.scoring_error == "handle_delivery_scored raised RuntimeError"
    # Sanitized: the raw exception message ("boom") must not leak into the API-facing field.
    assert "boom" not in (run_result.scoring_error or "")


def test_build_run_result_ok_when_all_handlers_succeed() -> None:
    project = _project()
    context = ScoringContext.from_raw_data(_no_data_raw_data())
    scores = compute_delivery_scores(context)
    compute_result = _ScoringComputeResult(resolved_project=project, scores=scores, event=None)
    handler_results = [
        HandlerExecutionResult(
            handler="handle_delivery_scored",
            success=True,
            result=HandlerRunSummary(),
            error=None,
        ),
    ]

    run_result = _build_run_result(compute_result, date(2026, 6, 1), handler_results)

    assert run_result.scoring_status == "ok"
    assert run_result.scoring_error is None


@pytest.mark.asyncio
async def test_event_bus_reports_success_when_handler_completes() -> None:
    bus = EventBus()

    async def _ok_handler(_session, _event):
        return "done"

    bus.subscribe(_FakeEvent, _ok_handler)

    class _FakeSession:
        def begin_nested(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return None

                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False

            return _Ctx()

    results = await bus.emit(_FakeSession(), _FakeEvent())

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].result == "done"
    assert results[0].error is None
    assert results[0].error_type is None
