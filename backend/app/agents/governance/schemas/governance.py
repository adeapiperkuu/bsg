from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import (
    GovernanceActionStatus,
    GovernanceAIRecommendationPriority,
    GovernanceAIRecommendationScope,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceCharterPublicationEventType,
    GovernanceCharterPublicationStatus,
    GovernanceCharterStatus,
    GovernanceDependencyStatus,
    GovernanceDependencyType,
    GovernanceEscalationSeverity,
    GovernanceEscalationSourceType,
    GovernanceEscalationStatus,
    GovernanceEvidenceSourceType,
    GovernanceRecommendationAcceptanceStatus,
    GovernanceRecommendationConversionTarget,
    GovernanceRecordEvidenceSourceType,
    GovernanceRecordLinkType,
    GovernanceScopeStatus,
    GovernanceSummaryStatus,
    KnowledgeVisibility,
)
from app.schemas.common import ORMModel


# --- Phase 8 provenance schemas ---


class GovernanceRecordEvidenceLinkRead(BaseModel):
    id: UUID
    link_type: GovernanceRecordLinkType
    source_type: GovernanceRecordEvidenceSourceType
    source_id: UUID | None = None
    evidence_id: str | None = None
    recommendation_id: UUID | None = None
    conversion_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    severity: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    occurred_at: datetime | None = None
    created_at: datetime
    source_available: bool = True
    can_view_source: bool = True


class GovernanceSourceRecommendationRead(BaseModel):
    id: UUID
    title: str
    recommendation_type: str | None = None
    priority: str | None = None
    confidence: float | None = None
    generated_at: datetime | None = None
    status: str | None = None
    accepted_at: datetime | None = None
    source_type: Literal["ai_recommendation"] = "ai_recommendation"
    can_view: bool = True
    source_available: bool = True


class GovernanceProvenanceMixin(BaseModel):
    provenance_source_type: Literal["manual", "ai_recommendation", "delivery_risk", "other"] = (
        "manual"
    )
    source_recommendation_id: UUID | None = None
    source_recommendation_title: str | None = None
    source_conversion_id: UUID | None = None
    evidence_link_count: int = 0
    has_ai_source: bool = False


# --- AI recommendation schemas (Phase 6) ---


class GovernanceSuggestedAction(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=800)
    action_type: Literal[
        "review",
        "assign_owner",
        "resolve_dependency",
        "create_action",
        "consider_escalation",
        "schedule_governance_review",
        "update_scope",
        "monitor",
    ]
    target_entity_type: str | None = Field(default=None, max_length=64)
    target_entity_id: UUID | None = None


class GovernanceAIRecommendationCandidate(BaseModel):
    scope: Literal["project", "portfolio"]
    project_id: UUID | None = None
    recommendation_type: GovernanceAIRecommendationType
    title: str = Field(min_length=1, max_length=200)
    narrative: str = Field(min_length=1, max_length=2500)
    rationale: str = Field(min_length=1, max_length=1500)
    priority: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    suggested_actions: list[GovernanceSuggestedAction] = Field(default_factory=list, max_length=8)


class GovernanceAIRecommendationLLMResponse(BaseModel):
    recommendations: list[GovernanceAIRecommendationCandidate] = Field(default_factory=list)


class GovernanceAIRecommendationEvidenceRead(BaseModel):
    evidence_id: str
    entity_type: str
    entity_id: UUID | None = None
    project_id: UUID | None = None
    title: str
    summary: str
    status: str | None = None
    severity: str | None = None
    occurred_at: datetime | None = None


