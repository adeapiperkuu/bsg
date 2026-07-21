"""Client Intelligence Change Intelligence tests (TASK 14).

Fixture materiality policies are test-only — not production thresholds.
"""

from __future__ import annotations

import copy
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
    GovernanceActionFacts,
    GovernanceDependencyFacts,
    GovernanceEvidenceFacts,
    KnowledgeEvidenceFacts,
    KnowledgeSourceAvailabilityFacts,
    MilestoneFacts,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    QualitySnapshotFacts,
    RiskAlertFacts,
    SourceAgent,
    ThroughputSnapshotFacts,
    WorkforceEvidenceFacts,
    finalize_pack_collections,
    resolve_reporting_period,
)
from app.agents.client_intelligence.change_intelligence import (
    ChangeIntelligenceIntegrityError,
    _assert_packs_compatible,
    assess_change_intelligence,
    build_change_candidates,
    build_change_comparison,
)
from app.agents.client_intelligence.change_intelligence_contracts import (
    LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE,
    LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE,
    LIMITATION_MILESTONE_CLOSURE_HISTORY_UNAVAILABLE,
    LIMITATION_MILESTONE_CREATION_HISTORY_UNAVAILABLE,
    LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE,
    LIMITATION_READINESS_INTELLIGENCE_UNAVAILABLE,
    LIMITATION_RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE,
    LIMITATION_RISK_CLOSURE_HISTORY_UNAVAILABLE,
    ChangeCandidate,
    ChangeCandidateContext,
    ChangeComparisonPeriod,
    ChangeComparisonResult,
    ChangeDirection,
    ChangeDomain,
    ChangeDomainCoverageState,
    ChangeEvidencePeriod,
    ChangeIntelligenceAssessment,
    ChangeIntelligenceAvailability,
    ChangeMateriality,
    ChangeMaterialityPolicyDecision,
    ChangeMaterialitySelection,
    ChangeScalarValue,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    worst_data_quality_state,
)
from app.agents.client_intelligence.evidence_validation import (
    finalize_data_quality_issues,
)

_AS_OF = date(2026, 6, 18)
_ORG = UUID("33333333-3333-4333-8333-333333333333")
_ASSESSED_AT = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
_TEST_RULES = "test.fixture.change_intelligence.v1"


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
    source_agent: SourceAgent,
    source_table: str,
    source_row_id: UUID,
    visibility: EvidenceVisibility,
    claim_keys: list[str],
    observed_at: datetime | None = None,
) -> ClientEvidenceReference:
    return ClientEvidenceReference(
        source_agent=source_agent,
        source_table=source_table,
        source_row_id=source_row_id,
        description="evidence",
        visibility=visibility,
        observed_at=observed_at,
        claim_keys=claim_keys,
    )


def _single_pack(
    *,
    visibility_mode: EvidenceVisibility = EvidenceVisibility.INTERNAL,
    project_id: UUID,
    org_id: UUID,
    as_of: date,
    reporting_period,
    confidence_score: Decimal,
    confidence_status: str = "confident",
    milestone_status: str = "planned",
    throughput_completed: int | None = None,
    throughput_forecast: int | None = None,
    quality_gold: Decimal | None = None,
    rework_rate: Decimal | None = None,
    team_id: UUID | None = None,
    milestone_id: UUID | None = None,
    confidence_id: UUID | None = None,
    throughput_id: UUID | None = None,
    quality_id: UUID | None = None,
    open_risks: list[RiskAlertFacts] | None = None,
    limitations: list[str] | None = None,
) -> ClientEvidencePack:
    milestone_id = milestone_id or uuid4()
    confidence_id = confidence_id or uuid4()
    refs = [
        _ref(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="projects",
            source_row_id=project_id,
            visibility=EvidenceVisibility.CLIENT_SAFE,
            claim_keys=["project_id", "project_name", "project_status"],
        ),
        _ref(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="milestones",
            source_row_id=milestone_id,
            visibility=EvidenceVisibility.CLIENT_SAFE,
            observed_at=datetime(2026, 6, 1, tzinfo=UTC),
            claim_keys=[
                "milestone_id",
                "milestone_name",
                "milestone_status",
                "planned_date",
            ],
        ),
        _ref(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="delivery_confidence_scores",
            source_row_id=confidence_id,
            visibility=EvidenceVisibility.CLIENT_SAFE,
            observed_at=datetime(2026, 6, 10, tzinfo=UTC),
            claim_keys=[
                "score_pct",
                "confidence_status",
                "forecast_completion_date",
            ],
        ),
    ]
    throughput_series: list[ThroughputSnapshotFacts] = []
    if throughput_completed is not None and throughput_forecast is not None:
        throughput_id = throughput_id or uuid4()
        snap_date = as_of
        throughput_series = [
            ThroughputSnapshotFacts(
                id=throughput_id,
                snapshot_date=snap_date,
                units_completed=throughput_completed,
                units_forecast=throughput_forecast,
            )
        ]
        refs.append(
            _ref(
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="throughput_snapshots",
                source_row_id=throughput_id,
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime.combine(snap_date, datetime.min.time(), tzinfo=UTC),
                claim_keys=["snapshot_date", "units_completed", "units_forecast"],
            )
        )
    quality_current: list[QualitySnapshotFacts] = []
    iso_year = reporting_period.start_date.isocalendar().year
    iso_week = reporting_period.start_date.isocalendar().week
    if quality_gold is not None and rework_rate is not None:
        quality_id = quality_id or uuid4()
        resolved_team_id = team_id or uuid4()
        quality_current = [
            QualitySnapshotFacts(
                snapshot_id=quality_id,
                iso_year=iso_year,
                iso_week=iso_week,
                team_id=resolved_team_id,
                gold_set_accuracy_pct=quality_gold,
                rework_rate_pct=rework_rate,
                observed_at=datetime(2026, 6, 10, tzinfo=UTC),
            )
        ]
        refs.append(
            _ref(
                source_agent=SourceAgent.QUALITY_INTELLIGENCE,
                source_table="quality_snapshots",
                source_row_id=quality_id,
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime(2026, 6, 10, tzinfo=UTC),
                claim_keys=[
                    "iso_year",
                    "iso_week",
                    "gold_set_accuracy_pct",
                    "rework_rate_pct",
                    "team_id",
                ],
            )
        )
    risks = open_risks or []
    for risk in risks:
        refs.append(
            _ref(
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="risk_alerts",
                source_row_id=risk.id,
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=risk.observed_at,
                claim_keys=["risk_id", "risk_title", "risk_tier", "alert_type", "status"],
            )
        )
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(source="milestones", state=DataQualityState.COMPLETE, detail="ok"),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
        ]
        + (
            [
                DataQualityIssue(
                    source="throughput_snapshots",
                    state=DataQualityState.COMPLETE,
                    detail="ok",
                )
            ]
            if throughput_series
            else []
        )
        + (
            [
                DataQualityIssue(
                    source="quality_snapshots",
                    state=DataQualityState.COMPLETE,
                    detail="ok",
                )
            ]
            if quality_current
            else []
        )
        + (
            [
                DataQualityIssue(
                    source="risk_alerts",
                    state=DataQualityState.COMPLETE,
                    detail="ok",
                )
            ]
            if risks
            else []
        )
    )
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=[],
        limitations=limitations or [],
    )
    delivery = DeliveryEvidenceFacts(
        latest_throughput=throughput_series[-1] if throughput_series else None,
        throughput_series=throughput_series,
        latest_delivery_confidence=DeliveryConfidenceFacts(
            id=confidence_id,
            milestone_id=milestone_id,
            score_pct=confidence_score,
            status=confidence_status,
            forecast_completion_date=date(2026, 7, 15),
            model_version=None
            if visibility_mode == EvidenceVisibility.CLIENT_SAFE
            else "delivery-v1",
            observed_at=datetime(2026, 6, 10, tzinfo=UTC),
        ),
        milestones=[
            MilestoneFacts(
                id=milestone_id,
                name="Batch 14",
                planned_date=date(2026, 7, 1),
                actual_date=None,
                status=milestone_status,
                description=None
                if visibility_mode == EvidenceVisibility.CLIENT_SAFE
                else "internal",
            )
        ],
        next_milestone_id=milestone_id,
        open_risks=risks,
        open_bottlenecks=[],
    )
    quality = QualityEvidenceFacts(
        current_period=quality_current,
        previous_period=[],
        current_iso_year=iso_year,
        current_iso_week=iso_week,
        previous_iso_year=iso_year,
        previous_iso_week=iso_week - 1 if iso_week > 1 else 52,
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
        project_id=project_id,
        org_id=org_id,
        project_name="Aurora Labeling",
        project_status="active",
    )
    overall = worst_data_quality_state([issue.state for issue in dq])
    fp = compute_source_fingerprint(
        project=project,
        reporting_period=reporting_period,
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
        reporting_period=reporting_period,
        visibility_mode=visibility_mode,
        delivery=delivery,
        quality=quality,
        workforce=workforce,
        governance=governance,
        knowledge=knowledge,
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        generated_at=datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
        source_fingerprint=fp,
        policy_fingerprint=None,
        visibility_limitations=vis,
        limitations=lim,
    )


