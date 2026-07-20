"""Deterministic Delivery Confidence Intelligence foundation (roadmap 8.2).

Consumes Delivery-owned confidence facts and adds structured explanation.
Never recalculates score, invents a band from thresholds, accesses the DB,
or calls an LLM. No production explanation policy is defined.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityState,
    DeliveryConfidenceFacts,
    EvidenceVisibility,
    SourceAgent,
)
from app.agents.client_intelligence.delivery_confidence_contracts import (
    DeliveryConfidenceAssessment,
    DeliveryConfidenceAvailability,
    DeliveryConfidenceCandidate,
    DeliveryConfidenceCandidateCategory,
    DeliveryConfidenceCandidateContext,
    DeliveryConfidenceDriver,
    DeliveryConfidenceDriverPolarity,
    DeliveryConfidenceEvidencePeriod,
    DeliveryConfidenceEvidenceRef,
    DeliveryConfidenceExplanationDecision,
    DeliveryConfidenceMilestoneView,
    DeliveryConfidenceTrend,
    MitigationContributionState,
    _canonicalize_source_limitations,
)
from app.agents.client_intelligence.delivery_confidence_policy import (
    DeliveryConfidenceExplanationPolicy,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    reference_supports_claim_keys,
    source_agent_owns_table,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.project_health import resolve_health_source_quality
from app.db.models import AppRole

LIMITATION_EXPLANATION_POLICY_UNAVAILABLE = "EXPLANATION_POLICY_UNAVAILABLE"
LIMITATION_EXPLANATION_NOT_EVALUATED_NO_SCORE = "EXPLANATION_NOT_EVALUATED_NO_SCORE"
LIMITATION_EXPLANATION_NOT_EVALUATED_UNRELIABLE_SOURCE = (
    "EXPLANATION_NOT_EVALUATED_UNRELIABLE_SOURCE"
)
LIMITATION_DELIVERY_CONFIDENCE_UNAVAILABLE = "DELIVERY_CONFIDENCE_UNAVAILABLE"
LIMITATION_DELIVERY_CONFIDENCE_STALE = "DELIVERY_CONFIDENCE_STALE"
LIMITATION_DELIVERY_CONFIDENCE_CONFLICTING = "DELIVERY_CONFIDENCE_CONFLICTING"
LIMITATION_DELIVERY_CONFIDENCE_PARTIAL = "DELIVERY_CONFIDENCE_PARTIAL"
LIMITATION_PREVIOUS_CONFIDENCE_UNAVAILABLE = "PREVIOUS_CONFIDENCE_UNAVAILABLE"
LIMITATION_PREVIOUS_PERIOD_MISMATCH = "PREVIOUS_PERIOD_MISMATCH"
LIMITATION_PREVIOUS_CONFIDENCE_STALE = "PREVIOUS_CONFIDENCE_STALE"
LIMITATION_PREVIOUS_CONFIDENCE_CONFLICTING = "PREVIOUS_CONFIDENCE_CONFLICTING"
LIMITATION_PREVIOUS_CONFIDENCE_PARTIAL = "PREVIOUS_CONFIDENCE_PARTIAL"
LIMITATION_PREVIOUS_CONFIDENCE_NO_SCORE = "PREVIOUS_CONFIDENCE_NO_SCORE"
LIMITATION_BACKLOG_SOURCE_UNAVAILABLE = "BACKLOG_SOURCE_UNAVAILABLE"
LIMITATION_MITIGATION_SOURCE_UNAVAILABLE = "MITIGATION_SOURCE_UNAVAILABLE"
LIMITATION_STABLE_THROUGHPUT_UNPROVEN = "STABLE_THROUGHPUT_UNPROVEN"
LIMITATION_PROACTIVE_QA_UNPROVEN = "PROACTIVE_QA_UNPROVEN"
LIMITATION_EMPTY_RISK_NOT_POSITIVE = "EMPTY_RISK_NOT_POSITIVE"
LIMITATION_EMPTY_BOTTLENECK_NOT_POSITIVE = "EMPTY_BOTTLENECK_NOT_POSITIVE"
LIMITATION_SOURCE_QUALITY_MISSING_MILESTONES = "SOURCE_QUALITY_MISSING_MILESTONES"
LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS = (
    "SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS"
)
LIMITATION_SOURCE_QUALITY_MISSING_QUALITY_SNAPSHOTS = (
    "SOURCE_QUALITY_MISSING_QUALITY_SNAPSHOTS"
)
LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS = "SOURCE_QUALITY_MISSING_RISK_ALERTS"
LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS = "SOURCE_QUALITY_MISSING_BOTTLENECKS"
LIMITATION_SOURCE_QUALITY_MISSING_GOVERNANCE_DEPENDENCIES = (
    "SOURCE_QUALITY_MISSING_GOVERNANCE_DEPENDENCIES"
)

_RELIABLE_QUALITY = frozenset({DataQualityState.COMPLETE})

_EVIDENCE_TABLE_TO_DQ_SOURCES: dict[str, frozenset[str]] = {
    "delivery_confidence_scores": frozenset(
        {"delivery_confidence", "delivery_confidence_scores"}
    ),
    "milestones": frozenset({"milestones"}),
    "throughput_snapshots": frozenset({"throughput_snapshots"}),
    "quality_snapshots": frozenset({"quality_snapshots"}),
    "risk_alerts": frozenset({"risk_alerts", "risks"}),
    "bottlenecks": frozenset({"bottlenecks"}),
    "project_dependencies": frozenset({"governance_dependencies"}),
}

_MISSING_QUALITY_LIMITATION: dict[str, str] = {
    "milestones": LIMITATION_SOURCE_QUALITY_MISSING_MILESTONES,
    "throughput_snapshots": LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS,
    "quality_snapshots": LIMITATION_SOURCE_QUALITY_MISSING_QUALITY_SNAPSHOTS,
    "risk_alerts": LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS,
    "bottlenecks": LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS,
    "project_dependencies": LIMITATION_SOURCE_QUALITY_MISSING_GOVERNANCE_DEPENDENCIES,
}

_SOURCE_QUALITY_LABEL: dict[str, str] = {
    "milestones": "MILESTONES",
    "throughput_snapshots": "THROUGHPUT_SNAPSHOTS",
    "quality_snapshots": "QUALITY_SNAPSHOTS",
    "risk_alerts": "RISK_ALERTS",
    "bottlenecks": "BOTTLENECKS",
    "project_dependencies": "GOVERNANCE_DEPENDENCIES",
    "delivery_confidence_scores": "DELIVERY_CONFIDENCE_SCORES",
}

_NON_COMPLETE_QUALITY_STATES = frozenset(
    {
        DataQualityState.STALE,
        DataQualityState.CONFLICTING,
        DataQualityState.PARTIAL,
        DataQualityState.UNAVAILABLE,
    }
)


class DeliveryConfidenceIntegrityError(Exception):
    """Deterministic Delivery Confidence Intelligence integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def assess_delivery_confidence(
    pack: ClientEvidencePack,
    *,
    explanation_policy: DeliveryConfidenceExplanationPolicy | None = None,
    previous: ClientEvidencePack | None = None,
) -> DeliveryConfidenceAssessment:
    """Build a Delivery Confidence assessment from a validated evidence pack."""
    working = pack.model_copy(deep=True)
    working_previous = (
        previous.model_copy(deep=True) if previous is not None else None
    )

    _validate_pack_or_raise(working)
    if working_previous is not None:
        _validate_pack_or_raise(working_previous)
        _assert_previous_compatible(working, working_previous)

    source_quality = resolve_health_source_quality(working, "delivery_confidence_scores")
    confidence = working.delivery.latest_delivery_confidence
    availability = _availability_for_quality(source_quality)

    source_limitations = _canonicalize_source_limitations(list(working.limitations))
    limitations: list[str] = []
    evidence: list[DeliveryConfidenceEvidenceRef] = []
    score_pct: Decimal | None = None
    confidence_band: str | None = None
    observed_at: datetime | None = None
    forecast: date | None = None
    milestone_view: DeliveryConfidenceMilestoneView | None = None
    positive: list[DeliveryConfidenceDriver] = []
    negative: list[DeliveryConfidenceDriver] = []
    rules_version: str | None = None

    core_org_id = working.project.org_id
    core_project_id = working.project.project_id
    core_reporting_period = working.reporting_period
    core_visibility = working.visibility_mode
    core_source_fingerprint = working.source_fingerprint
    core_generated_at = working.generated_at

    if availability == DeliveryConfidenceAvailability.NO_SCORE:
        if confidence is not None:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Delivery Confidence fact presence disagrees with pack quality.",
            )
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_UNAVAILABLE)
        if explanation_policy is None:
            limitations.append(LIMITATION_EXPLANATION_POLICY_UNAVAILABLE)
        else:
            limitations.append(LIMITATION_EXPLANATION_NOT_EVALUATED_NO_SCORE)
        trend, previous_score, previous_fp, trend_limits, trend_evidence = _compute_trend(
            working,
            working_previous,
            current_available=False,
            current_score=None,
        )
        limitations.extend(trend_limits)
        limitations.extend(_foundation_domain_limitations(working))
        return DeliveryConfidenceAssessment(
            org_id=core_org_id,
            project_id=core_project_id,
            reporting_period=core_reporting_period,
            visibility_mode=core_visibility,
            availability=availability,
            score_pct=None,
            confidence_band=None,
            confidence_band_is_delivery_owned_status=True,
            current_milestone=None,
            forecast_completion_date=None,
            observed_at=None,
            source_data_quality=source_quality,
            trend=DeliveryConfidenceTrend.UNKNOWN,
            previous_score_pct=previous_score,
            positive_drivers=[],
            negative_drivers=[],
            mitigation_contribution=MitigationContributionState.UNAVAILABLE,
            limitations=_canonicalize_strings(limitations),
            source_limitations=source_limitations,
            evidence=_sort_evidence(evidence + trend_evidence),
            source_fingerprint=core_source_fingerprint,
            previous_source_fingerprint=previous_fp,
            rules_version=None,
            assessed_at=core_generated_at,
        )

    if confidence is None:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence is absent without matching UNAVAILABLE quality.",
        )
    if type(confidence.score_pct) is float:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Float Delivery Confidence scores are not accepted.",
        )
    if not isinstance(confidence.score_pct, Decimal):
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence score_pct must remain Decimal-safe.",
        )

    score_pct = confidence.score_pct
    confidence_band = confidence.status
    observed_at = confidence.observed_at
    forecast = confidence.forecast_completion_date
    dc_evidence = _require_dc_evidence(working, confidence)
    evidence.extend(dc_evidence)
    milestone_view = _resolve_confidence_milestone(working, confidence)
    evidence.extend(milestone_view.evidence)

    if availability == DeliveryConfidenceAvailability.STALE:
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_STALE)
    elif availability == DeliveryConfidenceAvailability.CONFLICTING:
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_CONFLICTING)
    elif availability == DeliveryConfidenceAvailability.PARTIAL:
        limitations.append(LIMITATION_DELIVERY_CONFIDENCE_PARTIAL)

    trend, previous_score, previous_fp, trend_limits, trend_evidence = _compute_trend(
        working,
        working_previous,
        current_available=(availability == DeliveryConfidenceAvailability.AVAILABLE),
        current_score=score_pct,
    )
    limitations.extend(trend_limits)
    evidence.extend(trend_evidence)
    limitations.extend(_foundation_domain_limitations(working))

    if explanation_policy is None:
        limitations.append(LIMITATION_EXPLANATION_POLICY_UNAVAILABLE)
    elif availability == DeliveryConfidenceAvailability.AVAILABLE:
        rules_version = _require_rules_version(explanation_policy)
        authoritative = _build_candidate_context(
            working, source_quality=source_quality
        )
        limitations.extend(authoritative.context_limitations)
        decision = _evaluate_explanation(explanation_policy, authoritative)
        positive, negative = _normalize_drivers(
            decision,
            candidates=authoritative,
            pack=working,
            client_safe=core_visibility == EvidenceVisibility.CLIENT_SAFE,
        )
        limitations.extend(decision.policy_limitations)
        for driver in [*positive, *negative]:
            evidence.extend(driver.evidence)
    else:
        rules_version = _require_rules_version(explanation_policy)
        limitations.append(LIMITATION_EXPLANATION_NOT_EVALUATED_UNRELIABLE_SOURCE)

    if core_visibility == EvidenceVisibility.CLIENT_SAFE:
        evidence = [
            item
            for item in evidence
            if item.visibility == EvidenceVisibility.CLIENT_SAFE
        ]
        if confidence.model_version is not None:
            raise DeliveryConfidenceIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE packs must omit delivery confidence model_version.",
            )

    return DeliveryConfidenceAssessment(
        org_id=core_org_id,
        project_id=core_project_id,
        reporting_period=core_reporting_period,
        visibility_mode=core_visibility,
        availability=availability,
        score_pct=score_pct,
        confidence_band=confidence_band,
        confidence_band_is_delivery_owned_status=True,
        current_milestone=milestone_view,
        forecast_completion_date=forecast,
        observed_at=observed_at,
        source_data_quality=source_quality,
        trend=trend,
        previous_score_pct=previous_score,
        positive_drivers=_sort_drivers(positive),
        negative_drivers=_sort_drivers(negative),
        mitigation_contribution=MitigationContributionState.UNAVAILABLE,
        limitations=_canonicalize_strings(limitations),
        source_limitations=source_limitations,
        evidence=_sort_evidence(evidence),
        source_fingerprint=core_source_fingerprint,
        previous_source_fingerprint=previous_fp,
        rules_version=rules_version,
        assessed_at=core_generated_at,
    )


