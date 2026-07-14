"""Phase 12 — recommendation effectiveness metrics, quality, calibration, FP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.governance.services.effectiveness_metrics import (
    classify_false_positive,
    compute_calibration,
    compute_quality_score,
    confidence_band,
    is_accepted,
    is_converted,
    is_dismissed,
    is_resolved,
    is_reviewed,
    quality_band,
    rate_or_null,
)
from app.db.models import (
    GovernanceAIRecommendationStatus,
    GovernanceFalsePositiveStatus,
    GovernanceRecommendationAcceptanceStatus,
)


def _rec(**overrides):
    base = {
        "id": uuid4(),
        "title": "Rec",
        "confidence": 0.8,
        "calibrated_confidence": None,
        "status": GovernanceAIRecommendationStatus.ACTIVE,
        "acceptance_status": GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        "accepted_at": None,
        "dismissed_at": None,
        "dismiss_reason": None,
        "converted_action_id": None,
        "converted_escalation_id": None,
        "resolved_at": None,
        "reopened_at": None,
        "false_positive_status": None,
        "evidence_refs": [{"id": "e1"}],
        "recurrence_after_acceptance_count": 0,
        "recurrence_after_dismissal_count": 0,
        "generated_at": datetime.now(UTC) - timedelta(days=2),
        "updated_at": datetime.now(UTC),
        "priority": SimpleNamespace(value="high"),
        "trigger_type": None,
        "explanation_version": "v1",
        "project_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_rate_or_null_zero_denominator():
    metric = rate_or_null(0, 0, reason="no_reviewed_recommendations")
    assert metric.value is None
    assert metric.null_reason == "no_reviewed_recommendations"
    assert metric.denominator == 0


def test_metric_formulas_use_reviewed_accepted_converted_denominators():
    accepted = 4
    dismissed = 6
    reviewed = accepted + dismissed
    converted = 2
    resolved = 1
    assert rate_or_null(accepted, reviewed, reason="x").value == 40.0
    assert rate_or_null(dismissed, reviewed, reason="x").value == 60.0
    assert rate_or_null(converted, accepted, reason="x").value == 50.0
    assert rate_or_null(resolved, converted, reason="x").value == 50.0


def test_lifecycle_flags_are_separate():
    accepted_only = _rec(
        accepted_at=datetime.now(UTC),
        acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
    )
    converted = _rec(
        accepted_at=datetime.now(UTC),
        acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
        converted_action_id=uuid4(),
    )
    resolved = _rec(
        accepted_at=datetime.now(UTC),
        converted_action_id=uuid4(),
        resolved_at=datetime.now(UTC),
    )
    assert is_accepted(accepted_only) and not is_converted(accepted_only)
    assert is_converted(converted) and not is_resolved(converted)
    assert is_resolved(resolved)
    assert is_reviewed(accepted_only)
    assert is_dismissed(
        _rec(
            status=GovernanceAIRecommendationStatus.DISMISSED,
            dismissed_at=datetime.now(UTC),
        )
    )


def test_false_positive_not_inferred_from_every_dismissal():
    bare_dismiss = _rec(
        status=GovernanceAIRecommendationStatus.DISMISSED,
        dismissed_at=datetime.now(UTC),
        dismiss_reason="Not now",
    )
    assert classify_false_positive(bare_dismiss) == GovernanceFalsePositiveStatus.INSUFFICIENT_EVIDENCE

    explicit = _rec(
        status=GovernanceAIRecommendationStatus.DISMISSED,
        dismissed_at=datetime.now(UTC),
        dismiss_reason="false positive / incorrect evidence",
    )
    assert classify_false_positive(explicit) == GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE

    confirmed = _rec(
        false_positive_status=GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE,
    )
    assert classify_false_positive(confirmed) == GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE


def test_quality_score_bounds_weights_and_provisional():
    provisional = compute_quality_score(_rec(), feedback_rows=[], has_outcome_data=False)
    assert provisional.provisional is True
    assert provisional.quality_band == "insufficient"
    assert provisional.quality_score is None

    scored = compute_quality_score(
        _rec(
            accepted_at=datetime.now(UTC),
            acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
            converted_action_id=uuid4(),
            resolved_at=datetime.now(UTC),
            evidence_refs=[{"id": "a"}, {"id": "b"}],
        ),
        feedback_rows=[
            SimpleNamespace(
                helpful=True,
                accurate=True,
                useful=True,
                actionable=True,
                clear=True,
                duplicate=False,
                missing_evidence=False,
            )
        ],
        has_outcome_data=True,
    )
    assert scored.provisional is False
    assert scored.quality_score is not None
    assert 0 <= scored.quality_score <= 100
    assert abs(sum(scored.weights.values()) - 1.0) < 1e-6
    assert scored.quality_band in {"excellent", "good", "mixed", "weak", "poor"}


def test_confidence_calibration_preserves_fallback_and_min_sample():
    rows = [_rec(confidence=0.7) for _ in range(3)]
    calib = compute_calibration(rows, min_sample=10)
    assert calib.insufficient_history is True
    assert calib.fallback_to_original is True
    assert calib.calibrated_confidence is None

    reviewed = []
    for index in range(12):
        if index < 8:
            reviewed.append(
                _rec(
                    confidence=0.75,
                    accepted_at=datetime.now(UTC),
                    acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
                    converted_action_id=uuid4(),
                )
            )
        else:
            reviewed.append(
                _rec(
                    confidence=0.75,
                    status=GovernanceAIRecommendationStatus.DISMISSED,
                    dismissed_at=datetime.now(UTC),
                )
            )
    calib_ok = compute_calibration(reviewed, min_sample=10)
    assert calib_ok.insufficient_history is False
    assert calib_ok.calibrated_confidence is not None
    assert 0 <= calib_ok.calibrated_confidence <= 1
    assert calib_ok.brier_score is not None


def test_confidence_and_quality_bands():
    assert confidence_band(0.9) == "high"
    assert confidence_band(0.5) == "low"
    assert quality_band(92, provisional=False) == "excellent"
    assert quality_band(50, provisional=True) == "insufficient"


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (1, 4, 25.0),
        (0, 5, 0.0),
        (3, 0, None),
    ],
)
def test_rate_parametrized(numerator: int, denominator: int, expected: float | None):
    metric = rate_or_null(numerator, denominator, reason="empty")
    assert metric.value == expected
