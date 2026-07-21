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
    throughput_series: list[ThroughputSnapshotFacts] = Field(default_factory=list)
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


class WorkforceCapacityFacts(ClientIntelligenceModel):
    """Aggregated project capacity and utilization. No identities."""

    active_team_count: int | None = None
    active_worker_count: int | None = None
    certified_sme_count: int | None = None
    latest_snapshot_date: date | None = None
    allocated_hours_total: Decimal | None = None
    available_hours_total: Decimal | None = None
    utilization_pct: Decimal | None = None
    teams_with_utilization: int | None = None
    teams_without_utilization: int | None = None


class TeamCapacityFacts(ClientIntelligenceModel):
    """INTERNAL team-level utilization snapshot facts. No names or notes."""

    team_id: UUID
    snapshot_id: UUID
    snapshot_date: date
    allocated_hours: Decimal
    available_hours: Decimal
    utilization_pct: Decimal
    observed_at: datetime | None = None


class SkillCoverageFacts(ClientIntelligenceModel):
    """INTERNAL per-requirement coverage facts. No skill names or identities.

    When ``coverage_status`` is ``unavailable``, available counts are omitted
    because the referenced skill source is missing or deleted — not factual zero.
    """

    requirement_id: UUID
    skill_id: UUID
    required_proficiency_level: str
    priority: str
    required_headcount: int
    available_headcount: int | None = None
    required_sme_count: int
    available_sme_count: int | None = None
    coverage_status: str
    observed_at: datetime | None = None


class SkillCoverageSummaryFacts(ClientIntelligenceModel):
    """Aggregate skill-requirement coverage.

    Slot totals are sums of per-requirement headcount/SME requirements and
    available matches for requirements with a resolvable active skill. They are
    not unique-employee counts. Unavailable requirements count toward
    ``requirement_count`` but not covered/partial/gap.
    """

    requirement_count: int = 0
    covered_requirement_count: int = 0
    partial_requirement_count: int = 0
    gap_requirement_count: int = 0
    unavailable_requirement_count: int = 0
    required_headcount_slots: int = 0
    available_headcount_slots: int = 0
    required_sme_slots: int = 0
    available_sme_slots: int = 0


class TrainingCompletionFacts(ClientIntelligenceModel):
    """Aggregate mandatory training completion. No individual records."""

    mandatory_program_count: int | None = None
    required_assignment_count: int | None = None
    completed_assignment_count: int | None = None
    incomplete_assignment_count: int | None = None
    expired_or_failed_assignment_count: int | None = None
    completion_pct: Decimal | None = None
    observed_at: datetime | None = None


class CapabilityGapCountFacts(ClientIntelligenceModel):
    gap_type: str
    severity: str
    count: int


class CapabilityGapFacts(ClientIntelligenceModel):
    """INTERNAL structured capability-gap facts. No title/detail/evidence."""

    gap_id: UUID
    gap_type: str
    severity: str
    status: str
    team_id: UUID | None = None
    skill_id: UUID | None = None
    detected_at: datetime
    resolved_at: datetime | None = None
    observed_at: datetime | None = None


class WorkforceEvidenceFacts(ClientIntelligenceModel):
    """Workforce & Capability structured evidence for one project/as_of."""

    capacity: WorkforceCapacityFacts = Field(default_factory=WorkforceCapacityFacts)
    team_capacity: list[TeamCapacityFacts] = Field(default_factory=list)
    skill_coverage: SkillCoverageSummaryFacts = Field(default_factory=SkillCoverageSummaryFacts)
    skill_requirements: list[SkillCoverageFacts] = Field(default_factory=list)
    training: TrainingCompletionFacts = Field(default_factory=TrainingCompletionFacts)
    open_gap_counts: list[CapabilityGapCountFacts] = Field(default_factory=list)
    open_gaps: list[CapabilityGapFacts] = Field(default_factory=list)
    as_of: date


class GovernanceScopeFacts(ClientIntelligenceModel):
    """Project scope-state metadata. No notes or identity fields.

    ``scope_state_id`` is internal-only; CLIENT_SAFE projections set it to None.
    """

    scope_state_id: UUID | None = None
    scope_status: str
    version_label: str
    observed_at: datetime | None = None


class GovernanceCharterFacts(ClientIntelligenceModel):
    """Charter metadata only — never generated_text or approval identity."""

    charter_id: UUID
    version: str
    status: str
    visibility: str
    approved_at: datetime | None = None
    observed_at: datetime | None = None


class GovernanceDependencyFacts(ClientIntelligenceModel):
    """INTERNAL dependency facts. No title, description, or owners."""

    dependency_id: UUID
    dependency_type: str
    status: str
    due_date: date | None = None
    resolved_at: datetime | None = None
    observed_at: datetime | None = None


class GovernanceActionFacts(ClientIntelligenceModel):
    """INTERNAL action facts. No title, description, or owners."""

    action_id: UUID
    status: str
    due_date: date | None = None
    completed_at: datetime | None = None
    observed_at: datetime | None = None


