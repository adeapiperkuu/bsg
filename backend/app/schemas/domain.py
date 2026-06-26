from datetime import date, datetime
from decimal import Decimal
from typing import Literal
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
    retrieval_params: dict[str, object] | None = None
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
