"""Typed Project Readiness Assessment contracts (Phase 17.1).

Score and assessment confidence are intentionally separate. A high readiness
score with low evidence confidence must surface as uncertain, not “ready”.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agents.client_intelligence.contracts import (
    ClientIntelligenceModel,
    DataQualityState,
    EvidenceVisibility,
    SourceAgent,
)
from app.agents.client_intelligence.explainability import AiExplainability

_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_RULES_VERSION = "client_readiness_v1"

LIMITATION_READINESS_EVIDENCE_INCOMPLETE = "READINESS_EVIDENCE_INCOMPLETE"
LIMITATION_READINESS_HARD_BLOCKER = "READINESS_HARD_BLOCKER"
LIMITATION_READINESS_CATEGORY_UNAVAILABLE = "READINESS_CATEGORY_UNAVAILABLE"
LIMITATION_READINESS_CONFIDENCE_LOW = "READINESS_CONFIDENCE_LOW"

READINESS_CATEGORY_KEYS = (
    "resources",
    "planning",
    "risks",
    "dependencies",
    "documentation",
    "testing",
    "training",
    "governance",
)


class ReadinessAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTING = "conflicting"


class ReadinessStatus(StrEnum):
    READY = "ready"
    READY_WITH_MINOR_RISKS = "ready_with_minor_risks"
    CONDITIONALLY_READY = "conditionally_ready"
    NOT_READY = "not_ready"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReadinessCategoryKey(StrEnum):
    RESOURCES = "resources"
    PLANNING = "planning"
    RISKS = "risks"
    DEPENDENCIES = "dependencies"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    TRAINING = "training"
    GOVERNANCE = "governance"


class ReadinessFindingSeverity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    POSITIVE = "positive"


class ReadinessEvidencePeriod(StrEnum):
    CURRENT = "current"


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


def _canonicalize_strings(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("string list items must be strings")
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


class ReadinessEvidenceRef(ClientIntelligenceModel):
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    period: ReadinessEvidencePeriod = ReadinessEvidencePeriod.CURRENT
    claim_keys: list[str] = Field(default_factory=list)
    source_fingerprint: str | None = None
    observed_at: datetime | None = None

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @field_validator("claim_keys")
    @classmethod
    def _canonical_claim_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item for item in value if item]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("claim_keys must be unique")
        return sorted(cleaned)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_sha256_hex(value)

    @field_validator("observed_at")
    @classmethod
    def _aware_observed_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware when present")
        return value


class ReadinessFinding(ClientIntelligenceModel):
    finding_id: str = Field(min_length=1)
    category: ReadinessCategoryKey
    severity: ReadinessFindingSeverity
    summary: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    evidence: list[ReadinessEvidenceRef] = Field(default_factory=list)

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, value: str) -> str:
        return _require_reason_code(value)


class ReadinessCategoryScore(ClientIntelligenceModel):
    category: ReadinessCategoryKey
    score_pct: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    availability: ReadinessAvailability
    weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    missing_requirements: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    positive_findings: list[str] = Field(default_factory=list)
    evidence: list[ReadinessEvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_quality: DataQualityState

    @field_validator("missing_requirements", "blockers", "positive_findings", "limitations")
    @classmethod
    def _canonicalize_lists(cls, value: list[str]) -> list[str]:
        return _canonicalize_strings(value)

    @model_validator(mode="after")
    def _score_invariants(self) -> ReadinessCategoryScore:
        if self.availability in {
            ReadinessAvailability.UNAVAILABLE,
            ReadinessAvailability.CONFLICTING,
        } and self.score_pct is not None:
            raise ValueError("unavailable/conflicting categories must not carry scores")
        if (
            self.availability == ReadinessAvailability.AVAILABLE
            and self.score_pct is None
        ):
            raise ValueError("available categories require score_pct")
        return self


class ReadinessAssessment(ClientIntelligenceModel):
    """Overall project readiness with category breakdown and findings."""

    org_id: UUID
    project_id: UUID
    as_of: date
    assessed_at: datetime
    availability: ReadinessAvailability
    overall_score_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    status: ReadinessStatus
    assessment_confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    categories: list[ReadinessCategoryScore] = Field(min_length=8, max_length=8)
    missing_requirements: list[str] = Field(default_factory=list)
    major_blockers: list[str] = Field(default_factory=list)
    positive_findings: list[str] = Field(default_factory=list)
    findings: list[ReadinessFinding] = Field(default_factory=list)
    evidence: list[ReadinessEvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_fingerprint: str
    rules_version: str = _RULES_VERSION
    explainability: AiExplainability | None = None

    @field_validator("missing_requirements", "major_blockers", "positive_findings", "limitations")
    @classmethod
    def _canonicalize_lists(cls, value: list[str]) -> list[str]:
        return _canonicalize_strings(value)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("assessed_at")
    @classmethod
    def _aware_assessed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("assessed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _assessment_invariants(self) -> ReadinessAssessment:
        keys = [item.category for item in self.categories]
        if len(keys) != len(set(keys)):
            raise ValueError("categories must be unique")
        expected = {ReadinessCategoryKey(key) for key in READINESS_CATEGORY_KEYS}
        if set(keys) != expected:
            raise ValueError("categories must cover all eight readiness dimensions")
        if self.status == ReadinessStatus.INSUFFICIENT_EVIDENCE:
            if self.overall_score_pct is not None and self.availability == (
                ReadinessAvailability.UNAVAILABLE
            ):
                raise ValueError(
                    "unavailable insufficient assessments must not publish overall scores"
                )
        if (
            self.availability == ReadinessAvailability.AVAILABLE
            and self.overall_score_pct is None
        ):
            raise ValueError("available readiness requires overall_score_pct")
        if self.major_blockers and self.status in {
            ReadinessStatus.READY,
            ReadinessStatus.READY_WITH_MINOR_RISKS,
        }:
            raise ValueError("ready statuses cannot retain major blockers")
        return self


def readiness_status_for(
    score_pct: Decimal | None,
    *,
    has_hard_blocker: bool,
    assessment_confidence: Decimal,
    scored_category_count: int,
) -> ReadinessStatus:
    """Map score + blockers + confidence onto a readiness status band."""
    if scored_category_count < 4 or assessment_confidence < Decimal("0.35"):
        return ReadinessStatus.INSUFFICIENT_EVIDENCE
    if has_hard_blocker or score_pct is None:
        return ReadinessStatus.NOT_READY
    if score_pct >= Decimal("90"):
        return ReadinessStatus.READY
    if score_pct >= Decimal("75"):
        return ReadinessStatus.READY_WITH_MINOR_RISKS
    if score_pct >= Decimal("50"):
        return ReadinessStatus.CONDITIONALLY_READY
    return ReadinessStatus.NOT_READY


def readiness_status_label(status: ReadinessStatus) -> str:
    return {
        ReadinessStatus.READY: "Ready",
        ReadinessStatus.READY_WITH_MINOR_RISKS: "Ready with Minor Risks",
        ReadinessStatus.CONDITIONALLY_READY: "Conditionally Ready",
        ReadinessStatus.NOT_READY: "Not Ready",
        ReadinessStatus.INSUFFICIENT_EVIDENCE: "Insufficient Evidence",
    }[status]