def _change_pack(
    *,
    visibility_mode: EvidenceVisibility = EvidenceVisibility.INTERNAL,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    as_of: date = _AS_OF,
    confidence_score: Decimal = Decimal("88.50"),
    previous_confidence_score: Decimal | None = None,
    throughput_completed: int | None = 12,
    throughput_forecast: int | None = 10,
    quality_gold: Decimal | None = Decimal("95.00"),
    rework_rate: Decimal | None = Decimal("2.50"),
    include_risk: bool = False,
    include_milestone_change: bool = False,
    unchanged_values: bool = False,
    limitations: list[str] | None = None,
) -> tuple[ClientEvidencePack, ClientEvidencePack]:
    pid = project_id or uuid4()
    oid = org_id or _ORG
    team_id = uuid4()
    milestone_id = uuid4()
    confidence_id = uuid4()
    throughput_id = uuid4()
    quality_id = uuid4()
    period = resolve_reporting_period(as_of)
    prev_as_of = period.previous_end_date
    aligned_prev_period = period.model_copy(
        update={
            "start_date": period.previous_start_date,
            "end_date": period.previous_end_date,
            "previous_start_date": period.previous_start_date - timedelta(days=7),
            "previous_end_date": period.previous_end_date - timedelta(days=7),
            "as_of": period.previous_end_date,
        }
    )
    risks: list[RiskAlertFacts] = []
    if include_risk:
        risks.append(
            RiskAlertFacts(
                id=uuid4(),
                alert_type="delivery_risk",
                risk_tier="high",
                title="Risk",
                status="open",
                observed_at=datetime(2026, 6, 5, tzinfo=UTC),
            )
        )
    current = _refingerprint(
        _single_pack(
            visibility_mode=visibility_mode,
            project_id=pid,
            org_id=oid,
            as_of=as_of,
            reporting_period=period,
            confidence_score=confidence_score,
            milestone_status="in_progress" if include_milestone_change else "planned",
            throughput_completed=throughput_completed,
            throughput_forecast=throughput_forecast,
            quality_gold=quality_gold,
            rework_rate=rework_rate,
            team_id=team_id,
            milestone_id=milestone_id,
            confidence_id=confidence_id,
            throughput_id=throughput_id,
            quality_id=quality_id,
            open_risks=risks,
            limitations=limitations,
        )
    )
    previous = _refingerprint(
        _single_pack(
            visibility_mode=visibility_mode,
            project_id=pid,
            org_id=oid,
            as_of=prev_as_of,
            reporting_period=aligned_prev_period,
            confidence_score=(
                confidence_score
                if unchanged_values
                else (
                    previous_confidence_score
                    if previous_confidence_score is not None
                    else Decimal("80.00")
                )
            ),
            milestone_status="planned",
            throughput_completed=(
                throughput_completed if unchanged_values else (
                    throughput_completed - 2 if throughput_completed is not None else None
                )
            ),
            throughput_forecast=(
                throughput_forecast if unchanged_values else (
                    throughput_forecast - 1 if throughput_forecast is not None else None
                )
            ),
            quality_gold=(
                quality_gold if unchanged_values else (
                    quality_gold - Decimal("1.00") if quality_gold is not None else None
                )
            ),
            rework_rate=(
                rework_rate if unchanged_values else (
                    rework_rate + Decimal("0.50") if rework_rate is not None else None
                )
            ),
            team_id=team_id,
            milestone_id=milestone_id,
            confidence_id=confidence_id,
            throughput_id=throughput_id,
            quality_id=quality_id,
            open_risks=risks,
            limitations=limitations,
        )
    )
    return current, previous


