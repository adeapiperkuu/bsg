"""Reusable AI explainability contracts for Client Intelligence outputs (Phase 19.3).

Every AI recommendation and scored guidance artifact can expose:

- why it was generated
- supporting evidence
- confidence score
- assumptions
- affected KPIs
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agents.client_intelligence.contracts import (
    ClientIntelligenceModel,
    EvidenceVisibility,
    SourceAgent,
)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ExplainabilityConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class ExplainabilityEvidenceRef(ClientIntelligenceModel):
    """Evidence identity supporting an AI conclusion."""

    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(default_factory=list)
    summary: str | None = None
    observed_at: datetime | None = None

    @field_validator("claim_keys")
    @classmethod
    def _canonical_claim_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item for item in value if item]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("claim_keys must be unique")
        return sorted(cleaned)

    @field_validator("observed_at")
    @classmethod
    def _aware_observed_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware when present")
        return value


class AiExplainability(ClientIntelligenceModel):
    """Reusable explainability payload attached to Client Intelligence AI outputs."""

    why_generated: str = Field(min_length=1)
    supporting_evidence: list[ExplainabilityEvidenceRef] = Field(default_factory=list)
    confidence_score: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    confidence_band: ExplainabilityConfidenceBand
    assumptions: list[str] = Field(default_factory=list)
    affected_kpis: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    model_version: str = "client_intelligence_explainability_v1"
    source_fingerprint: str | None = None
    generated_at: datetime | None = None

    @field_validator("assumptions", "affected_kpis")
    @classmethod
    def _canonicalize_strings(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip() if isinstance(item, str) else ""
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    @field_validator("affected_kpis")
    @classmethod
    def _validate_kpi_keys(cls, value: list[str]) -> list[str]:
        for item in value:
            if not _KEY_RE.match(item):
                raise ValueError("affected_kpis must be stable lowercase keys")
        return value

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SHA256_HEX.match(value):
            raise ValueError("source_fingerprint must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("generated_at")
    @classmethod
    def _aware_generated_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware when present")
        return value

    @model_validator(mode="after")
    def _band_matches_score(self) -> AiExplainability:
        score = self.confidence_score
        expected = confidence_band_for(score)
        if self.confidence_band != expected:
            raise ValueError(
                f"confidence_band {self.confidence_band.value} does not match "
                f"score {score} (expected {expected.value})"
            )
        return self


def confidence_band_for(score: Decimal) -> ExplainabilityConfidenceBand:
    """Map a 0–1 confidence score onto a stable band."""
    if score < Decimal("0.35"):
        return ExplainabilityConfidenceBand.INSUFFICIENT
    if score < Decimal("0.55"):
        return ExplainabilityConfidenceBand.LOW
    if score < Decimal("0.75"):
        return ExplainabilityConfidenceBand.MEDIUM
    return ExplainabilityConfidenceBand.HIGH


def build_explainability(
    *,
    why_generated: str,
    confidence_score: Decimal | float | int,
    supporting_evidence: list[ExplainabilityEvidenceRef] | None = None,
    assumptions: list[str] | None = None,
    affected_kpis: list[str] | None = None,
    reasoning: str | None = None,
    model_version: str = "client_intelligence_explainability_v1",
    source_fingerprint: str | None = None,
    generated_at: datetime | None = None,
) -> AiExplainability:
    """Construct a validated explainability payload."""
    score = Decimal(str(confidence_score))
    if score < Decimal("0"):
        score = Decimal("0")
    if score > Decimal("1"):
        score = Decimal("1")
    score = score.quantize(Decimal("0.01"))
    return AiExplainability(
        why_generated=why_generated.strip(),
        supporting_evidence=list(supporting_evidence or []),
        confidence_score=score,
        confidence_band=confidence_band_for(score),
        assumptions=list(assumptions or []),
        affected_kpis=list(affected_kpis or []),
        reasoning=reasoning.strip() if reasoning else None,
        model_version=model_version,
        source_fingerprint=source_fingerprint,
        generated_at=generated_at,
    )
