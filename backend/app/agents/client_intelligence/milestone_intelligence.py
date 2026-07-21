"""Deterministic Milestone Intelligence foundation (roadmap 8.6 / TASK 15).

Consumes Delivery-owned milestone facts from a validated ClientEvidencePack.
No policy, LLM, forecast milestone dates, numeric progress, or milestone
dependency linkage is invented.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    DataQualityState,
    DeliveryConfidenceFacts,
    EvidenceVisibility,
    MilestoneFacts,
    ReportingPeriod,
    RiskAlertFacts,
    SourceAgent,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    reference_supports_claim_keys,
    source_agent_owns_table,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.milestone_intelligence_contracts import (
    LIMITATION_MILESTONE_CONFIDENCE_CONFLICTING,
    LIMITATION_MILESTONE_CONFIDENCE_MILESTONE_MISMATCH,
    LIMITATION_MILESTONE_CONFIDENCE_PARTIAL,
    LIMITATION_MILESTONE_CONFIDENCE_STALE,
    LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE,
    LIMITATION_MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE,
    LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE,
    LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE,
    LIMITATION_MILESTONE_SOURCE_UNAVAILABLE,
    LIMITATION_MILESTONE_STATUS_UNRECOGNIZED,
    LIMITATION_NEXT_MILESTONE_COMPLETED,
    LIMITATION_NEXT_MILESTONE_ID_UNAVAILABLE,
    LIMITATION_NEXT_MILESTONE_ID_UNKNOWN,
    LIMITATION_NO_SUPPORTED_MILESTONE_BLOCKER,
    LIMITATION_SELECTED_PERIOD_EMPTY_POPULATION,
    AtRiskMilestoneItem,
    MilestoneBlockerCollection,
    MilestoneBlockerItem,
    MilestoneBlockerState,
    MilestoneConfidenceAvailability,
    MilestoneConfidenceView,
    MilestoneDependencyState,
    MilestoneDependencyView,
    MilestoneEvidencePeriod,
    MilestoneEvidenceRef,
    MilestoneIntelligenceAssessment,
    MilestoneIntelligenceAvailability,
    MilestonePeriodCounts,
    MilestonePeriodItem,
    MilestoneProgressView,
    NextKeyMilestoneView,
    _canonicalize_source_limitations,
    _evidence_lineage_key,
    _evidence_sort_key,
    reason_code_for_status,
)
from app.db.models import AppRole

LIMITATION_SOURCE_QUALITY_STALE_MILESTONES = "SOURCE_QUALITY_STALE_MILESTONES"
LIMITATION_SOURCE_QUALITY_PARTIAL_MILESTONES = "SOURCE_QUALITY_PARTIAL_MILESTONES"
LIMITATION_SOURCE_QUALITY_CONFLICTING_MILESTONES = (
    "SOURCE_QUALITY_CONFLICTING_MILESTONES"
)

_OPEN_RISK_STATUSES = frozenset({"open", "acknowledged"})
_AT_RISK_STATUSES = frozenset({"at_risk", "missed"})
_STATUS_BUCKETS = frozenset({"on_track", "at_risk", "missed", "completed", "pending"})
_COMPLETED_STATUS = "completed"

_REQUIRED_MILESTONE_CLAIMS = [
    "milestone_id",
    "milestone_name",
    "milestone_status",
    "planned_date",
]
_REQUIRED_CONFIDENCE_CLAIMS = [
    "score_pct",
    "confidence_status",
    "forecast_completion_date",
]
_REQUIRED_RISK_BLOCKER_CLAIMS = [
    "risk_id",
    "risk_title",
    "risk_tier",
    "alert_type",
    "status",
]

_QUALITY_STATE_LIMITATIONS: dict[DataQualityState, str] = {
    DataQualityState.STALE: LIMITATION_SOURCE_QUALITY_STALE_MILESTONES,
    DataQualityState.PARTIAL: LIMITATION_SOURCE_QUALITY_PARTIAL_MILESTONES,
    DataQualityState.CONFLICTING: LIMITATION_SOURCE_QUALITY_CONFLICTING_MILESTONES,
    DataQualityState.UNAVAILABLE: LIMITATION_MILESTONE_SOURCE_UNAVAILABLE,
}


class MilestoneIntelligenceIntegrityError(Exception):
    """Deterministic Milestone Intelligence integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def assess_milestone_intelligence(
    pack: ClientEvidencePack,
    *,
    generated_at: datetime | None = None,
) -> MilestoneIntelligenceAssessment:
    """Build a Milestone Intelligence assessment from a validated evidence pack."""
    working = pack.model_copy(deep=True)
    _validate_pack_or_raise(working)

    source_limitations = _canonicalize_source_limitations(list(working.limitations))
    limitations = [
        LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE,
        LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE,
        LIMITATION_MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE,
    ]

    core_org_id = working.project.org_id
    core_project_id = working.project.project_id
    core_period = working.reporting_period
    core_as_of = core_period.as_of
    core_visibility = working.visibility_mode
    core_source_fingerprint = working.source_fingerprint
    core_generated_at = generated_at if generated_at is not None else working.generated_at
    if core_generated_at.tzinfo is None:
        raise MilestoneIntelligenceIntegrityError(
            "invalid_assessment_time",
            "generated_at must be timezone-aware.",
        )

    source_next_milestone_id = working.delivery.next_milestone_id
    milestone_quality = _resolve_milestone_quality(working)
    limitations.extend(_quality_limitations(milestone_quality))

    if milestone_quality == DataQualityState.CONFLICTING:
        return MilestoneIntelligenceAssessment(
            org_id=core_org_id,
            project_id=core_project_id,
            reporting_period=core_period,
            as_of=core_as_of,
            visibility_mode=core_visibility,
            availability=MilestoneIntelligenceAvailability.CONFLICTING,
            data_quality=DataQualityState.CONFLICTING,
            period_counts=_empty_counts(),
            selected_period_items=[],
            at_risk_items=[],
            source_next_milestone_id=None,
            next_key_milestone=None,
            evidence=[],
            limitations=_canonicalize_strings(limitations),
            source_limitations=source_limitations,
            source_fingerprint=core_source_fingerprint,
            generated_at=core_generated_at,
        )

    if milestone_quality == DataQualityState.UNAVAILABLE:
        return MilestoneIntelligenceAssessment(
            org_id=core_org_id,
            project_id=core_project_id,
            reporting_period=core_period,
            as_of=core_as_of,
            visibility_mode=core_visibility,
            availability=MilestoneIntelligenceAvailability.UNAVAILABLE,
            data_quality=DataQualityState.UNAVAILABLE,
            period_counts=_empty_counts(),
            selected_period_items=[],
            at_risk_items=[],
            source_next_milestone_id=None,
            next_key_milestone=None,
            evidence=[],
            limitations=_canonicalize_strings(limitations),
            source_limitations=source_limitations,
            source_fingerprint=core_source_fingerprint,
            generated_at=core_generated_at,
        )

    selected = _selected_period_milestones(working.delivery.milestones, core_period)
    selected_items = [
        _build_period_item(
            working,
            milestone=milestone,
            reporting_period=core_period,
            org_id=core_org_id,
            project_id=core_project_id,
            source_fingerprint=core_source_fingerprint,
        )
        for milestone in selected
    ]
    period_counts = _counts_from_items(selected_items)
    if period_counts.total_count == 0:
        limitations.append(LIMITATION_SELECTED_PERIOD_EMPTY_POPULATION)
    if period_counts.unclassified_count > 0:
        limitations.append(LIMITATION_MILESTONE_STATUS_UNRECOGNIZED)

    at_risk_items = [
        _build_at_risk_item(item)
        for item in selected_items
        if item.status in _AT_RISK_STATUSES
    ]

    next_key_milestone, next_limits = _resolve_next_key_milestone(
        working,
        reporting_period=core_period,
        org_id=core_org_id,
        project_id=core_project_id,
        source_fingerprint=core_source_fingerprint,
    )
    limitations.extend(next_limits)

    evidence = _aggregate_evidence(selected_items, at_risk_items, next_key_milestone)
    availability = _availability_from_quality(
        milestone_quality,
        has_selected_population=period_counts.total_count > 0,
        next_milestone_present=next_key_milestone is not None,
        has_unclassified=period_counts.unclassified_count > 0,
    )

    return MilestoneIntelligenceAssessment(
        org_id=core_org_id,
        project_id=core_project_id,
        reporting_period=core_period,
        as_of=core_as_of,
        visibility_mode=core_visibility,
        availability=availability,
        data_quality=milestone_quality,
        period_counts=period_counts,
        selected_period_items=selected_items,
        at_risk_items=at_risk_items,
        source_next_milestone_id=source_next_milestone_id,
        next_key_milestone=next_key_milestone,
        evidence=evidence,
        limitations=_canonicalize_strings(limitations),
        source_limitations=source_limitations,
        source_fingerprint=core_source_fingerprint,
        generated_at=core_generated_at,
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


def _canonicalize_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


def _empty_counts() -> MilestonePeriodCounts:
    return MilestonePeriodCounts(
        total_count=0,
        on_track_count=0,
        at_risk_count=0,
        missed_count=0,
        completed_count=0,
        pending_count=0,
        unclassified_count=0,
    )


def _resolve_milestone_quality(pack: ClientEvidencePack) -> DataQualityState:
    states = [issue.state for issue in pack.data_quality if issue.source == "milestones"]
    if not states:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_source_quality_missing",
            "Milestone source quality is not declared in the pack.",
        )
    unique = set(states)
    if len(unique) != 1:
        return DataQualityState.CONFLICTING
    state = next(iter(unique))
    facts_present = bool(pack.delivery.milestones)
    if state == DataQualityState.UNAVAILABLE and facts_present:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_fact_quality_mismatch",
            "Milestone fact presence disagrees with pack quality.",
        )
    if state != DataQualityState.UNAVAILABLE and not facts_present:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_fact_quality_mismatch",
            "Milestone facts are absent without matching UNAVAILABLE quality.",
        )
    return state


