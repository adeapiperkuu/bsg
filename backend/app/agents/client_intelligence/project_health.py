"""Deterministic Project Health Engine foundation (roadmap 8.1).

Policy-driven classification only. No production thresholds, no LLM,
no database access, no persistence, and no Delivery Confidence recalculation.
CI-DQ07 remains unresolved.

The injected policy selects status and drivers. It may not invent source facts:
DIRECT signal values must equal governed ClientEvidencePack facts proven by
exact evidence identity and claim keys.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    SourceAgent,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    reference_supports_claim_keys,
    source_agent_owns_table,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.health_contracts import (
    ProjectHealthAssessment,
    ProjectHealthBindingType,
    ProjectHealthDriver,
    ProjectHealthDriverPolarity,
    ProjectHealthEvidenceRef,
    ProjectHealthHistoryComparison,
    ProjectHealthPolicyDecision,
    ProjectHealthSignal,
    ProjectHealthSignalState,
    ProjectHealthStatus,
    ProjectHealthTrend,
)
from app.agents.client_intelligence.health_policy import ProjectHealthPolicy
from app.db.models import AppRole

LIMITATION_POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
LIMITATION_REQUIRED_SIGNAL_MISSING = "REQUIRED_SIGNAL_MISSING"
LIMITATION_REQUIRED_SIGNAL_UNAVAILABLE = "REQUIRED_SIGNAL_UNAVAILABLE"
LIMITATION_REQUIRED_SIGNAL_STALE = "REQUIRED_SIGNAL_STALE"
LIMITATION_REQUIRED_SIGNAL_CONFLICTING = "REQUIRED_SIGNAL_CONFLICTING"
LIMITATION_GREEN_BLOCKED_UNRELIABLE_REQUIRED = "GREEN_BLOCKED_UNRELIABLE_REQUIRED"
LIMITATION_GREEN_BLOCKED_NO_RELIABLE_POSITIVE = "GREEN_BLOCKED_NO_RELIABLE_POSITIVE"
LIMITATION_AMBER_BLOCKED_NO_RELIABLE_SUPPORT = "AMBER_BLOCKED_NO_RELIABLE_SUPPORT"
LIMITATION_RED_BLOCKED_NO_RELIABLE_SUPPORT = "RED_BLOCKED_NO_RELIABLE_SUPPORT"
LIMITATION_EVIDENCE_PACK_INCOMPLETE = "EVIDENCE_PACK_INCOMPLETE"
LIMITATION_RED_RETAINED_WITH_OPTIONAL_LIMITATION = "RED_RETAINED_WITH_OPTIONAL_LIMITATION"
LIMITATION_HISTORY_UNAVAILABLE = "HISTORY_COMPARISON_UNAVAILABLE"
LIMITATION_HISTORY_INSUFFICIENT = "HISTORY_COMPARISON_INSUFFICIENT"
LIMITATION_HISTORY_RULES_MISMATCH = "HISTORY_COMPARISON_RULES_MISMATCH"
LIMITATION_HISTORY_PERIOD_MISMATCH = "HISTORY_COMPARISON_PERIOD_MISMATCH"
LIMITATION_HISTORY_VISIBILITY_MISMATCH = "HISTORY_COMPARISON_VISIBILITY_MISMATCH"
LIMITATION_POSITIVE_EMPTY_ADVERSE_UNPROVEN = "POSITIVE_EMPTY_ADVERSE_UNPROVEN"
LIMITATION_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

_STATUS_RANK = {
    ProjectHealthStatus.RED: 0,
    ProjectHealthStatus.AMBER: 1,
    ProjectHealthStatus.GREEN: 2,
}
_RELIABLE_STATES = frozenset(
    {
        ProjectHealthSignalState.POSITIVE,
        ProjectHealthSignalState.NEUTRAL,
        ProjectHealthSignalState.WATCH,
        ProjectHealthSignalState.ADVERSE,
    }
)
_UNRELIABLE_STATES = frozenset(
    {
        ProjectHealthSignalState.UNAVAILABLE,
        ProjectHealthSignalState.STALE,
        ProjectHealthSignalState.CONFLICTING,
    }
)
# Narrow foundation domains — not a general multi-source health scorer.
_HEALTH_SUPPORTED_SOURCE_TABLES = frozenset(
    {"projects", "delivery_confidence_scores"}
)
_HEALTH_SOURCE_ALIASES: dict[str, frozenset[str]] = {
    "projects": frozenset({"projects"}),
    "delivery_confidence_scores": frozenset(
        {"delivery_confidence", "delivery_confidence_scores"}
    ),
}


class ProjectHealthIntegrityError(Exception):
    """Deterministic Project Health integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class VerifiedSourceFact:
    """Engine-resolved governed fact for DIRECT health binding."""

    __slots__ = (
        "source_agent",
        "source_table",
        "source_row_id",
        "claim_key",
        "value",
        "observed_at",
    )

    def __init__(
        self,
        *,
        source_agent: SourceAgent,
        source_table: str,
        source_row_id: UUID,
        claim_key: str,
        value: Any,
        observed_at: datetime | None,
    ) -> None:
        self.source_agent = source_agent
        self.source_table = source_table
        self.source_row_id = source_row_id
        self.claim_key = claim_key
        self.value = value
        self.observed_at = observed_at


