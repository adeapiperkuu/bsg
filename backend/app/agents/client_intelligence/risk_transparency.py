"""Deterministic Risk Transparency Intelligence foundation (roadmap 8.3).

Consumes Delivery-owned risk/bottleneck facts and adds selection structure.
Never invents business impact (CI-DQ09), mitigation, or client-safe publication
defaults. No production materiality/visibility policy is defined.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityState,
    EvidenceVisibility,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    reference_supports_claim_keys,
    source_agent_owns_table,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.risk_transparency_contracts import (
    LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED as CONTRACT_IMPACT_LIMITATION,
)
from app.agents.client_intelligence.risk_transparency_contracts import (
    LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE as CONTRACT_CLIENT_VISIBILITY_LIMITATION,
)
from app.agents.client_intelligence.risk_transparency_contracts import (
    LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE as CONTRACT_MITIGATION_LIMITATION,
)
from app.agents.client_intelligence.risk_transparency_contracts import (
    LIMITATION_RISK_POLICY_UNAVAILABLE as CONTRACT_RISK_POLICY_LIMITATION,
)
from app.agents.client_intelligence.risk_transparency_contracts import (
    RiskBusinessImpactDimension,
    RiskBusinessImpactView,
    RiskCandidateSourceType,
    RiskClientVisibilityDecision,
    RiskEvidencePeriod,
    RiskMaterialityDecision,
    RiskMitigationAvailability,
    RiskMitigationView,
    RiskTransparencyAssessment,
    RiskTransparencyAvailability,
    RiskTransparencyCandidate,
    RiskTransparencyCandidateContext,
    RiskTransparencyEvidenceRef,
    RiskTransparencyItem,
    RiskTransparencyPolicyDecision,
    _canonicalize_source_limitations,
    eligible_categories_for,
    require_rules_version,
)
from app.agents.client_intelligence.risk_transparency_policy import (
    RiskTransparencyPolicy,
)
from app.db.models import AppRole

LIMITATION_RISK_POLICY_UNAVAILABLE = CONTRACT_RISK_POLICY_LIMITATION
LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE = (
    CONTRACT_CLIENT_VISIBILITY_LIMITATION
)
LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED = CONTRACT_IMPACT_LIMITATION
LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE = CONTRACT_MITIGATION_LIMITATION
LIMITATION_CLIENT_SAFE_RISKS_NOT_CONFIGURED = "CLIENT_SAFE_RISKS_NOT_CONFIGURED"
LIMITATION_NO_OPEN_RISK_CANDIDATES = "NO_OPEN_RISK_CANDIDATES"
LIMITATION_NO_MATERIAL_RISKS_SELECTED = "NO_MATERIAL_RISKS_SELECTED"
LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS = "SOURCE_QUALITY_MISSING_RISK_ALERTS"
LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS = "SOURCE_QUALITY_MISSING_BOTTLENECKS"
LIMITATION_SOURCE_QUALITY_STALE_RISK_ALERTS = "SOURCE_QUALITY_STALE_RISK_ALERTS"
LIMITATION_SOURCE_QUALITY_STALE_BOTTLENECKS = "SOURCE_QUALITY_STALE_BOTTLENECKS"
LIMITATION_SOURCE_QUALITY_CONFLICTING_RISK_ALERTS = (
    "SOURCE_QUALITY_CONFLICTING_RISK_ALERTS"
)
LIMITATION_SOURCE_QUALITY_CONFLICTING_BOTTLENECKS = (
    "SOURCE_QUALITY_CONFLICTING_BOTTLENECKS"
)
LIMITATION_SOURCE_QUALITY_PARTIAL_RISK_ALERTS = "SOURCE_QUALITY_PARTIAL_RISK_ALERTS"
LIMITATION_SOURCE_QUALITY_PARTIAL_BOTTLENECKS = "SOURCE_QUALITY_PARTIAL_BOTTLENECKS"
LIMITATION_SOURCE_QUALITY_UNAVAILABLE_RISK_ALERTS = (
    "SOURCE_QUALITY_UNAVAILABLE_RISK_ALERTS"
)
LIMITATION_SOURCE_QUALITY_UNAVAILABLE_BOTTLENECKS = (
    "SOURCE_QUALITY_UNAVAILABLE_BOTTLENECKS"
)

_OPEN_STATUSES = frozenset({"open", "acknowledged"})
_RELIABLE_QUALITY = frozenset({DataQualityState.COMPLETE})

_EVIDENCE_TABLE_TO_DQ_SOURCES: dict[str, frozenset[str]] = {
    "risk_alerts": frozenset({"risk_alerts", "risks"}),
    "bottlenecks": frozenset({"bottlenecks"}),
}

_QUALITY_STATE_LIMITATIONS: dict[tuple[str, DataQualityState], str] = {
    ("risk_alerts", DataQualityState.STALE): LIMITATION_SOURCE_QUALITY_STALE_RISK_ALERTS,
    ("risk_alerts", DataQualityState.CONFLICTING): (
        LIMITATION_SOURCE_QUALITY_CONFLICTING_RISK_ALERTS
    ),
    ("risk_alerts", DataQualityState.PARTIAL): (
        LIMITATION_SOURCE_QUALITY_PARTIAL_RISK_ALERTS
    ),
    ("risk_alerts", DataQualityState.UNAVAILABLE): (
        LIMITATION_SOURCE_QUALITY_UNAVAILABLE_RISK_ALERTS
    ),
    ("bottlenecks", DataQualityState.STALE): LIMITATION_SOURCE_QUALITY_STALE_BOTTLENECKS,
    ("bottlenecks", DataQualityState.CONFLICTING): (
        LIMITATION_SOURCE_QUALITY_CONFLICTING_BOTTLENECKS
    ),
    ("bottlenecks", DataQualityState.PARTIAL): (
        LIMITATION_SOURCE_QUALITY_PARTIAL_BOTTLENECKS
    ),
    ("bottlenecks", DataQualityState.UNAVAILABLE): (
        LIMITATION_SOURCE_QUALITY_UNAVAILABLE_BOTTLENECKS
    ),
}


class RiskTransparencyIntegrityError(Exception):
    """Deterministic Risk Transparency integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def assess_risk_transparency(
    pack: ClientEvidencePack,
    *,
    policy: RiskTransparencyPolicy | None = None,
    assessed_at: datetime | None = None,
) -> RiskTransparencyAssessment:
    """Build a Risk Transparency assessment from a validated evidence pack."""
    working = pack.model_copy(deep=True)
    _validate_pack_or_raise(working)

    source_limitations = _canonicalize_source_limitations(list(working.limitations))
    limitations: list[str] = []
    core_org_id = working.project.org_id
    core_project_id = working.project.project_id
    core_as_of = working.reporting_period.as_of
    core_visibility = working.visibility_mode
    core_source_fingerprint = working.source_fingerprint
    core_assessed_at = assessed_at if assessed_at is not None else working.generated_at
    if core_assessed_at.tzinfo is None:
        raise RiskTransparencyIntegrityError(
            "invalid_policy_decision",
            "assessed_at must be timezone-aware.",
        )

    limitations.extend(
        [
            LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED,
            LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE,
        ]
    )

    if core_visibility == EvidenceVisibility.CLIENT_SAFE:
        if working.delivery.open_risks or working.delivery.open_bottlenecks:
            raise RiskTransparencyIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE packs must not carry risk or bottleneck facts.",
            )
        limitations.append(LIMITATION_CLIENT_SAFE_RISKS_NOT_CONFIGURED)

    risk_quality = _resolve_source_quality(working, "risk_alerts")
    bottleneck_quality = _resolve_source_quality(working, "bottlenecks")
    limitations.extend(
        _quality_limitations(
            "risk_alerts",
            risk_quality,
            facts_present=bool(working.delivery.open_risks),
        )
    )
    limitations.extend(
        _quality_limitations(
            "bottlenecks",
            bottleneck_quality,
            facts_present=bool(working.delivery.open_bottlenecks),
        )
    )

    authoritative = _build_candidate_context(
        working,
        risk_quality=risk_quality,
        bottleneck_quality=bottleneck_quality,
    )
    limitations.extend(authoritative.context_limitations)

    if policy is None:
        limitations.extend(
            [
                LIMITATION_RISK_POLICY_UNAVAILABLE,
                LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE,
            ]
        )
        availability = _availability_without_policy(
            risk_quality=risk_quality,
            bottleneck_quality=bottleneck_quality,
            risks_present=bool(working.delivery.open_risks),
            bottlenecks_present=bool(working.delivery.open_bottlenecks),
        )
        return RiskTransparencyAssessment(
            org_id=core_org_id,
            project_id=core_project_id,
            as_of=core_as_of,
            visibility_mode=core_visibility,
            availability=availability,
            risk_items=[],
            evidence=[],
            limitations=_canonicalize_strings(limitations),
            source_limitations=source_limitations,
            source_fingerprint=core_source_fingerprint,
            rules_version=None,
            assessed_at=core_assessed_at,
        )

    rules_version = _require_rules_version(policy)
    decision = _evaluate_policy(policy, authoritative)
    limitations.extend(decision.policy_limitations)

    items, evidence = _materialize_items(
        decision,
        candidates=authoritative,
        client_safe=core_visibility == EvidenceVisibility.CLIENT_SAFE,
    )
    if not items:
        limitations.append(LIMITATION_NO_MATERIAL_RISKS_SELECTED)

    availability = _availability_with_policy(
        items=items,
        risk_quality=risk_quality,
        bottleneck_quality=bottleneck_quality,
        risks_present=bool(working.delivery.open_risks),
        bottlenecks_present=bool(working.delivery.open_bottlenecks),
    )
    if availability != RiskTransparencyAvailability.AVAILABLE:
        items = []
        evidence = []

    if core_visibility == EvidenceVisibility.CLIENT_SAFE:
        evidence = [
            item
            for item in evidence
            if item.visibility == EvidenceVisibility.CLIENT_SAFE
        ]

    return RiskTransparencyAssessment(
        org_id=core_org_id,
        project_id=core_project_id,
        as_of=core_as_of,
        visibility_mode=core_visibility,
        availability=availability,
        risk_items=_sort_items(items),
        evidence=_sort_evidence(evidence),
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


def _resolve_source_quality(
    pack: ClientEvidencePack, source_table: str
) -> DataQualityState | None:
    aliases = _EVIDENCE_TABLE_TO_DQ_SOURCES.get(source_table)
    if aliases is None:
        raise RiskTransparencyIntegrityError(
            "invalid_policy_decision",
            "Unsupported risk transparency source_table.",
        )
    issues = [item for item in pack.data_quality if item.source in aliases]
    if not issues:
        return None
    states = {item.state for item in issues}
    if len(states) != 1:
        return DataQualityState.CONFLICTING
    return next(iter(states))


def _quality_limitations(
    source_table: str,
    quality: DataQualityState | None,
    *,
    facts_present: bool,
) -> list[str]:
    if quality is None:
        if not facts_present:
            return []
        if source_table == "risk_alerts":
            return [LIMITATION_SOURCE_QUALITY_MISSING_RISK_ALERTS]
        if source_table == "bottlenecks":
            return [LIMITATION_SOURCE_QUALITY_MISSING_BOTTLENECKS]
        return []
    code = _QUALITY_STATE_LIMITATIONS.get((source_table, quality))
    return [code] if code is not None else []


def _populated_qualities(
    *,
    risk_quality: DataQualityState | None,
    bottleneck_quality: DataQualityState | None,
    risks_present: bool,
    bottlenecks_present: bool,
) -> list[DataQualityState | None]:
    qualities: list[DataQualityState | None] = []
    if risks_present:
        qualities.append(risk_quality)
    if bottlenecks_present:
        qualities.append(bottleneck_quality)
    return qualities


def _availability_from_populated(
    populated: list[DataQualityState | None],
    *,
    items: list[RiskTransparencyItem] | None = None,
) -> RiskTransparencyAvailability:
    selected = items or []
    if not populated:
        return (
            RiskTransparencyAvailability.AVAILABLE
            if selected
            else RiskTransparencyAvailability.UNAVAILABLE
        )
    if any(q == DataQualityState.CONFLICTING for q in populated if q is not None):
        return RiskTransparencyAvailability.CONFLICTING
    if all(q == DataQualityState.COMPLETE for q in populated):
        if selected:
            return RiskTransparencyAvailability.AVAILABLE
        return RiskTransparencyAvailability.UNAVAILABLE
    if all(q == DataQualityState.STALE for q in populated):
        return RiskTransparencyAvailability.STALE
    if all(q == DataQualityState.PARTIAL for q in populated):
        return RiskTransparencyAvailability.PARTIAL
    if all(q == DataQualityState.UNAVAILABLE for q in populated):
        return RiskTransparencyAvailability.UNAVAILABLE
    # Mixed COMPLETE + unreliable/missing, PARTIAL, missing DQ, etc.
    return RiskTransparencyAvailability.PARTIAL


def _availability_without_policy(
    *,
    risk_quality: DataQualityState | None,
    bottleneck_quality: DataQualityState | None,
    risks_present: bool,
    bottlenecks_present: bool,
) -> RiskTransparencyAvailability:
    return _availability_from_populated(
        _populated_qualities(
            risk_quality=risk_quality,
            bottleneck_quality=bottleneck_quality,
            risks_present=risks_present,
            bottlenecks_present=bottlenecks_present,
        )
    )


def _availability_with_policy(
    *,
    items: list[RiskTransparencyItem],
    risk_quality: DataQualityState | None,
    bottleneck_quality: DataQualityState | None,
    risks_present: bool,
    bottlenecks_present: bool,
) -> RiskTransparencyAvailability:
    return _availability_from_populated(
        _populated_qualities(
            risk_quality=risk_quality,
            bottleneck_quality=bottleneck_quality,
            risks_present=risks_present,
            bottlenecks_present=bottlenecks_present,
        ),
        items=items,
    )


def _require_exact_observed_at(
    pack_ref: ClientEvidenceReference,
    fact_observed_at: datetime | None,
) -> datetime | None:
    if pack_ref.observed_at != fact_observed_at:
        raise RiskTransparencyIntegrityError(
            "invalid_policy_decision",
            "Evidence observed_at must exactly equal the source fact observed_at.",
        )
    return pack_ref.observed_at


def _require_pack_evidence(
    pack: ClientEvidencePack,
    *,
    source_table: str,
    source_row_id: UUID,
    claim_keys: list[str],
    fact_observed_at: datetime | None,
) -> RiskTransparencyEvidenceRef:
    matches = [
        item
        for item in pack.evidence
        if item.source_table == source_table and item.source_row_id == source_row_id
    ]
    if len(matches) != 1:
        raise RiskTransparencyIntegrityError(
            "unsupported_evidence_reference",
            "Candidate construction requires exactly one matching pack evidence row.",
        )
    pack_ref = matches[0]
    if not source_agent_owns_table(pack_ref.source_agent, source_table):
        raise RiskTransparencyIntegrityError(
            "unsupported_evidence_reference",
            "Candidate evidence source_agent does not own the declared table.",
        )
    client_safe = pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
    if client_safe and pack_ref.visibility != EvidenceVisibility.CLIENT_SAFE:
        raise RiskTransparencyIntegrityError(
            "visibility_violation",
            "CLIENT_SAFE candidates cannot use internal evidence.",
        )
    if not reference_supports_claim_keys(
        pack_ref, claim_keys, client_safe=client_safe
    ):
        raise RiskTransparencyIntegrityError(
            "unsupported_evidence_reference",
            "Candidate claim keys are not supported by pack evidence.",
        )
    observed_at = _require_exact_observed_at(pack_ref, fact_observed_at)
    return RiskTransparencyEvidenceRef(
        source_agent=pack_ref.source_agent,
        source_table=source_table,
        source_row_id=source_row_id,
        visibility=pack_ref.visibility,
        claim_keys=sorted(claim_keys),
        period=RiskEvidencePeriod.CURRENT,
        source_fingerprint=pack.source_fingerprint,
        observed_at=observed_at,
    )


def _build_candidate_context(
    pack: ClientEvidencePack,
    *,
    risk_quality: DataQualityState | None,
    bottleneck_quality: DataQualityState | None,
) -> RiskTransparencyCandidateContext:
    candidates: list[RiskTransparencyCandidate] = []
    limitations: list[str] = []

    if risk_quality in _RELIABLE_QUALITY:
        for risk in pack.delivery.open_risks:
            if risk.status not in _OPEN_STATUSES:
                raise RiskTransparencyIntegrityError(
                    "invalid_policy_decision",
                    "Only open or acknowledged risk facts are eligible.",
                )
            claim_keys = [
                "risk_id",
                "risk_title",
                "risk_tier",
                "alert_type",
                "status",
            ]
            evidence = [
                _require_pack_evidence(
                    pack,
                    source_table="risk_alerts",
                    source_row_id=risk.id,
                    claim_keys=claim_keys,
                    fact_observed_at=risk.observed_at,
                )
            ]
            candidates.append(
                RiskTransparencyCandidate(
                    candidate_key=f"risk_alert.{risk.id.hex}",
                    source_type=RiskCandidateSourceType.RISK_ALERT,
                    source_agent=evidence[0].source_agent,
                    source_table="risk_alerts",
                    source_row_id=risk.id,
                    status=risk.status,
                    risk_tier=risk.risk_tier,
                    alert_type=risk.alert_type,
                    title=risk.title,
                    eligible_categories=eligible_categories_for(
                        RiskCandidateSourceType.RISK_ALERT, risk.alert_type
                    ),
                    observed_at=evidence[0].observed_at,
                    data_quality=risk_quality,
                    visibility=evidence[0].visibility,
                    source_fingerprint=pack.source_fingerprint,
                    evidence=evidence,
                )
            )

    if bottleneck_quality in _RELIABLE_QUALITY:
        for bottleneck in pack.delivery.open_bottlenecks:
            if bottleneck.status not in _OPEN_STATUSES:
                raise RiskTransparencyIntegrityError(
                    "invalid_policy_decision",
                    "Only open or acknowledged bottleneck facts are eligible.",
                )
            claim_keys = ["bottleneck_id", "bottleneck_title", "status"]
            evidence = [
                _require_pack_evidence(
                    pack,
                    source_table="bottlenecks",
                    source_row_id=bottleneck.id,
                    claim_keys=claim_keys,
                    fact_observed_at=bottleneck.observed_at,
                )
            ]
            candidates.append(
                RiskTransparencyCandidate(
                    candidate_key=f"bottleneck.{bottleneck.id.hex}",
                    source_type=RiskCandidateSourceType.BOTTLENECK,
                    source_agent=evidence[0].source_agent,
                    source_table="bottlenecks",
                    source_row_id=bottleneck.id,
                    status=bottleneck.status,
                    risk_tier=None,
                    alert_type=None,
                    title=bottleneck.title,
                    eligible_categories=eligible_categories_for(
                        RiskCandidateSourceType.BOTTLENECK, None
                    ),
                    observed_at=evidence[0].observed_at,
                    data_quality=bottleneck_quality,
                    visibility=evidence[0].visibility,
                    source_fingerprint=pack.source_fingerprint,
                    evidence=evidence,
                )
            )

    if not candidates:
        limitations.append(LIMITATION_NO_OPEN_RISK_CANDIDATES)

    by_key = {item.candidate_key: item for item in candidates}
    if len(by_key) != len(candidates):
        raise RiskTransparencyIntegrityError(
            "invalid_policy_decision",
            "Duplicate verified risk candidate keys are not allowed.",
        )
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.source_type.value,
            item.candidate_key,
            item.source_table,
            str(item.source_row_id),
        ),
    )
    return RiskTransparencyCandidateContext(
        candidates=ordered,
        context_limitations=_canonicalize_strings(limitations),
    )