def _resolve_confidence_quality(pack: ClientEvidencePack) -> DataQualityState | None:
    states = [
        issue.state
        for issue in pack.data_quality
        if issue.source in {"delivery_confidence_scores", "delivery_confidence"}
    ]
    if not states:
        return None
    unique = set(states)
    if len(unique) != 1:
        return DataQualityState.CONFLICTING
    return next(iter(unique))


def _quality_limitations(quality: DataQualityState) -> list[str]:
    code = _QUALITY_STATE_LIMITATIONS.get(quality)
    return [code] if code is not None else []


def _confidence_quality_limitations(quality: DataQualityState | None) -> list[str]:
    if quality is None:
        return [LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE]
    if quality == DataQualityState.COMPLETE:
        return []
    if quality == DataQualityState.STALE:
        return [LIMITATION_MILESTONE_CONFIDENCE_STALE]
    if quality == DataQualityState.PARTIAL:
        return [LIMITATION_MILESTONE_CONFIDENCE_PARTIAL]
    if quality == DataQualityState.CONFLICTING:
        return [LIMITATION_MILESTONE_CONFIDENCE_CONFLICTING]
    return [LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE]


def _selected_period_milestones(
    milestones: list[MilestoneFacts],
    reporting_period: ReportingPeriod,
) -> list[MilestoneFacts]:
    selected = [
        milestone
        for milestone in milestones
        if reporting_period.start_date
        <= milestone.planned_date
        <= reporting_period.as_of
    ]
    return sorted(selected, key=lambda item: (item.planned_date, str(item.id)))