def assess_project_health(
    pack: ClientEvidencePack,
    *,
    policy: ProjectHealthPolicy | None,
    previous: ProjectHealthAssessment | None = None,
) -> ProjectHealthAssessment:
    """Classify project health from a validated evidence pack and injected policy."""
    _validate_pack_or_raise(pack)

    if policy is None:
        assessment = _insufficient_without_policy(pack)
        return _with_history(assessment, pack, previous=previous, policy=None)

    rules_version = _require_rules_version(policy)
    declared_required = _require_required_signal_keys(policy)
    decision = _evaluate_policy(policy, pack)
    normalized = _normalize_and_validate_decision(
        pack, decision, declared_required=declared_required
    )
    final_status, dq_limitations = _apply_data_quality_overrides(pack, normalized)
    signals = _sort_signals(normalized.signals)
    positive = _sort_drivers(normalized.positive_drivers)
    negative = _sort_drivers(normalized.negative_drivers)
    evidence = _collect_assessment_evidence(signals, positive, negative)
    limitations = _canonicalize_strings(
        list(pack.limitations)
        + [
            f"DQ_{item.source}_{item.state.value}".upper().replace("-", "_")
            for item in pack.data_quality
            if item.state != DataQualityState.COMPLETE
        ]
        + [f"VISIBILITY_{item.reason}".upper() for item in pack.visibility_limitations]
        + list(normalized.policy_limitations)
        + dq_limitations
    )
    assessment = ProjectHealthAssessment(
        org_id=pack.project.org_id,
        project_id=pack.project.project_id,
        reporting_period=pack.reporting_period,
        visibility_mode=pack.visibility_mode,
        status=final_status,
        rules_version=rules_version,
        source_fingerprint=pack.source_fingerprint,
        policy_fingerprint=pack.policy_fingerprint,
        overall_data_quality=pack.overall_data_quality,
        signals=signals,
        positive_drivers=positive,
        negative_drivers=negative,
        limitations=limitations,
        evidence=evidence,
        history=ProjectHealthHistoryComparison(
            current_status=final_status,
            trend=ProjectHealthTrend.UNKNOWN,
            limitation=LIMITATION_HISTORY_UNAVAILABLE,
        ),
        assessed_at=pack.generated_at,
    )
    return _with_history(assessment, pack, previous=previous, policy=policy)


def _validate_pack_or_raise(pack: ClientEvidencePack) -> None:
    role = (
        AppRole.CLIENT
        if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
        else AppRole.DELIVERY_MANAGER
    )
    result = validate_client_evidence_pack(pack, role=role)
    if not result.is_valid:
        raise EvidencePackIntegrityError(result)


def _require_rules_version(policy: ProjectHealthPolicy) -> str:
    try:
        version = policy.rules_version
    except Exception as exc:  # noqa: BLE001 — sanitize all policy-owned failures
        raise ProjectHealthIntegrityError(
            "invalid_policy",
            "Health policy rules_version is inaccessible.",
        ) from exc
    if not isinstance(version, str) or not version.strip():
        raise ProjectHealthIntegrityError(
            "invalid_policy",
            "Health policy rules_version must be a non-empty string.",
        )
    return version.strip()


def _require_required_signal_keys(policy: ProjectHealthPolicy) -> frozenset[str]:
    try:
        raw = policy.required_signal_keys()
        if isinstance(raw, str | bytes) or raw is None or isinstance(raw, Mapping):
            raise TypeError("required_signal_keys must be a unique key collection")
        if not isinstance(raw, Collection):
            raise TypeError("required_signal_keys must be a unique key collection")
        keys = list(raw)
        if not keys:
            raise ValueError("required_signal_keys must be non-empty")
        if len(keys) != len(set(keys)):
            raise ValueError("required_signal_keys must be unique")
        validated = ProjectHealthPolicyDecision.model_validate(
            {
                "proposed_status": ProjectHealthStatus.INSUFFICIENT,
                "required_signal_keys": list(keys),
            }
        )
        return frozenset(validated.required_signal_keys)
    except Exception as exc:  # noqa: BLE001 — sanitize all policy-owned failures
        raise ProjectHealthIntegrityError(
            "invalid_policy",
            "Health policy required_signal_keys failed.",
        ) from exc


def _evaluate_policy(
    policy: ProjectHealthPolicy, pack: ClientEvidencePack
) -> ProjectHealthPolicyDecision:
    try:
        decision = policy.evaluate(pack)
    except Exception as exc:  # noqa: BLE001 — sanitize all policy-owned failures
        raise ProjectHealthIntegrityError(
            "invalid_policy",
            "Injected health policy failed during evaluation.",
        ) from exc
    if not isinstance(decision, ProjectHealthPolicyDecision):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Health policy did not return a ProjectHealthPolicyDecision.",
        )
    return decision


def _insufficient_without_policy(pack: ClientEvidencePack) -> ProjectHealthAssessment:
    limitations = _canonicalize_strings(
        [LIMITATION_POLICY_UNAVAILABLE]
        + list(pack.limitations)
        + [
            f"DQ_{item.source}_{item.state.value}".upper().replace("-", "_")
            for item in pack.data_quality
            if item.state != DataQualityState.COMPLETE
        ]
        + [f"VISIBILITY_{item.reason}".upper() for item in pack.visibility_limitations]
    )
    return ProjectHealthAssessment(
        org_id=pack.project.org_id,
        project_id=pack.project.project_id,
        reporting_period=pack.reporting_period,
        visibility_mode=pack.visibility_mode,
        status=ProjectHealthStatus.INSUFFICIENT,
        rules_version=None,
        source_fingerprint=pack.source_fingerprint,
        policy_fingerprint=pack.policy_fingerprint,
        overall_data_quality=pack.overall_data_quality,
        signals=[],
        positive_drivers=[],
        negative_drivers=[],
        limitations=limitations,
        evidence=[],
        history=ProjectHealthHistoryComparison(
            current_status=ProjectHealthStatus.INSUFFICIENT,
            trend=ProjectHealthTrend.UNKNOWN,
            limitation=LIMITATION_HISTORY_UNAVAILABLE,
        ),
        assessed_at=pack.generated_at,
    )


