from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import (
    GovernanceActionStatus,
    GovernanceCharterStatus,
    GovernanceDependencyStatus,
    GovernanceDependencyType,
    GovernanceEscalationSeverity,
    GovernanceEscalationSourceType,
    GovernanceEscalationStatus,
    GovernanceEvidenceSourceType,
    GovernanceScopeStatus,
    GovernanceSummaryStatus,
    KnowledgeVisibility,
)
from app.schemas.common import ORMModel


class GovernanceKpisRead(BaseModel):
    open_actions: int
    overdue_actions: int
    open_escalations: int
    blocking_dependencies: int
    at_risk_items: int
    sla_adherence_pct: float


class ProjectScopeStateRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    scope_status: GovernanceScopeStatus
    version_label: str
    notes: str | None
    linked_charter_document_id: UUID | None = None
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectScopeStateUpdate(BaseModel):
    scope_status: GovernanceScopeStatus | None = None
    version_label: str | None = None
    notes: str | None = None
    linked_charter_document_id: UUID | None = None


class ProjectDependencyRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    title: str
    description: str | None
    dependency_type: GovernanceDependencyType
    owner_id: UUID | None
    due_date: date | None
    status: GovernanceDependencyStatus
    resolved_at: datetime | None
    resolved_by: UUID | None
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    overdue_days: int = 0
    project_name: str | None = None
    owner_name: str | None = None


class ProjectDependencyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    dependency_type: GovernanceDependencyType
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceDependencyStatus = GovernanceDependencyStatus.OPEN


class ProjectDependencyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    dependency_type: GovernanceDependencyType | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceDependencyStatus | None = None


class GovernanceEscalationRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    title: str
    description: str | None
    severity: GovernanceEscalationSeverity
    status: GovernanceEscalationStatus
    raised_by: UUID | None
    assigned_to: UUID | None
    raised_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    project_name: str | None = None
    raised_by_name: str | None = None
    assigned_to_name: str | None = None
    source_type: GovernanceEscalationSourceType | None = None
    source_id: UUID | None = None


class GovernanceEscalationCreate(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    severity: GovernanceEscalationSeverity = GovernanceEscalationSeverity.MEDIUM
    status: GovernanceEscalationStatus = GovernanceEscalationStatus.OPEN
    assigned_to: UUID | None = None
    source_type: GovernanceEscalationSourceType | None = None
    source_id: UUID | None = None


class GovernanceEscalationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    severity: GovernanceEscalationSeverity | None = None
    status: GovernanceEscalationStatus | None = None
    assigned_to: UUID | None = None
    resolved_at: datetime | None = None
    source_type: GovernanceEscalationSourceType | None = None
    source_id: UUID | None = None


class PromoteRiskAlertRequest(BaseModel):
    risk_alert_id: UUID


class GovernanceActionRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    title: str
    description: str | None
    owner_id: UUID | None
    due_date: date | None
    status: GovernanceActionStatus
    completed_at: datetime | None
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
    project_name: str | None = None
    owner_name: str | None = None
    linked_knowledge_document_id: UUID | None = None


class GovernanceActionCreate(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceActionStatus = GovernanceActionStatus.OPEN
    linked_knowledge_document_id: UUID | None = None


class GovernanceActionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceActionStatus | None = None
    completed_at: datetime | None = None
    linked_knowledge_document_id: UUID | None = None


class GovernanceEvidenceLinkRead(ORMModel):
    id: UUID
    org_id: UUID
    summary_id: UUID | None = None
    charter_id: UUID | None = None
    source_type: GovernanceEvidenceSourceType
    source_id: UUID
    created_at: datetime
    label: str | None = None
    detail: str | None = None
    project_name: str | None = None


class GovernanceWeeklySummaryRead(ORMModel):
    id: UUID
    org_id: UUID
    summary_week: date
    summary_text: str
    status: GovernanceSummaryStatus
    generated_by_ai: bool
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    evidence_links: list[GovernanceEvidenceLinkRead] = Field(default_factory=list)
    approved_by_name: str | None = None


class GovernanceEvidenceLinkCreate(BaseModel):
    source_type: GovernanceEvidenceSourceType
    source_id: UUID


class GovernanceWeeklySummaryCreate(BaseModel):
    summary_week: date
    summary_text: str = Field(min_length=1)
    evidence_links: list[GovernanceEvidenceLinkCreate] = Field(default_factory=list)


class GovernanceWeeklySummaryUpdate(BaseModel):
    summary_text: str = Field(min_length=1)


class GovernanceWeeklySummaryGenerateRequest(BaseModel):
    summary_week: date | None = None


class ProjectCharterGenerateRequest(BaseModel):
    project_id: UUID
    visibility: KnowledgeVisibility = KnowledgeVisibility.INTERNAL_ONLY


class ProjectCharterUpdate(BaseModel):
    generated_text: str = Field(min_length=1)
    visibility: KnowledgeVisibility | None = None


class ProjectCharterRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    version: str
    status: GovernanceCharterStatus
    generated_text: str
    generated_by_ai: bool
    previous_version_id: UUID | None
    knowledge_document_id: UUID | None
    visibility: KnowledgeVisibility
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    evidence_links: list[GovernanceEvidenceLinkRead] = Field(default_factory=list)
    approved_by_name: str | None = None
    project_name: str | None = None


class GovernanceCharterReferenceRead(BaseModel):
    document_id: UUID
    title: str
    project: str | None
    version: str
    status: str
    visibility: str


class GovernanceKnowledgeDocumentRef(BaseModel):
    document_id: UUID
    title: str
    project: str | None
    version: str
    status: str
    visibility: str
    source_type: str


class GovernanceBootstrapRead(BaseModel):
    kpis: GovernanceKpisRead
    dependencies: list[ProjectDependencyRead]
    escalations: list[GovernanceEscalationRead]
    actions: list[GovernanceActionRead]
    scope_states: list[ProjectScopeStateRead]
    charter_references: list[GovernanceCharterReferenceRead] = Field(default_factory=list)