def _counts_from_items(items: list[MilestonePeriodItem]) -> MilestonePeriodCounts:
    counts = {
        "on_track": 0,
        "at_risk": 0,
        "missed": 0,
        "completed": 0,
        "pending": 0,
        "unclassified": 0,
    }
    for item in items:
        if item.status in _STATUS_BUCKETS:
            counts[item.status] += 1
        else:
            counts["unclassified"] += 1
    return MilestonePeriodCounts(
        total_count=len(items),
        on_track_count=counts["on_track"],
        at_risk_count=counts["at_risk"],
        missed_count=counts["missed"],
        completed_count=counts["completed"],
        pending_count=counts["pending"],
        unclassified_count=counts["unclassified"],
    )


def _default_dependency() -> MilestoneDependencyView:
    return MilestoneDependencyView(
        state=MilestoneDependencyState.UNAVAILABLE,
        limitations=[LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE],
    )


def _unavailable_confidence(
    limitations: list[str],
    *,
    availability: MilestoneConfidenceAvailability = MilestoneConfidenceAvailability.UNAVAILABLE,
) -> MilestoneConfidenceView:
    return MilestoneConfidenceView(
        availability=availability,
        confidence_id=None,
        milestone_id=None,
        score_pct=None,
        confidence_status=None,
        forecast_completion_date=None,
        data_quality=None,
        evidence=[],
        limitations=_canonicalize_strings(
            limitations or [LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE]
        ),
    )