def _evidence_identity_key(
    item: ProjectHealthEvidenceRef | ClientEvidenceReference,
) -> tuple[str, str, str, str]:
    return (
        item.source_agent.value,
        item.source_table,
        str(item.source_row_id),
        item.visibility.value,
    )


def _pack_evidence_index(
    pack: ClientEvidencePack,
) -> dict[tuple[str, str, str, str], ClientEvidenceReference]:
    return {_evidence_identity_key(item): item for item in pack.evidence}


def _fact_key(table: str, row_id: UUID, claim_key: str) -> tuple[str, str, str]:
    return (table, str(row_id), claim_key)


def resolve_verified_source_facts(
    pack: ClientEvidencePack,
) -> dict[tuple[str, str, str], VerifiedSourceFact]:
    """Resolve pack-owned direct facts that Project Health may bind to."""
    facts: dict[tuple[str, str, str], VerifiedSourceFact] = {}
    project = pack.project
    for claim_key, value in (
        ("project_status", project.project_status),
        ("project_id", project.project_id),
        ("project_name", project.project_name),
    ):
        facts[_fact_key("projects", project.project_id, claim_key)] = VerifiedSourceFact(
            source_agent=SourceAgent.DELIVERY_PERFORMANCE,
            source_table="projects",
            source_row_id=project.project_id,
            claim_key=claim_key,
            value=value,
            observed_at=None,
        )
    confidence = pack.delivery.latest_delivery_confidence
    if confidence is not None:
        for claim_key, value in (
            ("score_pct", confidence.score_pct),
            ("confidence_status", confidence.status),
            ("forecast_completion_date", confidence.forecast_completion_date),
        ):
            facts[_fact_key("delivery_confidence_scores", confidence.id, claim_key)] = (
                VerifiedSourceFact(
                    source_agent=SourceAgent.DELIVERY_PERFORMANCE,
                    source_table="delivery_confidence_scores",
                    source_row_id=confidence.id,
                    claim_key=claim_key,
                    value=value,
                    observed_at=confidence.observed_at,
                )
            )
    return facts


def _matching_source_quality_issues(
    pack: ClientEvidencePack, source_table: str
) -> list[DataQualityIssue]:
    aliases = _HEALTH_SOURCE_ALIASES.get(source_table, frozenset({source_table}))
    return [issue for issue in pack.data_quality if issue.source in aliases]


def resolve_health_source_quality(
    pack: ClientEvidencePack, source_table: str
) -> DataQualityState:
    """Derive engine-owned source quality from the validated pack only.

    Foundation domains only — not a general multi-source scorer. No freshness
    thresholds and no timestamp inference (CI-DQ07 remains unresolved).
    """
    if source_table not in _HEALTH_SUPPORTED_SOURCE_TABLES:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Project Health foundation does not support the declared source_table.",
        )
    if source_table == "projects":
        # Validated packs always carry required ProjectIdentityFacts.
        if (
            pack.project.project_id is None
            or pack.project.org_id is None
            or not pack.project.project_status
            or not pack.project.project_name
        ):
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "Projects source identity is incomplete in the pack.",
            )
        return DataQualityState.COMPLETE

    # delivery_confidence_scores
    issues = _matching_source_quality_issues(pack, source_table)
    if not issues:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence source quality is not declared in the pack.",
        )
    states = {issue.state for issue in issues}
    if len(states) != 1:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence source quality is ambiguous or conflicting.",
        )
    state = next(iter(states))
    present = pack.delivery.latest_delivery_confidence is not None
    if state == DataQualityState.UNAVAILABLE:
        if present:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "Delivery Confidence fact presence disagrees with pack quality.",
            )
        return state
    if not present:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence is absent without matching UNAVAILABLE quality.",
        )
    return state


def _source_unavailable_for_table(pack: ClientEvidencePack, source_table: str) -> bool:
    """True only when absence and matching UNAVAILABLE quality are both proven."""
    if source_table not in _HEALTH_SUPPORTED_SOURCE_TABLES:
        return False
    if source_table == "projects":
        return False
    if pack.delivery.latest_delivery_confidence is not None:
        return False
    try:
        return (
            resolve_health_source_quality(pack, source_table)
            == DataQualityState.UNAVAILABLE
        )
    except ProjectHealthIntegrityError:
        return False


def _assert_signal_matches_source_quality(
    signal: ProjectHealthSignal,
    *,
    resolved: DataQualityState,
) -> None:
    """Reject policy-authored quality/state that disagree with pack-owned quality."""
    if signal.data_quality != resolved:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Signal data_quality does not match the pack-owned source quality.",
        )

    if resolved == DataQualityState.COMPLETE:
        if signal.binding_type == ProjectHealthBindingType.UNAVAILABLE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "COMPLETE sources cannot be represented as UNAVAILABLE.",
            )
        if signal.signal_state in _UNRELIABLE_STATES:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "COMPLETE sources cannot use unreliable signal states.",
            )
        return

    if resolved == DataQualityState.STALE:
        if signal.signal_state != ProjectHealthSignalState.STALE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "STALE sources must use STALE signal state.",
            )
        if signal.binding_type == ProjectHealthBindingType.UNAVAILABLE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "STALE sources cannot be labeled UNAVAILABLE.",
            )
        return

    if resolved == DataQualityState.CONFLICTING:
        if signal.signal_state != ProjectHealthSignalState.CONFLICTING:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "CONFLICTING sources must use CONFLICTING signal state.",
            )
        if signal.binding_type == ProjectHealthBindingType.UNAVAILABLE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "CONFLICTING sources cannot be labeled UNAVAILABLE.",
            )
        return

    if resolved == DataQualityState.UNAVAILABLE:
        if signal.binding_type != ProjectHealthBindingType.UNAVAILABLE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE sources require UNAVAILABLE binding.",
            )
        if signal.observed_value is not None:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE sources must omit observed_value.",
            )
        if signal.signal_state != ProjectHealthSignalState.UNAVAILABLE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE sources must use UNAVAILABLE signal state.",
            )
        if signal.limitation is None:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE sources require a structured limitation.",
            )
        return

    # PARTIAL (and any other declared pack state): exact match only; unreliable.
    if signal.binding_type == ProjectHealthBindingType.UNAVAILABLE:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Non-unavailable pack quality cannot use UNAVAILABLE binding.",
        )