class GovernanceAIRecommendationRead(BaseModel):
    id: UUID
    scope: GovernanceAIRecommendationScope
    project_id: UUID | None = None
    project_name: str | None = None
    recommendation_type: GovernanceAIRecommendationType
    title: str
    narrative: str
    rationale: str
    priority: GovernanceAIRecommendationPriority
    confidence: float
    suggested_actions: list[GovernanceSuggestedAction] = Field(default_factory=list)
    evidence: list[GovernanceAIRecommendationEvidenceRead] = Field(default_factory=list)
    status: GovernanceAIRecommendationStatus
    generated_at: datetime
    expires_at: datetime | None = None
    can_regenerate: bool = False
    can_dismiss: bool = False
    is_ai_generated: bool = True
    source_type: Literal["ai", "rule_based"] = "ai"
    is_stale: bool = False
    evidence_hash: str | None = None
    acceptance_status: GovernanceRecommendationAcceptanceStatus = (
        GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED
    )
    accepted_at: datetime | None = None
    accepted_by_user_id: UUID | None = None
    converted_action_id: UUID | None = None
    converted_escalation_id: UUID | None = None
    accepted_suggested_action_index: int | None = None
    acceptance_note: str | None = None
    auto_detected: bool = False
    trigger_type: str | None = None
    trigger_entity_type: str | None = None
    trigger_entity_id: UUID | None = None
    severity_score: float | None = None
    detected_at: datetime | None = None
    snoozed_until: datetime | None = None
    can_snooze: bool = False
    linked_milestone_id: UUID | None = None
    risk_categories: list[str] = Field(default_factory=list)
    signal_providers: list[str] = Field(default_factory=list)
    repeated_detection_count: int | None = None
    latest_detected_at: datetime | None = None


class GovernanceRuleBasedRecommendationRead(BaseModel):
    title: str
    detail: str
    priority: str
    project_id: UUID | None = None
    project_name: str | None = None
    evidence: list[GovernanceAIRecommendationEvidenceRead] = Field(default_factory=list)
    source_type: Literal["rule_based"] = "rule_based"
    is_ai_generated: bool = False


class GovernanceAIRecommendationGenerateRequest(BaseModel):
    project_id: UUID | None = None
    scope: GovernanceAIRecommendationScope = GovernanceAIRecommendationScope.PROJECT
    force: bool = False


class GovernanceAIRecommendationDismissRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class GovernanceAIRecommendationFeedbackRequest(BaseModel):
    helpful: bool
    reason: str | None = Field(default=None, max_length=500)


class GovernanceAIRecommendationFeedbackRead(BaseModel):
    id: UUID
    recommendation_id: UUID
    helpful: bool
    reason: str | None = None
    created_at: datetime


class EscalationSuggestionScanRequest(BaseModel):
    project_id: UUID | None = None
    force: bool = False


class EscalationSuggestionSnoozeRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=90)
    snoozed_until: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class EscalationSuggestionScanResult(BaseModel):
    suggestions: list[GovernanceAIRecommendationRead] = Field(default_factory=list)
    candidates_detected: int = 0
    suggestions_created: int = 0
    suggestions_reused: int = 0
    suggestions_suppressed_existing_escalation: int = 0
    projects_scanned: int = 0
    duration_ms: float = 0
    query_executes: int = 0
    llm_enrichment_used: bool = False
    enabled: bool = True
    signals_evaluated: int = 0
    suggestions_skipped_by_cooldown: int = 0
    provider_failures: dict[str, str] = Field(default_factory=dict)
    scan_id: UUID | None = None


class EscalationSuggestionScanHistoryRead(ORMModel):
    id: UUID
    org_id: UUID
    project_id: UUID | None = None
    scan_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    projects_checked: int
    signals_evaluated: int
    suggestions_created: int
    suggestions_refreshed: int
    suggestions_skipped_by_cooldown: int
    suggestions_suppressed_existing_escalation: int
    provider_failures: dict[str, str] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = None
    failure_reason: str | None = None


class ConvertRecommendationToActionRequest(BaseModel):
    suggested_action_index: int | None = Field(default=None, ge=0)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    project_id: UUID
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceActionStatus = GovernanceActionStatus.OPEN
    linked_knowledge_document_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=120)


class ConvertRecommendationToEscalationRequest(BaseModel):
    suggested_action_index: int | None = Field(default=None, ge=0)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    project_id: UUID
    severity: GovernanceEscalationSeverity = GovernanceEscalationSeverity.MEDIUM
    status: GovernanceEscalationStatus = GovernanceEscalationStatus.OPEN
    assigned_to: UUID | None = None
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=120)


