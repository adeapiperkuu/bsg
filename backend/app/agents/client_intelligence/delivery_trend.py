"""Deterministic Delivery Trend Intelligence foundation (roadmap 8.4).

Produces aligned actual/plan/forecast points from governed pack throughput
series. No plan source exists. No production deviation policy is defined.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityState,
    EvidenceVisibility,
    ThroughputSnapshotFacts,
)
from app.agents.client_intelligence.delivery_trend_contracts import (
    LIMITATION_ACTUAL_SERIES_NOT_CLIENT_VISIBLE,
    LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE,
    LIMITATION_DEVIATION_POLICY_UNAVAILABLE,
    LIMITATION_FORECAST_SERIES_NOT_CLIENT_VISIBLE,
    LIMITATION_FORECAST_VALUE_MISSING,
    LIMITATION_PLAN_SERIES_UNAVAILABLE,
    LIMITATION_THROUGHPUT_DATE_GAPS,
    LIMITATION_THROUGHPUT_HISTORY_UNAVAILABLE,
    DeliveryTrendAssessment,
    DeliveryTrendAvailability,
    DeliveryTrendDeviationCandidate,
    DeliveryTrendDeviationCandidateContext,
    DeliveryTrendDeviationPolicyDecision,
    DeliveryTrendDeviationResult,
    DeliveryTrendEvidencePeriod,
    DeliveryTrendEvidenceRef,
    DeliveryTrendPoint,
    TrendReportingGrain,
    TrendSeriesValueState,
    TrendTimezone,
    _canonicalize_source_limitations,
    canonical_deviation_candidate_key,
    require_rules_version,
)
from app.agents.client_intelligence.delivery_trend_policy import (
    DeliveryTrendDeviationPolicy,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    validate_client_evidence_pack,
)
from app.db.models import AppRole

LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS = (
    "SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS"
)
LIMITATION_SOURCE_QUALITY_STALE_THROUGHPUT_SNAPSHOTS = (
    "SOURCE_QUALITY_STALE_THROUGHPUT_SNAPSHOTS"
)
LIMITATION_SOURCE_QUALITY_CONFLICTING_THROUGHPUT_SNAPSHOTS = (
    "SOURCE_QUALITY_CONFLICTING_THROUGHPUT_SNAPSHOTS"
)
LIMITATION_SOURCE_QUALITY_PARTIAL_THROUGHPUT_SNAPSHOTS = (
    "SOURCE_QUALITY_PARTIAL_THROUGHPUT_SNAPSHOTS"
)
LIMITATION_SOURCE_QUALITY_UNAVAILABLE_THROUGHPUT_SNAPSHOTS = (
    "SOURCE_QUALITY_UNAVAILABLE_THROUGHPUT_SNAPSHOTS"
)

_RELIABLE_DEVIATION_QUALITY = frozenset({DataQualityState.COMPLETE})
_QUALITY_STATE_LIMITATIONS: dict[DataQualityState, str] = {
    DataQualityState.STALE: LIMITATION_SOURCE_QUALITY_STALE_THROUGHPUT_SNAPSHOTS,
    DataQualityState.CONFLICTING: LIMITATION_SOURCE_QUALITY_CONFLICTING_THROUGHPUT_SNAPSHOTS,
    DataQualityState.PARTIAL: LIMITATION_SOURCE_QUALITY_PARTIAL_THROUGHPUT_SNAPSHOTS,
    DataQualityState.UNAVAILABLE: LIMITATION_SOURCE_QUALITY_UNAVAILABLE_THROUGHPUT_SNAPSHOTS,
}


class DeliveryTrendIntegrityError(Exception):
    """Deterministic Delivery Trend integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def assess_delivery_trend(
    pack: ClientEvidencePack,
    *,
    policy: DeliveryTrendDeviationPolicy | None = None,
    assessed_at: datetime | None = None,
) -> DeliveryTrendAssessment:
    """Build a Delivery Trend assessment from a validated evidence pack."""
    working = pack.model_copy(deep=True)
    _validate_pack_or_raise(working)

    source_limitations = _canonicalize_source_limitations(list(working.limitations))
    limitations: list[str] = [LIMITATION_PLAN_SERIES_UNAVAILABLE]
    core_org_id = working.project.org_id
    core_project_id = working.project.project_id
    core_as_of = working.reporting_period.as_of
    core_start = working.reporting_period.previous_start_date
    core_visibility = working.visibility_mode
    core_source_fingerprint = working.source_fingerprint
    core_assessed_at = assessed_at if assessed_at is not None else working.generated_at
    if core_assessed_at.tzinfo is None:
        raise DeliveryTrendIntegrityError(
            "invalid_policy_decision",
            "assessed_at must be timezone-aware.",
        )

    throughput_quality = _resolve_source_quality(working)
    limitations.extend(
        _quality_limitations(
            throughput_quality, facts_present=_has_throughput_facts(working)
        )
    )

    if core_visibility == EvidenceVisibility.CLIENT_SAFE:
        limitations.extend(
            [
                LIMITATION_ACTUAL_SERIES_NOT_CLIENT_VISIBLE,
                LIMITATION_FORECAST_SERIES_NOT_CLIENT_VISIBLE,
            ]
        )
        return DeliveryTrendAssessment(
            org_id=core_org_id,
            project_id=core_project_id,
            as_of=core_as_of,
            covered_start_date=core_start,
            covered_end_date=core_as_of,
            grain=TrendReportingGrain.DAY,
            timezone=TrendTimezone.UTC,
            visibility_mode=core_visibility,
            availability=DeliveryTrendAvailability.UNAVAILABLE,
            trend_points=[],
            deviations=[],
            evidence=[],
            limitations=_canonicalize_strings(limitations),
            source_limitations=source_limitations,
            source_fingerprint=core_source_fingerprint,
            rules_version=None,
            assessed_at=core_assessed_at,
        )

    source_rows = _resolve_source_rows(working)
    if throughput_quality == DataQualityState.CONFLICTING:
        return _empty_assessment(
            org_id=core_org_id,
            project_id=core_project_id,
            as_of=core_as_of,
            covered_start_date=core_start,
            covered_end_date=core_as_of,
            visibility_mode=core_visibility,
            availability=DeliveryTrendAvailability.CONFLICTING,
            limitations=limitations,
            source_limitations=source_limitations,
            source_fingerprint=core_source_fingerprint,
            assessed_at=core_assessed_at,
        )

    if not source_rows:
        if throughput_quality == DataQualityState.UNAVAILABLE:
            availability = DeliveryTrendAvailability.UNAVAILABLE
        else:
            availability = DeliveryTrendAvailability.UNAVAILABLE
        return _empty_assessment(
            org_id=core_org_id,
            project_id=core_project_id,
            as_of=core_as_of,
            covered_start_date=core_start,
            covered_end_date=core_as_of,
            visibility_mode=core_visibility,
            availability=availability,
            limitations=limitations,
            source_limitations=source_limitations,
            source_fingerprint=core_source_fingerprint,
            assessed_at=core_assessed_at,
        )

    if throughput_quality is None:
        limitations.append(LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS)

    legacy_only = (
        not working.delivery.throughput_series
        and working.delivery.latest_throughput is not None
    )
    if legacy_only:
        limitations.append(LIMITATION_THROUGHPUT_HISTORY_UNAVAILABLE)

    points, point_evidence = _materialize_points(
        working,
        source_rows=source_rows,
        throughput_quality=throughput_quality,
        legacy_only=legacy_only,
        limitations=limitations,
    )
    if len(source_rows) >= 2:
        gaps = _detect_date_gaps([row.snapshot_date for row in source_rows])
        if gaps:
            limitations.append(LIMITATION_THROUGHPUT_DATE_GAPS)

    availability = _availability_from_quality(throughput_quality, points=points)

    deviations: list[DeliveryTrendDeviationResult] = []
    top_evidence = list(point_evidence)

    if policy is None:
        limitations.append(LIMITATION_DEVIATION_POLICY_UNAVAILABLE)
        rules_version = None
    elif throughput_quality not in _RELIABLE_DEVIATION_QUALITY:
        # Policy intentionally not evaluated — do not access rules_version.
        limitations.append(LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE)
        rules_version = None
    else:
        rules_version = _require_rules_version(policy)
        authoritative = _build_candidate_context(working, points=points)
        decision = _evaluate_policy(policy, authoritative)
        limitations.extend(decision.policy_limitations)
        deviations, deviation_evidence = _materialize_deviations(
            decision,
            candidates=authoritative,
        )
        top_evidence = _merge_evidence(point_evidence, deviation_evidence)

    if availability in {
        DeliveryTrendAvailability.CONFLICTING,
        DeliveryTrendAvailability.UNAVAILABLE,
    }:
        points = []
        deviations = []
        top_evidence = []

    return DeliveryTrendAssessment(
        org_id=core_org_id,
        project_id=core_project_id,
        as_of=core_as_of,
        covered_start_date=core_start,
        covered_end_date=core_as_of,
        grain=TrendReportingGrain.DAY,
        timezone=TrendTimezone.UTC,
        visibility_mode=core_visibility,
        availability=availability,
        trend_points=_sort_points(points),
        deviations=_sort_deviations(deviations),
        evidence=_sort_evidence(top_evidence),
        limitations=_canonicalize_strings(limitations),
        source_limitations=source_limitations,
        source_fingerprint=core_source_fingerprint,
        rules_version=rules_version,
        assessed_at=core_assessed_at,
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


def _has_throughput_facts(pack: ClientEvidencePack) -> bool:
    return bool(pack.delivery.throughput_series or pack.delivery.latest_throughput)


def _resolve_source_quality(pack: ClientEvidencePack) -> DataQualityState | None:
    states = [
        issue.state
        for issue in pack.data_quality
        if issue.source in {"throughput_snapshots", "throughput"}
    ]
    if not states:
        return None
    if len(set(states)) > 1:
        return DataQualityState.CONFLICTING
    return states[0]


def _quality_limitations(
    quality: DataQualityState | None, *, facts_present: bool
) -> list[str]:
    if quality is None:
        if facts_present:
            return [LIMITATION_SOURCE_QUALITY_MISSING_THROUGHPUT_SNAPSHOTS]
        return []
    code = _QUALITY_STATE_LIMITATIONS.get(quality)
    return [code] if code is not None else []


def _resolve_source_rows(pack: ClientEvidencePack) -> list[ThroughputSnapshotFacts]:
    if pack.delivery.throughput_series:
        return list(pack.delivery.throughput_series)
    if pack.delivery.latest_throughput is not None:
        return [pack.delivery.latest_throughput]
    return []


def _availability_from_quality(
    quality: DataQualityState | None,
    *,
    points: list[DeliveryTrendPoint],
) -> DeliveryTrendAvailability:
    if not points:
        if quality == DataQualityState.UNAVAILABLE:
            return DeliveryTrendAvailability.UNAVAILABLE
        if quality == DataQualityState.CONFLICTING:
            return DeliveryTrendAvailability.CONFLICTING
        return DeliveryTrendAvailability.UNAVAILABLE
    if quality == DataQualityState.CONFLICTING:
        return DeliveryTrendAvailability.CONFLICTING
    if quality == DataQualityState.UNAVAILABLE:
        return DeliveryTrendAvailability.UNAVAILABLE
    if quality == DataQualityState.STALE:
        return DeliveryTrendAvailability.STALE
    if quality == DataQualityState.PARTIAL:
        return DeliveryTrendAvailability.PARTIAL
    if quality is None:
        return DeliveryTrendAvailability.PARTIAL
    # Governed plan source is absent — full AVAILABLE is never reachable in TASK 13.
    return DeliveryTrendAvailability.PARTIAL


def _detect_date_gaps(dates: list[date]) -> bool:
    if len(dates) < 2:
        return False
    ordered = sorted(dates)
    return any(
        (right - left).days > 1 for left, right in zip(ordered, ordered[1:], strict=False)
    )


def _snapshot_observed_at(snapshot_date: date) -> datetime:
    return datetime.combine(snapshot_date, time.min, tzinfo=UTC)


def _pack_evidence_for_row(
    pack: ClientEvidencePack, row_id: UUID
) -> ClientEvidenceReference:
    matches = [
        item
        for item in pack.evidence
        if item.source_table == "throughput_snapshots" and item.source_row_id == row_id
    ]
    if len(matches) != 1:
        raise DeliveryTrendIntegrityError(
            "unsupported_evidence_reference",
            "Trend construction requires exactly one throughput evidence row.",
        )
    return matches[0]


def _to_trend_evidence(
    pack_ref: ClientEvidenceReference,
    *,
    claim_keys: list[str],
    source_fingerprint: str,
) -> DeliveryTrendEvidenceRef:
    return DeliveryTrendEvidenceRef(
        source_agent=pack_ref.source_agent,
        source_table="throughput_snapshots",
        source_row_id=pack_ref.source_row_id,
        visibility=pack_ref.visibility,
        claim_keys=sorted(claim_keys),
        period=DeliveryTrendEvidencePeriod.CURRENT,
        source_fingerprint=source_fingerprint,
        observed_at=pack_ref.observed_at,
    )


def _materialize_points(
    pack: ClientEvidencePack,
    *,
    source_rows: list[ThroughputSnapshotFacts],
    throughput_quality: DataQualityState | None,
    legacy_only: bool,
    limitations: list[str],
) -> tuple[list[DeliveryTrendPoint], list[DeliveryTrendEvidenceRef]]:
    points: list[DeliveryTrendPoint] = []
    evidence: list[DeliveryTrendEvidenceRef] = []
    quality = throughput_quality

    if quality in {DataQualityState.UNAVAILABLE, DataQualityState.CONFLICTING}:
        return [], []

    for row in source_rows:
        pack_ref = _pack_evidence_for_row(pack, row.id)
        observed_at = pack_ref.observed_at
        if observed_at != _snapshot_observed_at(row.snapshot_date):
            raise DeliveryTrendIntegrityError(
                "invalid_evidence_lineage",
                "Throughput evidence observed_at must equal snapshot_date midnight UTC.",
            )

        actual_state = TrendSeriesValueState.OBSERVED
        actual_units = row.units_completed
        if actual_units is None:
            actual_state = TrendSeriesValueState.MISSING_SOURCE
        elif isinstance(actual_units, bool):
            raise DeliveryTrendIntegrityError(
                "invalid_source_value",
                "units_completed must be an exact integer.",
            )

        forecast_state: TrendSeriesValueState
        forecast_units = row.units_forecast
        if forecast_units is None:
            forecast_state = TrendSeriesValueState.MISSING_SOURCE
            limitations.append(LIMITATION_FORECAST_VALUE_MISSING)
        else:
            if isinstance(forecast_units, bool):
                raise DeliveryTrendIntegrityError(
                    "invalid_source_value",
                    "units_forecast must be an exact integer.",
                )
            forecast_state = TrendSeriesValueState.OBSERVED

        claim_keys = ["snapshot_date"]
        if actual_state == TrendSeriesValueState.OBSERVED:
            claim_keys.append("units_completed")
        if forecast_state == TrendSeriesValueState.OBSERVED:
            claim_keys.append("units_forecast")

        item_evidence = [
            _to_trend_evidence(
                pack_ref,
                claim_keys=claim_keys,
                source_fingerprint=pack.source_fingerprint,
            )
        ]
        delta: int | None = None
        if actual_units is not None and forecast_units is not None:
            delta = actual_units - forecast_units

        point_limitations = [LIMITATION_PLAN_SERIES_UNAVAILABLE]
        if forecast_units is None:
            point_limitations.append(LIMITATION_FORECAST_VALUE_MISSING)
        if legacy_only:
            point_limitations.append(LIMITATION_THROUGHPUT_HISTORY_UNAVAILABLE)

        points.append(
            DeliveryTrendPoint(
                snapshot_date=row.snapshot_date,
                source_row_id=row.id,
                source_agent=pack_ref.source_agent,
                source_table="throughput_snapshots",
                actual_units=actual_units,
                actual_state=actual_state,
                plan_units=None,
                plan_state=TrendSeriesValueState.MISSING_SOURCE,
                forecast_units=forecast_units,
                forecast_state=forecast_state,
                delta_actual_forecast=delta,
                delta_actual_plan=None,
                data_quality=quality,
                visibility=pack_ref.visibility,
                source_fingerprint=pack.source_fingerprint,
                evidence=item_evidence,
                limitations=_canonicalize_strings(point_limitations),
            )
        )
        evidence.extend(item_evidence)
    return points, evidence


def _build_candidate_context(
    pack: ClientEvidencePack,
    *,
    points: list[DeliveryTrendPoint],
) -> DeliveryTrendDeviationCandidateContext:
    candidates: list[DeliveryTrendDeviationCandidate] = []
    for point in points:
        if point.data_quality != DataQualityState.COMPLETE:
            continue
        if point.actual_units is None or point.forecast_units is None:
            continue
        if point.delta_actual_forecast is None:
            continue
        candidates.append(
            DeliveryTrendDeviationCandidate(
                candidate_key=canonical_deviation_candidate_key(
                    point.source_row_id, point.snapshot_date
                ),
                source_row_id=point.source_row_id,
                snapshot_date=point.snapshot_date,
                actual_units=point.actual_units,
                forecast_units=point.forecast_units,
                delta_actual_forecast=point.delta_actual_forecast,
                data_quality=DataQualityState.COMPLETE,
                visibility=point.visibility,
                source_fingerprint=point.source_fingerprint,
                evidence=point.evidence,
            )
        )
    ordered = sorted(
        candidates,
        key=lambda item: (item.snapshot_date, str(item.source_row_id), item.candidate_key),
    )
    return DeliveryTrendDeviationCandidateContext(candidates=ordered, context_limitations=[])


def _require_rules_version(policy: DeliveryTrendDeviationPolicy) -> str:
    try:
        version = policy.rules_version
    except Exception as exc:  # noqa: BLE001
        raise DeliveryTrendIntegrityError(
            "invalid_policy",
            "Delivery trend policy rules_version is inaccessible.",
        ) from exc
    try:
        return require_rules_version(version)
    except (TypeError, ValueError) as exc:
        raise DeliveryTrendIntegrityError(
            "invalid_policy",
            "Delivery trend policy rules_version must be non-empty.",
        ) from exc


def _evaluate_policy(
    policy: DeliveryTrendDeviationPolicy,
    authoritative: DeliveryTrendDeviationCandidateContext,
) -> DeliveryTrendDeviationPolicyDecision:
    policy_copy = authoritative.model_copy(deep=True)
    try:
        decision = policy.evaluate(policy_copy)
    except Exception as exc:  # noqa: BLE001
        raise DeliveryTrendIntegrityError(
            "invalid_policy",
            "Injected delivery trend policy failed during evaluation.",
        ) from exc
    if not isinstance(decision, DeliveryTrendDeviationPolicyDecision):
        raise DeliveryTrendIntegrityError(
            "invalid_policy_decision",
            "Delivery trend policy did not return a DeliveryTrendDeviationPolicyDecision.",
        )
    return decision


def _materialize_deviations(
    decision: DeliveryTrendDeviationPolicyDecision,
    *,
    candidates: DeliveryTrendDeviationCandidateContext,
) -> tuple[list[DeliveryTrendDeviationResult], list[DeliveryTrendEvidenceRef]]:
    by_key = {item.candidate_key: item for item in candidates.candidates}
    results: list[DeliveryTrendDeviationResult] = []
    evidence: list[DeliveryTrendEvidenceRef] = []
    for selection in decision.selections:
        candidate = by_key.get(selection.candidate_key)
        if candidate is None:
            raise DeliveryTrendIntegrityError(
                "invalid_policy_decision",
                "Delivery trend policy selected an unknown candidate key.",
            )
        item_evidence = [
            DeliveryTrendEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=list(ref.claim_keys),
                period=ref.period,
                source_fingerprint=ref.source_fingerprint,
                observed_at=ref.observed_at,
            )
            for ref in candidate.evidence
        ]
        results.append(
            DeliveryTrendDeviationResult(
                candidate_key=candidate.candidate_key,
                source_row_id=candidate.source_row_id,
                snapshot_date=candidate.snapshot_date,
                actual_units=candidate.actual_units,
                forecast_units=candidate.forecast_units,
                delta_actual_forecast=candidate.delta_actual_forecast,
                materiality=selection.materiality,
                data_quality=candidate.data_quality,
                visibility=candidate.visibility,
                source_fingerprint=candidate.source_fingerprint,
                evidence=item_evidence,
            )
        )
        evidence.extend(item_evidence)
    return results, evidence