def _assert_supported_health_source(
    *,
    source_agent: SourceAgent,
    source_table: str,
) -> None:
    if source_table not in _HEALTH_SUPPORTED_SOURCE_TABLES:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Project Health foundation does not support the declared source_table.",
        )
    if not source_agent_owns_table(source_agent, source_table):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Declared source_agent does not own the declared source_table.",
        )


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        return False
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return left == right
    if isinstance(left, UUID) or isinstance(right, UUID):
        return str(left) == str(right)
    return left == right


def _canonicalize_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


def _sort_evidence(
    refs: list[ProjectHealthEvidenceRef],
) -> list[ProjectHealthEvidenceRef]:
    return sorted(
        refs,
        key=lambda ref: (*_evidence_identity_key(ref), tuple(ref.claim_keys)),
    )


def _sort_signals(signals: list[ProjectHealthSignal]) -> list[ProjectHealthSignal]:
    return sorted(signals, key=lambda item: item.signal_key)


def _sort_drivers(drivers: list[ProjectHealthDriver]) -> list[ProjectHealthDriver]:
    return sorted(
        drivers,
        key=lambda item: (
            item.materiality,
            item.polarity.value,
            item.driver_key,
            tuple(
                (*_evidence_identity_key(ref), tuple(ref.claim_keys))
                for ref in _sort_evidence(item.evidence)
            ),
        ),
    )


def _collect_assessment_evidence(
    signals: list[ProjectHealthSignal],
    positive: list[ProjectHealthDriver],
    negative: list[ProjectHealthDriver],
) -> list[ProjectHealthEvidenceRef]:
    collected: dict[tuple[str, str, str, str], set[str]] = {}
    templates: dict[tuple[str, str, str, str], ProjectHealthEvidenceRef] = {}
    for signal in signals:
        for ref in signal.evidence:
            key = _evidence_identity_key(ref)
            templates[key] = ref
            collected.setdefault(key, set()).update(ref.claim_keys)
    for driver in positive + negative:
        for ref in driver.evidence:
            key = _evidence_identity_key(ref)
            templates[key] = ref
            collected.setdefault(key, set()).update(ref.claim_keys)
    merged: list[ProjectHealthEvidenceRef] = []
    for key, claim_keys in collected.items():
        template = templates[key]
        merged.append(
            ProjectHealthEvidenceRef(
                source_agent=template.source_agent,
                source_table=template.source_table,
                source_row_id=template.source_row_id,
                visibility=template.visibility,
                claim_keys=sorted(claim_keys),
            )
        )
    return _sort_evidence(merged)


def _signal_is_reliable(signal: ProjectHealthSignal) -> bool:
    if signal.binding_type == ProjectHealthBindingType.UNAVAILABLE:
        return False
    # After validation, data_quality equals pack-owned quality. Only COMPLETE
    # source quality may participate in reliable driver support.
    if signal.data_quality != DataQualityState.COMPLETE:
        return False
    if signal.signal_state in _UNRELIABLE_STATES:
        return False
    return signal.signal_state in _RELIABLE_STATES


def _validate_evidence_refs(
    refs: list[ProjectHealthEvidenceRef],
    *,
    pack_index: dict[tuple[str, str, str, str], ClientEvidenceReference],
    client_safe: bool,
) -> list[ProjectHealthEvidenceRef]:
    """Validate refs and merge duplicate identities into a claim-key union."""
    by_identity: dict[tuple[str, str, str, str], ProjectHealthEvidenceRef] = {}
    claim_union: dict[tuple[str, str, str, str], set[str]] = {}
    for ref in refs:
        key = _evidence_identity_key(ref)
        pack_ref = pack_index.get(key)
        if pack_ref is None:
            raise ProjectHealthIntegrityError(
                "unsupported_evidence_reference",
                "Health output references evidence absent from the pack.",
            )
        if client_safe and (
            ref.visibility != EvidenceVisibility.CLIENT_SAFE
            or pack_ref.visibility != EvidenceVisibility.CLIENT_SAFE
        ):
            raise ProjectHealthIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE health assessment cannot include internal evidence.",
            )
        if not reference_supports_claim_keys(
            pack_ref, ref.claim_keys, client_safe=client_safe
        ):
            raise ProjectHealthIntegrityError(
                "unsupported_evidence_reference",
                "Claim keys are not supported by pack evidence.",
            )
        by_identity.setdefault(key, ref)
        claim_union.setdefault(key, set()).update(ref.claim_keys)

    normalized: list[ProjectHealthEvidenceRef] = []
    for key, ref in by_identity.items():
        claims = sorted(claim_union[key])
        pack_ref = pack_index[key]
        if not reference_supports_claim_keys(pack_ref, claims, client_safe=client_safe):
            raise ProjectHealthIntegrityError(
                "unsupported_evidence_reference",
                "Merged claim keys are not supported by pack evidence.",
            )
        normalized.append(
            ProjectHealthEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=claims,
            )
        )
    return _sort_evidence(normalized)