def _available_confidence(
    *,
    pack: ClientEvidencePack,
    confidence: DeliveryConfidenceFacts,
    milestone_id: UUID,
    source_fingerprint: str,
) -> MilestoneConfidenceView:
    evidence = _confidence_evidence_refs(
        pack,
        confidence=confidence,
        source_fingerprint=source_fingerprint,
    )
    return MilestoneConfidenceView(
        availability=MilestoneConfidenceAvailability.AVAILABLE,
        confidence_id=confidence.id,
        milestone_id=milestone_id,
        score_pct=confidence.score_pct,
        confidence_status=confidence.status,
        forecast_completion_date=confidence.forecast_completion_date,
        data_quality=DataQualityState.COMPLETE,
        evidence=evidence,
        limitations=[],
    )


def _resolve_confidence_view(
    pack: ClientEvidencePack,
    *,
    milestone_id: UUID,
    source_fingerprint: str,
) -> MilestoneConfidenceView:
    confidence = pack.delivery.latest_delivery_confidence
    quality = _resolve_confidence_quality(pack)

    if confidence is None:
        return _unavailable_confidence(_confidence_quality_limitations(quality))

    if confidence.milestone_id != milestone_id:
        return _unavailable_confidence(
            [
                LIMITATION_MILESTONE_CONFIDENCE_MILESTONE_MISMATCH,
                LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE,
            ],
            availability=MilestoneConfidenceAvailability.MISMATCH,
        )

    quality_limits = _confidence_quality_limitations(quality)
    if quality != DataQualityState.COMPLETE:
        availability = {
            DataQualityState.STALE: MilestoneConfidenceAvailability.STALE,
            DataQualityState.PARTIAL: MilestoneConfidenceAvailability.PARTIAL,
            DataQualityState.CONFLICTING: MilestoneConfidenceAvailability.CONFLICTING,
        }.get(quality, MilestoneConfidenceAvailability.UNAVAILABLE)
        return MilestoneConfidenceView(
            availability=availability,
            confidence_id=None,
            milestone_id=None,
            score_pct=None,
            confidence_status=None,
            forecast_completion_date=None,
            data_quality=quality,
            evidence=[],
            limitations=_canonicalize_strings(quality_limits),
        )

    return _available_confidence(
        pack=pack,
        confidence=confidence,
        milestone_id=milestone_id,
        source_fingerprint=source_fingerprint,
    )


def _resolve_blocker_collection(
    pack: ClientEvidencePack,
    *,
    milestone_id: UUID,
    source_fingerprint: str,
) -> MilestoneBlockerCollection:
    if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return MilestoneBlockerCollection(
            state=MilestoneBlockerState.NO_SUPPORTED_BLOCKER,
            blockers=[],
            limitations=[LIMITATION_NO_SUPPORTED_MILESTONE_BLOCKER],
        )

    blockers = [
        risk
        for risk in pack.delivery.open_risks
        if risk.milestone_id == milestone_id and risk.status in _OPEN_RISK_STATUSES
    ]
    blockers.sort(
        key=lambda risk: (
            risk.observed_at.isoformat() if risk.observed_at is not None else "",
            str(risk.id),
        )
    )
    if not blockers:
        return MilestoneBlockerCollection(
            state=MilestoneBlockerState.NO_SUPPORTED_BLOCKER,
            blockers=[],
            limitations=[LIMITATION_NO_SUPPORTED_MILESTONE_BLOCKER],
        )

    items = [
        MilestoneBlockerItem(
            risk_id=risk.id,
            milestone_id=milestone_id,
            alert_type=risk.alert_type,
            risk_tier=risk.risk_tier,
            status=risk.status,
            evidence=_risk_blocker_evidence_refs(
                pack,
                risk=risk,
                source_fingerprint=source_fingerprint,
            ),
        )
        for risk in blockers
    ]
    return MilestoneBlockerCollection(
        state=MilestoneBlockerState.PRESENT,
        blockers=items,
        limitations=[],
    )