def _merge_evidence(
    left: list[DeliveryTrendEvidenceRef],
    right: list[DeliveryTrendEvidenceRef],
) -> list[DeliveryTrendEvidenceRef]:
    return _sort_evidence([*left, *right])


def _sort_points(points: list[DeliveryTrendPoint]) -> list[DeliveryTrendPoint]:
    return sorted(points, key=lambda item: (item.snapshot_date, str(item.source_row_id)))


def _sort_deviations(
    deviations: list[DeliveryTrendDeviationResult],
) -> list[DeliveryTrendDeviationResult]:
    return sorted(
        deviations,
        key=lambda item: (item.snapshot_date, str(item.source_row_id), item.candidate_key),
    )


def _sort_evidence(
    refs: list[DeliveryTrendEvidenceRef],
) -> list[DeliveryTrendEvidenceRef]:
    identity_observed: dict[tuple[str, str, str, str, str, str], datetime | None] = {}
    merged: dict[tuple[str, str, str, str, str, str, str], DeliveryTrendEvidenceRef] = {}
    claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
    for ref in refs:
        identity = (
            ref.source_agent.value,
            ref.source_table,
            str(ref.source_row_id),
            ref.visibility.value,
            ref.period.value,
            ref.source_fingerprint,
        )
        if identity in identity_observed:
            if identity_observed[identity] != ref.observed_at:
                raise DeliveryTrendIntegrityError(
                    "invalid_policy_decision",
                    "Conflicting observed_at on the same evidence identity.",
                )
        else:
            identity_observed[identity] = ref.observed_at
        key = (
            *identity,
            ref.observed_at.isoformat() if ref.observed_at is not None else "",
        )
        merged.setdefault(key, ref)
        claims.setdefault(key, set()).update(ref.claim_keys)

    result: list[DeliveryTrendEvidenceRef] = []
    for key, ref in merged.items():
        result.append(
            DeliveryTrendEvidenceRef(
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
            item.source_fingerprint,
            item.source_agent.value,
            item.source_table,
            str(item.source_row_id),
            item.visibility.value,
            item.period.value,
            item.observed_at.isoformat() if item.observed_at is not None else "",
            tuple(item.claim_keys),
        ),
    )


def _empty_assessment(
    *,
    org_id: UUID,
    project_id: UUID,
    as_of: date,
    covered_start_date: date,
    covered_end_date: date,
    visibility_mode: EvidenceVisibility,
    availability: DeliveryTrendAvailability,
    limitations: list[str],
    source_limitations: list[str],
    source_fingerprint: str,
    assessed_at: datetime,
) -> DeliveryTrendAssessment:
    return DeliveryTrendAssessment(
        org_id=org_id,
        project_id=project_id,
        as_of=as_of,
        covered_start_date=covered_start_date,
        covered_end_date=covered_end_date,
        grain=TrendReportingGrain.DAY,
        timezone=TrendTimezone.UTC,
        visibility_mode=visibility_mode,
        availability=availability,
        trend_points=[],
        deviations=[],
        evidence=[],
        limitations=_canonicalize_strings(limitations),
        source_limitations=source_limitations,
        source_fingerprint=source_fingerprint,
        rules_version=None,
        assessed_at=assessed_at,
    )
