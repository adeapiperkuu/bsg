"""Client Intelligence Delivery Confidence Intelligence tests (TASK 11).

Fixture explanation policies are test-only — not production thresholds.
CI-DQ07 remains unresolved. Score/band remain Delivery-owned.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agents.client_intelligence import (
    BottleneckFacts,
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryConfidenceAssessment,
    DeliveryConfidenceAvailability,
    DeliveryConfidenceCandidateCategory,
    DeliveryConfidenceCandidateContext,
    DeliveryConfidenceDriver,
    DeliveryConfidenceDriverPolarity,
    DeliveryConfidenceEvidencePeriod,
    DeliveryConfidenceEvidenceRef,
    DeliveryConfidenceExplanationDecision,
    DeliveryConfidenceFacts,
    DeliveryConfidenceIntegrityError,
    DeliveryConfidenceMilestoneView,
    DeliveryConfidenceTrend,
    DeliveryEvidenceFacts,
    EvidencePackIntegrityError,
    EvidenceVisibility,
    GovernanceDependencyFacts,
    GovernanceEvidenceFacts,
    KnowledgeEvidenceFacts,
    KnowledgeSourceAvailabilityFacts,
    MilestoneFacts,
    MitigationContributionState,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    QualitySnapshotFacts,
    RiskAlertFacts,
    SourceAgent,
    ThroughputSnapshotFacts,
    WorkforceEvidenceFacts,
    assess_delivery_confidence,
    finalize_pack_collections,
    resolve_reporting_period,
)
from app.agents.client_intelligence.delivery_confidence_intelligence import (
    LIMITATION_BACKLOG_SOURCE_UNAVAILABLE,
    LIMITATION_DELIVERY_CONFIDENCE_UNAVAILABLE,
    LIMITATION_EXPLANATION_NOT_EVALUATED_NO_SCORE,
    LIMITATION_EXPLANATION_NOT_EVALUATED_UNRELIABLE_SOURCE,
    LIMITATION_EXPLANATION_POLICY_UNAVAILABLE,
    LIMITATION_MITIGATION_SOURCE_UNAVAILABLE,
    LIMITATION_PREVIOUS_CONFIDENCE_UNAVAILABLE,
    LIMITATION_PREVIOUS_PERIOD_MISMATCH,
    LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS,
    LIMITATION_SOURCE_QUALITY_MISSING_GOVERNANCE_DEPENDENCIES,
    LIMITATION_SOURCE_QUALITY_MISSING_QUALITY_SNAPSHOTS,
    LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS,
    LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS,
    _build_candidate_context,
    _sort_evidence,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    worst_data_quality_state,
)
from app.agents.client_intelligence.evidence_validation import finalize_data_quality_issues

_AS_OF = date(2026, 6, 18)
_ORG = UUID("33333333-3333-4333-8333-333333333333")
_TEST_RULES = "test.fixture.delivery_confidence.v1"


def _knowledge_availability() -> list[KnowledgeSourceAvailabilityFacts]:
    rows: list[KnowledgeSourceAvailabilityFacts] = []
    for requirement_id, source_type in (
        ("CI-D11", "sop"),
        ("CI-D12", "training_document"),
        ("CI-D13", "project_charter"),
        ("CI-D14", "client_communication"),
        ("CI-D15", "escalation_note"),
    ):
        rows.append(
            KnowledgeSourceAvailabilityFacts(
                requirement_id=requirement_id,
                source_type=source_type,
                document_count=0,
                chunk_count=0,
                state=DataQualityState.UNAVAILABLE,
                limitation="No approved documents.",
            )
        )
    return rows


def _ref(
    *,
    source_table: str,
    source_row_id: UUID,
    description: str,
    visibility: EvidenceVisibility,
    claim_keys: list[str],
    observed_at: datetime | None = None,
) -> ClientEvidenceReference:
    return ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table=source_table,
        source_row_id=source_row_id,
        description=description,
        visibility=visibility,
        observed_at=observed_at,
        claim_keys=claim_keys,
    )


def _base_pack(
    *,
    visibility_mode: EvidenceVisibility = EvidenceVisibility.INTERNAL,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    confidence_score: Decimal | None = Decimal("88.50"),
    confidence_status: str = "confident",
    as_of: date = _AS_OF,
    limitations: list[str] | None = None,
    next_milestone_different: bool = False,
) -> ClientEvidencePack:
    pid = project_id or uuid4()
    oid = org_id or _ORG
    period = resolve_reporting_period(as_of)
    milestone_id = uuid4()
    other_milestone_id = uuid4()
    confidence_id = uuid4()
    milestones = [
        MilestoneFacts(
            id=milestone_id,
            name="Batch 14",
            planned_date=date(2026, 7, 1),
            actual_date=None,
            status="planned",
            description=None
            if visibility_mode == EvidenceVisibility.CLIENT_SAFE
            else "internal note",
        )
    ]
    if next_milestone_different:
        milestones.append(
            MilestoneFacts(
                id=other_milestone_id,
                name="Batch 15",
                planned_date=date(2026, 8, 1),
                actual_date=None,
                status="planned",
                description=None,
            )
        )
    refs = [
        _ref(
            source_table="projects",
            source_row_id=pid,
            description="project",
            visibility=EvidenceVisibility.CLIENT_SAFE,
            claim_keys=["project_id", "project_name", "project_status"],
        ),
        _ref(
            source_table="milestones",
            source_row_id=milestone_id,
            description="milestone",
            visibility=EvidenceVisibility.CLIENT_SAFE,
            observed_at=datetime(2026, 6, 1, tzinfo=UTC),
            claim_keys=[
                "milestone_id",
                "milestone_name",
                "milestone_status",
                "planned_date",
            ],
        ),
    ]
    if next_milestone_different:
        refs.append(
            _ref(
                source_table="milestones",
                source_row_id=other_milestone_id,
                description="next milestone",
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=datetime(2026, 6, 1, tzinfo=UTC),
                claim_keys=[
                    "milestone_id",
                    "milestone_name",
                    "milestone_status",
                    "planned_date",
                ],
            )
        )
    confidence: DeliveryConfidenceFacts | None = None
    if confidence_score is not None:
        confidence = DeliveryConfidenceFacts(
            id=confidence_id,
            milestone_id=milestone_id,
            score_pct=confidence_score,
            status=confidence_status,
            forecast_completion_date=date(2026, 7, 15),
            model_version=None
            if visibility_mode == EvidenceVisibility.CLIENT_SAFE
            else "delivery-v1",
            observed_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        refs.append(
            _ref(
                source_table="delivery_confidence_scores",
                source_row_id=confidence_id,
                description="confidence",
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=datetime(2026, 6, 10, tzinfo=UTC),
                claim_keys=[
                    "score_pct",
                    "confidence_status",
                    "forecast_completion_date",
                ],
            )
        )
    dq = [
        DataQualityIssue(
            source="milestones",
            state=DataQualityState.COMPLETE,
            detail="ok",
        ),
        DataQualityIssue(
            source="delivery_confidence_scores",
            state=DataQualityState.COMPLETE
            if confidence_score is not None
            else DataQualityState.UNAVAILABLE,
            detail="ok",
        ),
    ]
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=[],
        limitations=limitations or [],
    )
    delivery = DeliveryEvidenceFacts(
        milestones=milestones,
        next_milestone_id=other_milestone_id
        if next_milestone_different
        else milestone_id,
        latest_delivery_confidence=confidence,
        open_risks=[],
        open_bottlenecks=[],
    )
    quality = QualityEvidenceFacts(
        current_period=[],
        previous_period=[],
        current_iso_year=2026,
        current_iso_week=25,
        previous_iso_year=2026,
        previous_iso_week=24,
    )
    workforce = WorkforceEvidenceFacts(as_of=as_of)
    governance = GovernanceEvidenceFacts(as_of=as_of)
    knowledge = KnowledgeEvidenceFacts(
        documents=[],
        chunks=[],
        source_availability=_knowledge_availability(),
        as_of=as_of,
        project_scope_key="abc",
    )
    project = ProjectIdentityFacts(
        project_id=pid,
        org_id=oid,
        project_name="Aurora Labeling",
        project_status="active",
    )
    overall = worst_data_quality_state([issue.state for issue in dq])
    fp = compute_source_fingerprint(
        project=project,
        reporting_period=period,
        visibility_mode=visibility_mode,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        visibility_limitations=vis,
        limitations=lim,
    )
    return ClientEvidencePack(
        project=project,
        reporting_period=period,
        visibility_mode=visibility_mode,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        generated_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        source_fingerprint=fp,
        policy_fingerprint=None,
        visibility_limitations=vis,
        limitations=lim,
    )


def _refingerprint(pack: ClientEvidencePack) -> ClientEvidencePack:
    return pack.model_copy(
        update={
            "source_fingerprint": compute_source_fingerprint(
                project=pack.project,
                reporting_period=pack.reporting_period,
                visibility_mode=pack.visibility_mode,
                delivery=pack.delivery,
                quality=pack.quality,
                workforce=pack.workforce,
                governance=pack.governance,
                knowledge=pack.knowledge,
                evidence=pack.evidence,
                data_quality=pack.data_quality,
                overall_data_quality=pack.overall_data_quality,
                visibility_limitations=pack.visibility_limitations,
                limitations=pack.limitations,
            )
        }
    )


def _complete_pack(**kwargs) -> ClientEvidencePack:
    pack = _base_pack(**kwargs)
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="milestones", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.COMPLETE
                if pack.delivery.latest_delivery_confidence is not None
                else DataQualityState.UNAVAILABLE,
                detail="ok",
            ),
        ]
    )
    overall = worst_data_quality_state([issue.state for issue in dq])
    return _refingerprint(
        pack.model_copy(update={"data_quality": dq, "overall_data_quality": overall})
    )


def _pack_with_dc_quality(state: DataQualityState, **kwargs) -> ClientEvidencePack:
    if state == DataQualityState.UNAVAILABLE:
        return _complete_pack(confidence_score=None, **kwargs)
    pack = _complete_pack(**kwargs)
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="milestones", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=state,
                detail="dc quality",
            ),
        ]
    )
    overall = worst_data_quality_state([issue.state for issue in dq])
    return _refingerprint(
        pack.model_copy(update={"data_quality": dq, "overall_data_quality": overall})
    )


def _aligned_previous(
    current: ClientEvidencePack,
    *,
    score: Decimal = Decimal("80.00"),
    status: str = "watch",
) -> ClientEvidencePack:
    prev_as_of = current.reporting_period.previous_end_date
    previous = _complete_pack(
        confidence_score=score,
        confidence_status=status,
        project_id=current.project.project_id,
        org_id=current.project.org_id,
        visibility_mode=current.visibility_mode,
        as_of=prev_as_of,
    )
    # Align reporting period window to current.previous_* dates.
    period = previous.reporting_period.model_copy(
        update={
            "start_date": current.reporting_period.previous_start_date,
            "end_date": current.reporting_period.previous_end_date,
            "previous_start_date": current.reporting_period.previous_start_date
            - timedelta(days=7),
            "previous_end_date": current.reporting_period.previous_end_date
            - timedelta(days=7),
            "as_of": current.reporting_period.previous_end_date,
        }
    )
    return _refingerprint(previous.model_copy(update={"reporting_period": period}))


def _dc_evidence_ref(
    pack: ClientEvidencePack,
    *,
    claim_keys: list[str] | None = None,
) -> DeliveryConfidenceEvidenceRef:
    conf = pack.delivery.latest_delivery_confidence
    assert conf is not None
    row = next(
        item
        for item in pack.evidence
        if item.source_table == "delivery_confidence_scores"
    )
    return DeliveryConfidenceEvidenceRef(
        source_agent=row.source_agent,
        source_table=row.source_table,
        source_row_id=row.source_row_id,
        visibility=row.visibility,
        claim_keys=claim_keys or ["score_pct"],
        period=DeliveryConfidenceEvidencePeriod.CURRENT,
        source_fingerprint=pack.source_fingerprint,
        observed_at=row.observed_at,
    )


class _FixtureExplanationPolicy:
    """Test-only explanation policy. Never modifies Delivery-owned core facts."""

    def __init__(self, *, mutate=None, rules_version: str = _TEST_RULES) -> None:
        self._rules_version = rules_version
        self._mutate = mutate

    @property
    def rules_version(self) -> str:
        return self._rules_version

    def evaluate(
        self,
        candidates: DeliveryConfidenceCandidateContext,
    ) -> DeliveryConfidenceExplanationDecision:
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score_key = "delivery_confidence.score_pct"
        drivers: list[DeliveryConfidenceDriver] = []
        if score_key in by_key:
            cand = by_key[score_key]
            drivers.append(
                DeliveryConfidenceDriver(
                    driver_key="delivery_confidence_score_driver",
                    polarity=DeliveryConfidenceDriverPolarity.POSITIVE,
                    category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
                    reason_code="DELIVERY_CONFIDENCE_PRESENT",
                    materiality=1,
                    candidate_keys=[score_key],
                    evidence=[
                        DeliveryConfidenceEvidenceRef(
                            source_agent=cand.source_agent,
                            source_table=cand.source_table,
                            source_row_id=cand.source_row_id,
                            visibility=cand.visibility,
                            claim_keys=[cand.claim_key],
                            period=DeliveryConfidenceEvidencePeriod.CURRENT,
                            source_fingerprint=cand.source_fingerprint,
                            observed_at=cand.observed_at,
                        )
                    ],
                    data_quality=DataQualityState.COMPLETE,
                )
            )
        decision = DeliveryConfidenceExplanationDecision(
            positive_drivers=drivers,
            negative_drivers=[],
            policy_limitations=[],
        )
        if self._mutate is not None:
            decision = self._mutate(candidates, decision)
        return decision


def test_exact_decimal_score_consumed_unchanged() -> None:
    score = Decimal("91.25")
    pack = _complete_pack(confidence_score=score)
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.score_pct == score
    assert isinstance(result.score_pct, Decimal)
    assert result.confidence_band == "confident"
    assert result.confidence_band_is_delivery_owned_status is True


def test_float_score_rejected_before_coercion() -> None:
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(
            {
                "org_id": str(uuid4()),
                "project_id": str(uuid4()),
                "reporting_period": resolve_reporting_period(_AS_OF).model_dump(
                    mode="json"
                ),
                "visibility_mode": EvidenceVisibility.INTERNAL,
                "availability": DeliveryConfidenceAvailability.AVAILABLE,
                "score_pct": 88.5,
                "confidence_band": "confident",
                "confidence_band_is_delivery_owned_status": True,
                "source_data_quality": DataQualityState.COMPLETE,
                "trend": DeliveryConfidenceTrend.UNKNOWN,
                "mitigation_contribution": MitigationContributionState.UNAVAILABLE,
                "source_fingerprint": "a" * 64,
                "assessed_at": datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
            }
        )


def test_delivery_status_consumed_unchanged_as_band() -> None:
    pack = _complete_pack(confidence_status="at_risk_custom")
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.confidence_band == "at_risk_custom"


def test_missing_policy_returns_core_facts_without_drivers() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.availability == DeliveryConfidenceAvailability.AVAILABLE
    assert result.positive_drivers == []
    assert result.negative_drivers == []
    assert LIMITATION_EXPLANATION_POLICY_UNAVAILABLE in result.limitations
    assert result.rules_version is None


def test_no_score_never_invents_score_or_band() -> None:
    pack = _complete_pack(confidence_score=None)
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.availability == DeliveryConfidenceAvailability.NO_SCORE
    assert result.score_pct is None
    assert result.confidence_band is None
    assert result.current_milestone is None
    assert result.forecast_completion_date is None
    assert result.trend == DeliveryConfidenceTrend.UNKNOWN
    assert LIMITATION_DELIVERY_CONFIDENCE_UNAVAILABLE in result.limitations
    assert result.mitigation_contribution == MitigationContributionState.UNAVAILABLE


def test_confidence_milestone_selected_by_exact_milestone_id() -> None:
    pack = _complete_pack(next_milestone_different=True)
    conf = pack.delivery.latest_delivery_confidence
    assert conf is not None
    assert pack.delivery.next_milestone_id != conf.milestone_id
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.current_milestone is not None
    assert result.current_milestone.milestone_id == conf.milestone_id
    assert result.current_milestone.milestone_id != pack.delivery.next_milestone_id


def test_client_safe_omits_milestone_description_and_model_version() -> None:
    pack = _complete_pack(visibility_mode=EvidenceVisibility.CLIENT_SAFE)
    result = assess_delivery_confidence(pack, explanation_policy=None)
    blob = str(result.model_dump(mode="json")).lower()
    assert "internal note" not in blob
    assert "delivery-v1" not in blob
    assert result.current_milestone is not None


def test_stale_source_not_reliable_for_drivers() -> None:
    pack = _pack_with_dc_quality(DataQualityState.STALE)
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert result.availability == DeliveryConfidenceAvailability.STALE
    assert result.score_pct == Decimal("88.50")
    assert result.positive_drivers == []
    assert result.negative_drivers == []


def test_conflicting_source_not_reliable() -> None:
    pack = _pack_with_dc_quality(DataQualityState.CONFLICTING)
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert result.availability == DeliveryConfidenceAvailability.CONFLICTING
    assert result.positive_drivers == []


def test_partial_source_not_presented_as_complete() -> None:
    pack = _pack_with_dc_quality(DataQualityState.PARTIAL)
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.availability == DeliveryConfidenceAvailability.PARTIAL
    assert result.source_data_quality == DataQualityState.PARTIAL


def test_trend_increase_decrease_stable() -> None:
    current = _complete_pack(confidence_score=Decimal("90.00"))
    previous = _aligned_previous(current, score=Decimal("80.00"))
    up = assess_delivery_confidence(current, previous=previous)
    assert up.trend == DeliveryConfidenceTrend.INCREASED
    assert up.previous_score_pct == Decimal("80.00")
    assert up.previous_source_fingerprint == previous.source_fingerprint
    assert any(
        item.period == DeliveryConfidenceEvidencePeriod.PREVIOUS
        for item in up.evidence
    )

    down_current = _complete_pack(
        confidence_score=Decimal("70.00"),
        project_id=current.project.project_id,
        org_id=current.project.org_id,
    )
    down = assess_delivery_confidence(down_current, previous=previous)
    assert down.trend == DeliveryConfidenceTrend.DECREASED

    equal_current = _complete_pack(
        confidence_score=Decimal("80.00"),
        project_id=current.project.project_id,
        org_id=current.project.org_id,
    )
    stable = assess_delivery_confidence(equal_current, previous=previous)
    assert stable.trend == DeliveryConfidenceTrend.STABLE


def test_no_previous_pack_trend_unknown() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(pack)
    assert result.trend == DeliveryConfidenceTrend.UNKNOWN
    assert result.previous_score_pct is None
    assert LIMITATION_PREVIOUS_CONFIDENCE_UNAVAILABLE in result.limitations


def test_misaligned_periods_trend_unknown() -> None:
    current = _complete_pack()
    previous = _complete_pack(
        project_id=current.project.project_id,
        org_id=current.project.org_id,
        as_of=current.reporting_period.as_of,
    )
    result = assess_delivery_confidence(current, previous=previous)
    assert result.trend == DeliveryConfidenceTrend.UNKNOWN
    assert LIMITATION_PREVIOUS_PERIOD_MISMATCH in result.limitations


def test_previous_stale_trend_unknown() -> None:
    current = _complete_pack()
    previous = _aligned_previous(current)
    previous = _pack_with_dc_quality(
        DataQualityState.STALE,
        project_id=current.project.project_id,
        org_id=current.project.org_id,
        visibility_mode=current.visibility_mode,
        as_of=current.reporting_period.previous_end_date,
    )
    period = previous.reporting_period.model_copy(
        update={
            "start_date": current.reporting_period.previous_start_date,
            "end_date": current.reporting_period.previous_end_date,
            "as_of": current.reporting_period.previous_end_date,
        }
    )
    previous = _refingerprint(previous.model_copy(update={"reporting_period": period}))
    result = assess_delivery_confidence(current, previous=previous)
    assert result.trend == DeliveryConfidenceTrend.UNKNOWN


def test_cross_tenant_previous_rejected() -> None:
    current = _complete_pack()
    other = _complete_pack(
        confidence_score=Decimal("80.00"),
        project_id=current.project.project_id,
        org_id=uuid4(),
        visibility_mode=current.visibility_mode,
        as_of=current.reporting_period.previous_end_date,
    )
    period = other.reporting_period.model_copy(
        update={
            "start_date": current.reporting_period.previous_start_date,
            "end_date": current.reporting_period.previous_end_date,
            "as_of": current.reporting_period.previous_end_date,
        }
    )
    other = _refingerprint(other.model_copy(update={"reporting_period": period}))
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(current, previous=other)
    assert (exc.value.code == "incompatible_previous_pack")


def test_cross_project_previous_rejected() -> None:
    current = _complete_pack()
    previous = _aligned_previous(current)
    # Build a fully valid pack for a different project, aligned to the prior window.
    other = _complete_pack(
        confidence_score=Decimal("80.00"),
        project_id=uuid4(),
        org_id=current.project.org_id,
        visibility_mode=current.visibility_mode,
        as_of=current.reporting_period.previous_end_date,
    )
    period = other.reporting_period.model_copy(
        update={
            "start_date": current.reporting_period.previous_start_date,
            "end_date": current.reporting_period.previous_end_date,
            "as_of": current.reporting_period.previous_end_date,
        }
    )
    other = _refingerprint(other.model_copy(update={"reporting_period": period}))
    del previous
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(current, previous=other)
    assert (exc.value.code == "incompatible_previous_pack")


def test_visibility_mismatch_previous_rejected() -> None:
    current = _complete_pack(visibility_mode=EvidenceVisibility.INTERNAL)
    previous = _aligned_previous(current)
    previous = _complete_pack(
        confidence_score=Decimal("80.00"),
        project_id=current.project.project_id,
        org_id=current.project.org_id,
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        as_of=current.reporting_period.previous_end_date,
    )
    period = previous.reporting_period.model_copy(
        update={
            "start_date": current.reporting_period.previous_start_date,
            "end_date": current.reporting_period.previous_end_date,
            "as_of": current.reporting_period.previous_end_date,
        }
    )
    previous = _refingerprint(previous.model_copy(update={"reporting_period": period}))
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(current, previous=previous)
    assert (exc.value.code == "incompatible_previous_pack")


def test_policy_cannot_alter_core_facts_via_decision() -> None:
    """Core facts come from the pack; policy only supplies drivers."""
    pack = _complete_pack(confidence_score=Decimal("88.50"), confidence_status="confident")
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert result.score_pct == Decimal("88.50")
    assert result.confidence_band == "confident"
    assert result.rules_version == _TEST_RULES
    assert result.positive_drivers


def test_unknown_candidate_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        del candidates
        drivers = [
            item.model_copy(update={"candidate_keys": ["missing.candidate"]})
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as exc:
        assess_delivery_confidence(
            pack,
            explanation_policy=_FixtureExplanationPolicy(mutate=_mutate),
        )
    assert exc.value.code == "invalid_policy_decision"


def test_unrelated_driver_evidence_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        milestone_cand = next(
            item
            for item in candidates.candidates
            if item.source_table == "milestones"
        )
        bad = DeliveryConfidenceEvidenceRef(
            source_agent=milestone_cand.source_agent,
            source_table=milestone_cand.source_table,
            source_row_id=milestone_cand.source_row_id,
            visibility=milestone_cand.visibility,
            claim_keys=["milestone_status"],
            period=DeliveryConfidenceEvidencePeriod.CURRENT,
            source_fingerprint=milestone_cand.source_fingerprint,
            observed_at=milestone_cand.observed_at,
        )
        drivers = [
            item.model_copy(update={"evidence": [bad]})
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as exc:
        assess_delivery_confidence(
            pack,
            explanation_policy=_FixtureExplanationPolicy(mutate=_mutate),
        )
    assert (exc.value.code == "unsupported_evidence_reference")


def test_wrong_polarity_collection_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        del candidates
        return decision.model_copy(
            update={
                "negative_drivers": [
                    item.model_copy(
                        update={"polarity": DeliveryConfidenceDriverPolarity.POSITIVE}
                    )
                    for item in decision.positive_drivers
                ],
                "positive_drivers": [],
            }
        )

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack,
            explanation_policy=_FixtureExplanationPolicy(mutate=_mutate),
        )
    assert (exc.value.code == "invalid_policy_decision")


def test_stale_candidate_driver_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        del candidates
        drivers = [
            item.model_copy(update={"data_quality": DataQualityState.STALE})
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack,
            explanation_policy=_FixtureExplanationPolicy(mutate=_mutate),
        )
    assert (exc.value.code == "invalid_policy_decision")


def test_empty_risk_bottleneck_not_positive_and_domains_unavailable() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert LIMITATION_BACKLOG_SOURCE_UNAVAILABLE in result.limitations
    assert LIMITATION_MITIGATION_SOURCE_UNAVAILABLE in result.limitations
    assert result.mitigation_contribution == MitigationContributionState.UNAVAILABLE


def test_identical_inputs_produce_identical_assessments() -> None:
    pack = _complete_pack()
    policy = _FixtureExplanationPolicy()
    first = assess_delivery_confidence(pack, explanation_policy=policy)
    second = assess_delivery_confidence(pack, explanation_policy=policy)
    assert first == second


def test_missing_dc_with_dishonest_complete_quality_rejected() -> None:
    pack = _complete_pack(confidence_score=None)
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="milestones", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.COMPLETE,
                detail="false",
            ),
        ]
    )
    pack = _refingerprint(
        pack.model_copy(
            update={
                "data_quality": dq,
                "overall_data_quality": DataQualityState.COMPLETE,
            }
        )
    )
    with pytest.raises(EvidencePackIntegrityError):
        assess_delivery_confidence(pack)


def test_present_dc_with_dishonest_unavailable_quality_rejected() -> None:
    pack = _complete_pack()
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="milestones", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.UNAVAILABLE,
                detail="false",
            ),
        ]
    )
    pack = _refingerprint(
        pack.model_copy(
            update={
                "data_quality": dq,
                "overall_data_quality": DataQualityState.UNAVAILABLE,
            }
        )
    )
    with pytest.raises(EvidencePackIntegrityError):
        assess_delivery_confidence(pack)


@pytest.mark.parametrize("boundary", ["rules_version", "evaluate"])
@pytest.mark.parametrize("kind", ["runtime", "integrity"])
def test_policy_boundary_errors_sanitized(boundary: str, kind: str) -> None:
    pack = _complete_pack()
    sensitive = "SECRET_reviewer_alice"

    class _Hostile(_FixtureExplanationPolicy):
        @property
        def rules_version(self) -> str:
            if boundary == "rules_version":
                if kind == "runtime":
                    raise RuntimeError(sensitive)
                raise DeliveryConfidenceIntegrityError("leaked", sensitive)
            return super().rules_version

        def evaluate(self, candidates):
            if boundary == "evaluate":
                if kind == "runtime":
                    raise RuntimeError(sensitive)
                raise DeliveryConfidenceIntegrityError("leaked", sensitive)
            return super().evaluate(candidates)

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(pack, explanation_policy=_Hostile())
    assert (exc.value.code == "invalid_policy")
    assert sensitive not in str(exc.value)
    assert sensitive not in (exc.value.detail)


def test_engine_performs_no_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"persist": 0}

    def _boom(*args, **kwargs):
        called["persist"] += 1
        raise AssertionError("persistence must not be called")

    monkeypatch.setattr(
        "app.agents.client_intelligence.evidence_persistence.persist_client_evidence_snapshot",
        _boom,
    )
    pack = _complete_pack()
    assess_delivery_confidence(pack, explanation_policy=_FixtureExplanationPolicy())
    assert called["persist"] == 0


def test_assessed_at_from_pack_generated_at() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(pack)
    assert result.assessed_at == pack.generated_at


def test_valid_driver_candidate_evidence_closure() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert result.positive_drivers
    driver = result.positive_drivers[0]
    assert driver.candidate_keys == ["delivery_confidence.score_pct"]
    assert driver.evidence[0].source_row_id == pack.delivery.latest_delivery_confidence.id


def test_evidence_claim_union_preserved() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(pack)
    row = next(
        item
        for item in result.evidence
        if item.source_table == "delivery_confidence_scores"
        and item.period == DeliveryConfidenceEvidencePeriod.CURRENT
    )
    assert "score_pct" in row.claim_keys
    assert "confidence_status" in row.claim_keys
    assert "forecast_completion_date" in row.claim_keys


def test_missing_confidence_milestone_fails_closed() -> None:
    pack = _complete_pack()
    conf = pack.delivery.latest_delivery_confidence
    assert conf is not None
    broken = conf.model_copy(update={"milestone_id": uuid4()})
    pack = _refingerprint(
        pack.model_copy(
            update={
                "delivery": pack.delivery.model_copy(
                    update={"latest_delivery_confidence": broken}
                )
            }
        )
    )
    with pytest.raises((DeliveryConfidenceIntegrityError, EvidencePackIntegrityError)):
        assess_delivery_confidence(pack)


def test_unsupported_claim_key_on_driver_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score_cand = by_key["delivery_confidence.score_pct"]
        bad = DeliveryConfidenceEvidenceRef.model_construct(
            source_agent=score_cand.source_agent,
            source_table=score_cand.source_table,
            source_row_id=score_cand.source_row_id,
            visibility=score_cand.visibility,
            claim_keys=["not_a_real_claim"],
            period=DeliveryConfidenceEvidencePeriod.CURRENT,
            source_fingerprint=score_cand.source_fingerprint,
            observed_at=score_cand.observed_at,
        )
        drivers = [
            item.model_copy(update={"evidence": [bad]})
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack,
            explanation_policy=_FixtureExplanationPolicy(mutate=_mutate),
        )
    assert (exc.value.code == "unsupported_evidence_reference")


def test_conflicting_candidate_quality_driver_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        del candidates
        drivers = [
            item.model_copy(update={"data_quality": DataQualityState.CONFLICTING})
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack,
            explanation_policy=_FixtureExplanationPolicy(mutate=_mutate),
        )
    assert (exc.value.code == "invalid_policy_decision")


def test_previous_missing_confidence_trend_unknown() -> None:
    current = _complete_pack()
    previous = _aligned_previous(current)
    previous = _complete_pack(
        confidence_score=None,
        project_id=current.project.project_id,
        org_id=current.project.org_id,
        visibility_mode=current.visibility_mode,
        as_of=current.reporting_period.previous_end_date,
    )
    period = previous.reporting_period.model_copy(
        update={
            "start_date": current.reporting_period.previous_start_date,
            "end_date": current.reporting_period.previous_end_date,
            "as_of": current.reporting_period.previous_end_date,
        }
    )
    previous = _refingerprint(previous.model_copy(update={"reporting_period": period}))
    result = assess_delivery_confidence(current, previous=previous)
    assert result.trend == DeliveryConfidenceTrend.UNKNOWN


def test_pack_limitations_propagate() -> None:
    pack = _complete_pack(limitations=["PACK_LIMIT_X"])
    result = assess_delivery_confidence(pack)
    assert "PACK_LIMIT_X" in result.source_limitations
    assert "PACK_LIMIT_X" not in result.limitations


def _skip_pack_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.client_intelligence.delivery_confidence_intelligence."
        "_validate_pack_or_raise",
        lambda _pack: None,
    )


def _replace_dq(
    pack: ClientEvidencePack, issues: list[DataQualityIssue]
) -> ClientEvidencePack:
    dq = finalize_data_quality_issues(issues)
    overall = worst_data_quality_state([item.state for item in dq])
    return _refingerprint(
        pack.model_copy(update={"data_quality": dq, "overall_data_quality": overall})
    )


def _with_domain_facts(
    pack: ClientEvidencePack,
    *,
    risk: bool = False,
    bottleneck: bool = False,
    throughput: bool = False,
    quality: bool = False,
    dependency: bool = False,
    risk_dq: DataQualityState | None = DataQualityState.COMPLETE,
    bottleneck_dq: DataQualityState | None = DataQualityState.COMPLETE,
    throughput_dq: DataQualityState | None = DataQualityState.COMPLETE,
    quality_dq: DataQualityState | None = DataQualityState.COMPLETE,
    dependency_dq: DataQualityState | None = DataQualityState.COMPLETE,
    include_risk_evidence: bool = True,
    risk_claim_keys: list[str] | None = None,
    risk_source_agent: SourceAgent = SourceAgent.DELIVERY_PERFORMANCE,
    risk_observed_at: datetime | None = datetime(2026, 6, 2, tzinfo=UTC),
) -> ClientEvidencePack:
    refs = list(pack.evidence)
    dq = list(pack.data_quality)
    open_risks = list(pack.delivery.open_risks)
    open_bottlenecks = list(pack.delivery.open_bottlenecks)
    latest_throughput = pack.delivery.latest_throughput
    quality_rows = list(pack.quality.current_period)
    dependencies = list(pack.governance.dependencies)

    if risk:
        risk_id = uuid4()
        open_risks.append(
            RiskAlertFacts(
                id=risk_id,
                alert_type="delivery_risk",
                risk_tier="high",
                title="Slippage",
                status="open",
                detail="internal",
                observed_at=risk_observed_at,
            )
        )
        if include_risk_evidence:
            refs.append(
                ClientEvidenceReference(
                    source_agent=risk_source_agent,
                    source_table="risk_alerts",
                    source_row_id=risk_id,
                    description="risk",
                    visibility=EvidenceVisibility.INTERNAL,
                    observed_at=risk_observed_at,
                    claim_keys=risk_claim_keys
                    or [
                        "risk_id",
                        "risk_title",
                        "risk_tier",
                        "alert_type",
                        "status",
                        "risk_detail",
                    ],
                )
            )
        if risk_dq is not None:
            dq.append(
                DataQualityIssue(
                    source="risk_alerts", state=risk_dq, detail="risk quality"
                )
            )

    if bottleneck:
        bn_id = uuid4()
        open_bottlenecks.append(
            BottleneckFacts(
                id=bn_id,
                title="Queue",
                status="open",
                detail="internal",
                observed_at=datetime(2026, 6, 3, tzinfo=UTC),
            )
        )
        refs.append(
            _ref(
                source_table="bottlenecks",
                source_row_id=bn_id,
                description="bottleneck",
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime(2026, 6, 3, tzinfo=UTC),
                claim_keys=[
                    "bottleneck_id",
                    "bottleneck_title",
                    "status",
                    "bottleneck_detail",
                ],
            )
        )
        if bottleneck_dq is not None:
            dq.append(
                DataQualityIssue(
                    source="bottlenecks",
                    state=bottleneck_dq,
                    detail="bn quality",
                )
            )

    if throughput:
        tp_id = uuid4()
        latest_throughput = ThroughputSnapshotFacts(
            id=tp_id,
            snapshot_date=date(2026, 6, 17),
            units_completed=None,
            units_forecast=None,
            rolling_7day_units=9,
        )
        refs.append(
            _ref(
                source_table="throughput_snapshots",
                source_row_id=tp_id,
                description="throughput",
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime(2026, 6, 17, tzinfo=UTC),
                claim_keys=[
                    "snapshot_date",
                    "rolling_7day_units",
                ],
            )
        )
        if throughput_dq is not None:
            dq.append(
                DataQualityIssue(
                    source="throughput_snapshots",
                    state=throughput_dq,
                    detail="tp quality",
                )
            )

    if quality:
        snap_id = uuid4()
        quality_rows.append(
            QualitySnapshotFacts(
                snapshot_id=snap_id,
                iso_year=2026,
                iso_week=25,
                rework_rate_pct=Decimal("4.50"),
                observed_at=datetime(2026, 6, 16, tzinfo=UTC),
            )
        )
        refs.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.QUALITY_INTELLIGENCE,
                source_table="quality_snapshots",
                source_row_id=snap_id,
                description="quality",
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=datetime(2026, 6, 16, tzinfo=UTC),
                claim_keys=["iso_year", "iso_week", "rework_rate_pct"],
            )
        )
        if quality_dq is not None:
            dq.append(
                DataQualityIssue(
                    source="quality_snapshots",
                    state=quality_dq,
                    detail="quality dq",
                )
            )

    if dependency:
        dep_id = uuid4()
        dependencies.append(
            GovernanceDependencyFacts(
                dependency_id=dep_id,
                dependency_type="client_action",
                status="open",
                due_date=None,
                resolved_at=None,
                observed_at=datetime(2026, 6, 4, tzinfo=UTC),
            )
        )
        refs.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="project_dependencies",
                source_row_id=dep_id,
                description="dependency",
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime(2026, 6, 4, tzinfo=UTC),
                claim_keys=["dependency_id", "dependency_type", "status"],
            )
        )
        if dependency_dq is not None:
            dq.append(
                DataQualityIssue(
                    source="governance_dependencies",
                    state=dependency_dq,
                    detail="gov dep quality",
                )
            )

    finalized_refs, finalized_dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=list(pack.visibility_limitations),
        limitations=list(pack.limitations),
    )
    delivery = pack.delivery.model_copy(
        update={
            "open_risks": open_risks,
            "open_bottlenecks": open_bottlenecks,
            "latest_throughput": latest_throughput,
        }
    )
    quality_facts = pack.quality.model_copy(update={"current_period": quality_rows})
    governance = pack.governance.model_copy(update={"dependencies": dependencies})
    overall = worst_data_quality_state([item.state for item in finalized_dq])
    return _refingerprint(
        pack.model_copy(
            update={
                "delivery": delivery,
                "quality": quality_facts,
                "governance": governance,
                "evidence": finalized_refs,
                "data_quality": finalized_dq,
                "overall_data_quality": overall,
                "visibility_limitations": vis,
                "limitations": lim,
            }
        )
    )


def test_policy_evaluate_signature_is_context_only() -> None:
    params = list(
        inspect.signature(_FixtureExplanationPolicy.evaluate).parameters.keys()
    )
    assert params == ["self", "candidates"]
    pack = _complete_pack()
    seen: dict[str, object] = {}

    class _Capture(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            seen["arg"] = candidates
            seen["type"] = type(candidates)
            return super().evaluate(candidates)

    assess_delivery_confidence(pack, explanation_policy=_Capture())
    assert isinstance(seen["arg"], DeliveryConfidenceCandidateContext)
    assert seen["type"] is DeliveryConfidenceCandidateContext
    assert not isinstance(seen["arg"], ClientEvidencePack)


def test_policy_cannot_access_pack_through_evaluate_args() -> None:
    pack = _complete_pack()

    class _Probe(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            assert not hasattr(candidates, "delivery")
            assert not hasattr(candidates, "project")
            assert not hasattr(candidates, "source_fingerprint")
            blob = str(candidates.model_dump(mode="json"))
            assert "Alice" not in blob
            assert "Aurora" not in blob
            return super().evaluate(candidates)

    assess_delivery_confidence(pack, explanation_policy=_Probe())


def test_policy_mutates_context_copy_without_affecting_assessment() -> None:
    pack = _complete_pack()
    authoritative_fp = pack.source_fingerprint

    class _MutateCopy(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            for item in candidates.candidates:
                item.source_fingerprint = (
                    "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                )
                item.data_quality = DataQualityState.STALE
                item.value = Decimal("0.01")
            candidates.candidates.clear()
            candidates.context_limitations.append("POLICY_MUTATED_CONTEXT")
            return decision

    result = assess_delivery_confidence(pack, explanation_policy=_MutateCopy())
    assert result.source_fingerprint == authoritative_fp
    assert result.score_pct == Decimal("88.50")
    assert result.positive_drivers
    assert result.positive_drivers[0].data_quality == DataQualityState.COMPLETE
    assert "POLICY_MUTATED_CONTEXT" not in result.limitations


def test_policy_closure_pack_mutation_bypass_closed() -> None:
    pack = _complete_pack(org_id=_ORG)
    original_org = pack.project.org_id
    original_project = pack.project.project_id
    original_fp = pack.source_fingerprint
    original_period = pack.reporting_period.model_copy(deep=True)
    original_generated = pack.generated_at
    original_score = pack.delivery.latest_delivery_confidence.score_pct
    original_status = pack.delivery.latest_delivery_confidence.status
    held = {"pack": pack}

    class _HostileClosure(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            owned = held["pack"]
            owned.project.org_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
            owned.project.project_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
            owned.source_fingerprint = (
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )
            owned.generated_at = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)
            owned.reporting_period = owned.reporting_period.model_copy(
                update={"as_of": date(2099, 1, 1)}
            )
            conf = owned.delivery.latest_delivery_confidence
            assert conf is not None
            owned.delivery.latest_delivery_confidence = conf.model_copy(
                update={
                    "score_pct": Decimal("1.00"),
                    "status": "mutated_hostile_band",
                }
            )
            return decision

    result = assess_delivery_confidence(pack, explanation_policy=_HostileClosure())
    assert pack.project.org_id != original_org
    assert pack.source_fingerprint != original_fp
    assert result.org_id == original_org
    assert result.project_id == original_project
    assert result.source_fingerprint == original_fp
    assert result.reporting_period == original_period
    assert result.assessed_at == original_generated
    assert result.score_pct == original_score
    assert result.confidence_band == original_status
    assert result.org_id != pack.project.org_id
    assert result.source_fingerprint != pack.source_fingerprint


def test_risk_without_quality_issue_not_complete_and_no_driver() -> None:
    pack = _with_domain_facts(_complete_pack(), risk=True, risk_dq=None)
    captured: dict[str, object] = {}

    class _TryRisk(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            captured["keys"] = [item.candidate_key for item in candidates.candidates]
            risk_keys = [
                item.candidate_key
                for item in candidates.candidates
                if item.category == DeliveryConfidenceCandidateCategory.RISK
            ]
            assert not risk_keys
            return super().evaluate(candidates)

    result = assess_delivery_confidence(pack, explanation_policy=_TryRisk())
    assert not any(key.startswith("risk.status.") for key in captured["keys"])  # type: ignore[index]
    assert LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS in result.limitations
    assert all(
        item.category != DeliveryConfidenceCandidateCategory.RISK
        for item in result.positive_drivers + result.negative_drivers
    )


def test_bottleneck_without_quality_issue_cannot_support_driver() -> None:
    pack = _with_domain_facts(_complete_pack(), bottleneck=True, bottleneck_dq=None)
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS in result.limitations
    context = _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert not any(
        item.category == DeliveryConfidenceCandidateCategory.BOTTLENECK
        for item in context.candidates
    )


def test_quality_without_quality_issue_cannot_support_driver() -> None:
    pack = _with_domain_facts(_complete_pack(), quality=True, quality_dq=None)
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert LIMITATION_SOURCE_QUALITY_MISSING_QUALITY_SNAPSHOTS in result.limitations
    context = _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert not any(
        item.category == DeliveryConfidenceCandidateCategory.QUALITY
        for item in context.candidates
    )


def test_throughput_without_quality_issue_cannot_support_driver() -> None:
    pack = _with_domain_facts(_complete_pack(), throughput=True, throughput_dq=None)
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS in result.limitations
    context = _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert not any(
        item.category == DeliveryConfidenceCandidateCategory.THROUGHPUT
        for item in context.candidates
    )


def test_dependency_uses_governance_dependencies_quality_not_table_name() -> None:
    pack = _with_domain_facts(_complete_pack(), dependency=True, dependency_dq=None)
    # project_dependencies DQ key must not unlock the candidate
    pack = _replace_dq(
        pack,
        [
            *pack.data_quality,
            DataQualityIssue(
                source="project_dependencies",
                state=DataQualityState.COMPLETE,
                detail="wrong key",
            ),
        ],
    )
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert (
        LIMITATION_SOURCE_QUALITY_MISSING_GOVERNANCE_DEPENDENCIES in result.limitations
    )
    context = _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert not any(
        item.category == DeliveryConfidenceCandidateCategory.DEPENDENCY
        for item in context.candidates
    )

    ok = _with_domain_facts(
        _complete_pack(),
        dependency=True,
        dependency_dq=DataQualityState.COMPLETE,
    )
    context_ok = _build_candidate_context(ok, source_quality=DataQualityState.COMPLETE)
    assert any(
        item.category == DeliveryConfidenceCandidateCategory.DEPENDENCY
        for item in context_ok.candidates
    )


def test_stale_candidate_cannot_support_material_driver() -> None:
    pack = _with_domain_facts(
        _complete_pack(), risk=True, risk_dq=DataQualityState.STALE
    )

    def _mutate(candidates, decision):
        risk = next(
            item
            for item in candidates.candidates
            if item.category == DeliveryConfidenceCandidateCategory.RISK
        )
        assert risk.data_quality == DataQualityState.STALE
        bad = DeliveryConfidenceDriver(
            driver_key="risk_stale_driver",
            polarity=DeliveryConfidenceDriverPolarity.NEGATIVE,
            category=DeliveryConfidenceCandidateCategory.RISK,
            reason_code="RISK_STALE_DRIVER",
            materiality=1,
            candidate_keys=[risk.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=risk.source_agent,
                    source_table=risk.source_table,
                    source_row_id=risk.source_row_id,
                    visibility=risk.visibility,
                    claim_keys=[risk.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=risk.source_fingerprint,
                    observed_at=risk.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return decision.model_copy(update={"negative_drivers": [bad]})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert exc.value.code == "invalid_policy_decision"


def test_candidate_missing_evidence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(
        _complete_pack(), risk=True, include_risk_evidence=False
    )
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert exc.value.code == "unsupported_evidence_reference"


def test_candidate_unsupported_claim_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(
        _complete_pack(),
        risk=True,
        risk_claim_keys=["risk_id", "risk_title", "risk_tier", "alert_type"],
    )
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert exc.value.code == "unsupported_evidence_reference"


def test_candidate_wrong_source_agent_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(
        _complete_pack(),
        risk=True,
        risk_source_agent=SourceAgent.PROJECT_GOVERNANCE,
    )
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert exc.value.code == "unsupported_evidence_reference"


def test_candidate_fact_evidence_observed_at_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(_complete_pack(), risk=True)
    risk = pack.delivery.open_risks[0]
    refs = []
    for item in pack.evidence:
        if item.source_table == "risk_alerts" and item.source_row_id == risk.id:
            refs.append(
                item.model_copy(
                    update={"observed_at": datetime(2026, 1, 1, tzinfo=UTC)}
                )
            )
        else:
            refs.append(item)
    pack = pack.model_copy(update={"evidence": refs})
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert (exc.value.code == "invalid_policy_decision")


def test_client_safe_internal_candidate_evidence_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _complete_pack(visibility_mode=EvidenceVisibility.CLIENT_SAFE)
    pack = _with_domain_facts(pack, risk=True)
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    assert exc.value.code == "visibility_violation"


def test_mixed_category_driver_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score = by_key["delivery_confidence.score_pct"]
        milestone = by_key["milestone.status"]
        bad = DeliveryConfidenceDriver(
            driver_key="mixed_category_driver",
            polarity=DeliveryConfidenceDriverPolarity.POSITIVE,
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            reason_code="MIXED_CATEGORY_DRIVER",
            materiality=1,
            candidate_keys=[score.candidate_key, milestone.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=score.source_agent,
                    source_table=score.source_table,
                    source_row_id=score.source_row_id,
                    visibility=score.visibility,
                    claim_keys=[score.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=score.source_fingerprint,
                    observed_at=score.observed_at,
                ),
                DeliveryConfidenceEvidenceRef(
                    source_agent=milestone.source_agent,
                    source_table=milestone.source_table,
                    source_row_id=milestone.source_row_id,
                    visibility=milestone.visibility,
                    claim_keys=[milestone.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=milestone.source_fingerprint,
                    observed_at=milestone.observed_at,
                ),
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return decision.model_copy(update={"positive_drivers": [bad]})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert exc.value.code == "invalid_policy_decision"


def test_driver_partial_candidate_evidence_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score = by_key["delivery_confidence.score_pct"]
        status = by_key["delivery_confidence.status"]
        bad = DeliveryConfidenceDriver(
            driver_key="partial_evidence_driver",
            polarity=DeliveryConfidenceDriverPolarity.POSITIVE,
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            reason_code="PARTIAL_EVIDENCE_DRIVER",
            materiality=1,
            candidate_keys=[score.candidate_key, status.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=score.source_agent,
                    source_table=score.source_table,
                    source_row_id=score.source_row_id,
                    visibility=score.visibility,
                    claim_keys=[score.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=score.source_fingerprint,
                    observed_at=score.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return decision.model_copy(update={"positive_drivers": [bad]})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert exc.value.code == "unsupported_evidence_reference"


def test_driver_extra_unrelated_evidence_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score = by_key["delivery_confidence.score_pct"]
        milestone = by_key["milestone.status"]
        drivers = []
        for item in decision.positive_drivers:
            drivers.append(
                item.model_copy(
                    update={
                        "evidence": [
                            *item.evidence,
                            DeliveryConfidenceEvidenceRef(
                                source_agent=milestone.source_agent,
                                source_table=milestone.source_table,
                                source_row_id=milestone.source_row_id,
                                visibility=milestone.visibility,
                                claim_keys=[milestone.claim_key],
                                period=DeliveryConfidenceEvidencePeriod.CURRENT,
                                source_fingerprint=milestone.source_fingerprint,
                                observed_at=milestone.observed_at,
                            ),
                        ]
                    }
                )
            )
        del score
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert (exc.value.code == "unsupported_evidence_reference")


def test_driver_extra_unselected_claim_key_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score = by_key["delivery_confidence.score_pct"]
        drivers = [
            item.model_copy(
                update={
                    "evidence": [
                        DeliveryConfidenceEvidenceRef(
                            source_agent=score.source_agent,
                            source_table=score.source_table,
                            source_row_id=score.source_row_id,
                            visibility=score.visibility,
                            claim_keys=["score_pct", "confidence_status"],
                            period=DeliveryConfidenceEvidencePeriod.CURRENT,
                            source_fingerprint=score.source_fingerprint,
                            observed_at=score.observed_at,
                        )
                    ]
                }
            )
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert (exc.value.code == "unsupported_evidence_reference")


def test_driver_data_quality_mismatch_rejected() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        del candidates
        drivers = [
            item.model_copy(update={"data_quality": DataQualityState.PARTIAL})
            for item in decision.positive_drivers
        ]
        return decision.model_copy(update={"positive_drivers": drivers})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert (exc.value.code == "invalid_policy_decision")


def test_exact_multi_candidate_same_category_evidence_union_accepted() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score = by_key["delivery_confidence.score_pct"]
        status = by_key["delivery_confidence.status"]
        driver = DeliveryConfidenceDriver(
            driver_key="delivery_confidence_pair_driver",
            polarity=DeliveryConfidenceDriverPolarity.POSITIVE,
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            reason_code="DELIVERY_CONFIDENCE_PAIR",
            materiality=1,
            candidate_keys=[score.candidate_key, status.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=score.source_agent,
                    source_table=score.source_table,
                    source_row_id=score.source_row_id,
                    visibility=score.visibility,
                    claim_keys=[score.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=score.source_fingerprint,
                    observed_at=score.observed_at,
                ),
                DeliveryConfidenceEvidenceRef(
                    source_agent=status.source_agent,
                    source_table=status.source_table,
                    source_row_id=status.source_row_id,
                    visibility=status.visibility,
                    claim_keys=[status.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=status.source_fingerprint,
                    observed_at=status.observed_at,
                ),
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return decision.model_copy(update={"positive_drivers": [driver]})

    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
    )
    driver = result.positive_drivers[0]
    assert set(driver.candidate_keys) == {
        "delivery_confidence.score_pct",
        "delivery_confidence.status",
    }
    assert set(driver.evidence[0].claim_keys) == {"confidence_status", "score_pct"}


def test_duplicate_evidence_conflicting_observed_at_rejected() -> None:
    pack = _complete_pack()
    conf = pack.delivery.latest_delivery_confidence
    assert conf is not None
    row = next(
        item
        for item in pack.evidence
        if item.source_table == "delivery_confidence_scores"
    )
    left = DeliveryConfidenceEvidenceRef(
        source_agent=row.source_agent,
        source_table=row.source_table,
        source_row_id=row.source_row_id,
        visibility=row.visibility,
        claim_keys=["score_pct"],
        period=DeliveryConfidenceEvidencePeriod.CURRENT,
        source_fingerprint=pack.source_fingerprint,
        observed_at=row.observed_at,
    )
    right = left.model_copy(
        update={
            "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
            "claim_keys": ["confidence_status"],
        }
    )
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        _sort_evidence([left, right])
    assert (exc.value.code == "invalid_policy_decision")


def test_confidence_source_observed_at_evidence_none_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _complete_pack()
    refs = []
    for item in pack.evidence:
        if item.source_table == "delivery_confidence_scores":
            refs.append(item.model_copy(update={"observed_at": None}))
        else:
            refs.append(item)
    pack = pack.model_copy(update={"evidence": refs})
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(pack)
    assert (exc.value.code == "invalid_policy_decision")


def test_confidence_evidence_observed_at_source_none_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _complete_pack()
    conf = pack.delivery.latest_delivery_confidence
    assert conf is not None
    delivery = pack.delivery.model_copy(
        update={
            "latest_delivery_confidence": conf.model_copy(update={"observed_at": None})
        }
    )
    pack = pack.model_copy(update={"delivery": delivery})
    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(pack)
    assert (exc.value.code == "invalid_policy_decision")


def test_previous_evidence_carries_exact_previous_observed_at() -> None:
    current = _complete_pack()
    previous = _aligned_previous(current, score=Decimal("70.00"))
    prev_conf = previous.delivery.latest_delivery_confidence
    assert prev_conf is not None
    result = assess_delivery_confidence(current, previous=previous)
    prev_ev = next(
        item
        for item in result.evidence
        if item.period == DeliveryConfidenceEvidencePeriod.PREVIOUS
        and item.source_table == "delivery_confidence_scores"
    )
    assert prev_ev.observed_at == prev_conf.observed_at
    assert prev_ev.source_fingerprint == previous.source_fingerprint


def test_availability_source_quality_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(
            {
                "org_id": str(_ORG),
                "project_id": str(uuid4()),
                "reporting_period": resolve_reporting_period(_AS_OF).model_dump(
                    mode="json"
                ),
                "visibility_mode": EvidenceVisibility.INTERNAL,
                "availability": DeliveryConfidenceAvailability.AVAILABLE,
                "score_pct": "88.50",
                "confidence_band": "confident",
                "confidence_band_is_delivery_owned_status": True,
                "current_milestone": {
                    "milestone_id": str(uuid4()),
                    "name": "Batch",
                    "status": "planned",
                    "planned_date": "2026-07-01",
                    "actual_date": None,
                    "evidence": [
                        {
                            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                            "source_table": "milestones",
                            "source_row_id": str(uuid4()),
                            "visibility": EvidenceVisibility.CLIENT_SAFE,
                            "claim_keys": ["milestone_status"],
                            "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                            "source_fingerprint": "a" * 64,
                            "observed_at": "2026-06-01T00:00:00+00:00",
                        }
                    ],
                },
                "source_data_quality": DataQualityState.STALE,
                "trend": DeliveryConfidenceTrend.UNKNOWN,
                "mitigation_contribution": MitigationContributionState.UNAVAILABLE,
                "evidence": [
                    {
                        "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                        "source_table": "delivery_confidence_scores",
                        "source_row_id": str(uuid4()),
                        "visibility": EvidenceVisibility.CLIENT_SAFE,
                        "claim_keys": ["score_pct"],
                        "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                        "source_fingerprint": "a" * 64,
                        "observed_at": "2026-06-10T00:00:00+00:00",
                    }
                ],
                "source_fingerprint": "a" * 64,
                "assessed_at": "2026-06-18T12:00:00+00:00",
            }
        )


def test_calculated_trend_without_previous_lineage_rejected() -> None:
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(
            {
                "org_id": str(_ORG),
                "project_id": str(uuid4()),
                "reporting_period": resolve_reporting_period(_AS_OF).model_dump(
                    mode="json"
                ),
                "visibility_mode": EvidenceVisibility.INTERNAL,
                "availability": DeliveryConfidenceAvailability.AVAILABLE,
                "score_pct": "88.50",
                "confidence_band": "confident",
                "confidence_band_is_delivery_owned_status": True,
                "current_milestone": {
                    "milestone_id": str(uuid4()),
                    "name": "Batch",
                    "status": "planned",
                    "planned_date": "2026-07-01",
                    "actual_date": None,
                    "evidence": [
                        {
                            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                            "source_table": "milestones",
                            "source_row_id": str(uuid4()),
                            "visibility": EvidenceVisibility.CLIENT_SAFE,
                            "claim_keys": ["milestone_status"],
                            "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                            "source_fingerprint": "a" * 64,
                            "observed_at": "2026-06-01T00:00:00+00:00",
                        }
                    ],
                },
                "source_data_quality": DataQualityState.COMPLETE,
                "trend": DeliveryConfidenceTrend.INCREASED,
                "previous_score_pct": None,
                "mitigation_contribution": MitigationContributionState.UNAVAILABLE,
                "evidence": [
                    {
                        "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                        "source_table": "delivery_confidence_scores",
                        "source_row_id": str(uuid4()),
                        "visibility": EvidenceVisibility.CLIENT_SAFE,
                        "claim_keys": ["score_pct"],
                        "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                        "source_fingerprint": "a" * 64,
                        "observed_at": "2026-06-10T00:00:00+00:00",
                    }
                ],
                "source_fingerprint": "a" * 64,
                "assessed_at": "2026-06-18T12:00:00+00:00",
            }
        )


def test_non_hex_source_fingerprint_rejected() -> None:
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(
            {
                "org_id": str(_ORG),
                "project_id": str(uuid4()),
                "reporting_period": resolve_reporting_period(_AS_OF).model_dump(
                    mode="json"
                ),
                "visibility_mode": EvidenceVisibility.INTERNAL,
                "availability": DeliveryConfidenceAvailability.NO_SCORE,
                "source_data_quality": DataQualityState.UNAVAILABLE,
                "trend": DeliveryConfidenceTrend.UNKNOWN,
                "mitigation_contribution": MitigationContributionState.UNAVAILABLE,
                "source_fingerprint": "g" * 64,
                "assessed_at": "2026-06-18T12:00:00+00:00",
            }
        )


def test_no_score_missing_policy_adds_unavailable_limitation() -> None:
    pack = _complete_pack(confidence_score=None)
    result = assess_delivery_confidence(pack, explanation_policy=None)
    assert result.availability == DeliveryConfidenceAvailability.NO_SCORE
    assert LIMITATION_EXPLANATION_POLICY_UNAVAILABLE in result.limitations
    assert LIMITATION_EXPLANATION_NOT_EVALUATED_NO_SCORE not in result.limitations


def test_no_score_supplied_policy_not_evaluated() -> None:
    evaluated = {"count": 0}

    class _MustNotRun(_FixtureExplanationPolicy):
        @property
        def rules_version(self) -> str:
            evaluated["count"] += 1
            return super().rules_version

        def evaluate(self, candidates):
            evaluated["count"] += 10
            raise AssertionError("policy must not evaluate on NO_SCORE")

    pack = _complete_pack(confidence_score=None)
    result = assess_delivery_confidence(pack, explanation_policy=_MustNotRun())
    assert LIMITATION_EXPLANATION_NOT_EVALUATED_NO_SCORE in result.limitations
    assert LIMITATION_EXPLANATION_POLICY_UNAVAILABLE not in result.limitations
    assert evaluated["count"] == 0
    assert result.rules_version is None
    assert result.positive_drivers == []


def test_regression_exact_decimal_status_forecast_milestone_unchanged() -> None:
    score = Decimal("91.25")
    pack = _complete_pack(confidence_score=score, confidence_status="watch_custom")
    conf = pack.delivery.latest_delivery_confidence
    assert conf is not None
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert result.score_pct == score
    assert result.confidence_band == "watch_custom"
    assert result.forecast_completion_date == conf.forecast_completion_date
    assert result.current_milestone is not None
    assert result.current_milestone.milestone_id == conf.milestone_id


def test_regression_aligned_prior_trend_remains_correct() -> None:
    current = _complete_pack(confidence_score=Decimal("90.00"))
    previous = _aligned_previous(current, score=Decimal("80.00"))
    result = assess_delivery_confidence(current, previous=previous)
    assert result.trend == DeliveryConfidenceTrend.INCREASED
    assert result.previous_score_pct == Decimal("80.00")
    assert result.previous_source_fingerprint == previous.source_fingerprint


def test_regression_identical_inputs_remain_deterministic() -> None:
    pack = _complete_pack()
    previous = _aligned_previous(pack)
    policy = _FixtureExplanationPolicy()
    first = assess_delivery_confidence(pack, explanation_policy=policy, previous=previous)
    second = assess_delivery_confidence(
        pack, explanation_policy=policy, previous=previous
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def _assessment_payload(**overrides: object) -> dict:
    period = resolve_reporting_period(_AS_OF).model_dump(mode="json")
    milestone_id = str(uuid4())
    conf_id = str(uuid4())
    fp = "a" * 64
    milestone_evidence = {
        "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
        "source_table": "milestones",
        "source_row_id": milestone_id,
        "visibility": EvidenceVisibility.CLIENT_SAFE,
        "claim_keys": [
            "milestone_id",
            "milestone_name",
            "milestone_status",
            "planned_date",
        ],
        "period": DeliveryConfidenceEvidencePeriod.CURRENT,
        "source_fingerprint": fp,
        "observed_at": "2026-06-01T00:00:00+00:00",
    }
    payload: dict = {
        "org_id": str(_ORG),
        "project_id": str(uuid4()),
        "reporting_period": period,
        "visibility_mode": EvidenceVisibility.INTERNAL,
        "availability": DeliveryConfidenceAvailability.AVAILABLE,
        "score_pct": "88.50",
        "confidence_band": "confident",
        "confidence_band_is_delivery_owned_status": True,
        "current_milestone": {
            "milestone_id": milestone_id,
            "name": "Batch",
            "status": "planned",
            "planned_date": "2026-07-01",
            "actual_date": None,
            "evidence": [milestone_evidence],
        },
        "observed_at": "2026-06-10T00:00:00+00:00",
        "source_data_quality": DataQualityState.COMPLETE,
        "trend": DeliveryConfidenceTrend.UNKNOWN,
        "mitigation_contribution": MitigationContributionState.UNAVAILABLE,
        "limitations": [],
        "source_limitations": [],
        "evidence": [
            {
                "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                "source_table": "delivery_confidence_scores",
                "source_row_id": conf_id,
                "visibility": EvidenceVisibility.CLIENT_SAFE,
                "claim_keys": [
                    "score_pct",
                    "confidence_status",
                    "forecast_completion_date",
                ],
                "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                "source_fingerprint": fp,
                "observed_at": "2026-06-10T00:00:00+00:00",
            },
            dict(milestone_evidence),
        ],
        "source_fingerprint": fp,
        "assessed_at": "2026-06-18T12:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_production_sentence_source_limitation_available_succeeds() -> None:
    note = "Delivery confidence source note is unavailable."
    pack = _complete_pack(limitations=[note])
    result = assess_delivery_confidence(pack)
    assert result.availability == DeliveryConfidenceAvailability.AVAILABLE
    assert note in result.source_limitations
    assert note not in result.limitations


def test_production_sentence_source_limitation_no_score_succeeds() -> None:
    note = "Delivery confidence source note is unavailable."
    pack = _complete_pack(confidence_score=None, limitations=[note])
    result = assess_delivery_confidence(pack)
    assert result.availability == DeliveryConfidenceAvailability.NO_SCORE
    assert note in result.source_limitations
    assert note not in result.limitations


def test_source_limitations_deduplicated_deterministically() -> None:
    note = "Duplicate source limitation text."
    pack = _complete_pack(limitations=[note, note, "Another note.", "Another note."])
    result = assess_delivery_confidence(pack)
    assert result.source_limitations == sorted({"Another note.", note})


def test_blank_source_limitation_filtered_by_contract() -> None:
    assessment = DeliveryConfidenceAssessment.model_validate(
        _assessment_payload(source_limitations=["ok text", "   ", "", "ok text"])
    )
    assert assessment.source_limitations == ["ok text"]


def test_policy_never_receives_source_limitation_text() -> None:
    note = "Delivery confidence source note is unavailable."
    pack = _complete_pack(limitations=[note])
    seen: dict[str, object] = {}

    class _Probe(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            blob = candidates.model_dump(mode="json")
            seen["blob"] = str(blob)
            assert note not in str(blob)
            assert not any(
                note.lower() in item.lower() for item in candidates.context_limitations
            )
            return super().evaluate(candidates)

    result = assess_delivery_confidence(pack, explanation_policy=_Probe())
    assert note in result.source_limitations
    assert "blob" in seen


def test_structured_engine_codes_remain_reason_validated() -> None:
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(
            _assessment_payload(limitations=["not a reason code"])
        )


def test_stale_risk_candidate_emits_structured_quality_limitation() -> None:
    pack = _with_domain_facts(
        _complete_pack(), risk=True, risk_dq=DataQualityState.STALE
    )
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert "SOURCE_QUALITY_STALE_RISK_ALERTS" in result.limitations
    assert LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS not in result.limitations


def test_conflicting_quality_candidate_emits_structured_limitation() -> None:
    pack = _with_domain_facts(
        _complete_pack(), quality=True, quality_dq=DataQualityState.CONFLICTING
    )
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert "SOURCE_QUALITY_CONFLICTING_QUALITY_SNAPSHOTS" in result.limitations


def test_partial_throughput_candidate_emits_structured_limitation() -> None:
    pack = _with_domain_facts(
        _complete_pack(), throughput=True, throughput_dq=DataQualityState.PARTIAL
    )
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert "SOURCE_QUALITY_PARTIAL_THROUGHPUT_SNAPSHOTS" in result.limitations


def test_unavailable_candidate_source_cannot_support_driver() -> None:
    pack = _with_domain_facts(
        _complete_pack(), risk=True, risk_dq=DataQualityState.UNAVAILABLE
    )

    def _mutate(candidates, decision):
        risk = next(
            item
            for item in candidates.candidates
            if item.category == DeliveryConfidenceCandidateCategory.RISK
        )
        assert risk.data_quality == DataQualityState.UNAVAILABLE
        bad = DeliveryConfidenceDriver(
            driver_key="risk_unavailable_driver",
            polarity=DeliveryConfidenceDriverPolarity.NEGATIVE,
            category=DeliveryConfidenceCandidateCategory.RISK,
            reason_code="RISK_UNAVAILABLE_DRIVER",
            materiality=1,
            candidate_keys=[risk.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=risk.source_agent,
                    source_table=risk.source_table,
                    source_row_id=risk.source_row_id,
                    visibility=risk.visibility,
                    claim_keys=[risk.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=risk.source_fingerprint,
                    observed_at=risk.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return decision.model_copy(update={"negative_drivers": [bad]})

    with pytest.raises(DeliveryConfidenceIntegrityError) as (exc):
        assess_delivery_confidence(
            pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
        )
    assert exc.value.code == "invalid_policy_decision"
    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert "SOURCE_QUALITY_UNAVAILABLE_RISK_ALERTS" in result.limitations


def test_missing_quality_distinct_from_unreliable_quality() -> None:
    missing = _with_domain_facts(_complete_pack(), risk=True, risk_dq=None)
    stale = _with_domain_facts(
        _complete_pack(), risk=True, risk_dq=DataQualityState.STALE
    )
    missing_result = assess_delivery_confidence(
        missing, explanation_policy=_FixtureExplanationPolicy()
    )
    stale_result = assess_delivery_confidence(
        stale, explanation_policy=_FixtureExplanationPolicy()
    )
    assert LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS in missing_result.limitations
    assert "SOURCE_QUALITY_STALE_RISK_ALERTS" not in missing_result.limitations
    assert "SOURCE_QUALITY_STALE_RISK_ALERTS" in stale_result.limitations
    assert LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS not in stale_result.limitations


def test_risk_fact_none_evidence_timestamp_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(
        _complete_pack(), risk=True, risk_observed_at=None
    )
    risk = pack.delivery.open_risks[0]
    refs = []
    for item in pack.evidence:
        if item.source_table == "risk_alerts" and item.source_row_id == risk.id:
            refs.append(
                item.model_copy(
                    update={"observed_at": datetime(2026, 6, 2, tzinfo=UTC)}
                )
            )
        else:
            refs.append(item)
    pack = pack.model_copy(update={"evidence": refs})
    with pytest.raises(DeliveryConfidenceIntegrityError):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)


def test_risk_fact_timestamp_evidence_none_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(_complete_pack(), risk=True)
    risk = pack.delivery.open_risks[0]
    refs = []
    for item in pack.evidence:
        if item.source_table == "risk_alerts" and item.source_row_id == risk.id:
            refs.append(item.model_copy(update={"observed_at": None}))
        else:
            refs.append(item)
    pack = pack.model_copy(update={"evidence": refs})
    with pytest.raises(DeliveryConfidenceIntegrityError):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)


def test_quality_fact_none_evidence_timestamp_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(_complete_pack(), quality=True)
    snap = pack.quality.current_period[0]
    quality_rows = [
        snap.model_copy(update={"observed_at": None}),
    ]
    pack = pack.model_copy(
        update={"quality": pack.quality.model_copy(update={"current_period": quality_rows})}
    )
    with pytest.raises(DeliveryConfidenceIntegrityError):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)


def test_bottleneck_fact_none_evidence_timestamp_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(_complete_pack(), bottleneck=True)
    bn = pack.delivery.open_bottlenecks[0]
    delivery = pack.delivery.model_copy(
        update={
            "open_bottlenecks": [
                bn.model_copy(update={"observed_at": None}),
            ]
        }
    )
    pack = pack.model_copy(update={"delivery": delivery})
    with pytest.raises(DeliveryConfidenceIntegrityError):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)


def test_dependency_fact_none_evidence_timestamp_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_pack_validation(monkeypatch)
    pack = _with_domain_facts(_complete_pack(), dependency=True)
    dep = pack.governance.dependencies[0]
    governance = pack.governance.model_copy(
        update={
            "dependencies": [dep.model_copy(update={"observed_at": None})],
        }
    )
    pack = pack.model_copy(update={"governance": governance})
    with pytest.raises(DeliveryConfidenceIntegrityError):
        _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)


def test_milestone_without_fact_timestamp_uses_evidence_observed_at() -> None:
    pack = _complete_pack()
    milestone_ref = next(
        item for item in pack.evidence if item.source_table == "milestones"
    )
    context = _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    candidate = next(
        item for item in context.candidates if item.candidate_key == "milestone.status"
    )
    assert candidate.observed_at == milestone_ref.observed_at
    assert candidate.observed_at is not None


def test_throughput_without_fact_timestamp_uses_evidence_observed_at() -> None:
    pack = _with_domain_facts(_complete_pack(), throughput=True)
    tp_ref = next(
        item for item in pack.evidence if item.source_table == "throughput_snapshots"
    )
    context = _build_candidate_context(pack, source_quality=DataQualityState.COMPLETE)
    candidate = next(
        item
        for item in context.candidates
        if item.candidate_key == "throughput.rolling_7day_units"
    )
    assert candidate.observed_at == tp_ref.observed_at


class _RiskDriverPolicy(_FixtureExplanationPolicy):
    def evaluate(self, candidates):
        risk = next(
            item
            for item in candidates.candidates
            if item.category == DeliveryConfidenceCandidateCategory.RISK
        )
        driver = DeliveryConfidenceDriver(
            driver_key="risk_open_driver",
            polarity=DeliveryConfidenceDriverPolarity.NEGATIVE,
            category=DeliveryConfidenceCandidateCategory.RISK,
            reason_code="RISK_OPEN",
            materiality=1,
            candidate_keys=[risk.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=risk.source_agent,
                    source_table=risk.source_table,
                    source_row_id=risk.source_row_id,
                    visibility=risk.visibility,
                    claim_keys=[risk.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=risk.source_fingerprint,
                    observed_at=risk.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return DeliveryConfidenceExplanationDecision(
            positive_drivers=[],
            negative_drivers=[driver],
            policy_limitations=[],
        )


class _QualityDriverPolicy(_FixtureExplanationPolicy):
    def evaluate(self, candidates):
        quality = next(
            item
            for item in candidates.candidates
            if item.category == DeliveryConfidenceCandidateCategory.QUALITY
        )
        driver = DeliveryConfidenceDriver(
            driver_key="quality_rework_driver",
            polarity=DeliveryConfidenceDriverPolarity.NEGATIVE,
            category=DeliveryConfidenceCandidateCategory.QUALITY,
            reason_code="QUALITY_REWORK",
            materiality=1,
            candidate_keys=[quality.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=quality.source_agent,
                    source_table=quality.source_table,
                    source_row_id=quality.source_row_id,
                    visibility=quality.visibility,
                    claim_keys=[quality.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=quality.source_fingerprint,
                    observed_at=quality.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return DeliveryConfidenceExplanationDecision(
            positive_drivers=[],
            negative_drivers=[driver],
            policy_limitations=[],
        )


def test_risk_driver_evidence_appears_in_top_level_assessment() -> None:
    pack = _with_domain_facts(_complete_pack(), risk=True)
    result = assess_delivery_confidence(pack, explanation_policy=_RiskDriverPolicy())
    assert result.negative_drivers
    risk_ev = result.negative_drivers[0].evidence[0]
    assert any(
        item.source_table == risk_ev.source_table
        and item.source_row_id == risk_ev.source_row_id
        and risk_ev.claim_keys[0] in item.claim_keys
        for item in result.evidence
    )


def test_quality_driver_evidence_appears_in_top_level_assessment() -> None:
    pack = _with_domain_facts(_complete_pack(), quality=True)
    result = assess_delivery_confidence(
        pack, explanation_policy=_QualityDriverPolicy()
    )
    quality_ev = result.negative_drivers[0].evidence[0]
    assert any(
        item.source_table == quality_ev.source_table
        and item.source_row_id == quality_ev.source_row_id
        and "rework_rate_pct" in item.claim_keys
        for item in result.evidence
    )


def test_multiple_drivers_preserve_claim_key_union_on_shared_row() -> None:
    pack = _complete_pack()

    def _mutate(candidates, decision):
        by_key = {item.candidate_key: item for item in candidates.candidates}
        score = by_key["delivery_confidence.score_pct"]
        status = by_key["delivery_confidence.status"]
        pos = DeliveryConfidenceDriver(
            driver_key="score_driver",
            polarity=DeliveryConfidenceDriverPolarity.POSITIVE,
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            reason_code="SCORE_PRESENT",
            materiality=1,
            candidate_keys=[score.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=score.source_agent,
                    source_table=score.source_table,
                    source_row_id=score.source_row_id,
                    visibility=score.visibility,
                    claim_keys=[score.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=score.source_fingerprint,
                    observed_at=score.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        neg = DeliveryConfidenceDriver(
            driver_key="status_driver",
            polarity=DeliveryConfidenceDriverPolarity.NEGATIVE,
            category=DeliveryConfidenceCandidateCategory.DELIVERY_CONFIDENCE,
            reason_code="STATUS_WATCH",
            materiality=2,
            candidate_keys=[status.candidate_key],
            evidence=[
                DeliveryConfidenceEvidenceRef(
                    source_agent=status.source_agent,
                    source_table=status.source_table,
                    source_row_id=status.source_row_id,
                    visibility=status.visibility,
                    claim_keys=[status.claim_key],
                    period=DeliveryConfidenceEvidencePeriod.CURRENT,
                    source_fingerprint=status.source_fingerprint,
                    observed_at=status.observed_at,
                )
            ],
            data_quality=DataQualityState.COMPLETE,
        )
        return decision.model_copy(
            update={"positive_drivers": [pos], "negative_drivers": [neg]}
        )

    result = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy(mutate=_mutate)
    )
    row = next(
        item
        for item in result.evidence
        if item.source_table == "delivery_confidence_scores"
        and item.period == DeliveryConfidenceEvidencePeriod.CURRENT
    )
    assert "score_pct" in row.claim_keys
    assert "confidence_status" in row.claim_keys


def test_driver_evidence_missing_from_top_level_rejected_by_contract() -> None:
    payload = _assessment_payload()
    driver_row = {
        "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
        "source_table": "risk_alerts",
        "source_row_id": str(uuid4()),
        "visibility": EvidenceVisibility.INTERNAL,
        "claim_keys": ["status"],
        "period": DeliveryConfidenceEvidencePeriod.CURRENT,
        "source_fingerprint": "a" * 64,
        "observed_at": "2026-06-02T00:00:00+00:00",
    }
    payload["negative_drivers"] = [
        {
            "driver_key": "orphan_risk",
            "polarity": DeliveryConfidenceDriverPolarity.NEGATIVE,
            "category": DeliveryConfidenceCandidateCategory.RISK,
            "reason_code": "ORPHAN_RISK",
            "materiality": 1,
            "candidate_keys": ["risk.status.deadbeef"],
            "evidence": [driver_row],
            "data_quality": DataQualityState.COMPLETE,
        }
    ]
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_top_level_current_wrong_fingerprint_rejected() -> None:
    payload = _assessment_payload()
    payload["evidence"][0]["source_fingerprint"] = "b" * 64
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_top_level_previous_wrong_fingerprint_rejected() -> None:
    payload = _assessment_payload(
        trend=DeliveryConfidenceTrend.INCREASED,
        previous_score_pct="70.00",
        previous_source_fingerprint="c" * 64,
    )
    payload["evidence"].append(
        {
            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
            "source_table": "delivery_confidence_scores",
            "source_row_id": str(uuid4()),
            "visibility": EvidenceVisibility.CLIENT_SAFE,
            "claim_keys": ["score_pct"],
            "period": DeliveryConfidenceEvidencePeriod.PREVIOUS,
            "source_fingerprint": "d" * 64,
            "observed_at": "2026-06-03T00:00:00+00:00",
        }
    )
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_previous_evidence_without_previous_fingerprint_rejected() -> None:
    payload = _assessment_payload(previous_source_fingerprint=None)
    payload["evidence"].append(
        {
            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
            "source_table": "delivery_confidence_scores",
            "source_row_id": str(uuid4()),
            "visibility": EvidenceVisibility.CLIENT_SAFE,
            "claim_keys": ["score_pct"],
            "period": DeliveryConfidenceEvidencePeriod.PREVIOUS,
            "source_fingerprint": "a" * 64,
            "observed_at": "2026-06-03T00:00:00+00:00",
        }
    )
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_driver_top_level_observed_at_mismatch_rejected() -> None:
    payload = _assessment_payload()
    risk_id = str(uuid4())
    payload["evidence"].append(
        {
            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
            "source_table": "risk_alerts",
            "source_row_id": risk_id,
            "visibility": EvidenceVisibility.INTERNAL,
            "claim_keys": ["status"],
            "period": DeliveryConfidenceEvidencePeriod.CURRENT,
            "source_fingerprint": "a" * 64,
            "observed_at": "2026-06-02T00:00:00+00:00",
        }
    )
    payload["negative_drivers"] = [
        {
            "driver_key": "risk_mismatch",
            "polarity": DeliveryConfidenceDriverPolarity.NEGATIVE,
            "category": DeliveryConfidenceCandidateCategory.RISK,
            "reason_code": "RISK_MISMATCH",
            "materiality": 1,
            "candidate_keys": ["risk.status.aabb"],
            "evidence": [
                {
                    "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                    "source_table": "risk_alerts",
                    "source_row_id": risk_id,
                    "visibility": EvidenceVisibility.INTERNAL,
                    "claim_keys": ["status"],
                    "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                    "source_fingerprint": "a" * 64,
                    "observed_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "data_quality": DataQualityState.COMPLETE,
        }
    ]
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_driver_top_level_claim_key_mismatch_rejected() -> None:
    payload = _assessment_payload()
    risk_id = str(uuid4())
    payload["evidence"].append(
        {
            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
            "source_table": "risk_alerts",
            "source_row_id": risk_id,
            "visibility": EvidenceVisibility.INTERNAL,
            "claim_keys": ["status"],
            "period": DeliveryConfidenceEvidencePeriod.CURRENT,
            "source_fingerprint": "a" * 64,
            "observed_at": "2026-06-02T00:00:00+00:00",
        }
    )
    payload["negative_drivers"] = [
        {
            "driver_key": "risk_claim",
            "polarity": DeliveryConfidenceDriverPolarity.NEGATIVE,
            "category": DeliveryConfidenceCandidateCategory.RISK,
            "reason_code": "RISK_CLAIM",
            "materiality": 1,
            "candidate_keys": ["risk.status.aabb"],
            "evidence": [
                {
                    "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
                    "source_table": "risk_alerts",
                    "source_row_id": risk_id,
                    "visibility": EvidenceVisibility.INTERNAL,
                    "claim_keys": ["status", "risk_tier"],
                    "period": DeliveryConfidenceEvidencePeriod.CURRENT,
                    "source_fingerprint": "a" * 64,
                    "observed_at": "2026-06-02T00:00:00+00:00",
                }
            ],
            "data_quality": DataQualityState.COMPLETE,
        }
    ]
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_client_safe_top_level_rejects_internal_driver_evidence() -> None:
    payload = _assessment_payload(visibility_mode=EvidenceVisibility.CLIENT_SAFE)
    for item in payload["evidence"]:
        item["visibility"] = EvidenceVisibility.CLIENT_SAFE.value
    payload["current_milestone"]["evidence"][0]["visibility"] = (
        EvidenceVisibility.CLIENT_SAFE.value
    )
    risk_id = str(uuid4())
    payload["evidence"].append(
        {
            "source_agent": SourceAgent.DELIVERY_PERFORMANCE,
            "source_table": "risk_alerts",
            "source_row_id": risk_id,
            "visibility": EvidenceVisibility.INTERNAL,
            "claim_keys": ["status"],
            "period": DeliveryConfidenceEvidencePeriod.CURRENT,
            "source_fingerprint": "a" * 64,
            "observed_at": "2026-06-02T00:00:00+00:00",
        }
    )
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


@pytest.mark.parametrize(
    "state",
    [
        DataQualityState.STALE,
        DataQualityState.CONFLICTING,
        DataQualityState.PARTIAL,
    ],
)
def test_unreliable_current_confidence_does_not_evaluate_policy(
    state: DataQualityState,
) -> None:
    evaluated = {"count": 0}

    class _MustNotEvaluate(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            evaluated["count"] += 1
            raise AssertionError("must not evaluate on unreliable source")

    pack = _pack_with_dc_quality(state)
    result = assess_delivery_confidence(
        pack, explanation_policy=_MustNotEvaluate()
    )
    assert evaluated["count"] == 0
    assert result.positive_drivers == []
    assert result.negative_drivers == []
    assert LIMITATION_EXPLANATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations
    assert result.rules_version == _TEST_RULES


def test_finalize_no_score_policy_behavior_unchanged() -> None:
    pack = _complete_pack(confidence_score=None)
    missing = assess_delivery_confidence(pack, explanation_policy=None)
    assert LIMITATION_EXPLANATION_POLICY_UNAVAILABLE in missing.limitations
    supplied = assess_delivery_confidence(
        pack, explanation_policy=_FixtureExplanationPolicy()
    )
    assert LIMITATION_EXPLANATION_NOT_EVALUATED_NO_SCORE in supplied.limitations


_REQUIRED_MS_CLAIMS = [
    "milestone_id",
    "milestone_name",
    "milestone_status",
    "planned_date",
]


def _valid_nested_milestone_evidence(
    milestone_id: UUID,
    *,
    fingerprint: str = "a" * 64,
    visibility: EvidenceVisibility = EvidenceVisibility.CLIENT_SAFE,
    claim_keys: list[str] | None = None,
    observed_at: str = "2026-06-01T00:00:00+00:00",
    source_table: str = "milestones",
    source_agent: SourceAgent = SourceAgent.DELIVERY_PERFORMANCE,
    period: DeliveryConfidenceEvidencePeriod = DeliveryConfidenceEvidencePeriod.CURRENT,
    source_row_id: UUID | None = None,
) -> dict:
    return {
        "source_agent": source_agent,
        "source_table": source_table,
        "source_row_id": str(source_row_id or milestone_id),
        "visibility": visibility,
        "claim_keys": claim_keys or list(_REQUIRED_MS_CLAIMS),
        "period": period,
        "source_fingerprint": fingerprint,
        "observed_at": observed_at,
    }


def test_engine_assessment_contains_top_level_milestone_evidence() -> None:
    pack = _complete_pack()
    result = assess_delivery_confidence(pack)
    assert result.current_milestone is not None
    nested = result.current_milestone.evidence[0]
    top = [
        item
        for item in result.evidence
        if item.source_table == "milestones"
        and item.source_row_id == result.current_milestone.milestone_id
    ]
    assert top
    assert set(nested.claim_keys).issubset(set(top[0].claim_keys))
    assert {
        "milestone_id",
        "milestone_name",
        "milestone_status",
        "planned_date",
    }.issubset(set(top[0].claim_keys))


def test_nested_milestone_only_status_rejected() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "actual_date": None,
                "evidence": [
                    _valid_nested_milestone_evidence(
                        mid, claim_keys=["milestone_status"]
                    )
                ],
            }
        )


def test_nested_milestone_missing_milestone_id_claim_rejected() -> None:
    mid = uuid4()
    claims = [c for c in _REQUIRED_MS_CLAIMS if c != "milestone_id"]
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [_valid_nested_milestone_evidence(mid, claim_keys=claims)],
            }
        )


def test_nested_milestone_missing_milestone_name_claim_rejected() -> None:
    mid = uuid4()
    claims = [c for c in _REQUIRED_MS_CLAIMS if c != "milestone_name"]
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [_valid_nested_milestone_evidence(mid, claim_keys=claims)],
            }
        )


def test_nested_milestone_missing_planned_date_claim_rejected() -> None:
    mid = uuid4()
    claims = [c for c in _REQUIRED_MS_CLAIMS if c != "planned_date"]
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [_valid_nested_milestone_evidence(mid, claim_keys=claims)],
            }
        )


def test_nested_milestone_actual_date_without_claim_rejected() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "done",
                "planned_date": "2026-07-01",
                "actual_date": "2026-07-02",
                "evidence": [
                    _valid_nested_milestone_evidence(
                        mid, claim_keys=list(_REQUIRED_MS_CLAIMS)
                    )
                ],
            }
        )


def test_nested_milestone_wrong_source_row_rejected() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [
                    _valid_nested_milestone_evidence(mid, source_row_id=uuid4())
                ],
            }
        )


def test_nested_milestone_wrong_table_rejected() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [
                    _valid_nested_milestone_evidence(
                        mid, source_table="delivery_confidence_scores"
                    )
                ],
            }
        )


def test_nested_milestone_wrong_source_agent_rejected() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [
                    _valid_nested_milestone_evidence(
                        mid, source_agent=SourceAgent.PROJECT_GOVERNANCE
                    )
                ],
            }
        )


def test_nested_milestone_previous_period_rejected() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        DeliveryConfidenceMilestoneView.model_validate(
            {
                "milestone_id": str(mid),
                "name": "Batch",
                "status": "planned",
                "planned_date": "2026-07-01",
                "evidence": [
                    _valid_nested_milestone_evidence(
                        mid, period=DeliveryConfidenceEvidencePeriod.PREVIOUS
                    )
                ],
            }
        )


def test_nested_milestone_wrong_fingerprint_rejected_by_assessment() -> None:
    payload = _assessment_payload()
    payload["current_milestone"]["evidence"][0]["source_fingerprint"] = "b" * 64
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_nested_milestone_missing_from_top_level_rejected() -> None:
    payload = _assessment_payload()
    payload["evidence"] = [
        item
        for item in payload["evidence"]
        if item["source_table"] != "milestones"
    ]
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_nested_top_level_milestone_observed_at_mismatch_rejected() -> None:
    payload = _assessment_payload()
    for item in payload["evidence"]:
        if item["source_table"] == "milestones":
            item["observed_at"] = "2026-01-01T00:00:00+00:00"
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_nested_milestone_claims_not_in_top_level_union_rejected() -> None:
    payload = _assessment_payload()
    for item in payload["evidence"]:
        if item["source_table"] == "milestones":
            item["claim_keys"] = [
                "milestone_id",
                "milestone_name",
                "milestone_status",
            ]
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_client_safe_internal_nested_milestone_rejected() -> None:
    payload = _assessment_payload(visibility_mode=EvidenceVisibility.CLIENT_SAFE)
    for item in payload["evidence"]:
        item["visibility"] = EvidenceVisibility.CLIENT_SAFE.value
    payload["current_milestone"]["evidence"][0]["visibility"] = (
        EvidenceVisibility.INTERNAL.value
    )
    with pytest.raises(ValidationError):
        DeliveryConfidenceAssessment.model_validate(payload)


def test_exact_valid_nested_top_level_milestone_lineage_accepted() -> None:
    payload = _assessment_payload()
    assessment = DeliveryConfidenceAssessment.model_validate(payload)
    assert assessment.current_milestone is not None
    nested = assessment.current_milestone.evidence[0]
    top = next(
        item
        for item in assessment.evidence
        if item.source_table == "milestones"
    )
    assert nested.source_row_id == assessment.current_milestone.milestone_id
    assert set(nested.claim_keys).issubset(set(top.claim_keys))
    assert nested.observed_at == top.observed_at
    assert nested.source_fingerprint == assessment.source_fingerprint


def test_milestone_lineage_preserves_confidence_trend_driver_behavior() -> None:
    current = _complete_pack(confidence_score=Decimal("90.00"))
    previous = _aligned_previous(current, score=Decimal("80.00"))
    result = assess_delivery_confidence(
        current,
        previous=previous,
        explanation_policy=_FixtureExplanationPolicy(),
    )
    assert result.trend == DeliveryConfidenceTrend.INCREASED
    assert result.positive_drivers
    assert any(
        item.source_table == "delivery_confidence_scores"
        and item.period == DeliveryConfidenceEvidencePeriod.CURRENT
        for item in result.evidence
    )
    assert any(
        item.source_table == "milestones" for item in result.evidence
    )


def test_milestone_finalize_policy_mutation_bypass_still_closed() -> None:
    pack = _complete_pack(org_id=_ORG)
    original_org = pack.project.org_id
    original_fp = pack.source_fingerprint
    held = {"pack": pack}

    class _Hostile(_FixtureExplanationPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            owned = held["pack"]
            owned.project.org_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
            owned.source_fingerprint = "b" * 64
            return decision

    result = assess_delivery_confidence(pack, explanation_policy=_Hostile())
    assert result.org_id == original_org
    assert result.source_fingerprint == original_fp


def test_milestone_finalize_production_source_limitations_still_succeed() -> None:
    note = "Delivery confidence source note is unavailable."
    pack = _complete_pack(limitations=[note])
    result = assess_delivery_confidence(pack)
    assert note in result.source_limitations
    assert any(item.source_table == "milestones" for item in result.evidence)


def test_milestone_finalize_identical_inputs_remain_deterministic() -> None:
    pack = _complete_pack()
    previous = _aligned_previous(pack)
    policy = _FixtureExplanationPolicy()
    first = assess_delivery_confidence(pack, explanation_policy=policy, previous=previous)
    second = assess_delivery_confidence(
        pack, explanation_policy=policy, previous=previous
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
