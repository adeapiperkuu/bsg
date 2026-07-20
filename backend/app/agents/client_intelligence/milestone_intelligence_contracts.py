"""Typed Milestone Intelligence contracts (Phase 2 foundation).

Consumes Delivery-owned milestone facts from a validated ClientEvidencePack.
No production policy, forecast dates, numeric progress, or milestone dependency
linkage is invented here.
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
    ReportingPeriod,
    SourceAgent,
)
from app.agents.client_intelligence.evidence_validation import source_agent_owns_table

_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SOURCE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE = "MILESTONE_PROGRESS_SOURCE_UNAVAILABLE"
LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE = "MILESTONE_DEPENDENCY_LINK_UNAVAILABLE"
LIMITATION_MILESTONE_SOURCE_UNAVAILABLE = "MILESTONE_SOURCE_UNAVAILABLE"
LIMITATION_SELECTED_PERIOD_EMPTY_POPULATION = "SELECTED_PERIOD_EMPTY_POPULATION"
LIMITATION_NEXT_MILESTONE_ID_UNAVAILABLE = "NEXT_MILESTONE_ID_UNAVAILABLE"
LIMITATION_NEXT_MILESTONE_ID_UNKNOWN = "NEXT_MILESTONE_ID_UNKNOWN"
LIMITATION_NEXT_MILESTONE_COMPLETED = "NEXT_MILESTONE_COMPLETED"
LIMITATION_MILESTONE_CONFIDENCE_UNAVAILABLE = "MILESTONE_CONFIDENCE_UNAVAILABLE"
LIMITATION_MILESTONE_CONFIDENCE_MILESTONE_MISMATCH = (
    "MILESTONE_CONFIDENCE_MILESTONE_MISMATCH"
)
LIMITATION_MILESTONE_CONFIDENCE_STALE = "MILESTONE_CONFIDENCE_STALE"
LIMITATION_MILESTONE_CONFIDENCE_PARTIAL = "MILESTONE_CONFIDENCE_PARTIAL"
LIMITATION_MILESTONE_CONFIDENCE_CONFLICTING = "MILESTONE_CONFIDENCE_CONFLICTING"
LIMITATION_NO_SUPPORTED_MILESTONE_BLOCKER = "NO_SUPPORTED_MILESTONE_BLOCKER"
LIMITATION_MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE = (
    "MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE"
)
LIMITATION_MILESTONE_STATUS_UNRECOGNIZED = "MILESTONE_STATUS_UNRECOGNIZED"

# Backward-compatible alias for earlier TASK 15 drafts.
LIMITATION_MILESTONE_FORECAST_DATE_SOURCE_UNAVAILABLE = (
    LIMITATION_MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE
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
_REQUIRED_CONFIDENCE_CLAIMS = frozenset(
    {"score_pct", "confidence_status", "forecast_completion_date"}
)
_REQUIRED_RISK_BLOCKER_CLAIMS = frozenset(
    {"risk_id", "risk_title", "risk_tier", "alert_type", "status"}
)
_FORBIDDEN_DETAIL_CLAIMS = frozenset({"risk_detail", "bottleneck_detail"})
_OPEN_RISK_STATUSES = frozenset({"open", "acknowledged"})
_AT_RISK_STATUSES = frozenset({"at_risk", "missed"})
_STATUS_BUCKETS = frozenset({"on_track", "at_risk", "missed", "completed", "pending"})
_COMPLETED_STATUS = "completed"
_NEXT_LIMITATIONS = frozenset(
    {
        LIMITATION_NEXT_MILESTONE_ID_UNAVAILABLE,
        LIMITATION_NEXT_MILESTONE_ID_UNKNOWN,
        LIMITATION_NEXT_MILESTONE_COMPLETED,
    }
)


class MilestoneIntelligenceAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTING = "conflicting"


class MilestoneAtRiskReasonCode(StrEnum):
    SOURCE_STATUS_AT_RISK = "SOURCE_STATUS_AT_RISK"
    SOURCE_STATUS_MISSED = "SOURCE_STATUS_MISSED"


class MilestoneConfidenceAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    PARTIAL = "partial"
    CONFLICTING = "conflicting"
    MISMATCH = "mismatch"


class MilestoneBlockerState(StrEnum):
    PRESENT = "present"
    NO_SUPPORTED_BLOCKER = "no_supported_blocker"


class MilestoneDependencyState(StrEnum):
    UNAVAILABLE = "unavailable"


class MilestoneEvidencePeriod(StrEnum):
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
    ref: MilestoneEvidenceRef,
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


def _evidence_sort_key(
    ref: MilestoneEvidenceRef,
) -> tuple[str, str, str, str]:
    return (
        ref.source_table,
        str(ref.source_row_id),
        ref.period.value,
        _observed_at_key(ref.observed_at),
    )


def reason_code_for_status(status: str) -> MilestoneAtRiskReasonCode | None:
    if status == "at_risk":
        return MilestoneAtRiskReasonCode.SOURCE_STATUS_AT_RISK
    if status == "missed":
        return MilestoneAtRiskReasonCode.SOURCE_STATUS_MISSED
    return None


def planned_date_in_reporting_period(
    planned_date: date, reporting_period: ReportingPeriod
) -> bool:
    return (
        reporting_period.start_date <= planned_date <= reporting_period.as_of
    )


class MilestoneEvidenceRef(ClientIntelligenceModel):
    """Exact pack evidence identity plus claim keys and lineage."""

    source_agent: SourceAgent
    source_table: str = Field(min_length=1)
    source_row_id: UUID
    visibility: EvidenceVisibility
    claim_keys: list[str] = Field(min_length=1)
    period: MilestoneEvidencePeriod
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


class MilestoneProgressView(ClientIntelligenceModel):
    """Source lifecycle status only — numeric progress is unavailable."""

    progress_state: str
    progress_pct: None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _progress_invariants(self) -> MilestoneProgressView:
        if self.progress_pct is not None:
            raise ValueError("numeric milestone progress is unavailable in TASK 15")
        if LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE not in self.limitations:
            raise ValueError(
                "progress view must include MILESTONE_PROGRESS_SOURCE_UNAVAILABLE"
            )
        return self


class MilestoneConfidenceView(ClientIntelligenceModel):
    availability: MilestoneConfidenceAvailability
    confidence_id: UUID | None = None
    milestone_id: UUID | None = None
    score_pct: Decimal | None = None
    confidence_status: str | None = None
    forecast_completion_date: date | None = None
    data_quality: DataQualityState | None = None
    evidence: list[MilestoneEvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _confidence_invariants(self) -> MilestoneConfidenceView:
        if self.availability == MilestoneConfidenceAvailability.AVAILABLE:
            if self.confidence_id is None or self.milestone_id is None:
                raise ValueError("available confidence requires confidence and milestone IDs")
            if self.score_pct is None or not self.confidence_status:
                raise ValueError("available confidence requires score and status")
            if self.data_quality != DataQualityState.COMPLETE:
                raise ValueError("available confidence requires COMPLETE data quality")
            if len(self.evidence) != 1:
                raise ValueError("available confidence requires exactly one evidence ref")
            ref = self.evidence[0]
            if ref.source_table != "delivery_confidence_scores":
                raise ValueError("confidence evidence must reference confidence scores")
            if ref.source_row_id != self.confidence_id:
                raise ValueError("confidence evidence source_row_id must equal confidence_id")
            if not _REQUIRED_CONFIDENCE_CLAIMS.issubset(set(ref.claim_keys)):
                raise ValueError("confidence evidence missing required claim keys")
        elif self.availability == MilestoneConfidenceAvailability.MISMATCH:
            if self.confidence_id is not None or self.milestone_id is not None:
                raise ValueError("mismatch confidence cannot carry source identity")
            if self.score_pct is not None or self.confidence_status is not None:
                raise ValueError("mismatch confidence cannot carry score/status")
            if self.forecast_completion_date is not None or self.evidence:
                raise ValueError("mismatch confidence cannot carry forecast or evidence")
            if LIMITATION_MILESTONE_CONFIDENCE_MILESTONE_MISMATCH not in self.limitations:
                raise ValueError(
                    "mismatch confidence requires MILESTONE_CONFIDENCE_MILESTONE_MISMATCH"
                )
        else:
            if self.confidence_id is not None or self.milestone_id is not None:
                raise ValueError("unavailable confidence cannot carry source identity")
            if self.score_pct is not None or self.confidence_status is not None:
                raise ValueError("unavailable confidence cannot carry score/status")
            if self.forecast_completion_date is not None:
                raise ValueError("unavailable confidence cannot carry forecast")
            if self.evidence:
                raise ValueError("unavailable confidence cannot carry evidence")
            if not self.limitations:
                raise ValueError("unavailable confidence requires limitations")
        return self


class MilestoneBlockerItem(ClientIntelligenceModel):
    risk_id: UUID
    milestone_id: UUID
    alert_type: str
    risk_tier: str
    status: str
    evidence: list[MilestoneEvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def _blocker_item_invariants(self) -> MilestoneBlockerItem:
        if self.status not in _OPEN_RISK_STATUSES:
            raise ValueError("blocker requires open/acknowledged status")
        if not self.alert_type or not self.risk_tier:
            raise ValueError("blocker requires alert_type and risk_tier")
        if len(self.evidence) != 1:
            raise ValueError("blocker requires exactly one evidence ref")
        ref = self.evidence[0]
        if ref.source_table != "risk_alerts":
            raise ValueError("blocker evidence must reference risk_alerts")
        if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
            raise ValueError("blocker evidence source_agent must be delivery_performance")
        if ref.source_row_id != self.risk_id:
            raise ValueError("blocker evidence source_row_id must equal risk_id")
        if not _REQUIRED_RISK_BLOCKER_CLAIMS.issubset(set(ref.claim_keys)):
            raise ValueError("blocker evidence missing required claim keys")
        return self


class MilestoneBlockerCollection(ClientIntelligenceModel):
    state: MilestoneBlockerState
    blockers: list[MilestoneBlockerItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _collection_invariants(self) -> MilestoneBlockerCollection:
        risk_ids = [item.risk_id for item in self.blockers]
        if len(risk_ids) != len(set(risk_ids)):
            raise ValueError("blocker risk IDs must be unique")
        ordered = sorted(
            self.blockers,
            key=lambda item: (
                item.evidence[0].observed_at.isoformat()
                if item.evidence and item.evidence[0].observed_at is not None
                else "",
                str(item.risk_id),
            ),
        )
        if [item.risk_id for item in self.blockers] != [item.risk_id for item in ordered]:
            raise ValueError("blockers must be canonically ordered")

        if self.state == MilestoneBlockerState.PRESENT:
            if not self.blockers:
                raise ValueError("PRESENT blocker collection requires blockers")
        else:
            if self.blockers:
                raise ValueError("NO_SUPPORTED_BLOCKER cannot carry blockers")
            if LIMITATION_NO_SUPPORTED_MILESTONE_BLOCKER not in self.limitations:
                raise ValueError(
                    "NO_SUPPORTED_BLOCKER must include NO_SUPPORTED_MILESTONE_BLOCKER"
                )
        return self


class MilestoneDependencyView(ClientIntelligenceModel):
    state: MilestoneDependencyState = MilestoneDependencyState.UNAVAILABLE
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, value: list[str]) -> list[str]:
        return sorted({_require_reason_code(item) for item in value})

    @model_validator(mode="after")
    def _dependency_invariants(self) -> MilestoneDependencyView:
        if self.state != MilestoneDependencyState.UNAVAILABLE:
            raise ValueError("milestone dependency linkage is unavailable in TASK 15")
        if LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE not in self.limitations:
            raise ValueError(
                "dependency view must include MILESTONE_DEPENDENCY_LINK_UNAVAILABLE"
            )
        return self


class MilestonePeriodCounts(ClientIntelligenceModel):
    total_count: int = Field(ge=0)
    on_track_count: int = Field(ge=0)
    at_risk_count: int = Field(ge=0)
    missed_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    unclassified_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _count_invariants(self) -> MilestonePeriodCounts:
        bucket_sum = (
            self.on_track_count
            + self.at_risk_count
            + self.missed_count
            + self.completed_count
            + self.pending_count
            + self.unclassified_count
        )
        if bucket_sum != self.total_count:
            raise ValueError(
                "total_count must equal the sum of all status bucket counts"
            )
        return self


def _validate_milestone_evidence(
    *,
    milestone_id: UUID,
    source_fingerprint: str,
    actual_date: date | None,
    evidence: list[MilestoneEvidenceRef],
) -> None:
    milestone_refs = [ref for ref in evidence if ref.source_table == "milestones"]
    if len(milestone_refs) != 1:
        raise ValueError("milestone items require exactly one milestones evidence ref")
    ref = milestone_refs[0]
    if ref.source_agent != SourceAgent.DELIVERY_PERFORMANCE:
        raise ValueError("milestone evidence source_agent must be delivery_performance")
    if not source_agent_owns_table(ref.source_agent, ref.source_table):
        raise ValueError("milestone evidence source ownership mismatch")
    if ref.source_row_id != milestone_id:
        raise ValueError("milestone evidence source_row_id must equal milestone_id")
    if ref.source_fingerprint != source_fingerprint:
        raise ValueError("milestone evidence fingerprint must match item fingerprint")
    claims = set(ref.claim_keys)
    if not _REQUIRED_MILESTONE_CLAIMS.issubset(claims):
        raise ValueError("milestone evidence missing required claim keys")
    if not claims.issubset(_ALLOWED_MILESTONE_CLAIMS):
        raise ValueError("milestone evidence contains unsupported claim keys")
    if actual_date is None and "actual_date" in claims:
        raise ValueError("actual_date claim requires actual_date value")
    if actual_date is not None and "actual_date" not in claims:
        raise ValueError("actual_date value requires actual_date claim")


def _validate_nested_views_for_milestone(
    *,
    milestone_id: UUID,
    source_fingerprint: str,
    progress: MilestoneProgressView,
    status: str,
    confidence: MilestoneConfidenceView,
    blockers: MilestoneBlockerCollection,
    revised_date: date | None,
    expected_date: date | None,
    forecast_date: date | None,
) -> None:
    if progress.progress_state != status:
        raise ValueError("progress_state must equal milestone status")
    if revised_date is not None or expected_date is not None:
        raise ValueError("invented milestone dates are not allowed")
    if forecast_date is not None:
        raise ValueError("forecast dates cannot be published as milestone dates")
    if confidence.availability == MilestoneConfidenceAvailability.AVAILABLE:
        if confidence.milestone_id != milestone_id:
            raise ValueError("confidence milestone_id must equal parent milestone_id")
        for ref in confidence.evidence:
            if ref.source_fingerprint != source_fingerprint:
                raise ValueError("confidence evidence fingerprint must match item")
    for blocker in blockers.blockers:
        if blocker.milestone_id != milestone_id:
            raise ValueError("blocker milestone_id must equal parent milestone_id")
        for ref in blocker.evidence:
            if ref.source_fingerprint != source_fingerprint:
                raise ValueError("blocker evidence fingerprint must match item")


class MilestonePeriodItem(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    reporting_period: ReportingPeriod
    milestone_id: UUID
    name: str
    status: str
    planned_date: date
    actual_date: date | None = None
    revised_date: None = None
    expected_date: None = None
    forecast_date: None = None
    progress: MilestoneProgressView
    confidence: MilestoneConfidenceView
    blockers: MilestoneBlockerCollection
    dependency: MilestoneDependencyView
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[MilestoneEvidenceRef] = Field(min_length=1)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @model_validator(mode="after")
    def _item_invariants(self) -> MilestonePeriodItem:
        if not planned_date_in_reporting_period(
            self.planned_date, self.reporting_period
        ):
            raise ValueError("planned_date must fall within reporting period")
        _validate_milestone_evidence(
            milestone_id=self.milestone_id,
            source_fingerprint=self.source_fingerprint,
            actual_date=self.actual_date,
            evidence=self.evidence,
        )
        _validate_nested_views_for_milestone(
            milestone_id=self.milestone_id,
            source_fingerprint=self.source_fingerprint,
            progress=self.progress,
            status=self.status,
            confidence=self.confidence,
            blockers=self.blockers,
            revised_date=self.revised_date,
            expected_date=self.expected_date,
            forecast_date=self.forecast_date,
        )
        return self


class AtRiskMilestoneItem(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    reporting_period: ReportingPeriod
    milestone_id: UUID
    name: str
    status: str
    planned_date: date
    actual_date: date | None = None
    reason_codes: list[MilestoneAtRiskReasonCode] = Field(min_length=1)
    progress: MilestoneProgressView
    confidence: MilestoneConfidenceView
    blockers: MilestoneBlockerCollection
    dependency: MilestoneDependencyView
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[MilestoneEvidenceRef] = Field(min_length=1)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("reason_codes")
    @classmethod
    def _canonical_reason_codes(
        cls, value: list[MilestoneAtRiskReasonCode]
    ) -> list[MilestoneAtRiskReasonCode]:
        ordered = sorted(set(value), key=lambda item: item.value)
        if not ordered:
            raise ValueError("reason_codes must be non-empty")
        return ordered

    @model_validator(mode="after")
    def _at_risk_invariants(self) -> AtRiskMilestoneItem:
        if self.status not in _AT_RISK_STATUSES:
            raise ValueError("at-risk items require explicit at_risk or missed status")
        expected = reason_code_for_status(self.status)
        if expected is None or self.reason_codes != [expected]:
            raise ValueError("reason_codes must match explicit source status exactly")
        _validate_milestone_evidence(
            milestone_id=self.milestone_id,
            source_fingerprint=self.source_fingerprint,
            actual_date=self.actual_date,
            evidence=self.evidence,
        )
        _validate_nested_views_for_milestone(
            milestone_id=self.milestone_id,
            source_fingerprint=self.source_fingerprint,
            progress=self.progress,
            status=self.status,
            confidence=self.confidence,
            blockers=self.blockers,
            revised_date=None,
            expected_date=None,
            forecast_date=None,
        )
        return self


class NextKeyMilestoneView(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    reporting_period: ReportingPeriod
    milestone_id: UUID
    name: str
    status: str
    planned_date: date
    actual_date: date | None = None
    revised_date: None = None
    expected_date: None = None
    forecast_date: None = None
    progress: MilestoneProgressView
    confidence: MilestoneConfidenceView
    blockers: MilestoneBlockerCollection
    dependency: MilestoneDependencyView
    source_fingerprint: str = Field(min_length=64, max_length=64)
    evidence: list[MilestoneEvidenceRef] = Field(min_length=1)

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @model_validator(mode="after")
    def _next_invariants(self) -> NextKeyMilestoneView:
        if self.status == _COMPLETED_STATUS:
            raise ValueError("completed milestones cannot be published as next")
        _validate_milestone_evidence(
            milestone_id=self.milestone_id,
            source_fingerprint=self.source_fingerprint,
            actual_date=self.actual_date,
            evidence=self.evidence,
        )
        _validate_nested_views_for_milestone(
            milestone_id=self.milestone_id,
            source_fingerprint=self.source_fingerprint,
            progress=self.progress,
            status=self.status,
            confidence=self.confidence,
            blockers=self.blockers,
            revised_date=self.revised_date,
            expected_date=self.expected_date,
            forecast_date=self.forecast_date,
        )
        return self


def _shared_milestone_fields_match(
    left: MilestonePeriodItem | AtRiskMilestoneItem | NextKeyMilestoneView,
    right: MilestonePeriodItem | AtRiskMilestoneItem | NextKeyMilestoneView,
) -> bool:
    return (
        left.org_id == right.org_id
        and left.project_id == right.project_id
        and left.reporting_period == right.reporting_period
        and left.milestone_id == right.milestone_id
        and left.name == right.name
        and left.status == right.status
        and left.planned_date == right.planned_date
        and left.actual_date == right.actual_date
        and left.progress == right.progress
        and left.confidence == right.confidence
        and left.blockers == right.blockers
        and left.dependency == right.dependency
        and left.source_fingerprint == right.source_fingerprint
        and left.evidence == right.evidence
    )


def _project_at_risk_from_selected(item: MilestonePeriodItem) -> AtRiskMilestoneItem:
    reason = reason_code_for_status(item.status)
    if reason is None:
        raise ValueError("selected item is not an at-risk projection candidate")
    return AtRiskMilestoneItem(
        org_id=item.org_id,
        project_id=item.project_id,
        reporting_period=item.reporting_period,
        milestone_id=item.milestone_id,
        name=item.name,
        status=item.status,
        planned_date=item.planned_date,
        actual_date=item.actual_date,
        reason_codes=[reason],
        progress=item.progress,
        confidence=item.confidence,
        blockers=item.blockers,
        dependency=item.dependency,
        source_fingerprint=item.source_fingerprint,
        evidence=item.evidence,
    )


class MilestoneIntelligenceAssessment(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    reporting_period: ReportingPeriod
    as_of: date
    visibility_mode: EvidenceVisibility
    availability: MilestoneIntelligenceAvailability
    data_quality: DataQualityState
    period_counts: MilestonePeriodCounts
    selected_period_items: list[MilestonePeriodItem] = Field(default_factory=list)
    at_risk_items: list[AtRiskMilestoneItem] = Field(default_factory=list)
    source_next_milestone_id: UUID | None = None
    next_key_milestone: NextKeyMilestoneView | None = None
    evidence: list[MilestoneEvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_limitations: list[str] = Field(default_factory=list)
    source_fingerprint: str = Field(min_length=64, max_length=64)
    generated_at: datetime

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_source_fingerprint(cls, value: str) -> str:
        return _require_sha256_hex(value)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
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
    def _assessment_invariants(self) -> MilestoneIntelligenceAssessment:
        if self.as_of != self.reporting_period.as_of:
            raise ValueError("as_of must equal reporting_period.as_of")

        foundation = {
            LIMITATION_MILESTONE_PROGRESS_SOURCE_UNAVAILABLE,
            LIMITATION_MILESTONE_DEPENDENCY_LINK_UNAVAILABLE,
            LIMITATION_MILESTONE_DATE_FORECAST_FIELDS_UNAVAILABLE,
        }
        if not foundation.issubset(set(self.limitations)):
            raise ValueError("assessment must include foundation limitations")

        if self.availability == MilestoneIntelligenceAvailability.AVAILABLE:
            raise ValueError(
                "TASK 15 caps availability at PARTIAL while progress and "
                "dependency linkage remain unavailable"
            )

        if self.period_counts.total_count != len(self.selected_period_items):
            raise ValueError("total_count must equal selected_period_items length")

        selected_ids = [item.milestone_id for item in self.selected_period_items]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("selected period items must have unique milestone IDs")
        ordered_selected = sorted(
            self.selected_period_items,
            key=lambda item: (item.planned_date, str(item.milestone_id)),
        )
        if [item.milestone_id for item in self.selected_period_items] != [
            item.milestone_id for item in ordered_selected
        ]:
            raise ValueError(
                "selected period items must be ordered by planned_date, milestone_id"
            )

        observed = {
            "on_track": 0,
            "at_risk": 0,
            "missed": 0,
            "completed": 0,
            "pending": 0,
            "unclassified": 0,
        }
        for item in self.selected_period_items:
            if item.org_id != self.org_id or item.project_id != self.project_id:
                raise ValueError("selected item identity must match assessment")
            if item.reporting_period != self.reporting_period:
                raise ValueError("selected item reporting_period must match assessment")
            if item.source_fingerprint != self.source_fingerprint:
                raise ValueError("selected item fingerprint must match assessment")
            for ref in item.evidence:
                if ref.visibility != self.visibility_mode:
                    raise ValueError(
                        "milestone evidence visibility must equal assessment visibility"
                    )
            if item.status in _STATUS_BUCKETS:
                observed[item.status] += 1
            else:
                observed["unclassified"] += 1

        if observed["on_track"] != self.period_counts.on_track_count:
            raise ValueError("on_track_count must reconcile with selected items")
        if observed["at_risk"] != self.period_counts.at_risk_count:
            raise ValueError("at_risk_count must reconcile with selected items")
        if observed["missed"] != self.period_counts.missed_count:
            raise ValueError("missed_count must reconcile with selected items")
        if observed["completed"] != self.period_counts.completed_count:
            raise ValueError("completed_count must reconcile with selected items")
        if observed["pending"] != self.period_counts.pending_count:
            raise ValueError("pending_count must reconcile with selected items")
        if observed["unclassified"] != self.period_counts.unclassified_count:
            raise ValueError("unclassified_count must reconcile with selected items")
        if (
            self.period_counts.unclassified_count > 0
            and LIMITATION_MILESTONE_STATUS_UNRECOGNIZED not in self.limitations
        ):
            raise ValueError(
                "unclassified statuses require MILESTONE_STATUS_UNRECOGNIZED"
            )
        if (
            self.period_counts.unclassified_count > 0
            and self.availability
            not in {
                MilestoneIntelligenceAvailability.PARTIAL,
                MilestoneIntelligenceAvailability.STALE,
                MilestoneIntelligenceAvailability.CONFLICTING,
                MilestoneIntelligenceAvailability.UNAVAILABLE,
            }
        ):
            raise ValueError("unclassified statuses cannot raise availability above PARTIAL")

        expected_at_risk = [
            _project_at_risk_from_selected(item)
            for item in self.selected_period_items
            if item.status in _AT_RISK_STATUSES
        ]
        if len(self.at_risk_items) != len(expected_at_risk):
            raise ValueError(
                "at_risk_items must be the exact projection of qualifying selected items"
            )
        for published, expected in zip(self.at_risk_items, expected_at_risk, strict=True):
            if published != expected:
                raise ValueError(
                    "at-risk item must exactly project its selected-period source item"
                )

        if (
            self.availability == MilestoneIntelligenceAvailability.CONFLICTING
            and (
                self.selected_period_items
                or self.at_risk_items
                or self.next_key_milestone
                or self.evidence
            )
        ):
            raise ValueError(
                "CONFLICTING assessments cannot carry milestone output or evidence"
            )

        if (
            self.availability == MilestoneIntelligenceAvailability.UNAVAILABLE
            and (
                self.selected_period_items
                or self.at_risk_items
                or self.next_key_milestone
                or self.evidence
            )
        ):
            raise ValueError(
                "UNAVAILABLE assessments cannot carry milestone output or evidence"
            )

        if self.next_key_milestone is None:
            if self.source_next_milestone_id is not None and not (
                _NEXT_LIMITATIONS & set(self.limitations)
            ):
                raise ValueError(
                    "missing next milestone with source ID requires a next-selection limitation"
                )
        else:
            nxt = self.next_key_milestone
            if self.source_next_milestone_id is None:
                raise ValueError(
                    "published next milestone requires source_next_milestone_id"
                )
            if nxt.milestone_id != self.source_next_milestone_id:
                raise ValueError(
                    "next milestone ID must equal source_next_milestone_id"
                )
            if nxt.org_id != self.org_id or nxt.project_id != self.project_id:
                raise ValueError("next milestone identity must match assessment")
            if nxt.reporting_period != self.reporting_period:
                raise ValueError("next milestone reporting_period must match assessment")
            if nxt.source_fingerprint != self.source_fingerprint:
                raise ValueError("next milestone fingerprint must match assessment")
            for ref in nxt.evidence:
                if ref.visibility != self.visibility_mode:
                    raise ValueError(
                        "next milestone evidence visibility must equal assessment"
                    )
            for selected in self.selected_period_items:
                if selected.milestone_id == nxt.milestone_id and not (
                    _shared_milestone_fields_match(selected, nxt)
                ):
                    raise ValueError(
                        "next milestone must exactly project overlapping selected item"
                    )
            if _NEXT_LIMITATIONS & set(self.limitations):
                raise ValueError(
                    "published next milestone cannot carry next-selection failure limitations"
                )

        next_codes = _NEXT_LIMITATIONS & set(self.limitations)
        if len(next_codes) > 1:
            raise ValueError("next-selection limitations must be mutually exclusive")

        if (
            self.period_counts.total_count == 0
            and self.availability
            in {
                MilestoneIntelligenceAvailability.PARTIAL,
                MilestoneIntelligenceAvailability.STALE,
            }
            and LIMITATION_SELECTED_PERIOD_EMPTY_POPULATION not in self.limitations
            and self.data_quality
            not in {DataQualityState.UNAVAILABLE, DataQualityState.CONFLICTING}
        ):
            raise ValueError(
                "empty selected-period population requires SELECTED_PERIOD_EMPTY_POPULATION"
            )

        top_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        lineage_seen: set[tuple[str, str, str, str, str, str, str]] = set()
        for ref in self.evidence:
            if ref.period != MilestoneEvidencePeriod.CURRENT:
                raise ValueError("assessment evidence must use CURRENT period")
            if ref.source_fingerprint != self.source_fingerprint:
                raise ValueError(
                    "evidence source_fingerprint must match assessment fingerprint"
                )
            if ref.visibility != self.visibility_mode:
                raise ValueError(
                    "evidence visibility must equal assessment visibility"
                )
            if _FORBIDDEN_DETAIL_CLAIMS.intersection(ref.claim_keys):
                raise ValueError("internal detail claims are not allowed top-level")
            key = _evidence_lineage_key(ref)
            if key in lineage_seen:
                raise ValueError("duplicate evidence lineage is not allowed")
            lineage_seen.add(key)
            top_claims[key] = set(ref.claim_keys)

        ordered_evidence = sorted(self.evidence, key=_evidence_sort_key)
        if [ _evidence_lineage_key(ref) for ref in self.evidence ] != [
            _evidence_lineage_key(ref) for ref in ordered_evidence
        ]:
            raise ValueError("top-level evidence must be canonically ordered")

        def _assert_item_evidence_subset(
            item_evidence: list[MilestoneEvidenceRef],
        ) -> dict[tuple[str, str, str, str, str, str, str], set[str]]:
            item_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
            for ref in item_evidence:
                if ref.source_fingerprint != self.source_fingerprint:
                    raise ValueError("item evidence fingerprint must match assessment")
                if ref.visibility != self.visibility_mode:
                    raise ValueError("item evidence visibility must match assessment")
                key = _evidence_lineage_key(ref)
                claimed = top_claims.get(key)
                if claimed is None:
                    raise ValueError("item evidence must exist in top-level evidence")
                if set(ref.claim_keys) != claimed:
                    raise ValueError(
                        "item claim keys must exactly equal top-level evidence claims"
                    )
                item_claims[key] = set(ref.claim_keys)
            return item_claims

        def _ingest_nested(
            union_claims: dict[tuple[str, str, str, str, str, str, str], set[str]],
            *,
            evidence: list[MilestoneEvidenceRef],
            confidence: MilestoneConfidenceView,
            blockers: MilestoneBlockerCollection,
        ) -> None:
            for key, claims in _assert_item_evidence_subset(evidence).items():
                union_claims.setdefault(key, set()).update(claims)
            for key, claims in _assert_item_evidence_subset(confidence.evidence).items():
                union_claims.setdefault(key, set()).update(claims)
            for blocker in blockers.blockers:
                for key, claims in _assert_item_evidence_subset(blocker.evidence).items():
                    union_claims.setdefault(key, set()).update(claims)

        union_claims: dict[tuple[str, str, str, str, str, str, str], set[str]] = {}
        for item in self.selected_period_items:
            _ingest_nested(
                union_claims,
                evidence=item.evidence,
                confidence=item.confidence,
                blockers=item.blockers,
            )
        for item in self.at_risk_items:
            _ingest_nested(
                union_claims,
                evidence=item.evidence,
                confidence=item.confidence,
                blockers=item.blockers,
            )
        if self.next_key_milestone is not None:
            _ingest_nested(
                union_claims,
                evidence=self.next_key_milestone.evidence,
                confidence=self.next_key_milestone.confidence,
                blockers=self.next_key_milestone.blockers,
            )

        if self.availability in {
            MilestoneIntelligenceAvailability.PARTIAL,
            MilestoneIntelligenceAvailability.STALE,
        }:
            if set(top_claims) != set(union_claims):
                raise ValueError(
                    "top-level evidence must equal the published claim union"
                )
            for key, claims in union_claims.items():
                if top_claims[key] != claims:
                    raise ValueError(
                        "top-level claim union must equal the published claim union"
                    )

        return self