class GovernanceAIRecommendationGenerationResult(BaseModel):
    recommendations: list[GovernanceAIRecommendationRead] = Field(default_factory=list)
    rule_based_fallback: list[GovernanceRuleBasedRecommendationRead] = Field(default_factory=list)
    reused: bool = False
    fallback_used: bool = False
    fallback_reason: str | None = None
    generation_request_id: UUID | None = None
    evidence_hash: str | None = None
    candidates_returned: int = 0
    candidates_persisted: int = 0
    candidates_rejected_grounding: int = 0
    duplicates_suppressed: int = 0
    duration_ms: float | None = None
    projects_attempted: int = 0
    projects_with_recommendations: int = 0
    projects_reused: int = 0
    projects_using_fallback: int = 0
    project_failures: dict[str, str] = Field(default_factory=dict)


class GovernanceAIRecommendationListRead(BaseModel):
    items: list[GovernanceAIRecommendationRead] = Field(default_factory=list)
    rule_based: list[GovernanceRuleBasedRecommendationRead] = Field(default_factory=list)
    total: int = 0
    ai_enabled: bool = False
    can_generate: bool = False



class GovernanceKpisRead(BaseModel):
    open_actions: int
    overdue_actions: int
    open_escalations: int
    blocking_dependencies: int
    at_risk_items: int
    sla_adherence_pct: float


class GovernanceRegisterRowRead(BaseModel):
    project_id: UUID
    project_name: str
    scope_status: GovernanceScopeStatus | None = None
    scope_version: str | None = None
    open_dependencies: int = 0
    blocking_dependencies: int = 0
    open_actions: int = 0
    open_escalations: int = 0
    health: str


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


