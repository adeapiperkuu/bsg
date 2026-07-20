"""Typed Risk Transparency Intelligence contracts (Phase 2 foundation).

Client Intelligence consumes Delivery-owned risk/bottleneck facts and adds
selection structure only. No production materiality/client-visibility policy,
business-impact thresholds (CI-DQ09), or mitigation authoring live here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agents.client_intelligence.contracts import (
    ClientIntelligenceModel,
    DataQualityState,
    EvidenceVisibility,
    SourceAgent,
)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_RULES_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED = "BUSINESS_IMPACT_POLICY_UNRESOLVED"
LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE = "MITIGATION_EVIDENCE_UNAVAILABLE"
LIMITATION_RISK_POLICY_UNAVAILABLE = "RISK_POLICY_UNAVAILABLE"
LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE = (
    "CLIENT_VISIBILITY_POLICY_UNAVAILABLE"
)

_REQUIRED_RISK_ALERT_CLAIMS = frozenset(
    {"risk_id", "risk_title", "risk_tier", "alert_type", "status"}
)
_REQUIRED_BOTTLENECK_CLAIMS = frozenset(
    {"bottleneck_id", "bottleneck_title", "status"}
)
_OPEN_STATUSES = frozenset({"open", "acknowledged"})
_VALID_ALERT_TYPES = frozenset(
    {
        "delivery_risk",
        "quality_drift",
        "milestone_at_risk",
        "workforce_imbalance",
    }
)
_VALID_RISK_TIERS = frozenset({"low", "medium", "high", "critical"})
_FORBIDDEN_DETAIL_CLAIMS = frozenset({"risk_detail", "bottleneck_detail"})


class RiskTransparencyAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTING = "conflicting"


class RiskCategory(StrEnum):
    RESOURCE_CONSTRAINT = "resource_constraint"
    QA_REWORK = "qa_rework"
    WORKFLOW_BOTTLENECK = "workflow_bottleneck"
    DEPENDENCY_DELAY = "dependency_delay"
    UNCLASSIFIED = "unclassified"


class RiskCandidateSourceType(StrEnum):
    RISK_ALERT = "risk_alert"
    BOTTLENECK = "bottleneck"


class RiskBusinessImpactDimension(StrEnum):
    TIMELINE = "timeline"
    SCOPE = "scope"
    QUALITY = "quality"
    READINESS = "readiness"
    CLIENT_ACTION = "client_action"
    UNAVAILABLE = "unavailable"


class RiskMitigationAvailability(StrEnum):
    UNAVAILABLE = "unavailable"


class RiskMaterialityDecision(StrEnum):
    MATERIAL = "material"
    NOT_MATERIAL = "not_material"
    UNDECIDED = "undecided"


class RiskClientVisibilityDecision(StrEnum):
    CLIENT_VISIBLE = "client_visible"
    INTERNAL_ONLY = "internal_only"
    UNDECIDED = "undecided"


class RiskEvidencePeriod(StrEnum):
    CURRENT = "current"


def _require_key(value: str) -> str:
    if not isinstance(value, str) or not _KEY_RE.match(value):
        raise ValueError("must be a stable lowercase key")
    return value


def _require_reason_code(value: str) -> str:
    if not isinstance(value, str) or not _REASON_CODE_RE.match(value):
        raise ValueError("must be a structured uppercase label")
    return value


def _require_source_table(value: str) -> str:
    if not isinstance(value, str) or not _SOURCE_TABLE_RE.match(value):
        raise ValueError("must be a stable lowercase source_table identifier")
    return value


def _require_sha256_hex(value: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.match(value):
        raise ValueError("must be a lowercase SHA-256 hex digest")
    return value


def _require_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware when present")
    return value


def _canonicalize_source_limitations(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("source_limitations must be strings")
        if not item.strip():
            continue
        cleaned.append(item)
    return sorted(set(cleaned))


def _observed_at_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _evidence_lineage_key(
    ref: RiskTransparencyEvidenceRef,
) -> tuple[str, str, str, str, str, str, str]:
    return (
        ref.source_agent.value,
        ref.source_table,
        str(ref.source_row_id),
        ref.visibility.value,
        ref.period.value,
        ref.source_fingerprint,
        _observed_at_key(ref.observed_at),
    )


def eligible_categories_for(
    source_type: RiskCandidateSourceType,
    alert_type: str | None,
) -> list[RiskCategory]:
    if source_type == RiskCandidateSourceType.BOTTLENECK:
        return [RiskCategory.WORKFLOW_BOTTLENECK, RiskCategory.UNCLASSIFIED]
    if source_type == RiskCandidateSourceType.RISK_ALERT:
        if alert_type == "workforce_imbalance":
            return [RiskCategory.RESOURCE_CONSTRAINT, RiskCategory.UNCLASSIFIED]
        return [RiskCategory.UNCLASSIFIED]
    raise ValueError("unsupported risk candidate source type")


def canonical_candidate_key(
    source_type: RiskCandidateSourceType, source_row_id: UUID
) -> str:
    if source_type == RiskCandidateSourceType.RISK_ALERT:
        return f"risk_alert.{source_row_id.hex}"
    if source_type == RiskCandidateSourceType.BOTTLENECK:
        return f"bottleneck.{source_row_id.hex}"
    raise ValueError("unsupported risk candidate source type")


def require_rules_version(value: str) -> str:
    """Validate an injected policy rules_version; never invent or strip."""
    if not isinstance(value, str) or not _RULES_VERSION_RE.match(value):
        raise ValueError("rules_version must be a stable non-empty identifier")
    return value


def _require_open_status(value: str) -> str:
    if value not in _OPEN_STATUSES:
        raise ValueError("status must be open or acknowledged")
    return value


def _validate_source_owned_fields(
    *,
    source_type: RiskCandidateSourceType,
    source_agent: SourceAgent,
    source_table: str,
    status: str,
    risk_tier: str | None,
    alert_type: str | None,
) -> None:
    _require_open_status(status)
    if source_agent != SourceAgent.DELIVERY_PERFORMANCE:
        raise ValueError("source_agent must be delivery_performance")
    if source_type == RiskCandidateSourceType.RISK_ALERT:
        if source_table != "risk_alerts":
            raise ValueError("risk_alert source_table must be risk_alerts")
        if risk_tier is None or risk_tier not in _VALID_RISK_TIERS:
            raise ValueError("risk_alert requires a governed risk_tier")
        if alert_type is None or alert_type not in _VALID_ALERT_TYPES:
            raise ValueError("risk_alert requires a governed alert_type")
    elif source_type == RiskCandidateSourceType.BOTTLENECK:
        if source_table != "bottlenecks":
            raise ValueError("bottleneck source_table must be bottlenecks")
        if risk_tier is not None:
            raise ValueError("bottleneck risk_tier must be None")
        if alert_type is not None:
            raise ValueError("bottleneck alert_type must be None")
    else:
        raise ValueError("unsupported source_type")


def _validate_evidence_for_source(
    *,
    source_type: RiskCandidateSourceType,
    source_agent: SourceAgent,
    source_table: str,
    source_row_id: UUID,
    source_fingerprint: str,
    visibility: EvidenceVisibility,
    observed_at: datetime | None,
    evidence: list[RiskTransparencyEvidenceRef],
) -> set[str]:
    claims: set[str] = set()
    for ref in evidence:
        if ref.source_agent != source_agent:
            raise ValueError("evidence source_agent mismatch")
        if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
            raise ValueError("evidence source_agent must be delivery_performance")
        if ref.source_table != source_table:
            raise ValueError("evidence source_table mismatch")
        if ref.source_row_id != source_row_id:
            raise ValueError("evidence source_row_id mismatch")
        if ref.visibility != visibility:
            raise ValueError("evidence visibility mismatch")
        if ref.source_fingerprint != source_fingerprint:
            raise ValueError("evidence fingerprint mismatch")
        if ref.observed_at != observed_at:
            raise ValueError("evidence observed_at mismatch")
        if ref.period != RiskEvidencePeriod.CURRENT:
            raise ValueError("evidence must use CURRENT period")
        if _FORBIDDEN_DETAIL_CLAIMS.intersection(ref.claim_keys):
            raise ValueError("internal detail claims are not allowed")
        claims.update(ref.claim_keys)

    if source_type == RiskCandidateSourceType.RISK_ALERT:
        if claims != _REQUIRED_RISK_ALERT_CLAIMS:
            raise ValueError(
                "risk_alert evidence claim union must exactly equal governed claims"
            )
    else:
        if claims != _REQUIRED_BOTTLENECK_CLAIMS:
            raise ValueError(
                "bottleneck evidence claim union must exactly equal governed claims"
            )
    return claims


class RiskTransparencyEvidenceRef(ClientIntelligenceModel):
    """Exact pack evidence identity plus claim keys and observed_at lineage."""

    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(min_length=1)
    period: RiskEvidencePeriod
    source_fingerprint: str = Field(min_length=64, max_length=64)
    observed_at: datetime | None = None

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("claim_keys")
    @classmethod
    def _canonical_claim_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item for item in value if item]
        if not cleaned:
            raise ValueError("claim_keys must be non-empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("claim_keys must be unique")
        if _FORBIDDEN_DETAIL_CLAIMS.intersection(cleaned):
            raise ValueError("internal detail claims are not allowed")
        return sorted(cleaned)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)


class RiskTransparencyCandidate(ClientIntelligenceModel):
    """Engine-owned verified candidate available to an injected risk policy."""

    candidate_key: Annotated[str, Field(min_length=1)]
    source_type: RiskCandidateSourceType
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    status: str
    risk_tier: str | None = None
    alert_type: str | None = None
    title: str
    eligible_categories: list[RiskCategory] = Field(min_length=1)
    observed_at: datetime | None = None
    data_quality: DataQualityState
    visibility: EvidenceVisibility
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[RiskTransparencyEvidenceRef] = Field(min_length=1)

    @field_validator("candidate_key")
    @classmethod
    def _validate_candidate_key(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        return _require_open_status(value)

    @field_validator("eligible_categories")
    @classmethod
    def _canonical_categories(cls, value: list[RiskCategory]) -> list[RiskCategory]:
        cleaned: list[RiskCategory] = []
        seen: set[RiskCategory] = set()
        for item in value:
            if item not in seen:
                cleaned.append(item)
                seen.add(item)
        if not cleaned:
            raise ValueError("eligible_categories must be non-empty")
        return cleaned

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)

    @model_validator(mode="after")
    def _candidate_invariants(self) -> RiskTransparencyCandidate:
        if self.data_quality != DataQualityState.COMPLETE:
            raise ValueError("policy candidates require COMPLETE source quality")
        if not self.title or not self.title.strip():
            raise ValueError("candidate title must be non-empty")
        expected_key = canonical_candidate_key(self.source_type, self.source_row_id)
        if self.candidate_key != expected_key:
            raise ValueError(
                "candidate_key must equal canonical source_type.source_row_id.hex"
            )
        _validate_source_owned_fields(
            source_type=self.source_type,
            source_agent=self.source_agent,
            source_table=self.source_table,
            status=self.status,
            risk_tier=self.risk_tier,
            alert_type=self.alert_type,
        )
        expected = eligible_categories_for(self.source_type, self.alert_type)
        if list(self.eligible_categories) != expected:
            raise ValueError("eligible_categories must match governed eligibility")
        _validate_evidence_for_source(
            source_type=self.source_type,
            source_agent=self.source_agent,
            source_table=self.source_table,
            source_row_id=self.source_row_id,
            source_fingerprint=self.source_fingerprint,
            visibility=self.visibility,
            observed_at=self.observed_at,
            evidence=self.evidence,
        )
        return self


class RiskTransparencyCandidateContext(ClientIntelligenceModel):
    """Isolated verified-candidate context for policy evaluation only."""

    candidates: list[RiskTransparencyCandidate] = Field(default_factory=list)
    context_limitations: list[str] = Field(default_factory=list)

    @field_validator("context_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _context_invariants(self) -> RiskTransparencyCandidateContext:
        keys = [item.candidate_key for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate keys must be unique")
        identities = [
            (item.source_type, item.source_table, item.source_row_id)
            for item in self.candidates
        ]
        if len(identities) != len(set(identities)):
            raise ValueError(
                "source row/type identity must not be duplicated under different keys"
            )
        for item in self.candidates:
            if item.data_quality != DataQualityState.COMPLETE:
                raise ValueError("candidate context requires COMPLETE quality")
        return self


class RiskTransparencySelection(ClientIntelligenceModel):
    """Policy-owned selection of a verified candidate."""

    candidate_key: Annotated[str, Field(min_length=1)]
    category: RiskCategory
    material: bool
    client_visible: bool

    @field_validator("candidate_key")
    @classmethod
    def _validate_candidate_key(cls, value: str) -> str:
        return _require_key(value)


class RiskTransparencyPolicyDecision(ClientIntelligenceModel):
    """Policy-owned selection only — never core source facts or impact."""

    selections: list[RiskTransparencySelection] = Field(default_factory=list)
    policy_limitations: list[str] = Field(default_factory=list)

    @field_validator("policy_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _unique_selections(self) -> RiskTransparencyPolicyDecision:
        keys = [item.candidate_key for item in self.selections]
        if len(keys) != len(set(keys)):
            raise ValueError("policy selections must use unique candidate keys")
        return self


class RiskBusinessImpactView(ClientIntelligenceModel):
    """Business-impact state. Quantified values are not inventable (CI-DQ09)."""

    dimension: RiskBusinessImpactDimension = RiskBusinessImpactDimension.UNAVAILABLE
    quantified: bool = False
    amount: None = None
    unit: None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _impact_invariants(self) -> RiskBusinessImpactView:
        if self.dimension != RiskBusinessImpactDimension.UNAVAILABLE:
            raise ValueError("TASK 12 business impact must remain UNAVAILABLE")
        if self.quantified or self.amount is not None or self.unit is not None:
            raise ValueError("UNAVAILABLE business impact cannot be quantified")
        if LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED not in self.limitations:
            raise ValueError(
                "business impact must include BUSINESS_IMPACT_POLICY_UNRESOLVED"
            )
        return self


class RiskMitigationView(ClientIntelligenceModel):
    """Mitigation state. Owner/progress/target/residual are not inventable."""

    availability: RiskMitigationAvailability = RiskMitigationAvailability.UNAVAILABLE
    owner_role: None = None
    progress: None = None
    target: None = None
    residual_risk: None = None
    client_action: None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _mitigation_invariants(self) -> RiskMitigationView:
        if self.availability != RiskMitigationAvailability.UNAVAILABLE:
            raise ValueError("only UNAVAILABLE mitigation is accepted in TASK 12")
        if any(
            value is not None
            for value in (
                self.owner_role,
                self.progress,
                self.target,
                self.residual_risk,
                self.client_action,
            )
        ):
            raise ValueError("UNAVAILABLE mitigation cannot carry authored fields")
        if LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE not in self.limitations:
            raise ValueError(
                "mitigation must include MITIGATION_EVIDENCE_UNAVAILABLE"
            )
        return self


class RiskTransparencyItem(ClientIntelligenceModel):
    """Source-bound selected risk item — typed facts only, no narrative prose."""

    source_row_id: UUID
    source_type: RiskCandidateSourceType
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=64, max_length=64)
    category: RiskCategory
    status: str
    risk_tier: str | None = None
    alert_type: str | None = None
    materiality: RiskMaterialityDecision
    client_visibility: RiskClientVisibilityDecision
    data_quality: DataQualityState
    visibility: EvidenceVisibility
    observed_at: datetime | None = None
    business_impact: RiskBusinessImpactView
    mitigation: RiskMitigationView
    evidence: list[RiskTransparencyEvidenceRef] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        return _require_open_status(value)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)

    @model_validator(mode="after")
    def _item_invariants(self) -> RiskTransparencyItem:
        if self.materiality != RiskMaterialityDecision.MATERIAL:
            raise ValueError("published risk items must be MATERIAL")
        if self.data_quality != DataQualityState.COMPLETE:
            raise ValueError("material risk items require COMPLETE source quality")
        if self.client_visibility == RiskClientVisibilityDecision.UNDECIDED:
            raise ValueError("published risk items cannot use UNDECIDED visibility")
        if LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED not in self.limitations:
            raise ValueError("item must include BUSINESS_IMPACT_POLICY_UNRESOLVED")
        if LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE not in self.limitations:
            raise ValueError("item must include MITIGATION_EVIDENCE_UNAVAILABLE")
        _validate_source_owned_fields(
            source_type=self.source_type,
            source_agent=self.source_agent,
            source_table=self.source_table,
            status=self.status,
            risk_tier=self.risk_tier,
            alert_type=self.alert_type,
        )
        eligible = eligible_categories_for(self.source_type, self.alert_type)
        if self.category not in eligible:
            raise ValueError("category is not eligible for source type/alert_type")
        _validate_evidence_for_source(
            source_type=self.source_type,
            source_agent=self.source_agent,
            source_table=self.source_table,
            source_row_id=self.source_row_id,
            source_fingerprint=self.source_fingerprint,
            visibility=self.visibility,
            observed_at=self.observed_at,
            evidence=self.evidence,
        )
        return self


class RiskTransparencyAssessment(ClientIntelligenceModel):
    """Deterministic Risk Transparency foundation assessment."""

    org_id: UUID
    project_id: UUID
    as_of: date
    visibility_mode: EvidenceVisibility
    availability: RiskTransparencyAvailability
    risk_items: list[RiskTransparencyItem] = Field(default_factory=list)
    evidence: list[RiskTransparencyEvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_limitations: list[str] = Field(default_factory=list)
    source_fingerprint: str = Field(min_length=64, max_length=64)
    rules_version: str | None = None
    assessed_at: datetime

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_source_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("rules_version")
    @classmethod
    def _validate_rules_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_rules_version(value)

    @field_validator("assessed_at")
    @classmethod
    def _validate_assessed_at(cls, value: datetime) -> datetime:
        aware = _require_aware_datetime(value)
        assert aware is not None
        return aware

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value if item})

    @field_validator("source_limitations")
    @classmethod
    def _validate_source_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_source_limitations(value)

    @model_validator(mode="after")
    def _assessment_invariants(self) -> RiskTransparencyAssessment:
        if LIMITATION_BUSINESS_IMPACT_POLICY_UNRESOLVED not in self.limitations:
            raise ValueError(
                "assessment must include BUSINESS_IMPACT_POLICY_UNRESOLVED"
            )
        if LIMITATION_MITIGATION_EVIDENCE_UNAVAILABLE not in self.limitations:
            raise ValueError(
                "assessment must include MITIGATION_EVIDENCE_UNAVAILABLE"
            )

        if self.rules_version is None:
            if self.availability == RiskTransparencyAvailability.AVAILABLE:
                raise ValueError(
                    "AVAILABLE assessments require a valid non-None rules_version"
                )
            if self.risk_items or self.evidence:
                raise ValueError(
                    "missing-policy assessments cannot carry risk items or evidence"
                )
            if LIMITATION_RISK_POLICY_UNAVAILABLE not in self.limitations:
                raise ValueError(
                    "missing-policy assessments require RISK_POLICY_UNAVAILABLE"
                )
            if LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE not in self.limitations:
                raise ValueError(
                    "missing-policy assessments require "
                    "CLIENT_VISIBILITY_POLICY_UNAVAILABLE"
                )
        else:
            if LIMITATION_RISK_POLICY_UNAVAILABLE in self.limitations:
                raise ValueError(
                    "evaluated-policy assessments cannot include RISK_POLICY_UNAVAILABLE"
                )
            if LIMITATION_CLIENT_VISIBILITY_POLICY_UNAVAILABLE in self.limitations:
                raise ValueError(
                    "evaluated-policy assessments cannot include "
                    "CLIENT_VISIBILITY_POLICY_UNAVAILABLE"
                )

        if self.availability == RiskTransparencyAvailability.AVAILABLE:
            if self.rules_version is None:
                raise ValueError(
                    "AVAILABLE assessments require a valid non-None rules_version"
                )
            if not self.risk_items:
                raise ValueError("AVAILABLE assessments require selected risk items")
        elif (
            self.availability
            in {
                RiskTransparencyAvailability.UNAVAILABLE,
                RiskTransparencyAvailability.STALE,
                RiskTransparencyAvailability.CONFLICTING,
                RiskTransparencyAvailability.PARTIAL,
            }
            and self.risk_items
        ):
            raise ValueError(
                "unreliable/unavailable assessments cannot carry material risk items"
            )

        if self.availability != RiskTransparencyAvailability.AVAILABLE and self.evidence:
            raise ValueError(
                "non-AVAILABLE assessments cannot carry top-level risk evidence"
            )

        published_identities = [
            (
                item.source_type,
                item.source_agent,
                item.source_table,
                item.source_row_id,
            )
            for item in self.risk_items
        ]
        if len(published_identities) != len(set(published_identities)):
            raise ValueError("published risk items must have unique source identities")

        if self.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
            for ref in self.evidence:
                if ref.visibility != EvidenceVisibility.CLIENT_SAFE:
                    raise ValueError(
                        "CLIENT_SAFE assessments cannot carry internal evidence"
                    )
            for item in self.risk_items:
                if item.client_visibility != RiskClientVisibilityDecision.CLIENT_VISIBLE:
                    raise ValueError(
                        "CLIENT_SAFE assessments require CLIENT_VISIBLE risk items"
                    )
                if item.visibility != EvidenceVisibility.CLIENT_SAFE:
                    raise ValueError(
                        "CLIENT_SAFE assessments require CLIENT_SAFE item visibility"
                    )
                for ref in item.evidence:
                    if ref.visibility != EvidenceVisibility.CLIENT_SAFE:
                        raise ValueError(
                            "CLIENT_SAFE assessments cannot carry internal "
                            "risk-item evidence"
                        )

        top_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        for ref in self.evidence:
            if ref.period != RiskEvidencePeriod.CURRENT:
                raise ValueError("assessment evidence must use CURRENT period")
            if ref.source_fingerprint != self.source_fingerprint:
                raise ValueError(
                    "evidence source_fingerprint must match assessment fingerprint"
                )
            if _FORBIDDEN_DETAIL_CLAIMS.intersection(ref.claim_keys):
                raise ValueError("internal detail claims are not allowed top-level")
            key = _evidence_lineage_key(ref)
            top_claims.setdefault(key, set()).update(ref.claim_keys)

        item_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        for item in self.risk_items:
            if item.source_fingerprint != self.source_fingerprint:
                raise ValueError("item source_fingerprint must match assessment")
            for ref in item.evidence:
                if ref.source_fingerprint != self.source_fingerprint:
                    raise ValueError(
                        "risk-item evidence fingerprint must match assessment"
                    )
                key = _evidence_lineage_key(ref)
                claimed = top_claims.get(key)
                if claimed is None:
                    raise ValueError(
                        "risk-item evidence must exist in top-level assessment evidence"
                    )
                if not set(ref.claim_keys).issubset(claimed):
                    raise ValueError(
                        "risk-item claim keys must be included in top-level evidence"
                    )
                item_claims.setdefault(key, set()).update(ref.claim_keys)

        if self.availability == RiskTransparencyAvailability.AVAILABLE:
            if set(top_claims) != set(item_claims):
                raise ValueError(
                    "top-level evidence must equal the selected item evidence union"
                )
            for key, claims in item_claims.items():
                if top_claims[key] != claims:
                    raise ValueError(
                        "top-level claim union must equal the item claim union"
                    )
        return self
