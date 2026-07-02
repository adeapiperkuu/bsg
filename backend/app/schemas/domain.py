import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# Canonical error taxonomy codes (spec §7.3). Names are lowercased for matching.
CANONICAL_ERROR_CODES: dict[str, str] = {
    "ERR-01": "boundary precision",
    "ERR-02": "class confusion",
    "ERR-03": "missed object",
    "ERR-04": "guideline ambiguity",
    "ERR-05": "false positive",
    "ERR-06": "attribute error",
    "ERR-07": "tool error",
    "ERR-OTHER": "other",
}

from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    CommunicationStatus,
    CommunicationType,
    DeliverySite,
    MilestoneStatus,
    ProficiencyLevel,
    ProjectStatus,
    RiskTier,
    SkillCoverageStatus,
    SkillRequirementPriority,
    CertificationStatus,
    TrainingGapType,
    TrainingRecordStatus,
    CapabilityGapSeverity,
    CapabilityGapStatus,
    CapabilityGapType,
)
from app.schemas.common import EvidenceLinkRead, ORMModel, Pagination, ensure_month_start


class OrganisationRead(ORMModel):
    id: UUID
    name: str
    slug: str
    vertical: str
    region: str
    is_active: bool


class OrganisationSummary(ORMModel):
    id: UUID
    name: str
    vertical: str
    region: str


class OrganisationCreate(BaseModel):
    name: str
    slug: str
    vertical: str
    region: str
    is_active: bool = True


class OrganisationUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    vertical: str | None = None
    region: str | None = None
    is_active: bool | None = None


class UserRead(ORMModel):
    id: UUID
    org_id: UUID
    email: str
    full_name: str | None
    role: AppRole
    is_active: bool


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: AppRole
    org_id: UUID


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: AppRole | None = None
    is_active: bool | None = None
    org_id: UUID | None = None
    password: str | None = Field(default=None, min_length=8)


class MePermissions(BaseModel):
    can_manage_projects: bool = False
    can_approve_communications: bool = False
    can_manage_metric_configurations: bool = False
    can_view_cross_client_portfolio: bool = False
    can_manage_users: bool = False
    can_manage_organisations: bool = False


class AuthSessionRead(BaseModel):
    id: UUID
    email: str
    full_name: str | None = None
    role: AppRole


class MeRead(UserRead):
    organisation: OrganisationSummary | None = None
    permissions: MePermissions = Field(default_factory=MePermissions)


class ProjectRead(ORMModel):
    id: UUID
    org_id: UUID
    name: str
    description: str | None
    vertical: str
    status: ProjectStatus
    start_date: date
    target_end_date: date
    actual_end_date: date | None
    daily_target_units: int | None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    vertical: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    start_date: date
    target_end_date: date
    daily_target_units: int | None = Field(default=None, ge=0)
    org_id: UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    target_end_date: date | None = None
    actual_end_date: date | None = None
    daily_target_units: int | None = Field(default=None, ge=0)


class MilestoneRead(ORMModel):
    id: UUID
    project_id: UUID
    name: str
    description: str | None
    planned_date: date
    actual_date: date | None
    status: MilestoneStatus


class TeamRead(ORMModel):
    id: UUID
    project_id: UUID
    org_id: UUID
    name: str
    site: DeliverySite
    domain: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TeamCreate(BaseModel):
    name: str
    site: DeliverySite
    domain: str
    is_active: bool = True


class TeamUpdate(BaseModel):
    name: str | None = None
    site: DeliverySite | None = None
    domain: str | None = None
    is_active: bool | None = None


class AnnotatorRead(ORMModel):
    id: UUID
    org_id: UUID
    team_id: UUID
    full_name: str
    site: DeliverySite
    is_sme_certified: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AnnotatorCreate(BaseModel):
    full_name: str
    site: DeliverySite
    is_sme_certified: bool = False
    is_active: bool = True


class AnnotatorUpdate(BaseModel):
    full_name: str | None = None
    site: DeliverySite | None = None
    is_sme_certified: bool | None = None
    is_active: bool | None = None
    team_id: UUID | None = None


class UtilizationSnapshotRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    team_id: UUID | None
    annotator_id: UUID | None
    snapshot_date: date
    allocated_hours: Decimal
    available_hours: Decimal
    utilization_pct: Decimal
    billable_hours: Decimal | None
    non_billable_hours: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class UtilizationSnapshotCreate(BaseModel):
    snapshot_date: date
    team_id: UUID | None = None
    annotator_id: UUID | None = None
    allocated_hours: Decimal = Field(ge=0)
    available_hours: Decimal = Field(ge=0)
    utilization_pct: Decimal | None = Field(default=None, ge=0)
    billable_hours: Decimal | None = Field(default=None, ge=0)
    non_billable_hours: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def annotator_requires_team(self) -> "UtilizationSnapshotCreate":
        if self.annotator_id is not None and self.team_id is None:
            raise ValueError("team_id is required when annotator_id is provided.")
        return self


