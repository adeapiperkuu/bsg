"""Deterministic Change Intelligence foundation (roadmap 8.5 / CI-F06).

Compares governed facts across two validated, aligned ClientEvidencePack instances.
No database access, persistence, API calls, LLM calls, or production materiality
policy is defined here.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.agents.client_intelligence.change_intelligence_contracts import (
    _ALL_DOMAINS_ORDERED,
    LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE,
    LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE,
    LIMITATION_GOVERNANCE_HISTORY_LIMITED,
    LIMITATION_MILESTONE_CLOSURE_HISTORY_UNAVAILABLE,
    LIMITATION_MILESTONE_CREATION_HISTORY_UNAVAILABLE,
    LIMITATION_MILESTONE_HISTORY_LIMITED,
    LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE,
    LIMITATION_READINESS_INTELLIGENCE_UNAVAILABLE,
    LIMITATION_RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE,
    LIMITATION_RISK_CLOSURE_HISTORY_UNAVAILABLE,
    LIMITATION_RISK_CREATION_HISTORY_UNAVAILABLE,
    LIMITATION_RISK_HISTORY_LIMITED,
    ChangeCandidate,
    ChangeCandidateContext,
    ChangeComparisonPeriod,
    ChangeComparisonResult,
    ChangeDirection,
    ChangeDomain,
    ChangeDomainComparisonOutcome,
    ChangeDomainCoverageItem,
    ChangeDomainCoverageState,
    ChangeEvidencePeriod,
    ChangeEvidenceReference,
    ChangeIntelligenceAssessment,
    ChangeIntelligenceAvailability,
    ChangeItem,
    ChangeMaterialityPolicyDecision,
    ChangeScalarValue,
    ChangeSourceRowIdentity,
    ChangeValueType,
    _canonical_evidence_union,
    _canonicalize_period_text_limitations,
    canonical_comparison_identity,
    exact_claim_keys_for_metric,
    require_rules_version,
)
from app.agents.client_intelligence.change_intelligence_policy import (
    ChangeMaterialityPolicy,
)
from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityState,
    DeliveryConfidenceFacts,
    EvidenceVisibility,
    GovernanceActionFacts,
    GovernanceDependencyFacts,
    MilestoneFacts,
    QualitySnapshotFacts,
    SourceAgent,
    ThroughputSnapshotFacts,
)
from app.agents.client_intelligence.evidence_validation import (
    reference_supports_claim_keys,
    source_agent_owns_table,
    validate_client_evidence_pack,
)
from app.db.models import AppRole

_RELIABLE_QUALITY = frozenset({DataQualityState.COMPLETE})

_EVIDENCE_TABLE_TO_DQ_SOURCES: dict[str, frozenset[str]] = {
    "throughput_snapshots": frozenset({"throughput_snapshots", "throughput"}),
    "delivery_confidence_scores": frozenset(
        {"delivery_confidence", "delivery_confidence_scores"}
    ),
    "quality_snapshots": frozenset({"quality_snapshots"}),
    "milestones": frozenset({"milestones"}),
    "risk_alerts": frozenset({"risk_alerts", "risks"}),
    "utilization_snapshots": frozenset({"utilization_snapshots"}),
    "project_skill_requirements": frozenset(
        {"project_skill_requirements", "skill_requirements"}
    ),
    "project_dependencies": frozenset({"governance_dependencies", "project_dependencies"}),
    "governance_actions": frozenset({"governance_actions"}),
}

_ALL_DOMAINS = _ALL_DOMAINS_ORDERED


class _DomainCompareBundle:
    __slots__ = ("domain", "state", "limitations", "candidates")

    def __init__(
        self,
        *,
        domain: ChangeDomain,
        state: ChangeDomainCoverageState,
        limitations: list[str],
        candidates: list[ChangeCandidate],
    ) -> None:
        self.domain = domain
        self.state = state
        self.limitations = limitations
        self.candidates = candidates


class ChangeIntelligenceIntegrityError(Exception):
    """Deterministic Change Intelligence integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def build_change_comparison(
    current_pack: ClientEvidencePack,
    previous_pack: ClientEvidencePack,
) -> ChangeComparisonResult:
    """Build deterministic comparison outcomes from aligned validated packs."""
    current = current_pack.model_copy(deep=True)
    previous = previous_pack.model_copy(deep=True)
    _validate_pack_or_raise(current)
    _validate_pack_or_raise(previous)
    _assert_packs_compatible(current, previous)

    comparison_period = _comparison_period(current, previous)
    bundles = [
        _compare_throughput(current, previous, comparison_period),
        _compare_quality(current, previous, comparison_period),
        _compare_rework(current, previous, comparison_period),
        _compare_delivery_confidence(current, previous, comparison_period),
        _compare_milestones(current, previous, comparison_period),
        _compare_risks(current, previous, comparison_period),
        _compare_readiness(),
        _compare_workforce_capacity(current, previous, comparison_period),
        _compare_sme_coverage(current, previous, comparison_period),
        _compare_governance_dependencies(current, previous, comparison_period),
        _compare_governance_actions(current, previous, comparison_period),
        _compare_resource_onboarding(),
    ]
    candidates: list[ChangeCandidate] = []
    domain_outcomes: list[ChangeDomainComparisonOutcome] = []
    comparison_limitations: list[str] = []
    for bundle in bundles:
        domain_outcomes.append(
            ChangeDomainComparisonOutcome(
                domain=bundle.domain,
                state=bundle.state,
                limitations=bundle.limitations,
            )
        )
        comparison_limitations.extend(bundle.limitations)
        candidates.extend(bundle.candidates)
    return ChangeComparisonResult(
        candidates=_sort_candidates(candidates),
        domain_outcomes=domain_outcomes,
        comparison_limitations=_canonicalize_limitations(comparison_limitations),
    )


def build_change_candidates(
    current_pack: ClientEvidencePack,
    previous_pack: ClientEvidencePack,
) -> list[ChangeCandidate]:
    """Build deterministic change candidates from aligned validated packs."""
    return build_change_comparison(current_pack, previous_pack).candidates