def _require_rules_version(policy: RiskTransparencyPolicy) -> str:
    try:
        version = policy.rules_version
    except Exception as exc:  # noqa: BLE001 — sanitize policy-owned failures
        raise RiskTransparencyIntegrityError(
            "invalid_policy",
            "Risk transparency policy rules_version is inaccessible.",
        ) from exc
    try:
        return require_rules_version(version)
    except (TypeError, ValueError) as exc:
        raise RiskTransparencyIntegrityError(
            "invalid_policy",
            "Risk transparency policy rules_version must be non-empty.",
        ) from exc


def _evaluate_policy(
    policy: RiskTransparencyPolicy,
    authoritative: RiskTransparencyCandidateContext,
) -> RiskTransparencyPolicyDecision:
    policy_copy = authoritative.model_copy(deep=True)
    try:
        decision = policy.evaluate(policy_copy)
    except Exception as exc:  # noqa: BLE001 — sanitize policy-owned failures
        raise RiskTransparencyIntegrityError(
            "invalid_policy",
            "Injected risk transparency policy failed during evaluation.",
        ) from (exc)
    if not isinstance(decision, RiskTransparencyPolicyDecision):
        raise RiskTransparencyIntegrityError(
            "invalid_policy_decision",
            "Risk policy did not return a RiskTransparencyPolicyDecision.",
        )
    return decision


