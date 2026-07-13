"""Typed contracts for the Client Intelligence Agent evidence foundation.

These models represent governed facts only — not health scores, readiness,
recommendations, or narratives.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvidenceVisibility(StrEnum):
    INTERNAL = "internal"
    CLIENT_SAFE = "client_safe"


class DataQualityState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    STALE = "stale"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class SourceAgent(StrEnum):
    DELIVERY_PERFORMANCE = "delivery_performance"
    QUALITY_INTELLIGENCE = "quality_intelligence"
    WORKFORCE_CAPABILITY = "workforce_capability"
    PROJECT_GOVERNANCE = "project_governance"
    OPERATIONAL_KNOWLEDGE = "operational_knowledge"
    CLIENT_INTELLIGENCE = "client_intelligence"


class ClientIntelligenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientEvidenceReference(ClientIntelligenceModel):
    source_agent: SourceAgent
    source_table: str
    source_row_id: UUID
    description: str
    visibility: EvidenceVisibility
    observed_at: datetime | None = None
    claim_keys: list[str] = Field(default_factory=list)


class DataQualityIssue(ClientIntelligenceModel):
    """Source completeness/freshness/conflict — not visibility policy."""

    source: str
    state: DataQualityState
    detail: str
    observed_at: datetime | None = None


class VisibilityLimitation(ClientIntelligenceModel):
    """Policy redaction — distinct from missing or stale source data."""

    source: str
    reason: str
    detail: str


class ReportingPeriod(ClientIntelligenceModel):
    start_date: date
    end_date: date
    previous_start_date: date
    previous_end_date: date
    as_of: date


class ProjectIdentityFacts(ClientIntelligenceModel):
    """Client-safe project identity only — no description or internal notes."""

    project_id: UUID
    org_id: UUID
    project_name: str
    project_status: str


class ThroughputSnapshotFacts(ClientIntelligenceModel):
    """Throughput facts. Optional numerics may be omitted under client-safe policy."""

    id: UUID
    snapshot_date: date
    units_completed: int | None = None
    units_forecast: int | None = None
    rolling_7day_units: int | None = None


class DeliveryConfidenceFacts(ClientIntelligenceModel):
    """Delivery confidence facts. ``model_version`` is internal-only."""

    id: UUID
    milestone_id: UUID
    score_pct: Decimal
    status: str
    forecast_completion_date: date | None = None
    model_version: str | None = None
    observed_at: datetime | None = None


class MilestoneFacts(ClientIntelligenceModel):
    id: UUID
    name: str
    planned_date: date
    actual_date: date | None = None
    status: str
    description: str | None = None


class RiskAlertFacts(ClientIntelligenceModel):
    """Structured risk facts. Free-text detail is internal-only when present."""

    id: UUID
    alert_type: str
    risk_tier: str
    title: str
    status: str
    milestone_id: UUID | None = None
    detail: str | None = None
    observed_at: datetime | None = None


class BottleneckFacts(ClientIntelligenceModel):
    """Structured bottleneck facts. Free-text detail is internal-only when present."""

    id: UUID
    title: str
    status: str
    detail: str | None = None
    observed_at: datetime | None = None


class DeliveryEvidenceFacts(ClientIntelligenceModel):
    """Delivery-owned structured facts. No Client Intelligence conclusions."""

    latest_throughput: ThroughputSnapshotFacts | None = None
    latest_delivery_confidence: DeliveryConfidenceFacts | None = None
    milestones: list[MilestoneFacts] = Field(default_factory=list)
    next_milestone_id: UUID | None = None
    open_risks: list[RiskAlertFacts] = Field(default_factory=list)
    open_bottlenecks: list[BottleneckFacts] = Field(default_factory=list)


class QualitySnapshotFacts(ClientIntelligenceModel):
    """Per-team QualitySnapshot aggregate facts. No root-cause or free-text drift."""

    snapshot_id: UUID
    iso_year: int
    iso_week: int
    team_id: UUID | None = None
    gold_set_accuracy_pct: Decimal | None = None
    rework_rate_pct: Decimal | None = None
    iaa_krippendorff_alpha: Decimal | None = None
    evaluated_item_count: int | None = None
    has_drift_alert: bool | None = None
    confidence_level: str | None = None
    observed_at: datetime | None = None


class QualityEvidenceFacts(ClientIntelligenceModel):
    """Quality snapshots for the current and previous reporting ISO weeks."""

    current_period: list[QualitySnapshotFacts] = Field(default_factory=list)
    previous_period: list[QualitySnapshotFacts] = Field(default_factory=list)
    current_iso_year: int
    current_iso_week: int
    previous_iso_year: int
    previous_iso_week: int


class ClientEvidencePack(ClientIntelligenceModel):
    project: ProjectIdentityFacts
    reporting_period: ReportingPeriod
    visibility_mode: EvidenceVisibility
    delivery: DeliveryEvidenceFacts
    quality: QualityEvidenceFacts
    evidence: list[ClientEvidenceReference] = Field(default_factory=list)
    data_quality: list[DataQualityIssue] = Field(default_factory=list)
    overall_data_quality: DataQualityState
    generated_at: datetime
    source_fingerprint: str
    policy_fingerprint: str | None = None
    visibility_limitations: list[VisibilityLimitation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