def _validate_pack_or_raise(pack: ClientEvidencePack) -> None:
    role = (
        AppRole.CLIENT
        if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
        else AppRole.DELIVERY_MANAGER
    )
    result = validate_client_evidence_pack(pack, role=role)
    if not result.is_valid:
        raise EvidencePackIntegrityError(result)


def _availability_for_quality(
    quality: DataQualityState,
) -> DeliveryConfidenceAvailability:
    if quality == DataQualityState.COMPLETE:
        return DeliveryConfidenceAvailability.AVAILABLE
    if quality == DataQualityState.STALE:
        return DeliveryConfidenceAvailability.STALE
    if quality == DataQualityState.CONFLICTING:
        return DeliveryConfidenceAvailability.CONFLICTING
    if quality == DataQualityState.PARTIAL:
        return DeliveryConfidenceAvailability.PARTIAL
    if quality == DataQualityState.UNAVAILABLE:
        return DeliveryConfidenceAvailability.NO_SCORE
    raise DeliveryConfidenceIntegrityError(
        "invalid_policy_decision",
        "Unsupported Delivery Confidence source quality.",
    )


def _canonicalize_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


def _evidence_identity_key(
    item: DeliveryConfidenceEvidenceRef | ClientEvidenceReference,
) -> tuple[str, str, str, str]:
    return (
        item.source_agent.value,
        item.source_table,
        str(item.source_row_id),
        item.visibility.value,
    )