def _validate_signal(
    signal: ProjectHealthSignal,
    *,
    pack: ClientEvidencePack,
    pack_index: dict[tuple[str, str, str, str], ClientEvidenceReference],
    verified_facts: dict[tuple[str, str, str], VerifiedSourceFact],
    client_safe: bool,
) -> ProjectHealthSignal:
    _assert_supported_health_source(
        source_agent=signal.source_agent,
        source_table=signal.source_table,
    )
    resolved_quality = resolve_health_source_quality(pack, signal.source_table)
    _assert_signal_matches_source_quality(signal, resolved=resolved_quality)

    evidence = _validate_evidence_refs(
        signal.evidence,
        pack_index=pack_index,
        client_safe=client_safe,
    )
    if signal.binding_type == ProjectHealthBindingType.UNAVAILABLE:
        if resolved_quality != DataQualityState.UNAVAILABLE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE binding requires pack-owned UNAVAILABLE source quality.",
            )
        if evidence:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE sources cannot retain COMPLETE evidence as unreliable.",
            )
        if not _source_unavailable_for_table(pack, signal.source_table):
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "UNAVAILABLE signal omitted evidence without pack unavailability.",
            )
        return signal.model_copy(update={"evidence": evidence})

    if not evidence:
        raise ProjectHealthIntegrityError(
            "unsupported_evidence_reference",
            "DIRECT signals require pack evidence.",
        )
    if resolved_quality == DataQualityState.UNAVAILABLE:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "UNAVAILABLE sources cannot use DIRECT binding.",
        )

    for ref in evidence:
        if ref.source_table != signal.source_table:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "DIRECT signal source_table does not match its evidence.",
            )
        if ref.source_agent != signal.source_agent:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "DIRECT signal source_agent does not match its evidence.",
            )

    # One PRIMARY claim key per DIRECT signal: all claim keys must resolve to the
    # same governed (value, observed_at) pair for this exact source row.
    primary_fact: VerifiedSourceFact | None = None
    for ref in evidence:
        pack_ref = pack_index[_evidence_identity_key(ref)]
        if not reference_supports_claim_keys(
            pack_ref, ref.claim_keys, client_safe=client_safe
        ):
            raise ProjectHealthIntegrityError(
                "unsupported_evidence_reference",
                "Signal claim keys are not supported by pack evidence.",
            )
        for claim_key in ref.claim_keys:
            fact = verified_facts.get(
                _fact_key(ref.source_table, ref.source_row_id, claim_key)
            )
            if fact is None:
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Signal claims an unsupported or unbound source fact.",
                )
            if fact.source_agent != signal.source_agent:
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Signal source_agent does not match the verified pack fact.",
                )
            if fact.source_table != signal.source_table:
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Signal source_table does not match the verified pack fact.",
                )
            if fact.source_agent != ref.source_agent:
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Signal evidence source agent does not match the pack fact.",
                )
            if primary_fact is None:
                primary_fact = fact
            elif primary_fact.claim_key != fact.claim_key:
                # Prefer one exact fact claim; unrelated same-valued claims
                # are not treated as the same governed fact.
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "DIRECT signal must bind to one unambiguous governed fact.",
                )
            elif not (
                _values_equal(primary_fact.value, fact.value)
                and primary_fact.observed_at == fact.observed_at
                and primary_fact.source_row_id == fact.source_row_id
                and primary_fact.source_table == fact.source_table
            ):
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "DIRECT signal must bind to one unambiguous governed fact.",
                )
            if (
                pack_ref.observed_at is not None
                and fact.observed_at is not None
                and pack_ref.observed_at != fact.observed_at
            ):
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Signal observed_at does not match pack evidence timestamp.",
                )

    if primary_fact is None:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "DIRECT signal has no verified source fact.",
        )
    if type(signal.observed_value) is float:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Float observed values are not accepted for source-bound facts.",
        )
    if isinstance(primary_fact.value, Decimal) and not isinstance(
        signal.observed_value, Decimal
    ):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Delivery Confidence Decimal values must remain Decimal-safe.",
        )
    if not _values_equal(signal.observed_value, primary_fact.value):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "DIRECT signal observed_value does not match the governed source fact.",
        )
    if signal.observed_at != primary_fact.observed_at:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "DIRECT signal observed_at does not match the source fact timestamp.",
        )
    return signal.model_copy(update={"evidence": evidence})


def _validate_driver(
    driver: ProjectHealthDriver,
    *,
    signal_map: dict[str, ProjectHealthSignal],
    pack_index: dict[tuple[str, str, str, str], ClientEvidenceReference],
    client_safe: bool,
) -> ProjectHealthDriver:
    if not driver.signal_keys:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Health drivers must declare at least one signal key.",
        )
    unknown = [key for key in driver.signal_keys if key not in signal_map]
    if unknown:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Health driver references an unknown signal key.",
        )
    linked = [signal_map[key] for key in driver.signal_keys]
    if all(not _signal_is_reliable(signal) for signal in linked):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Material drivers cannot be supported only by unreliable signals.",
        )
    if all(
        signal.binding_type == ProjectHealthBindingType.UNAVAILABLE for signal in linked
    ):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Material drivers cannot be supported only by UNAVAILABLE signals.",
        )

    signal_evidence_union: dict[tuple[str, str, str, str], ProjectHealthEvidenceRef] = {}
    signal_claim_union: dict[tuple[str, str, str, str], set[str]] = {}
    for signal in linked:
        for ref in signal.evidence:
            key = _evidence_identity_key(ref)
            signal_evidence_union[key] = ref
            signal_claim_union.setdefault(key, set()).update(ref.claim_keys)

    evidence = _validate_evidence_refs(
        driver.evidence,
        pack_index=pack_index,
        client_safe=client_safe,
    )
    for ref in evidence:
        key = _evidence_identity_key(ref)
        if key not in signal_evidence_union:
            raise ProjectHealthIntegrityError(
                "unsupported_evidence_reference",
                "Driver evidence must be a subset of linked signal evidence.",
            )
        if not set(ref.claim_keys).issubset(signal_claim_union[key]):
            raise ProjectHealthIntegrityError(
                "unsupported_evidence_reference",
                "Driver claim keys must support the linked signals.",
            )
    if driver.reason_code in {
        "ZERO_OPEN_RISKS_ASSUMED",
        "EMPTY_ADVERSE_ASSUMED_POSITIVE",
        "ON_TRACK_ASSUMED",
    }:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Positive driver reason code is not permitted without proven completeness.",
        )
    return driver.model_copy(update={"evidence": evidence})


