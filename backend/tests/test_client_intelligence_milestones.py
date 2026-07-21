"""Client Intelligence Milestone Intelligence tests (TASK 15)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agents.client_intelligence import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryConfidenceFacts,
    DeliveryEvidenceFacts,
    EvidenceVisibility,
    GovernanceEvidenceFacts,
    KnowledgeEvidenceFacts,
    KnowledgeSourceAvailabilityFacts,
    MilestoneFacts,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    RiskAlertFacts,
    SourceAgent,
    WorkforceEvidenceFacts,
    assess_milestone_intelligence,
    finalize_pack_collections,
    resolve_reporting_period,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    worst_data_quality_state,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    finalize_data_quality_issues,
)
from app.agents.client_intelligence.milestone_intelligence import (
    LIMITATION_SOURCE_QUALITY_CONFLICTING_MILESTONES,
    LIMITATION_SOURCE_QUALITY_PARTIAL_MILESTONES,
    LIMITATION_SOURCE_QUALITY_STALE_MILESTONES,
)
from app.agents.client_intelligence.milestone_intelligence_contracts import (
    LIMITATION_MILESTONE_CONFIDENCE_CONFLICTING,
    LIMITATION_MILESTONE_CONFIDENCE_MILESTONE_MISMATCH,
    LIMITATION_MILESTONE_CONFIDENCE_PARTIAL,
    LIMITATION_MILESTONE_CONFIDENCE_STALE,
    LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE,
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
    MilestoneAtRiskReasonCode,
    MilestoneBlockerState,
    MilestoneConfidenceAvailability,
    MilestoneIntelligenceAssessment,
    MilestoneIntelligenceAvailability,
)

_AS_OF = date(2026, 6, 18)
_ORG = UUID("44444444-4444-4444-8444-444444444444")


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


def _milestone_ref(
    milestone_id: UUID,
    *,
    observed_at: datetime | None = datetime(2026, 6, 1, tzinfo=UTC),
    include_actual: bool = False,
) -> ClientEvidenceReference:
    keys = [
        "milestone_id",
        "milestone_name",
        "milestone_status",
        "planned_date",
    ]
    if include_actual:
        keys.append("actual_date")
    return ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="milestones",
        source_row_id=milestone_id,
        description="milestone",
        visibility=EvidenceVisibility.CLIENT_SAFE,
        observed_at=observed_at,
        claim_keys=keys,
    )


def _confidence_ref(confidence_id: UUID) -> ClientEvidenceReference:
    return ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
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


def _risk_ref(risk_id: UUID, observed_at: datetime) -> ClientEvidenceReference:
    return ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="risk_alerts",
        source_row_id=risk_id,
        description="risk",
        visibility=EvidenceVisibility.INTERNAL,
        observed_at=observed_at,
        claim_keys=[
            "risk_id",
            "risk_title",
            "risk_tier",
            "alert_type",
            "status",
            "risk_detail",
        ],
    )


def _refingerprint(pack: ClientEvidencePack) -> ClientEvidencePack:
    overall = worst_data_quality_state([item.state for item in pack.data_quality])
    return pack.model_copy(
        update={
            "overall_data_quality": overall,
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
                overall_data_quality=overall,
                visibility_limitations=pack.visibility_limitations,
                limitations=pack.limitations,
            ),
        }
    )


def _pack(
    *,
    milestones: list[MilestoneFacts] | None = None,
    milestone_dq: DataQualityState = DataQualityState.COMPLETE,
    next_milestone_id: UUID | None = None,
    confidence: DeliveryConfidenceFacts | None = None,
    confidence_dq: DataQualityState | None = DataQualityState.COMPLETE,
    risks: list[RiskAlertFacts] | None = None,
    risk_dq: DataQualityState | None = None,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    reporting_period=None,
) -> ClientEvidencePack:
    pid = project_id or uuid4()
    oid = org_id or _ORG
    period = reporting_period or resolve_reporting_period(_AS_OF)
    milestone_rows = milestones or []
    refs: list[ClientEvidenceReference] = [
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="projects",
            source_row_id=pid,
            description="project",
            visibility=EvidenceVisibility.CLIENT_SAFE,
            claim_keys=["project_id", "project_name", "project_status"],
        )
    ]
    for milestone in milestone_rows:
        refs.append(
            _milestone_ref(
                milestone.id,
                include_actual=milestone.actual_date is not None,
            )
        )
    dq_rows = [
        DataQualityIssue(source="milestones", state=milestone_dq, detail="milestones")
    ]
    if confidence is not None:
        refs.append(_confidence_ref(confidence.id))
        if confidence_dq is not None:
            dq_rows.append(
                DataQualityIssue(
                    source="delivery_confidence_scores",
                    state=confidence_dq,
                    detail="confidence",
                )
            )
    if risks:
        for risk in risks:
            refs.append(
                _risk_ref(
                    risk.id,
                    risk.observed_at or datetime(2026, 6, 2, tzinfo=UTC),
                )
            )
        if risk_dq is not None:
            dq_rows.append(
                DataQualityIssue(source="risk_alerts", state=risk_dq, detail="risks")
            )
    dq = finalize_data_quality_issues(dq_rows)
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=[],
        limitations=[],
    )
    delivery = DeliveryEvidenceFacts(
        milestones=milestone_rows,
        next_milestone_id=next_milestone_id,
        latest_delivery_confidence=confidence,
        open_risks=risks or [],
        open_bottlenecks=[],
    )
    project = ProjectIdentityFacts(
        project_id=pid,
        org_id=oid,
        project_name="Aurora Labeling",
        project_status="active",
    )
    overall = worst_data_quality_state([item.state for item in dq])
    knowledge = KnowledgeEvidenceFacts(
        documents=[],
        chunks=[],
        source_availability=_knowledge_availability(),
        as_of=period.as_of,
        project_scope_key="abc",
    )
    pack = ClientEvidencePack(
        project=project,
        reporting_period=period,
        visibility_mode=EvidenceVisibility.INTERNAL,
        delivery=delivery,
        quality=QualityEvidenceFacts(
            current_period=[],
            previous_period=[],
            current_iso_year=2026,
            current_iso_week=25,
            previous_iso_year=2026,
            previous_iso_week=24,
        ),
        workforce=WorkforceEvidenceFacts(as_of=period.as_of),
        governance=GovernanceEvidenceFacts(as_of=period.as_of),
        knowledge=knowledge,
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        generated_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        source_fingerprint="0" * 64,
        policy_fingerprint=None,
        visibility_limitations=vis,
        limitations=lim,
    )
    return _refingerprint(pack)


def _milestone(
    *,
    milestone_id: UUID | None = None,
    planned_date: date,
    status: str = "on_track",
    actual_date: date | None = None,
    name: str = "Batch",
) -> MilestoneFacts:
    return MilestoneFacts(
        id=milestone_id or uuid4(),
        name=name,
        planned_date=planned_date,
        actual_date=actual_date,
        status=status,
        description="internal",
    )


def _confidence_for(
    milestone_id: UUID,
    *,
    score: str = "88.50",
    status: str = "on_track",
    forecast: date | None = date(2026, 7, 1),
) -> DeliveryConfidenceFacts:
    return DeliveryConfidenceFacts(
        id=uuid4(),
        milestone_id=milestone_id,
        score_pct=Decimal(score),
        status=status,
        forecast_completion_date=forecast,
        model_version="delivery-v1",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )


def test_empty_milestone_source_unavailable() -> None:
    pack = _pack(milestones=[], milestone_dq=DataQualityState.UNAVAILABLE)
    result = assess_milestone_intelligence(pack)
    assert result.availability == MilestoneIntelligenceAvailability.UNAVAILABLE
    assert result.period_counts.total_count == 0
    assert LIMITATION_MILESTONE_SOURCE_UNAVAILABLE in result.limitations


def test_empty_selected_period_with_source_available() -> None:
    future = _milestone(planned_date=date(2026, 6, 25), status="pending")
    pack = _pack(milestones=[future], next_milestone_id=future.id)
    result = assess_milestone_intelligence(pack)
    assert result.period_counts.total_count == 0
    assert LIMITATION_SELECTED_PERIOD_EMPTY_POPULATION in result.limitations
    assert result.availability == MilestoneIntelligenceAvailability.PARTIAL


def test_inclusive_reporting_period_boundaries() -> None:
    period = resolve_reporting_period(_AS_OF)
    start_item = _milestone(planned_date=period.start_date, status="on_track")
    end_item = _milestone(planned_date=period.as_of, status="pending")
    pack = _pack(
        milestones=[start_item, end_item],
        next_milestone_id=start_item.id,
    )
    result = assess_milestone_intelligence(pack)
    assert result.period_counts.total_count == 2
    ids = {item.milestone_id for item in result.selected_period_items}
    assert ids == {start_item.id, end_item.id}


def test_excludes_future_and_out_of_period_milestones() -> None:
    period = resolve_reporting_period(_AS_OF)
    before = _milestone(planned_date=period.start_date - timedelta(days=1))
    in_period = _milestone(planned_date=period.as_of, status="on_track")
    after = _milestone(planned_date=period.as_of + timedelta(days=1), status="pending")
    pack = _pack(
        milestones=[before, in_period, after],
        next_milestone_id=after.id,
    )
    result = assess_milestone_intelligence(pack)
    assert result.period_counts.total_count == 1
    assert result.selected_period_items[0].milestone_id == in_period.id
    assert result.next_key_milestone is not None
    assert result.next_key_milestone.milestone_id == after.id
def test_exact_count_reconciliation() -> None:
    items = [
        _milestone(planned_date=date(2026, 6, 16), status="on_track"),
        _milestone(planned_date=date(2026, 6, 17), status="at_risk"),
        _milestone(planned_date=date(2026, 6, 18), status="missed"),
        _milestone(planned_date=date(2026, 6, 18), status="completed"),
        _milestone(planned_date=date(2026, 6, 18), status="pending"),
    ]
    pack = _pack(milestones=items, next_milestone_id=items[0].id)
    result = assess_milestone_intelligence(pack)
    counts = result.period_counts
    assert counts.total_count == 5
    assert counts.on_track_count == 1
    assert counts.at_risk_count == 1
    assert counts.missed_count == 1
    assert counts.completed_count == 1
    assert counts.pending_count == 1


def test_on_track_counts_only_explicit_status() -> None:
    unknown = _milestone(planned_date=date(2026, 6, 17), status="planned")
    on_track = _milestone(planned_date=date(2026, 6, 18), status="on_track")
    pack = _pack(milestones=[unknown, on_track], next_milestone_id=on_track.id)
    result = assess_milestone_intelligence(pack)
    assert result.period_counts.total_count == 2
    assert result.period_counts.on_track_count == 1
    assert result.period_counts.unclassified_count == 1
    assert LIMITATION_MILESTONE_STATUS_UNRECOGNIZED in result.limitations


def test_at_risk_and_missed_reason_codes() -> None:
    at_risk = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    missed = _milestone(planned_date=date(2026, 6, 18), status="missed")
    pack = _pack(milestones=[at_risk, missed], next_milestone_id=at_risk.id)
    result = assess_milestone_intelligence(pack)
    by_id = {item.milestone_id: item for item in result.at_risk_items}
    assert by_id[at_risk.id].reason_codes == [
        MilestoneAtRiskReasonCode.SOURCE_STATUS_AT_RISK
    ]
    assert by_id[missed.id].reason_codes == [
        MilestoneAtRiskReasonCode.SOURCE_STATUS_MISSED
    ]


def test_pending_overdue_not_auto_at_risk() -> None:
    overdue = _milestone(planned_date=date(2026, 6, 16), status="pending")
    pack = _pack(milestones=[overdue], next_milestone_id=overdue.id)
    result = assess_milestone_intelligence(pack)
    assert result.at_risk_items == []
    assert result.period_counts.at_risk_count == 0


def test_next_milestone_from_pack_next_milestone_id() -> None:
    first = _milestone(planned_date=date(2026, 6, 16), status="completed")
    second = _milestone(planned_date=date(2026, 6, 25), status="pending")
    pack = _pack(milestones=[first, second], next_milestone_id=second.id)
    result = assess_milestone_intelligence(pack)
    assert result.next_key_milestone is not None
    assert result.next_key_milestone.milestone_id == second.id


def test_missing_next_milestone_id() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=None)
    result = assess_milestone_intelligence(pack)
    assert result.next_key_milestone is None
    assert LIMITATION_NEXT_MILESTONE_ID_UNAVAILABLE in result.limitations


def test_unknown_next_milestone_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.client_intelligence.milestone_intelligence._validate_pack_or_raise",
        lambda _pack: None,
    )
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=uuid4())
    result = assess_milestone_intelligence(pack)
    assert result.next_key_milestone is None
    assert LIMITATION_NEXT_MILESTONE_ID_UNKNOWN in result.limitations


def test_completed_milestone_cannot_be_next() -> None:
    completed = _milestone(planned_date=date(2026, 6, 17), status="completed")
    pack = _pack(milestones=[completed], next_milestone_id=completed.id)
    result = assess_milestone_intelligence(pack)
    assert result.next_key_milestone is None
    assert LIMITATION_NEXT_MILESTONE_COMPLETED in result.limitations


def test_planned_and_actual_date_preservation() -> None:
    actual = date(2026, 6, 17)
    item = _milestone(
        planned_date=date(2026, 6, 16),
        actual_date=actual,
        status="completed",
    )
    pack = _pack(milestones=[item], next_milestone_id=None)
    result = assess_milestone_intelligence(pack)
    published = result.selected_period_items[0]
    assert published.planned_date == date(2026, 6, 16)
    assert published.actual_date == actual


def test_no_invented_forecast_or_revised_dates() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id, forecast=date(2026, 7, 20))
    pack = _pack(
        milestones=[item],
        confidence=confidence,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    published = result.selected_period_items[0]
    assert published.revised_date is None
    assert published.forecast_date is None
    assert published.confidence.forecast_completion_date == date(2026, 7, 20)
    assert result.next_key_milestone is not None
    assert result.next_key_milestone.forecast_date is None


def test_numeric_progress_remains_unavailable() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    progress = result.selected_period_items[0].progress
    assert progress.progress_pct is None
    assert progress.progress_state == "on_track"
    assert LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE in progress.limitations


def test_exact_milestone_linked_confidence_binding() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    view = result.selected_period_items[0].confidence
    assert view.availability == MilestoneConfidenceAvailability.AVAILABLE
    assert view.score_pct == Decimal("88.50")
    assert view.confidence_status == "on_track"
    assert any(ref.source_table == "delivery_confidence_scores" for ref in view.evidence)


def test_confidence_for_other_milestone_not_transferred() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    other = _milestone(planned_date=date(2026, 6, 18), status="pending")
    confidence = _confidence_for(other.id)
    pack = _pack(
        milestones=[item, other],
        confidence=confidence,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    view = result.selected_period_items[0].confidence
    assert view.availability == MilestoneConfidenceAvailability.MISMATCH
    assert LIMITATION_MILESTONE_CONFIDENCE_MILESTONE_MISMATCH in view.limitations


def test_stale_partial_conflicting_confidence_behavior() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    stale_pack = _pack(
        milestones=[item],
        confidence=confidence,
        confidence_dq=DataQualityState.STALE,
        next_milestone_id=item.id,
    )
    stale = assess_milestone_intelligence(stale_pack).selected_period_items[0].confidence
    assert stale.availability == MilestoneConfidenceAvailability.STALE
    assert LIMITATION_MILESTONE_CONFIDENCE_STALE in stale.limitations

    partial_pack = _pack(
        milestones=[item],
        confidence=confidence,
        confidence_dq=DataQualityState.PARTIAL,
        next_milestone_id=item.id,
    )
    partial = assess_milestone_intelligence(partial_pack).selected_period_items[0].confidence
    assert partial.availability == MilestoneConfidenceAvailability.PARTIAL
    assert LIMITATION_MILESTONE_CONFIDENCE_PARTIAL in partial.limitations

    conflicting_pack = _pack(
        milestones=[item],
        confidence=confidence,
        confidence_dq=DataQualityState.CONFLICTING,
        next_milestone_id=item.id,
    )
    conflicting = assess_milestone_intelligence(
        conflicting_pack
    ).selected_period_items[0].confidence
    assert conflicting.availability == MilestoneConfidenceAvailability.CONFLICTING
    assert LIMITATION_MILESTONE_CONFIDENCE_CONFLICTING in conflicting.limitations


def test_exact_milestone_linked_risk_blocker_binding() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    risk_id = uuid4()
    risk = RiskAlertFacts(
        id=risk_id,
        alert_type="milestone_at_risk",
        risk_tier="high",
        title="Delay",
        status="open",
        milestone_id=item.id,
        detail="internal",
        observed_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    pack = _pack(
        milestones=[item],
        risks=[risk],
        risk_dq=DataQualityState.COMPLETE,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    blocker = result.selected_period_items[0].blockers
    assert blocker.state == MilestoneBlockerState.PRESENT
    assert len(blocker.blockers) == 1
    assert blocker.blockers[0].risk_id == risk_id
    assert blocker.blockers[0].alert_type == "milestone_at_risk"
    assert any(
        ref.source_table == "risk_alerts" for ref in blocker.blockers[0].evidence
    )


def test_unrelated_risks_and_bottlenecks_not_attached() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    unrelated = RiskAlertFacts(
        id=uuid4(),
        alert_type="delivery_risk",
        risk_tier="medium",
        title="Portfolio",
        status="open",
        milestone_id=None,
        detail="internal",
        observed_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    other_milestone = _milestone(planned_date=date(2026, 6, 18), status="pending")
    other_risk = RiskAlertFacts(
        id=uuid4(),
        alert_type="milestone_at_risk",
        risk_tier="high",
        title="Other",
        status="open",
        milestone_id=other_milestone.id,
        detail="internal",
        observed_at=datetime(2026, 6, 3, tzinfo=UTC),
    )
    pack = _pack(
        milestones=[item, other_milestone],
        risks=[unrelated, other_risk],
        risk_dq=DataQualityState.COMPLETE,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    blocker = result.selected_period_items[0].blockers
    assert blocker.state == MilestoneBlockerState.NO_SUPPORTED_BLOCKER
    assert blocker.blockers == []
    assert LIMITATION_NO_SUPPORTED_MILESTONE_BLOCKER in blocker.limitations


def test_dependency_link_unavailable() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    dependency = result.selected_period_items[0].dependency
    assert LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE in dependency.limitations


def test_source_quality_states() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    stale = assess_milestone_intelligence(
        _pack(milestones=[item], milestone_dq=DataQualityState.STALE, next_milestone_id=item.id)
    )
    assert stale.availability == MilestoneIntelligenceAvailability.STALE
    assert LIMITATION_SOURCE_QUALITY_STALE_MILESTONES in stale.limitations

    partial = assess_milestone_intelligence(
        _pack(
            milestones=[item],
            milestone_dq=DataQualityState.PARTIAL,
            next_milestone_id=item.id,
        )
    )
    assert partial.availability == MilestoneIntelligenceAvailability.PARTIAL
    assert LIMITATION_SOURCE_QUALITY_PARTIAL_MILESTONES in partial.limitations

    conflicting = assess_milestone_intelligence(
        _pack(milestones=[item], milestone_dq=DataQualityState.CONFLICTING)
    )
    assert conflicting.availability == MilestoneIntelligenceAvailability.CONFLICTING
    assert LIMITATION_SOURCE_QUALITY_CONFLICTING_MILESTONES in conflicting.limitations


def test_evidence_identity_and_claim_coverage() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    milestone_ref = next(
        ref for ref in result.evidence if ref.source_table == "milestones"
    )
    assert milestone_ref.source_row_id == item.id
    assert set(milestone_ref.claim_keys) == {
        "milestone_id",
        "milestone_name",
        "milestone_status",
        "planned_date",
    }
    assert all(ref.source_fingerprint == pack.source_fingerprint for ref in result.evidence)


def test_foreign_project_org_fingerprint_rejected_by_contract() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["org_id"] = uuid4()
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_duplicate_and_orphan_evidence_rejected_by_contract() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["evidence"].append(
        {
            "source_agent": "delivery_performance",
            "source_table": "milestones",
            "source_row_id": str(uuid4()),
            "visibility": "internal",
            "claim_keys": ["milestone_id"],
            "period": "current",
            "source_fingerprint": pack.source_fingerprint,
            "observed_at": None,
        }
    )
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_canonical_deterministic_ordering() -> None:
    second = _milestone(planned_date=date(2026, 6, 18), status="pending", name="B")
    first = _milestone(planned_date=date(2026, 6, 17), status="on_track", name="A")
    pack = _pack(milestones=[second, first], next_milestone_id=first.id)
    result = assess_milestone_intelligence(pack)
    ordered = [item.milestone_id for item in result.selected_period_items]
    assert ordered == [first.id, second.id]


def test_caller_pack_and_result_mutation_isolation() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    before = pack.model_dump(mode="json")
    result = assess_milestone_intelligence(pack)
    snapshot = result.model_dump(mode="json")
    pack.delivery.milestones[0].status = "missed"
    pack.delivery.next_milestone_id = uuid4()
    assert pack.model_dump(mode="json") != before
    assert result.model_dump(mode="json") == snapshot


def test_model_validate_rejects_fabricated_progress_and_counts() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["period_counts"]["on_track_count"] = 99
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)

    bad = result.model_dump()
    bad["selected_period_items"][0]["progress"]["progress_pct"] = "50.0"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_no_llm_persistence_api_or_database_writes() -> None:
    module_source = inspect.getsource(
        __import__(
            "app.agents.client_intelligence.milestone_intelligence",
            fromlist=["milestone_intelligence"],
        )
    )
    forbidden = (
        "openai",
        "anthropic",
        "llm",
        "persist_",
        "APIRouter",
        "session.execute",
        "session.add",
    )
    for token in forbidden:
        assert token not in module_source


def test_entry_point_has_no_policy_parameter() -> None:
    signature = inspect.signature(assess_milestone_intelligence)
    assert "policy" not in signature.parameters


def test_at_risk_item_contract_rejects_fabricated_reason_code() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    period_item = result.selected_period_items[0]
    with pytest.raises(ValidationError):
        AtRiskMilestoneItem(
            org_id=period_item.org_id,
            project_id=period_item.project_id,
            reporting_period=period_item.reporting_period,
            milestone_id=period_item.milestone_id,
            name=period_item.name,
            status="at_risk",
            planned_date=period_item.planned_date,
            actual_date=None,
            reason_codes=[MilestoneAtRiskReasonCode.SOURCE_STATUS_MISSED],
            progress=period_item.progress,
            confidence=period_item.confidence,
            blockers=period_item.blockers,
            dependency=period_item.dependency,
            source_fingerprint=period_item.source_fingerprint,
            evidence=period_item.evidence,
        )


def test_missing_confidence_remains_unavailable() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(
        milestones=[item],
        confidence=None,
        confidence_dq=None,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    view = result.selected_period_items[0].confidence
    assert view.availability == MilestoneConfidenceAvailability.UNAVAILABLE
    assert LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE in view.limitations


def test_duplicate_milestone_evidence_fails_closed() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    dup_ref = _milestone_ref(item.id)
    mutated = pack.model_copy(
        update={"evidence": [*pack.evidence, dup_ref]},
    )
    with pytest.raises(EvidencePackIntegrityError):
        assess_milestone_intelligence(mutated)


def test_status_counts_reconcile_exactly_with_unclassified() -> None:
    items = [
        _milestone(planned_date=date(2026, 6, 16), status="on_track"),
        _milestone(planned_date=date(2026, 6, 17), status="planned"),
        _milestone(planned_date=date(2026, 6, 18), status="at_risk"),
    ]
    pack = _pack(milestones=items, next_milestone_id=items[0].id)
    result = assess_milestone_intelligence(pack)
    counts = result.period_counts
    assert counts.total_count == (
        counts.on_track_count
        + counts.at_risk_count
        + counts.missed_count
        + counts.completed_count
        + counts.pending_count
        + counts.unclassified_count
    )
    assert counts.unclassified_count == 1


def test_selected_item_outside_reporting_period_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["selected_period_items"][0]["planned_date"] = "2026-06-01"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_progress_state_must_equal_status() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["selected_period_items"][0]["progress"]["progress_state"] = "pending"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_at_risk_list_cannot_omit_qualifying_milestone() -> None:
    at_risk = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    missed = _milestone(planned_date=date(2026, 6, 18), status="missed")
    pack = _pack(milestones=[at_risk, missed], next_milestone_id=at_risk.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["at_risk_items"] = bad["at_risk_items"][:1]
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_at_risk_list_cannot_add_non_qualifying_milestone() -> None:
    on_track = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    at_risk = _milestone(planned_date=date(2026, 6, 18), status="at_risk")
    pack = _pack(milestones=[on_track, at_risk], next_milestone_id=on_track.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    fabricated = bad["at_risk_items"][0].copy()
    fabricated["milestone_id"] = str(on_track.id)
    fabricated["status"] = "at_risk"
    fabricated["name"] = on_track.name
    bad["at_risk_items"].append(fabricated)
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_at_risk_cannot_diverge_from_selected_item() -> None:
    at_risk = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    pack = _pack(milestones=[at_risk], next_milestone_id=at_risk.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["at_risk_items"][0]["name"] = "mutated"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_confidence_carries_exact_row_and_milestone_identity() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    view = result.selected_period_items[0].confidence
    assert view.confidence_id == confidence.id
    assert view.milestone_id == item.id
    assert view.evidence[0].source_row_id == confidence.id


def test_confidence_evidence_row_mismatch_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["selected_period_items"][0]["confidence"]["evidence"][0]["source_row_id"] = str(
        uuid4()
    )
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_confidence_from_other_milestone_cannot_be_injected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    other = _milestone(planned_date=date(2026, 6, 18), status="pending")
    confidence = _confidence_for(other.id)
    pack = _pack(
        milestones=[item, other],
        confidence=confidence,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    conf = bad["selected_period_items"][0]["confidence"]
    conf["availability"] = "available"
    conf["confidence_id"] = str(confidence.id)
    conf["milestone_id"] = str(other.id)
    conf["score_pct"] = "88.50"
    conf["confidence_status"] = "on_track"
    conf["forecast_completion_date"] = "2026-07-01"
    conf["data_quality"] = "complete"
    conf["evidence"] = [
        {
            "source_agent": "delivery_performance",
            "source_table": "delivery_confidence_scores",
            "source_row_id": str(confidence.id),
            "visibility": "internal",
            "claim_keys": [
                "score_pct",
                "confidence_status",
                "forecast_completion_date",
            ],
            "period": "current",
            "source_fingerprint": pack.source_fingerprint,
            "observed_at": "2026-06-10T00:00:00+00:00",
        }
    ]
    conf["limitations"] = []
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_delivery_confidence_forecast_separate_from_milestone_dates() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id, forecast=date(2026, 7, 20))
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    published = result.selected_period_items[0]
    assert published.confidence.forecast_completion_date == date(2026, 7, 20)
    assert published.forecast_date is None
    assert published.revised_date is None
    assert published.expected_date is None
    bad = result.model_dump()
    bad["selected_period_items"][0]["forecast_date"] = "2026-07-20"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_multiple_exact_milestone_blockers_preserved() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    early = RiskAlertFacts(
        id=uuid4(),
        alert_type="milestone_at_risk",
        risk_tier="medium",
        title="Earlier",
        status="open",
        milestone_id=item.id,
        detail="internal",
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    late = RiskAlertFacts(
        id=uuid4(),
        alert_type="delivery_risk",
        risk_tier="high",
        title="Later",
        status="acknowledged",
        milestone_id=item.id,
        detail="internal",
        observed_at=datetime(2026, 6, 3, tzinfo=UTC),
    )
    pack = _pack(
        milestones=[item],
        risks=[late, early],
        risk_dq=DataQualityState.COMPLETE,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    blockers = result.selected_period_items[0].blockers
    assert blockers.state == MilestoneBlockerState.PRESENT
    assert [row.risk_id for row in blockers.blockers] == [early.id, late.id]


def test_blocker_evidence_row_must_equal_risk_id() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    risk = RiskAlertFacts(
        id=uuid4(),
        alert_type="milestone_at_risk",
        risk_tier="high",
        title="Delay",
        status="open",
        milestone_id=item.id,
        detail="internal",
        observed_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    pack = _pack(
        milestones=[item],
        risks=[risk],
        risk_dq=DataQualityState.COMPLETE,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["selected_period_items"][0]["blockers"]["blockers"][0]["evidence"][0][
        "source_row_id"
    ] = str(uuid4())
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_blocker_milestone_id_must_equal_parent() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    risk = RiskAlertFacts(
        id=uuid4(),
        alert_type="milestone_at_risk",
        risk_tier="high",
        title="Delay",
        status="open",
        milestone_id=item.id,
        detail="internal",
        observed_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    pack = _pack(
        milestones=[item],
        risks=[risk],
        risk_dq=DataQualityState.COMPLETE,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["selected_period_items"][0]["blockers"]["blockers"][0]["milestone_id"] = str(
        uuid4()
    )
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_duplicate_blockers_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="at_risk")
    risk = RiskAlertFacts(
        id=uuid4(),
        alert_type="milestone_at_risk",
        risk_tier="high",
        title="Delay",
        status="open",
        milestone_id=item.id,
        detail="internal",
        observed_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    pack = _pack(
        milestones=[item],
        risks=[risk],
        risk_dq=DataQualityState.COMPLETE,
        next_milestone_id=item.id,
    )
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    dup = bad["selected_period_items"][0]["blockers"]["blockers"][0]
    bad["selected_period_items"][0]["blockers"]["blockers"].append(dup)
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_next_milestone_matches_source_selected_id() -> None:
    first = _milestone(planned_date=date(2026, 6, 16), status="completed")
    second = _milestone(planned_date=date(2026, 6, 25), status="pending")
    pack = _pack(milestones=[first, second], next_milestone_id=second.id)
    result = assess_milestone_intelligence(pack)
    assert result.source_next_milestone_id == second.id
    assert result.next_key_milestone is not None
    assert result.next_key_milestone.milestone_id == second.id
    bad = result.model_dump()
    bad["next_key_milestone"]["milestone_id"] = str(first.id)
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_next_milestone_cannot_diverge_from_selected_overlap() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["next_key_milestone"]["name"] = "mutated-next"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_next_milestone_foreign_reporting_period_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["next_key_milestone"]["reporting_period"]["as_of"] = "2026-06-01"
    bad["next_key_milestone"]["reporting_period"]["start_date"] = "2026-05-26"
    bad["next_key_milestone"]["reporting_period"]["end_date"] = "2026-06-01"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_duplicate_identical_top_level_evidence_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["evidence"].append(bad["evidence"][0])
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_reordered_non_canonical_evidence_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    assert len(result.evidence) >= 2
    bad = result.model_dump()
    bad["evidence"] = list(reversed(bad["evidence"]))
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_orphan_top_level_claim_rejected() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    bad = result.model_dump()
    bad["evidence"].append(
        {
            "source_agent": "delivery_performance",
            "source_table": "milestones",
            "source_row_id": str(uuid4()),
            "visibility": "internal",
            "claim_keys": [
                "milestone_id",
                "milestone_name",
                "milestone_status",
                "planned_date",
            ],
            "period": "current",
            "source_fingerprint": pack.source_fingerprint,
            "observed_at": None,
        }
    )
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_internal_assessment_rejects_client_safe_evidence() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    pack = _pack(milestones=[item], next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    assert result.visibility_mode == EvidenceVisibility.INTERNAL
    bad = result.model_dump()
    bad["evidence"][0]["visibility"] = "client_safe"
    bad["selected_period_items"][0]["evidence"][0]["visibility"] = "client_safe"
    if bad["next_key_milestone"] is not None:
        bad["next_key_milestone"]["evidence"][0]["visibility"] = "client_safe"
    with pytest.raises(ValidationError):
        MilestoneIntelligenceAssessment.model_validate(bad)


def test_no_milestone_error_uses_policy_terminology() -> None:
    module = __import__(
        "app.agents.client_intelligence.milestone_intelligence",
        fromlist=["milestone_intelligence"],
    )
    source = inspect.getsource(module)
    assert "invalid_policy_decision" not in source


def test_available_confidence_does_not_claim_forecast_unavailable() -> None:
    item = _milestone(planned_date=date(2026, 6, 17), status="on_track")
    confidence = _confidence_for(item.id)
    pack = _pack(milestones=[item], confidence=confidence, next_milestone_id=item.id)
    result = assess_milestone_intelligence(pack)
    view = result.selected_period_items[0].confidence
    assert view.availability == MilestoneConfidenceAvailability.AVAILABLE
    assert view.forecast_completion_date is not None
    assert "MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE" not in view.limitations
    assert "MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE" in result.limitations