def _sort_evidence(
    refs: list[DeliveryConfidenceEvidenceRef],
) -> list[DeliveryConfidenceEvidenceRef]:
    merged: dict[
        tuple[str, str, str, str, str, str, str], DeliveryConfidenceEvidenceRef
    ] = {}
    claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
    observed_by_identity: dict[
        tuple[str, str, str, str, str, str], datetime | None
    ] = {}

    for ref in refs:
        identity = (
            *_evidence_identity_key(ref),
            ref.period.value,
            ref.source_fingerprint,
        )
        if identity in observed_by_identity:
            if observed_by_identity[identity] != ref.observed_at:
                raise DeliveryConfidenceIntegrityError(
                    "invalid_policy_decision",
                    "Conflicting observed_at on the same evidence identity.",
                )
        else:
            observed_by_identity[identity] = ref.observed_at

        key = (*identity, _observed_at_key(ref.observed_at))
        merged.setdefault(key, ref)
        claims.setdefault(key, set()).update(ref.claim_keys)

    result: list[DeliveryConfidenceEvidenceRef] = []
    for key, ref in merged.items():
        result.append(
            DeliveryConfidenceEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=sorted(claims[key]),
                period=ref.period,
                source_fingerprint=ref.source_fingerprint,
                observed_at=ref.observed_at,
            )
        )
    return sorted(
        result,
        key=lambda item: (
            item.period.value,
            item.source_fingerprint,
            *_evidence_identity_key(item),
            _observed_at_key(item.observed_at),
            tuple(item.claim_keys),
        ),
    )


