"""Typed Delivery Confidence Intelligence contracts (Phase 2 foundation).

Score, status/band, milestone, and forecast remain Delivery-owned. Client
Intelligence adds explanation structure only. No production explanation policy
or confidence-band thresholds live here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.agents.client_intelligence.contracts import (
    ClientIntelligenceModel,
    DataQualityState,
    EvidenceVisibility,
    ReportingPeriod,
    SourceAgent,
)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_AVAILABILITY_QUALITY = {
    "available": DataQualityState.COMPLETE,
    "stale": DataQualityState.STALE,
    "conflicting": DataQualityState.CONFLICTING,
    "partial": DataQualityState.PARTIAL,
    "no_score": DataQualityState.UNAVAILABLE,
}

_REQUIRED_CURRENT_CONFIDENCE_CLAIMS = frozenset(
    {"score_pct", "confidence_status", "forecast_completion_date"}
)
_REQUIRED_MILESTONE_CLAIMS = frozenset(
    {"milestone_id", "milestone_name", "milestone_status", "planned_date"}
)
_ALLOWED_MILESTONE_CLAIMS = frozenset(
    {
        "milestone_id",
        "milestone_name",
        "milestone_status",
        "planned_date",
        "actual_date",
    }
)


class DeliveryConfidenceAvailability(StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    CONFLICTING = "conflicting"
    PARTIAL = "partial"
    NO_SCORE = "no_score"


class DeliveryConfidenceTrend(StrEnum):
    INCREASED = "increased"
    DECREASED = "decreased"
    STABLE = "stable"
    UNKNOWN = "unknown"


class MitigationContributionState(StrEnum):
    VERIFIED = "verified"
    NONE_PROVEN = "none_proven"
    UNAVAILABLE = "unavailable"


class DeliveryConfidenceDriverPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class DeliveryConfidenceCandidateCategory(StrEnum):
    DELIVERY_CONFIDENCE = "delivery_confidence"
    MILESTONE = "milestone"
    THROUGHPUT = "throughput"
    QUALITY = "quality"
    BOTTLENECK = "bottleneck"
    DEPENDENCY = "dependency"
    RISK = "risk"
    MITIGATION = "mitigation"


class DeliveryConfidenceEvidencePeriod(StrEnum):
    CURRENT = "current"
    PREVIOUS = "previous"


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
    """Pack-inherited limitation text: exact strings, blank-only rejected/filtered."""
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
    ref: DeliveryConfidenceEvidenceRef,
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


class DeliveryConfidenceEvidenceRef(ClientIntelligenceModel):
    """Exact pack evidence identity plus claim keys, observed_at, and period lineage."""

    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(min_length=1)
    period: DeliveryConfidenceEvidencePeriod
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
        return sorted(cleaned)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)


class DeliveryConfidenceMilestoneView(ClientIntelligenceModel):
    """Structured confidence-linked milestone facts (no free-text description)."""

    milestone_id: UUID
    name: str
    status: str
    planned_date: date
    actual_date: date | None = None
    evidence: list[DeliveryConfidenceEvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def _milestone_evidence_invariants(self) -> DeliveryConfidenceMilestoneView:
        merged: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        templates: dict[
            tuple[str, str, str, str, str, str, str], DeliveryConfidenceEvidenceRef
        ] = {}
        fingerprints: set[str] = set()
        visibilities: set[EvidenceVisibility] = set()

        for ref in self.evidence:
            if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
                raise ValueError(
                    "milestone evidence source_agent must be delivery_performance"
                )
            if ref.source_table != "milestones":
                raise ValueError("milestone evidence source_table must be milestones")
            if ref.source_row_id != self.milestone_id:
                raise ValueError(
                    "milestone evidence source_row_id must equal milestone_id"
                )
            if ref.period != DeliveryConfidenceEvidencePeriod.CURRENT:
                raise ValueError("current_milestone evidence must use CURRENT period")
            if not set(ref.claim_keys).issubset(_ALLOWED_MILESTONE_CLAIMS):
                raise ValueError("milestone evidence contains unsupported claim keys")

            fingerprints.add(ref.source_fingerprint)
            visibilities.add(ref.visibility)
            key = _evidence_lineage_key(ref)
            if key in merged:
                # Exact duplicate lineage may union claims; conflicting observed_at
                # already excluded by key including observed_at.
                pass
            merged.setdefault(key, set()).update(ref.claim_keys)
            templates.setdefault(key, ref)

        if len(fingerprints) != 1:
            raise ValueError("milestone evidence must share one source fingerprint")
        if len(visibilities) != 1:
            raise ValueError("milestone evidence must share one visibility")

        claim_union = set().union(*merged.values()) if merged else set()
        if not _REQUIRED_MILESTONE_CLAIMS.issubset(claim_union):
            raise ValueError(
                "milestone evidence must support milestone_id, milestone_name, "
                "milestone_status, and planned_date"
            )
        if self.actual_date is not None and "actual_date" not in claim_union:
            raise ValueError(
                "milestone evidence must support actual_date when actual_date is set"
            )

        canonical = [
            DeliveryConfidenceEvidenceRef(
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
        object.__setattr__(self, "evidence", canonical)
        return self


class DeliveryConfidenceCandidate(ClientIntelligenceModel):
    """Engine-owned verified candidate available to an explanation policy."""

    candidate_key: Annotated[str, Field(min_length=1)]
    category: DeliveryConfidenceCandidateCategory
    value: str | int | bool | Decimal | date | datetime | None
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    claim_key: str = Field(min_length=1)
    observed_at: datetime | None = None
    data_quality: DataQualityState
    visibility: EvidenceVisibility
    source_fingerprint: str = Field(min_length=64, max_length=64)

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

    @field_validator("value", mode="before")
    @classmethod
    def _reject_float_value(cls, value: object) -> object:
        if type(value) is float:
            raise PydanticCustomError(
                "float_candidate_value",
                "float candidate values are not accepted",
            )
        return value

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)


class DeliveryConfidenceCandidateContext(ClientIntelligenceModel):
    """Typed verified-candidate context built by the engine for explanation only."""

    candidates: list[DeliveryConfidenceCandidate] = Field(default_factory=list)
    context_limitations: list[str] = Field(default_factory=list)

    @field_validator("context_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})


class DeliveryConfidenceDriver(ClientIntelligenceModel):
    """
    Material explanation driver.

    Materiality ordering (deterministic ascending priority):
    1. lower materiality first (0 = highest priority);
    2. then polarity value;
    3. then stable driver_key;
    4. then stable evidence identity / claim keys / observed_at.
    """

    driver_key: Annotated[str, Field(min_length=1)]
    polarity: DeliveryConfidenceDriverPolarity
    category: DeliveryConfidenceCandidateCategory
    reason_code: Annotated[str, Field(min_length=1)]
    materiality: Annotated[int, Field(ge=0)]
    candidate_keys: list[str] = Field(min_length=1)
    evidence: list[DeliveryConfidenceEvidenceRef] = Field(min_length=1)
    data_quality: DataQualityState

    @field_validator("driver_key")
    @classmethod
    def _validate_driver_key(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, value: str) -> str:
        return _require_reason_code(value)

    @field_validator("candidate_keys")
    @classmethod
    def _validate_candidate_keys(cls, value: list[str]) -> list[str]:
        cleaned = [_require_key(item) for item in value]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("candidate_keys must be unique")
        return sorted(cleaned)


class DeliveryConfidenceExplanationDecision(ClientIntelligenceModel):
    """Policy-owned explanation only — never core Delivery facts."""

    positive_drivers: list[DeliveryConfidenceDriver] = Field(default_factory=list)
    negative_drivers: list[DeliveryConfidenceDriver] = Field(default_factory=list)
    policy_limitations: list[str] = Field(default_factory=list)

    @field_validator("policy_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})


class DeliveryConfidenceAssessment(ClientIntelligenceModel):
    """Deterministic Delivery Confidence Intelligence assessment."""

    org_id: UUID
    project_id: UUID
    reporting_period: ReportingPeriod
    visibility_mode: EvidenceVisibility
    availability: DeliveryConfidenceAvailability
    score_pct: Decimal | None = None
    confidence_band: str | None = None
    confidence_band_is_delivery_owned_status: bool = True
    current_milestone: DeliveryConfidenceMilestoneView | None = None
    forecast_completion_date: date | None = None
    observed_at: datetime | None = None
    source_data_quality: DataQualityState
    trend: DeliveryConfidenceTrend
    previous_score_pct: Decimal | None = None
    positive_drivers: list[DeliveryConfidenceDriver] = Field(default_factory=list)
    negative_drivers: list[DeliveryConfidenceDriver] = Field(default_factory=list)
    mitigation_contribution: MitigationContributionState
    limitations: list[str] = Field(default_factory=list)
    source_limitations: list[str] = Field(default_factory=list)
    evidence: list[DeliveryConfidenceEvidenceRef] = Field(default_factory=list)
    source_fingerprint: str = Field(min_length=64, max_length=64)
    previous_source_fingerprint: str | None = None
    rules_version: str | None = None
    assessed_at: datetime

    @field_validator("score_pct", mode="before")
    @classmethod
    def _reject_float_score(cls, value: object) -> object:
        if type(value) is float:
            raise PydanticCustomError(
                "float_score_pct",
                "float score_pct is not accepted; use Exact Decimal",
            )
        return value

    @field_validator("previous_score_pct", mode="before")
    @classmethod
    def _reject_float_previous_score(cls, value: object) -> object:
        if type(value) is float:
            raise PydanticCustomError(
                "float_previous_score_pct",
                "float previous_score_pct is not accepted; use Exact Decimal",
            )
        return value

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_source_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("previous_source_fingerprint")
    @classmethod
    def _validate_previous_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_sha256_hex(value)

    @field_validator("observed_at", "assessed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value if item})

    @field_validator("source_limitations")
    @classmethod
    def _validate_source_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_source_limitations(value)

    @model_validator(mode="after")
    def _core_invariants(self) -> DeliveryConfidenceAssessment:
        if self.confidence_band_is_delivery_owned_status is not True:
            raise ValueError("confidence_band must be declared delivery-owned")
        expected_quality = _AVAILABILITY_QUALITY[self.availability.value]
        if self.source_data_quality != expected_quality:
            raise ValueError("availability must match source_data_quality exactly")
        if type(self.score_pct) is float or type(self.previous_score_pct) is float:
            raise ValueError("float scores are not accepted")

        if self.availability == DeliveryConfidenceAvailability.NO_SCORE:
            if self.score_pct is not None or self.confidence_band is not None:
                raise ValueError("NO_SCORE assessments cannot carry a score or band")
            if self.current_milestone is not None:
                raise ValueError(
                    "NO_SCORE assessments cannot carry a confidence milestone"
                )
            if self.forecast_completion_date is not None:
                raise ValueError("NO_SCORE assessments cannot carry a forecast date")
            if self.positive_drivers or self.negative_drivers:
                raise ValueError(
                    "NO_SCORE assessments cannot carry explanation drivers"
                )
            if self.trend != DeliveryConfidenceTrend.UNKNOWN:
                raise ValueError("NO_SCORE assessments must use UNKNOWN trend")
        elif self.availability in {
            DeliveryConfidenceAvailability.AVAILABLE,
            DeliveryConfidenceAvailability.STALE,
            DeliveryConfidenceAvailability.CONFLICTING,
            DeliveryConfidenceAvailability.PARTIAL,
        }:
            if self.score_pct is None or not isinstance(self.score_pct, Decimal):
                raise ValueError("scored assessments require an exact Decimal score")
            if self.confidence_band is None:
                raise ValueError(
                    "scored assessments require Delivery-owned status/band"
                )
            if self.current_milestone is None:
                raise ValueError("scored assessments require the confidence milestone")
            if not any(
                ref.source_table == "delivery_confidence_scores"
                and ref.period == DeliveryConfidenceEvidencePeriod.CURRENT
                for ref in self.evidence
            ):
                raise ValueError(
                    "scored assessments require current confidence evidence"
                )

        if self.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
            for ref in self.evidence:
                if ref.visibility != EvidenceVisibility.CLIENT_SAFE:
                    raise ValueError(
                        "CLIENT_SAFE assessments cannot carry internal evidence"
                    )
            for driver in [*self.positive_drivers, *self.negative_drivers]:
                for ref in driver.evidence:
                    if ref.visibility != EvidenceVisibility.CLIENT_SAFE:
                        raise ValueError(
                            "CLIENT_SAFE assessments cannot carry internal "
                            "driver evidence"
                        )

        top_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        current_dc_claims: set[str] = set()
        previous_dc_claims: set[str] = set()
        for ref in self.evidence:
            if ref.period == DeliveryConfidenceEvidencePeriod.CURRENT:
                if ref.source_fingerprint != self.source_fingerprint:
                    raise ValueError(
                        "CURRENT evidence source_fingerprint must match assessment"
                    )
            elif ref.period == DeliveryConfidenceEvidencePeriod.PREVIOUS:
                if self.previous_source_fingerprint is None:
                    raise ValueError(
                        "PREVIOUS evidence requires previous_source_fingerprint"
                    )
                if ref.source_fingerprint != self.previous_source_fingerprint:
                    raise ValueError(
                        "PREVIOUS evidence source_fingerprint must match assessment"
                    )
            else:
                raise ValueError("unsupported evidence period")

            key = _evidence_lineage_key(ref)
            top_claims.setdefault(key, set()).update(ref.claim_keys)

            if (
                ref.source_table == "delivery_confidence_scores"
                and ref.period == DeliveryConfidenceEvidencePeriod.CURRENT
            ):
                if ref.observed_at != self.observed_at:
                    raise ValueError(
                        "current confidence evidence observed_at must equal "
                        "assessment.observed_at"
                    )
                current_dc_claims.update(ref.claim_keys)
            if (
                ref.source_table == "delivery_confidence_scores"
                and ref.period == DeliveryConfidenceEvidencePeriod.PREVIOUS
            ):
                previous_dc_claims.update(ref.claim_keys)

        if self.availability in {
            DeliveryConfidenceAvailability.AVAILABLE,
            DeliveryConfidenceAvailability.STALE,
            DeliveryConfidenceAvailability.CONFLICTING,
            DeliveryConfidenceAvailability.PARTIAL,
        } and not _REQUIRED_CURRENT_CONFIDENCE_CLAIMS.issubset(current_dc_claims):
            raise ValueError(
                "scored assessments require current confidence evidence "
                "supporting score_pct, confidence_status, and "
                "forecast_completion_date"
            )

        if self.trend in {
            DeliveryConfidenceTrend.INCREASED,
            DeliveryConfidenceTrend.DECREASED,
            DeliveryConfidenceTrend.STABLE,
        }:
            if self.score_pct is None or self.previous_score_pct is None:
                raise ValueError("calculated trend requires current and previous scores")
            if self.previous_source_fingerprint is None:
                raise ValueError("calculated trend requires previous source fingerprint")
            if "score_pct" not in previous_dc_claims:
                raise ValueError(
                    "calculated trend requires previous confidence evidence "
                    "supporting score_pct"
                )

        for driver in [*self.positive_drivers, *self.negative_drivers]:
            for ref in driver.evidence:
                key = _evidence_lineage_key(ref)
                claimed = top_claims.get(key)
                if claimed is None:
                    raise ValueError(
                        "driver evidence must exist in top-level assessment evidence"
                    )
                if not set(ref.claim_keys).issubset(claimed):
                    raise ValueError(
                        "driver evidence claim keys must be included in "
                        "top-level assessment evidence"
                    )

        if self.current_milestone is not None:
            milestone_claim_union: set[str] = set()
            for ref in self.current_milestone.evidence:
                if ref.source_fingerprint != self.source_fingerprint:
                    raise ValueError(
                        "current_milestone evidence fingerprint must match assessment"
                    )
                if ref.source_row_id != self.current_milestone.milestone_id:
                    raise ValueError(
                        "current_milestone evidence row must equal milestone_id"
                    )
                if (
                    self.visibility_mode == EvidenceVisibility.CLIENT_SAFE
                    and ref.visibility != EvidenceVisibility.CLIENT_SAFE
                ):
                    raise ValueError(
                        "CLIENT_SAFE assessments require CLIENT_SAFE milestone evidence"
                    )
                key = _evidence_lineage_key(ref)
                claimed = top_claims.get(key)
                if claimed is None:
                    raise ValueError(
                        "current_milestone evidence must exist in top-level "
                        "assessment evidence"
                    )
                if not set(ref.claim_keys).issubset(claimed):
                    raise ValueError(
                        "current_milestone claim keys must be included in "
                        "top-level assessment evidence"
                    )
                milestone_claim_union.update(ref.claim_keys)

            top_milestone_claims: set[str] = set()
            for ref in self.evidence:
                if (
                    ref.source_table == "milestones"
                    and ref.source_row_id == self.current_milestone.milestone_id
                    and ref.period == DeliveryConfidenceEvidencePeriod.CURRENT
                ):
                    top_milestone_claims.update(ref.claim_keys)
            if not milestone_claim_union.issubset(top_milestone_claims):
                raise ValueError(
                    "top-level evidence must preserve the complete milestone "
                    "claim union"
                )
            if not _REQUIRED_MILESTONE_CLAIMS.issubset(top_milestone_claims):
                raise ValueError(
                    "top-level assessment evidence must include complete "
                    "current milestone claim coverage"
                )

        return self