def assess_change_intelligence(
    current_pack: ClientEvidencePack,
    previous_pack: ClientEvidencePack | None = None,
    policy: ChangeMaterialityPolicy | None = None,
    *,
    assessed_at: datetime | None = None,
) -> ChangeIntelligenceAssessment:
    """Assess cross-cycle changes from validated aligned evidence packs."""
    current = current_pack.model_copy(deep=True)
    _validate_pack_or_raise(current)

    source_limits = _split_source_limitations(current, previous_pack)
    limitations: list[str] = []
    core_assessed_at = assessed_at if assessed_at is not None else current.generated_at
    if core_assessed_at.tzinfo is None:
        raise ChangeIntelligenceIntegrityError(
            "invalid_assessment",
            "assessed_at must be timezone-aware.",
        )

    if previous_pack is None:
        limitations.append(LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE)
        if policy is None:
            limitations.append(LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE)
        return ChangeIntelligenceAssessment(
            org_id=current.project.org_id,
            project_id=current.project.project_id,
            current_reporting_period=current.reporting_period,
            previous_reporting_period=None,
            visibility_mode=current.visibility_mode,
            availability=ChangeIntelligenceAvailability.UNAVAILABLE,
            changes=[],
            detected_candidate_count=0,
            evaluated_candidate_count=0,
            published_change_count=0,
            policy_evaluated=False,
            domain_coverage=_domain_coverage_unavailable(policy_evaluated=False),
            limitations=_canonicalize_limitations(limitations),
            previous_source_limitations=source_limits["previous"],
            current_source_limitations=source_limits["current"],
            evidence=[],
            previous_source_fingerprint=None,
            current_source_fingerprint=current.source_fingerprint,
            rules_version=None,
            assessed_at=core_assessed_at,
        )

    previous = previous_pack.model_copy(deep=True)
    comparison = build_change_comparison(current, previous)
    candidates = comparison.candidates
    detected_count = len(candidates)
    reliable = [item for item in candidates if item.is_reliable]
    domain_coverage = _finalize_domain_coverage(
        comparison.domain_outcomes,
        candidates,
        policy_evaluated=False,
    )
    limitations.extend(comparison.comparison_limitations)
    limitations.extend(_domain_limitations(domain_coverage))

    if any(not item.is_reliable for item in candidates):
        limitations.append(LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE)

    changes: list[ChangeItem] = []
    top_evidence: list[ChangeEvidenceReference] = []
    rules_version: str | None = None
    policy_evaluated = False
    evaluated_count = 0

    if policy is None:
        limitations.append(LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE)
    elif reliable:
        try:
            rules_version = require_rules_version(policy.rules_version)
        except ValueError as exc:
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy",
                "Change materiality policy rules_version is invalid.",
            ) from exc
        context = ChangeCandidateContext(
            candidates=[item.model_copy(deep=True) for item in reliable],
            context_limitations=[],
        )
        decision = _evaluate_policy(policy, context)
        limitations.extend(decision.policy_limitations)
        changes, top_evidence = _materialize_changes(
            decision,
            candidates_by_key={item.candidate_key: item for item in reliable},
        )
        policy_evaluated = True
        evaluated_count = len(reliable)
        domain_coverage = _finalize_domain_coverage(
            comparison.domain_outcomes,
            candidates,
            policy_evaluated=True,
        )

    availability = _availability_from_coverage(domain_coverage, limitations)

    return ChangeIntelligenceAssessment(
        org_id=current.project.org_id,
        project_id=current.project.project_id,
        current_reporting_period=current.reporting_period,
        previous_reporting_period=previous.reporting_period,
        visibility_mode=current.visibility_mode,
        availability=availability,
        changes=_sort_changes(changes),
        detected_candidate_count=detected_count,
        evaluated_candidate_count=evaluated_count,
        published_change_count=len(changes),
        policy_evaluated=policy_evaluated,
        domain_coverage=domain_coverage,
        limitations=_canonicalize_limitations(limitations),
        previous_source_limitations=source_limits["previous"],
        current_source_limitations=source_limits["current"],
        evidence=_sort_evidence(top_evidence),
        previous_source_fingerprint=previous.source_fingerprint,
        current_source_fingerprint=current.source_fingerprint,
        rules_version=rules_version,
        assessed_at=core_assessed_at,
    )


def _validate_pack_or_raise(pack: ClientEvidencePack) -> None:
    result = validate_client_evidence_pack(pack, role=AppRole.DELIVERY_MANAGER)
    if not result.is_valid:
        raise ChangeIntelligenceIntegrityError(
            "invalid_pack",
            "Evidence pack failed integrity validation.",
        )


def _assert_packs_compatible(
    current: ClientEvidencePack, previous: ClientEvidencePack
) -> None:
    if previous.project.org_id != current.project.org_id:
        raise ChangeIntelligenceIntegrityError(
            "incompatible_org",
            "Previous pack org_id does not match current pack.",
        )
    if previous.project.project_id != current.project.project_id:
        raise ChangeIntelligenceIntegrityError(
            "incompatible_project",
            "Previous pack project_id does not match current pack.",
        )
    if previous.visibility_mode != current.visibility_mode:
        raise ChangeIntelligenceIntegrityError(
            "incompatible_visibility",
            "Previous pack visibility_mode does not match current pack.",
        )
    if previous.source_fingerprint == current.source_fingerprint:
        raise ChangeIntelligenceIntegrityError(
            "identical_source_fingerprint",
            "Current and previous packs must have distinct source fingerprints.",
        )
    if previous.reporting_period.as_of >= current.reporting_period.as_of:
        raise ChangeIntelligenceIntegrityError(
            "reversed_reporting_period",
            "Previous pack as_of must be earlier than current pack as_of.",
        )
    period = current.reporting_period
    prev_period = previous.reporting_period
    if not (
        prev_period.start_date == period.previous_start_date
        and prev_period.end_date == period.previous_end_date
    ):
        raise ChangeIntelligenceIntegrityError(
            "misaligned_previous_cycle",
            "Previous pack reporting period is not aligned to current previous cycle.",
        )
    if prev_period.end_date >= period.start_date:
        raise ChangeIntelligenceIntegrityError(
            "overlapping_reporting_period",
            "Reporting periods overlap or are reversed.",
        )


def _comparison_period(
    current: ClientEvidencePack, previous: ClientEvidencePack
) -> ChangeComparisonPeriod:
    return ChangeComparisonPeriod(
        previous_start_date=previous.reporting_period.start_date,
        previous_end_date=previous.reporting_period.end_date,
        current_start_date=current.reporting_period.start_date,
        current_end_date=current.reporting_period.end_date,
    )


def _split_source_limitations(
    current: ClientEvidencePack,
    previous: ClientEvidencePack | None,
) -> dict[str, list[str]]:
    current_limits = _canonicalize_period_text_limitations(list(current.limitations))
    previous_limits: list[str] = []
    if previous is not None:
        previous_limits = _canonicalize_period_text_limitations(list(previous.limitations))
    return {"previous": previous_limits, "current": current_limits}


def _resolve_source_quality(
    pack: ClientEvidencePack, source_table: str
) -> DataQualityState | None:
    aliases = _EVIDENCE_TABLE_TO_DQ_SOURCES.get(source_table)
    if aliases is None:
        raise ChangeIntelligenceIntegrityError(
            "invalid_source_table",
            "Unsupported change intelligence source_table.",
        )
    issues = [item for item in pack.data_quality if item.source in aliases]
    if not issues:
        return None
    states = {item.state for item in issues}
    if len(states) != 1:
        return DataQualityState.CONFLICTING
    return next(iter(states))


def _to_evidence_ref(
    pack: ClientEvidencePack,
    reference: ClientEvidenceReference,
    *,
    period: ChangeEvidencePeriod,
    claim_keys: list[str],
) -> ChangeEvidenceReference:
    if not source_agent_owns_table(reference.source_agent, reference.source_table):
        raise ChangeIntelligenceIntegrityError(
            "unsupported_evidence_reference",
            "Evidence source ownership is invalid.",
        )
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if not reference_supports_claim_keys(
        reference, claim_keys, client_safe=client_safe
    ):
        raise ChangeIntelligenceIntegrityError(
            "unsupported_evidence_reference",
            "Evidence does not support required claim keys.",
        )
    return ChangeEvidenceReference(
        source_agent=reference.source_agent,
        source_table=reference.source_table,
        source_row_id=reference.source_row_id,
        visibility=reference.visibility,
        claim_keys=sorted(claim_keys),
        period=period,
        source_fingerprint=pack.source_fingerprint,
        observed_at=reference.observed_at,
    )