class GovernanceEscalationFacts(ClientIntelligenceModel):
    """INTERNAL escalation facts. No title, description, or ownership."""

    escalation_id: UUID
    severity: str
    status: str
    raised_at: datetime
    resolved_at: datetime | None = None
    source_type: str | None = None
    observed_at: datetime | None = None


class GovernanceCountFacts(ClientIntelligenceModel):
    category: str
    status: str
    count: int


class GovernanceSummaryFacts(ClientIntelligenceModel):
    """Deterministic Governance aggregates — not health or readiness scores."""

    dependency_count: int = 0
    open_dependency_count: int = 0
    blocking_dependency_count: int = 0
    overdue_dependency_count: int = 0
    client_action_dependency_count: int = 0
    action_count: int = 0
    open_action_count: int = 0
    overdue_action_count: int = 0
    escalation_count: int = 0
    open_escalation_count: int = 0
    critical_escalation_count: int = 0
    scope_present: bool = False
    approved_charter_present: bool = False
    client_safe_charter_present: bool = False
    grouped_counts: list[GovernanceCountFacts] = Field(default_factory=list)


class GovernanceEvidenceFacts(ClientIntelligenceModel):
    """Project Governance structured evidence for one project/as_of."""

    scope: GovernanceScopeFacts | None = None
    charter: GovernanceCharterFacts | None = None
    summary: GovernanceSummaryFacts = Field(default_factory=GovernanceSummaryFacts)
    dependencies: list[GovernanceDependencyFacts] = Field(default_factory=list)
    actions: list[GovernanceActionFacts] = Field(default_factory=list)
    escalations: list[GovernanceEscalationFacts] = Field(default_factory=list)
    as_of: date


class KnowledgeDocumentFacts(ClientIntelligenceModel):
    """Approved Knowledge document metadata only.

    ``document_title`` is INTERNAL-only; CLIENT_SAFE projections set it to None.
    Never includes description, project text, department, owners, approvers,
    file/storage metadata, checksums, extracted text, summaries, procedures,
    warnings, rejection reasons, or user IDs.
    """

    document_id: UUID
    source_type: str
    document_type: str | None = None
    version: str
    visibility: str
    effective_date: date | None = None
    approved_at: datetime
    indexed_at: datetime
    active_version_id: UUID
    document_title: str | None = None
    observed_at: datetime | None = None


class KnowledgeChunkFacts(ClientIntelligenceModel):
    """Approved Knowledge chunk evidence.

    ``untrusted_text`` is approved source data, never an instruction to the
    application or LLM. Embeddings, token counts, department/project text,
    folder IDs, storage metadata, and extraction diagnostics are excluded.
    """

    chunk_id: UUID
    document_id: UUID
    source_type: str
    document_version: str
    chunk_index: int
    page_number: int | None = None
    section_label: str | None = None
    untrusted_text: str
    content_sha256: str
    observed_at: datetime | None = None


class KnowledgeSourceAvailabilityFacts(ClientIntelligenceModel):
    """Per-requirement availability for CI-D11–CI-D15 Knowledge inputs."""

    requirement_id: str
    source_type: str
    document_count: int
    chunk_count: int
    state: DataQualityState
    limitation: str | None = None


class KnowledgeEvidenceFacts(ClientIntelligenceModel):
    """Operational Knowledge unstructured evidence for one project/as_of."""

    documents: list[KnowledgeDocumentFacts] = Field(default_factory=list)
    chunks: list[KnowledgeChunkFacts] = Field(default_factory=list)
    source_availability: list[KnowledgeSourceAvailabilityFacts] = Field(default_factory=list)
    as_of: date
    project_scope_key: str


class ClientEvidencePack(ClientIntelligenceModel):
    project: ProjectIdentityFacts
    reporting_period: ReportingPeriod
    visibility_mode: EvidenceVisibility
    delivery: DeliveryEvidenceFacts
    quality: QualityEvidenceFacts
    workforce: WorkforceEvidenceFacts
    governance: GovernanceEvidenceFacts
    knowledge: KnowledgeEvidenceFacts
    evidence: list[ClientEvidenceReference] = Field(default_factory=list)
    data_quality: list[DataQualityIssue] = Field(default_factory=list)
    overall_data_quality: DataQualityState
    generated_at: datetime
    source_fingerprint: str
    policy_fingerprint: str | None = None
    visibility_limitations: list[VisibilityLimitation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceValidationIssue(ClientIntelligenceModel):
    """Integrity/redaction finding. Details must not include raw source values."""

    code: str
    detail: str
    source: str | None = None
    evidence_id: UUID | None = None


class EvidencePackValidationResult(ClientIntelligenceModel):
    is_valid: bool
    errors: list[EvidenceValidationIssue] = Field(default_factory=list)
    warnings: list[EvidenceValidationIssue] = Field(default_factory=list)