def _normalize_and_validate_decision(
    pack: ClientEvidencePack,
    decision: ProjectHealthPolicyDecision,
    *,
    declared_required: frozenset[str],
) -> ProjectHealthPolicyDecision:
    if decision.proposed_status not in {
        ProjectHealthStatus.GREEN,
        ProjectHealthStatus.AMBER,
        ProjectHealthStatus.RED,
        ProjectHealthStatus.INSUFFICIENT,
    }:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Unsupported proposed health status.",
        )

    required = frozenset(decision.required_signal_keys)
    if required != declared_required:
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Decision required_signal_keys must match policy declaration exactly.",
        )
    missing_unreliable = frozenset(decision.missing_unreliable_required_signal_keys)
    if not missing_unreliable.issubset(required):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "missing_unreliable_required_signal_keys must be a subset of required keys.",
        )

    signal_keys = [item.signal_key for item in decision.signals]
    if len(signal_keys) != len(set(signal_keys)):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Duplicate health signal keys are not allowed.",
        )
    known_signals = set(signal_keys)
    for key in required:
        present = key in known_signals
        marked_missing = key in missing_unreliable
        if not present and not marked_missing:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "Required signal key is neither present nor marked missing/unreliable.",
            )
        if present and marked_missing:
            signal = next(item for item in decision.signals if item.signal_key == key)
            if (
                signal.binding_type == ProjectHealthBindingType.DIRECT
                and _signal_is_reliable(signal)
            ):
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Required signal cannot be marked missing while a reliable signal exists.",
                )

    pack_index = _pack_evidence_index(pack)
    verified_facts = resolve_verified_source_facts(pack)
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    normalized_signals = [
        _validate_signal(
            signal,
            pack=pack,
            pack_index=pack_index,
            verified_facts=verified_facts,
            client_safe=client_safe,
        )
        for signal in decision.signals
    ]
    if pack.delivery.latest_delivery_confidence is None:
        for signal in normalized_signals:
            if signal.binding_type == ProjectHealthBindingType.DIRECT and any(
                ref.source_table == "delivery_confidence_scores"
                for ref in signal.evidence
            ):
                raise ProjectHealthIntegrityError(
                    "invalid_policy_decision",
                    "Delivery Confidence values cannot be invented when absent.",
                )

    signal_map = {item.signal_key: item for item in normalized_signals}
    positive: list[ProjectHealthDriver] = []
    negative: list[ProjectHealthDriver] = []
    for driver in decision.positive_drivers:
        if driver.polarity != ProjectHealthDriverPolarity.POSITIVE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "POSITIVE drivers must use positive polarity.",
            )
        positive.append(
            _validate_driver(
                driver,
                signal_map=signal_map,
                pack_index=pack_index,
                client_safe=client_safe,
            )
        )
    for driver in decision.negative_drivers:
        if driver.polarity != ProjectHealthDriverPolarity.NEGATIVE:
            raise ProjectHealthIntegrityError(
                "invalid_policy_decision",
                "NEGATIVE drivers must use negative polarity.",
            )
        negative.append(
            _validate_driver(
                driver,
                signal_map=signal_map,
                pack_index=pack_index,
                client_safe=client_safe,
            )
        )
    all_driver_keys = [item.driver_key for item in positive + negative]
    if len(all_driver_keys) != len(set(all_driver_keys)):
        raise ProjectHealthIntegrityError(
            "invalid_policy_decision",
            "Duplicate health driver keys are not allowed.",
        )
    return ProjectHealthPolicyDecision(
        proposed_status=decision.proposed_status,
        signals=normalized_signals,
        positive_drivers=positive,
        negative_drivers=negative,
        required_signal_keys=sorted(required),
        missing_unreliable_required_signal_keys=sorted(missing_unreliable),
        policy_limitations=list(decision.policy_limitations),
    )


def _driver_is_reliably_supported(
    driver: ProjectHealthDriver,
    signal_map: dict[str, ProjectHealthSignal],
    *,
    require_states: frozenset[ProjectHealthSignalState] | None = None,
) -> bool:
    """True only when every linked signal is reliable and polarity support holds.

    A single reliable linked signal cannot salvage a driver that also links
    STALE/CONFLICTING/UNAVAILABLE/incomplete signals.
    """
    linked: list[ProjectHealthSignal] = []
    for key in driver.signal_keys:
        signal = signal_map.get(key)
        if signal is None:
            return False
        linked.append(signal)
    if not all(_signal_is_reliable(signal) for signal in linked):
        return False
    if require_states is None:
        return True
    return any(signal.signal_state in require_states for signal in linked)


