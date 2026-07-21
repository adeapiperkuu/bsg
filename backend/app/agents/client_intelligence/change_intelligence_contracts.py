"""Typed Change Intelligence contracts (Phase 2 foundation).

Compares governed facts across two validated, aligned ClientEvidencePack
instances. Materiality and business meaning remain policy-owned. No production
materiality policy or threshold lives here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
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
from app.agents.client_intelligence.evidence_validation import source_agent_owns_table

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_COMPARISON_IDENTITY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,255}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_RULES_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE = "PREVIOUS_REPORTING_CYCLE_UNAVAILABLE"
LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE = "CHANGE_MATERIALITY_POLICY_UNAVAILABLE"
LIMITATION_CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE = (
    "CHANGE_NOT_EVALUATED_UNRELIABLE_SOURCE"
)
LIMITATION_READINESS_INTELLIGENCE_UNAVAILABLE = "READINESS_INTELLIGENCE_UNAVAILABLE"
LIMITATION_RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE = (
    "RESOURCE_ONBOARDING_SOURCE_UNAVAILABLE"
)
LIMITATION_THROUGHPUT_ACTUAL_NOT_CLIENT_VISIBLE = "THROUGHPUT_ACTUAL_NOT_CLIENT_VISIBLE"
LIMITATION_THROUGHPUT_FORECAST_NOT_CLIENT_VISIBLE = (
    "THROUGHPUT_FORECAST_NOT_CLIENT_VISIBLE"
)
LIMITATION_RISK_HISTORY_LIMITED = "RISK_HISTORY_LIMITED"
LIMITATION_MILESTONE_HISTORY_LIMITED = "MILESTONE_HISTORY_LIMITED"
LIMITATION_GOVERNANCE_HISTORY_LIMITED = "GOVERNANCE_HISTORY_LIMITED"
LIMITATION_MILESTONE_CREATION_HISTORY_UNAVAILABLE = (
    "MILESTONE_CREATION_HISTORY_UNAVAILABLE"
)
LIMITATION_MILESTONE_CLOSURE_HISTORY_UNAVAILABLE = (
    "MILESTONE_CLOSURE_HISTORY_UNAVAILABLE"
)
LIMITATION_RISK_CREATION_HISTORY_UNAVAILABLE = "RISK_CREATION_HISTORY_UNAVAILABLE"
LIMITATION_RISK_CLOSURE_HISTORY_UNAVAILABLE = "RISK_CLOSURE_HISTORY_UNAVAILABLE"

_FORBIDDEN_EVIDENCE_CLAIMS = frozenset(
    {
        "risk_detail",
        "bottleneck_detail",
        "milestone_name",
        "risk_title",
        "bottleneck_title",
    }
)

_ALL_DOMAINS_ORDERED: tuple[ChangeDomain, ...]


class ChangeDomain(StrEnum):
    THROUGHPUT = "throughput"
    QUALITY = "quality"
    REWORK = "rework"
    DELIVERY_CONFIDENCE = "delivery_confidence"
    MILESTONE = "milestone"
    RISK = "risk"
    READINESS = "readiness"
    WORKFORCE_CAPACITY = "workforce_capacity"
    SME_COVERAGE = "sme_coverage"
    GOVERNANCE_DEPENDENCY = "governance_dependency"
    GOVERNANCE_ACTION = "governance_action"
    RESOURCE_ONBOARDING = "resource_onboarding"


_ALL_DOMAINS_ORDERED = tuple(ChangeDomain)


class ChangeDirection(StrEnum):
    INCREASED = "increased"
    DECREASED = "decreased"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNKNOWN = "unknown"


class ChangeValueType(StrEnum):
    DECIMAL = "decimal"
    INTEGER = "integer"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    NONE = "none"


class ChangeEvidencePeriod(StrEnum):
    PREVIOUS = "previous"
    CURRENT = "current"


class ChangeMateriality(StrEnum):
    MATERIAL = "material"
    NOT_MATERIAL = "not_material"


class ChangeIntelligenceAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTING = "conflicting"


class ChangeDomainCoverageState(StrEnum):
    EVALUATED = "evaluated"
    UNAVAILABLE = "unavailable"
    UNRELIABLE = "unreliable"
    POLICY_NOT_EVALUATED = "policy_not_evaluated"


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


def _require_comparison_identity(value: str) -> str:
    if not isinstance(value, str) or not _COMPARISON_IDENTITY_RE.match(value):
        raise ValueError("must be a canonical comparison identity")
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


def _canonicalize_period_text_limitations(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("source limitation text must be strings")
        if not item.strip():
            continue
        cleaned.append(item)
    return sorted(set(cleaned))


def _observed_at_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


class ChangeComparisonPeriod(ClientIntelligenceModel):
    previous_start_date: date
    previous_end_date: date
    current_start_date: date
    current_end_date: date


def require_rules_version(value: str) -> str:
    if not isinstance(value, str) or not _RULES_VERSION_RE.match(value):
        raise ValueError("rules_version must be a stable non-empty identifier")
    return value


def encode_scalar(value: Any) -> tuple[ChangeValueType, Any]:
    if value is None:
        return ChangeValueType.NONE, None
    if type(value) is float:
        raise ValueError("float values are not accepted")
    if isinstance(value, Decimal):
        return ChangeValueType.DECIMAL, value
    if isinstance(value, bool):
        return ChangeValueType.BOOLEAN, value
    if isinstance(value, int):
        return ChangeValueType.INTEGER, value
    if isinstance(value, str):
        return ChangeValueType.STRING, value
    if isinstance(value, date) and not isinstance(value, datetime):
        return ChangeValueType.DATE, value
    if isinstance(value, datetime):
        return ChangeValueType.DATETIME, value
    raise ValueError("unsupported scalar value type")


def decode_scalar(value_type: ChangeValueType, raw: Any) -> Any:
    if value_type == ChangeValueType.NONE:
        return None
    if value_type == ChangeValueType.DECIMAL:
        if not isinstance(raw, Decimal):
            raise ValueError("decimal value required")
        return raw
    if value_type == ChangeValueType.INTEGER:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError("integer value required")
        return raw
    if value_type == ChangeValueType.STRING:
        if not isinstance(raw, str):
            raise ValueError("string value required")
        return raw
    if value_type == ChangeValueType.BOOLEAN:
        if not isinstance(raw, bool):
            raise ValueError("boolean value required")
        return raw
    if value_type == ChangeValueType.DATE:
        if not isinstance(raw, date) or isinstance(raw, datetime):
            raise ValueError("date value required")
        return raw
    if value_type == ChangeValueType.DATETIME:
        if not isinstance(raw, datetime):
            raise ValueError("datetime value required")
        return raw
    raise ValueError("unsupported value_type")


def exact_claim_keys_for_metric(domain: ChangeDomain, metric_key: str) -> frozenset[str]:
    if domain == ChangeDomain.THROUGHPUT:
        return frozenset({"snapshot_date", metric_key})
    if domain in {ChangeDomain.QUALITY, ChangeDomain.REWORK}:
        return frozenset({"iso_year", "iso_week", metric_key})
    if domain == ChangeDomain.DELIVERY_CONFIDENCE:
        claim = (
            "confidence_status"
            if metric_key == "confidence_status"
            else metric_key
        )
        return frozenset({claim})
    if domain == ChangeDomain.MILESTONE:
        if metric_key == "milestone_status":
            return frozenset({"milestone_id", "milestone_status"})
        if metric_key == "planned_date":
            return frozenset({"milestone_id", "planned_date"})
        if metric_key == "actual_date":
            return frozenset({"milestone_id", "actual_date"})
    if domain == ChangeDomain.RISK:
        if metric_key == "status":
            return frozenset({"risk_id", "status"})
        if metric_key == "risk_tier":
            return frozenset({"risk_id", "risk_tier"})
        if metric_key == "alert_type":
            return frozenset({"risk_id", "alert_type"})
    if domain == ChangeDomain.GOVERNANCE_DEPENDENCY:
        return frozenset({"dependency_id", metric_key})
    if domain == ChangeDomain.GOVERNANCE_ACTION:
        return frozenset({"action_id", metric_key})
    if domain in {ChangeDomain.WORKFORCE_CAPACITY, ChangeDomain.SME_COVERAGE}:
        return frozenset({metric_key})
    raise ValueError("unsupported domain/metric claim binding")


def canonical_comparison_identity(
    *,
    domain: ChangeDomain,
    metric_key: str,
    entity_id: UUID | None = None,
    team_key: str | None = None,
) -> str:
    parts = [domain.value]
    if entity_id is not None:
        parts.append(entity_id.hex)
    elif team_key is not None:
        parts.append(team_key)
    parts.append(metric_key)
    identity = ":".join(parts)
    return _require_comparison_identity(identity)


class ChangeSourceRowIdentity(ClientIntelligenceModel):
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @model_validator(mode="after")
    def _ownership(self) -> ChangeSourceRowIdentity:
        if not source_agent_owns_table(self.source_agent, self.source_table):
            raise ValueError("source_agent does not own source_table")
        return self


class ChangeEvidenceReference(ClientIntelligenceModel):
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(min_length=1)
    period: ChangeEvidencePeriod
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
        if _FORBIDDEN_EVIDENCE_CLAIMS.intersection(cleaned):
            raise ValueError("forbidden descriptive claim keys are not allowed")
        return sorted(cleaned)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)

    @model_validator(mode="after")
    def _ownership(self) -> ChangeEvidenceReference:
        if not source_agent_owns_table(self.source_agent, self.source_table):
            raise ValueError("source_agent does not own source_table")
        return self


class ChangeScalarValue(ClientIntelligenceModel):
    value_type: ChangeValueType
    decimal_value: Decimal | None = None
    integer_value: int | None = None
    string_value: str | None = None
    boolean_value: bool | None = None
    date_value: date | None = None
    datetime_value: datetime | None = None

    @field_validator("decimal_value", mode="before")
    @classmethod
    def _reject_float_decimal(cls, value: object) -> object:
        if type(value) is float:
            raise PydanticCustomError(
                "float_scalar_value",
                "float scalar values are not accepted",
            )
        return value

    @model_validator(mode="after")
    def _scalar_invariants(self) -> ChangeScalarValue:
        if self.value_type == ChangeValueType.NONE:
            if any(
                item is not None
                for item in (
                    self.decimal_value,
                    self.integer_value,
                    self.string_value,
                    self.boolean_value,
                    self.date_value,
                    self.datetime_value,
                )
            ):
                raise ValueError("none value_type requires all value slots empty")
            return self
        if self.value_type == ChangeValueType.DECIMAL:
            if self.decimal_value is None or any(
                item is not None
                for item in (
                    self.integer_value,
                    self.string_value,
                    self.boolean_value,
                    self.date_value,
                    self.datetime_value,
                )
            ):
                raise ValueError("decimal value_type requires decimal_value only")
            return self
        if self.value_type == ChangeValueType.INTEGER:
            if self.integer_value is None or isinstance(self.integer_value, bool):
                raise ValueError("integer value_type requires integer_value only")
            return self
        if self.value_type == ChangeValueType.STRING:
            if self.string_value is None:
                raise ValueError("string value_type requires string_value")
            return self
        if self.value_type == ChangeValueType.BOOLEAN:
            if self.boolean_value is None:
                raise ValueError("boolean value_type requires boolean_value")
            return self
        if self.value_type == ChangeValueType.DATE:
            if self.date_value is None:
                raise ValueError("date value_type requires date_value")
            return self
        if self.value_type == ChangeValueType.DATETIME:
            if self.datetime_value is None:
                raise ValueError("datetime value_type requires datetime_value")
            return self
        raise ValueError("unsupported value_type")

    def to_python(self) -> Any:
        return decode_scalar(
            self.value_type,
            {
                ChangeValueType.DECIMAL: self.decimal_value,
                ChangeValueType.INTEGER: self.integer_value,
                ChangeValueType.STRING: self.string_value,
                ChangeValueType.BOOLEAN: self.boolean_value,
                ChangeValueType.DATE: self.date_value,
                ChangeValueType.DATETIME: self.datetime_value,
                ChangeValueType.NONE: None,
            }[self.value_type],
        )

    @classmethod
    def from_python(cls, value: Any) -> ChangeScalarValue:
        value_type, raw = encode_scalar(value)
        payload: dict[str, Any] = {"value_type": value_type}
        if value_type == ChangeValueType.DECIMAL:
            payload["decimal_value"] = raw
        elif value_type == ChangeValueType.INTEGER:
            payload["integer_value"] = raw
        elif value_type == ChangeValueType.STRING:
            payload["string_value"] = raw
        elif value_type == ChangeValueType.BOOLEAN:
            payload["boolean_value"] = raw
        elif value_type == ChangeValueType.DATE:
            payload["date_value"] = raw
        elif value_type == ChangeValueType.DATETIME:
            payload["datetime_value"] = raw
        return cls.model_validate(payload)


def _validate_evidence_identity_closure(
    refs: list[ChangeEvidenceReference],
    *,
    identity: ChangeSourceRowIdentity,
    period: ChangeEvidencePeriod,
    fingerprint: str,
    required_claims: frozenset[str],
) -> None:
    if not refs:
        raise ValueError("evidence must be non-empty")
    for ref in refs:
        if ref.period != period:
            raise ValueError("evidence period mismatch")
        if ref.source_fingerprint != fingerprint:
            raise ValueError("evidence fingerprint mismatch")
        if (
            ref.source_agent != identity.source_agent
            or ref.source_table != identity.source_table
            or ref.source_row_id != identity.source_row_id
        ):
            raise ValueError("evidence source identity mismatch")
        if frozenset(ref.claim_keys) != required_claims:
            raise ValueError("evidence claim_keys must match exact metric binding")


class ChangeCandidate(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    candidate_key: Annotated[str, Field(min_length=1)]
    domain: ChangeDomain
    metric_key: Annotated[str, Field(min_length=1)]
    comparison_identity: Annotated[str, Field(min_length=1)]
    previous_source: ChangeSourceRowIdentity
    current_source: ChangeSourceRowIdentity
    previous_value: ChangeScalarValue
    current_value: ChangeScalarValue
    value_type: ChangeValueType
    direction: ChangeDirection
    previous_data_quality: DataQualityState | None = None
    current_data_quality: DataQualityState | None = None
    previous_evidence: list[ChangeEvidenceReference] = Field(min_length=1)
    current_evidence: list[ChangeEvidenceReference] = Field(min_length=1)
    previous_source_fingerprint: str = Field(min_length=64, max_length=64)
    current_source_fingerprint: str = Field(min_length=64, max_length=64)
    comparison_period: ChangeComparisonPeriod
    limitations: list[str] = Field(default_factory=list)

    @field_validator("candidate_key", "metric_key")
    @classmethod
    def _validate_keys(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("comparison_identity")
    @classmethod
    def _validate_comparison_identity(cls, value: str) -> str:
        return _require_comparison_identity(value)

    @field_validator("previous_source_fingerprint", "current_source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _candidate_invariants(self) -> ChangeCandidate:
        if self.direction == ChangeDirection.UNCHANGED:
            raise ValueError("unchanged candidates must not be published as changes")
        if self.previous_value.value_type != self.value_type:
            raise ValueError("previous_value value_type must match candidate value_type")
        if self.current_value.value_type != self.value_type:
            raise ValueError("current_value value_type must match candidate value_type")
        required_claims = exact_claim_keys_for_metric(self.domain, self.metric_key)
        _validate_evidence_identity_closure(
            self.previous_evidence,
            identity=self.previous_source,
            period=ChangeEvidencePeriod.PREVIOUS,
            fingerprint=self.previous_source_fingerprint,
            required_claims=required_claims,
        )
        _validate_evidence_identity_closure(
            self.current_evidence,
            identity=self.current_source,
            period=ChangeEvidencePeriod.CURRENT,
            fingerprint=self.current_source_fingerprint,
            required_claims=required_claims,
        )
        return self

    @property
    def is_reliable(self) -> bool:
        return (
            self.previous_data_quality == DataQualityState.COMPLETE
            and self.current_data_quality == DataQualityState.COMPLETE
            and self.direction != ChangeDirection.UNKNOWN
        )


class ChangeDomainComparisonOutcome(ClientIntelligenceModel):
    domain: ChangeDomain
    state: ChangeDomainCoverageState
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})


class ChangeComparisonResult(ClientIntelligenceModel):
    candidates: list[ChangeCandidate] = Field(default_factory=list)
    domain_outcomes: list[ChangeDomainComparisonOutcome] = Field(min_length=1)
    comparison_limitations: list[str] = Field(default_factory=list)

    @field_validator("comparison_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _comparison_invariants(self) -> ChangeComparisonResult:
        if len(self.domain_outcomes) != len(_ALL_DOMAINS_ORDERED):
            raise ValueError("domain_outcomes must include every ChangeDomain exactly once")
        domains = [item.domain for item in self.domain_outcomes]
        if domains != list(_ALL_DOMAINS_ORDERED):
            raise ValueError("domain_outcomes must use canonical ChangeDomain order")
        if len(domains) != len(set(domains)):
            raise ValueError("domain_outcomes must not duplicate domains")
        keys = [item.candidate_key for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate keys must be unique")
        return self


class ChangeCandidateContext(ClientIntelligenceModel):
    candidates: list[ChangeCandidate] = Field(default_factory=list)
    context_limitations: list[str] = Field(default_factory=list)

    @field_validator("context_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _context_invariants(self) -> ChangeCandidateContext:
        keys = [item.candidate_key for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate keys must be unique")
        return self


class ChangeMaterialitySelection(ClientIntelligenceModel):
    candidate_key: Annotated[str, Field(min_length=1)]
    materiality: ChangeMateriality
    business_meaning_code: Annotated[str, Field(min_length=1)]
    priority: int

    @field_validator("candidate_key")
    @classmethod
    def _validate_candidate_key(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("business_meaning_code")
    @classmethod
    def _validate_business_meaning(cls, value: str) -> str:
        return _require_reason_code(value)


class ChangeMaterialityPolicyDecision(ClientIntelligenceModel):
    selections: list[ChangeMaterialitySelection] = Field(default_factory=list)
    policy_limitations: list[str] = Field(default_factory=list)

    @field_validator("policy_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _unique_selections(self) -> ChangeMaterialityPolicyDecision:
        keys = [item.candidate_key for item in self.selections]
        if len(keys) != len(set(keys)):
            raise ValueError("policy selections must use unique candidate keys")
        return self


class ChangeDomainCoverageItem(ClientIntelligenceModel):
    domain: ChangeDomain
    state: ChangeDomainCoverageState


class ChangeItem(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    candidate_key: Annotated[str, Field(min_length=1)]
    domain: ChangeDomain
    metric_key: Annotated[str, Field(min_length=1)]
    comparison_identity: Annotated[str, Field(min_length=1)]
    previous_source: ChangeSourceRowIdentity
    current_source: ChangeSourceRowIdentity
    previous_value: ChangeScalarValue
    current_value: ChangeScalarValue
    direction: ChangeDirection
    materiality: ChangeMateriality
    business_meaning_code: Annotated[str, Field(min_length=1)]
    priority: int
    previous_evidence: list[ChangeEvidenceReference] = Field(min_length=1)
    current_evidence: list[ChangeEvidenceReference] = Field(min_length=1)
    previous_source_fingerprint: str = Field(min_length=64, max_length=64)
    current_source_fingerprint: str = Field(min_length=64, max_length=64)
    previous_data_quality: DataQualityState
    current_data_quality: DataQualityState
    comparison_period: ChangeComparisonPeriod
    limitations: list[str] = Field(default_factory=list)

    @field_validator("candidate_key", "metric_key")
    @classmethod
    def _validate_keys(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("comparison_identity")
    @classmethod
    def _validate_comparison_identity(cls, value: str) -> str:
        return _require_comparison_identity(value)

    @field_validator("business_meaning_code")
    @classmethod
    def _validate_business_meaning(cls, value: str) -> str:
        return _require_reason_code(value)

    @field_validator("previous_source_fingerprint", "current_source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _published_invariants(self) -> ChangeItem:
        if self.previous_data_quality != DataQualityState.COMPLETE:
            raise ValueError("published changes require COMPLETE previous_data_quality")
        if self.current_data_quality != DataQualityState.COMPLETE:
            raise ValueError("published changes require COMPLETE current_data_quality")
        if self.direction == ChangeDirection.UNCHANGED:
            raise ValueError("unchanged facts must not be published")
        required_claims = exact_claim_keys_for_metric(self.domain, self.metric_key)
        _validate_evidence_identity_closure(
            self.previous_evidence,
            identity=self.previous_source,
            period=ChangeEvidencePeriod.PREVIOUS,
            fingerprint=self.previous_source_fingerprint,
            required_claims=required_claims,
        )
        _validate_evidence_identity_closure(
            self.current_evidence,
            identity=self.current_source,
            period=ChangeEvidencePeriod.CURRENT,
            fingerprint=self.current_source_fingerprint,
            required_claims=required_claims,
        )
        return self


class ChangeIntelligenceAssessment(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    current_reporting_period: ReportingPeriod
    previous_reporting_period: ReportingPeriod | None = None
    visibility_mode: EvidenceVisibility
    availability: ChangeIntelligenceAvailability
    changes: list[ChangeItem] = Field(default_factory=list)
    detected_candidate_count: int = Field(ge=0)
    evaluated_candidate_count: int = Field(ge=0)
    published_change_count: int = Field(ge=0)
    policy_evaluated: bool
    domain_coverage: list[ChangeDomainCoverageItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    previous_source_limitations: list[str] = Field(default_factory=list)
    current_source_limitations: list[str] = Field(default_factory=list)
    evidence: list[ChangeEvidenceReference] = Field(default_factory=list)
    previous_source_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    current_source_fingerprint: str = Field(min_length=64, max_length=64)
    rules_version: str | None = None
    assessed_at: datetime

    @field_validator("current_source_fingerprint")
    @classmethod
    def _validate_current_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("previous_source_fingerprint")
    @classmethod
    def _validate_previous_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
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

    @field_validator("previous_source_limitations", "current_source_limitations")
    @classmethod
    def _validate_source_limitations(cls, value: list[str]) -> list[str]:
        return _canonicalize_period_text_limitations(value)

    @model_validator(mode="after")
    def _assessment_invariants(self) -> ChangeIntelligenceAssessment:
        if self.published_change_count != len(self.changes):
            raise ValueError("published_change_count must equal changes length")
        if self.published_change_count > self.evaluated_candidate_count:
            raise ValueError(
                "published_change_count must be <= evaluated_candidate_count"
            )
        if self.evaluated_candidate_count > self.detected_candidate_count:
            raise ValueError(
                "evaluated_candidate_count must be <= detected_candidate_count"
            )

        if self.policy_evaluated:
            if self.rules_version is None:
                raise ValueError("policy_evaluated requires rules_version")
            if LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE in self.limitations:
                raise ValueError(
                    "policy_evaluated cannot include missing policy limitation"
                )
            if self.evaluated_candidate_count <= 0:
                raise ValueError(
                    "policy_evaluated requires reliable candidates evaluated"
                )
        else:
            if self.rules_version is not None:
                raise ValueError("rules_version requires policy_evaluated")
            if self.evaluated_candidate_count != 0:
                raise ValueError(
                    "evaluated_candidate_count must be 0 when policy was not evaluated"
                )

        if len(self.domain_coverage) != len(_ALL_DOMAINS_ORDERED):
            raise ValueError("domain_coverage must include every ChangeDomain exactly once")
        coverage_domains = [item.domain for item in self.domain_coverage]
        if coverage_domains != list(_ALL_DOMAINS_ORDERED):
            raise ValueError("domain_coverage must use canonical ChangeDomain order")
        if len(coverage_domains) != len(set(coverage_domains)):
            raise ValueError("domain_coverage must not duplicate domains")

        published_evidence: list[ChangeEvidenceReference] = []
        for item in self.changes:
            published_evidence.extend(item.previous_evidence)
            published_evidence.extend(item.current_evidence)
        canonical = _canonical_evidence_union(published_evidence)
        if canonical != _canonical_evidence_union(self.evidence):
            raise ValueError("top-level evidence must equal published change evidence union")
        if not self.changes and self.evidence:
            raise ValueError("no published changes requires empty top-level evidence")

        keys = [item.candidate_key for item in self.changes]
        if len(keys) != len(set(keys)):
            raise ValueError("published change candidate keys must be unique")

        if self.previous_reporting_period is None:
            if self.availability != ChangeIntelligenceAvailability.UNAVAILABLE:
                raise ValueError(
                    "missing previous period requires UNAVAILABLE availability"
                )
            if self.changes:
                raise ValueError("missing previous period cannot publish changes")
            if self.evidence:
                raise ValueError("missing previous period requires empty evidence")
            if self.previous_source_fingerprint is not None:
                raise ValueError("missing previous period requires no previous fingerprint")
            if LIMITATION_PREVIOUS_REPORTING_CYCLE_UNAVAILABLE not in self.limitations:
                raise ValueError(
                    "missing previous period requires PREVIOUS_REPORTING_CYCLE_UNAVAILABLE"
                )
        elif self.previous_reporting_period is not None:
            period = self.current_reporting_period
            prev = self.previous_reporting_period
            if not (
                prev.start_date == period.previous_start_date
                and prev.end_date == period.previous_end_date
            ):
                raise ValueError("previous_reporting_period must align to current previous cycle")
            if prev.end_date >= period.start_date:
                raise ValueError("previous and current reporting periods must not overlap")

        if self.changes and not self.policy_evaluated:
            raise ValueError("published changes require policy_evaluated")
        if LIMITATION_CHANGE_MATERIALITY_POLICY_UNAVAILABLE in self.limitations and self.changes:
            raise ValueError("missing materiality policy cannot publish changes")

        if self.availability == ChangeIntelligenceAvailability.UNAVAILABLE and self.changes:
            raise ValueError("unavailable assessment cannot publish changes")

        if self.availability == ChangeIntelligenceAvailability.AVAILABLE:
            raise ValueError("bounded foundation assessments cannot be AVAILABLE")

        for item in self.changes:
            if item.org_id != self.org_id:
                raise ValueError("published change org_id must match assessment")
            if item.project_id != self.project_id:
                raise ValueError("published change project_id must match assessment")
            if self.previous_reporting_period is not None:
                period = self.current_reporting_period
                prev = self.previous_reporting_period
                cp = item.comparison_period
                if cp.previous_start_date != prev.start_date:
                    raise ValueError(
                        "published change previous_start_date must match assessment"
                    )
                if cp.previous_end_date != prev.end_date:
                    raise ValueError(
                        "published change previous_end_date must match assessment"
                    )
                if cp.current_start_date != period.start_date:
                    raise ValueError(
                        "published change current_start_date must match assessment"
                    )
                if cp.current_end_date != period.end_date:
                    raise ValueError(
                        "published change current_end_date must match assessment"
                    )
            if item.previous_source_fingerprint != self.previous_source_fingerprint:
                raise ValueError("published previous fingerprint must match assessment")
            if item.current_source_fingerprint != self.current_source_fingerprint:
                raise ValueError("published current fingerprint must match assessment")

        return self


def _evidence_lineage_key(
    ref: ChangeEvidenceReference,
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


def _canonical_evidence_union(
    refs: list[ChangeEvidenceReference],
) -> list[ChangeEvidenceReference]:
    merged: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
    templates: dict[tuple[str, str, str, str, str, str, str], ChangeEvidenceReference] = {}
    for ref in refs:
        key = _evidence_lineage_key(ref)
        merged.setdefault(key, set()).update(ref.claim_keys)
        templates.setdefault(key, ref)
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