def _observed_at_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _sort_drivers(
    drivers: list[DeliveryConfidenceDriver],
) -> list[DeliveryConfidenceDriver]:
    return sorted(
        drivers,
        key=lambda item: (
            item.materiality,
            item.polarity.value,
            item.driver_key,
            tuple(item.candidate_keys),
            tuple(
                (
                    ref.period.value,
                    ref.source_fingerprint,
                    *_evidence_identity_key(ref),
                    _observed_at_key(ref.observed_at),
                    tuple(ref.claim_keys),
                )
                for ref in _sort_evidence(item.evidence)
            ),
        ),
    )


def _pack_evidence_index(
    pack: ClientEvidencePack,
) -> dict[tuple[str, str, str, str], ClientEvidenceReference]:
    return {_evidence_identity_key(item): item for item in pack.evidence}


def _resolve_candidate_source_quality(
    pack: ClientEvidencePack,
    source_table: str,
) -> DataQualityState | None:
    if source_table == "delivery_confidence_scores":
        return resolve_health_source_quality(pack, "delivery_confidence_scores")

    aliases = _EVIDENCE_TABLE_TO_DQ_SOURCES.get(source_table)
    if aliases is None:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Unsupported candidate source_table for data quality resolution.",
        )
    issues = [item for item in pack.data_quality if item.source in aliases]
    if not issues:
        return None
    states = {item.state for item in issues}
    if len(states) != 1:
        return DataQualityState.CONFLICTING
    return next(iter(states))


def _require_dc_evidence(
    pack: ClientEvidencePack,
    confidence: DeliveryConfidenceFacts,
) -> list[DeliveryConfidenceEvidenceRef]:
    matches = [
        item
        for item in pack.evidence
        if item.source_table == "delivery_confidence_scores"
        and item.source_row_id == confidence.id
    ]
    if len(matches) != 1:
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Delivery Confidence must bind to exactly one matching evidence row.",
        )
    ref = matches[0]
    if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Delivery Confidence evidence source_agent is invalid.",
        )
    if not source_agent_owns_table(ref.source_agent, ref.source_table):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Delivery Confidence evidence source_agent does not own the table.",
        )
    required_claims = {"score_pct", "confidence_status", "forecast_completion_date"}
    if not required_claims.issubset(set(ref.claim_keys)):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Delivery Confidence evidence must support score and status claims.",
        )
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if not reference_supports_claim_keys(
        ref, sorted(required_claims), client_safe=client_safe
    ):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Delivery Confidence claim keys are not supported by pack evidence.",
        )
    if ref.observed_at != confidence.observed_at:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence evidence observed_at must match the source fact exactly.",
        )
    if client_safe and ref.visibility != EvidenceVisibility.CLIENT_SAFE:
        raise DeliveryConfidenceIntegrityError(
            "visibility_violation",
            "CLIENT_SAFE assessment cannot include internal confidence evidence.",
        )
    return [
        DeliveryConfidenceEvidenceRef(
            source_agent=ref.source_agent,
            source_table=ref.source_table,
            source_row_id=ref.source_row_id,
            visibility=ref.visibility,
            claim_keys=sorted(required_claims),
            period=DeliveryConfidenceEvidencePeriod.CURRENT,
            source_fingerprint=pack.source_fingerprint,
            observed_at=ref.observed_at,
        )
    ]


def _resolve_confidence_milestone(
    pack: ClientEvidencePack,
    confidence: DeliveryConfidenceFacts,
) -> DeliveryConfidenceMilestoneView:
    matches = [
        item for item in pack.delivery.milestones if item.id == confidence.milestone_id
    ]
    if len(matches) != 1:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence milestone_id must match exactly one milestone fact.",
        )
    milestone = matches[0]
    evidence_matches = [
        item
        for item in pack.evidence
        if item.source_table == "milestones" and item.source_row_id == milestone.id
    ]
    if len(evidence_matches) != 1:
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Confidence milestone must bind to exactly one milestones evidence row.",
        )
    ref = evidence_matches[0]
    claim_keys = ["milestone_id", "milestone_name", "milestone_status", "planned_date"]
    if milestone.actual_date is not None:
        claim_keys.append("actual_date")
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if not reference_supports_claim_keys(ref, claim_keys, client_safe=client_safe):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Milestone claim keys are not supported by pack evidence.",
        )
    if client_safe and (
        milestone.description is not None
        or ref.visibility != EvidenceVisibility.CLIENT_SAFE
    ):
        if milestone.description is not None:
            raise DeliveryConfidenceIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE assessments cannot expose milestone descriptions.",
            )
        raise DeliveryConfidenceIntegrityError(
            "visibility_violation",
            "CLIENT_SAFE assessment cannot include internal milestone evidence.",
        )
    return DeliveryConfidenceMilestoneView(
        milestone_id=milestone.id,
        name=milestone.name,
        status=milestone.status,
        planned_date=milestone.planned_date,
        actual_date=milestone.actual_date,
        evidence=[
            DeliveryConfidenceEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=sorted(claim_keys),
                period=DeliveryConfidenceEvidencePeriod.CURRENT,
                source_fingerprint=pack.source_fingerprint,
                observed_at=ref.observed_at,
            )
        ],
    )