class UtilizationSnapshotUpdate(BaseModel):
    snapshot_date: date | None = None
    team_id: UUID | None = None
    annotator_id: UUID | None = None
    allocated_hours: Decimal | None = Field(default=None, ge=0)
    available_hours: Decimal | None = Field(default=None, ge=0)
    utilization_pct: Decimal | None = Field(default=None, ge=0)
    billable_hours: Decimal | None = Field(default=None, ge=0)
    non_billable_hours: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class SkillRead(ORMModel):
    id: UUID
    org_id: UUID
    name: str
    category: str | None
    domain: str | None
    description: str | None
    is_critical: bool
    created_at: datetime
    updated_at: datetime


class SkillCreate(BaseModel):
    name: str
    category: str | None = None
    domain: str | None = None
    description: str | None = None
    is_critical: bool = False


class SkillUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    domain: str | None = None
    description: str | None = None
    is_critical: bool | None = None


class AnnotatorSkillRead(ORMModel):
    id: UUID
    org_id: UUID
    annotator_id: UUID
    skill_id: UUID
    proficiency_level: ProficiencyLevel
    verified_by: UUID | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnnotatorSkillCreate(BaseModel):
    skill_id: UUID
    proficiency_level: ProficiencyLevel
    verified_by: UUID | None = None
    verified_at: datetime | None = None


class AnnotatorSkillUpdate(BaseModel):
    proficiency_level: ProficiencyLevel | None = None
    verified_by: UUID | None = None
    verified_at: datetime | None = None


class ProjectSkillRequirementRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    skill_id: UUID
    required_proficiency_level: ProficiencyLevel
    required_headcount: int
    required_sme_count: int
    priority: SkillRequirementPriority
    created_at: datetime
    updated_at: datetime


class ProjectSkillRequirementCreate(BaseModel):
    skill_id: UUID
    required_proficiency_level: ProficiencyLevel
    required_headcount: int = Field(default=1, ge=0)
    required_sme_count: int = Field(default=0, ge=0)
    priority: SkillRequirementPriority = SkillRequirementPriority.MEDIUM


class ProjectSkillRequirementUpdate(BaseModel):
    required_proficiency_level: ProficiencyLevel | None = None
    required_headcount: int | None = Field(default=None, ge=0)
    required_sme_count: int | None = Field(default=None, ge=0)
    priority: SkillRequirementPriority | None = None


class SkillMatrixSiteSummary(BaseModel):
    site: DeliverySite
    available_headcount: int
    available_sme_count: int
    coverage_status: SkillCoverageStatus


class SkillMatrixRow(BaseModel):
    skill_id: UUID
    skill_name: str
    category: str | None
    domain: str | None
    required_proficiency_level: ProficiencyLevel
    required_headcount: int
    available_headcount: int
    required_sme_count: int
    available_sme_count: int
    coverage_status: SkillCoverageStatus
    by_site: list[SkillMatrixSiteSummary]


class SkillMatrixRead(BaseModel):
    project_id: UUID
    rows: list[SkillMatrixRow]


class CertificationRead(ORMModel):
    id: UUID
    org_id: UUID
    name: str
    issuing_body: str | None
    description: str | None
    validity_months: int | None
    is_required_for_sme: bool
    created_at: datetime
    updated_at: datetime


class CertificationCreate(BaseModel):
    name: str
    issuing_body: str | None = None
    description: str | None = None
    validity_months: int | None = Field(default=None, ge=0)
    is_required_for_sme: bool = False


class CertificationUpdate(BaseModel):
    name: str | None = None
    issuing_body: str | None = None
    description: str | None = None
    validity_months: int | None = Field(default=None, ge=0)
    is_required_for_sme: bool | None = None


class EmployeeCertificationRead(ORMModel):
    id: UUID
    org_id: UUID
    annotator_id: UUID
    certification_id: UUID
    issued_at: date | None
    expires_at: date | None
    status: CertificationStatus
    evidence_url: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeCertificationCreate(BaseModel):
    certification_id: UUID
    issued_at: date | None = None
    expires_at: date | None = None
    status: CertificationStatus = CertificationStatus.ACTIVE
    evidence_url: str | None = None


class EmployeeCertificationUpdate(BaseModel):
    issued_at: date | None = None
    expires_at: date | None = None
    status: CertificationStatus | None = None
    evidence_url: str | None = None


class TrainingProgramRead(ORMModel):
    id: UUID
    org_id: UUID
    skill_id: UUID | None
    name: str
    description: str | None
    required_for_skill_level: ProficiencyLevel | None
    is_mandatory: bool
    knowledge_document_id: UUID | None
    created_at: datetime
    updated_at: datetime


class TrainingProgramCreate(BaseModel):
    name: str
    skill_id: UUID | None = None
    description: str | None = None
    required_for_skill_level: ProficiencyLevel | None = None
    is_mandatory: bool = False
    knowledge_document_id: UUID | None = None


