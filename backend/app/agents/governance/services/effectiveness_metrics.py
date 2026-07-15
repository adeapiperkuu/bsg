"""Pure Phase 12 recommendation effectiveness formulas (no I/O)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, median

from app.agents.governance.schemas.governance import (
    GovernanceEffectivenessCalibrationRead,
    GovernanceEffectivenessMetricRead,
    GovernanceEffectivenessQualityScoreRead,
)
from app.core.config import get_settings
from app.db.models import (
    GovernanceAIRecommendation,
    GovernanceAIRecommendationFeedback,
    GovernanceAIRecommendationStatus,
    GovernanceFalsePositiveStatus,
    GovernanceRecommendationAcceptanceStatus,
)

QUALITY_SCORE_VERSION = "v1"
CALIBRATION_VERSION = "v1"
QUALITY_WEIGHTS = {
    "evidence_quality": 0.15,
    "confidence_calibration": 0.10,
    "acceptance_outcome": 0.20,
    "conversion_outcome": 0.15,
    "resolution_outcome": 0.15,
    "user_feedback": 0.15,
    "recurrence": 0.10,
}
ACCEPTED_STATUSES = {
    GovernanceRecommendationAcceptanceStatus.PARTIALLY_ACCEPTED,
    GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
    GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ESCALATION,
}


def rate_or_null(numerator: int, denominator: int, *, reason: str) -> GovernanceEffectivenessMetricRead:
    if denominator <= 0:
        return GovernanceEffectivenessMetricRead(
            value=None, numerator=numerator, denominator=0, null_reason=reason
        )
    return GovernanceEffectivenessMetricRead(
        value=round((numerator / denominator) * 100.0, 1),
        numerator=numerator,
        denominator=denominator,
        null_reason=None,
    )


def is_accepted(row: GovernanceAIRecommendation) -> bool:
    if row.accepted_at is not None:
        return True
    return row.acceptance_status in ACCEPTED_STATUSES


def is_dismissed(row: GovernanceAIRecommendation) -> bool:
    if row.dismissed_at is not None:
        return True
    return row.status == GovernanceAIRecommendationStatus.DISMISSED


def is_reviewed(row: GovernanceAIRecommendation) -> bool:
    return is_accepted(row) or is_dismissed(row)


def is_converted(row: GovernanceAIRecommendation) -> bool:
    return row.converted_action_id is not None or row.converted_escalation_id is not None


def is_resolved(row: GovernanceAIRecommendation) -> bool:
    return row.resolved_at is not None and row.reopened_at is None


def confidence_band(confidence: float | None) -> str:
    if confidence is None:
        return "unknown"
    pct = confidence * 100.0 if confidence <= 1.0 else float(confidence)
    if pct >= 80:
        return "high"
    if pct >= 60:
        return "medium"
    if pct >= 40:
        return "low"
    return "very_low"


def quality_band(score: float | None, *, provisional: bool) -> str:
    if score is None or provisional:
        return "insufficient"
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 60:
        return "mixed"
    if score >= 40:
        return "weak"
    return "poor"


def classify_false_positive(
    row: GovernanceAIRecommendation,
    *,
    feedback_rows: list[GovernanceAIRecommendationFeedback] | None = None,
) -> GovernanceFalsePositiveStatus:
    if row.false_positive_status is not None:
        return row.false_positive_status

    reason = (row.dismiss_reason or "").casefold()
    explicit_fp = any(
        token in reason
        for token in (
            "false positive",
            "incorrect evidence",
            "wrong evidence",
            "stale",
            "invalid detection",
        )
    )
    feedback = feedback_rows or []
    inaccurate = any(item.accurate is False for item in feedback)
    missing = any(item.missing_evidence for item in feedback)
    duplicate = any(item.duplicate for item in feedback)

    if explicit_fp or (inaccurate and missing):
        return GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE
    if is_dismissed(row) and (inaccurate or duplicate):
        return GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE
    if is_accepted(row) and is_converted(row) and is_resolved(row):
        return GovernanceFalsePositiveStatus.NOT_FALSE_POSITIVE
    return GovernanceFalsePositiveStatus.INSUFFICIENT_EVIDENCE


def compute_quality_score(
    row: GovernanceAIRecommendation,
    *,
    feedback_rows: list[GovernanceAIRecommendationFeedback] | None = None,
    has_outcome_data: bool,
) -> GovernanceEffectivenessQualityScoreRead:
    settings = get_settings()
    version = settings.governance_recommendation_quality_score_version or QUALITY_SCORE_VERSION
    if not has_outcome_data and not is_reviewed(row):
        return GovernanceEffectivenessQualityScoreRead(
            quality_score=None,
            quality_band="insufficient",
            component_scores={},
            weights=dict(QUALITY_WEIGHTS),
            penalties={},
            data_completeness=0.0,
            score_version=version,
            provisional=True,
        )

    evidence_count = len(row.evidence_refs or [])
    evidence_quality = min(100.0, 40.0 + evidence_count * 12.0)
    calibration_component = 70.0
    if row.calibrated_confidence is not None and row.confidence is not None:
        gap = abs(float(row.confidence) - float(row.calibrated_confidence))
        calibration_component = max(0.0, 100.0 - gap * 200.0)

    acceptance_component = 50.0
    if is_accepted(row):
        acceptance_component = 90.0
    elif is_dismissed(row):
        acceptance_component = 25.0

    conversion_component = 40.0
    if is_converted(row):
        conversion_component = 90.0
    elif is_accepted(row):
        conversion_component = 35.0

    resolution_component = 40.0
    if is_resolved(row):
        resolution_component = 95.0
    elif is_converted(row):
        resolution_component = 45.0

    feedback = feedback_rows or []
    feedback_component = 50.0
    if feedback:
        positives = 0
        total = 0
        for item in feedback:
            for flag in (item.helpful, item.accurate, item.useful, item.actionable, item.clear):
                if flag is None:
                    continue
                total += 1
                positives += 1 if flag else 0
        if total:
            feedback_component = (positives / total) * 100.0

    recurrence_penalty = min(
        40.0,
        (row.recurrence_after_acceptance_count or 0) * 12.0
        + (row.recurrence_after_dismissal_count or 0) * 8.0,
    )
    recurrence_component = max(0.0, 100.0 - recurrence_penalty)

    fp_status = classify_false_positive(row, feedback_rows=feedback)
    penalties: dict[str, float] = {}
    if fp_status == GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE:
        penalties["false_positive"] = 35.0
    elif fp_status == GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE:
        penalties["false_positive"] = 20.0
    if any(item.duplicate for item in feedback):
        penalties["duplicate"] = 15.0
    if "stale" in (row.dismiss_reason or "").casefold() or row.status == GovernanceAIRecommendationStatus.STALE:
        penalties["stale_evidence"] = 10.0

    components = {
        "evidence_quality": round(evidence_quality, 1),
        "confidence_calibration": round(calibration_component, 1),
        "acceptance_outcome": round(acceptance_component, 1),
        "conversion_outcome": round(conversion_component, 1),
        "resolution_outcome": round(resolution_component, 1),
        "user_feedback": round(feedback_component, 1),
        "recurrence": round(recurrence_component, 1),
    }
    weighted = sum(components[key] * QUALITY_WEIGHTS[key] for key in QUALITY_WEIGHTS)
    score = max(0.0, min(100.0, weighted - sum(penalties.values())))
    completeness = 0.35
    if is_reviewed(row):
        completeness += 0.25
    if is_converted(row):
        completeness += 0.15
    if is_resolved(row) or feedback:
        completeness += 0.15
    if row.evidence_refs:
        completeness += 0.10
    provisional = completeness < 0.6 and not is_reviewed(row)
    return GovernanceEffectivenessQualityScoreRead(
        quality_score=None if provisional else round(score, 1),
        quality_band=quality_band(score, provisional=provisional),
        component_scores=components,
        weights=dict(QUALITY_WEIGHTS),
        penalties=penalties,
        data_completeness=round(min(1.0, completeness), 2),
        score_version=version,
        provisional=provisional,
    )


def compute_calibration(
    rows: list[GovernanceAIRecommendation],
    *,
    min_sample: int,
) -> GovernanceEffectivenessCalibrationRead:
    settings = get_settings()
    version = settings.governance_recommendation_calibration_version or CALIBRATION_VERSION
    reviewed = [row for row in rows if is_reviewed(row)]
    if len(reviewed) < min_sample:
        return GovernanceEffectivenessCalibrationRead(
            calibrated_confidence=None,
            confidence_band="insufficient",
            calibration_version=version,
            observed_success_rate=None,
            calibration_gap=None,
            expected_calibration_error=None,
            brier_score=None,
            sample_size=len(reviewed),
            min_sample=min_sample,
            insufficient_history=True,
            fallback_to_original=True,
        )

    successes = [
        row
        for row in reviewed
        if is_accepted(row)
        and is_converted(row)
        and classify_false_positive(row)
        not in {
            GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE,
            GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE,
        }
    ]
    observed = len(successes) / len(reviewed)
    original_mean = mean(float(row.confidence) for row in reviewed if row.confidence is not None)
    calibrated = max(0.0, min(1.0, (original_mean * 0.4) + (observed * 0.6)))
    gap = calibrated - original_mean
    brier = mean(
        (float(row.confidence) - (1.0 if row in successes else 0.0)) ** 2
        for row in reviewed
        if row.confidence is not None
    )
    ece_buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in reviewed:
        if row.confidence is None:
            continue
        band = confidence_band(float(row.confidence))
        ece_buckets[band].append((float(row.confidence), 1.0 if row in successes else 0.0))
    ece = 0.0
    for values in ece_buckets.values():
        pred = mean(v[0] for v in values)
        obs = mean(v[1] for v in values)
        ece += abs(pred - obs) * (len(values) / len(reviewed))

    return GovernanceEffectivenessCalibrationRead(
        calibrated_confidence=round(calibrated, 3),
        confidence_band=confidence_band(calibrated),
        calibration_version=version,
        observed_success_rate=round(observed, 4),
        calibration_gap=round(gap, 4),
        expected_calibration_error=round(ece, 4),
        brier_score=round(brier, 4),
        sample_size=len(reviewed),
        min_sample=min_sample,
        insufficient_history=False,
        fallback_to_original=False,
    )


def seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0.0, (end - start).total_seconds())


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(median(values), 1)


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 1)