class ProjectDependencyListRead(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    dependency_type: GovernanceDependencyType
    owner_id: UUID | None
    due_date: date | None
    status: GovernanceDependencyStatus
    overdue_days: int = 0
    project_name: str | None = None
    owner_name: str | None = None


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
    client_summary: str | None = None
    client_visible: bool = False
    client_published_at: datetime | None = None
    provenance_source_type: Literal["manual", "ai_recommendation", "delivery_risk", "other"] = (
        "manual"
    )
    source_recommendation_id: UUID | None = None
    source_recommendation_title: str | None = None
    source_conversion_id: UUID | None = None
    evidence_link_count: int = 0
    has_ai_source: bool = False


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
    client_summary: str | None = Field(default=None, max_length=4000)


class PromoteRiskAlertRequest(BaseModel):
    risk_alert_id: UUID


class PublishClientEscalationSummaryRequest(BaseModel):
    client_summary: str = Field(min_length=1, max_length=4000)
    client_visible: bool = True


class GovernanceEscalationListRead(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    severity: GovernanceEscalationSeverity
    status: GovernanceEscalationStatus
    raised_at: datetime
    source_type: GovernanceEscalationSourceType | None = None
    source_id: UUID | None = None
    project_name: str | None = None
    raised_by_name: str | None = None
    assigned_to_name: str | None = None
    description: str | None = None
    client_summary: str | None = None
    client_visible: bool = False
    client_published_at: datetime | None = None


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
    provenance_source_type: Literal["manual", "ai_recommendation", "delivery_risk", "other"] = (
        "manual"
    )
    source_recommendation_id: UUID | None = None
    source_recommendation_title: str | None = None
    source_conversion_id: UUID | None = None
    evidence_link_count: int = 0
    has_ai_source: bool = False


class GovernanceActionCreate(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceActionStatus = GovernanceActionStatus.OPEN
    linked_knowledge_document_id: UUID | None = None


class GovernanceActionListRead(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    owner_id: UUID | None
    due_date: date | None
    status: GovernanceActionStatus
    project_name: str | None = None
    owner_name: str | None = None


class GovernanceActionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    status: GovernanceActionStatus | None = None
    completed_at: datetime | None = None
    linked_knowledge_document_id: UUID | None = None


class GovernanceRecommendationConversionRead(BaseModel):
    id: UUID
    recommendation_id: UUID
    conversion_target: GovernanceRecommendationConversionTarget
    suggested_action_index: int
    created_action_id: UUID | None = None
    created_escalation_id: UUID | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime
    note: str | None = None
    idempotent_reuse: bool = False
    created_action: GovernanceActionRead | None = None
    created_escalation: GovernanceEscalationRead | None = None
    updated_recommendation: GovernanceAIRecommendationRead | None = None


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
    knowledge_version_id: UUID | None = None
    visibility: KnowledgeVisibility
    approved_by: UUID | None
    approved_at: datetime | None
    publication_status: GovernanceCharterPublicationStatus = (
        GovernanceCharterPublicationStatus.NOT_PUBLISHED
    )
    published_at: datetime | None = None
    published_by: UUID | None = None
    publication_error: str | None = None
    publication_attempt_count: int = 0
    last_publication_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    evidence_links: list[GovernanceEvidenceLinkRead] = Field(default_factory=list)
    approved_by_name: str | None = None
    published_by_name: str | None = None
    project_name: str | None = None
    knowledge_url: str | None = None


class CharterPublicationActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class CharterPublicationStatusRead(BaseModel):
    charter_id: UUID
    publication_status: GovernanceCharterPublicationStatus
    knowledge_document_id: UUID | None = None
    knowledge_version_id: UUID | None = None
    published_at: datetime | None = None
    published_by: UUID | None = None
    published_by_name: str | None = None
    publication_error: str | None = None
    publication_attempt_count: int = 0
    last_publication_attempt_at: datetime | None = None
    knowledge_url: str | None = None
    charter_status: GovernanceCharterStatus
    charter_version: str


class CharterKnowledgeLinkRead(CharterPublicationStatusRead):
    project_name: str | None = None
    knowledge_document_title: str | None = None
    view_document_url: str | None = None
    open_in_knowledge_url: str | None = None


class CharterPublicationVersionRead(BaseModel):
    charter_id: UUID
    charter_version: str
    charter_status: GovernanceCharterStatus
    publication_status: GovernanceCharterPublicationStatus
    knowledge_document_id: UUID | None = None
    knowledge_version_id: UUID | None = None
    knowledge_version: str | None = None
    created_at: datetime
    published_at: datetime | None = None
    published_by: UUID | None = None
    published_by_name: str | None = None
    approval_date: datetime | None = None
    knowledge_url: str | None = None


class CharterPublicationEventRead(ORMModel):
    id: UUID
    org_id: UUID
    charter_id: UUID
    project_id: UUID
    event_type: GovernanceCharterPublicationEventType
    actor_user_id: UUID | None = None
    knowledge_document_id: UUID | None = None
    knowledge_version_id: UUID | None = None
    previous_knowledge_version_id: UUID | None = None
    charter_version: str | None = None
    reason: str | None = None
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class GovernanceKnowledgeDocumentRef(BaseModel):
    document_id: UUID
    title: str
    project: str | None
    department: str | None = None
    version: str
    status: str
    visibility: str
    source_type: str


class GovernanceBootstrapRead(BaseModel):
    kpis: GovernanceKpisRead
    dependencies: list[ProjectDependencyRead] = Field(default_factory=list)
    escalations: list[GovernanceEscalationRead] = Field(default_factory=list)
    actions: list[GovernanceActionRead] = Field(default_factory=list)
    scope_states: list[ProjectScopeStateRead] = Field(default_factory=list)


class GovernanceEvidenceRead(BaseModel):
    source_type: str
    source_id: str | None = None
    label: str
    detail: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None


class GovernanceInsightRead(BaseModel):
    title: str
    detail: str
    severity: str
    evidence: list[GovernanceEvidenceRead] = Field(default_factory=list)


class GovernanceRecommendationRead(BaseModel):
    title: str
    detail: str
    priority: str
    project_id: UUID | None = None
    project_name: str | None = None
    evidence: list[GovernanceEvidenceRead] = Field(default_factory=list)


class GovernanceHealthProjectRead(BaseModel):
    project_id: UUID
    project_name: str
    score: int
    risk_level: str
    priority: int
    blocking_dependencies: int
    open_dependencies: int
    open_escalations: int
    critical_escalations: int
    overdue_actions: int
    pending_scope_revisions: int
    delivery_confidence: float | None = None
    delivery_traffic_light: str | None = None
    quality_risk: str | None = None
    workforce_risk: str | None = None
    trend: str
    vertical: str | None = None
    evidence: list[GovernanceEvidenceRead] = Field(default_factory=list)


class GovernanceChartPointRead(BaseModel):
    label: str
    value: float
    secondary_value: float | None = None


class GovernanceInsightsKpisRead(BaseModel):
    portfolio_governance_score: float
    projects_at_risk: int = 0
    recommendation_acceptance_rate_pct: float = 0.0
    recommendation_dismissal_rate_pct: float = 0.0
    escalations_created: int = 0
    recommendations_created: int = 0
    sla_adherence_pct: float = 0.0


class GovernanceRiskHeatmapCellRead(BaseModel):
    vertical: str
    risk_level: str
    project_count: int
    avg_score: float


class GovernanceNamedCountRead(BaseModel):
    label: str
    count: int
    project_id: UUID | None = None
    project_name: str | None = None
    vertical: str | None = None
    detail: str | None = None


class GovernanceAnalyticsRead(BaseModel):
    generated_at: datetime
    date_range_days: int
    project_health: list[GovernanceHealthProjectRead]
    portfolio_risk_ranking: list[GovernanceHealthProjectRead]
    insights: list[GovernanceInsightRead]
    recommendations: list[GovernanceRecommendationRead]
    charts: dict[str, list[GovernanceChartPointRead]]
    recent_activity: list[GovernanceEvidenceRead] = Field(default_factory=list)
    export_sections: list[str] = Field(default_factory=list)
    portfolio_governance_score: float | None = None
    insights_kpis: GovernanceInsightsKpisRead | None = None
    top_governance_risks: list[GovernanceNamedCountRead] = Field(default_factory=list)
    top_recurring_blockers: list[GovernanceNamedCountRead] = Field(default_factory=list)
    top_recurring_mitigation_failures: list[GovernanceNamedCountRead] = Field(
        default_factory=list
    )
    most_affected_projects: list[GovernanceNamedCountRead] = Field(default_factory=list)
    most_affected_departments: list[GovernanceNamedCountRead] = Field(default_factory=list)
    risk_heatmap: list[GovernanceRiskHeatmapCellRead] = Field(default_factory=list)


class GovernanceAnalyticsSummaryRead(BaseModel):
    generated_at: datetime
    date_range_days: int
    project_health: list[GovernanceHealthProjectRead] = Field(default_factory=list)
    portfolio_risk_ranking: list[GovernanceHealthProjectRead] = Field(default_factory=list)
    charts: dict[str, list[GovernanceChartPointRead]] = Field(default_factory=dict)
    export_sections: list[str] = Field(default_factory=list)
    portfolio_governance_score: float | None = None
    insights_kpis: GovernanceInsightsKpisRead | None = None


class GovernanceAnalyticsDetailRead(BaseModel):
    generated_at: datetime
    date_range_days: int
    insights: list[GovernanceInsightRead] = Field(default_factory=list)
    recommendations: list[GovernanceRecommendationRead] = Field(default_factory=list)
    charts: dict[str, list[GovernanceChartPointRead]] = Field(default_factory=dict)
    recent_activity: list[GovernanceEvidenceRead] = Field(default_factory=list)
    export_sections: list[str] = Field(default_factory=list)
    insights_kpis: GovernanceInsightsKpisRead | None = None
    top_governance_risks: list[GovernanceNamedCountRead] = Field(default_factory=list)
    top_recurring_blockers: list[GovernanceNamedCountRead] = Field(default_factory=list)
    top_recurring_mitigation_failures: list[GovernanceNamedCountRead] = Field(
        default_factory=list
    )
    most_affected_projects: list[GovernanceNamedCountRead] = Field(default_factory=list)
    most_affected_departments: list[GovernanceNamedCountRead] = Field(default_factory=list)
    risk_heatmap: list[GovernanceRiskHeatmapCellRead] = Field(default_factory=list)


class GovernanceMonitoringRead(BaseModel):
    generated_at: datetime
    window_hours: int
    audit_events: int
    chatbot_queries: int
    chatbot_latency_avg_ms: int | None = None
    chatbot_latency_p95_ms: int | None = None
    failed_or_empty_ai_answers: int
    dashboard_exports: int
    recent_event_types: dict[str, int] = Field(default_factory=dict)


# --- Phase 12: Recommendation Effectiveness ---


class GovernanceEffectivenessMetricRead(BaseModel):
    value: float | None = None
    numerator: int = 0
    denominator: int = 0
    null_reason: str | None = None


class GovernanceEffectivenessSummaryRead(BaseModel):
    generated_at: datetime
    date_range_days: int
    total_recommendations: int = 0
    reviewed: int = 0
    pending: int = 0
    acceptance_rate: GovernanceEffectivenessMetricRead
    dismissal_rate: GovernanceEffectivenessMetricRead
    conversion_rate: GovernanceEffectivenessMetricRead
    resolution_rate: GovernanceEffectivenessMetricRead
    false_positive_rate: GovernanceEffectivenessMetricRead
    average_quality_score: float | None = None
    median_time_to_review_seconds: float | None = None
    average_time_to_review_seconds: float | None = None
    median_time_to_convert_seconds: float | None = None
    average_time_to_convert_seconds: float | None = None
    median_time_to_resolve_seconds: float | None = None
    average_time_to_resolve_seconds: float | None = None
    recurrence_after_acceptance: int = 0
    recurrence_after_dismissal: int = 0
    metric_version: str = "v1"


class GovernanceEffectivenessFunnelRead(BaseModel):
    created: int = 0
    reviewed: int = 0
    accepted: int = 0
    dismissed: int = 0
    converted: int = 0
    resolved: int = 0


class GovernanceEffectivenessTrendPointRead(BaseModel):
    date: date
    created: int = 0
    reviewed: int = 0
    accepted: int = 0
    dismissed: int = 0
    converted: int = 0
    resolved: int = 0
    false_positives: int = 0
    average_quality_score: float | None = None
    recurrence_after_acceptance: int = 0
    recurrence_after_dismissal: int = 0


class GovernanceEffectivenessTrendsRead(BaseModel):
    points: list[GovernanceEffectivenessTrendPointRead] = Field(default_factory=list)


class GovernanceEffectivenessTimingRead(BaseModel):
    average_time_to_review_seconds: float | None = None
    median_time_to_review_seconds: float | None = None
    average_time_to_convert_seconds: float | None = None
    median_time_to_convert_seconds: float | None = None
    average_time_to_resolve_seconds: float | None = None
    median_time_to_resolve_seconds: float | None = None


class GovernanceEffectivenessQualityScoreRead(BaseModel):
    quality_score: float | None = None
    quality_band: str
    component_scores: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)
    data_completeness: float = 0.0
    score_version: str = "v1"
    provisional: bool = True


class GovernanceEffectivenessQualityRead(BaseModel):
    average_quality_score: float | None = None
    band_distribution: list[GovernanceNamedCountRead] = Field(default_factory=list)
    provisional_count: int = 0
    score_version: str = "v1"
    sample_scores: list[GovernanceEffectivenessQualityScoreRead] = Field(default_factory=list)


class GovernanceEffectivenessCalibrationRead(BaseModel):
    calibrated_confidence: float | None = None
    confidence_band: str
    calibration_version: str = "v1"
    observed_success_rate: float | None = None
    calibration_gap: float | None = None
    expected_calibration_error: float | None = None
    brier_score: float | None = None
    sample_size: int = 0
    min_sample: int = 0
    insufficient_history: bool = False
    fallback_to_original: bool = True


class GovernanceEffectivenessCategoryStatRead(BaseModel):
    category_key: str
    trigger_type: str
    severity: str
    confidence_band: str
    vertical: str
    explanation_version: str
    sample_size: int
    acceptance_rate: GovernanceEffectivenessMetricRead
    dismissal_rate: GovernanceEffectivenessMetricRead
    conversion_rate: GovernanceEffectivenessMetricRead
    resolution_rate: GovernanceEffectivenessMetricRead
    false_positive_rate: GovernanceEffectivenessMetricRead
    recurrence_after_acceptance: int = 0
    recurrence_after_dismissal: int = 0
    successful: bool = False


class GovernanceEffectivenessFalsePositiveRead(BaseModel):
    confirmed: int = 0
    likely: int = 0
    not_false_positive: int = 0
    insufficient_evidence: int = 0
    rate: GovernanceEffectivenessMetricRead
    categories: list[GovernanceEffectivenessCategoryStatRead] = Field(default_factory=list)


class GovernanceEffectivenessRecurrenceRead(BaseModel):
    after_acceptance: int = 0
    after_dismissal: int = 0
    recurring_recommendations: list[GovernanceNamedCountRead] = Field(default_factory=list)


class GovernanceEffectivenessDrilldownItemRead(BaseModel):
    recommendation_id: UUID
    title: str
    project_id: UUID | None = None
    project_name: str | None = None
    vertical: str | None = None
    trigger_type: str | None = None
    status: str
    acceptance_status: str
    confidence: float | None = None
    calibrated_confidence: float | None = None
    quality_score: float | None = None
    quality_band: str | None = None
    false_positive_status: str | None = None
    generated_at: datetime | None = None


class GovernanceEffectivenessDrilldownRead(BaseModel):
    items: list[GovernanceEffectivenessDrilldownItemRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 25
    offset: int = 0


class GovernanceRecommendationLifecycleEventRead(BaseModel):
    id: UUID
    recommendation_id: UUID
    event_type: str
    actor_user_id: UUID | None = None
    conversion_target: str | None = None
    conversion_target_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class GovernanceEffectivenessReportRead(BaseModel):
    generated_at: datetime
    date_range_days: int
    filters: dict[str, Any] = Field(default_factory=dict)
    sample_sizes: dict[str, int] = Field(default_factory=dict)
    summary: GovernanceEffectivenessSummaryRead
    calibration: GovernanceEffectivenessCalibrationRead
    quality: GovernanceEffectivenessQualityRead
    funnel: GovernanceEffectivenessFunnelRead
    warnings: list[str] = Field(default_factory=list)
    recommended_review_actions: list[str] = Field(default_factory=list)
    metric_definitions: dict[str, str] = Field(default_factory=dict)
    calculation_versions: dict[str, str] = Field(default_factory=dict)
    data_completeness: float = 0.0


class GovernanceStructuredFeedbackRequest(BaseModel):
    helpful: bool | None = None
    accurate: bool | None = None
    useful: bool | None = None
    actionable: bool | None = None
    clear: bool | None = None
    missing_evidence: bool = False
    duplicate: bool = False
    already_handled: bool = False
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)


class GovernanceStructuredFeedbackRead(BaseModel):
    id: UUID
    recommendation_id: UUID
    helpful: bool | None = None
    accurate: bool | None = None
    useful: bool | None = None
    actionable: bool | None = None
    clear: bool | None = None
    missing_evidence: bool = False
    duplicate: bool = False
    already_handled: bool = False
    rating: int | None = None
    comment: str | None = None
    reason: str | None = None
    feedback_version: str = "v1"
    created_at: datetime


# ---------------------------------------------------------------------------
# Phase 13 — Controlled Recommendation Optimization
# ---------------------------------------------------------------------------


class GovernanceOptimizationFilters(BaseModel):
    days: int = 30
    project_id: UUID | None = None
    vertical: str | None = None
    trigger_type: str | None = None
    strategy_version: str | None = None
    learning_rule_id: UUID | None = None
    quality_band: str | None = None
    confidence_band: str | None = None
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class GovernanceRecommendationConvertRequest(BaseModel):
    target: GovernanceRecommendationConversionTarget
    project_id: UUID
    suggested_action_index: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=120)


class GovernanceRecommendationResolveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class GovernanceRecommendationReopenRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class GovernanceRecommendationCancelResolutionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class GovernanceRecommendationChangeConversionTargetRequest(BaseModel):
    target: GovernanceRecommendationConversionTarget
    target_id: UUID
    note: str | None = Field(default=None, max_length=500)


class GovernanceRecommendationLifecycleActionRead(BaseModel):
    recommendation_id: UUID
    event_type: str
    conversion_target: str | None = None
    conversion_target_id: UUID | None = None
    resolved_at: datetime | None = None
    reopened_at: datetime | None = None
    message: str


class GovernanceLearningRuleRead(BaseModel):
    id: UUID
    org_id: UUID
    rule_type: str
    rule_payload: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    status: str
    evaluation_mode: str = "none"
    change_summary: str | None = None
    approved_at: datetime | None = None
    activated_at: datetime | None = None
    reverted_at: datetime | None = None
    disabled_at: datetime | None = None
    shadow_evaluation_id: UUID | None = None
    supersedes_rule_id: UUID | None = None
    performance_before: dict[str, Any] | None = None
    performance_after: dict[str, Any] | None = None
    allowed_effects: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None


class GovernanceLearningRuleApproveRequest(BaseModel):
    activate: bool = False


class GovernanceLearningRuleRollbackRequest(BaseModel):
    disable_only: bool = False


class GovernanceOptimizationDriftAlertRead(BaseModel):
    id: UUID | None = None
    alert_type: str
    severity: str
    metric_name: str
    baseline_value: float | None = None
    current_value: float | None = None
    threshold_value: float | None = None
    message: str
    strategy_version: str | None = None
    created_at: datetime


class GovernanceOptimizationDriftRead(BaseModel):
    window_days: int
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    current_metrics: dict[str, Any] = Field(default_factory=dict)
    alerts: list[GovernanceOptimizationDriftAlertRead] = Field(default_factory=list)
    auto_remediation: bool = False


class GovernanceOptimizationStrategyRead(BaseModel):
    id: UUID
    strategy_version: str
    confidence_version: str
    quality_version: str
    explanation_version: str
    learning_rule_version: str | None = None
    is_active: bool = False
    change_summary: str | None = None
    activated_at: datetime | None = None
    created_at: datetime


class GovernanceOptimizationCompareRead(BaseModel):
    strategy_a: str
    strategy_b: str
    days: int
    metrics_a: dict[str, Any] = Field(default_factory=dict)
    metrics_b: dict[str, Any] = Field(default_factory=dict)
    deltas: dict[str, float | None] = Field(default_factory=dict)
    generated_at: datetime


class GovernanceOptimizationShadowRead(BaseModel):
    id: UUID
    learning_rule_id: UUID | None = None
    status: str
    sample_size: int = 0
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    shadow_metrics: dict[str, Any] = Field(default_factory=dict)
    comparison_summary: dict[str, Any] = Field(default_factory=dict)
    expected_impact: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class GovernanceOptimizationReportRead(BaseModel):
    id: UUID
    period: str
    period_start: date
    period_end: date
    strategy_version: str | None = None
    report_payload: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class GovernanceOptimizationSummaryRead(BaseModel):
    generated_at: datetime
    filters: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    active_learning_rules: list[GovernanceLearningRuleRead] = Field(default_factory=list)
    pending_approvals: list[GovernanceLearningRuleRead] = Field(default_factory=list)
    recent_shadow_evaluations: list[GovernanceOptimizationShadowRead] = Field(default_factory=list)
    drift_warnings: list[GovernanceOptimizationDriftAlertRead] = Field(default_factory=list)
    strategy_versions: list[GovernanceOptimizationStrategyRead] = Field(default_factory=list)
    recent_reports: list[GovernanceOptimizationReportRead] = Field(default_factory=list)
    learning_rules_enabled: bool = False