class TrainingProgramUpdate(BaseModel):
    name: str | None = None
    skill_id: UUID | None = None
    description: str | None = None
    required_for_skill_level: ProficiencyLevel | None = None
    is_mandatory: bool | None = None
    knowledge_document_id: UUID | None = None


class TrainingRecordRead(ORMModel):
    id: UUID
    org_id: UUID
    annotator_id: UUID
    training_program_id: UUID
    status: TrainingRecordStatus
    started_at: datetime | None
    completed_at: datetime | None
    score_pct: Decimal | None
    created_at: datetime
    updated_at: datetime


class TrainingRecordCreate(BaseModel):
    training_program_id: UUID
    status: TrainingRecordStatus = TrainingRecordStatus.NOT_STARTED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    score_pct: Decimal | None = Field(default=None, ge=0, le=100)


class TrainingRecordUpdate(BaseModel):
    status: TrainingRecordStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    score_pct: Decimal | None = Field(default=None, ge=0, le=100)


class TrainingGapRow(BaseModel):
    team_id: UUID | None
    team_name: str | None
    skill_id: UUID | None
    skill_name: str | None
    training_program_id: UUID | None
    training_program_name: str | None
    certification_id: UUID | None
    certification_name: str | None
    gap_type: TrainingGapType
    affected_count: int


class TrainingGapSummaryRead(BaseModel):
    project_id: UUID
    total_training_gaps: int
    mandatory_training_incomplete: int
    expired_or_failed_training: int
    expired_certifications: int
    pending_certification_reviews: int
    rows: list[TrainingGapRow]


class CapabilityGapRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    team_id: UUID | None
    skill_id: UUID | None
    gap_type: CapabilityGapType
    severity: CapabilityGapSeverity
    title: str
    detail: str
    evidence: dict[str, Any] | None
    status: CapabilityGapStatus
    detected_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CapabilityGapUpdate(BaseModel):
    status: CapabilityGapStatus | None = None
    severity: CapabilityGapSeverity | None = None
    title: str | None = None
    detail: str | None = None


class CapabilityGapDetectionResponse(BaseModel):
    project_id: UUID
    detected_count: int
    created_count: int
    gaps: list[CapabilityGapRead]
    risk_alerts_created: int
    recommendations_created: int


class ThroughputSnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    snapshot_date: date
    units_completed: int
    units_forecast: int | None
    rolling_7day_units: int | None
    created_at: datetime
    updated_at: datetime
    # Populated only by the create endpoint (never by list reads, where scoring already
    # ran previously). "failed" means the snapshot was stored but confidence/risk scoring
    # did not complete — never silently hidden from the caller.
    scoring_status: str | None = None
    scoring_error: str | None = None


class ThroughputSnapshotCreate(BaseModel):
    snapshot_date: date
    units_completed: int = Field(ge=0)
    units_forecast: int | None = Field(default=None, ge=0)


class QualityErrorEntryRead(ORMModel):
    id: UUID
    quality_snapshot_id: UUID
    error_category: str
    share_pct: Decimal = Field(ge=0, le=100)
    recommended_action: str | None


class QualityErrorEntryCreate(BaseModel):
    error_category: str
    share_pct: Decimal = Field(ge=0, le=100)
    recommended_action: str | None = None
    error_note: str | None = None

    @field_validator("error_category", mode="before")
    @classmethod
    def normalize_error_category(cls, v: str) -> str:
        """Accept canonical code (ERR-01) or canonical name; reject unknown categories."""
        raw = str(v).strip()
        upper = raw.upper()
        if upper in CANONICAL_ERROR_CODES:
            return upper
        lower = raw.lower()
        for code, name in CANONICAL_ERROR_CODES.items():
            if lower == name:
                return code
        allowed = ", ".join(sorted(CANONICAL_ERROR_CODES.keys()))
        raise ValueError(f"Unknown error category {raw!r}. Use one of: {allowed}")

    @model_validator(mode="after")
    def require_note_for_other(self) -> "QualityErrorEntryCreate":
        if self.error_category == "ERR-OTHER" and not self.error_note:
            raise ValueError("error_note is required when error_category is ERR-OTHER")
        return self


class QualitySnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    team_id: UUID
    iso_year: int
    iso_week: int
    gold_set_accuracy_pct: Decimal | None
    iaa_krippendorff_alpha: Decimal | None
    rework_rate_pct: Decimal | None
    evaluated_item_count: int | None
    has_drift_alert: bool
    drift_alert_detail: str | None
    root_cause: dict | None
    confidence_level: str | None
    created_at: datetime
    updated_at: datetime
    error_entries: list[QualityErrorEntryRead] = []


class QualitySnapshotUpdate(BaseModel):
    gold_set_accuracy_pct: Decimal | None = Field(default=None, ge=0, le=100)
    iaa_krippendorff_alpha: Decimal | None = Field(default=None, ge=0, le=1)
    rework_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    evaluated_item_count: int | None = Field(default=None, ge=0)


