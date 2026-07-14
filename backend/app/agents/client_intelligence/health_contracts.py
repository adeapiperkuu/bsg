"""Typed Project Health contracts (Phase 2 foundation).

No production thresholds, narratives, recommendations, readiness dimensions,
or Delivery Confidence recalculation live here. Classification policy is
injected separately; CI-DQ07 remains unresolved.

Materiality ordering (deterministic ascending priority):
1. lower ``materiality`` first (0 = highest priority);
2. then polarity value;
3. then stable ``driver_key``;
4. then stable evidence identity / claim keys.
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

_SIGNAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class ProjectHealthStatus(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    INSUFFICIENT = "insufficient"


class ProjectHealthSignalState(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    WATCH = "watch"
    ADVERSE = "adverse"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTING = "conflicting"


class ProjectHealthTrend(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    DETERIORATING = "deteriorating"
    UNKNOWN = "unknown"


class ProjectHealthDriverPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ProjectHealthBindingType(StrEnum):
    """How a signal value relates to ClientEvidencePack source facts."""

    DIRECT = "direct"
    UNAVAILABLE = "unavailable"


def _require_signal_key(value: str) -> str:
    if not isinstance(value, str) or not _SIGNAL_KEY_RE.match(value):
        raise ValueError("must be a stable lowercase signal/driver key")
    return value


def _require_reason_code(value: str) -> str:
    if not isinstance(value, str) or not _REASON_CODE_RE.match(value):
        raise ValueError("must be a structured uppercase label")
    return value


def _require_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware when present")
    return value


def _require_source_table(value: str) -> str:
    if not isinstance(value, str) or not _SOURCE_TABLE_RE.match(value):
        raise ValueError("must be a stable lowercase source_table identifier")
    return value


class ProjectHealthEvidenceRef(ClientIntelligenceModel):
    """Exact evidence-reference identity plus supporting claim keys."""

    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(min_length=1)

    @field_validator("claim_keys")
    @classmethod
    def _canonical_claim_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item for item in value if item]
        if not cleaned:
            raise ValueError("claim_keys must be non-empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("claim_keys must be unique")
        return sorted(cleaned)


class ProjectHealthSignal(ClientIntelligenceModel):
    signal_key: Annotated[str, Field(min_length=1)]
    source_agent: SourceAgent
    source_table: Annotated[str, Field(min_length=1)]
    binding_type: ProjectHealthBindingType
    observed_value: str | int | bool | Decimal | date | datetime | None = None
    signal_state: ProjectHealthSignalState
    observed_at: datetime | None = None
    data_quality: DataQualityState
    evidence: list[ProjectHealthEvidenceRef] = Field(default_factory=list)
    limitation: str | None = None

    @field_validator("signal_key")
    @classmethod
    def _validate_signal_key(cls, value: str) -> str:
        return _require_signal_key(value)

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @field_validator("observed_value", mode="before")
    @classmethod
    def _reject_float_observed_value(cls, value: object) -> object:
        # Reject before Pydantic can coerce float -> Decimal.
        if type(value) is float:
            raise PydanticCustomError(
                "float_observed_value",
                "float observed_value is not accepted; use Exact Decimal or other governed types",
            )
        return value

    @field_validator("limitation")
    @classmethod
    def _validate_limitation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_reason_code(value)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)

    @model_validator(mode="after")
    def _binding_invariants(self) -> ProjectHealthSignal:
        if self.binding_type == ProjectHealthBindingType.DIRECT:
            if not self.evidence:
                raise ValueError("DIRECT signals require evidence references")
            if self.observed_value is None:
                raise ValueError("DIRECT signals require an observed value")
            if type(self.observed_value) is float:
                raise ValueError("float observed_value is not accepted")
        if self.binding_type == ProjectHealthBindingType.UNAVAILABLE:
            if self.observed_value is not None:
                raise ValueError("UNAVAILABLE signals must have observed_value=None")
            if self.limitation is None:
                raise ValueError("UNAVAILABLE signals require a structured limitation")
            if self.signal_state not in {
                ProjectHealthSignalState.UNAVAILABLE,
                ProjectHealthSignalState.STALE,
                ProjectHealthSignalState.CONFLICTING,
            }:
                raise ValueError(
                    "UNAVAILABLE binding requires UNAVAILABLE/STALE/CONFLICTING state"
                )
        return self


class ProjectHealthDriver(ClientIntelligenceModel):
    """Material contributor. Reason codes are structured labels only."""

    driver_key: Annotated[str, Field(min_length=1)]
    polarity: ProjectHealthDriverPolarity
    materiality: Annotated[int, Field(ge=0)]
    reason_code: Annotated[str, Field(min_length=1)]
    signal_keys: list[str] = Field(min_length=1)
    evidence: list[ProjectHealthEvidenceRef] = Field(min_length=1)

    @field_validator("driver_key")
    @classmethod
    def _validate_driver_key(cls, value: str) -> str:
        return _require_signal_key(value)

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, value: str) -> str:
        return _require_reason_code(value)

    @field_validator("signal_keys")
    @classmethod
    def _validate_signal_keys(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("signal_keys must be non-empty")
        cleaned = [_require_signal_key(item) for item in value]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("signal_keys must be unique")
        return sorted(cleaned)


class ProjectHealthPolicyDecision(ClientIntelligenceModel):
    proposed_status: ProjectHealthStatus
    signals: list[ProjectHealthSignal] = Field(default_factory=list)
    positive_drivers: list[ProjectHealthDriver] = Field(default_factory=list)
    negative_drivers: list[ProjectHealthDriver] = Field(default_factory=list)
    required_signal_keys: list[str] = Field(default_factory=list)
    missing_unreliable_required_signal_keys: list[str] = Field(default_factory=list)
    policy_limitations: list[str] = Field(default_factory=list)

    @field_validator("required_signal_keys", "missing_unreliable_required_signal_keys")
    @classmethod
    def _validate_key_lists(cls, value: list[str]) -> list[str]:
        cleaned = [_require_signal_key(item) for item in value]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("signal key lists must be unique")
        return sorted(cleaned)

    @field_validator("policy_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})


class ProjectHealthHistoryComparison(ClientIntelligenceModel):
    previous_status: ProjectHealthStatus | None = None
    current_status: ProjectHealthStatus
    trend: ProjectHealthTrend
    previous_reporting_period: ReportingPeriod | None = None
    added_driver_keys: list[str] = Field(default_factory=list)
    removed_driver_keys: list[str] = Field(default_factory=list)
    changed_driver_keys: list[str] = Field(default_factory=list)
    limitation: str | None = None


class ProjectHealthAssessment(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    reporting_period: ReportingPeriod
    visibility_mode: EvidenceVisibility
    status: ProjectHealthStatus
    rules_version: str | None = None
    source_fingerprint: str
    policy_fingerprint: str | None = None
    overall_data_quality: DataQualityState
    signals: list[ProjectHealthSignal] = Field(default_factory=list)
    positive_drivers: list[ProjectHealthDriver] = Field(default_factory=list)
    negative_drivers: list[ProjectHealthDriver] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[ProjectHealthEvidenceRef] = Field(default_factory=list)
    history: ProjectHealthHistoryComparison
    assessed_at: datetime

    @field_validator("assessed_at")
    @classmethod
    def _validate_assessed_at(cls, value: datetime) -> datetime:
        aware = _require_aware_datetime(value)
        assert aware is not None
        return aware
