import logging
from datetime import date, datetime
from decimal import Decimal
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
    MilestoneStatus,
    ProjectStatus,
    RiskTier,
)
from app.schemas.common import EvidenceLinkRead, ORMModel, ensure_month_start


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


class ThroughputSnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    snapshot_date: date
    units_completed: int
    units_forecast: int | None
    rolling_7day_units: int | None
    created_at: datetime
    updated_at: datetime


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


class AgentQueryCreate(BaseModel):
    agent_name: str
    project_id: UUID | None = None
    query_text: str = Field(min_length=1)


class AgentQueryRead(ORMModel):
    id: UUID
    agent_name: str
    project_id: UUID | None
    query_text: str
    answer_text: str
    model_used: str | None
    latency_ms: int | None
    created_at: datetime
    evidence_links: list[EvidenceLinkRead] = []


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


class SkillGapSignal(BaseModel):
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