def _foundation_domain_limitations(pack: ClientEvidencePack) -> list[str]:
    limitations = [
        LIMITATION_BACKLOG_SOURCE_UNAVAILABLE,
        LIMITATION_MITIGATION_SOURCE_UNAVAILABLE,
        LIMITATION_STABLE_THROUGHPUT_UNPROVEN,
        LIMITATION_PROACTIVE_QA_UNPROVEN,
    ]
    if not pack.delivery.open_risks:
        limitations.append(LIMITATION_EMPTY_RISK_NOT_POSITIVE)
    if not pack.delivery.open_bottlenecks:
        limitations.append(LIMITATION_EMPTY_BOTTLENECK_NOT_POSITIVE)
    return limitations


def _assert_previous_compatible(
    current: ClientEvidencePack, previous: ClientEvidencePack
) -> None:
    if (
        previous.project.org_id != current.project.org_id
        or previous.project.project_id != current.project.project_id
    ):
        raise DeliveryConfidenceIntegrityError(
            "incompatible_previous_pack",
            "Previous confidence pack tenant/project does not match.",
        )
    if previous.visibility_mode != current.visibility_mode:
        raise DeliveryConfidenceIntegrityError(
            "incompatible_previous_pack",
            "Previous confidence pack visibility_mode does not match.",
        )


def _compute_trend(
    current: ClientEvidencePack,
    previous: ClientEvidencePack | None,
    *,
    current_available: bool,
    current_score: Decimal | None = None,
) -> tuple[
    DeliveryConfidenceTrend,
    Decimal | None,
    str | None,
    list[str],
    list[DeliveryConfidenceEvidenceRef],
]:
    if previous is None:
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            None,
            None,
            [LIMITATION_PREVIOUS_CONFIDENCE_UNAVAILABLE],
            [],
        )

    period = current.reporting_period
    prev_period = previous.reporting_period
    if not (
        prev_period.start_date == period.previous_start_date
        and prev_period.end_date == period.previous_end_date
    ):
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            None,
            previous.source_fingerprint,
            [LIMITATION_PREVIOUS_PERIOD_MISMATCH],
            [],
        )

    try:
        prev_quality = resolve_health_source_quality(
            previous, "delivery_confidence_scores"
        )
    except Exception as exc:  # noqa: BLE001 — map to structured limitation path
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Previous Delivery Confidence source quality is inconsistent.",
        ) from exc

    prev_conf = previous.delivery.latest_delivery_confidence
    if prev_quality == DataQualityState.UNAVAILABLE or prev_conf is None:
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            None,
            previous.source_fingerprint,
            [LIMITATION_PREVIOUS_CONFIDENCE_NO_SCORE],
            [],
        )
    if prev_quality == DataQualityState.STALE:
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            None,
            previous.source_fingerprint,
            [LIMITATION_PREVIOUS_CONFIDENCE_STALE],
            [],
        )
    if prev_quality == DataQualityState.CONFLICTING:
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            None,
            previous.source_fingerprint,
            [LIMITATION_PREVIOUS_CONFIDENCE_CONFLICTING],
            [],
        )
    if prev_quality == DataQualityState.PARTIAL:
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            None,
            previous.source_fingerprint,
            [LIMITATION_PREVIOUS_CONFIDENCE_PARTIAL],
            [],
        )

    if type(prev_conf.score_pct) is float or not isinstance(prev_conf.score_pct, Decimal):
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Previous Delivery Confidence score_pct must remain Decimal-safe.",
        )

    prev_evidence = _require_dc_evidence(previous, prev_conf)
    prev_evidence = [
        item.model_copy(
            update={
                "period": DeliveryConfidenceEvidencePeriod.PREVIOUS,
                "source_fingerprint": previous.source_fingerprint,
            }
        )
        for item in prev_evidence
    ]

    if (
        not current_available
        or current_score is None
        or not isinstance(current_score, Decimal)
    ):
        return (
            DeliveryConfidenceTrend.UNKNOWN,
            prev_conf.score_pct,
            previous.source_fingerprint,
            [],
            prev_evidence,
        )

    if current_score > prev_conf.score_pct:
        trend = DeliveryConfidenceTrend.INCREASED
    elif current_score < prev_conf.score_pct:
        trend = DeliveryConfidenceTrend.DECREASED
    else:
        trend = DeliveryConfidenceTrend.STABLE
    return (
        trend,
        prev_conf.score_pct,
        previous.source_fingerprint,
        [],
        prev_evidence,
    )


def _require_rules_version(policy: DeliveryConfidenceExplanationPolicy) -> str:
    try:
        version = policy.rules_version
    except Exception as exc:  # noqa: BLE001 — sanitize policy-owned failures
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy",
            "Delivery confidence explanation policy rules_version is inaccessible.",
        ) from exc
    if not isinstance(version, str) or not version.strip():
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy",
            "Delivery confidence explanation policy rules_version must be non-empty.",
        )
    return version.strip()


def _evaluate_explanation(
    policy: DeliveryConfidenceExplanationPolicy,
    authoritative: DeliveryConfidenceCandidateContext,
) -> DeliveryConfidenceExplanationDecision:
    policy_copy = authoritative.model_copy(deep=True)
    try:
        decision = policy.evaluate(policy_copy)
    except Exception as exc:  # noqa: BLE001 — sanitize all policy-owned failures
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy",
            "Injected delivery confidence explanation policy failed during evaluation.",
        ) from exc
    if not isinstance(decision, DeliveryConfidenceExplanationDecision):
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Explanation policy did not return a DeliveryConfidenceExplanationDecision.",
        )
    return decision