def _apply_data_quality_overrides(
    pack: ClientEvidencePack,
    decision: ProjectHealthPolicyDecision,
) -> tuple[ProjectHealthStatus, list[str]]:
    limitations: list[str] = []
    status = decision.proposed_status
    by_key = {item.signal_key: item for item in decision.signals}

    missing_required: list[str] = []
    unavailable_required: list[str] = []
    stale_required: list[str] = []
    conflicting_required: list[str] = []

    for key in decision.required_signal_keys:
        signal = by_key.get(key)
        marked = key in decision.missing_unreliable_required_signal_keys
        if signal is None or marked:
            if signal is None:
                missing_required.append(key)
            elif signal.signal_state == ProjectHealthSignalState.STALE or (
                signal.data_quality == DataQualityState.STALE
            ):
                stale_required.append(key)
            elif signal.signal_state == ProjectHealthSignalState.CONFLICTING or (
                signal.data_quality == DataQualityState.CONFLICTING
            ):
                conflicting_required.append(key)
            elif signal.signal_state == ProjectHealthSignalState.UNAVAILABLE or (
                signal.data_quality == DataQualityState.UNAVAILABLE
            ):
                unavailable_required.append(key)
            else:
                missing_required.append(key)
            continue
        if not _signal_is_reliable(signal):
            if signal.signal_state == ProjectHealthSignalState.UNAVAILABLE or (
                signal.data_quality == DataQualityState.UNAVAILABLE
            ):
                unavailable_required.append(key)
            elif signal.signal_state == ProjectHealthSignalState.STALE or (
                signal.data_quality == DataQualityState.STALE
            ):
                stale_required.append(key)
            elif signal.signal_state == ProjectHealthSignalState.CONFLICTING or (
                signal.data_quality == DataQualityState.CONFLICTING
            ):
                conflicting_required.append(key)
            else:
                unavailable_required.append(key)

    if missing_required:
        limitations.append(LIMITATION_REQUIRED_SIGNAL_MISSING)
    if unavailable_required:
        limitations.append(LIMITATION_REQUIRED_SIGNAL_UNAVAILABLE)
    if stale_required:
        limitations.append(LIMITATION_REQUIRED_SIGNAL_STALE)
    if conflicting_required:
        limitations.append(LIMITATION_REQUIRED_SIGNAL_CONFLICTING)
    if pack.overall_data_quality != DataQualityState.COMPLETE:
        limitations.append(LIMITATION_EVIDENCE_PACK_INCOMPLETE)

    risk_dq = next(
        (issue for issue in pack.data_quality if issue.source in {"risk_alerts", "risks"}),
        None,
    )
    if (
        risk_dq is not None
        and risk_dq.state == DataQualityState.UNAVAILABLE
        and not pack.delivery.open_risks
    ):
        for driver in decision.positive_drivers:
            if driver.reason_code in {"NO_OPEN_RISKS", "ZERO_OPEN_RISKS", "RISKS_CLEAR"}:
                limitations.append(LIMITATION_POSITIVE_EMPTY_ADVERSE_UNPROVEN)
                if status == ProjectHealthStatus.GREEN:
                    status = ProjectHealthStatus.INSUFFICIENT

    required_unreliable = (
        missing_required + unavailable_required + stale_required + conflicting_required
    )
    reliable_positive = [
        driver
        for driver in decision.positive_drivers
        if _driver_is_reliably_supported(
            driver,
            by_key,
            require_states=frozenset({ProjectHealthSignalState.POSITIVE}),
        )
    ]
    reliable_amber = [
        driver
        for driver in decision.negative_drivers
        if _driver_is_reliably_supported(
            driver,
            by_key,
            require_states=frozenset(
                {ProjectHealthSignalState.WATCH, ProjectHealthSignalState.ADVERSE}
            ),
        )
    ]
    reliable_red = [
        driver
        for driver in decision.negative_drivers
        if _driver_is_reliably_supported(
            driver,
            by_key,
            require_states=frozenset({ProjectHealthSignalState.ADVERSE}),
        )
    ]

    if status == ProjectHealthStatus.GREEN:
        if required_unreliable or pack.overall_data_quality != DataQualityState.COMPLETE:
            limitations.append(LIMITATION_GREEN_BLOCKED_UNRELIABLE_REQUIRED)
            status = ProjectHealthStatus.INSUFFICIENT
        elif not reliable_positive:
            limitations.append(LIMITATION_GREEN_BLOCKED_NO_RELIABLE_POSITIVE)
            status = ProjectHealthStatus.INSUFFICIENT
    elif status == ProjectHealthStatus.AMBER:
        if missing_required or unavailable_required:
            status = ProjectHealthStatus.INSUFFICIENT
        elif not reliable_amber:
            limitations.append(LIMITATION_AMBER_BLOCKED_NO_RELIABLE_SUPPORT)
            status = ProjectHealthStatus.INSUFFICIENT
    elif status == ProjectHealthStatus.RED:
        if missing_required or unavailable_required:
            status = ProjectHealthStatus.INSUFFICIENT
        elif reliable_red:
            if required_unreliable or decision.policy_limitations:
                limitations.append(LIMITATION_RED_RETAINED_WITH_OPTIONAL_LIMITATION)
        else:
            limitations.append(LIMITATION_RED_BLOCKED_NO_RELIABLE_SUPPORT)
            status = ProjectHealthStatus.INSUFFICIENT

    return status, _canonicalize_strings(limitations)