def _build_period_item(
    pack: ClientEvidencePack,
    *,
    milestone: MilestoneFacts,
    reporting_period: ReportingPeriod,
    org_id: UUID,
    project_id: UUID,
    source_fingerprint: str,
) -> MilestonePeriodItem:
    return MilestonePeriodItem(
        **_milestone_common_fields(
            pack,
            milestone=milestone,
            reporting_period=reporting_period,
            org_id=org_id,
            project_id=project_id,
            source_fingerprint=source_fingerprint,
        )
    )


def _milestone_common_fields(
    pack: ClientEvidencePack,
    *,
    milestone: MilestoneFacts,
    reporting_period: ReportingPeriod,
    org_id: UUID,
    project_id: UUID,
    source_fingerprint: str,
) -> dict:
    milestone_evidence = _milestone_evidence_refs(
        pack,
        milestone=milestone,
        source_fingerprint=source_fingerprint,
    )
    return {
        "org_id": org_id,
        "project_id": project_id,
        "reporting_period": reporting_period,
        "milestone_id": milestone.id,
        "name": milestone.name,
        "status": milestone.status,
        "planned_date": milestone.planned_date,
        "actual_date": milestone.actual_date,
        "revised_date": None,
        "expected_date": None,
        "forecast_date": None,
        "progress": MilestoneProgressView(
            progress_state=milestone.status,
            progress_pct=None,
            limitations=[LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE],
        ),
        "confidence": _resolve_confidence_view(
            pack,
            milestone_id=milestone.id,
            source_fingerprint=source_fingerprint,
        ),
        "blockers": _resolve_blocker_collection(
            pack,
            milestone_id=milestone.id,
            source_fingerprint=source_fingerprint,
        ),
        "dependency": _default_dependency(),
        "source_fingerprint": source_fingerprint,
        "evidence": milestone_evidence,
    }


def _build_at_risk_item(item: MilestonePeriodItem) -> AtRiskMilestoneItem:
    reason = reason_code_for_status(item.status)
    if reason is None:
        raise MilestoneIntelligenceIntegrityError(
            "invalid_at_risk_item",
            "At-risk item requires explicit at_risk or missed status.",
        )
    return AtRiskMilestoneItem(
        org_id=item.org_id,
        project_id=item.project_id,
        reporting_period=item.reporting_period,
        milestone_id=item.milestone_id,
        name=item.name,
        status=item.status,
        planned_date=item.planned_date,
        actual_date=item.actual_date,
        reason_codes=[reason],
        progress=item.progress,
        confidence=item.confidence,
        blockers=item.blockers,
        dependency=item.dependency,
        source_fingerprint=item.source_fingerprint,
        evidence=item.evidence,
    )


def _resolve_next_key_milestone(
    pack: ClientEvidencePack,
    *,
    reporting_period: ReportingPeriod,
    org_id: UUID,
    project_id: UUID,
    source_fingerprint: str,
) -> tuple[NextKeyMilestoneView | None, list[str]]:
    limitations: list[str] = []
    next_id = pack.delivery.next_milestone_id
    if next_id is None:
        limitations.append(LIMITATION_NEXT_MILESTONE_ID_UNAVAILABLE)
        return None, limitations

    matches = [item for item in pack.delivery.milestones if item.id == next_id]
    if len(matches) != 1:
        limitations.append(LIMITATION_NEXT_MILESTONE_ID_UNKNOWN)
        return None, limitations

    milestone = matches[0]
    if milestone.status == _COMPLETED_STATUS:
        limitations.append(LIMITATION_NEXT_MILESTONE_COMPLETED)
        return None, limitations

    period_item_fields = _milestone_common_fields(
        pack,
        milestone=milestone,
        reporting_period=reporting_period,
        org_id=org_id,
        project_id=project_id,
        source_fingerprint=source_fingerprint,
    )
    return (
        NextKeyMilestoneView(**period_item_fields),
        limitations,
    )