def _resolve_candidate_observed_at(
    pack_ref: ClientEvidenceReference,
    fact_observed_at: datetime | None,
    *,
    fact_observed_at_authoritative: bool,
) -> datetime | None:
    if not fact_observed_at_authoritative:
        return pack_ref.observed_at
    if pack_ref.observed_at != fact_observed_at:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Candidate observed_at must exactly equal the source fact observed_at.",
        )
    return pack_ref.observed_at


def _add_candidate(
    candidates: list[DeliveryConfidenceCandidate],
    *,
    pack: ClientEvidencePack,
    key: str,
    category: DeliveryConfidenceCandidateCategory,
    value: Any,
    source_table: str,
    source_row_id: UUID,
    claim_key: str,
    fact_observed_at: datetime | None,
    fact_observed_at_authoritative: bool,
    data_quality: DataQualityState,
) -> None:
    if type(value) is float:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Float candidate values are not accepted.",
        )

    matches = [
        item
        for item in pack.evidence
        if item.source_table == source_table and item.source_row_id == source_row_id
    ]
    if len(matches) != 1:
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Candidate construction requires exactly one matching pack evidence row.",
        )
    pack_ref = matches[0]
    if not source_agent_owns_table(pack_ref.source_agent, source_table):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Candidate evidence source_agent does not own the declared table.",
        )

    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if client_safe and pack_ref.visibility != EvidenceVisibility.CLIENT_SAFE:
        raise DeliveryConfidenceIntegrityError(
            "visibility_violation",
            "CLIENT_SAFE candidates cannot use internal evidence.",
        )
    if not reference_supports_claim_keys(
        pack_ref, [claim_key], client_safe=client_safe
    ):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Candidate claim key is not supported by pack evidence.",
        )

    observed_at = _resolve_candidate_observed_at(
        pack_ref,
        fact_observed_at,
        fact_observed_at_authoritative=fact_observed_at_authoritative,
    )

    candidates.append(
        DeliveryConfidenceCandidate(
            candidate_key=key,
            category=category,
            value=value,
            source_agent=pack_ref.source_agent,
            source_table=source_table,
            source_row_id=source_row_id,
            claim_key=claim_key,
            observed_at=observed_at,
            data_quality=data_quality,
            visibility=pack_ref.visibility,
            source_fingerprint=pack.source_fingerprint,
        )
    )


def _non_complete_quality_limitation(
    source_table: str, quality: DataQualityState
) -> str | None:
    if quality not in _NON_COMPLETE_QUALITY_STATES:
        return None
    label = _SOURCE_QUALITY_LABEL.get(source_table)
    if label is None:
        return None
    return f"SOURCE_QUALITY_{quality.value.upper()}_{label}"


def _maybe_add_source_quality_limitation(
    limitations: list[str], source_table: str, quality: DataQualityState | None
) -> bool:
    if quality is None:
        limitation = _MISSING_QUALITY_LIMITATION.get(source_table)
        if limitation is not None:
            limitations.append(limitation)
        return False
    state_code = _non_complete_quality_limitation(source_table, quality)
    if state_code is not None:
        limitations.append(state_code)
    return True


