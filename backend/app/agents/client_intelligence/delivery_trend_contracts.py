"""Typed Delivery Trend Intelligence contracts (Phase 2 foundation).

Actual/plan/forecast alignment with explicit missing-value states. No governed
plan source exists (no units_plan). No production deviation/materiality policy.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
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
from app.agents.client_intelligence.reporting_period import resolve_reporting_period

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_RULES_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

LIMITATION_PLAN_SERIES_UNAVAILABLE = "PLAN_SERIES_UNAVAILABLE"
LIMITATION_FORECAST_VALUE_MISSING = "FORECAST_VALUE_MISSING"
LIMITATION_THROUGHPUT_HISTORY_UNAVAILABLE = "THROUGHPUT_HISTORY_UNAVAILABLE"
LIMITATION_THROUGHPUT_DATE_GAPS = "THROUGHPUT_DATE_GAPS"
LIMITATION_DEVIATION_POLICY_UNAVAILABLE = "DEVIATION_POLICY_UNAVAILABLE"
LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE = (
    "DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE"
)
LIMITATION_ACTUAL_SERIES_NOT_CLIENT_VISIBLE = "ACTUAL_SERIES_NOT_CLIENT_VISIBLE"
LIMITATION_FORECAST_SERIES_NOT_CLIENT_VISIBLE = "FORECAST_SERIES_NOT_CLIENT_VISIBLE"

_FORBIDDEN_PLAN_CLAIMS = frozenset({"units_plan"})
_FORBIDDEN_TREND_OUTPUT_CLAIMS = frozenset({"rolling_7day_units", "units_plan"})
_ALLOWED_TREND_OUTPUT_CLAIMS = frozenset(
    {"snapshot_date", "units_completed", "units_forecast"}
)


class DeliveryTrendAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    STALE = "stale"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class TrendReportingGrain(StrEnum):
    DAY = "day"


class TrendTimezone(StrEnum):
    UTC = "utc"


class TrendSeriesValueState(StrEnum):
    OBSERVED = "observed"
    MISSING_SOURCE = "missing_source"
    REDACTED = "redacted"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTING = "conflicting"


class DeviationMateriality(StrEnum):
    MATERIAL = "material"
    NOT_MATERIAL = "not_material"


class DeliveryTrendEvidencePeriod(StrEnum):
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
    ref: DeliveryTrendEvidenceRef,
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


def canonical_deviation_candidate_key(source_row_id: UUID, snapshot_date: date) -> str:
    return f"throughput.{source_row_id.hex}.{snapshot_date.strftime('%Y%m%d')}"


def require_rules_version(value: str) -> str:
    if not isinstance(value, str) or not _RULES_VERSION_RE.match(value):
        raise ValueError("rules_version must be a stable non-empty identifier")
    return value


def snapshot_utc_midnight(snapshot_date: date) -> datetime:
    return datetime.combine(snapshot_date, time.min, tzinfo=UTC)


def is_canonical_utc_midnight(value: datetime | None, snapshot_date: date) -> bool:
    if value is None or value.tzinfo is None:
        return False
    if value.utcoffset() != timedelta(0):
        return False
    if value.tzname() != "UTC":
        return False
    return (
        value.year == snapshot_date.year
        and value.month == snapshot_date.month
        and value.day == snapshot_date.day
        and value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


def expected_point_claim_keys(
    *,
    actual_state: TrendSeriesValueState,
    forecast_state: TrendSeriesValueState,
) -> set[str]:
    claims = {"snapshot_date"}
    if actual_state == TrendSeriesValueState.OBSERVED:
        claims.add("units_completed")
    if forecast_state == TrendSeriesValueState.OBSERVED:
        claims.add("units_forecast")
    return claims


def _require_non_negative_int(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("units must be exact integers")
    if value < 0:
        raise ValueError("units must be non-negative")
    return value


class DeliveryTrendEvidenceRef(ClientIntelligenceModel):
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(min_length=1)
    period: DeliveryTrendEvidencePeriod
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
        if _FORBIDDEN_TREND_OUTPUT_CLAIMS.intersection(cleaned):
            raise ValueError("rolling_7day_units and units_plan are not allowed in trend output")
        if not set(cleaned).issubset(_ALLOWED_TREND_OUTPUT_CLAIMS):
            raise ValueError("trend output claim_keys contain unsupported claims")
        return sorted(cleaned)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)


class DeliveryTrendPoint(ClientIntelligenceModel):
    snapshot_date: date
    source_row_id: UUID
    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    actual_units: int | None = None
    actual_state: TrendSeriesValueState
    plan_units: int | None = None
    plan_state: TrendSeriesValueState
    forecast_units: int | None = None
    forecast_state: TrendSeriesValueState
    delta_actual_forecast: int | None = None
    delta_actual_plan: int | None = None
    data_quality: DataQualityState | None = None
    visibility: EvidenceVisibility
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[DeliveryTrendEvidenceRef] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("source_table")
    @classmethod
    def _validate_source_table(cls, value: str) -> str:
        return _require_source_table(value)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("actual_units", "plan_units", "forecast_units")
    @classmethod
    def _validate_units(cls, value: int | None) -> int | None:
        return _require_non_negative_int(value)

    @field_validator("delta_actual_forecast", "delta_actual_plan")
    @classmethod
    def _validate_delta(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("delta must be an exact integer")
        return value

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _point_invariants(self) -> DeliveryTrendPoint:
        if self.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
            raise ValueError("source_agent must be delivery_performance")
        if self.source_table != "throughput_snapshots":
            raise ValueError("source_table must be throughput_snapshots")
        if self.data_quality in {
            DataQualityState.UNAVAILABLE,
            DataQualityState.CONFLICTING,
        }:
            raise ValueError("published points cannot use UNAVAILABLE or CONFLICTING quality")
        if self.plan_units is not None:
            raise ValueError("plan_units must remain None in TASK 13")
        if self.plan_state != TrendSeriesValueState.MISSING_SOURCE:
            raise ValueError("plan_state must be MISSING_SOURCE")
        if self.delta_actual_plan is not None:
            raise ValueError("actual-vs-plan delta is not supported without plan source")
        if LIMITATION_PLAN_SERIES_UNAVAILABLE not in self.limitations:
            raise ValueError("point must include PLAN_SERIES_UNAVAILABLE")
        if self.actual_state == TrendSeriesValueState.OBSERVED:
            if self.actual_units is None:
                raise ValueError("OBSERVED actual requires units")
        elif self.actual_units is not None:
            raise ValueError("non-OBSERVED actual must not carry units")
        if self.forecast_state == TrendSeriesValueState.OBSERVED:
            if self.forecast_units is None:
                raise ValueError("OBSERVED forecast requires units")
            if LIMITATION_FORECAST_VALUE_MISSING in self.limitations:
                raise ValueError("observed forecast cannot include FORECAST_VALUE_MISSING")
        elif self.forecast_units is not None:
            raise ValueError("non-OBSERVED forecast must not carry units")
        if (
            self.forecast_state == TrendSeriesValueState.MISSING_SOURCE
            and LIMITATION_FORECAST_VALUE_MISSING not in self.limitations
        ):
            raise ValueError("missing forecast requires FORECAST_VALUE_MISSING")
        if self.delta_actual_forecast is not None:
            if self.actual_units is None or self.forecast_units is None:
                raise ValueError("delta requires both actual and forecast")
            if self.delta_actual_forecast != self.actual_units - self.forecast_units:
                raise ValueError("delta_actual_forecast must equal exact subtraction")
        elif self.actual_units is not None and self.forecast_units is not None:
            raise ValueError("both operands present requires delta_actual_forecast")

        expected_claims = expected_point_claim_keys(
            actual_state=self.actual_state,
            forecast_state=self.forecast_state,
        )
        claims: set[str] = set()
        for ref in self.evidence:
            if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
                raise ValueError("evidence source_agent must be delivery_performance")
            if ref.source_table != "throughput_snapshots":
                raise ValueError("evidence source_table must be throughput_snapshots")
            if ref.source_row_id != self.source_row_id:
                raise ValueError("evidence source_row_id mismatch")
            if ref.visibility != self.visibility:
                raise ValueError("evidence visibility mismatch")
            if ref.source_fingerprint != self.source_fingerprint:
                raise ValueError("evidence fingerprint mismatch")
            if ref.period != DeliveryTrendEvidencePeriod.CURRENT:
                raise ValueError("evidence must use CURRENT period")
            if not is_canonical_utc_midnight(ref.observed_at, self.snapshot_date):
                raise ValueError(
                    "evidence observed_at must equal snapshot_date at 00:00:00 UTC"
                )
            if _FORBIDDEN_TREND_OUTPUT_CLAIMS.intersection(ref.claim_keys):
                raise ValueError("rolling_7day_units and units_plan are not allowed")
            claims.update(ref.claim_keys)

        if claims != expected_claims:
            raise ValueError("point evidence claim union must exactly equal governed claims")
        return self


class DeliveryTrendDeviationCandidate(ClientIntelligenceModel):
    candidate_key: Annotated[str, Field(min_length=1)]
    source_row_id: UUID
    snapshot_date: date
    actual_units: int
    forecast_units: int
    delta_actual_forecast: int
    data_quality: DataQualityState
    visibility: EvidenceVisibility
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[DeliveryTrendEvidenceRef] = Field(min_length=1)

    @field_validator("candidate_key")
    @classmethod
    def _validate_candidate_key(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("actual_units", "forecast_units")
    @classmethod
    def _validate_units(cls, value: int) -> int:
        result = _require_non_negative_int(value)
        assert result is not None
        return result

    @field_validator("delta_actual_forecast")
    @classmethod
    def _validate_delta(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("delta must be an exact integer")
        return value

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @model_validator(mode="after")
    def _candidate_invariants(self) -> DeliveryTrendDeviationCandidate:
        if self.data_quality != DataQualityState.COMPLETE:
            raise ValueError("deviation candidates require COMPLETE source quality")
        expected = canonical_deviation_candidate_key(self.source_row_id, self.snapshot_date)
        if self.candidate_key != expected:
            raise ValueError("candidate_key must equal canonical row/date identity")
        if self.delta_actual_forecast != self.actual_units - self.forecast_units:
            raise ValueError("delta must equal exact subtraction")
        expected_claims = {"snapshot_date", "units_completed", "units_forecast"}
        claims: set[str] = set()
        for ref in self.evidence:
            if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
                raise ValueError("candidate evidence source_agent mismatch")
            if ref.source_table != "throughput_snapshots":
                raise ValueError("candidate evidence source_table mismatch")
            if ref.source_row_id != self.source_row_id:
                raise ValueError("candidate evidence row mismatch")
            if ref.visibility != self.visibility:
                raise ValueError("candidate evidence visibility mismatch")
            if ref.source_fingerprint != self.source_fingerprint:
                raise ValueError("candidate evidence fingerprint mismatch")
            if ref.period != DeliveryTrendEvidencePeriod.CURRENT:
                raise ValueError("candidate evidence must use CURRENT period")
            if not is_canonical_utc_midnight(ref.observed_at, self.snapshot_date):
                raise ValueError(
                    "candidate evidence observed_at must be snapshot_date UTC midnight"
                )
            if _FORBIDDEN_TREND_OUTPUT_CLAIMS.intersection(ref.claim_keys):
                raise ValueError("candidate evidence cannot include rolling or plan claims")
            claims.update(ref.claim_keys)
        if claims != expected_claims:
            raise ValueError("candidate evidence claims must equal governed actual/forecast set")
        return self


class DeliveryTrendDeviationCandidateContext(ClientIntelligenceModel):
    candidates: list[DeliveryTrendDeviationCandidate] = Field(default_factory=list)
    context_limitations: list[str] = Field(default_factory=list)

    @field_validator("context_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _context_invariants(self) -> DeliveryTrendDeviationCandidateContext:
        keys = [item.candidate_key for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate keys must be unique")
        identities = [(item.source_row_id, item.snapshot_date) for item in self.candidates]
        if len(identities) != len(set(identities)):
            raise ValueError("source row/date identity must not be duplicated")
        return self


class DeliveryTrendDeviationSelection(ClientIntelligenceModel):
    candidate_key: Annotated[str, Field(min_length=1)]
    materiality: DeviationMateriality

    @field_validator("candidate_key")
    @classmethod
    def _validate_candidate_key(cls, value: str) -> str:
        return _require_key(value)


class DeliveryTrendDeviationPolicyDecision(ClientIntelligenceModel):
    selections: list[DeliveryTrendDeviationSelection] = Field(default_factory=list)
    policy_limitations: list[str] = Field(default_factory=list)

    @field_validator("policy_limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _unique_selections(self) -> DeliveryTrendDeviationPolicyDecision:
        keys = [item.candidate_key for item in self.selections]
        if len(keys) != len(set(keys)):
            raise ValueError("policy selections must use unique candidate keys")
        return self


class DeliveryTrendDeviationResult(ClientIntelligenceModel):
    candidate_key: Annotated[str, Field(min_length=1)]
    source_row_id: UUID
    snapshot_date: date
    actual_units: int
    forecast_units: int
    delta_actual_forecast: int
    materiality: DeviationMateriality
    data_quality: DataQualityState
    visibility: EvidenceVisibility
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[DeliveryTrendEvidenceRef] = Field(min_length=1)

    @field_validator("candidate_key")
    @classmethod
    def _validate_candidate_key(cls, value: str) -> str:
        return _require_key(value)

    @field_validator("actual_units", "forecast_units")
    @classmethod
    def _validate_units(cls, value: int) -> int:
        result = _require_non_negative_int(value)
        assert result is not None
        return result

    @field_validator("delta_actual_forecast")
    @classmethod
    def _validate_delta(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("delta must be an exact integer")
        return value

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @model_validator(mode="after")
    def _result_invariants(self) -> DeliveryTrendDeviationResult:
        if self.data_quality != DataQualityState.COMPLETE:
            raise ValueError("published deviation results require COMPLETE quality")
        if self.delta_actual_forecast != self.actual_units - self.forecast_units:
            raise ValueError("delta must equal exact subtraction")
        expected = canonical_deviation_candidate_key(self.source_row_id, self.snapshot_date)
        if self.candidate_key != expected:
            raise ValueError("candidate_key must equal canonical row/date identity")
        expected_claims = {"snapshot_date", "units_completed", "units_forecast"}
        claims: set[str] = set()
        for ref in self.evidence:
            if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
                raise ValueError("deviation evidence source_agent mismatch")
            if ref.source_table != "throughput_snapshots":
                raise ValueError("deviation evidence source_table mismatch")
            if ref.source_row_id != self.source_row_id:
                raise ValueError("deviation evidence row mismatch")
            if ref.visibility != self.visibility:
                raise ValueError("deviation evidence visibility mismatch")
            if ref.source_fingerprint != self.source_fingerprint:
                raise ValueError("deviation evidence fingerprint mismatch")
            if ref.period != DeliveryTrendEvidencePeriod.CURRENT:
                raise ValueError("deviation evidence must use CURRENT period")
            if not is_canonical_utc_midnight(ref.observed_at, self.snapshot_date):
                raise ValueError(
                    "deviation evidence observed_at must be snapshot_date UTC midnight"
                )
            if _FORBIDDEN_TREND_OUTPUT_CLAIMS.intersection(ref.claim_keys):
                raise ValueError("deviation evidence cannot include rolling or plan claims")
            claims.update(ref.claim_keys)
        if claims != expected_claims:
            raise ValueError("deviation evidence claims must equal governed actual/forecast set")
        return self


class DeliveryTrendAssessment(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    as_of: date
    covered_start_date: date
    covered_end_date: date
    grain: TrendReportingGrain
    timezone: TrendTimezone
    visibility_mode: EvidenceVisibility
    availability: DeliveryTrendAvailability
    trend_points: list[DeliveryTrendPoint] = Field(default_factory=list)
    deviations: list[DeliveryTrendDeviationResult] = Field(default_factory=list)
    evidence: list[DeliveryTrendEvidenceRef] = Field(default_factory=list)
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
    def _assessment_invariants(self) -> DeliveryTrendAssessment:
        if LIMITATION_PLAN_SERIES_UNAVAILABLE not in self.limitations:
            raise ValueError("assessment must include PLAN_SERIES_UNAVAILABLE")

        if self.availability == DeliveryTrendAvailability.AVAILABLE:
            raise ValueError("TASK 13 cannot produce AVAILABLE without governed plan")

        if (
            self.availability == DeliveryTrendAvailability.CONFLICTING
            and (self.trend_points or self.deviations or self.evidence)
        ):
            raise ValueError("CONFLICTING assessments cannot carry trend output")

        if (
            self.availability == DeliveryTrendAvailability.UNAVAILABLE
            and (self.trend_points or self.deviations or self.evidence)
        ):
            raise ValueError("UNAVAILABLE assessments cannot carry trend output")

        if self.grain != TrendReportingGrain.DAY:
            raise ValueError("grain must be DAY")
        if self.timezone != TrendTimezone.UTC:
            raise ValueError("timezone must be UTC")

        expected_window = resolve_reporting_period(self.as_of)
        if self.covered_end_date != self.as_of:
            raise ValueError("covered_end_date must equal as_of")
        if self.covered_start_date != expected_window.previous_start_date:
            raise ValueError(
                "covered_start_date must equal resolve_reporting_period(as_of).previous_start_date"
            )
        if self.covered_start_date > self.covered_end_date:
            raise ValueError("covered_start_date must be <= covered_end_date")

        policy_unavailable = (
            LIMITATION_DEVIATION_POLICY_UNAVAILABLE in self.limitations
        )
        policy_not_evaluated = (
            LIMITATION_DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE in self.limitations
        )

        if self.rules_version is not None:
            if policy_unavailable:
                raise ValueError(
                    "evaluated-policy assessments cannot include DEVIATION_POLICY_UNAVAILABLE"
                )
            if policy_not_evaluated:
                raise ValueError(
                    "evaluated-policy assessments cannot include "
                    "DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE"
                )
        elif self.trend_points:
            if policy_unavailable and policy_not_evaluated:
                raise ValueError(
                    "missing-policy and unreliable-source codes cannot both be present"
                )
            if not policy_unavailable and not policy_not_evaluated:
                raise ValueError(
                    "rules_version-less assessments with trend points require exactly one "
                    "policy provenance limitation"
                )
            if self.deviations:
                raise ValueError("rules_version None forbids deviations")
        elif policy_unavailable and policy_not_evaluated:
            raise ValueError(
                "missing-policy and unreliable-source codes cannot both be present"
            )

        if self.deviations:
            if self.rules_version is None:
                raise ValueError("published deviations require a valid rules_version")
            if policy_unavailable or policy_not_evaluated:
                raise ValueError(
                    "published deviations forbid policy-unavailable/not-evaluated codes"
                )

        point_identities = [
            (point.source_row_id, point.snapshot_date) for point in self.trend_points
        ]
        if len(point_identities) != len(set(point_identities)):
            raise ValueError("trend points must have unique source row/date identities")
        point_dates = [point.snapshot_date for point in self.trend_points]
        if len(point_dates) != len(set(point_dates)):
            raise ValueError("trend points must have unique snapshot dates")

        canonical_points = sorted(
            self.trend_points,
            key=lambda item: (item.snapshot_date, str(item.source_row_id)),
        )
        if list(self.trend_points) != canonical_points:
            raise ValueError("trend_points must be canonically ordered")

        deviation_keys = [item.candidate_key for item in self.deviations]
        if len(deviation_keys) != len(set(deviation_keys)):
            raise ValueError("deviation candidate keys must be unique")
        deviation_identities = [
            (item.source_row_id, item.snapshot_date) for item in self.deviations
        ]
        if len(deviation_identities) != len(set(deviation_identities)):
            raise ValueError("deviation row/date identities must be unique")
        canonical_devs = sorted(
            self.deviations,
            key=lambda item: (
                item.snapshot_date,
                str(item.source_row_id),
                item.candidate_key,
            ),
        )
        if list(self.deviations) != canonical_devs:
            raise ValueError("deviations must be canonically ordered")

        point_qualities = {point.data_quality for point in self.trend_points}
        if len(point_qualities) > 1:
            raise ValueError("all trend points must share the same pack-owned quality")
        if (
            policy_not_evaluated
            and self.trend_points
            and DataQualityState.COMPLETE in point_qualities
        ):
            raise ValueError(
                "DEVIATION_NOT_EVALUATED_UNRELIABLE_SOURCE is invalid with COMPLETE points"
            )
        if self.availability == DeliveryTrendAvailability.STALE and any(
            point.data_quality != DataQualityState.STALE for point in self.trend_points
        ):
            raise ValueError("STALE assessments may contain only STALE points")
        if self.availability == DeliveryTrendAvailability.PARTIAL:
            for point in self.trend_points:
                if point.data_quality not in {
                    DataQualityState.COMPLETE,
                    DataQualityState.PARTIAL,
                    None,
                }:
                    raise ValueError(
                        "PARTIAL assessments may contain only COMPLETE, PARTIAL, or None points"
                    )

        for point in self.trend_points:
            if (
                point.snapshot_date < self.covered_start_date
                or point.snapshot_date > self.covered_end_date
            ):
                raise ValueError("point date must be within the assessment reporting window")
        for deviation in self.deviations:
            if (
                deviation.snapshot_date < self.covered_start_date
                or deviation.snapshot_date > self.covered_end_date
            ):
                raise ValueError(
                    "deviation date must be within the assessment reporting window"
                )

        points_by_identity = {
            (point.source_row_id, point.snapshot_date): point for point in self.trend_points
        }
        for deviation in self.deviations:
            point = points_by_identity.get((deviation.source_row_id, deviation.snapshot_date))
            if point is None:
                raise ValueError("deviation must match exactly one trend point")
            if point.actual_state != TrendSeriesValueState.OBSERVED:
                raise ValueError("deviation requires OBSERVED actual on matching point")
            if point.forecast_state != TrendSeriesValueState.OBSERVED:
                raise ValueError("deviation requires OBSERVED forecast on matching point")
            if point.data_quality != DataQualityState.COMPLETE:
                raise ValueError("deviation requires COMPLETE matching point quality")
            if point.actual_units != deviation.actual_units:
                raise ValueError("deviation actual_units must match the trend point")
            if point.forecast_units != deviation.forecast_units:
                raise ValueError("deviation forecast_units must match the trend point")
            if point.delta_actual_forecast != deviation.delta_actual_forecast:
                raise ValueError("deviation delta must match the trend point")
            if point.visibility != deviation.visibility:
                raise ValueError("deviation visibility must match the trend point")
            if point.source_fingerprint != deviation.source_fingerprint:
                raise ValueError("deviation fingerprint must match the trend point")
            point_claim_union: set[str] = set()
            for ref in point.evidence:
                point_claim_union.update(ref.claim_keys)
            deviation_claim_union: set[str] = set()
            for ref in deviation.evidence:
                deviation_claim_union.update(ref.claim_keys)
            if deviation_claim_union != point_claim_union:
                raise ValueError("deviation evidence claim union must match the point")
            point_lineage = {_evidence_lineage_key(ref) for ref in point.evidence}
            deviation_lineage = {_evidence_lineage_key(ref) for ref in deviation.evidence}
            if deviation_lineage != point_lineage:
                raise ValueError("deviation evidence lineage must match the point")

        top_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        for ref in self.evidence:
            if ref.period != DeliveryTrendEvidencePeriod.CURRENT:
                raise ValueError("assessment evidence must use CURRENT period")
            if ref.source_fingerprint != self.source_fingerprint:
                raise ValueError("evidence fingerprint must match assessment")
            if _FORBIDDEN_TREND_OUTPUT_CLAIMS.intersection(ref.claim_keys):
                raise ValueError("top-level trend evidence cannot include rolling or plan claims")
            if not set(ref.claim_keys).issubset(_ALLOWED_TREND_OUTPUT_CLAIMS):
                raise ValueError("top-level trend evidence contains unsupported claims")
            key = _evidence_lineage_key(ref)
            top_claims.setdefault(key, set()).update(ref.claim_keys)

        item_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        for point in self.trend_points:
            if point.source_fingerprint != self.source_fingerprint:
                raise ValueError("point fingerprint must match assessment")
            for ref in point.evidence:
                if not is_canonical_utc_midnight(ref.observed_at, point.snapshot_date):
                    raise ValueError("point evidence timestamp must be UTC midnight")
                key = _evidence_lineage_key(ref)
                claimed = top_claims.get(key)
                if claimed is None:
                    raise ValueError("point evidence must exist top-level")
                if not set(ref.claim_keys).issubset(claimed):
                    raise ValueError("point claims must be included top-level")
                item_claims.setdefault(key, set()).update(ref.claim_keys)
        for deviation in self.deviations:
            if deviation.source_fingerprint != self.source_fingerprint:
                raise ValueError("deviation fingerprint must match assessment")
            for ref in deviation.evidence:
                if not is_canonical_utc_midnight(ref.observed_at, deviation.snapshot_date):
                    raise ValueError("deviation evidence timestamp must be UTC midnight")
                key = _evidence_lineage_key(ref)
                claimed = top_claims.get(key)
                if claimed is None:
                    raise ValueError("deviation evidence must exist top-level")
                if not set(ref.claim_keys).issubset(claimed):
                    raise ValueError("deviation claims must be included top-level")
                item_claims.setdefault(key, set()).update(ref.claim_keys)

        if self.availability in {
            DeliveryTrendAvailability.PARTIAL,
            DeliveryTrendAvailability.STALE,
        }:
            if set(top_claims) != set(item_claims):
                raise ValueError("top-level evidence must equal point/deviation union")
            for key, claims in item_claims.items():
                if top_claims[key] != claims:
                    raise ValueError("top-level claim union must equal item union")

        if (
            self.visibility_mode == EvidenceVisibility.CLIENT_SAFE
            and (self.trend_points or self.deviations)
        ):
            raise ValueError("CLIENT_SAFE Delivery Trend actual/forecast is unavailable")

        return self