def _default_business_impact() -> RiskBusinessImpactView:
    return RiskBusinessImpactView(
        dimension=RiskBusinessImpactDimension.UNAVAILABLE,
        quantified=False,
        limitations=[LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED],
    )


def _default_mitigation() -> RiskMitigationView:
    return RiskMitigationView(
        availability=RiskMitigationAvailability.UNAVAILABLE,
        limitations=[LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE],
    )


def _materialize_items(
    decision: RiskTransparencyPolicyDecision,
    *,
    candidates: RiskTransparencyCandidateContext,
    client_safe: bool,
) -> tuple[list[RiskTransparencyItem], list[RiskTransparencyEvidenceRef]]:
    by_key = {item.candidate_key: item for item in candidates.candidates}
    items: list[RiskTransparencyItem] = []
    evidence: list[RiskTransparencyEvidenceRef] = []

    for selection in decision.selections:
        candidate = by_key.get(selection.candidate_key)
        if candidate is None:
            raise RiskTransparencyIntegrityError(
                "invalid_policy_decision",
                "Risk policy selected an unknown candidate key.",
            )
        if selection.category not in candidate.eligible_categories:
            raise RiskTransparencyIntegrityError(
                "invalid_policy_decision",
                "Risk policy selected an ineligible category.",
            )
        if candidate.data_quality not in _RELIABLE_QUALITY:
            raise RiskTransparencyIntegrityError(
                "invalid_policy_decision",
                "Material risks cannot use unreliable source quality.",
            )
        if client_safe and candidate.visibility != EvidenceVisibility.CLIENT_SAFE:
            raise RiskTransparencyIntegrityError(
                "visibility_violation",
                "CLIENT_SAFE assessments cannot select internal candidates.",
            )
        if not selection.material:
            continue
        if client_safe and not selection.client_visible:
            continue

        item_evidence = [
            RiskTransparencyEvidenceRef(
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
        items.append(
            RiskTransparencyItem(
                source_row_id=candidate.source_row_id,
                source_type=candidate.source_type,
                source_agent=candidate.source_agent,
                source_table=candidate.source_table,
                source_fingerprint=candidate.source_fingerprint,
                category=selection.category,
                status=candidate.status,
                risk_tier=candidate.risk_tier,
                alert_type=candidate.alert_type,
                materiality=RiskMaterialityDecision.MATERIAL,
                client_visibility=(
                    RiskClientVisibilityDecision.CLIENT_VISIBLE
                    if selection.client_visible
                    else RiskClientVisibilityDecision.INTERNAL_ONLY
                ),
                data_quality=candidate.data_quality,
                visibility=candidate.visibility,
                observed_at=candidate.observed_at,
                business_impact=_default_business_impact(),
                mitigation=_default_mitigation(),
                evidence=item_evidence,
                limitations=[
                    LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED,
                    LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE,
                ],
            )
        )
        evidence.extend(item_evidence)

    return items, evidence


def _sort_evidence(
    refs: list[RiskTransparencyEvidenceRef],
) -> list[RiskTransparencyEvidenceRef]:
    identity_observed: dict[tuple[str, str, str, str, str, str], datetime | None] = {}
    merged: dict[
        tuple[str, str, str, str, str, str, str], RiskTransparencyEvidenceRef
    ] = {}
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
                raise RiskTransparencyIntegrityError(
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

    result: list[RiskTransparencyEvidenceRef] = []
    for key, ref in merged.items():
        result.append(
            RiskTransparencyEvidenceRef(
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


def _sort_items(items: list[RiskTransparencyItem]) -> list[RiskTransparencyItem]:
    return sorted(
        items,
        key=lambda item: (
            item.source_type.value,
            item.category.value,
            str(item.source_row_id),
            item.status,
            item.risk_tier or "",
            item.alert_type or "",
        ),
    )