def _build_candidate_context(
    pack: ClientEvidencePack,
    *,
    source_quality: DataQualityState,
) -> DeliveryConfidenceCandidateContext:
    candidates: list[DeliveryConfidenceCandidate] = []
    limitations: list[str] = []
    confidence = pack.delivery.latest_delivery_confidence
    if confidence is not None:
        _add_candidate(
            candidates,
            pack=pack,
            key="delivery_confidence.score_pct",
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            value=confidence.score_pct,
            source_table="delivery_confidence_scores",
            source_row_id=confidence.id,
            claim_key="score_pct",
            fact_observed_at=confidence.observed_at,
            fact_observed_at_authoritative=True,
            data_quality=source_quality,
        )
        _add_candidate(
            candidates,
            pack=pack,
            key="delivery_confidence.status",
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            value=confidence.status,
            source_table="delivery_confidence_scores",
            source_row_id=confidence.id,
            claim_key="confidence_status",
            fact_observed_at=confidence.observed_at,
            fact_observed_at_authoritative=True,
            data_quality=source_quality,
        )
        milestone = next(
            (
                item
                for item in pack.delivery.milestones
                if item.id == confidence.milestone_id
            ),
            None,
        )
        if milestone is not None:
            mq = _resolve_candidate_source_quality(pack, "milestones")
            if _maybe_add_source_quality_limitation(limitations, "milestones", mq):
                _add_candidate(
                    candidates,
                    pack=pack,
                    key="milestone.status",
                    category=DeliveryConfidenceCandidateCategory.MILESTONE,
                    value=milestone.status,
                    source_table="milestones",
                    source_row_id=milestone.id,
                    claim_key="milestone_status",
                    fact_observed_at=None,
                    fact_observed_at_authoritative=False,
                    data_quality=mq,
                )

    throughput = pack.delivery.latest_throughput
    if throughput is not None:
        tq = _resolve_candidate_source_quality(pack, "throughput_snapshots")
        if (
            _maybe_add_source_quality_limitation(
                limitations, "throughput_snapshots", tq
            )
            and throughput.rolling_7day_units is not None
        ):
            _add_candidate(
                candidates,
                pack=pack,
                key="throughput.rolling_7day_units",
                category=DeliveryConfidenceCandidateCategory.THROUGHPUT,
                value=throughput.rolling_7day_units,
                source_table="throughput_snapshots",
                source_row_id=throughput.id,
                claim_key="rolling_7day_units",
                fact_observed_at=None,
                fact_observed_at_authoritative=False,
                data_quality=tq,
            )
        limitations.append(LIMITATION_STABLE_THROUGHPUT_UNPROVEN)

    for snap in pack.quality.current_period:
        qq = _resolve_candidate_source_quality(pack, "quality_snapshots")
        if (
            _maybe_add_source_quality_limitation(
                limitations, "quality_snapshots", qq
            )
            and snap.rework_rate_pct is not None
        ):
            _add_candidate(
                candidates,
                pack=pack,
                key=f"quality.rework_rate.{snap.snapshot_id.hex}",
                category=DeliveryConfidenceCandidateCategory.QUALITY,
                value=snap.rework_rate_pct,
                source_table="quality_snapshots",
                source_row_id=snap.snapshot_id,
                claim_key="rework_rate_pct",
                fact_observed_at=snap.observed_at,
                fact_observed_at_authoritative=True,
                data_quality=qq,
            )
    if pack.quality.current_period:
        limitations.append(LIMITATION_PROACTIVE_QA_UNPROVEN)

    for risk in pack.delivery.open_risks:
        rq = _resolve_candidate_source_quality(pack, "risk_alerts")
        if _maybe_add_source_quality_limitation(limitations, "risk_alerts", rq):
            _add_candidate(
                candidates,
                pack=pack,
                key=f"risk.status.{risk.id.hex}",
                category=DeliveryConfidenceCandidateCategory.RISK,
                value=risk.status,
                source_table="risk_alerts",
                source_row_id=risk.id,
                claim_key="status",
                fact_observed_at=risk.observed_at,
                fact_observed_at_authoritative=True,
                data_quality=rq,
            )

    for bottleneck in pack.delivery.open_bottlenecks:
        bq = _resolve_candidate_source_quality(pack, "bottlenecks")
        if _maybe_add_source_quality_limitation(limitations, "bottlenecks", bq):
            _add_candidate(
                candidates,
                pack=pack,
                key=f"bottleneck.status.{bottleneck.id.hex}",
                category=DeliveryConfidenceCandidateCategory.BOTTLENECK,
                value=bottleneck.status,
                source_table="bottlenecks",
                source_row_id=bottleneck.id,
                claim_key="status",
                fact_observed_at=bottleneck.observed_at,
                fact_observed_at_authoritative=True,
                data_quality=bq,
            )

    for dep in pack.governance.dependencies:
        dq = _resolve_candidate_source_quality(pack, "project_dependencies")
        if _maybe_add_source_quality_limitation(
            limitations, "project_dependencies", dq
        ):
            _add_candidate(
                candidates,
                pack=pack,
                key=f"dependency.status.{dep.dependency_id.hex}",
                category=DeliveryConfidenceCandidateCategory.DEPENDENCY,
                value=dep.status,
                source_table="project_dependencies",
                source_row_id=dep.dependency_id,
                claim_key="status",
                fact_observed_at=dep.observed_at,
                fact_observed_at_authoritative=True,
                data_quality=dq,
            )

    limitations.extend(
        [
            LIMITATION_BACKLOG_SOURCE_UNAVAILABLE,
            LIMITATION_MITIGATION_SOURCE_UNAVAILABLE,
        ]
    )
    if not pack.delivery.open_risks:
        limitations.append(LIMITATION_EMPTY_RISK_NOT_POSITIVE)
    if not pack.delivery.open_bottlenecks:
        limitations.append(LIMITATION_EMPTY_BOTTLENECK_NOT_POSITIVE)

    by_key = {item.candidate_key: item for item in candidates}
    if len(by_key) != len(candidates):
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Duplicate verified candidate keys are not allowed.",
        )
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.category.value,
            item.candidate_key,
            item.source_table,
            str(item.source_row_id),
            item.claim_key,
        ),
    )
    return DeliveryConfidenceCandidateContext(
        candidates=ordered,
        context_limitations=_canonicalize_strings(limitations),
    )


def _normalize_drivers(
    decision: DeliveryConfidenceExplanationDecision,
    *,
    candidates: DeliveryConfidenceCandidateContext,
    pack: ClientEvidencePack,
    client_safe: bool,
) -> tuple[list[DeliveryConfidenceDriver], list[DeliveryConfidenceDriver]]:
    by_key = {item.candidate_key: item for item in candidates.candidates}
    positive: list[DeliveryConfidenceDriver] = []
    negative: list[DeliveryConfidenceDriver] = []
    seen_keys: set[str] = set()

    for driver in decision.positive_drivers:
        if driver.polarity != DeliveryConfidenceDriverPolarity.POSITIVE:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "POSITIVE drivers must use positive polarity.",
            )
        positive.append(
            _validate_driver(
                driver, by_key=by_key, pack=pack, client_safe=client_safe
            )
        )
        if driver.driver_key in seen_keys:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Duplicate explanation driver keys are not allowed.",
            )
        seen_keys.add(driver.driver_key)

    for driver in decision.negative_drivers:
        if driver.polarity != DeliveryConfidenceDriverPolarity.NEGATIVE:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "NEGATIVE drivers must use negative polarity.",
            )
        negative.append(
            _validate_driver(
                driver, by_key=by_key, pack=pack, client_safe=client_safe
            )
        )
        if driver.driver_key in seen_keys:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Duplicate explanation driver keys are not allowed.",
            )
        seen_keys.add(driver.driver_key)

    return positive, negative