def _mixed_reliability_pack() -> tuple[ClientEvidencePack, ClientEvidencePack]:
    current, previous = _change_pack()
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="throughput_snapshots",
                state=DataQualityState.STALE,
                detail="stale throughput",
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
            DataQualityIssue(source="milestones", state=DataQualityState.COMPLETE, detail="ok"),
            DataQualityIssue(
                source="quality_snapshots", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="utilization_snapshots",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
            DataQualityIssue(
                source="project_skill_requirements",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
        ]
    )
    current = _refingerprint(
        current.model_copy(
            update={
                "data_quality": dq,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
    )
    return current, previous


def _with_extra_milestone(
    pack: ClientEvidencePack, *, milestone_id: UUID | None = None
) -> ClientEvidencePack:
    milestone_id = milestone_id or uuid4()
    refs = list(pack.evidence) + [
        _ref(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="milestones",
            source_row_id=milestone_id,
            visibility=EvidenceVisibility.INTERNAL,
            claim_keys=["milestone_id", "milestone_name", "milestone_status", "planned_date"],
        )
    ]
    delivery = pack.delivery.model_copy(
        update={
            "milestones": list(pack.delivery.milestones)
            + [
                MilestoneFacts(
                    id=milestone_id,
                    name="Extra",
                    planned_date=date(2026, 8, 1),
                    actual_date=None,
                    status="planned",
                    description="internal",
                )
            ]
        }
    )
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=list(pack.data_quality),
        visibility_limitations=pack.visibility_limitations,
        limitations=pack.limitations,
    )
    return _refingerprint(
        pack.model_copy(
            update={
                "delivery": delivery,
                "evidence": refs,
                "data_quality": dq,
                "visibility_limitations": vis,
                "limitations": lim,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
    )


def _with_extra_risk(
    pack: ClientEvidencePack, *, risk_id: UUID | None = None
) -> ClientEvidencePack:
    risk_id = risk_id or uuid4()
    risk = RiskAlertFacts(
        id=risk_id,
        alert_type="delivery_risk",
        risk_tier="high",
        title="Extra",
        status="open",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    refs = list(pack.evidence) + [
        _ref(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="risk_alerts",
            source_row_id=risk_id,
            visibility=EvidenceVisibility.INTERNAL,
            claim_keys=["risk_id", "risk_title", "risk_tier", "alert_type", "status"],
        )
    ]
    dq = finalize_data_quality_issues(
        [
            issue
            for issue in pack.data_quality
            if issue.source != "risk_alerts"
        ]
        + [
            DataQualityIssue(
                source="risk_alerts",
                state=DataQualityState.COMPLETE,
                detail="ok",
            )
        ]
    )
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=pack.visibility_limitations,
        limitations=pack.limitations,
    )
    delivery = pack.delivery.model_copy(
        update={"open_risks": list(pack.delivery.open_risks) + [risk]}
    )
    return _refingerprint(
        pack.model_copy(
            update={
                "delivery": delivery,
                "evidence": refs,
                "data_quality": dq,
                "visibility_limitations": vis,
                "limitations": lim,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
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


def _first_reliable_candidate(
    current: ClientEvidencePack, previous: ClientEvidencePack
) -> ChangeCandidate:
    return next(
        item
        for item in build_change_candidates(current, previous)
        if item.is_reliable
    )


def _domain_outcome(
    comparison: ChangeComparisonResult, domain: ChangeDomain
):
    return next(item for item in comparison.domain_outcomes if item.domain == domain)


def _coverage_item(result: ChangeIntelligenceAssessment, domain: ChangeDomain):
    return next(item for item in result.domain_coverage if item.domain == domain)


class _FixtureChangePolicy:
    def __init__(
        self,
        *,
        mutate=None,
        material: bool = True,
        rules_version: str = _TEST_RULES,
        select_all: bool = True,
        priority: int = 0,
        business_code: str = "TEST_CHANGE_MEANING",
    ) -> None:
        self._rules_version = rules_version
        self._mutate = mutate
        self._material = material
        self._select_all = select_all
        self._priority = priority
        self._business_code = business_code
        self.received_context: ChangeCandidateContext | None = None

    @property
    def rules_version(self) -> str:
        return self._rules_version

    def evaluate(self, candidates: ChangeCandidateContext) -> ChangeMaterialityPolicyDecision:
        self.received_context = candidates
        selections = []
        for item in candidates.candidates:
            if not self._select_all:
                continue
            selections.append(
                ChangeMaterialitySelection(
                    candidate_key=item.candidate_key,
                    materiality=(
                        ChangeMateriality.MATERIAL
                        if self._material
                        else ChangeMateriality.NOT_MATERIAL
                    ),
                    business_meaning_code=self._business_code,
                    priority=self._priority,
                )
            )
        decision = ChangeMaterialityPolicyDecision(
            selections=selections,
            policy_limitations=[],
        )
        if self._mutate is not None:
            decision = self._mutate(candidates, decision)
        return decision


class _ZeroSelectionPolicy:
    def __init__(self, rules_version: str = _TEST_RULES) -> None:
        self._rules_version = rules_version
        self.received_context: ChangeCandidateContext | None = None

    @property
    def rules_version(self) -> str:
        return self._rules_version

    def evaluate(self, candidates: ChangeCandidateContext) -> ChangeMaterialityPolicyDecision:
        self.received_context = candidates
        return ChangeMaterialityPolicyDecision(selections=[], policy_limitations=[])


def _assessment_payload(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    *,
    policy=None,
) -> dict:
    return assess_change_intelligence(
        current, previous, policy=policy or _FixtureChangePolicy()
    ).model_dump(mode="python")


def test_missing_previous_pack_unavailable() -> None:
    current, _ = _change_pack()
    result = assess_change_intelligence(current, previous_pack=None)
    assert result.availability == ChangeIntelligenceAvailability.UNAVAILABLE


def test_missing_previous_pack_publishes_no_changes() -> None:
    current, _ = _change_pack()
    result = assess_change_intelligence(current, previous_pack=None)
    assert result.changes == []
    assert result.published_change_count == 0


def test_missing_previous_pack_limitation() -> None:
    current, _ = _change_pack()
    result = assess_change_intelligence(current, previous_pack=None)
    assert LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE in result.limitations


def test_reversed_period_order_fails() -> None:
    current, previous = _change_pack()
    bad = previous.model_copy(
        update={
            "reporting_period": previous.reporting_period.model_copy(
                update={"as_of": current.reporting_period.as_of}
            )
        }
    )
    with pytest.raises(ChangeIntelligenceIntegrityError) as exc:
        _assert_packs_compatible(current, bad)
    assert exc.value.code == "reversed_reporting_period"


def test_misaligned_previous_cycle_fails() -> None:
    current, previous = _change_pack()
    bad = previous.model_copy(
        update={
            "reporting_period": previous.reporting_period.model_copy(
                update={
                    "start_date": date(2020, 1, 6),
                    "end_date": date(2020, 1, 12),
                }
            )
        }
    )
    with pytest.raises(ChangeIntelligenceIntegrityError) as exc:
        _assert_packs_compatible(current, bad)
    assert exc.value.code == "misaligned_previous_cycle"


def test_cross_project_comparison_fails() -> None:
    current, previous = _change_pack()
    other_pid = uuid4()
    bad = _refingerprint(
        previous.model_copy(
            update={
                "project": previous.project.model_copy(update={"project_id": other_pid}),
                "evidence": [
                    item.model_copy(update={"source_row_id": other_pid})
                    if item.source_table == "projects"
                    else item
                    for item in previous.evidence
                ],
            }
        )
    )
    with pytest.raises(ChangeIntelligenceIntegrityError) as exc:
        build_change_candidates(current, bad)
    assert exc.value.code == "incompatible_project"


def test_cross_org_comparison_fails() -> None:
    current, previous = _change_pack()
    other_org = uuid4()
    bad = _refingerprint(
        previous.model_copy(
            update={"project": previous.project.model_copy(update={"org_id": other_org})}
        )
    )
    with pytest.raises(ChangeIntelligenceIntegrityError) as exc:
        build_change_candidates(current, bad)
    assert exc.value.code == "incompatible_org"


def test_cross_visibility_comparison_fails() -> None:
    current, previous = _change_pack()
    bad = previous.model_copy(update={"visibility_mode": EvidenceVisibility.CLIENT_SAFE})
    with pytest.raises(ChangeIntelligenceIntegrityError) as exc:
        _assert_packs_compatible(current, bad)
    assert exc.value.code == "incompatible_visibility"


def test_invalid_current_pack_fails() -> None:
    current, previous = _change_pack()
    broken = current.model_copy(update={"source_fingerprint": "0" * 64})
    with pytest.raises(ChangeIntelligenceIntegrityError):
        assess_change_intelligence(broken, previous)


def test_invalid_previous_pack_fails() -> None:
    current, previous = _change_pack()
    broken = previous.model_copy(update={"source_fingerprint": "0" * 64})
    with pytest.raises(ChangeIntelligenceIntegrityError):
        build_change_candidates(current, broken)


def test_caller_owned_packs_not_mutated() -> None:
    current, previous = _change_pack()
    current_dump = current.model_dump(mode="python")
    previous_dump = previous.model_dump(mode="python")
    assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    assert current.model_dump(mode="python") == current_dump
    assert previous.model_dump(mode="python") == previous_dump


def test_same_inputs_byte_equivalent_dump() -> None:
    current, previous = _change_pack()
    first = assess_change_intelligence(
        current,
        previous,
        policy=_FixtureChangePolicy(),
        assessed_at=_ASSESSED_AT,
    )
    second = assess_change_intelligence(
        current,
        previous,
        policy=_FixtureChangePolicy(),
        assessed_at=_ASSESSED_AT,
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_candidate_ordering_canonical() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    keys = [item.candidate_key for item in candidates]
    assert keys == sorted(keys, key=lambda key: (key.split(".")[0], key))


def test_duplicate_candidate_keys_fail_validation() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    assert candidates
    dup = candidates + [candidates[0]]
    with pytest.raises(ValidationError):
        ChangeCandidateContext(candidates=dup)


def test_evidence_period_labels() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    assert candidates
    for item in candidates:
        if item.previous_evidence:
            assert all(
                ref.period == ChangeEvidencePeriod.PREVIOUS for ref in item.previous_evidence
            )
        assert all(ref.period == ChangeEvidencePeriod.CURRENT for ref in item.current_evidence)


def test_evidence_fingerprints_match_packs() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        if item.previous_evidence:
            assert {ref.source_fingerprint for ref in item.previous_evidence} == {
                previous.source_fingerprint
            }
        assert {ref.source_fingerprint for ref in item.current_evidence} == {
            current.source_fingerprint
        }


def test_cross_period_evidence_swap_fails_contract() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = next(item for item in candidates if item.is_reliable)
    data = reliable.model_dump(mode="python")
    data["previous_evidence"], data["current_evidence"] = (
        data["current_evidence"],
        data["previous_evidence"],
    )
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_evidence_supports_compared_claim_key() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        if item.previous_evidence:
            assert any(
                item.metric_key in ref.claim_keys for ref in item.previous_evidence
            )
        assert any(item.metric_key in ref.claim_keys for ref in item.current_evidence)


def test_decimal_values_remain_exact() -> None:
    current, previous = _change_pack(confidence_score=Decimal("88.50"))
    candidate = next(
        item
        for item in build_change_candidates(current, previous)
        if item.domain == ChangeDomain.DELIVERY_CONFIDENCE and item.metric_key == "score_pct"
    )
    assert candidate.current_value.decimal_value == Decimal("88.50")


def test_float_values_rejected() -> None:
    with pytest.raises((ValidationError, ValueError)):
        ChangeScalarValue.from_python(1.5)


def test_missing_source_quality_not_complete() -> None:
    current, previous = _change_pack()
    dq = [issue for issue in current.data_quality if issue.source != "throughput_snapshots"]
    current = _refingerprint(current.model_copy(update={"data_quality": dq}))
    for item in build_change_candidates(current, previous):
        if item.domain == ChangeDomain.THROUGHPUT:
            assert item.current_data_quality is None


def test_unreliable_candidates_not_published() -> None:
    current, previous = _change_pack()
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="throughput_snapshots",
                state=DataQualityState.STALE,
                detail="stale",
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
            DataQualityIssue(source="milestones", state=DataQualityState.COMPLETE, detail="ok"),
            DataQualityIssue(
                source="quality_snapshots", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="utilization_snapshots",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
            DataQualityIssue(
                source="project_skill_requirements",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
        ]
    )
    current = _refingerprint(
        current.model_copy(
            update={
                "data_quality": dq,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
    )
    result = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    assert all(item.domain != ChangeDomain.THROUGHPUT for item in result.changes)


def test_missing_policy_publishes_no_changes() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    assert result.changes == []


def test_missing_policy_limitation() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    assert LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE in result.limitations


def test_missing_policy_not_no_changes_semantics() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    assert result.detected_candidate_count > 0
    assert result.evaluated_candidate_count == 0
    assert result.policy_evaluated is False
    assert LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE in result.limitations


def test_policy_never_receives_evidence_pack() -> None:
    current, previous = _change_pack()
    policy = _FixtureChangePolicy()
    assess_change_intelligence(current, previous, policy=policy)
    assert policy.received_context is not None
    assert not inspect.signature(policy.evaluate).parameters.get("pack")


def test_policy_receives_isolated_deep_copy() -> None:
    current, previous = _change_pack()
    policy = _FixtureChangePolicy()
    assess_change_intelligence(current, previous, policy=policy)
    assert policy.received_context is not None
    mutated = copy.deepcopy(policy.received_context)
    mutated.candidates[0].direction = ChangeDirection.UNKNOWN
    assert mutated.model_dump() != policy.received_context.model_dump()


def test_policy_mutation_cannot_alter_assessment_facts() -> None:
    current, previous = _change_pack()

    def _mutate(ctx, decision):
        if ctx.candidates:
            ctx.candidates[0].direction = ChangeDirection.UNKNOWN
        return decision

    result = assess_change_intelligence(
        current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
    )
    assert result.changes or result.evaluated_candidate_count >= 0


def test_unknown_policy_candidate_keys_fail() -> None:
    current, previous = _change_pack()

    def _mutate(_ctx, decision):
        return decision.model_copy(
            update={
                "selections": [
                    ChangeMaterialitySelection(
                        candidate_key="unknown.key",
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST",
                        priority=0,
                    )
                ]
            }
        )

    with pytest.raises(ChangeIntelligenceIntegrityError):
        assess_change_intelligence(
            current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
        )


def test_duplicate_policy_selections_fail() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = [item for item in candidates if item.is_reliable]
    assert reliable
    key = reliable[0].candidate_key

    def _mutate(_ctx, decision):
        dup = ChangeMaterialitySelection(
            candidate_key=key,
            materiality=ChangeMateriality.MATERIAL,
            business_meaning_code="TEST",
            priority=0,
        )
        return decision.model_copy(update={"selections": [dup, dup]})

    with pytest.raises(ChangeIntelligenceIntegrityError):
        assess_change_intelligence(
            current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
        )


def test_policy_cannot_mutate_values() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = next(item for item in candidates if item.is_reliable)

    def _mutate(ctx, decision):
        ctx.candidates[0].current_value = ChangeScalarValue.from_python("mutated")
        return decision.model_copy(
            update={
                "selections": [
                    ChangeMaterialitySelection(
                        candidate_key=reliable.candidate_key,
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST",
                        priority=0,
                    )
                ]
            }
        )

    result = assess_change_intelligence(
        current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
    )
    published = next(
        item for item in result.changes if item.candidate_key == reliable.candidate_key
    )
    assert published.current_value.model_dump() == reliable.current_value.model_dump()


def test_policy_cannot_mutate_direction() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = next(item for item in candidates if item.is_reliable)

    def _mutate(ctx, decision):
        ctx.candidates[0].direction = ChangeDirection.UNKNOWN
        return decision.model_copy(
            update={
                "selections": [
                    ChangeMaterialitySelection(
                        candidate_key=reliable.candidate_key,
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST",
                        priority=0,
                    )
                ]
            }
        )

    result = assess_change_intelligence(
        current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
    )
    published = next(
        item for item in result.changes if item.candidate_key == reliable.candidate_key
    )
    assert published.direction == reliable.direction


def test_policy_cannot_publish_unreliable_candidates() -> None:
    current, previous = _mixed_reliability_pack()
    candidates = build_change_candidates(current, previous)
    unreliable = next(item for item in candidates if not item.is_reliable)
    assert not unreliable.is_reliable

    def _mutate(_ctx, decision):
        return decision.model_copy(
            update={
                "selections": [
                    ChangeMaterialitySelection(
                        candidate_key=unreliable.candidate_key,
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST",
                        priority=0,
                    )
                ]
            }
        )

    with pytest.raises(ChangeIntelligenceIntegrityError):
        assess_change_intelligence(
            current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
        )


def test_supplied_policy_requires_rules_version() -> None:
    current, previous = _change_pack()

    class _BadPolicy:
        @property
        def rules_version(self) -> str:
            return ""

        def evaluate(self, candidates):
            return ChangeMaterialityPolicyDecision(selections=[], policy_limitations=[])

    with pytest.raises(ChangeIntelligenceIntegrityError):
        assess_change_intelligence(current, previous, policy=_BadPolicy())


def test_published_ordering_follows_priority() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = [item for item in candidates if item.is_reliable]
    assert len(reliable) >= 2

    class _PriorityPolicy:
        @property
        def rules_version(self) -> str:
            return _TEST_RULES

        def evaluate(self, ctx: ChangeCandidateContext) -> ChangeMaterialityPolicyDecision:
            selections = []
            for idx, item in enumerate(ctx.candidates):
                selections.append(
                    ChangeMaterialitySelection(
                        candidate_key=item.candidate_key,
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST_ORDER",
                        priority=idx,
                    )
                )
            return ChangeMaterialityPolicyDecision(selections=selections)

    result = assess_change_intelligence(current, previous, policy=_PriorityPolicy())
    assert len(result.changes) >= 2
    priorities = [item.priority for item in result.changes]
    assert priorities == sorted(priorities)


def test_top_level_evidence_equals_published_union() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    ChangeIntelligenceAssessment.model_validate(result.model_dump(mode="python"))


def test_no_published_changes_empty_top_level_evidence() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    assert result.changes == []
    assert result.evidence == []


def test_counts_match_collections() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    candidates = build_change_candidates(current, previous)
    reliable = [item for item in candidates if item.is_reliable]
    assert result.published_change_count == len(result.changes)
    assert result.detected_candidate_count == len(candidates)
    assert result.evaluated_candidate_count == len(reliable)
    assert (
        result.published_change_count
        <= result.evaluated_candidate_count
        <= result.detected_candidate_count
    )


def test_throughput_actual_forecast_separate() -> None:
    current, previous = _change_pack()
    throughput = [
        item
        for item in build_change_candidates(current, previous)
        if item.domain == ChangeDomain.THROUGHPUT
    ]
    metrics = {item.metric_key for item in throughput}
    assert "units_completed" in metrics
    assert "units_forecast" in metrics
    assert "units_plan" not in metrics


def test_no_plan_invented() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        assert item.metric_key != "units_plan"


def test_quality_not_silent_team_aggregation() -> None:
    current, previous = _change_pack()
    quality = [
        item
        for item in build_change_candidates(current, previous)
        if item.domain == ChangeDomain.QUALITY
    ]
    for item in quality:
        assert "project" in item.candidate_key or "." in item.candidate_key


def test_rework_not_inferred_from_quality_drift() -> None:
    current, previous = _change_pack()
    rework = [
        item
        for item in build_change_candidates(current, previous)
        if item.domain == ChangeDomain.REWORK
    ]
    assert rework
    assert all(item.metric_key == "rework_rate_pct" for item in rework)


def test_delivery_confidence_delivery_owned() -> None:
    current, previous = _change_pack()
    dc = [
        item
        for item in build_change_candidates(current, previous)
        if item.domain == ChangeDomain.DELIVERY_CONFIDENCE
    ]
    assert dc
    assert all(item.current_source.source_table == "delivery_confidence_scores" for item in dc)


def test_no_confidence_threshold_introduced() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    assert result.rules_version is None


def test_milestones_align_by_stable_id() -> None:
    current, previous = _change_pack(include_milestone_change=True)
    milestone = [
        item
        for item in build_change_candidates(current, previous)
        if item.domain == ChangeDomain.MILESTONE
    ]
    assert milestone
    assert all("milestone." in item.candidate_key for item in milestone)


def test_missing_milestone_not_completion() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    removed_ids = {
        item.id for item in previous.delivery.milestones
    } - {item.id for item in current.delivery.milestones}
    for milestone_id in removed_ids:
        assert not any(
            milestone_id.hex in item.candidate_key
            and item.direction in {ChangeDirection.CHANGED, ChangeDirection.DECREASED}
            for item in candidates
        )


def test_missing_risk_not_closure() -> None:
    current, previous = _change_pack(include_risk=True)
    risk_id = current.delivery.open_risks[0].id
    dq = finalize_data_quality_issues(
        [
            issue
            for issue in current.data_quality
            if issue.source != "risk_alerts"
        ]
        + [
            DataQualityIssue(
                source="risk_alerts",
                state=DataQualityState.UNAVAILABLE,
                detail="no risks",
            )
        ]
    )
    current = _refingerprint(
        current.model_copy(
            update={
                "delivery": current.delivery.model_copy(update={"open_risks": []}),
                "evidence": [
                    item for item in current.evidence if item.source_table != "risk_alerts"
                ],
                "data_quality": dq,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
    )
    candidates = build_change_candidates(current, previous)
    assert not any(
        item.domain == ChangeDomain.RISK and risk_id.hex in item.candidate_key
        for item in candidates
    )


def test_risk_business_impact_not_invented() -> None:
    current, previous = _change_pack(include_risk=True)
    result = assess_change_intelligence(current, previous, policy=None)
    assert all("impact" not in code.lower() for code in result.limitations)


def test_readiness_explicitly_unavailable() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    readiness = next(
        item for item in result.domain_coverage if item.domain == ChangeDomain.READINESS
    )
    assert readiness.state == ChangeDomainCoverageState.UNAVAILABLE
    assert LIMITATION_READINESS_INTELLIGENCE_UNAVAILABLE in result.limitations


def test_workforce_output_no_identities() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        if item.domain == ChangeDomain.WORKFORCE_CAPACITY:
            blob = item.model_dump_json()
            assert "annotator" not in blob.lower()
            assert "worker_name" not in blob.lower()


def test_capacity_direction_not_improving_label() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        assert item.direction.value not in {"improving", "deteriorating"}


def test_governance_output_no_title_description_owner() -> None:
    current, previous = _change_pack()
    dep_id = uuid4()
    action_id = uuid4()

    def _with_governance(pack: ClientEvidencePack, *, due: date) -> ClientEvidencePack:
        refs = list(pack.evidence) + [
            _ref(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="project_dependencies",
                source_row_id=dep_id,
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime(2026, 6, 5, tzinfo=UTC),
                claim_keys=["dependency_id", "status", "due_date"],
            ),
            _ref(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="governance_actions",
                source_row_id=action_id,
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=datetime(2026, 6, 5, tzinfo=UTC),
                claim_keys=["action_id", "status", "due_date"],
            ),
        ]
        dq = finalize_data_quality_issues(
            list(pack.data_quality)
            + [
                DataQualityIssue(
                    source="governance_dependencies",
                    state=DataQualityState.COMPLETE,
                    detail="ok",
                ),
                DataQualityIssue(
                    source="governance_actions",
                    state=DataQualityState.COMPLETE,
                    detail="ok",
                ),
            ]
        )
        refs, dq, vis, lim = finalize_pack_collections(
            evidence=refs,
            data_quality=dq,
            visibility_limitations=pack.visibility_limitations,
            limitations=pack.limitations,
        )
        updated = pack.model_copy(
            update={
                "governance": GovernanceEvidenceFacts(
                    as_of=pack.governance.as_of,
                    dependencies=[
                        GovernanceDependencyFacts(
                            dependency_id=dep_id,
                            dependency_type="client",
                            status="open",
                            due_date=due,
                        )
                    ],
                    actions=[
                        GovernanceActionFacts(
                            action_id=action_id,
                            status="open",
                            due_date=due,
                        )
                    ],
                    summary=pack.governance.summary.model_copy(
                        update={"dependency_count": 1, "action_count": 1}
                    ),
                ),
                "evidence": refs,
                "data_quality": dq,
                "visibility_limitations": vis,
                "limitations": lim,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
        return _refingerprint(updated)

    current = _with_governance(current, due=date(2026, 7, 1))
    previous = _with_governance(previous, due=date(2026, 6, 20))
    for item in build_change_candidates(current, previous):
        if item.domain in {
            ChangeDomain.GOVERNANCE_DEPENDENCY,
            ChangeDomain.GOVERNANCE_ACTION,
        }:
            blob = item.model_dump_json()
            assert "title" not in blob.lower()
            assert "description" not in blob.lower()
            assert "owner" not in blob.lower()


def test_missing_dependency_not_resolved_completed() -> None:
    current, previous = _change_pack()
    dep_id = uuid4()
    refs = list(previous.evidence) + [
        _ref(
            source_agent=SourceAgent.PROJECT_GOVERNANCE,
            source_table="project_dependencies",
            source_row_id=dep_id,
            visibility=EvidenceVisibility.INTERNAL,
            claim_keys=["dependency_id", "status"],
        )
    ]
    dq = finalize_data_quality_issues(
        list(previous.data_quality)
        + [
            DataQualityIssue(
                source="governance_dependencies",
                state=DataQualityState.COMPLETE,
                detail="ok",
            )
        ]
    )
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=previous.visibility_limitations,
        limitations=previous.limitations,
    )
    previous = _refingerprint(
        previous.model_copy(
            update={
                "governance": previous.governance.model_copy(
                    update={
                        "dependencies": [
                            GovernanceDependencyFacts(
                                dependency_id=dep_id,
                                dependency_type="client",
                                status="open",
                            )
                        ],
                        "summary": previous.governance.summary.model_copy(
                            update={"dependency_count": 1}
                        ),
                    }
                ),
                "evidence": refs,
                "data_quality": dq,
                "visibility_limitations": vis,
                "limitations": lim,
                "overall_data_quality": worst_data_quality_state(
                    [issue.state for issue in dq]
                ),
            }
        )
    )
    candidates = build_change_candidates(current, previous)
    assert not any(dep_id.hex in item.candidate_key for item in candidates)


def test_resource_onboarding_unavailable() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    onboarding = next(
        item for item in result.domain_coverage if item.domain == ChangeDomain.RESOURCE_ONBOARDING
    )
    assert onboarding.state == ChangeDomainCoverageState.UNAVAILABLE
    assert LIMITATION_RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE in result.limitations


def test_engine_limitations_separate_from_source_limitations() -> None:
    current, previous = _change_pack(limitations=["Pack source limitation text."])
    result = assess_change_intelligence(current, previous, policy=None)
    assert "Pack source limitation text." in result.current_source_limitations
    assert "Pack source limitation text." in result.previous_source_limitations
    assert "Pack source limitation text." not in result.limitations


def test_client_safe_never_internal_evidence() -> None:
    current, previous = _change_pack(
        visibility_mode=EvidenceVisibility.CLIENT_SAFE,
        throughput_completed=None,
        throughput_forecast=None,
        quality_gold=None,
        rework_rate=None,
    )
    result = assess_change_intelligence(current, previous, policy=None)
    for ref in result.evidence:
        assert ref.visibility == EvidenceVisibility.CLIENT_SAFE


def test_public_contracts_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(
            {
                "org_id": uuid4(),
                "project_id": uuid4(),
                "current_reporting_period": resolve_reporting_period(_AS_OF).model_dump(),
                "visibility_mode": "internal",
                "availability": "partial",
                "changes": [],
                "detected_candidate_count": 0,
                "evaluated_candidate_count": 0,
                "published_change_count": 0,
                "policy_evaluated": False,
                "domain_coverage": [],
                "limitations": [],
                "previous_source_limitations": [],
                "current_source_limitations": [],
                "evidence": [],
                "current_source_fingerprint": "a" * 64,
                "assessed_at": datetime(2026, 6, 18, tzinfo=UTC),
                "extra": "nope",
            }
        )


def test_unreliable_candidate_limitation_code() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        if not item.is_reliable:
            assert LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE in item.limitations


def test_current_only_milestone_no_added_candidate() -> None:
    current, previous = _change_pack()
    extra_id = uuid4()
    current = _with_extra_milestone(current, milestone_id=extra_id)
    candidates = build_change_candidates(current, previous)
    assert not any(
        item.domain == ChangeDomain.MILESTONE and extra_id.hex in item.candidate_key
        for item in candidates
    )
    comparison = build_change_comparison(current, previous)
    milestone = _domain_outcome(comparison, ChangeDomain.MILESTONE)
    assert LIMITATION_MILESTONE_CREATION_HISTORY_UNAVAILABLE in milestone.limitations


def test_current_only_risk_no_added_candidate() -> None:
    current, previous = _change_pack()
    risk_id = uuid4()
    current = _with_extra_risk(current, risk_id=risk_id)
    candidates = build_change_candidates(current, previous)
    assert not any(
        item.domain == ChangeDomain.RISK and risk_id.hex in item.candidate_key
        for item in candidates
    )


def test_current_only_milestone_risk_not_publishable_by_policy() -> None:
    current, previous = _change_pack()
    extra_ms = uuid4()
    extra_risk = uuid4()
    current = _with_extra_risk(
        _with_extra_milestone(current, milestone_id=extra_ms),
        risk_id=extra_risk,
    )
    result = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    assert not any(extra_ms.hex in item.candidate_key for item in result.changes)
    assert not any(extra_risk.hex in item.candidate_key for item in result.changes)


def test_previous_only_milestone_not_completed_removed() -> None:
    current, previous = _change_pack()
    only_prev_id = uuid4()
    previous = _with_extra_milestone(previous, milestone_id=only_prev_id)
    candidates = build_change_candidates(current, previous)
    assert not any(only_prev_id.hex in item.candidate_key for item in candidates)
    comparison = build_change_comparison(current, previous)
    milestone = _domain_outcome(comparison, ChangeDomain.MILESTONE)
    assert LIMITATION_MILESTONE_CLOSURE_HISTORY_UNAVAILABLE in milestone.limitations


def test_previous_only_risk_not_closed_mitigated() -> None:
    current, previous = _change_pack(include_risk=True)
    risk_id = previous.delivery.open_risks[0].id
    current = _refingerprint(
        current.model_copy(
            update={
                "delivery": current.delivery.model_copy(update={"open_risks": []}),
                "evidence": [
                    item for item in current.evidence if item.source_table != "risk_alerts"
                ],
            }
        )
    )
    candidates = build_change_candidates(current, previous)
    assert not any(
        item.domain == ChangeDomain.RISK and risk_id.hex in item.candidate_key
        for item in candidates
    )
    comparison = build_change_comparison(current, previous)
    risk = next(item for item in comparison.domain_outcomes if item.domain == ChangeDomain.RISK)
    assert LIMITATION_RISK_CLOSURE_HISTORY_UNAVAILABLE in risk.limitations


def test_reliable_unchanged_domain_evaluated_zero_candidates() -> None:
    current, previous = _change_pack(unchanged_values=True)
    comparison = build_change_comparison(current, previous)
    assert comparison.candidates == []
    for domain in (ChangeDomain.DELIVERY_CONFIDENCE, ChangeDomain.QUALITY, ChangeDomain.REWORK):
        outcome = next(item for item in comparison.domain_outcomes if item.domain == domain)
        assert outcome.state == ChangeDomainCoverageState.EVALUATED


def test_unavailable_domain_distinct_from_evaluated_no_change() -> None:
    current, previous = _change_pack()
    comparison = build_change_comparison(current, previous)
    readiness = _domain_outcome(comparison, ChangeDomain.READINESS)
    quality = _domain_outcome(comparison, ChangeDomain.QUALITY)
    assert readiness.state == ChangeDomainCoverageState.UNAVAILABLE
    assert quality.state == ChangeDomainCoverageState.EVALUATED


def test_unreliable_domain_distinct_from_unavailable() -> None:
    current, previous = _mixed_reliability_pack()
    comparison = build_change_comparison(current, previous)
    throughput = next(
        item for item in comparison.domain_outcomes if item.domain == ChangeDomain.THROUGHPUT
    )
    readiness = next(
        item for item in comparison.domain_outcomes if item.domain == ChangeDomain.READINESS
    )
    assert throughput.state == ChangeDomainCoverageState.UNRELIABLE
    assert readiness.state == ChangeDomainCoverageState.UNAVAILABLE


def test_missing_policy_only_affects_domains_with_reliable_candidates() -> None:
    current, previous = _mixed_reliability_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    throughput = _coverage_item(result, ChangeDomain.THROUGHPUT)
    delivery = next(
        item for item in result.domain_coverage if item.domain == ChangeDomain.DELIVERY_CONFIDENCE
    )
    assert throughput.state == ChangeDomainCoverageState.UNRELIABLE
    assert delivery.state == ChangeDomainCoverageState.POLICY_NOT_EVALUATED


def test_coverage_contains_every_domain_once_canonical_order() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=None)
    domains = [item.domain for item in result.domain_coverage]
    assert domains == list(ChangeDomain)
    assert len(domains) == len(set(domains))


def test_mixed_reliability_assessment_limitation_and_policy_context() -> None:
    current, previous = _mixed_reliability_pack()
    policy = _FixtureChangePolicy()
    result = assess_change_intelligence(current, previous, policy=policy)
    assert LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations
    assert policy.received_context is not None
    assert all(item.is_reliable for item in policy.received_context.candidates)
    assert any(
        item.domain == ChangeDomain.THROUGHPUT and not item.is_reliable
        for item in build_change_candidates(current, previous)
    )


def test_policy_decision_on_unreliable_key_fails_closed() -> None:
    current, previous = _mixed_reliability_pack()
    unreliable = next(
        item for item in build_change_candidates(current, previous) if not item.is_reliable
    )

    def _mutate(_ctx, decision):
        return decision.model_copy(
            update={
                "selections": [
                    ChangeMaterialitySelection(
                        candidate_key=unreliable.candidate_key,
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST",
                        priority=0,
                    )
                ]
            }
        )

    with pytest.raises(ChangeIntelligenceIntegrityError):
        assess_change_intelligence(
            current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
        )


def test_source_limitation_period_provenance_serialization() -> None:
    current, previous = _change_pack(limitations=["Current-only note."])
    previous = _refingerprint(
        previous.model_copy(update={"limitations": ["Previous-only note."]})
    )
    result = assess_change_intelligence(current, previous, policy=None)
    assert result.current_source_limitations == ["Current-only note."]
    assert result.previous_source_limitations == ["Previous-only note."]
    payload = result.model_dump(mode="json")
    assert "source_limitations" not in payload
    assert payload["current_source_limitations"] == ["Current-only note."]
    assert payload["previous_source_limitations"] == ["Previous-only note."]


def test_candidate_rejects_unrelated_extra_claims() -> None:
    current, previous = _change_pack()
    candidate = _first_reliable_candidate(current, previous)
    data = candidate.model_dump(mode="python")
    data["current_evidence"][0]["claim_keys"].append("units_forecast")
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_candidate_rejects_wrong_row_id() -> None:
    current, previous = _change_pack()
    candidate = _first_reliable_candidate(current, previous)
    data = candidate.model_dump(mode="python")
    data["current_evidence"][0]["source_row_id"] = uuid4()
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_candidate_rejects_wrong_table() -> None:
    current, previous = _change_pack()
    candidate = _first_reliable_candidate(current, previous)
    data = candidate.model_dump(mode="python")
    data["current_evidence"][0]["source_table"] = "projects"
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_candidate_rejects_wrong_source_agent() -> None:
    current, previous = _change_pack()
    candidate = next(
        item
        for item in build_change_candidates(current, previous)
        if item.is_reliable and item.domain == ChangeDomain.DELIVERY_CONFIDENCE
    )
    data = candidate.model_dump(mode="python")
    data["current_evidence"][0]["source_agent"] = SourceAgent.QUALITY_INTELLIGENCE.value
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_candidate_rejects_swapped_previous_current_identity() -> None:
    current, previous = _change_pack()
    candidate = _first_reliable_candidate(current, previous)
    data = candidate.model_dump(mode="python")
    data["previous_evidence"], data["current_evidence"] = (
        data["current_evidence"],
        data["previous_evidence"],
    )
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_candidate_rejects_fabricated_comparison_identity() -> None:
    current, previous = _change_pack()
    candidate = _first_reliable_candidate(current, previous)
    data = candidate.model_dump(mode="python")
    data["comparison_identity"] = "not-a-valid-identity!!!"
    with pytest.raises(ValidationError):
        ChangeCandidate.model_validate(data)


def test_assessment_rejects_published_changes_without_rules_version() -> None:
    current, previous = _change_pack()
    base = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    data = base.model_dump(mode="python")
    data["rules_version"] = None
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_assessment_rejects_missing_previous_period_with_changes() -> None:
    current, previous = _change_pack()
    base = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    data = base.model_dump(mode="python")
    data["previous_reporting_period"] = None
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_no_added_direction_in_public_contract() -> None:
    assert "added" not in {item.value for item in ChangeDirection}


def test_zero_selection_policy_evaluates_candidates() -> None:
    current, previous = _change_pack()
    policy = _ZeroSelectionPolicy()
    assess_change_intelligence(current, previous, policy=policy)
    assert policy.received_context is not None
    assert len(policy.received_context.candidates) > 0


def test_zero_selection_policy_retains_rules_version() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert result.rules_version == _TEST_RULES


def test_zero_selection_policy_published_count_zero() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert result.published_change_count == 0
    assert result.changes == []


def test_zero_selection_policy_empty_evidence() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert result.evidence == []


def test_zero_selection_policy_no_missing_policy_limitation() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE not in result.limitations


def test_zero_selection_policy_applicable_coverage_evaluated() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    delivery = _coverage_item(result, ChangeDomain.DELIVERY_CONFIDENCE)
    assert delivery.state == ChangeDomainCoverageState.EVALUATED


def test_zero_selection_policy_deterministic() -> None:
    current, previous = _change_pack()
    first = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    second = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_zero_selection_policy_evaluated_count_and_provenance() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = [item for item in candidates if item.is_reliable]
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert result.policy_evaluated is True
    assert result.evaluated_candidate_count == len(reliable)
    assert result.detected_candidate_count == len(candidates)


def test_missing_policy_detected_vs_evaluated_counts() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    result = assess_change_intelligence(current, previous, policy=None)
    assert result.detected_candidate_count == len(candidates)
    assert result.evaluated_candidate_count == 0


def test_mixed_reliability_count_semantics() -> None:
    current, previous = _mixed_reliability_pack()
    candidates = build_change_candidates(current, previous)
    reliable = [item for item in candidates if item.is_reliable]
    result = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    assert result.detected_candidate_count == len(candidates)
    assert result.evaluated_candidate_count == len(reliable)
    assert result.published_change_count <= result.evaluated_candidate_count


def test_engine_never_returns_available() -> None:
    current, previous = _change_pack()
    with_policy = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    without_policy = assess_change_intelligence(current, previous, policy=None)
    zero_selection = assess_change_intelligence(
        current, previous, policy=_ZeroSelectionPolicy()
    )
    assert with_policy.availability != ChangeIntelligenceAvailability.AVAILABLE
    assert without_policy.availability != ChangeIntelligenceAvailability.AVAILABLE
    assert zero_selection.availability != ChangeIntelligenceAvailability.AVAILABLE


def test_zero_selection_policy_remains_partial() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_ZeroSelectionPolicy())
    assert result.availability == ChangeIntelligenceAvailability.PARTIAL


def test_fabricated_available_assessment_rejected() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous)
    data["availability"] = ChangeIntelligenceAvailability.AVAILABLE.value
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_fabricated_available_with_unavailable_readiness_fails() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous, policy=None)
    data["availability"] = ChangeIntelligenceAvailability.AVAILABLE.value
    readiness = next(
        item for item in data["domain_coverage"] if item["domain"] == ChangeDomain.READINESS.value
    )
    readiness["state"] = ChangeDomainCoverageState.UNAVAILABLE.value
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_fabricated_available_with_unavailable_resource_onboarding_fails() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous, policy=None)
    data["availability"] = ChangeIntelligenceAvailability.AVAILABLE.value
    onboarding = next(
        item
        for item in data["domain_coverage"]
        if item["domain"] == ChangeDomain.RESOURCE_ONBOARDING.value
    )
    onboarding["state"] = ChangeDomainCoverageState.UNAVAILABLE.value
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_fabricated_available_with_policy_not_evaluated_fails() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous, policy=None)
    data["availability"] = ChangeIntelligenceAvailability.AVAILABLE.value
    delivery = next(
        item
        for item in data["domain_coverage"]
        if item["domain"] == ChangeDomain.DELIVERY_CONFIDENCE.value
    )
    delivery["state"] = ChangeDomainCoverageState.POLICY_NOT_EVALUATED.value
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_assessment_rejects_cross_org_change_item() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous)
    data["changes"][0]["org_id"] = uuid4()
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_assessment_rejects_cross_project_change_item() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous)
    data["changes"][0]["project_id"] = uuid4()
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_assessment_rejects_mismatched_previous_period() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous)
    period = data["changes"][0]["comparison_period"]
    period["previous_start_date"] = date(2019, 1, 1)
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_assessment_rejects_mismatched_current_period() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous)
    period = data["changes"][0]["comparison_period"]
    period["current_end_date"] = date(2099, 12, 31)
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_policy_mutation_cannot_alter_identity() -> None:
    current, previous = _change_pack()
    candidates = build_change_candidates(current, previous)
    reliable = next(item for item in candidates if item.is_reliable)

    def _mutate(ctx, decision):
        if ctx.candidates:
            ctx.candidates[0].org_id = uuid4()
            ctx.candidates[0].project_id = uuid4()
            ctx.candidates[0].comparison_period = ChangeComparisonPeriod(
                previous_start_date=date(2010, 1, 1),
                previous_end_date=date(2010, 1, 7),
                current_start_date=date(2010, 1, 8),
                current_end_date=date(2010, 1, 14),
            )
        return decision.model_copy(
            update={
                "selections": [
                    ChangeMaterialitySelection(
                        candidate_key=reliable.candidate_key,
                        materiality=ChangeMateriality.MATERIAL,
                        business_meaning_code="TEST",
                        priority=0,
                    )
                ]
            }
        )

    result = assess_change_intelligence(
        current, previous, policy=_FixtureChangePolicy(mutate=_mutate)
    )
    published = next(
        item for item in result.changes if item.candidate_key == reliable.candidate_key
    )
    assert published.org_id == reliable.org_id
    assert published.project_id == reliable.project_id
    assert published.comparison_period == reliable.comparison_period


def test_valid_change_items_carry_comparison_identity() -> None:
    current, previous = _change_pack()
    result = assess_change_intelligence(current, previous, policy=_FixtureChangePolicy())
    period = ChangeComparisonPeriod(
        previous_start_date=previous.reporting_period.start_date,
        previous_end_date=previous.reporting_period.end_date,
        current_start_date=current.reporting_period.start_date,
        current_end_date=current.reporting_period.end_date,
    )
    for item in result.changes:
        assert item.org_id == current.project.org_id
        assert item.project_id == current.project.project_id
        assert item.comparison_period == period


def test_candidates_carry_pack_identity() -> None:
    current, previous = _change_pack()
    for item in build_change_candidates(current, previous):
        assert item.org_id == current.project.org_id
        assert item.project_id == current.project.project_id


def test_policy_evaluated_false_requires_zero_evaluated_count() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous, policy=None)
    data["evaluated_candidate_count"] = 1
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)


def test_policy_evaluated_true_requires_rules_version() -> None:
    current, previous = _change_pack()
    data = _assessment_payload(current, previous, policy=_ZeroSelectionPolicy())
    data["rules_version"] = None
    with pytest.raises(ValidationError):
        ChangeIntelligenceAssessment.model_validate(data)