def _published_visibility(pack: ClientEvidencePack) -> EvidenceVisibility:
    return pack.visibility_mode


def _milestone_evidence_refs(
    pack: ClientEvidencePack,
    *,
    milestone: MilestoneFacts,
    source_fingerprint: str,
) -> list[MilestoneEvidenceRef]:
    matches = [
        item
        for item in pack.evidence
        if item.source_table == "milestones" and item.source_row_id == milestone.id
    ]
    if len(matches) != 1:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_evidence_mismatch",
            "Milestone must bind to exactly one milestones evidence row.",
        )
    ref = matches[0]
    claim_keys = list(_REQUIRED_MILESTONE_CLAIMS)
    if milestone.actual_date is not None:
        claim_keys.append("actual_date")
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if not reference_supports_claim_keys(ref, claim_keys, client_safe=client_safe):
        raise MilestoneIntelligenceIntegrityError(
            "milestone_evidence_mismatch",
            "Milestone claim keys are not supported by pack evidence.",
        )
    if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_evidence_mismatch",
            "Milestone evidence source_agent must be delivery_performance.",
        )
    if not source_agent_owns_table(ref.source_agent, ref.source_table):
        raise MilestoneIntelligenceIntegrityError(
            "milestone_evidence_mismatch",
            "Milestone evidence source ownership mismatch.",
        )
    if client_safe and ref.visibility != EvidenceVisibility.CLIENT_SAFE:
        raise MilestoneIntelligenceIntegrityError(
            "visibility_violation",
            "CLIENT_SAFE assessment cannot include internal milestone evidence.",
        )
    return [
        MilestoneEvidenceRef(
            source_agent=ref.source_agent,
            source_table=ref.source_table,
            source_row_id=ref.source_row_id,
            visibility=_published_visibility(pack),
            claim_keys=sorted(claim_keys),
            period=MilestoneEvidencePeriod.CURRENT,
            source_fingerprint=source_fingerprint,
            observed_at=ref.observed_at,
        )
    ]


def _confidence_evidence_refs(
    pack: ClientEvidencePack,
    *,
    confidence: DeliveryConfidenceFacts,
    source_fingerprint: str,
) -> list[MilestoneEvidenceRef]:
    matches = [
        item
        for item in pack.evidence
        if item.source_table == "delivery_confidence_scores"
        and item.source_row_id == confidence.id
    ]
    if len(matches) != 1:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_confidence_evidence_mismatch",
            "Confidence must bind to exactly one delivery_confidence_scores row.",
        )
    ref = matches[0]
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if not reference_supports_claim_keys(
        ref, _REQUIRED_CONFIDENCE_CLAIMS, client_safe=client_safe
    ):
        raise MilestoneIntelligenceIntegrityError(
            "milestone_confidence_evidence_mismatch",
            "Confidence claim keys are not supported by pack evidence.",
        )
    if ref.observed_at != confidence.observed_at:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_confidence_evidence_mismatch",
            "Confidence evidence observed_at must match the source fact exactly.",
        )
    if client_safe and ref.visibility != EvidenceVisibility.CLIENT_SAFE:
        raise MilestoneIntelligenceIntegrityError(
            "visibility_violation",
            "CLIENT_SAFE assessment cannot include internal confidence evidence.",
        )
    return [
        MilestoneEvidenceRef(
            source_agent=ref.source_agent,
            source_table=ref.source_table,
            source_row_id=ref.source_row_id,
            visibility=_published_visibility(pack),
            claim_keys=sorted(_REQUIRED_CONFIDENCE_CLAIMS),
            period=MilestoneEvidencePeriod.CURRENT,
            source_fingerprint=source_fingerprint,
            observed_at=ref.observed_at,
        )
    ]


