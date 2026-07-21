"""Client Intelligence Delivery Trend tests (TASK 13).

No production deviation policy. Plan series unavailable. CLIENT_SAFE fail-closed.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agents.client_intelligence import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    DeliveryEvidenceFacts,
    DeliveryTrendAssessment,
    DeliveryTrendAvailability,
    DeliveryTrendDeviationCandidateContext,
    DeliveryTrendDeviationPolicyDecision,
    DeliveryTrendDeviationSelection,
    DeliveryTrendIntegrityError,
    DeviationMateriality,
    EvidenceVisibility,
    GovernanceEvidenceFacts,
    KnowledgeEvidenceFacts,
    KnowledgeSourceAvailabilityFacts,
    MilestoneFacts,
    ProjectIdentityFacts,
    QualityEvidenceFacts,
    SourceAgent,
    ThroughputSnapshotFacts,
    TrendReportingGrain,
    TrendSeriesValueState,
    TrendTimezone,
    WorkforceEvidenceFacts,
    assess_delivery_trend,
    finalize_pack_collections,
    reconstruct_client_evidence_pack,
    resolve_reporting_period,
    serialize_client_evidence_pack_for_persistence,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.delivery_trend_contracts import (
    LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE,
    LIMITATION_DEVIATION_POLICY_UNAVAILABLE,
    LIMITATION_PLAN_SERIES_UNAVAILABLE,
    LIMITATION_THROUGHPUT_DATE_GAPS,
    LIMITATION_THROUGHPUT_HISTORY_UNAVAILABLE,
    DeliveryTrendDeviationCandidate,
    DeliveryTrendDeviationResult,
    DeliveryTrendEvidencePeriod,
    DeliveryTrendEvidenceRef,
    canonical_deviation_candidate_key,
)
from app.agents.client_intelligence.evidence_fingerprint import (
    compute_source_fingerprint,
    worst_data_quality_state,
)
from app.db.models import AppRole

_AS_OF = date(2026, 6, 18)
_ORG = UUID("33333333-3333-4333-8333-333333333333")
_TEST_RULES = "test.fixture.delivery_trend.v1"


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


def _throughput_ref(
    row_id: UUID,
    snapshot_date: date,
    *,
    claim_keys: list[str] | None = None,
    visibility: EvidenceVisibility = EvidenceVisibility.INTERNAL,
    units_completed: int | None = 10,
    units_forecast: int | None = 8,
    rolling: int | None = 70,
) -> ClientEvidenceReference:
    if claim_keys is None:
        keys = ["snapshot_date"]
        if units_completed is not None:
            keys.append("units_completed")
        if units_forecast is not None:
            keys.append("units_forecast")
        if rolling is not None:
            keys.append("rolling_7day_units")
    else:
        keys = claim_keys
    return ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="throughput_snapshots",
        source_row_id=row_id,
        description=f"Throughput {snapshot_date.isoformat()}",
        visibility=visibility,
        observed_at=datetime.combine(snapshot_date, datetime.min.time(), tzinfo=UTC),
        claim_keys=keys,
    )


def _throughput_fact(
    row_id: UUID,
    snapshot_date: date,
    *,
    units_completed: int = 10,
    units_forecast: int | None = 8,
    rolling: int | None = 70,
) -> ThroughputSnapshotFacts:
    return ThroughputSnapshotFacts(
        id=row_id,
        snapshot_date=snapshot_date,
        units_completed=units_completed,
        units_forecast=units_forecast,
        rolling_7day_units=rolling,
    )


def _base_pack(
    *,
    visibility_mode: EvidenceVisibility = EvidenceVisibility.INTERNAL,
    throughput_series: list[ThroughputSnapshotFacts] | None = None,
    latest_throughput: ThroughputSnapshotFacts | None = None,
    throughput_dq: DataQualityState | None = DataQualityState.PARTIAL,
    limitations: list[str] | None = None,
) -> ClientEvidencePack:
    pid = uuid4()
    period = resolve_reporting_period(_AS_OF)
    milestone_id = uuid4()
    series = throughput_series or []
    latest = latest_throughput
    if latest is None and series:
        latest = series[-1]
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
    ]
    for row in series:
        refs.append(
            _throughput_ref(
                row.id,
                row.snapshot_date,
                units_completed=row.units_completed,
                units_forecast=row.units_forecast,
                rolling=row.rolling_7day_units,
            )
        )
    if latest is not None and latest.id not in {item.id for item in series}:
        refs.append(
            _throughput_ref(
                latest.id,
                latest.snapshot_date,
                units_completed=latest.units_completed,
                units_forecast=latest.units_forecast,
                rolling=latest.rolling_7day_units,
            )
        )

    dq = [
        DataQualityIssue(source="milestones", state=DataQualityState.COMPLETE, detail="ok"),
    ]
    if throughput_dq is not None:
        dq.append(
            DataQualityIssue(
                source="throughput_snapshots",
                state=throughput_dq,
                detail="throughput quality",
            )
        )
    refs, dq, vis, lim = finalize_pack_collections(
        evidence=refs,
        data_quality=dq,
        visibility_limitations=[],
        limitations=limitations or [],
    )
    delivery = DeliveryEvidenceFacts(
        latest_throughput=latest,
        throughput_series=series,
        milestones=[
            MilestoneFacts(
                id=milestone_id,
                name="Batch",
                planned_date=date(2026, 7, 1),
                status="planned",
            )
        ],
        next_milestone_id=milestone_id,
    )
    project = ProjectIdentityFacts(
        project_id=pid,
        org_id=_ORG,
        project_name="Aurora",
        project_status="active",
    )
    quality = QualityEvidenceFacts(
        current_period=[],
        previous_period=[],
        current_iso_year=2026,
        current_iso_week=25,
        previous_iso_year=2026,
        previous_iso_week=24,
    )
    overall = worst_data_quality_state([item.state for item in dq])
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
        visibility_limitations=vis,
        limitations=lim,
    )


class _FixtureDeviationPolicy:
    def __init__(
        self,
        *,
        mutate=None,
        material: bool = True,
        rules_version: str = _TEST_RULES,
        select_all: bool = True,
    ) -> None:
        self._rules_version = rules_version
        self._mutate = mutate
        self._material = material
        self._select_all = select_all

    @property
    def rules_version(self) -> str:
        return self._rules_version

    def evaluate(self, candidates: DeliveryTrendDeviationCandidateContext):
        selections = []
        for item in candidates.candidates:
            if not self._select_all:
                continue
            selections.append(
                DeliveryTrendDeviationSelection(
                    candidate_key=item.candidate_key,
                    materiality=(
                        DeviationMateriality.MATERIAL
                        if self._material
                        else DeviationMateriality.NOT_MATERIAL
                    ),
                )
            )
        decision = DeliveryTrendDeviationPolicyDecision(
            selections=selections,
            policy_limitations=[],
        )
        if self._mutate is not None:
            decision = self._mutate(candidates, decision)
        return decision


def _series_pack(count: int = 3) -> ClientEvidencePack:
    rows = []
    for offset in range(count):
        snap_date = date(2026, 6, 10 + offset)
        rows.append(
            _throughput_fact(
                uuid4(),
                snap_date,
                units_completed=10 + offset,
                units_forecast=8 + offset,
            )
        )
    return _base_pack(throughput_series=rows, throughput_dq=DataQualityState.COMPLETE)


def _available_assessment() -> DeliveryTrendAssessment:
    return assess_delivery_trend(_series_pack(), policy=_FixtureDeviationPolicy())


def test_internal_multi_row_series() -> None:
    result = assess_delivery_trend(_series_pack(3))
    assert len(result.trend_points) == 3
    assert result.grain == TrendReportingGrain.DAY
    assert result.timezone == TrendTimezone.UTC


def test_deterministic_ascending_order() -> None:
    result = assess_delivery_trend(_series_pack(3))
    dates = [point.snapshot_date for point in result.trend_points]
    assert dates == sorted(dates)


def test_latest_equals_latest_series_member() -> None:
    pack = _series_pack(2)
    assert pack.delivery.latest_throughput is not None
    assert pack.delivery.latest_throughput.id == pack.delivery.throughput_series[-1].id


def test_duplicate_date_rejected_by_pack_validation() -> None:
    row_id = uuid4()
    snap = date(2026, 6, 10)
    dup = [
        _throughput_fact(row_id, snap),
        _throughput_fact(uuid4(), snap),
    ]
    pack = _base_pack(throughput_series=dup)
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_duplicate_row_identity_rejected_by_assessment_contract() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"].append(dict(data["trend_points"][0]))
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_future_snapshot_rejected_by_pack_validation() -> None:
    future = _throughput_fact(uuid4(), date(2027, 1, 1))
    pack = _base_pack(throughput_series=[future])
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_row_before_window_rejected() -> None:
    early = _throughput_fact(uuid4(), date(2020, 1, 1))
    pack = _base_pack(throughput_series=[early])
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_orphan_series_evidence_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    pack = pack.model_copy(update={"evidence": pack.evidence[:-1]})
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_missing_series_evidence_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    extra = ClientEvidenceReference(
        source_agent=SourceAgent.DELIVERY_PERFORMANCE,
        source_table="throughput_snapshots",
        source_row_id=uuid4(),
        description="orphan",
        visibility=EvidenceVisibility.INTERNAL,
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
        claim_keys=["snapshot_date", "units_completed"],
    )
    pack = pack.model_copy(update={"evidence": [*pack.evidence, extra]})
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_wrong_source_agent_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["source_agent"] = "quality_intelligence"
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_wrong_source_table_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["source_table"] = "milestones"
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_wrong_row_id_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["source_row_id"] = uuid4()
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_wrong_fingerprint_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["source_fingerprint"] = "b" * 64
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_wrong_visibility_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["visibility"] = "client_safe"
    data["trend_points"][0]["evidence"][0]["visibility"] = "client_safe"
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_wrong_observed_at_rejected() -> None:
    pack = _series_pack(1)
    refs = []
    for item in pack.evidence:
        if item.source_table == "throughput_snapshots":
            refs.append(item.model_copy(update={"observed_at": datetime(2026, 6, 11, tzinfo=UTC)}))
        else:
            refs.append(item)
    pack = pack.model_copy(update={"evidence": refs})
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_midnight_utc_timestamp_enforced() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    ref = next(item for item in pack.evidence if item.source_table == "throughput_snapshots")
    assert ref.observed_at == datetime(2026, 6, 10, 0, 0, tzinfo=UTC)


def test_actual_from_units_completed_only() -> None:
    result = assess_delivery_trend(_series_pack(1))
    assert result.trend_points[0].actual_units == 10
    assert result.trend_points[0].actual_state == TrendSeriesValueState.OBSERVED


def test_forecast_from_units_forecast_only() -> None:
    result = assess_delivery_trend(_series_pack(1))
    assert result.trend_points[0].forecast_units == 8


def test_rolling_never_substitutes_actual() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_completed=12, rolling=999)
    result = assess_delivery_trend(_base_pack(throughput_series=[row]))
    assert result.trend_points[0].actual_units == 12


def test_rolling_never_substitutes_plan_or_forecast() -> None:
    row = _throughput_fact(
        uuid4(), date(2026, 6, 10), units_forecast=None, rolling=999
    )
    result = assess_delivery_trend(_base_pack(throughput_series=[row]))
    assert result.trend_points[0].forecast_units is None
    assert result.trend_points[0].plan_units is None


def test_plan_always_missing_source() -> None:
    result = assess_delivery_trend(_series_pack(1))
    point = result.trend_points[0]
    assert point.plan_units is None
    assert point.plan_state == TrendSeriesValueState.MISSING_SOURCE
    assert LIMITATION_PLAN_SERIES_UNAVAILABLE in result.limitations


def test_non_none_plan_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["plan_units"] = 5
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_units_plan_evidence_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["evidence"][0]["claim_keys"] = list(data["evidence"][0]["claim_keys"]) + [
        "units_plan"
    ]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_actual_vs_plan_delta_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["delta_actual_plan"] = 1
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_forecast_missing_remains_none() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=None)
    result = assess_delivery_trend(_base_pack(throughput_series=[row]))
    assert result.trend_points[0].forecast_units is None


def test_forecast_missing_no_delta() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=None)
    result = assess_delivery_trend(_base_pack(throughput_series=[row]))
    assert result.trend_points[0].delta_actual_forecast is None


def test_forecast_missing_no_deviation_candidate() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=None)
    result = assess_delivery_trend(
        _base_pack(throughput_series=[row], throughput_dq=DataQualityState.COMPLETE),
        policy=_FixtureDeviationPolicy(),
    )
    assert result.deviations == []


def test_no_synthetic_calendar_dates() -> None:
    rows = [
        _throughput_fact(uuid4(), date(2026, 6, 10)),
        _throughput_fact(uuid4(), date(2026, 6, 12)),
    ]
    result = assess_delivery_trend(_base_pack(throughput_series=rows))
    assert len(result.trend_points) == 2


def test_date_gaps_limitation() -> None:
    rows = [
        _throughput_fact(uuid4(), date(2026, 6, 10)),
        _throughput_fact(uuid4(), date(2026, 6, 12)),
    ]
    result = assess_delivery_trend(_base_pack(throughput_series=rows))
    assert LIMITATION_THROUGHPUT_DATE_GAPS in result.limitations


def test_exact_arithmetic_delta() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_completed=12, units_forecast=7)
    result = assess_delivery_trend(_base_pack(throughput_series=[row]))
    assert result.trend_points[0].delta_actual_forecast == 5


def test_incorrect_delta_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["delta_actual_forecast"] = 999
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_bool_units_rejected_by_contract() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["actual_units"] = True
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_negative_units_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["actual_units"] = -1
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_complete_quality_with_policy() -> None:
    result = assess_delivery_trend(
        _series_pack(1), policy=_FixtureDeviationPolicy()
    )
    assert result.availability == DeliveryTrendAvailability.PARTIAL
    assert result.deviations


def test_partial_quality_behavior() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.PARTIAL,
        )
    )
    assert result.availability == DeliveryTrendAvailability.PARTIAL
    assert result.trend_points


def test_stale_quality_behavior() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.STALE,
        )
    )
    assert result.availability == DeliveryTrendAvailability.STALE


def test_conflicting_quality_fail_closed() -> None:
    pack = _base_pack(
        throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
        throughput_dq=DataQualityState.CONFLICTING,
    )
    result = assess_delivery_trend(pack)
    assert result.availability == DeliveryTrendAvailability.CONFLICTING
    assert result.trend_points == []
    assert result.evidence == []


def test_unavailable_quality_behavior() -> None:
    pack = _base_pack(
        throughput_series=[],
        latest_throughput=None,
        throughput_dq=DataQualityState.UNAVAILABLE,
    )
    result = assess_delivery_trend(pack)
    assert result.availability == DeliveryTrendAvailability.UNAVAILABLE


def test_missing_source_quality_no_complete_fallback() -> None:
    pack = _base_pack(
        throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
        throughput_dq=None,
    )
    result = assess_delivery_trend(pack, policy=_FixtureDeviationPolicy())
    assert result.trend_points[0].data_quality is None
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations
    assert result.deviations == []
    assert result.rules_version is None


def test_plan_absence_keeps_partial() -> None:
    result = assess_delivery_trend(
        _series_pack(1), policy=_FixtureDeviationPolicy()
    )
    assert result.availability == DeliveryTrendAvailability.PARTIAL


def test_empty_pack() -> None:
    result = assess_delivery_trend(_base_pack())
    assert result.trend_points == []
    assert result.availability == DeliveryTrendAvailability.UNAVAILABLE


def test_legacy_latest_only_pack() -> None:
    latest = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(latest_throughput=latest, throughput_series=[])
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    assert result.is_valid
    trend = assess_delivery_trend(pack)
    assert len(trend.trend_points) == 1
    assert LIMITATION_THROUGHPUT_HISTORY_UNAVAILABLE in trend.limitations


def test_client_safe_fail_closed() -> None:
    result = assess_delivery_trend(_base_pack(visibility_mode=EvidenceVisibility.CLIENT_SAFE))
    assert result.availability == DeliveryTrendAvailability.UNAVAILABLE
    assert result.trend_points == []


def test_missing_policy_no_material_deviation() -> None:
    result = assess_delivery_trend(_series_pack(1))
    assert result.deviations == []
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE in result.limitations
    assert result.rules_version is None


def test_valid_policy_classifies_candidate() -> None:
    result = assess_delivery_trend(_series_pack(1), policy=_FixtureDeviationPolicy())
    assert result.deviations
    assert result.deviations[0].materiality == DeviationMateriality.MATERIAL
    assert result.rules_version == _TEST_RULES


def test_unknown_candidate_rejected() -> None:
    pack = _series_pack(1)

    def _mutate(candidates, decision):
        del candidates
        return decision.model_copy(
            update={
                "selections": [
                    DeliveryTrendDeviationSelection(
                        candidate_key="throughput.deadbeefdeadbeefdeadbeefdeadbeef.20260610",
                        materiality=DeviationMateriality.MATERIAL,
                    )
                ]
            }
        )

    with pytest.raises(DeliveryTrendIntegrityError):
        assess_delivery_trend(pack, policy=_FixtureDeviationPolicy(mutate=_mutate))


def test_duplicate_policy_selection_rejected() -> None:
    from app.agents.client_intelligence.delivery_trend_contracts import (
        DeliveryTrendDeviationPolicyDecision,
    )

    key = canonical_deviation_candidate_key(
        _series_pack(1).delivery.throughput_series[0].id,
        date(2026, 6, 10),
    )
    with pytest.raises(ValidationError):
        DeliveryTrendDeviationPolicyDecision(
            selections=[
                DeliveryTrendDeviationSelection(
                    candidate_key=key, materiality=DeviationMateriality.MATERIAL
                ),
                DeliveryTrendDeviationSelection(
                    candidate_key=key, materiality=DeviationMateriality.NOT_MATERIAL
                ),
            ]
        )


def test_policy_cannot_change_values() -> None:
    pack = _series_pack(1)
    original = assess_delivery_trend(pack, policy=_FixtureDeviationPolicy())
    assert original.trend_points[0].actual_units == 10


def test_policy_mutation_isolation() -> None:
    pack = _series_pack(1)
    original_fp = pack.source_fingerprint

    class _Mutate(_FixtureDeviationPolicy):
        def evaluate(self, candidates):
            decision = super().evaluate(candidates)
            for item in candidates.candidates:
                item.actual_units = 1
                item.forecast_units = 1
                item.delta_actual_forecast = 0
            return decision

    result = assess_delivery_trend(pack, policy=_Mutate())
    assert result.source_fingerprint == original_fp
    assert result.trend_points[0].actual_units == 10


def test_policy_exception_sanitized() -> None:
    secret = "SECRET_deviation_policy"

    class _Hostile(_FixtureDeviationPolicy):
        def evaluate(self, candidates):
            raise RuntimeError(secret)

    with pytest.raises(DeliveryTrendIntegrityError) as exc:
        assess_delivery_trend(_series_pack(1), policy=_Hostile())
    assert secret not in str(exc.value)


def test_invalid_rules_version_rejected() -> None:
    with pytest.raises(DeliveryTrendIntegrityError):
        assess_delivery_trend(
            _series_pack(1), policy=_FixtureDeviationPolicy(rules_version="   ")
        )


def test_candidate_key_bound_to_row_and_date() -> None:
    pack = _series_pack(1)
    row = pack.delivery.throughput_series[0]
    expected = canonical_deviation_candidate_key(row.id, row.snapshot_date)
    result = assess_delivery_trend(pack, policy=_FixtureDeviationPolicy())
    assert result.deviations[0].candidate_key == expected


def test_top_level_evidence_exact_union() -> None:
    result = assess_delivery_trend(_series_pack(2), policy=_FixtureDeviationPolicy())
    for point in result.trend_points:
        for ref in point.evidence:
            assert (str(ref.source_row_id), tuple(ref.claim_keys)) in {
                (str(r.source_row_id), tuple(r.claim_keys)) for r in result.evidence
            }


def test_orphan_top_level_evidence_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    orphan = dict(data["evidence"][0])
    orphan["source_row_id"] = uuid4()
    data["evidence"].append(orphan)
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_missing_top_level_claim_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["evidence"][0]["claim_keys"] = ["snapshot_date"]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_extra_top_level_claim_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["evidence"][0]["claim_keys"] = list(data["evidence"][0]["claim_keys"]) + [
        "extra_claim"
    ]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_source_limitations_separate() -> None:
    note = "Adapter throughput note."
    pack = _series_pack(1)
    pack = pack.model_copy(
        update={
            "limitations": [note, *pack.limitations],
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
                limitations=[note, *pack.limitations],
            ),
        }
    )
    result = assess_delivery_trend(pack, policy=_FixtureDeviationPolicy())
    assert note in result.source_limitations
    assert note not in result.limitations


def test_deterministic_serialization() -> None:
    pack = _series_pack(2)
    policy = _FixtureDeviationPolicy()
    first = assess_delivery_trend(pack, policy=policy)
    second = assess_delivery_trend(pack, policy=policy)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_fingerprint_changes_when_series_changes() -> None:
    base = _series_pack(1)
    other = _base_pack(
        throughput_series=[
            _throughput_fact(uuid4(), date(2026, 6, 11), units_completed=99)
        ],
        throughput_dq=DataQualityState.COMPLETE,
    )
    assert base.source_fingerprint != other.source_fingerprint


def test_persistence_reconstruction_valid() -> None:
    pack = _series_pack(2)
    payload = serialize_client_evidence_pack_for_persistence(pack)
    rebuilt = reconstruct_client_evidence_pack(payload)
    assert len(rebuilt.delivery.throughput_series) == 2
    result = validate_client_evidence_pack(rebuilt, role=AppRole.DELIVERY_MANAGER)
    assert result.is_valid


def test_persistence_reconstruction_rejects_tampered_series() -> None:
    pack = _series_pack(1)
    payload = serialize_client_evidence_pack_for_persistence(pack)
    payload["delivery"]["throughput_series"][0]["units_completed"] = 9999
    rebuilt = reconstruct_client_evidence_pack(payload)
    result = validate_client_evidence_pack(rebuilt, role=AppRole.DELIVERY_MANAGER)
    assert not result.is_valid


def test_policy_context_only_signature() -> None:
    params = list(inspect.signature(_FixtureDeviationPolicy.evaluate).parameters.keys())
    assert params == ["self", "candidates"]


def test_available_assessment_never_available_without_plan() -> None:
    with pytest.raises(ValidationError):
        data = _available_assessment().model_dump(mode="python")
        data["availability"] = DeliveryTrendAvailability.AVAILABLE.value
        DeliveryTrendAssessment.model_validate(data)


# --- TASK 13 acceptance: pack claim binding, contract closure, provenance ---


def test_pack_omits_units_forecast_claim_when_forecast_none() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=None)
    pack = _base_pack(throughput_series=[row])
    ref = next(r for r in pack.evidence if r.source_row_id == row.id)
    assert "units_forecast" not in ref.claim_keys
    assert validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_pack_omits_rolling_claim_when_rolling_none() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), rolling=None)
    pack = _base_pack(throughput_series=[row])
    ref = next(r for r in pack.evidence if r.source_row_id == row.id)
    assert "rolling_7day_units" not in ref.claim_keys
    assert validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_pack_present_forecast_without_claim_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=8)
    pack = _base_pack(throughput_series=[row])
    refs = [
        (
            r.model_copy(
                update={
                    "claim_keys": [
                        "snapshot_date",
                        "units_completed",
                        "rolling_7day_units",
                    ]
                }
            )
            if r.source_row_id == row.id
            else r
        )
        for r in pack.evidence
    ]
    pack = pack.model_copy(update={"evidence": refs})
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_pack_none_forecast_with_claim_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=None)
    pack = _base_pack(throughput_series=[row])
    refs = [
        (
            r.model_copy(
                update={
                    "claim_keys": [
                        "snapshot_date",
                        "units_completed",
                        "units_forecast",
                        "rolling_7day_units",
                    ]
                }
            )
            if r.source_row_id == row.id
            else r
        )
        for r in pack.evidence
    ]
    pack = pack.model_copy(update={"evidence": refs})
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_pack_present_rolling_without_claim_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), rolling=70)
    pack = _base_pack(throughput_series=[row])
    refs = [
        (
            r.model_copy(
                update={"claim_keys": ["snapshot_date", "units_completed", "units_forecast"]}
            )
            if r.source_row_id == row.id
            else r
        )
        for r in pack.evidence
    ]
    pack = pack.model_copy(update={"evidence": refs})
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_pack_none_rolling_with_claim_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), rolling=None)
    pack = _base_pack(throughput_series=[row])
    refs = [
        (
            r.model_copy(
                update={
                    "claim_keys": [
                        "snapshot_date",
                        "units_completed",
                        "units_forecast",
                        "rolling_7day_units",
                    ]
                }
            )
            if r.source_row_id == row.id
            else r
        )
        for r in pack.evidence
    ]
    pack = pack.model_copy(update={"evidence": refs})
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_latest_same_id_different_date_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    latest = row.model_copy(update={"snapshot_date": date(2026, 6, 11)})
    pack = pack.model_copy(
        update={"delivery": pack.delivery.model_copy(update={"latest_throughput": latest})}
    )
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_latest_same_id_different_actual_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    latest = row.model_copy(update={"units_completed": 99})
    pack = pack.model_copy(
        update={"delivery": pack.delivery.model_copy(update={"latest_throughput": latest})}
    )
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_latest_same_id_different_forecast_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    latest = row.model_copy(update={"units_forecast": 99})
    pack = pack.model_copy(
        update={"delivery": pack.delivery.model_copy(update={"latest_throughput": latest})}
    )
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_latest_same_id_different_rolling_rejected() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10))
    pack = _base_pack(throughput_series=[row])
    latest = row.model_copy(update={"rolling_7day_units": 1})
    pack = pack.model_copy(
        update={"delivery": pack.delivery.model_copy(update={"latest_throughput": latest})}
    )
    assert not validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER).is_valid


def test_missing_source_quality_remains_none_not_unavailable() -> None:
    pack = _base_pack(
        throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
        throughput_dq=None,
    )
    result = assess_delivery_trend(pack)
    assert result.trend_points[0].data_quality is None
    assert result.trend_points[0].data_quality != DataQualityState.UNAVAILABLE
    assert result.trend_points[0].data_quality != DataQualityState.COMPLETE


def test_missing_source_quality_never_complete() -> None:
    pack = _base_pack(
        throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
        throughput_dq=None,
    )
    result = assess_delivery_trend(pack, policy=_FixtureDeviationPolicy())
    assert all(p.data_quality is None for p in result.trend_points)
    assert result.deviations == []


def test_point_missing_plan_limitation_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["limitations"] = [
        x for x in data["trend_points"][0]["limitations"] if x != LIMITATION_PLAN_SERIES_UNAVAILABLE
    ]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_missing_forecast_point_requires_forecast_limitation() -> None:
    row = _throughput_fact(uuid4(), date(2026, 6, 10), units_forecast=None)
    result = assess_delivery_trend(_base_pack(throughput_series=[row]))
    data = result.model_dump(mode="python")
    data["trend_points"][0]["limitations"] = [LIMITATION_PLAN_SERIES_UNAVAILABLE]
    data["limitations"] = [
        x for x in data["limitations"] if x != "FORECAST_VALUE_MISSING"
    ]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_observed_forecast_cannot_carry_forecast_missing_limitation() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["limitations"] = sorted(
        {
            *data["trend_points"][0]["limitations"],
            "FORECAST_VALUE_MISSING",
        }
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_rolling_claim_in_point_evidence_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["evidence"][0]["claim_keys"] = sorted(
        {*data["trend_points"][0]["evidence"][0]["claim_keys"], "rolling_7day_units"}
    )
    data["evidence"][0]["claim_keys"] = sorted(
        {*data["evidence"][0]["claim_keys"], "rolling_7day_units"}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_rolling_claim_consistently_added_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    for bucket in (data["trend_points"][0]["evidence"], data["evidence"]):
        for ref in bucket:
            ref["claim_keys"] = sorted({*ref["claim_keys"], "rolling_7day_units"})
    if data["deviations"]:
        for ref in data["deviations"][0]["evidence"]:
            ref["claim_keys"] = sorted({*ref["claim_keys"], "rolling_7day_units"})
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_consistent_timestamp_shift_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    shifted = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    for ref in data["trend_points"][0]["evidence"]:
        ref["observed_at"] = shifted
    for ref in data["evidence"]:
        if ref["source_row_id"] == data["trend_points"][0]["source_row_id"]:
            ref["observed_at"] = shifted
    if data["deviations"]:
        for ref in data["deviations"][0]["evidence"]:
            ref["observed_at"] = shifted
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_offset_equivalent_noncanonical_timestamp_rejected() -> None:
    from datetime import timedelta, timezone

    data = _available_assessment().model_dump(mode="python")
    point_date = data["trend_points"][0]["snapshot_date"]
    if isinstance(point_date, str):
        point_date = date.fromisoformat(point_date)
    noncanonical = datetime(
        point_date.year,
        point_date.month,
        point_date.day,
        0,
        0,
        tzinfo=timezone(timedelta(0), name="Etc/GMT"),
    )
    for ref in data["trend_points"][0]["evidence"]:
        ref["observed_at"] = noncanonical
    for ref in data["evidence"]:
        if ref["source_row_id"] == data["trend_points"][0]["source_row_id"]:
            ref["observed_at"] = noncanonical
    if data["deviations"]:
        for ref in data["deviations"][0]["evidence"]:
            ref["observed_at"] = noncanonical
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_fabricated_covered_start_date_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["covered_start_date"] = data["as_of"]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_covered_end_date_must_equal_as_of() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["covered_end_date"] = date(2026, 6, 17)
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_point_outside_assessment_window_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["snapshot_date"] = date(2026, 5, 1)
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_reversed_point_ordering_rejected() -> None:
    result = assess_delivery_trend(_series_pack(2), policy=_FixtureDeviationPolicy())
    data = result.model_dump(mode="python")
    data["trend_points"] = list(reversed(data["trend_points"]))
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_duplicate_point_date_rejected() -> None:
    result = assess_delivery_trend(_series_pack(2), policy=_FixtureDeviationPolicy())
    data = result.model_dump(mode="python")
    data["trend_points"][1]["snapshot_date"] = data["trend_points"][0]["snapshot_date"]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_reversed_deviation_ordering_rejected() -> None:
    result = assess_delivery_trend(_series_pack(2), policy=_FixtureDeviationPolicy())
    assert len(result.deviations) >= 2
    data = result.model_dump(mode="python")
    data["deviations"] = list(reversed(data["deviations"]))
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_duplicate_deviation_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["deviations"].append(data["deviations"][0])
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_deviation_without_rules_version_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["rules_version"] = None
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_changed_deviation_actual_forecast_delta_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["deviations"][0]["actual_units"] = data["deviations"][0]["actual_units"] + 5
    data["deviations"][0]["delta_actual_forecast"] = (
        data["deviations"][0]["actual_units"] - data["deviations"][0]["forecast_units"]
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_deviation_without_matching_point_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"] = []
    data["evidence"] = data["deviations"][0]["evidence"]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_deviation_wrong_point_date_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    row_id = data["deviations"][0]["source_row_id"]
    if isinstance(row_id, str):
        row_id = UUID(row_id)
    data["deviations"][0]["snapshot_date"] = date(2026, 6, 11)
    data["deviations"][0]["candidate_key"] = canonical_deviation_candidate_key(
        row_id,
        date(2026, 6, 11),
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_deviation_wrong_evidence_rejected() -> None:
    result = assess_delivery_trend(_series_pack(2), policy=_FixtureDeviationPolicy())
    data = result.model_dump(mode="python")
    other = data["trend_points"][1]["evidence"][0]
    data["deviations"][0]["evidence"] = [other]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_deviation_candidate_wrong_agent_table_rejected() -> None:
    result = assess_delivery_trend(_series_pack(1), policy=_FixtureDeviationPolicy())
    point = result.trend_points[0]
    with pytest.raises(ValidationError):
        DeliveryTrendDeviationCandidate(
            candidate_key=canonical_deviation_candidate_key(
                point.source_row_id, point.snapshot_date
            ),
            source_row_id=point.source_row_id,
            snapshot_date=point.snapshot_date,
            actual_units=point.actual_units or 0,
            forecast_units=point.forecast_units or 0,
            delta_actual_forecast=point.delta_actual_forecast or 0,
            data_quality=DataQualityState.COMPLETE,
            visibility=point.visibility,
            source_fingerprint=point.source_fingerprint,
            evidence=[
                DeliveryTrendEvidenceRef(
                    source_agent=SourceAgent.QUALITY_INTELLIGENCE,
                    source_table="defects",
                    source_row_id=point.source_row_id,
                    visibility=point.visibility,
                    claim_keys=["snapshot_date", "units_completed", "units_forecast"],
                    period=DeliveryTrendEvidencePeriod.CURRENT,
                    source_fingerprint=point.source_fingerprint,
                    observed_at=point.evidence[0].observed_at,
                )
            ],
        )


def test_deviation_candidate_wrong_timestamp_rejected() -> None:
    result = assess_delivery_trend(_series_pack(1), policy=_FixtureDeviationPolicy())
    point = result.trend_points[0]
    bad_ref = point.evidence[0].model_copy(
        update={"observed_at": datetime(2026, 6, 10, 15, 0, tzinfo=UTC)}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendDeviationCandidate(
            candidate_key=canonical_deviation_candidate_key(
                point.source_row_id, point.snapshot_date
            ),
            source_row_id=point.source_row_id,
            snapshot_date=point.snapshot_date,
            actual_units=point.actual_units or 0,
            forecast_units=point.forecast_units or 0,
            delta_actual_forecast=point.delta_actual_forecast or 0,
            data_quality=DataQualityState.COMPLETE,
            visibility=point.visibility,
            source_fingerprint=point.source_fingerprint,
            evidence=[bad_ref],
        )


def test_deviation_candidate_rolling_claim_rejected() -> None:
    result = assess_delivery_trend(_series_pack(1), policy=_FixtureDeviationPolicy())
    point = result.trend_points[0]
    bad_ref = point.evidence[0].model_copy(
        update={
            "claim_keys": sorted(
                {*point.evidence[0].claim_keys, "rolling_7day_units"}
            )
        }
    )
    with pytest.raises(ValidationError):
        DeliveryTrendDeviationCandidate(
            candidate_key=canonical_deviation_candidate_key(
                point.source_row_id, point.snapshot_date
            ),
            source_row_id=point.source_row_id,
            snapshot_date=point.snapshot_date,
            actual_units=point.actual_units or 0,
            forecast_units=point.forecast_units or 0,
            delta_actual_forecast=point.delta_actual_forecast or 0,
            data_quality=DataQualityState.COMPLETE,
            visibility=point.visibility,
            source_fingerprint=point.source_fingerprint,
            evidence=[bad_ref],
        )


def test_deviation_result_wrong_agent_table_rejected() -> None:
    result = assess_delivery_trend(_series_pack(1), policy=_FixtureDeviationPolicy())
    deviation = result.deviations[0]
    with pytest.raises(ValidationError):
        DeliveryTrendDeviationResult(
            candidate_key=deviation.candidate_key,
            source_row_id=deviation.source_row_id,
            snapshot_date=deviation.snapshot_date,
            actual_units=deviation.actual_units,
            forecast_units=deviation.forecast_units,
            delta_actual_forecast=deviation.delta_actual_forecast,
            materiality=deviation.materiality,
            data_quality=DataQualityState.COMPLETE,
            visibility=deviation.visibility,
            source_fingerprint=deviation.source_fingerprint,
            evidence=[
                DeliveryTrendEvidenceRef(
                    source_agent=SourceAgent.QUALITY_INTELLIGENCE,
                    source_table="defects",
                    source_row_id=deviation.source_row_id,
                    visibility=deviation.visibility,
                    claim_keys=["snapshot_date", "units_completed", "units_forecast"],
                    period=DeliveryTrendEvidencePeriod.CURRENT,
                    source_fingerprint=deviation.source_fingerprint,
                    observed_at=deviation.evidence[0].observed_at,
                )
            ],
        )


def test_missing_policy_requires_deviation_policy_unavailable() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.COMPLETE,
        )
    )
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE in result.limitations
    assert result.rules_version is None
    assert result.deviations == []


def test_evaluated_policy_rejects_contradictory_policy_unavailable() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["limitations"] = sorted(
        {*data["limitations"], LIMITATION_DEVIATION_POLICY_UNAVAILABLE}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_policy_supplied_partial_source_not_evaluated() -> None:
    class TrackingPolicy(_FixtureDeviationPolicy):
        called = False

        @property
        def rules_version(self) -> str:
            type(self).called = True
            return _TEST_RULES

        def evaluate(self, candidates):  # type: ignore[no-untyped-def]
            type(self).called = True
            return super().evaluate(candidates)

    TrackingPolicy.called = False
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.PARTIAL,
        ),
        policy=TrackingPolicy(),
    )
    assert TrackingPolicy.called is False
    assert result.rules_version is None
    assert result.deviations == []
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE not in result.limitations


def test_policy_supplied_stale_source_not_evaluated() -> None:
    class TrackingPolicy(_FixtureDeviationPolicy):
        called = False

        @property
        def rules_version(self) -> str:
            type(self).called = True
            return _TEST_RULES

        def evaluate(self, candidates):  # type: ignore[no-untyped-def]
            type(self).called = True
            return super().evaluate(candidates)

    TrackingPolicy.called = False
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.STALE,
        ),
        policy=TrackingPolicy(),
    )
    assert TrackingPolicy.called is False
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations


def test_policy_supplied_missing_quality_not_evaluated() -> None:
    class TrackingPolicy(_FixtureDeviationPolicy):
        called = False

        @property
        def rules_version(self) -> str:
            type(self).called = True
            return _TEST_RULES

        def evaluate(self, candidates):  # type: ignore[no-untyped-def]
            type(self).called = True
            return super().evaluate(candidates)

    TrackingPolicy.called = False
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=None,
        ),
        policy=TrackingPolicy(),
    )
    assert TrackingPolicy.called is False
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations


def test_unreliable_source_uses_not_evaluated_limitation() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.PARTIAL,
        ),
        policy=_FixtureDeviationPolicy(),
    )
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations


def test_malicious_policy_cannot_mutate_original_pack() -> None:
    pack = _series_pack(1)
    original_completed = pack.delivery.throughput_series[0].units_completed
    original_fp = pack.source_fingerprint
    held = {"pack": pack}

    class MutatingPolicy(_FixtureDeviationPolicy):
        def evaluate(self, candidates):  # type: ignore[no-untyped-def]
            decision = super().evaluate(candidates)
            owned = held["pack"]
            owned.delivery.throughput_series[0] = owned.delivery.throughput_series[
                0
            ].model_copy(update={"units_completed": 999999})
            owned.source_fingerprint = "b" * 64
            for item in candidates.candidates:
                item.actual_units = 1
                item.forecast_units = 1
                item.delta_actual_forecast = 0
            return decision

    result = assess_delivery_trend(pack, policy=MutatingPolicy())
    assert result.source_fingerprint == original_fp
    assert result.trend_points[0].actual_units == original_completed
    assert result.deviations[0].actual_units == original_completed


def test_partial_assessment_point_quality_consistency() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[
                _throughput_fact(uuid4(), date(2026, 6, 10)),
                _throughput_fact(uuid4(), date(2026, 6, 11)),
            ],
            throughput_dq=DataQualityState.PARTIAL,
        )
    )
    qualities = {point.data_quality for point in result.trend_points}
    assert qualities == {DataQualityState.PARTIAL}


def test_stale_assessment_rejects_complete_point() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.STALE,
        )
    )
    data = result.model_dump(mode="python")
    data["trend_points"][0]["data_quality"] = DataQualityState.COMPLETE.value
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_partial_assessment_rejects_mixed_point_quality() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[
                _throughput_fact(uuid4(), date(2026, 6, 10)),
                _throughput_fact(uuid4(), date(2026, 6, 11)),
            ],
            throughput_dq=DataQualityState.PARTIAL,
        )
    )
    data = result.model_dump(mode="python")
    data["trend_points"][1]["data_quality"] = DataQualityState.COMPLETE.value
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_unavailable_point_quality_cannot_be_published() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["trend_points"][0]["data_quality"] = DataQualityState.UNAVAILABLE.value
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_top_level_rolling_claim_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    data["evidence"][0]["claim_keys"] = sorted(
        {*data["evidence"][0]["claim_keys"], "rolling_7day_units"}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_exact_point_deviation_top_level_union_remains_valid() -> None:
    result = assess_delivery_trend(_series_pack(2), policy=_FixtureDeviationPolicy())
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))
    assert result.deviations
    assert result.evidence
    assert result.trend_points


def test_strip_all_point_limitations_rejected() -> None:
    data = _available_assessment().model_dump(mode="python")
    for point in data["trend_points"]:
        point["limitations"] = []
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


# --- Final policy-provenance contract closure ---


def test_missing_policy_code_cannot_be_removed() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.COMPLETE,
        ),
        policy=None,
    )
    assert result.rules_version is None
    assert result.deviations == []
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE in result.limitations
    data = result.model_dump(mode="python")
    data["limitations"] = [
        item
        for item in data["limitations"]
        if item != LIMITATION_DEVIATION_POLICY_UNAVAILABLE
    ]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_missing_policy_with_unavailable_code_valid() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.COMPLETE,
        ),
        policy=None,
    )
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE in result.limitations
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE not in result.limitations


def test_rules_version_none_neither_provenance_code_rejected() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.COMPLETE,
        ),
        policy=None,
    )
    data = result.model_dump(mode="python")
    data["limitations"] = [
        item
        for item in data["limitations"]
        if item
        not in {
            LIMITATION_DEVIATION_POLICY_UNAVAILABLE,
            LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE,
        }
    ]
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_rules_version_none_both_provenance_codes_rejected() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.COMPLETE,
        ),
        policy=None,
    )
    data = result.model_dump(mode="python")
    data["limitations"] = sorted(
        {
            *data["limitations"],
            LIMITATION_DEVIATION_POLICY_UNAVAILABLE,
            LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE,
        }
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_partial_points_not_evaluated_provenance_valid() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.PARTIAL,
        ),
        policy=_FixtureDeviationPolicy(),
    )
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE not in result.limitations
    assert result.rules_version is None


def test_stale_points_not_evaluated_provenance_valid() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.STALE,
        ),
        policy=_FixtureDeviationPolicy(),
    )
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations


def test_missing_quality_points_not_evaluated_provenance_valid() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=None,
        ),
        policy=_FixtureDeviationPolicy(),
    )
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in result.limitations
    assert all(point.data_quality is None for point in result.trend_points)


def test_complete_points_reject_not_evaluated_code() -> None:
    result = assess_delivery_trend(
        _base_pack(
            throughput_series=[_throughput_fact(uuid4(), date(2026, 6, 10))],
            throughput_dq=DataQualityState.COMPLETE,
        ),
        policy=None,
    )
    data = result.model_dump(mode="python")
    data["limitations"] = sorted(
        {
            *(
                item
                for item in data["limitations"]
                if item != LIMITATION_DEVIATION_POLICY_UNAVAILABLE
            ),
            LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE,
        }
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_evaluated_zero_selection_policy_remains_valid() -> None:
    result = assess_delivery_trend(
        _series_pack(1),
        policy=_FixtureDeviationPolicy(select_all=False),
    )
    assert result.rules_version == _TEST_RULES
    assert result.deviations == []
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE not in result.limitations
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE not in result.limitations
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))


def test_evaluated_zero_selection_rejects_policy_unavailable() -> None:
    result = assess_delivery_trend(
        _series_pack(1),
        policy=_FixtureDeviationPolicy(select_all=False),
    )
    data = result.model_dump(mode="python")
    data["limitations"] = sorted(
        {*data["limitations"], LIMITATION_DEVIATION_POLICY_UNAVAILABLE}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_evaluated_zero_selection_rejects_not_evaluated_code() -> None:
    result = assess_delivery_trend(
        _series_pack(1),
        policy=_FixtureDeviationPolicy(select_all=False),
    )
    data = result.model_dump(mode="python")
    data["limitations"] = sorted(
        {*data["limitations"], LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_evaluated_with_deviations_rejects_contradictory_codes() -> None:
    data = _available_assessment().model_dump(mode="python")
    assert data["deviations"]
    data["limitations"] = sorted(
        {*data["limitations"], LIMITATION_DEVIATION_POLICY_UNAVAILABLE}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)
    data = _available_assessment().model_dump(mode="python")
    data["limitations"] = sorted(
        {*data["limitations"], LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE}
    )
    with pytest.raises(ValidationError):
        DeliveryTrendAssessment.model_validate(data)


def test_empty_unavailable_assessment_needs_no_policy_code() -> None:
    result = assess_delivery_trend(
        _base_pack(throughput_series=[], throughput_dq=DataQualityState.UNAVAILABLE)
    )
    assert result.availability == DeliveryTrendAvailability.UNAVAILABLE
    assert result.trend_points == []
    assert result.deviations == []
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE not in result.limitations
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE not in result.limitations
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))


def test_client_safe_empty_assessment_needs_no_policy_code() -> None:
    result = assess_delivery_trend(
        _base_pack(visibility_mode=EvidenceVisibility.CLIENT_SAFE)
    )
    assert result.availability == DeliveryTrendAvailability.UNAVAILABLE
    assert result.trend_points == []
    assert LIMITATION_DEVIATION_POLICY_UNAVAILABLE not in result.limitations
    assert LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE not in result.limitations
    DeliveryTrendAssessment.model_validate(result.model_dump(mode="python"))
