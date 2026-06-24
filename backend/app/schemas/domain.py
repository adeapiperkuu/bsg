from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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


class QualitySnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    team_id: UUID
    iso_year: int
    iso_week: int
    gold_set_accuracy_pct: Decimal | None
    iaa_krippendorff_alpha: Decimal | None
    rework_rate_pct: Decimal | None
    has_drift_alert: bool
    drift_alert_detail: str | None
    created_at: datetime
    updated_at: datetime


class QualitySnapshotCreate(BaseModel):
    team_id: UUID
    iso_year: int = Field(ge=2024)
    iso_week: int = Field(ge=1, le=53)
    gold_set_accuracy_pct: Decimal | None = Field(default=None, ge=0, le=100)
    iaa_krippendorff_alpha: Decimal | None = Field(default=None, ge=0, le=1)
    rework_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
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
    contributing_causes: dict[str, float] | None
    status: AlertStatus
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


class MitigationRecommendationAssignOwner(BaseModel):
    owner_type: str | None = None
    owner_id: UUID | None = None


class OwnerOptionRead(BaseModel):
    owner_type: str
    owner_id: UUID
    label: str


class ProjectRecommendationsResponse(BaseModel):
    data: list[MitigationRecommendationRead]
    assignable_owners: list[OwnerOptionRead]
    pagination: Pagination


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