def _find_evidence_for_claim(
    pack: ClientEvidencePack,
    *,
    source_table: str,
    claim_key: str,
    period: ChangeEvidencePeriod,
    source_row_id: UUID | None = None,
) -> list[ChangeEvidenceReference]:
    refs = [
        item
        for item in pack.evidence
        if item.source_table == source_table
        and claim_key in item.claim_keys
        and (source_row_id is None or item.source_row_id == source_row_id)
    ]
    if not refs:
        raise ChangeIntelligenceIntegrityError(
            "unsupported_evidence_reference",
            "Required pack evidence is missing.",
        )
    selected = sorted(refs, key=lambda item: str(item.source_row_id))[0]
    return _find_evidence(
        pack,
        source_table=source_table,
        source_row_id=selected.source_row_id,
        claim_keys=[claim_key],
        period=period,
    )


def _find_evidence(
    pack: ClientEvidencePack,
    *,
    source_table: str,
    source_row_id: UUID,
    claim_keys: list[str],
    period: ChangeEvidencePeriod,
) -> list[ChangeEvidenceReference]:
    refs = [
        item
        for item in pack.evidence
        if item.source_table == source_table
        and item.source_row_id == source_row_id
        and set(claim_keys).issubset(set(item.claim_keys))
    ]
    if not refs:
        raise ChangeIntelligenceIntegrityError(
            "unsupported_evidence_reference",
            "Required pack evidence is missing.",
        )
    merged: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
    templates: dict[tuple[str, str, str, str, str, str, str], ChangeEvidenceReference] = {}
    for ref in refs:
        converted = _to_evidence_ref(
            pack, ref, period=period, claim_keys=claim_keys
        )
        key = (
            converted.source_agent.value,
            converted.source_table,
            str(converted.source_row_id),
            converted.visibility.value,
            converted.period.value,
            converted.source_fingerprint,
            converted.observed_at.isoformat() if converted.observed_at else "",
        )
        merged.setdefault(key, set()).update(converted.claim_keys)
        templates.setdefault(key, converted)
    return [
        ChangeEvidenceReference(
            source_agent=templates[key].source_agent,
            source_table=templates[key].source_table,
            source_row_id=templates[key].source_row_id,
            visibility=templates[key].visibility,
            claim_keys=sorted(claims),
            period=templates[key].period,
            source_fingerprint=templates[key].source_fingerprint,
            observed_at=templates[key].observed_at,
        )
        for key, claims in sorted(merged.items())
    ]


def _direction_for_values(
    previous: Any, current: Any, *, numeric: bool = False
) -> ChangeDirection:
    if previous is None and current is not None:
        return ChangeDirection.UNKNOWN
    if previous is not None and current is None:
        return ChangeDirection.UNKNOWN
    if previous == current:
        return ChangeDirection.UNCHANGED
    if numeric:
        if previous is None or current is None:
            return ChangeDirection.UNKNOWN
        if current > previous:
            return ChangeDirection.INCREASED
        if current < previous:
            return ChangeDirection.DECREASED
    return ChangeDirection.CHANGED


def _candidate_limitations(
    previous_quality: DataQualityState | None,
    current_quality: DataQualityState | None,
) -> list[str]:
    if (
        previous_quality in _RELIABLE_QUALITY
        and current_quality in _RELIABLE_QUALITY
    ):
        return []
    return [LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE]


def _factual_domain_state(
    *,
    comparable: bool,
    previous_quality: DataQualityState | None,
    current_quality: DataQualityState | None,
) -> ChangeDomainCoverageState:
    if not comparable:
        return ChangeDomainCoverageState.UNAVAILABLE
    if (
        previous_quality == DataQualityState.COMPLETE
        and current_quality == DataQualityState.COMPLETE
    ):
        return ChangeDomainCoverageState.EVALUATED
    return ChangeDomainCoverageState.UNRELIABLE


def _make_candidate(
    *,
    org_id: UUID,
    project_id: UUID,
    candidate_key: str,
    domain: ChangeDomain,
    metric_key: str,
    source_agent: SourceAgent,
    source_table: str,
    previous_row_id: UUID,
    current_row_id: UUID,
    entity_id: UUID | None = None,
    team_key: str | None = None,
    previous_value: Any,
    current_value: Any,
    direction: ChangeDirection,
    previous_quality: DataQualityState | None,
    current_quality: DataQualityState | None,
    previous_evidence: list[ChangeEvidenceReference],
    current_evidence: list[ChangeEvidenceReference],
    previous_fingerprint: str,
    current_fingerprint: str,
    comparison_period: ChangeComparisonPeriod,
    extra_limitations: Iterable[str] | None = None,
) -> ChangeCandidate | None:
    if direction in {ChangeDirection.UNCHANGED, ChangeDirection.UNKNOWN}:
        return None
    value_type, _ = _encode_pair(previous_value, current_value)
    limitations = _candidate_limitations(previous_quality, current_quality)
    if extra_limitations:
        limitations = sorted(set(limitations).union(extra_limitations))
    return ChangeCandidate(
        org_id=org_id,
        project_id=project_id,
        candidate_key=candidate_key,
        domain=domain,
        metric_key=metric_key,
        comparison_identity=canonical_comparison_identity(
            domain=domain,
            metric_key=metric_key,
            entity_id=entity_id,
            team_key=team_key,
        ),
        previous_source=ChangeSourceRowIdentity(
            source_agent=source_agent,
            source_table=source_table,
            source_row_id=previous_row_id,
        ),
        current_source=ChangeSourceRowIdentity(
            source_agent=source_agent,
            source_table=source_table,
            source_row_id=current_row_id,
        ),
        previous_value=ChangeScalarValue.from_python(previous_value),
        current_value=ChangeScalarValue.from_python(current_value),
        value_type=value_type,
        direction=direction,
        previous_data_quality=previous_quality,
        current_data_quality=current_quality,
        previous_evidence=previous_evidence,
        current_evidence=current_evidence,
        previous_source_fingerprint=previous_fingerprint,
        current_source_fingerprint=current_fingerprint,
        comparison_period=comparison_period,
        limitations=limitations,
    )


def _encode_pair(previous: Any, current: Any) -> tuple[ChangeValueType, None]:
    prev_scalar = ChangeScalarValue.from_python(previous)
    curr_scalar = ChangeScalarValue.from_python(current)
    if prev_scalar.value_type != curr_scalar.value_type:
        raise ChangeIntelligenceIntegrityError(
            "incompatible_value_types",
            "Compared values must share a value_type.",
        )
    return prev_scalar.value_type, None