def _validate_driver(
    driver: DeliveryConfidenceDriver,
    *,
    by_key: Mapping[str, DeliveryConfidenceCandidate],
    pack: ClientEvidencePack,
    client_safe: bool,
) -> DeliveryConfidenceDriver:
    selected: list[DeliveryConfidenceCandidate] = []
    for key in driver.candidate_keys:
        candidate = by_key.get(key)
        if candidate is None:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Explanation driver references an unknown candidate key.",
            )
        selected.append(candidate)

    if not selected:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Explanation drivers must reference at least one verified candidate.",
        )

    if not all(item.data_quality in _RELIABLE_QUALITY for item in selected):
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Material drivers cannot be supported by unreliable candidates.",
        )

    if not all(item.category == driver.category for item in selected):
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Every selected candidate category must match the driver category.",
        )

    expected_claims: dict[tuple[str, str, str, str], set[str]] = {}
    expected_observed_at: dict[tuple[str, str, str, str], datetime | None] = {}
    pack_index = _pack_evidence_index(pack)

    for candidate in selected:
        identity = _evidence_identity_key(candidate)
        expected_claims.setdefault(identity, set()).add(candidate.claim_key)
        pack_ref = pack_index.get(identity)
        if pack_ref is None:
            raise DeliveryConfidenceIntegrityError(
                "unsupported_evidence_reference",
                "Selected candidate evidence is absent from the pack.",
            )
        if identity in expected_observed_at:
            if expected_observed_at[identity] != pack_ref.observed_at:
                raise DeliveryConfidenceIntegrityError(
                    "invalid_policy_decision",
                    "Selected candidates disagree on pack evidence observed_at.",
                )
        else:
            expected_observed_at[identity] = pack_ref.observed_at
        if client_safe and candidate.visibility != EvidenceVisibility.CLIENT_SAFE:
            raise DeliveryConfidenceIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE drivers cannot use internal candidates.",
            )

    driver_claims: dict[tuple[str, str, str, str], set[str]] = {}
    for ref in driver.evidence:
        identity = _evidence_identity_key(ref)
        if identity not in expected_claims:
            raise DeliveryConfidenceIntegrityError(
                "unsupported_evidence_reference",
                "Driver evidence includes an unrelated evidence identity.",
            )
        pack_ref = pack_index.get(identity)
        if pack_ref is None:
            raise DeliveryConfidenceIntegrityError(
                "unsupported_evidence_reference",
                "Driver evidence is absent from the pack.",
            )
        if not reference_supports_claim_keys(
            pack_ref, ref.claim_keys, client_safe=client_safe
        ):
            raise DeliveryConfidenceIntegrityError(
                "unsupported_evidence_reference",
                "Driver claim keys are not supported by pack evidence.",
            )
        if client_safe and (
            ref.visibility != EvidenceVisibility.CLIENT_SAFE
            or pack_ref.visibility != EvidenceVisibility.CLIENT_SAFE
        ):
            raise DeliveryConfidenceIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE drivers cannot include internal evidence.",
            )
        if ref.period != DeliveryConfidenceEvidencePeriod.CURRENT:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Explanation drivers must reference CURRENT period evidence.",
            )
        if ref.source_fingerprint != pack.source_fingerprint:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Driver evidence source fingerprint must match the current pack.",
            )
        if ref.observed_at != pack_ref.observed_at:
            raise DeliveryConfidenceIntegrityError(
                "invalid_policy_decision",
                "Driver evidence observed_at must match pack evidence.",
            )
        driver_claims.setdefault(identity, set()).update(ref.claim_keys)

    if set(driver_claims) != set(expected_claims):
        raise DeliveryConfidenceIntegrityError(
            "unsupported_evidence_reference",
            "Driver evidence must include every selected candidate evidence identity.",
        )

    for identity, expected in expected_claims.items():
        actual = driver_claims.get(identity)
        if actual is None or actual != expected:
            raise DeliveryConfidenceIntegrityError(
                "unsupported_evidence_reference",
                "Driver evidence claim keys must exactly match selected candidates.",
            )

    aggregate_quality = (
        DataQualityState.COMPLETE
        if all(item.data_quality == DataQualityState.COMPLETE for item in selected)
        else DataQualityState.CONFLICTING
    )
    if driver.data_quality != aggregate_quality:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Driver data_quality must match the aggregate of selected candidates.",
        )
    if driver.data_quality not in _RELIABLE_QUALITY:
        raise DeliveryConfidenceIntegrityError(
            "invalid_policy_decision",
            "Material drivers must declare COMPLETE data quality.",
        )

    normalized_evidence: list[DeliveryConfidenceEvidenceRef] = []
    for identity, claims in sorted(expected_claims.items()):
        template = next(
            ref for ref in driver.evidence if _evidence_identity_key(ref) == identity
        )
        normalized_evidence.append(
            DeliveryConfidenceEvidenceRef(
                source_agent=template.source_agent,
                source_table=template.source_table,
                source_row_id=template.source_row_id,
                visibility=template.visibility,
                claim_keys=sorted(claims),
                period=template.period,
                source_fingerprint=template.source_fingerprint,
                observed_at=expected_observed_at[identity],
            )
        )

    return driver.model_copy(
        update={"evidence": _sort_evidence(normalized_evidence)}
    )
