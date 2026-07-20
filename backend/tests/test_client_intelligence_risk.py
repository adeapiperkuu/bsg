"""Client Intelligence Risk Transparency tests (TASK 12).

Fixture policies are test-only — not production materiality/visibility rules.
CI-DQ09 remains unresolved. Business impact and mitigation remain UNAVAILABLE.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
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
    RiskBusinessImpactDimension,
    RiskBusinessImpactView,
    RiskCandidateSourceType,
    RiskCategory,
    RiskClientVisibilityDecision,
    RiskMitigationAvailability,
    RiskMitigationView,
    RiskTransparencyAssessment,
    RiskTransparencyAvailability,
    RiskTransparencyCandidateContext,
    RiskTransparencyIntegrityError,
    RiskTransparencyPolicyDecision,
    RiskTransparencySelection,
    SourceAgent,
    WorkforceEvidenceFacts,
    assess_risk_transparency,
    finalize_pack_collections,
    resolve_reporting_period,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    worst_data_quality_state,
)
from app.agents.client_intelligence.evidence_validation import finalize_data_quality_issues
from app.agents.client_intelligence.risk_transparency import (
    LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED,
    LIMITATION_CLIENT_SAFE_RISKS_NOT_CONFIGURED,
    LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE,
    LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE,
    LIMITATION_RISK_POLICY_UNAVAILABLE,
    LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS,
    LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS,
    LIMITATION_SOURCE_QUALITY_STALE_RISK_ALERTS,
)

_AS_OF = date(2026, 6, 18)
_ORG = UUID("33333333-3333-4333-8333-333333333333")
_TEST_RULES = "test.fixture.risk_transparency.v1"


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


def _base_pack(
    *,
    visibility_mode: EvidenceVisibility = EvidenceVisibility.INTERNAL,
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    limitations: list[str] | None = None,
) -> ClientEvidencePack:
    pid = project_id or uuid4()
    oid = org_id or _ORG
    period = resolve_reporting_period(_AS_OF)
    milestone_id = uuid4()
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
    refs = [
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="projects",
            source_row_id=pid,
            description="project",
            visibility=EvidenceVisibility.CLIENT_SAFE,
            claim_keys=["project_id", "project_name", "project_status"],
        ),
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
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
        ClientEvidenceReference(
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
        ),
    ]
    confidence = DeliveryConfidenceFacts(
        id=confidence_id,
        milestone_id=milestone_id,
        score_pct=Decimal("88.50"),
        status="confident",
        forecast_completion_date=date(2026, 7, 15),
        model_version=None
        if visibility_mode == EvidenceVisibility.CLIENT_SAFE
        else "delivery-v1",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    dq = finalize_data_quality_issues(
        [
            DataQualityIssue(
                source="milestones", state=DataQualityState.COMPLETE, detail="ok"
            ),
            DataQualityIssue(
                source="delivery_confidence_scores",
                state=DataQualityState.COMPLETE,
                detail="ok",
            ),
        ]
    )
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=[],
        limitations=limitations or [],
    )
    delivery = DeliveryEvidenceFacts(
        milestones=milestones,
        next_milestone_id=milestone_id,
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
    project = ProjectIdentityFacts(
        project_id=pid,
        org_id=oid,
        project_name="Aurora Labeling",
        project_status="active",
    )
    overall = worst_data_quality_state([issue.state for issue in dq])
    return ClientEvidencePack(
        project=project,
        reporting_period=period,
        visibility_mode=visibility_mode,
        delivery=delivery,
        quality=quality,
        workforce=WorkforceEvidenceFacts(as_of=_AS_OF),
        governance=GovernanceEvidenceFacts(as_of=_AS_OF),
        knowledge=KnowledgeEvidenceFacts(
            documents=[],
            chunks=[],
            source_availability=_knowledge_availability(),
            as_of=_AS_OF,
            project_scope_key="abc",
        ),
        evidence=refs,
        data_quality=dq,
        overall_data_quality=overall,
        generated_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        source_fingerprint=compute_source_fingerprint(
            project=project,
            reporting_period=period,
            visibility_mode=visibility_mode,
            delivery=delivery,
            quality=quality,
            workforce=WorkforceEvidenceFacts(as_of=_AS_OF),
            governance=GovernanceEvidenceFacts(as_of=_AS_OF),
            knowledge=KnowledgeEvidenceFacts(
                documents=[],
                chunks=[],
                source_availability=_knowledge_availability(),
                as_of=_AS_OF,
                project_scope_key="abc",
            ),
            evidence=refs,
            data_quality=dq,
            overall_data_quality=overall,
            visibility_limitations=vis,
            limitations=lim,
        ),
        policy_fingerprint=None,
        visibility_limitations=vis,
        limitations=lim,
    )


def _with_risk(
    pack: ClientEvidencePack,
    *,
    alert_type: str = "delivery_risk",
    risk_tier: str = "high",
    status: str = "open",
    risk_dq: DataQualityState | None = DataQualityState.COMPLETE,
    observed_at: datetime | None = datetime(2026, 6, 2, tzinfo=UTC),
    title: str = "Slippage",
) -> ClientEvidencePack:
    risk_id = uuid4()
    refs = list(pack.evidence)
    dq = list(pack.data_quality)
    open_risks = list(pack.delivery.open_risks)
    open_risks.append(
        RiskAlertFacts(
            id=risk_id,
            alert_type=alert_type,
            risk_tier=risk_tier,
            title=title,
            status=status,
            detail="internal detail",
            observed_at=observed_at,
        )
    )
    refs.append(
        ClientEvidenceReference(
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
    )
    if risk_dq is not None:
        dq.append(
            DataQualityIssue(source="risk_alerts", state=risk_dq, detail="risk quality")
        )
    finalized_refs, finalized_dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=list(pack.visibility_limitations),
        limitations=list(pack.limitations),
    )
    delivery = pack.delivery.model_copy(update={"open_risks": open_risks})
    overall = worst_data_quality_state([item.state for item in finalized_dq])
    return _refingerprint(
        pack.model_copy(
            update={
                "delivery": delivery,
                "evidence": finalized_refs,
                "data_quality": finalized_dq,
                "overall_data_quality": overall,
                "visibility_limitations": vis,
                "limitations": lim,
            }
        )
    )


def _with_bottleneck(
    pack: ClientEvidencePack,
    *,
    status: str = "open",
    bottleneck_dq: DataQualityState | None = DataQualityState.COMPLETE,
    observed_at: datetime | None = datetime(2026, 6, 3, tzinfo=UTC),
) -> ClientEvidencePack:
    bn_id = uuid4()
    refs = list(pack.evidence)
    dq = list(pack.data_quality)
    open_bottlenecks = list(pack.delivery.open_bottlenecks)
    open_bottlenecks.append(
        BottleneckFacts(
            id=bn_id,
            title="Queue",
            status=status,
            detail="internal",
            observed_at=observed_at,
        )
    )
    refs.append(
        ClientEvidenceReference(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="bottlenecks",
            source_row_id=bn_id,
            description="bottleneck",
            visibility=EvidenceVisibility.INTERNAL,
            observed_at=observed_at,
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
                source="bottlenecks", state=bottleneck_dq, detail="bn quality"
            )
        )
    finalized_refs, finalized_dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=list(pack.visibility_limitations),
        limitations=list(pack.limitations),
    )
    delivery = pack.delivery.model_copy(update={"open_bottlenecks": open_bottlenecks})
    overall = worst_data_quality_state([item.state for item in finalized_dq])
    return _refingerprint(
        pack.model_copy(
            update={
                "delivery": delivery,
                "evidence": finalized_refs,
                "data_quality": finalized_dq,
                "overall_data_quality": overall,
                "visibility_limitations": vis,
                "limitations": lim,
            }
        )
    )


class _FixtureRiskPolicy:
    """Test-only selection policy. Never invents impact or mitigation."""

    def __init__(
        self,
        *,
        mutate=None,
        category_overrides: dict[str, RiskCategory] | None = None,
        material: bool = True,
        client_visible: bool = False,
        rules_version: str = _TEST_RULES,
        select_all: bool = True,
        only_keys: list[str] | None = None,
    ) -> None:
        self._rules_version = rules_version
        self._mutate = mutate
        self._category_overrides = category_overrides or {}
        self._material = material
        self._client_visible = client_visible
        self._select_all = select_all
        self._only_keys = only_keys

    @property
    def rules_version(self) -> str:
        return self._rules_version

    def evaluate(
        self, candidates: RiskTransparencyCandidateContext
    ) -> RiskTransparencyPolicyDecision:
        selections: list[RiskTransparencySelection] = []
        for item in candidates.candidates:
            if self._only_keys is not None and item.candidate_key not in self._only_keys:
                continue
            if not self._select_all and self._only_keys is None:
                continue
            category = self._category_overrides.get(
                item.candidate_key, item.eligible_categories[0]
            )
            selections.append(
                RiskTransparencySelection(
                    candidate_key=item.candidate_key,
                    category=category,
                    material=self._material,
                    client_visible=self._client_visible,
                )
            )
        decision = RiskTransparencyPolicyDecision(
            selections=selections,
            policy_limitations=[],
        )
        if self._mutate is not None:
            decision = self._mutate(candidates, decision)
        return decision


def test_missing_policy_fails_closed_and_publishes_no_risks() -> None:
    pack = _with_risk(_base_pack())
    result = assess_risk_transparency(pack, policy=None)
    assert result.risk_items == []
    assert result.availability == RiskTransparencyAvailability.UNAVAILABLE
    assert LIMITATION_RISK_POLICY_UNAVAILABLE in result.limitations
    assert LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE in result.limitations


def test_empty_no_risk_pack_behavior() -> None:
    pack = _base_pack()
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.risk_items == []
    assert result.availability == RiskTransparencyAvailability.UNAVAILABLE


def test_valid_internal_risk_alert_selection() -> None:
    pack = _with_risk(_base_pack())
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.availability == RiskTransparencyAvailability.AVAILABLE
    assert len(result.risk_items) == 1
    item = result.risk_items[0]
    assert item.source_type == RiskCandidateSourceType.RISK_ALERT
    assert item.status == "open"
    assert item.risk_tier == "high"
    assert item.business_impact.dimension == RiskBusinessImpactDimension.UNAVAILABLE
    assert item.mitigation.availability == RiskMitigationAvailability.UNAVAILABLE
    assert any(ref.source_table == "risk_alerts" for ref in result.evidence)


def test_valid_internal_bottleneck_selection() -> None:
    pack = _with_bottleneck(_base_pack())
    result = assess_risk_transparency(
        pack,
        policy=_FixtureRiskPolicy(
            category_overrides={}  # eligible first is WORKFLOW_BOTTLENECK
        ),
    )
    assert result.availability == RiskTransparencyAvailability.AVAILABLE
    assert result.risk_items[0].category == RiskCategory.WORKFLOW_BOTTLENECK
    assert result.risk_items[0].source_type == RiskCandidateSourceType.BOTTLENECK


def test_acknowledged_risk_is_eligible() -> None:
    pack = _with_risk(_base_pack(), status="acknowledged")
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert len(result.risk_items) == 1
    assert result.risk_items[0].status == "acknowledged"


def test_resolved_risk_in_pack_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.client_intelligence.risk_transparency._validate_pack_or_raise",
        lambda _pack: None,
    )
    pack = _with_risk(_base_pack(), status="resolved")
    with pytest.raises(RiskTransparencyIntegrityError):
        assess_risk_transparency(pack, policy=_FixtureRiskPolicy())


def test_workforce_imbalance_supports_resource_constraint() -> None:
    pack = _with_risk(_base_pack(), alert_type="workforce_imbalance")
    result = assess_risk_transparency(
        pack,
        policy=_FixtureRiskPolicy(
            category_overrides={},
        ),
    )
    # Fixture picks eligible_categories[0] which is RESOURCE_CONSTRAINT
    assert result.risk_items[0].category == RiskCategory.RESOURCE_CONSTRAINT


def test_bottleneck_supports_only_workflow_or_unclassified() -> None:
    pack = _with_bottleneck(_base_pack())

    def _mutate(candidates, decision):
        bad = [
            item.model_copy(update={"category": RiskCategory.QA_REWORK})
            for item in decision.selections
        ]
        return decision.model_copy(update={"selections": bad})

    with pytest.raises(RiskTransparencyIntegrityError) as (exc):
        assess_risk_transparency(
            pack, policy=_FixtureRiskPolicy(mutate=_mutate)
        )
    assert exc.value.code == "invalid_policy_decision"


def test_quality_drift_does_not_auto_prove_qa_rework() -> None:
    pack = _with_risk(_base_pack(), alert_type="quality_drift")

    def _mutate(candidates, decision):
        bad = [
            item.model_copy(update={"category": RiskCategory.QA_REWORK})
            for item in decision.selections
        ]
        return decision.model_copy(update={"selections": bad})

    with pytest.raises(RiskTransparencyIntegrityError):
        assess_risk_transparency(pack, policy=_FixtureRiskPolicy(mutate=_mutate))
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.risk_items[0].category == RiskCategory.UNCLASSIFIED


def test_delivery_risk_does_not_auto_prove_dependency_delay() -> None:
    pack = _with_risk(_base_pack(), alert_type="delivery_risk")

    def _mutate(candidates, decision):
        bad = [
            item.model_copy(update={"category": RiskCategory.DEPENDENCY_DELAY})
            for item in decision.selections
        ]
        return decision.model_copy(update={"selections": bad})

    with pytest.raises(RiskTransparencyIntegrityError):
        assess_risk_transparency(pack, policy=_FixtureRiskPolicy(mutate=_mutate))


def test_policy_cannot_select_unknown_candidate() -> None:
    pack = _with_risk(_base_pack())

    def _mutate(candidates, decision):
        del candidates
        return decision.model_copy(
            update={
                "selections": [
                    RiskTransparencySelection(
                        candidate_key="risk_alert.deadbeefdeadbeefdeadbeefdeadbeef",
                        category=RiskCategory.UNCLASSIFIED,
                        material=True,
                        client_visible=False,
                    )
                ]
            }
        )

    with pytest.raises(RiskTransparencyIntegrityError) as (exc):
        assess_risk_transparency(pack, policy=_FixtureRiskPolicy(mutate=_mutate))
    assert exc.value.code == "invalid_policy_decision"


def test_policy_cannot_rewrite_status_via_selection() -> None:
    pack = _with_risk(_base_pack(), status="open", risk_tier="critical")
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.risk_items[0].status == "open"
    assert result.risk_items[0].risk_tier == "critical"


def test_policy_context_only_signature() -> None:
    params = list(inspect.signature(_FixtureRiskPolicy.evaluate).parameters.keys())
    assert params == ["self", "candidates"]


def test_policy_mutation_of_context_does_not_change_assessment() -> None:
    pack = _with_risk(_base_pack())
    original_fp = pack.source_fingerprint

    class _Mutate(_FixtureRiskPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            for item in candidates.candidates:
                item.status = "resolved"
                item.risk_tier = "low"
                item.source_fingerprint = "c" * 64
                item.data_quality = DataQualityState.STALE
            candidates.candidates.clear()
            return decision

    result = assess_risk_transparency(pack, policy=_Mutate())
    assert result.source_fingerprint == original_fp
    assert result.risk_items[0].status == "open"
    assert result.risk_items[0].risk_tier == "high"
    assert result.risk_items[0].data_quality == DataQualityState.COMPLETE


def test_policy_closure_pack_mutation_bypass_closed() -> None:
    pack = _with_risk(_base_pack(org_id=_ORG))
    original_org = pack.project.org_id
    original_fp = pack.source_fingerprint
    held = {"pack": pack}

    class _Hostile(_FixtureRiskPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            owned = held["pack"]
            owned.project.org_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
            owned.source_fingerprint = "b" * 64
            if owned.delivery.open_risks:
                risk = owned.delivery.open_risks[0]
                owned.delivery.open_risks[0] = risk.model_copy(
                    update={"status": "dismissed", "risk_tier": "low"}
                )
            return decision

    result = assess_risk_transparency(pack, policy=_Hostile())
    assert result.org_id == original_org
    assert result.source_fingerprint == original_fp
    assert result.risk_items[0].status == "open"
    assert result.risk_items[0].risk_tier == "high"


def test_policy_exception_sanitized() -> None:
    pack = _with_risk(_base_pack())
    sensitive = "SECRET_reviewer_alice"

    class _Hostile(_FixtureRiskPolicy):
        def evaluate(self, candidates):
            raise RuntimeError(sensitive)

    with pytest.raises(RiskTransparencyIntegrityError) as (exc):
        assess_risk_transparency(pack, policy=_Hostile())
    assert exc.value.code == "invalid_policy"
    assert sensitive not in str(exc.value)
    assert sensitive not in exc.value.detail


def test_missing_source_quality_no_complete_fallback() -> None:
    pack = _with_risk(_base_pack(), risk_dq=None)
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.risk_items == []
    assert LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS in result.limitations


def test_stale_source_cannot_publish_material_risks() -> None:
    pack = _with_risk(_base_pack(), risk_dq=DataQualityState.STALE)
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.risk_items == []
    assert LIMITATION_SOURCE_QUALITY_STALE_RISK_ALERTS in result.limitations
    assert result.availability == RiskTransparencyAvailability.STALE


def test_business_impact_unavailable_and_unquantified() -> None:
    pack = _with_risk(_base_pack())
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    impact = result.risk_items[0].business_impact
    assert impact.dimension == RiskBusinessImpactDimension.UNAVAILABLE
    assert impact.quantified is False
    assert LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED in result.limitations
    with pytest.raises(ValidationError):
        RiskBusinessImpactView(
            dimension=RiskBusinessImpactDimension.TIMELINE,
            quantified=False,
        )


def test_mitigation_unavailable() -> None:
    pack = _with_risk(_base_pack())
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert (
        result.risk_items[0].mitigation.availability
        == RiskMitigationAvailability.UNAVAILABLE
    )
    assert LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE in result.limitations
    with pytest.raises(ValidationError):
        RiskMitigationView(
            availability=RiskMitigationAvailability.UNAVAILABLE,
            owner_role="pm",
        )


def test_source_limitations_separate_from_structured_codes() -> None:
    note = "Risk adapter source note is unavailable."
    pack = _with_risk(_base_pack(limitations=[note]))
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert note in result.source_limitations
    assert note not in result.limitations


def test_client_safe_mode_fail_closed() -> None:
    pack = _base_pack(visibility_mode=EvidenceVisibility.CLIENT_SAFE)
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.risk_items == []
    assert LIMITATION_CLIENT_SAFE_RISKS_NOT_CONFIGURED in result.limitations
    assert result.evidence == []


def test_item_evidence_missing_from_top_level_rejected() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack()), policy=_FixtureRiskPolicy()
    )
    data = result.model_dump(mode="python")
    data["evidence"] = []
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_observed_at_none_versus_timestamp_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.client_intelligence.risk_transparency._validate_pack_or_raise",
        lambda _pack: None,
    )
    pack = _with_risk(_base_pack(), observed_at=None)
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
    with pytest.raises(RiskTransparencyIntegrityError):
        assess_risk_transparency(pack, policy=_FixtureRiskPolicy())


def test_deterministic_ordering_and_serialization() -> None:
    pack = _with_bottleneck(_with_risk(_base_pack()))
    policy = _FixtureRiskPolicy()
    first = assess_risk_transparency(pack, policy=policy)
    second = assess_risk_transparency(pack, policy=policy)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_non_material_selection_not_published() -> None:
    pack = _with_risk(_base_pack())
    result = assess_risk_transparency(
        pack, policy=_FixtureRiskPolicy(material=False)
    )
    assert result.risk_items == []
    assert result.availability == RiskTransparencyAvailability.UNAVAILABLE


def _available_risk_assessment() -> RiskTransparencyAssessment:
    return assess_risk_transparency(
        _with_risk(_base_pack()), policy=_FixtureRiskPolicy()
    )


def _available_bottleneck_assessment() -> RiskTransparencyAssessment:
    return assess_risk_transparency(
        _with_bottleneck(_base_pack()), policy=_FixtureRiskPolicy()
    )


def _payload_rejects(mutator) -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    mutator(data)
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def _bn_payload_rejects(mutator) -> None:
    data = _available_bottleneck_assessment().model_dump(mode="python")
    mutator(data)
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_contract_risk_alert_declared_as_bottleneck() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("source_type", "bottleneck"))


def test_contract_bottleneck_declared_as_risk_alert() -> None:
    _bn_payload_rejects(
        lambda d: d["risk_items"][0].__setitem__("source_type", "risk_alert")
    )


def test_contract_wrong_source_table_for_source_type() -> None:
    def _mutate(d):
        d["risk_items"][0]["source_table"] = "bottlenecks"
        d["risk_items"][0]["evidence"][0]["source_table"] = "bottlenecks"
        d["evidence"][0]["source_table"] = "bottlenecks"

    _payload_rejects(_mutate)


def test_contract_wrong_source_agent_ownership() -> None:
    def _mutate(d):
        d["risk_items"][0]["source_agent"] = "quality_intelligence"
        d["risk_items"][0]["evidence"][0]["source_agent"] = "quality_intelligence"
        d["evidence"][0]["source_agent"] = "quality_intelligence"

    _payload_rejects(_mutate)


def test_contract_wrong_evidence_row_id() -> None:
    other = uuid4()

    def _mutate(d):
        d["risk_items"][0]["evidence"][0]["source_row_id"] = other
        d["evidence"][0]["source_row_id"] = other

    _payload_rejects(_mutate)


def test_contract_wrong_evidence_fingerprint() -> None:
    fp = "b" * 64

    def _mutate(d):
        d["risk_items"][0]["evidence"][0]["source_fingerprint"] = fp
        d["evidence"][0]["source_fingerprint"] = fp

    _payload_rejects(_mutate)


def test_contract_wrong_evidence_period() -> None:
    def _mutate(d):
        # period is enum-only CURRENT; invent invalid string
        d["risk_items"][0]["evidence"][0]["period"] = "historical"
        d["evidence"][0]["period"] = "historical"

    _payload_rejects(_mutate)


def test_contract_wrong_evidence_visibility() -> None:
    def _mutate(d):
        # keep item.visibility INTERNAL; flip evidence only
        d["risk_items"][0]["evidence"][0]["visibility"] = "client_safe"
        d["evidence"][0]["visibility"] = "client_safe"

    _payload_rejects(_mutate)


def test_contract_none_versus_timestamp_mismatch() -> None:
    def _mutate(d):
        d["risk_items"][0]["observed_at"] = None
        # leave evidence timestamp present

    _payload_rejects(_mutate)


def test_contract_resolved_status() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("status", "resolved"))


def test_contract_dismissed_status() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("status", "dismissed"))


def test_contract_arbitrary_status() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("status", "watching"))


def test_contract_missing_risk_alert_tier() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("risk_tier", None))


def test_contract_missing_risk_alert_alert_type() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("alert_type", None))


def test_contract_bottleneck_carrying_risk_tier() -> None:
    _bn_payload_rejects(lambda d: d["risk_items"][0].__setitem__("risk_tier", "high"))


def test_contract_bottleneck_carrying_alert_type() -> None:
    _bn_payload_rejects(
        lambda d: d["risk_items"][0].__setitem__("alert_type", "delivery_risk")
    )


def test_contract_invalid_risk_alert_tier() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("risk_tier", "severe"))


def test_contract_invalid_risk_alert_alert_type() -> None:
    _payload_rejects(lambda d: d["risk_items"][0].__setitem__("alert_type", "scope_creep"))


def test_contract_missing_required_risk_alert_claim() -> None:
    def _mutate(d):
        claims = [
            "risk_id",
            "risk_title",
            "risk_tier",
            "alert_type",
            # status omitted
        ]
        d["risk_items"][0]["evidence"][0]["claim_keys"] = claims
        d["evidence"][0]["claim_keys"] = claims

    _payload_rejects(_mutate)


def test_contract_missing_required_bottleneck_claim() -> None:
    def _mutate(d):
        claims = ["bottleneck_id", "bottleneck_title"]  # status omitted
        d["risk_items"][0]["evidence"][0]["claim_keys"] = claims
        d["evidence"][0]["claim_keys"] = claims

    _bn_payload_rejects(_mutate)


def test_contract_internal_detail_claim_on_item_evidence() -> None:
    def _mutate(d):
        claims = list(d["risk_items"][0]["evidence"][0]["claim_keys"]) + ["risk_detail"]
        d["risk_items"][0]["evidence"][0]["claim_keys"] = claims
        d["evidence"][0]["claim_keys"] = claims

    _payload_rejects(_mutate)


def test_contract_internal_detail_claim_only_at_top_level() -> None:
    def _mutate(d):
        claims = list(d["evidence"][0]["claim_keys"]) + ["risk_detail"]
        d["evidence"][0]["claim_keys"] = claims

    _payload_rejects(_mutate)


def test_contract_qa_rework_on_quality_drift() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack(), alert_type="quality_drift"),
        policy=_FixtureRiskPolicy(),
    )
    data = result.model_dump(mode="python")
    data["risk_items"][0]["category"] = RiskCategory.QA_REWORK.value
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_contract_dependency_delay_on_delivery_or_milestone_risk() -> None:
    for alert_type in ("delivery_risk", "milestone_at_risk"):
        result = assess_risk_transparency(
            _with_risk(_base_pack(), alert_type=alert_type),
            policy=_FixtureRiskPolicy(),
        )
        data = result.model_dump(mode="python")
        data["risk_items"][0]["category"] = RiskCategory.DEPENDENCY_DELAY.value
        with pytest.raises(ValidationError):
            RiskTransparencyAssessment.model_validate(data)


def test_contract_resource_constraint_on_non_workforce_risk() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack(), alert_type="delivery_risk"),
        policy=_FixtureRiskPolicy(),
    )
    data = result.model_dump(mode="python")
    data["risk_items"][0]["category"] = RiskCategory.RESOURCE_CONSTRAINT.value
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_contract_workflow_bottleneck_on_risk_alert() -> None:
    _payload_rejects(
        lambda d: d["risk_items"][0].__setitem__(
            "category", RiskCategory.WORKFLOW_BOTTLENECK.value
        )
    )


def test_contract_risk_category_incorrectly_on_bottleneck() -> None:
    _bn_payload_rejects(
        lambda d: d["risk_items"][0].__setitem__(
            "category", RiskCategory.RESOURCE_CONSTRAINT.value
        )
    )


def test_contract_item_client_visibility_undecided() -> None:
    _payload_rejects(
        lambda d: d["risk_items"][0].__setitem__(
            "client_visibility", RiskClientVisibilityDecision.UNDECIDED.value
        )
    )


def test_contract_missing_business_impact_required_limitation() -> None:
    def _mutate(d):
        d["risk_items"][0]["business_impact"]["limitations"] = []

    _payload_rejects(_mutate)


def test_contract_missing_mitigation_required_limitation() -> None:
    def _mutate(d):
        d["risk_items"][0]["mitigation"]["limitations"] = []

    _payload_rejects(_mutate)


def test_contract_missing_item_level_impact_mitigation_limitations() -> None:
    def _mutate(d):
        d["risk_items"][0]["limitations"] = [
            x
            for x in d["risk_items"][0]["limitations"]
            if x
            not in {
                LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED,
                LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE,
            }
        ]

    _payload_rejects(_mutate)


def test_contract_missing_assessment_level_impact_mitigation_limitations() -> None:
    def _mutate(d):
        d["limitations"] = [
            x
            for x in d["limitations"]
            if x
            not in {
                LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED,
                LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE,
            }
        ]

    _payload_rejects(_mutate)


def test_contract_item_evidence_missing_top_level() -> None:
    _payload_rejects(lambda d: d.__setitem__("evidence", []))


def test_contract_item_claim_missing_top_level() -> None:
    def _mutate(d):
        # drop status from top-level only
        d["evidence"][0]["claim_keys"] = [
            c for c in d["evidence"][0]["claim_keys"] if c != "status"
        ]

    _payload_rejects(_mutate)


def test_contract_orphan_top_level_evidence() -> None:
    def _mutate(d):
        orphan_id = uuid4()
        orphan = dict(d["evidence"][0])
        orphan["source_row_id"] = orphan_id
        d["evidence"].append(orphan)

    _payload_rejects(_mutate)


def test_contract_extra_top_level_claim_not_in_item_union() -> None:
    def _mutate(d):
        claims = list(d["evidence"][0]["claim_keys"]) + ["extra_claim"]
        d["evidence"][0]["claim_keys"] = claims

    _payload_rejects(_mutate)


def test_contract_top_level_evidence_on_non_available_assessment() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack(), risk_dq=DataQualityState.STALE),
        policy=_FixtureRiskPolicy(),
    )
    assert result.availability == RiskTransparencyAvailability.STALE
    data = result.model_dump(mode="python")
    available = _available_risk_assessment()
    data["evidence"] = available.model_dump(mode="python")["evidence"]
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_contract_duplicate_candidate_key() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack()), policy=_FixtureRiskPolicy()
    )
    # reconstruct candidate context from engine path by building two identical keys
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    pack = _with_risk(_base_pack())
    assessment = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    # Use engine candidate via assessing again is hard; build from assessment item
    item = assessment.risk_items[0]
    cand = RiskTransparencyCandidate(
        candidate_key=f"risk_alert.{item.source_row_id.hex}",
        source_type=item.source_type,
        source_agent=item.source_agent,
        source_table=item.source_table,
        source_row_id=item.source_row_id,
        status=item.status,
        risk_tier=item.risk_tier,
        alert_type=item.alert_type,
        title="Slippage",
        eligible_categories=[RiskCategory.UNCLASSIFIED],
        observed_at=item.observed_at,
        data_quality=DataQualityState.COMPLETE,
        visibility=item.evidence[0].visibility,
        source_fingerprint=item.source_fingerprint,
        evidence=item.evidence,
    )
    with pytest.raises(ValidationError):
        RiskTransparencyCandidateContext(
            candidates=[cand, cand.model_copy()],
            context_limitations=[],
        )
    del result


def test_contract_same_source_identity_under_different_keys() -> None:
    assessment = assess_risk_transparency(
        _with_risk(_base_pack()), policy=_FixtureRiskPolicy()
    )
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    item = assessment.risk_items[0]
    with pytest.raises(ValidationError):
        RiskTransparencyCandidate(
            candidate_key="risk_alert.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source_type=item.source_type,
            source_agent=item.source_agent,
            source_table=item.source_table,
            source_row_id=item.source_row_id,
            status=item.status,
            risk_tier=item.risk_tier,
            alert_type=item.alert_type,
            title="Slippage",
            eligible_categories=[RiskCategory.UNCLASSIFIED],
            observed_at=item.observed_at,
            data_quality=DataQualityState.COMPLETE,
            visibility=item.evidence[0].visibility,
            source_fingerprint=item.source_fingerprint,
            evidence=item.evidence,
        )


def test_contract_candidate_using_non_complete_quality() -> None:
    assessment = assess_risk_transparency(
        _with_risk(_base_pack()), policy=_FixtureRiskPolicy()
    )
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    item = assessment.risk_items[0]
    with pytest.raises(ValidationError):
        RiskTransparencyCandidate(
            candidate_key=f"risk_alert.{item.source_row_id.hex}",
            source_type=item.source_type,
            source_agent=item.source_agent,
            source_table=item.source_table,
            source_row_id=item.source_row_id,
            status=item.status,
            risk_tier=item.risk_tier,
            alert_type=item.alert_type,
            title="Slippage",
            eligible_categories=[RiskCategory.UNCLASSIFIED],
            observed_at=item.observed_at,
            data_quality=DataQualityState.STALE,
            visibility=item.evidence[0].visibility,
            source_fingerprint=item.source_fingerprint,
            evidence=item.evidence,
        )


def test_mixed_complete_risk_plus_populated_stale_bottleneck() -> None:
    pack = _with_bottleneck(
        _with_risk(_base_pack()),
        bottleneck_dq=DataQualityState.STALE,
    )
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.availability == RiskTransparencyAvailability.PARTIAL
    assert result.risk_items == []
    assert result.evidence == []


def test_mixed_complete_risk_plus_populated_conflicting_bottleneck() -> None:
    pack = _with_bottleneck(
        _with_risk(_base_pack()),
        bottleneck_dq=DataQualityState.CONFLICTING,
    )
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.availability == RiskTransparencyAvailability.CONFLICTING
    assert result.risk_items == []


def test_mixed_complete_risk_plus_populated_partial_bottleneck() -> None:
    pack = _with_bottleneck(
        _with_risk(_base_pack()),
        bottleneck_dq=DataQualityState.PARTIAL,
    )
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.availability == RiskTransparencyAvailability.PARTIAL
    assert result.risk_items == []


def test_mixed_complete_risk_plus_populated_bottleneck_missing_quality() -> None:
    pack = _with_bottleneck(_with_risk(_base_pack()), bottleneck_dq=None)
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.availability == RiskTransparencyAvailability.PARTIAL
    assert result.risk_items == []
    assert LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS in result.limitations


def test_no_fact_no_quality_secondary_source_does_not_degrade() -> None:
    pack = _with_risk(_base_pack())
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert result.availability == RiskTransparencyAvailability.AVAILABLE
    assert len(result.risk_items) == 1


def test_policy_mutation_isolation_regression() -> None:
    pack = _with_risk(_base_pack())
    original_fp = pack.source_fingerprint

    class _Mutate(_FixtureRiskPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            for item in candidates.candidates:
                item.status = "resolved"
                item.alert_type = "quality_drift"
                item.evidence.clear()
            return decision

    result = assess_risk_transparency(pack, policy=_Mutate())
    assert result.source_fingerprint == original_fp
    assert result.risk_items[0].status == "open"
    assert result.risk_items[0].alert_type == "delivery_risk"
    assert result.risk_items[0].evidence


def test_deterministic_evidence_and_item_ordering() -> None:
    pack = _with_bottleneck(_with_risk(_base_pack(), title="Z-risk"))
    first = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    second = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert [i.source_type for i in first.risk_items] == [
        i.source_type for i in second.risk_items
    ]
    assert [e.source_row_id for e in first.evidence] == [
        e.source_row_id for e in second.evidence
    ]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_existing_source_limitations_separation() -> None:
    note = "Adapter free-text limitation."
    pack = _with_risk(_base_pack(limitations=[note]))
    result = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert note in result.source_limitations
    assert note not in result.limitations
    assert LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED in result.limitations


def test_available_rules_version_none_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["rules_version"] = None
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_available_rules_version_empty_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["rules_version"] = ""
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_available_rules_version_whitespace_only_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["rules_version"] = "   "
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_available_rules_version_surrounding_whitespace_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["rules_version"] = f" {_TEST_RULES} "
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_available_rules_version_malformed_characters_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["rules_version"] = "bad version!"
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_available_rules_version_valid_accepted() -> None:
    result = _available_risk_assessment()
    assert result.availability == RiskTransparencyAvailability.AVAILABLE
    assert result.rules_version == _TEST_RULES
    validated = RiskTransparencyAssessment.model_validate(
        result.model_dump(mode="python")
    )
    assert validated.rules_version == _TEST_RULES


def test_non_available_with_evaluated_policy_rules_version() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack()), policy=_FixtureRiskPolicy(material=False)
    )
    assert result.availability == RiskTransparencyAvailability.UNAVAILABLE
    assert result.rules_version == _TEST_RULES
    assert result.risk_items == []
    validated = RiskTransparencyAssessment.model_validate(
        result.model_dump(mode="python")
    )
    assert validated.rules_version == _TEST_RULES


def test_no_policy_missing_risk_policy_unavailable() -> None:
    result = assess_risk_transparency(_with_risk(_base_pack()), policy=None)
    data = result.model_dump(mode="python")
    data["limitations"] = [
        code
        for code in data["limitations"]
        if code != LIMITATION_RISK_POLICY_UNAVAILABLE
    ]
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_no_policy_missing_client_visibility_policy_unavailable() -> None:
    result = assess_risk_transparency(_with_risk(_base_pack()), policy=None)
    data = result.model_dump(mode="python")
    data["limitations"] = [
        code
        for code in data["limitations"]
        if code != LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE
    ]
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_no_policy_missing_both_policy_limitations() -> None:
    result = assess_risk_transparency(_with_risk(_base_pack()), policy=None)
    data = result.model_dump(mode="python")
    data["limitations"] = [
        code
        for code in data["limitations"]
        if code
        not in {
            LIMITATION_RISK_POLICY_UNAVAILABLE,
            LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE,
        }
    ]
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_no_policy_incorrectly_marked_available() -> None:
    result = assess_risk_transparency(_with_risk(_base_pack()), policy=None)
    data = result.model_dump(mode="python")
    data["availability"] = RiskTransparencyAvailability.AVAILABLE.value
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_valid_rules_version_plus_contradictory_risk_policy_unavailable() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["limitations"] = sorted(
        set(data["limitations"]) | {LIMITATION_RISK_POLICY_UNAVAILABLE}
    )
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_valid_rules_version_plus_contradictory_client_visibility_unavailable() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["limitations"] = sorted(
        set(data["limitations"]) | {LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE}
    )
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_exact_duplicate_published_risk_item_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    data["risk_items"].append(dict(data["risk_items"][0]))
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_same_source_row_repeated_different_category_rejected() -> None:
    result = assess_risk_transparency(
        _with_risk(_base_pack(), alert_type="workforce_imbalance"),
        policy=_FixtureRiskPolicy(),
    )
    data = result.model_dump(mode="python")
    duplicate = dict(data["risk_items"][0])
    duplicate["category"] = RiskCategory.UNCLASSIFIED.value
    data["risk_items"].append(duplicate)
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_same_source_row_repeated_different_visibility_rejected() -> None:
    data = _available_risk_assessment().model_dump(mode="python")
    duplicate = dict(data["risk_items"][0])
    duplicate["client_visibility"] = (
        RiskClientVisibilityDecision.CLIENT_VISIBLE.value
    )
    data["risk_items"].append(duplicate)
    with pytest.raises(ValidationError):
        RiskTransparencyAssessment.model_validate(data)


def test_two_genuinely_different_source_rows_remain_valid() -> None:
    result = assess_risk_transparency(
        _with_bottleneck(_with_risk(_base_pack())),
        policy=_FixtureRiskPolicy(),
    )
    assert result.availability == RiskTransparencyAvailability.AVAILABLE
    assert len(result.risk_items) == 2
    identities = {
        (item.source_type, item.source_table, item.source_row_id)
        for item in result.risk_items
    }
    assert len(identities) == 2
    RiskTransparencyAssessment.model_validate(result.model_dump(mode="python"))


def test_risk_alert_candidate_key_wrong_uuid_fragment() -> None:
    assessment = _available_risk_assessment()
    item = assessment.risk_items[0]
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    with pytest.raises(ValidationError):
        RiskTransparencyCandidate(
            candidate_key="risk_alert.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source_type=item.source_type,
            source_agent=item.source_agent,
            source_table=item.source_table,
            source_row_id=item.source_row_id,
            status=item.status,
            risk_tier=item.risk_tier,
            alert_type=item.alert_type,
            title="Slippage",
            eligible_categories=[RiskCategory.UNCLASSIFIED],
            observed_at=item.observed_at,
            data_quality=DataQualityState.COMPLETE,
            visibility=item.visibility,
            source_fingerprint=item.source_fingerprint,
            evidence=item.evidence,
        )


def test_risk_alert_candidate_key_bottleneck_prefix() -> None:
    assessment = _available_risk_assessment()
    item = assessment.risk_items[0]
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    with pytest.raises(ValidationError):
        RiskTransparencyCandidate(
            candidate_key=f"bottleneck.{item.source_row_id.hex}",
            source_type=item.source_type,
            source_agent=item.source_agent,
            source_table=item.source_table,
            source_row_id=item.source_row_id,
            status=item.status,
            risk_tier=item.risk_tier,
            alert_type=item.alert_type,
            title="Slippage",
            eligible_categories=[RiskCategory.UNCLASSIFIED],
            observed_at=item.observed_at,
            data_quality=DataQualityState.COMPLETE,
            visibility=item.visibility,
            source_fingerprint=item.source_fingerprint,
            evidence=item.evidence,
        )


def test_bottleneck_candidate_key_wrong_uuid_fragment() -> None:
    assessment = _available_bottleneck_assessment()
    item = assessment.risk_items[0]
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    with pytest.raises(ValidationError):
        RiskTransparencyCandidate(
            candidate_key="bottleneck.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            source_type=item.source_type,
            source_agent=item.source_agent,
            source_table=item.source_table,
            source_row_id=item.source_row_id,
            status=item.status,
            risk_tier=None,
            alert_type=None,
            title="Queue",
            eligible_categories=[
                RiskCategory.WORKFLOW_BOTTLENECK,
                RiskCategory.UNCLASSIFIED,
            ],
            observed_at=item.observed_at,
            data_quality=DataQualityState.COMPLETE,
            visibility=item.visibility,
            source_fingerprint=item.source_fingerprint,
            evidence=item.evidence,
        )


def test_bottleneck_candidate_key_risk_alert_prefix() -> None:
    assessment = _available_bottleneck_assessment()
    item = assessment.risk_items[0]
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
    )

    with pytest.raises(ValidationError):
        RiskTransparencyCandidate(
            candidate_key=f"risk_alert.{item.source_row_id.hex}",
            source_type=item.source_type,
            source_agent=item.source_agent,
            source_table=item.source_table,
            source_row_id=item.source_row_id,
            status=item.status,
            risk_tier=None,
            alert_type=None,
            title="Queue",
            eligible_categories=[
                RiskCategory.WORKFLOW_BOTTLENECK,
                RiskCategory.UNCLASSIFIED,
            ],
            observed_at=item.observed_at,
            data_quality=DataQualityState.COMPLETE,
            visibility=item.visibility,
            source_fingerprint=item.source_fingerprint,
            evidence=item.evidence,
        )


def test_canonical_risk_alert_candidate_key_accepted() -> None:
    assessment = _available_risk_assessment()
    item = assessment.risk_items[0]
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
        canonical_candidate_key,
    )

    key = canonical_candidate_key(item.source_type, item.source_row_id)
    candidate = RiskTransparencyCandidate(
        candidate_key=key,
        source_type=item.source_type,
        source_agent=item.source_agent,
        source_table=item.source_table,
        source_row_id=item.source_row_id,
        status=item.status,
        risk_tier=item.risk_tier,
        alert_type=item.alert_type,
        title="Slippage",
        eligible_categories=[RiskCategory.UNCLASSIFIED],
        observed_at=item.observed_at,
        data_quality=DataQualityState.COMPLETE,
        visibility=item.visibility,
        source_fingerprint=item.source_fingerprint,
        evidence=item.evidence,
    )
    assert candidate.candidate_key == f"risk_alert.{item.source_row_id.hex}"


def test_canonical_bottleneck_candidate_key_accepted() -> None:
    assessment = _available_bottleneck_assessment()
    item = assessment.risk_items[0]
    from app.agents.client_intelligence.risk_transparency_contracts import (
        RiskTransparencyCandidate,
        canonical_candidate_key,
    )

    key = canonical_candidate_key(item.source_type, item.source_row_id)
    candidate = RiskTransparencyCandidate(
        candidate_key=key,
        source_type=item.source_type,
        source_agent=item.source_agent,
        source_table=item.source_table,
        source_row_id=item.source_row_id,
        status=item.status,
        risk_tier=None,
        alert_type=None,
        title="Queue",
        eligible_categories=[
            RiskCategory.WORKFLOW_BOTTLENECK,
            RiskCategory.UNCLASSIFIED,
        ],
        observed_at=item.observed_at,
        data_quality=DataQualityState.COMPLETE,
        visibility=item.visibility,
        source_fingerprint=item.source_fingerprint,
        evidence=item.evidence,
    )
    assert candidate.candidate_key == f"bottleneck.{item.source_row_id.hex}"


def test_policy_mutation_unknown_candidate_regression() -> None:
    pack = _with_risk(_base_pack())

    def _mutate(candidates, decision):
        del candidates
        return decision.model_copy(
            update={
                "selections": [
                    RiskTransparencySelection(
                        candidate_key="risk_alert.deadbeefdeadbeefdeadbeefdeadbeef",
                        category=RiskCategory.UNCLASSIFIED,
                        material=True,
                        client_visible=False,
                    )
                ]
            }
        )

    with pytest.raises(RiskTransparencyIntegrityError) as exc:
        assess_risk_transparency(pack, policy=_FixtureRiskPolicy(mutate=_mutate))
    assert exc.value.code == "invalid_policy_decision"


def test_deterministic_ordering_regression() -> None:
    pack = _with_bottleneck(_with_risk(_base_pack()))
    first = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    second = assess_risk_transparency(pack, policy=_FixtureRiskPolicy())
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