def _find_exact_evidence(
    pack: ClientEvidencePack,
    *,
    domain: ChangeDomain,
    metric_key: str,
    source_table: str,
    source_row_id: UUID,
    period: ChangeEvidencePeriod,
) -> list[ChangeEvidenceReference]:
    claim_keys = sorted(exact_claim_keys_for_metric(domain, metric_key))
    return _find_evidence(
        pack,
        source_table=source_table,
        source_row_id=source_row_id,
        claim_keys=claim_keys,
        period=period,
    )


def _throughput_snapshot_at(
    pack: ClientEvidencePack, target_date: date
) -> ThroughputSnapshotFacts | None:
    for row in pack.delivery.throughput_series:
        if row.snapshot_date == target_date:
            return row
    latest = pack.delivery.latest_throughput
    if latest is not None and latest.snapshot_date == target_date:
        return latest
    return None


def _compare_throughput(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.THROUGHPUT
    if current.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE,
            limitations=[],
            candidates=[],
        )

    quality_prev = _resolve_source_quality(previous, "throughput_snapshots")
    quality_curr = _resolve_source_quality(current, "throughput_snapshots")
    prev_row = _throughput_snapshot_at(previous, previous.reporting_period.as_of)
    curr_row = _throughput_snapshot_at(current, current.reporting_period.as_of)
    comparable = prev_row is not None and curr_row is not None
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not comparable:
        return _DomainCompareBundle(
            domain=domain,
            state=state,
            limitations=[],
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    for metric_key in ("units_completed", "units_forecast"):
        prev_val = getattr(prev_row, metric_key)
        curr_val = getattr(curr_row, metric_key)
        direction = _direction_for_values(prev_val, curr_val, numeric=True)
        if direction == ChangeDirection.UNCHANGED:
            continue
        candidate = _make_candidate(
            org_id=current.project.org_id,
            project_id=current.project.project_id,
            candidate_key=(
                f"throughput.{prev_row.id.hex}.{curr_row.id.hex}.{metric_key}."
                f"{comparison_period.current_end_date.strftime('%Y%m%d')}"
            ),
            domain=domain,
            metric_key=metric_key,
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="throughput_snapshots",
            previous_row_id=prev_row.id,
            current_row_id=curr_row.id,
            previous_value=prev_val,
            current_value=curr_val,
            direction=direction,
            previous_quality=quality_prev,
            current_quality=quality_curr,
            previous_evidence=_find_exact_evidence(
                previous,
                domain=domain,
                metric_key=metric_key,
                source_table="throughput_snapshots",
                source_row_id=prev_row.id,
                period=ChangeEvidencePeriod.PREVIOUS,
            ),
            current_evidence=_find_exact_evidence(
                current,
                domain=domain,
                metric_key=metric_key,
                source_table="throughput_snapshots",
                source_row_id=curr_row.id,
                period=ChangeEvidencePeriod.CURRENT,
            ),
            previous_fingerprint=previous.source_fingerprint,
            current_fingerprint=current.source_fingerprint,
            comparison_period=comparison_period,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=[],
        candidates=candidates,
    )


def _quality_alignment_ok(
    current: ClientEvidencePack, previous: ClientEvidencePack
) -> bool:
    return (
        previous.quality.current_iso_year == current.quality.previous_iso_year
        and previous.quality.current_iso_week == current.quality.previous_iso_week
    )


def _quality_snapshots_by_team(
    snapshots: list[QualitySnapshotFacts],
) -> dict[str, QualitySnapshotFacts]:
    indexed: dict[str, QualitySnapshotFacts] = {}
    for snap in snapshots:
        team_key = snap.team_id.hex if snap.team_id is not None else "project"
        indexed[team_key] = snap
    return indexed


def _compare_quality_metric(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
    *,
    metric_key: str,
    domain: ChangeDomain,
    key_prefix: str,
) -> _DomainCompareBundle:
    aligned = _quality_alignment_ok(current, previous)
    quality_prev = _resolve_source_quality(previous, "quality_snapshots")
    quality_curr = _resolve_source_quality(current, "quality_snapshots")
    if not aligned:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE,
            limitations=[],
            candidates=[],
        )
    prev_by_team = _quality_snapshots_by_team(previous.quality.current_period)
    curr_by_team = _quality_snapshots_by_team(current.quality.current_period)
    shared_teams = set(prev_by_team) & set(curr_by_team)
    comparable = bool(shared_teams)
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not comparable:
        return _DomainCompareBundle(
            domain=domain,
            state=state,
            limitations=[],
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    for team_key in sorted(shared_teams):
        prev_snap = prev_by_team[team_key]
        curr_snap = curr_by_team[team_key]
        prev_val = getattr(prev_snap, metric_key)
        curr_val = getattr(curr_snap, metric_key)
        if prev_val is None or curr_val is None:
            continue
        if type(prev_val) is float or type(curr_val) is float:
            raise ChangeIntelligenceIntegrityError(
                "invalid_numeric_value",
                "Quality metrics must remain Decimal-safe.",
            )
        direction = _direction_for_values(prev_val, curr_val, numeric=True)
        if direction == ChangeDirection.UNCHANGED:
            continue
        candidate = _make_candidate(
            org_id=current.project.org_id,
            project_id=current.project.project_id,
            candidate_key=(
                f"{key_prefix}.{team_key}.{metric_key}."
                f"{current.quality.current_iso_year}w{current.quality.current_iso_week:02d}"
            ),
            domain=domain,
            metric_key=metric_key,
            source_agent=SourceAgent.QUALITY_INTELLIGENCE,
            source_table="quality_snapshots",
            previous_row_id=prev_snap.snapshot_id,
            current_row_id=curr_snap.snapshot_id,
            team_key=team_key,
            previous_value=prev_val,
            current_value=curr_val,
            direction=direction,
            previous_quality=quality_prev,
            current_quality=quality_curr,
            previous_evidence=_find_exact_evidence(
                previous,
                domain=domain,
                metric_key=metric_key,
                source_table="quality_snapshots",
                source_row_id=prev_snap.snapshot_id,
                period=ChangeEvidencePeriod.PREVIOUS,
            ),
            current_evidence=_find_exact_evidence(
                current,
                domain=domain,
                metric_key=metric_key,
                source_table="quality_snapshots",
                source_row_id=curr_snap.snapshot_id,
                period=ChangeEvidencePeriod.CURRENT,
            ),
            previous_fingerprint=previous.source_fingerprint,
            current_fingerprint=current.source_fingerprint,
            comparison_period=comparison_period,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=[],
        candidates=candidates,
    )


def _compare_quality(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    return _compare_quality_metric(
        current,
        previous,
        comparison_period,
        metric_key="gold_set_accuracy_pct",
        domain=ChangeDomain.QUALITY,
        key_prefix="quality",
    )


def _compare_rework(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    return _compare_quality_metric(
        current,
        previous,
        comparison_period,
        metric_key="rework_rate_pct",
        domain=ChangeDomain.REWORK,
        key_prefix="rework",
    )


def _compare_delivery_confidence(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.DELIVERY_CONFIDENCE
    quality_prev = _resolve_source_quality(previous, "delivery_confidence_scores")
    quality_curr = _resolve_source_quality(current, "delivery_confidence_scores")
    prev_conf = previous.delivery.latest_delivery_confidence
    curr_conf = current.delivery.latest_delivery_confidence
    comparable = prev_conf is not None and curr_conf is not None
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not comparable:
        return _DomainCompareBundle(
            domain=domain,
            state=state,
            limitations=[],
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    comparisons: list[tuple[str, Callable[[DeliveryConfidenceFacts], Any], bool]] = [
        ("score_pct", lambda item: item.score_pct, True),
        ("confidence_status", lambda item: item.status, False),
        ("forecast_completion_date", lambda item: item.forecast_completion_date, False),
    ]
    for metric_key, accessor, numeric in comparisons:
        prev_val = accessor(prev_conf)
        curr_val = accessor(curr_conf)
        direction = _direction_for_values(prev_val, curr_val, numeric=numeric)
        if direction == ChangeDirection.UNCHANGED:
            continue
        candidate = _make_candidate(
            org_id=current.project.org_id,
            project_id=current.project.project_id,
            candidate_key=f"delivery_confidence.{prev_conf.id.hex}.{curr_conf.id.hex}.{metric_key}",
            domain=domain,
            metric_key=metric_key,
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="delivery_confidence_scores",
            previous_row_id=prev_conf.id,
            current_row_id=curr_conf.id,
            previous_value=prev_val,
            current_value=curr_val,
            direction=direction,
            previous_quality=quality_prev,
            current_quality=quality_curr,
            previous_evidence=_find_exact_evidence(
                previous,
                domain=domain,
                metric_key=metric_key,
                source_table="delivery_confidence_scores",
                source_row_id=prev_conf.id,
                period=ChangeEvidencePeriod.PREVIOUS,
            ),
            current_evidence=_find_exact_evidence(
                current,
                domain=domain,
                metric_key=metric_key,
                source_table="delivery_confidence_scores",
                source_row_id=curr_conf.id,
                period=ChangeEvidencePeriod.CURRENT,
            ),
            previous_fingerprint=previous.source_fingerprint,
            current_fingerprint=current.source_fingerprint,
            comparison_period=comparison_period,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=[],
        candidates=candidates,
    )


def _milestones_by_id(
    milestones: list[MilestoneFacts],
) -> dict[UUID, MilestoneFacts]:
    return {item.id: item for item in milestones}


def _compare_milestones(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.MILESTONE
    if current.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE,
            limitations=[],
            candidates=[],
        )
    quality_prev = _resolve_source_quality(previous, "milestones")
    quality_curr = _resolve_source_quality(current, "milestones")
    prev_map = _milestones_by_id(previous.delivery.milestones)
    curr_map = _milestones_by_id(current.delivery.milestones)
    shared_ids = set(prev_map) & set(curr_map)
    current_only = set(curr_map) - set(prev_map)
    previous_only = set(prev_map) - set(curr_map)
    limitations: list[str] = [LIMITATION_MILESTONE_HISTORY_LIMITED]
    if current_only:
        limitations.append(LIMITATION_MILESTONE_CREATION_HISTORY_UNAVAILABLE)
    if previous_only:
        limitations.append(LIMITATION_MILESTONE_CLOSURE_HISTORY_UNAVAILABLE)
    comparable = bool(shared_ids)
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not shared_ids:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE if not comparable else state,
            limitations=sorted(set(limitations)),
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    for milestone_id in sorted(shared_ids, key=lambda value: value.hex):
        prev_ms = prev_map[milestone_id]
        curr_ms = curr_map[milestone_id]
        for metric_key, accessor in (
            ("milestone_status", lambda item: item.status),
            ("planned_date", lambda item: item.planned_date),
            ("actual_date", lambda item: item.actual_date),
        ):
            prev_val = accessor(prev_ms)
            curr_val = accessor(curr_ms)
            direction = _direction_for_values(prev_val, curr_val)
            if direction == ChangeDirection.UNCHANGED:
                continue
            candidate = _make_candidate(
                org_id=current.project.org_id,
                project_id=current.project.project_id,
                candidate_key=f"milestone.{milestone_id.hex}.{metric_key}",
                domain=domain,
                metric_key=metric_key,
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="milestones",
                previous_row_id=milestone_id,
                current_row_id=milestone_id,
                entity_id=milestone_id,
                previous_value=prev_val,
                current_value=curr_val,
                direction=direction,
                previous_quality=quality_prev,
                current_quality=quality_curr,
                previous_evidence=_find_exact_evidence(
                    previous,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="milestones",
                    source_row_id=milestone_id,
                    period=ChangeEvidencePeriod.PREVIOUS,
                ),
                current_evidence=_find_exact_evidence(
                    current,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="milestones",
                    source_row_id=milestone_id,
                    period=ChangeEvidencePeriod.CURRENT,
                ),
                previous_fingerprint=previous.source_fingerprint,
                current_fingerprint=current.source_fingerprint,
                comparison_period=comparison_period,
                extra_limitations=[LIMITATION_MILESTONE_HISTORY_LIMITED],
            )
            if candidate is not None:
                candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=sorted(set(limitations)),
        candidates=candidates,
    )


def _compare_risks(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.RISK
    if current.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE,
            limitations=[],
            candidates=[],
        )
    quality_prev = _resolve_source_quality(previous, "risk_alerts")
    quality_curr = _resolve_source_quality(current, "risk_alerts")
    prev_map = {item.id: item for item in previous.delivery.open_risks}
    curr_map = {item.id: item for item in current.delivery.open_risks}
    shared_ids = set(prev_map) & set(curr_map)
    current_only = set(curr_map) - set(prev_map)
    previous_only = set(prev_map) - set(curr_map)
    limitations: list[str] = [LIMITATION_RISK_HISTORY_LIMITED]
    if current_only:
        limitations.append(LIMITATION_RISK_CREATION_HISTORY_UNAVAILABLE)
    if previous_only:
        limitations.append(LIMITATION_RISK_CLOSURE_HISTORY_UNAVAILABLE)
    comparable = bool(shared_ids)
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not shared_ids:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE if not comparable else state,
            limitations=sorted(set(limitations)),
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    for risk_id in sorted(shared_ids, key=lambda value: value.hex):
        prev_risk = prev_map[risk_id]
        curr_risk = curr_map[risk_id]
        for metric_key, accessor in (
            ("status", lambda item: item.status),
            ("risk_tier", lambda item: item.risk_tier),
            ("alert_type", lambda item: item.alert_type),
        ):
            prev_val = accessor(prev_risk)
            curr_val = accessor(curr_risk)
            direction = _direction_for_values(prev_val, curr_val)
            if direction == ChangeDirection.UNCHANGED:
                continue
            candidate = _make_candidate(
                org_id=current.project.org_id,
                project_id=current.project.project_id,
                candidate_key=f"risk.{risk_id.hex}.{metric_key}",
                domain=domain,
                metric_key=metric_key,
                source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                source_table="risk_alerts",
                previous_row_id=risk_id,
                current_row_id=risk_id,
                entity_id=risk_id,
                previous_value=prev_val,
                current_value=curr_val,
                direction=direction,
                previous_quality=quality_prev,
                current_quality=quality_curr,
                previous_evidence=_find_exact_evidence(
                    previous,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="risk_alerts",
                    source_row_id=risk_id,
                    period=ChangeEvidencePeriod.PREVIOUS,
                ),
                current_evidence=_find_exact_evidence(
                    current,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="risk_alerts",
                    source_row_id=risk_id,
                    period=ChangeEvidencePeriod.CURRENT,
                ),
                previous_fingerprint=previous.source_fingerprint,
                current_fingerprint=current.source_fingerprint,
                comparison_period=comparison_period,
                extra_limitations=[LIMITATION_RISK_HISTORY_LIMITED],
            )
            if candidate is not None:
                candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=sorted(set(limitations)),
        candidates=candidates,
    )


def _compare_readiness() -> _DomainCompareBundle:
    return _DomainCompareBundle(
        domain=ChangeDomain.READINESS,
        state=ChangeDomainCoverageState.UNAVAILABLE,
        limitations=[LIMITATION_READINESS_INTELLIGENCE_UNAVAILABLE],
        candidates=[],
    )


def _compare_resource_onboarding() -> _DomainCompareBundle:
    return _DomainCompareBundle(
        domain=ChangeDomain.RESOURCE_ONBOARDING,
        state=ChangeDomainCoverageState.UNAVAILABLE,
        limitations=[LIMITATION_RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE],
        candidates=[],
    )


def _compare_workforce_capacity(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.WORKFORCE_CAPACITY
    quality_prev = _resolve_source_quality(previous, "utilization_snapshots")
    quality_curr = _resolve_source_quality(current, "utilization_snapshots")
    prev_cap = previous.workforce.capacity
    curr_cap = current.workforce.capacity
    comparable = prev_cap is not None and curr_cap is not None
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    candidates: list[ChangeCandidate] = []
    metrics = [
        "utilization_pct",
        "allocated_hours_total",
        "available_hours_total",
        "teams_with_utilization",
        "teams_without_utilization",
    ]
    for metric_key in metrics:
        prev_val = getattr(prev_cap, metric_key)
        curr_val = getattr(curr_cap, metric_key)
        if prev_val is None or curr_val is None:
            continue
        if type(prev_val) is float or type(curr_val) is float:
            raise ChangeIntelligenceIntegrityError(
                "invalid_numeric_value",
                "Workforce capacity metrics must remain Decimal-safe.",
            )
        direction = _direction_for_values(prev_val, curr_val, numeric=True)
        if direction == ChangeDirection.UNCHANGED:
            continue
        try:
            prev_evidence = _find_exact_evidence(
                previous,
                domain=domain,
                metric_key=metric_key,
                source_table="utilization_snapshots",
                source_row_id=_find_evidence_for_claim(
                    previous,
                    source_table="utilization_snapshots",
                    claim_key=metric_key,
                    period=ChangeEvidencePeriod.PREVIOUS,
                )[0].source_row_id,
                period=ChangeEvidencePeriod.PREVIOUS,
            )
            curr_evidence = _find_exact_evidence(
                current,
                domain=domain,
                metric_key=metric_key,
                source_table="utilization_snapshots",
                source_row_id=_find_evidence_for_claim(
                    current,
                    source_table="utilization_snapshots",
                    claim_key=metric_key,
                    period=ChangeEvidencePeriod.CURRENT,
                )[0].source_row_id,
                period=ChangeEvidencePeriod.CURRENT,
            )
        except ChangeIntelligenceIntegrityError:
            continue
        candidate = _make_candidate(
            org_id=current.project.org_id,
            project_id=current.project.project_id,
            candidate_key=f"workforce_capacity.{metric_key}",
            domain=domain,
            metric_key=metric_key,
            source_agent=SourceAgent.WORKFORCE_CAPABILITY,
            source_table="utilization_snapshots",
            previous_row_id=prev_evidence[0].source_row_id,
            current_row_id=curr_evidence[0].source_row_id,
            previous_value=prev_val,
            current_value=curr_val,
            direction=direction,
            previous_quality=quality_prev,
            current_quality=quality_curr,
            previous_evidence=prev_evidence,
            current_evidence=curr_evidence,
            previous_fingerprint=previous.source_fingerprint,
            current_fingerprint=current.source_fingerprint,
            comparison_period=comparison_period,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=[],
        candidates=candidates,
    )


def _compare_sme_coverage(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.SME_COVERAGE
    quality_prev = _resolve_source_quality(previous, "project_skill_requirements")
    quality_curr = _resolve_source_quality(current, "project_skill_requirements")
    prev_summary = previous.workforce.skill_coverage
    curr_summary = current.workforce.skill_coverage
    comparable = prev_summary is not None and curr_summary is not None
    state = _factual_domain_state(
        comparable=comparable,
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    candidates: list[ChangeCandidate] = []
    metrics = [
        "requirement_count",
        "covered_requirement_count",
        "partial_requirement_count",
        "gap_requirement_count",
        "required_headcount_slots",
        "available_headcount_slots",
        "required_sme_slots",
        "available_sme_slots",
    ]
    for metric_key in metrics:
        prev_val = getattr(prev_summary, metric_key)
        curr_val = getattr(curr_summary, metric_key)
        direction = _direction_for_values(prev_val, curr_val, numeric=True)
        if direction == ChangeDirection.UNCHANGED:
            continue
        try:
            prev_evidence = _find_exact_evidence(
                previous,
                domain=domain,
                metric_key=metric_key,
                source_table="project_skill_requirements",
                source_row_id=_find_evidence_for_claim(
                    previous,
                    source_table="project_skill_requirements",
                    claim_key=metric_key,
                    period=ChangeEvidencePeriod.PREVIOUS,
                )[0].source_row_id,
                period=ChangeEvidencePeriod.PREVIOUS,
            )
            curr_evidence = _find_exact_evidence(
                current,
                domain=domain,
                metric_key=metric_key,
                source_table="project_skill_requirements",
                source_row_id=_find_evidence_for_claim(
                    current,
                    source_table="project_skill_requirements",
                    claim_key=metric_key,
                    period=ChangeEvidencePeriod.CURRENT,
                )[0].source_row_id,
                period=ChangeEvidencePeriod.CURRENT,
            )
        except ChangeIntelligenceIntegrityError:
            continue
        candidate = _make_candidate(
            org_id=current.project.org_id,
            project_id=current.project.project_id,
            candidate_key=f"sme_coverage.{metric_key}",
            domain=domain,
            metric_key=metric_key,
            source_agent=SourceAgent.WORKFORCE_CAPABILITY,
            source_table="project_skill_requirements",
            previous_row_id=prev_evidence[0].source_row_id,
            current_row_id=curr_evidence[0].source_row_id,
            previous_value=prev_val,
            current_value=curr_val,
            direction=direction,
            previous_quality=quality_prev,
            current_quality=quality_curr,
            previous_evidence=prev_evidence,
            current_evidence=curr_evidence,
            previous_fingerprint=previous.source_fingerprint,
            current_fingerprint=current.source_fingerprint,
            comparison_period=comparison_period,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=[],
        candidates=candidates,
    )


def _dependencies_by_id(
    items: list[GovernanceDependencyFacts],
) -> dict[UUID, GovernanceDependencyFacts]:
    return {item.dependency_id: item for item in items}


def _compare_governance_dependencies(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.GOVERNANCE_DEPENDENCY
    if current.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE,
            limitations=[],
            candidates=[],
        )
    quality_prev = _resolve_source_quality(previous, "project_dependencies")
    quality_curr = _resolve_source_quality(current, "project_dependencies")
    prev_map = _dependencies_by_id(previous.governance.dependencies)
    curr_map = _dependencies_by_id(current.governance.dependencies)
    shared_ids = set(prev_map) & set(curr_map)
    limitations = [LIMITATION_GOVERNANCE_HISTORY_LIMITED]
    comparable = bool(shared_ids) or bool(prev_map or curr_map)
    state = _factual_domain_state(
        comparable=comparable and bool(shared_ids or (prev_map and curr_map)),
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not shared_ids:
        return _DomainCompareBundle(
            domain=domain,
            state=state if (prev_map or curr_map) else ChangeDomainCoverageState.UNAVAILABLE,
            limitations=limitations,
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    for dependency_id in sorted(shared_ids, key=lambda value: value.hex):
        prev_item = prev_map[dependency_id]
        curr_item = curr_map[dependency_id]
        for metric_key, accessor in (
            ("status", lambda item: item.status),
            ("due_date", lambda item: item.due_date),
            ("resolved_at", lambda item: item.resolved_at),
        ):
            prev_val = accessor(prev_item)
            curr_val = accessor(curr_item)
            direction = _direction_for_values(prev_val, curr_val)
            if direction == ChangeDirection.UNCHANGED:
                continue
            try:
                prev_evidence = _find_exact_evidence(
                    previous,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="project_dependencies",
                    source_row_id=dependency_id,
                    period=ChangeEvidencePeriod.PREVIOUS,
                )
                curr_evidence = _find_exact_evidence(
                    current,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="project_dependencies",
                    source_row_id=dependency_id,
                    period=ChangeEvidencePeriod.CURRENT,
                )
            except ChangeIntelligenceIntegrityError:
                continue
            candidate = _make_candidate(
                org_id=current.project.org_id,
                project_id=current.project.project_id,
                candidate_key=f"governance_dependency.{dependency_id.hex}.{metric_key}",
                domain=domain,
                metric_key=metric_key,
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="project_dependencies",
                previous_row_id=dependency_id,
                current_row_id=dependency_id,
                entity_id=dependency_id,
                previous_value=prev_val,
                current_value=curr_val,
                direction=direction,
                previous_quality=quality_prev,
                current_quality=quality_curr,
                previous_evidence=prev_evidence,
                current_evidence=curr_evidence,
                previous_fingerprint=previous.source_fingerprint,
                current_fingerprint=current.source_fingerprint,
                comparison_period=comparison_period,
                extra_limitations=[LIMITATION_GOVERNANCE_HISTORY_LIMITED],
            )
            if candidate is not None:
                candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=limitations,
        candidates=candidates,
    )


def _compare_governance_actions(
    current: ClientEvidencePack,
    previous: ClientEvidencePack,
    comparison_period: ChangeComparisonPeriod,
) -> _DomainCompareBundle:
    domain = ChangeDomain.GOVERNANCE_ACTION
    if current.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return _DomainCompareBundle(
            domain=domain,
            state=ChangeDomainCoverageState.UNAVAILABLE,
            limitations=[],
            candidates=[],
        )
    quality_prev = _resolve_source_quality(previous, "governance_actions")
    quality_curr = _resolve_source_quality(current, "governance_actions")
    prev_map = _actions_by_id(previous.governance.actions)
    curr_map = _actions_by_id(current.governance.actions)
    shared_ids = set(prev_map) & set(curr_map)
    limitations = [LIMITATION_GOVERNANCE_HISTORY_LIMITED]
    comparable = bool(shared_ids) or bool(prev_map or curr_map)
    state = _factual_domain_state(
        comparable=comparable and bool(shared_ids or (prev_map and curr_map)),
        previous_quality=quality_prev,
        current_quality=quality_curr,
    )
    if not shared_ids:
        return _DomainCompareBundle(
            domain=domain,
            state=state if (prev_map or curr_map) else ChangeDomainCoverageState.UNAVAILABLE,
            limitations=limitations,
            candidates=[],
        )

    candidates: list[ChangeCandidate] = []
    for action_id in sorted(shared_ids, key=lambda value: value.hex):
        prev_item = prev_map[action_id]
        curr_item = curr_map[action_id]
        for metric_key, accessor in (
            ("status", lambda item: item.status),
            ("due_date", lambda item: item.due_date),
            ("completed_at", lambda item: item.completed_at),
        ):
            prev_val = accessor(prev_item)
            curr_val = accessor(curr_item)
            direction = _direction_for_values(prev_val, curr_val)
            if direction == ChangeDirection.UNCHANGED:
                continue
            try:
                prev_evidence = _find_exact_evidence(
                    previous,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="governance_actions",
                    source_row_id=action_id,
                    period=ChangeEvidencePeriod.PREVIOUS,
                )
                curr_evidence = _find_exact_evidence(
                    current,
                    domain=domain,
                    metric_key=metric_key,
                    source_table="governance_actions",
                    source_row_id=action_id,
                    period=ChangeEvidencePeriod.CURRENT,
                )
            except ChangeIntelligenceIntegrityError:
                continue
            candidate = _make_candidate(
                org_id=current.project.org_id,
                project_id=current.project.project_id,
                candidate_key=f"governance_action.{action_id.hex}.{metric_key}",
                domain=domain,
                metric_key=metric_key,
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="governance_actions",
                previous_row_id=action_id,
                current_row_id=action_id,
                entity_id=action_id,
                previous_value=prev_val,
                current_value=curr_val,
                direction=direction,
                previous_quality=quality_prev,
                current_quality=quality_curr,
                previous_evidence=prev_evidence,
                current_evidence=curr_evidence,
                previous_fingerprint=previous.source_fingerprint,
                current_fingerprint=current.source_fingerprint,
                comparison_period=comparison_period,
                extra_limitations=[LIMITATION_GOVERNANCE_HISTORY_LIMITED],
            )
            if candidate is not None:
                candidates.append(candidate)
    return _DomainCompareBundle(
        domain=domain,
        state=state,
        limitations=limitations,
        candidates=candidates,
    )


def _actions_by_id(
    items: list[GovernanceActionFacts],
) -> dict[UUID, GovernanceActionFacts]:
    return {item.action_id: item for item in items}


def _evaluate_policy(
    policy: ChangeMaterialityPolicy,
    context: ChangeCandidateContext,
) -> ChangeMaterialityPolicyDecision:
    isolated = copy.deepcopy(context)
    try:
        raw = policy.evaluate(isolated)
    except ChangeIntelligenceIntegrityError:
        raise
    except Exception as exc:
        raise ChangeIntelligenceIntegrityError(
            "invalid_policy",
            "Change materiality policy evaluation failed.",
        ) from exc
    try:
        decision = ChangeMaterialityPolicyDecision.model_validate(raw)
    except ValidationError as exc:
        raise ChangeIntelligenceIntegrityError(
            "invalid_policy_decision",
            "Change materiality policy returned an invalid decision.",
        ) from exc
    return decision


def _materialize_changes(
    decision: ChangeMaterialityPolicyDecision,
    *,
    candidates_by_key: dict[str, ChangeCandidate],
) -> tuple[list[ChangeItem], list[ChangeEvidenceReference]]:
    known = set(candidates_by_key)
    selected_keys = [item.candidate_key for item in decision.selections]
    if len(selected_keys) != len(set(selected_keys)):
        raise ChangeIntelligenceIntegrityError(
            "invalid_policy_decision",
            "Policy selections contain duplicate candidate keys.",
        )
    unknown = set(selected_keys) - known
    if unknown:
        raise ChangeIntelligenceIntegrityError(
            "invalid_policy_decision",
            "Policy referenced unknown candidate keys.",
        )

    changes: list[ChangeItem] = []
    for selection in sorted(
        decision.selections,
        key=lambda item: (item.priority, item.candidate_key),
    ):
        candidate = candidates_by_key[selection.candidate_key]
        if not candidate.is_reliable:
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy_decision",
                "Policy cannot publish unreliable candidates.",
            )
        if (
            candidate.previous_value.model_dump(mode="python")
            != candidates_by_key[selection.candidate_key].previous_value.model_dump(
                mode="python"
            )
        ):
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy_decision",
                "Policy cannot mutate candidate previous_value.",
            )
        if candidate.direction != candidates_by_key[selection.candidate_key].direction:
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy_decision",
                "Policy cannot mutate candidate direction.",
            )
        original = candidates_by_key[selection.candidate_key]
        if candidate.org_id != original.org_id:
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy_decision",
                "Policy cannot mutate candidate org_id.",
            )
        if candidate.project_id != original.project_id:
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy_decision",
                "Policy cannot mutate candidate project_id.",
            )
        if candidate.comparison_period != original.comparison_period:
            raise ChangeIntelligenceIntegrityError(
                "invalid_policy_decision",
                "Policy cannot mutate candidate comparison_period.",
            )
        changes.append(
            ChangeItem(
                org_id=candidate.org_id,
                project_id=candidate.project_id,
                candidate_key=candidate.candidate_key,
                domain=candidate.domain,
                metric_key=candidate.metric_key,
                comparison_identity=candidate.comparison_identity,
                previous_source=candidate.previous_source,
                current_source=candidate.current_source,
                previous_value=candidate.previous_value,
                current_value=candidate.current_value,
                direction=candidate.direction,
                materiality=selection.materiality,
                business_meaning_code=selection.business_meaning_code,
                priority=selection.priority,
                previous_evidence=list(candidate.previous_evidence),
                current_evidence=list(candidate.current_evidence),
                previous_source_fingerprint=candidate.previous_source_fingerprint,
                current_source_fingerprint=candidate.current_source_fingerprint,
                previous_data_quality=(
                    candidate.previous_data_quality or DataQualityState.UNAVAILABLE
                ),
                current_data_quality=(
                    candidate.current_data_quality or DataQualityState.UNAVAILABLE
                ),
                comparison_period=candidate.comparison_period,
                limitations=list(candidate.limitations),
            )
        )
    evidence = _canonical_evidence_union(
        [ref for item in changes for ref in item.previous_evidence + item.current_evidence]
    )
    return changes, evidence


def _domain_coverage_unavailable(
    *, policy_evaluated: bool
) -> list[ChangeDomainCoverageItem]:
    items: list[ChangeDomainCoverageItem] = []
    for domain in _ALL_DOMAINS:
        if domain in {ChangeDomain.READINESS, ChangeDomain.RESOURCE_ONBOARDING}:
            state = ChangeDomainCoverageState.UNAVAILABLE
        elif policy_evaluated:
            state = ChangeDomainCoverageState.POLICY_NOT_EVALUATED
        else:
            state = ChangeDomainCoverageState.UNAVAILABLE
        items.append(ChangeDomainCoverageItem(domain=domain, state=state))
    return items


def _finalize_domain_coverage(
    factual_outcomes: list[ChangeDomainComparisonOutcome],
    candidates: list[ChangeCandidate],
    *,
    policy_evaluated: bool,
) -> list[ChangeDomainCoverageItem]:
    by_domain: dict[ChangeDomain, list[ChangeCandidate]] = {
        domain: [] for domain in _ALL_DOMAINS
    }
    for candidate in candidates:
        by_domain[candidate.domain].append(candidate)

    coverage: list[ChangeDomainCoverageItem] = []
    for outcome in factual_outcomes:
        domain = outcome.domain
        state = outcome.state
        if state == ChangeDomainCoverageState.EVALUATED:
            reliable_changed = [
                item for item in by_domain[domain] if item.is_reliable
            ]
            if reliable_changed and not policy_evaluated:
                state = ChangeDomainCoverageState.POLICY_NOT_EVALUATED
        coverage.append(ChangeDomainCoverageItem(domain=domain, state=state))
    return coverage


def _domain_limitations(
    coverage: list[ChangeDomainCoverageItem],
) -> list[str]:
    limitations: list[str] = []
    for item in coverage:
        if item.domain == ChangeDomain.READINESS:
            limitations.append(LIMITATION_READINESS_INTELLIGENCE_UNAVAILABLE)
        if item.domain == ChangeDomain.RESOURCE_ONBOARDING:
            limitations.append(LIMITATION_RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE)
    return limitations


def _availability_from_coverage(
    coverage: list[ChangeDomainCoverageItem],
    limitations: list[str],
) -> ChangeIntelligenceAvailability:
    if LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE in limitations:
        return ChangeIntelligenceAvailability.UNAVAILABLE
    states = {item.state for item in coverage}
    if (
        ChangeDomainCoverageState.EVALUATED in states
        or ChangeDomainCoverageState.POLICY_NOT_EVALUATED in states
        or ChangeDomainCoverageState.UNRELIABLE in states
    ):
        return ChangeIntelligenceAvailability.PARTIAL
    return ChangeIntelligenceAvailability.UNAVAILABLE


def policy_ready_limitations(limitations: list[str]) -> bool:
    return LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE not in limitations


def _canonicalize_limitations(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _sort_candidates(candidates: list[ChangeCandidate]) -> list[ChangeCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.domain.value,
            item.metric_key,
            item.candidate_key,
        ),
    )


def _sort_changes(changes: list[ChangeItem]) -> list[ChangeItem]:
    return sorted(
        changes,
        key=lambda item: (item.priority, item.domain.value, item.candidate_key),
    )


def _sort_evidence(
    refs: list[ChangeEvidenceReference],
) -> list[ChangeEvidenceReference]:
    return sorted(
        refs,
        key=lambda ref: (
            ref.period.value,
            ref.source_table,
            str(ref.source_row_id),
            tuple(ref.claim_keys),
            ref.source_fingerprint,
            ref.observed_at.isoformat() if ref.observed_at else "",
        ),
    )