def _driver_material_fingerprint(
    driver: ProjectHealthDriver,
    signal_map: dict[str, ProjectHealthSignal],
) -> tuple[Any, ...]:
    linked_states = tuple(
        (
            key,
            signal_map[key].signal_state.value if key in signal_map else None,
            repr(signal_map[key].observed_value) if key in signal_map else None,
        )
        for key in driver.signal_keys
    )
    evidence = tuple(
        (*_evidence_identity_key(ref), tuple(ref.claim_keys))
        for ref in _sort_evidence(driver.evidence)
    )
    return (
        driver.reason_code,
        driver.polarity.value,
        driver.materiality,
        tuple(driver.signal_keys),
        evidence,
        linked_states,
    )


def _assert_previous_identity(
    pack: ClientEvidencePack,
    previous: ProjectHealthAssessment,
) -> None:
    if (
        previous.org_id != pack.project.org_id
        or previous.project_id != pack.project.project_id
    ):
        raise ProjectHealthIntegrityError(
            "incompatible_previous_assessment",
            "Previous health assessment tenant/project does not match.",
        )


def _with_history(
    assessment: ProjectHealthAssessment,
    pack: ClientEvidencePack,
    *,
    previous: ProjectHealthAssessment | None,
    policy: ProjectHealthPolicy | None,
) -> ProjectHealthAssessment:
    if previous is None:
        history = ProjectHealthHistoryComparison(
            previous_status=None,
            current_status=assessment.status,
            trend=ProjectHealthTrend.UNKNOWN,
            previous_reporting_period=None,
            limitation=LIMITATION_HISTORY_UNAVAILABLE,
        )
        return assessment.model_copy(update={"history": history})

    _assert_previous_identity(pack, previous)
    try:
        ProjectHealthAssessment.model_validate(previous.model_dump(mode="python"))
    except ValidationError as exc:
        raise ProjectHealthIntegrityError(
            "incompatible_previous_assessment",
            "Previous health assessment is structurally invalid.",
        ) from exc

    if previous.visibility_mode != pack.visibility_mode:
        return assessment.model_copy(
            update={
                "history": ProjectHealthHistoryComparison(
                    previous_status=previous.status,
                    current_status=assessment.status,
                    trend=ProjectHealthTrend.UNKNOWN,
                    previous_reporting_period=previous.reporting_period,
                    limitation=LIMITATION_HISTORY_VISIBILITY_MISMATCH,
                )
            }
        )

    period = pack.reporting_period
    prev_period = previous.reporting_period
    if not (
        prev_period.start_date == period.previous_start_date
        and prev_period.end_date == period.previous_end_date
    ):
        return assessment.model_copy(
            update={
                "history": ProjectHealthHistoryComparison(
                    previous_status=previous.status,
                    current_status=assessment.status,
                    trend=ProjectHealthTrend.UNKNOWN,
                    previous_reporting_period=previous.reporting_period,
                    limitation=LIMITATION_HISTORY_PERIOD_MISMATCH,
                )
            }
        )

    if policy is None or assessment.rules_version is None or (
        previous.rules_version != assessment.rules_version
    ):
        return assessment.model_copy(
            update={
                "history": ProjectHealthHistoryComparison(
                    previous_status=previous.status,
                    current_status=assessment.status,
                    trend=ProjectHealthTrend.UNKNOWN,
                    previous_reporting_period=previous.reporting_period,
                    limitation=(
                        LIMITATION_HISTORY_RULES_MISMATCH
                        if previous.rules_version != assessment.rules_version
                        else LIMITATION_HISTORY_UNAVAILABLE
                    ),
                )
            }
        )

    if (
        previous.status == ProjectHealthStatus.INSUFFICIENT
        or assessment.status == ProjectHealthStatus.INSUFFICIENT
    ):
        return assessment.model_copy(
            update={
                "history": ProjectHealthHistoryComparison(
                    previous_status=previous.status,
                    current_status=assessment.status,
                    trend=ProjectHealthTrend.UNKNOWN,
                    previous_reporting_period=previous.reporting_period,
                    limitation=LIMITATION_HISTORY_INSUFFICIENT,
                )
            }
        )

    prev_signal_map = {item.signal_key: item for item in previous.signals}
    curr_signal_map = {item.signal_key: item for item in assessment.signals}
    prev_drivers = {
        item.driver_key: item
        for item in previous.positive_drivers + previous.negative_drivers
    }
    curr_drivers = {
        item.driver_key: item
        for item in assessment.positive_drivers + assessment.negative_drivers
    }
    added = _canonicalize_strings([key for key in curr_drivers if key not in prev_drivers])
    removed = _canonicalize_strings([key for key in prev_drivers if key not in curr_drivers])
    changed = _canonicalize_strings(
        [
            key
            for key in curr_drivers
            if key in prev_drivers
            and _driver_material_fingerprint(curr_drivers[key], curr_signal_map)
            != _driver_material_fingerprint(prev_drivers[key], prev_signal_map)
        ]
    )
    prev_rank = _STATUS_RANK.get(previous.status)
    curr_rank = _STATUS_RANK.get(assessment.status)
    if prev_rank is None or curr_rank is None:
        trend = ProjectHealthTrend.UNKNOWN
    elif curr_rank > prev_rank:
        trend = ProjectHealthTrend.IMPROVING
    elif curr_rank < prev_rank:
        trend = ProjectHealthTrend.DETERIORATING
    else:
        trend = ProjectHealthTrend.STABLE
    return assessment.model_copy(
        update={
            "history": ProjectHealthHistoryComparison(
                previous_status=previous.status,
                current_status=assessment.status,
                trend=trend,
                previous_reporting_period=previous.reporting_period,
                added_driver_keys=added,
                removed_driver_keys=removed,
                changed_driver_keys=changed,
                limitation=None,
            )
        }
    )