def _risk_blocker_evidence_refs(
    pack: ClientEvidencePack,
    *,
    risk: RiskAlertFacts,
    source_fingerprint: str,
) -> list[MilestoneEvidenceRef]:
    matches = [
        item
        for item in pack.evidence
        if item.source_table == "risk_alerts" and item.source_row_id == risk.id
    ]
    if len(matches) != 1:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_blocker_evidence_mismatch",
            "Blocker risk must bind to exactly one risk_alerts evidence row.",
        )
    ref = matches[0]
    if not reference_supports_claim_keys(
        ref, _REQUIRED_RISK_BLOCKER_CLAIMS, client_safe=False
    ):
        raise MilestoneIntelligenceIntegrityError(
            "milestone_blocker_evidence_mismatch",
            "Risk blocker claim keys are not supported by pack evidence.",
        )
    if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
        raise MilestoneIntelligenceIntegrityError(
            "milestone_blocker_evidence_mismatch",
            "Risk blocker evidence source_agent must be delivery_performance.",
        )
    return [
        MilestoneEvidenceRef(
            source_agent=ref.source_agent,
            source_table=ref.source_table,
            source_row_id=ref.source_row_id,
            visibility=_published_visibility(pack),
            claim_keys=sorted(_REQUIRED_RISK_BLOCKER_CLAIMS),
            period=MilestoneEvidencePeriod.CURRENT,
            source_fingerprint=source_fingerprint,
            observed_at=ref.observed_at,
        )
    ]


def _aggregate_evidence(
    selected_items: list[MilestonePeriodItem],
    at_risk_items: list[AtRiskMilestoneItem],
    next_key_milestone: NextKeyMilestoneView | None,
) -> list[MilestoneEvidenceRef]:
    by_lineage: dict[tuple[str, str, str, str, str, str, str], MilestoneEvidenceRef] = {}

    def _ingest(refs: list[MilestoneEvidenceRef]) -> None:
        for ref in refs:
            key = _evidence_lineage_key(ref)
            existing = by_lineage.get(key)
            if existing is None:
                by_lineage[key] = ref
                continue
            if existing.claim_keys != ref.claim_keys:
                raise MilestoneIntelligenceIntegrityError(
                    "milestone_evidence_conflict",
                    "Conflicting claim sets for the same evidence lineage.",
                )

    for item in selected_items:
        _ingest(item.evidence)
        _ingest(item.confidence.evidence)
        for blocker in item.blockers.blockers:
            _ingest(blocker.evidence)
    for item in at_risk_items:
        _ingest(item.evidence)
        _ingest(item.confidence.evidence)
        for blocker in item.blockers.blockers:
            _ingest(blocker.evidence)
    if next_key_milestone is not None:
        _ingest(next_key_milestone.evidence)
        _ingest(next_key_milestone.confidence.evidence)
        for blocker in next_key_milestone.blockers.blockers:
            _ingest(blocker.evidence)

    return sorted(by_lineage.values(), key=_evidence_sort_key)


def _availability_from_quality(
    quality: DataQualityState,
    *,
    has_selected_population: bool,
    next_milestone_present: bool,
    has_unclassified: bool,
) -> MilestoneIntelligenceAvailability:
    """Map source quality to availability. TASK 15 never returns AVAILABLE.

    Empty selected-period populations and missing next milestones remain
    PARTIAL/STALE with structured limitations rather than UNAVAILABLE, so
    reliable selected-period counts can still be published when present.
    Unclassified statuses also keep availability at most PARTIAL.
    """
    if quality == DataQualityState.STALE:
        return MilestoneIntelligenceAvailability.STALE
    if quality in {DataQualityState.PARTIAL, DataQualityState.COMPLETE}:
        _ = (has_selected_population, next_milestone_present, has_unclassified)
        return MilestoneIntelligenceAvailability.PARTIAL
    return MilestoneIntelligenceAvailability.UNAVAILABLE