class QualitySnapshotCreate(BaseModel):
    team_id: UUID
    iso_year: int = Field(ge=2024)
    iso_week: int = Field(ge=1, le=53)
    gold_set_accuracy_pct: Decimal | None = Field(default=None, ge=0, le=100)
    iaa_krippendorff_alpha: Decimal | None = Field(default=None, ge=0, le=1)
    rework_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    evaluated_item_count: int | None = Field(default=None, ge=0)
    error_entries: list[QualityErrorEntryCreate] = []


class RiskAlertRead(ORMModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID | None
    alert_type: AlertType
    risk_tier: RiskTier
    title: str
    detail: str
    slippage_probability: Decimal | None
    contributing_causes: dict | None
    status: AlertStatus
    source_table: str | None = None
    source_row_id: UUID | None = None
    resolved_at: datetime | None
    resolved_by: UUID | None
    created_at: datetime
    updated_at: datetime


class RiskAlertUpdate(BaseModel):
    status: AlertStatus


class MitigationRecommendationRead(ORMModel):
    id: UUID
    project_id: UUID
    title: str
    description: str | None
    severity: str
    confidence_score: Decimal
    status: str
    owner_type: str | None
    owner_id: UUID | None
    owner_label: str | None = None
    source_risk_id: UUID | None
    source_risk_title: str | None = None
    source_risk_type: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkforceRecommendationGenerateResponse(BaseModel):
    project_id: UUID
    recommendations_created: int
    recommendations: list[MitigationRecommendationRead]


class MitigationRecommendationAssignOwner(BaseModel):
    owner_type: str | None = None
    owner_id: UUID | None = None


class OwnerOptionRead(BaseModel):
    owner_type: str
    owner_id: UUID
    label: str


class GroupedRecommendationRiskRead(BaseModel):
    """One risk-level member within a GroupedMitigationRecommendationRead."""

    recommendation_id: UUID
    source_risk_id: UUID | None
    source_risk_title: str | None = None
    description: str | None
    status: str
    confidence_score: Decimal
    # True when confidence_score fell back to a static per-tier constant rather than
    # being computed from the linked risk's slippage_probability.
    is_estimated: bool = False
    owner_type: str | None = None
    owner_id: UUID | None = None
    owner_label: str | None = None


class GroupedMitigationRecommendationRead(BaseModel):
    """Recommendations sharing the same action title, grouped for display.

    This is a read-time aggregation of MitigationRecommendationRead rows —
    each linked risk keeps its own id/status/confidence in `risks` so
    accept/reject/assign-owner continue to act on individual recommendations.
    """

    title: str
    severity: str
    confidence_score: Decimal
    is_estimated: bool = False
    project_id: UUID
    risks: list[GroupedRecommendationRiskRead]
    statuses: list[str]
    descriptions: list[str]


class ProjectRecommendationsResponse(BaseModel):
    data: list[GroupedMitigationRecommendationRead]
    assignable_owners: list[OwnerOptionRead]
    pagination: Pagination


class AgentQueryCreate(BaseModel):
    agent_name: str
    project_id: UUID | None = None
    query_text: str = Field(min_length=1)
    filters: dict[str, object] | None = None


class AgentQueryRead(ORMModel):
    id: UUID
    agent_name: str
    project_id: UUID | None
    query_text: str
    answer_text: str
    model_used: str | None
    latency_ms: int | None
    created_at: datetime
    retrieval_params: dict[str, object] | None = None
    evidence_links: list[EvidenceLinkRead] = []
    confidence_level: str | None = None
    insufficient_evidence: bool = False
    related_records: list[dict[str, object]] = []
    source_agents_used: list[str] = []


class CommunicationDraftCreate(BaseModel):
    comm_type: CommunicationType
    subject: str
    instructions: str | None = None


class CommunicationReview(BaseModel):
    body_approved: str
    status: CommunicationStatus = CommunicationStatus.IN_REVIEW


class CommunicationApprove(BaseModel):
    body_approved: str | None = None


class CommunicationRead(ORMModel):
    id: UUID
    project_id: UUID
    comm_type: CommunicationType
    subject: str
    body_draft: str
    body_approved: str | None
    status: CommunicationStatus
    drafted_by_agent: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    evidence_links: list[EvidenceLinkRead] = []


class MetricConfigurationRead(ORMModel):
    id: UUID
    metric_key: str
    display_label: str
    is_client_visible: bool
    display_order: int
    description: str | None
    threshold_config: dict | None = None


class MetricConfigurationCreate(BaseModel):
    metric_key: str
    display_label: str
    is_client_visible: bool = False
    display_order: int = 0
    description: str | None = None


class MetricConfigurationUpdate(BaseModel):
    display_label: str | None = None
    is_client_visible: bool | None = None
    display_order: int | None = None
    description: str | None = None
    threshold_config: dict | None = None


class QualityDashboardKpis(BaseModel):
    gold_set_accuracy_pct: Decimal | None = None
    iaa_krippendorff_alpha: Decimal | None = None
    rework_rate_pct: Decimal | None = None
    rework_rate_target_pct: Decimal | None = None
    active_drift_alerts: int = 0


class QualityTrendPoint(BaseModel):
    iso_year: int
    iso_week: int
    gold_set_accuracy_pct: Decimal | None = None
    iaa_krippendorff_alpha: Decimal | None = None


class QualityErrorBreakdown(BaseModel):
    error_category: str
    share_pct: Decimal


class QualityTeamScorecard(BaseModel):
    team_id: UUID
    team_name: str
    gold_set_accuracy_pct: Decimal | None = None
    iaa_krippendorff_alpha: Decimal | None = None
    rework_rate_pct: Decimal | None = None
    status: str
    has_drift_alert: bool = False
    has_data_gap: bool = False
    evaluated_item_count: int | None = None


class QualityDashboardRead(BaseModel):
    kpis: QualityDashboardKpis
    trend: list[QualityTrendPoint]
    error_breakdown: list[QualityErrorBreakdown]
    team_scorecard: list[QualityTeamScorecard]
    drift_alerts: list[RiskAlertRead] = []
    narrative: str | None = None
    data_gap_teams: list[str] = []


class QualityDriftEvent(BaseModel):
    team: str
    week: int
    status: str
    resolution_summary: str | None = None


class QualitySummaryRead(BaseModel):
    report_type: str = "quality_summary"
    period: str
    project_id: UUID
    overall_status: str
    gold_set_accuracy_blended: str | None
    rework_rate: str | None
    rework_rate_target: str
    iaa_score: str | None
    drift_events_this_period: list[QualityDriftEvent] = []
    client_narrative: str | None
    confidence: str


class QualityScanRunRead(ORMModel):
    id: UUID
    trigger: str
    triggered_by: UUID | None
    iso_year: int
    iso_week: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    projects_scanned: int
    snapshots_evaluated: int
    alerts_created: int
    data_gaps: int
    per_project_results: list[dict] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminProjectRead(BaseModel):
    id: UUID
    name: str
    org_id: UUID
    org_name: str
    status: ProjectStatus
    vertical: str
    start_date: date
    target_end_date: date
    latest_iso_year: int | None = None
    latest_iso_week: int | None = None
    active_drift_alerts: int = 0
    data_gap_teams: list[str] = []


class QualityPortfolioProjectRead(BaseModel):
    project_id: UUID
    name: str
    org_name: str
    status: str
    active_drift_alerts: int = 0
    latest_gold_accuracy: str | None = None
    data_gap: bool = False


class QualityPortfolioRead(BaseModel):
    portfolio_week: str
    projects_total: int
    projects_with_drift: int
    blended_gold_accuracy: str | None = None
    blended_rework_rate: str | None = None
    per_project: list[QualityPortfolioProjectRead] = []


class NotificationRead(ORMModel):
    id: UUID
    title: str
    body: str
    is_read: bool
    source_table: str | None
    source_row_id: UUID | None
    created_at: datetime


class NotificationUpdate(BaseModel):
    is_read: bool


class ClientCsatCreate(BaseModel):
    score: Decimal = Field(ge=1, le=5)
    reporting_period_month: date
    comment: str | None = None

    @field_validator("reporting_period_month")
    @classmethod
    def validate_month_start(cls, value: date) -> date:
        return ensure_month_start(value)


# --- Phase 2.0 Quality Intelligence schemas ---


class KnowledgeLessonCreate(BaseModel):
    title: str
    body: str
    tags: list[str] = []
    linked_quality_event_id: UUID | None = None
    linked_alert_id: UUID | None = None


class KnowledgeLessonRead(ORMModel):
    id: UUID
    org_id: UUID
    title: str
    body: str
    tags: list[str] = []
    linked_quality_event_id: UUID | None = None
    linked_alert_id: UUID | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class KnowledgeSearchResult(BaseModel):
    id: UUID
    source_type: str
    title: str
    snippet: str


class ReviewerScorecardCreate(BaseModel):
    annotator_id: UUID
    iso_year: int = Field(ge=2024)
    iso_week: int = Field(ge=1, le=53)
    items_evaluated: int = Field(ge=0)
    accuracy_pct: Decimal | None = Field(default=None, ge=0, le=100)
    error_breakdown: dict | None = None


class ReviewerScorecardRead(ORMModel):
    id: UUID
    annotator_id: UUID
    project_id: UUID
    org_id: UUID
    iso_year: int
    iso_week: int
    items_evaluated: int
    accuracy_pct: Decimal | None
    error_breakdown: dict | None
    created_at: datetime
    updated_at: datetime


class KnowledgeFolderRead(ORMModel):
    id: UUID
    name: str
    folder_kind: str
    display_order: int


class KnowledgeFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeQualityCriterion(BaseModel):
    key: str
    label: str
    passed: bool


class KnowledgeQualityScore(BaseModel):
    score: int
    max_score: int = 6
    criteria: list[KnowledgeQualityCriterion]


class KnowledgeChunkRead(BaseModel):
    id: UUID
    chunk_index: int
    section_title: str | None = None
    page_number: int | None = None
    chunk_text: str
    token_count: int | None = None


class KnowledgeDocumentRead(ORMModel):
    id: UUID
    folder_id: UUID
    folder_name: str
    folder_kind: str
    title: str
    source_type: str
    version: str
    visibility: str
    status: str
    owner_approver: str
    effective_date: date | None
    file_name: str
    file_mime_type: str
    file_url: str | None = None
    processing_status: str
    processing_error: str | None = None
    indexing_status: str
    preview: list[str]
    workflow_state: str = "needs_review"
    quality_score: KnowledgeQualityScore | None = None
    chunk_count: int = 0
    citation_count: int = 0
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    chunks: list[KnowledgeChunkRead] = []
    semantic_relevance: float | None = None
    created_at: datetime
    updated_at: datetime


class GoldSetEvaluationLogCreate(BaseModel):
    annotator_id: UUID
    item_id: str
    score: Decimal | None = Field(default=None, ge=0, le=100)
    error_category: str | None = None
    evaluated_at: datetime | None = None

    @field_validator("error_category", mode="before")
    @classmethod
    def normalize_eval_error_category(cls, v: str | None) -> str | None:
        if v is None:
            return None
        raw = str(v).strip()
        upper = raw.upper()
        if upper in CANONICAL_ERROR_CODES:
            return upper
        lower = raw.lower()
        for code, name in CANONICAL_ERROR_CODES.items():
            if lower == name:
                return code
        allowed = ", ".join(sorted(CANONICAL_ERROR_CODES.keys()))
        raise ValueError(f"Unknown error category {raw!r}. Use one of: {allowed}")


class GoldSetEvaluationLogRead(ORMModel):
    id: UUID
    annotator_id: UUID
    project_id: UUID
    org_id: UUID
    item_id: str
    score: Decimal | None
    error_category: str | None
    evaluated_at: datetime
    created_at: datetime


class ReworkLogCreate(BaseModel):
    annotator_id: UUID | None = None
    item_id: str
    reason: str | None = None
    rework_date: date


class ReworkLogRead(ORMModel):
    id: UUID
    project_id: UUID
    org_id: UUID
    annotator_id: UUID | None
    item_id: str
    reason: str | None
    rework_date: date
    created_at: datetime


class SopAmbiguityConfirm(BaseModel):
    alert_id: UUID
    sop_version_id: UUID


class QualitySopLinkRead(ORMModel):
    id: UUID
    org_id: UUID
    risk_alert_id: UUID
    sop_version_id: UUID
    confirmed_by: UUID | None
    created_at: datetime


class IaaMeasurementCreate(BaseModel):
    team_id: UUID | None = None
    reviewer_a_id: UUID
    reviewer_b_id: UUID
    task_type: str | None = None
    krippendorff_alpha: Decimal | None = Field(default=None, ge=0, le=1)
    iso_year: int = Field(ge=2024)
    iso_week: int = Field(ge=1, le=53)


class IaaMeasurementRead(ORMModel):
    id: UUID
    project_id: UUID
    org_id: UUID
    team_id: UUID | None
    reviewer_a_id: UUID
    reviewer_b_id: UUID
    task_type: str | None
    krippendorff_alpha: Decimal | None
    iso_year: int
    iso_week: int
    created_at: datetime


class SopVersionCreate(BaseModel):
    sop_document_id: UUID
    version: str
    change_summary: str | None = None
    effective_date: date


class SopVersionRead(ORMModel):
    id: UUID
    sop_document_id: UUID
    org_id: UUID
    version: str
    change_summary: str | None
    effective_date: date
    created_at: datetime


class GoldSetMetadataCreate(BaseModel):
    version: str
    item_count: int = Field(ge=0)


class GoldSetMetadataRead(ORMModel):
    id: UUID
    project_id: UUID
    org_id: UUID
    version: str
    item_count: int
    last_updated: datetime
    created_at: datetime
    updated_at: datetime


class OnboardingRecordCreate(BaseModel):
    annotator_id: UUID
    onboarding_date: date
    calibration_status: str = "pending"
    notes: str | None = None


class OnboardingRecordRead(ORMModel):
    id: UUID
    annotator_id: UUID
    org_id: UUID
    onboarding_date: date
    calibration_status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class QualitySkillGapSignalRead(BaseModel):
    """Inter-agent skill_gap payload emitted by quality calibration."""
    signal_type: str = "skill_gap"
    reviewer_ids: list[str]
    project_id: UUID
    task_type: str | None = None
    error_category: str | None = None
    recommendation: str
    urgency: str


class CalibrationCandidateRead(BaseModel):
    annotator_id: UUID
    accuracy_pct: float | None
    items_evaluated: int
    error_category: str | None = None
    priority: str
    reason: str


class CalibrationBriefRead(BaseModel):
    project_id: UUID
    iso_year: int
    iso_week: int
    candidates: list[CalibrationCandidateRead] = []
    brief_text: str | None = None
    signal_sent_at: datetime | None = None


class SopAmbiguityFlagRead(BaseModel):
    alert_id: UUID | None = None
    task_type: str | None = None
    affected_reviewer_count: int = 0
    sop_version: str | None = None
    draft_amendment: str | None = None
    detail: str | None = None


class WhatIfQueryRead(BaseModel):
    scenario: str
    projected_outcome: str
    assumptions: list[str] = []
    confidence: str
    no_precedent: bool = False
    comparable_lessons: list[dict] = []


class InterAgentSignalRead(ORMModel):
    id: UUID
    signal_type: str
    source_agent: str
    target_agent: str
    payload: dict
    status: str
    project_id: UUID | None
    org_id: UUID | None
    created_at: datetime


class RiskAlertResolve(BaseModel):
    resolution_summary: str | None = None


# --- Workforce dashboard schemas ---


class SkillGapSignal(BaseModel):
    id: UUID
    title: str
    body: str
    source_row_id: UUID | None = None
    created_at: datetime
    is_read: bool


class TeamUtilizationRead(BaseModel):
    team_id: UUID
    team_name: str
    iso_year: int
    iso_week: int
    target_hours: Decimal
    logged_hours: Decimal
    utilization_pct: Decimal | None = None
    status: str


class SkillMatrixEntry(BaseModel):
    skill_code: str
    proficiency_counts: dict[str, int]


class WorkforceDashboardKpis(BaseModel):
    teams_tracked: int
    avg_utilization_pct: str | None = None
    sme_certified_count: int
    skill_records: int
    open_skill_gaps: int


class WorkforceDashboardRead(BaseModel):
    kpis: WorkforceDashboardKpis
    team_utilization: list[TeamUtilizationRead] = []
    skill_matrix: list[SkillMatrixEntry] = []
    skill_gap_signals: list[SkillGapSignal] = []


class SmeAllocationRead(BaseModel):
    annotator_id: UUID
    team_id: UUID
    team_name: str
    site: str
    skills: list[str]
    utilization_pct: Decimal | None = None


# --- Knowledge library schemas ---


class KnowledgeFolderRead(ORMModel):
    id: UUID
    name: str
    folder_kind: str
    display_order: int


class KnowledgeFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeQualityCriterion(BaseModel):
    key: str
    label: str
    passed: bool


class KnowledgeQualityScore(BaseModel):
    score: int
    max_score: int = 6
    criteria: list[KnowledgeQualityCriterion]


class KnowledgeChunkRead(BaseModel):
    id: UUID
    chunk_index: int
    section_title: str | None = None
    page_number: int | None = None
    chunk_text: str
    token_count: int | None = None


class KnowledgeDocumentRead(ORMModel):
    id: UUID
    folder_id: UUID
    folder_name: str
    folder_kind: str
    title: str
    source_type: str
    version: str
    visibility: str
    status: str
    owner_approver: str
    effective_date: date | None
    file_name: str
    file_mime_type: str
    file_url: str | None = None
    processing_status: str
    processing_error: str | None = None
    indexing_status: str
    preview: list[str]
    workflow_state: str = "needs_review"
    quality_score: KnowledgeQualityScore | None = None
    chunk_count: int = 0
    citation_count: int = 0
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    chunks: list[KnowledgeChunkRead] = []
    semantic_relevance: float | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = None
    folder_id: UUID | None = None
    folder_kind: str | None = None
    source_type: str | None = None
    version: str | None = None
    visibility: str | None = None
    status: str | None = None
    owner_approver: str | None = None
    effective_date: date | None = None


class KnowledgeConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class KnowledgeAskCreate(BaseModel):
    query_text: str = Field(min_length=1, max_length=8000)
    conversation_history: list[KnowledgeConversationTurn] = Field(default_factory=list, max_length=6)
    answer_mode: Literal["internal", "client_safe"] = "internal"
    include_histories: bool = True
    max_sources: int = Field(default=5, ge=1, le=10)
    min_relevance_score: float = Field(default=0.25, ge=0.0, le=1.0)
    project: str | None = None
    department: str | None = None


class KnowledgeCitationRead(BaseModel):
    document_id: UUID
    chunk_id: UUID | None = None
    citation_label: str
    title: str
    source_type: str
    version: str
    folder_name: str = ""
    folder_kind: str = ""
    relevance_score: float = 0.0
    page_number: int | None = None
    chunk_index: int | None = None
    chunk_preview: str = ""
    section_title: str | None = None


class KnowledgeStructuredAnswer(BaseModel):
    policy: str = ""
    steps: str = ""
    owner: str = ""
    evidence: str = ""
    next_action: str = ""


class KnowledgeGapRead(BaseModel):
    message: str
    suggested_title: str | None = None
    suggested_source_type: str | None = None
    suggested_folder_kind: str | None = None


class KnowledgeGapTodoRead(BaseModel):
    id: UUID
    query_text: str
    message: str
    suggested_title: str | None = None
    suggested_source_type: str | None = None
    suggested_folder_kind: str | None = None
    agent_query_id: UUID | None = None
    created_at: datetime


class KnowledgeLibraryHealthRead(BaseModel):
    ready_count: int = 0
    needs_review_count: int = 0
    expired_count: int = 0
    needs_reindex_count: int = 0
    indexing_count: int = 0
    draft_count: int = 0
    archived_count: int = 0
    open_gaps: list[KnowledgeGapTodoRead] = Field(default_factory=list)


class KnowledgeBootstrapRead(BaseModel):
    folders: list[KnowledgeFolderRead]
    documents: list[KnowledgeDocumentRead]
    library_health: KnowledgeLibraryHealthRead


class KnowledgeAskRead(BaseModel):
    answer_text: str
    next_step: str = ""
    confidence_score: float = 0.0
    confidence_reasons: list[str] = []
    structured_answer: KnowledgeStructuredAnswer | None = None
    knowledge_gap: KnowledgeGapRead | None = None
    citations: list[KnowledgeCitationRead]
    query_id: UUID | None = None
    model_used: str | None = None
    retrieval_debug: dict[str, object] | None = None


class KnowledgeDocumentVersionRead(BaseModel):
    id: UUID
    version: str
    is_active: bool
    uploaded_at: datetime
    uploaded_by_name: str | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    checksum_sha256: str | None = None
    chunk_count: int = 0


class KnowledgeVersionCompareRead(BaseModel):
    left_version: str
    right_version: str
    left_approved_by: str | None = None
    right_approved_by: str | None = None
    summary: str
    added_sections: list[str] = []
    removed_sections: list[str] = []


class KnowledgeRetrievalSettingsRead(BaseModel):
    only_approved: bool = True
    include_histories: bool = True
    min_confidence: float = 0.25
    max_sources: int = 5
    project: str | None = None
    department: str | None = None


class KnowledgeRetrievalSettingsUpdate(BaseModel):
    only_approved: bool | None = None
    include_histories: bool | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    max_sources: int | None = Field(default=None, ge=1, le=10)
    project: str | None = None
    department: str | None = None


class KnowledgeFeedbackCreate(BaseModel):
    query_id: UUID
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


class KnowledgeFeedbackRead(BaseModel):
    id: UUID
    query_id: UUID
    rating: str
    comment: str | None = None
    created_at: datetime


class KnowledgeEvalQuestionCreate(BaseModel):
    question_text: str = Field(min_length=1, max_length=8000)
    expected_document_ids: list[UUID] = Field(default_factory=list, max_length=10)
    expected_answer_notes: str | None = Field(default=None, max_length=4000)


class KnowledgeEvalQuestionUpdate(BaseModel):
    question_text: str | None = Field(default=None, min_length=1, max_length=8000)
    expected_document_ids: list[UUID] | None = Field(default=None, max_length=10)
    expected_answer_notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


class KnowledgeEvalQuestionRead(BaseModel):
    id: UUID
    question_text: str
    expected_document_ids: list[UUID] = []
    expected_answer_notes: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class KnowledgeEvalRunItemRead(BaseModel):
    id: UUID
    eval_question_id: UUID
    query_id: UUID | None = None
    citation_hit: bool
    empty_answer: bool
    latency_ms: int | None = None
    observed_document_ids: list[UUID] = []
    created_at: datetime


class KnowledgeEvalRunRead(BaseModel):
    run_count: int
    citation_hit_rate: float
    empty_answer_rate: float
    latency_p95_ms: int | None = None
    results: list[KnowledgeEvalRunItemRead]


class KnowledgeEvalMetricsRead(BaseModel):
    days: int
    total_queries: int
    empty_answer_rate: float
    latency_p95_ms: int | None = None
    downvote_rate: float
    eval_question_count: int
    eval_run_count: int
    citation_hit_rate: float


# --- Workforce dashboard schemas ---


class TeamUtilizationRead(BaseModel):
    team_id: UUID
    team_name: str
    iso_year: int
    iso_week: int
    target_hours: Decimal | None = None
    logged_hours: Decimal | None = None
    utilization_pct: Decimal | None = None
    status: str


class SkillMatrixEntry(BaseModel):
    skill_code: str
    proficiency_counts: dict[str, int]


class SkillGapSignal(BaseModel):
    id: UUID
    title: str
    body: str
    source_row_id: UUID | None = None
    created_at: datetime
    is_read: bool


class WorkforceDashboardKpis(BaseModel):
    teams_tracked: int = 0
    avg_utilization_pct: str | None = None
    sme_certified_count: int = 0
    skill_records: int = 0
    open_skill_gaps: int = 0


class WorkforceDashboardRead(BaseModel):
    kpis: WorkforceDashboardKpis
    team_utilization: list[TeamUtilizationRead] = []
    skill_matrix: list[SkillMatrixEntry] = []
    skill_gap_signals: list[SkillGapSignal] = []


class SmeAllocationRead(BaseModel):
    annotator_id: UUID
    team_id: UUID
    team_name: str
    site: str
    skills: list[str] = []
    utilization_pct: Decimal | None = None
