from datetime import date, datetime
from decimal import Decimal
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, desc, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.models.base import Base, CreatedAt, SoftDelete, UpdatedAt, UuidPrimaryKey


class AppRole(StrEnum):
    CLIENT = "client"
    DELIVERY_MANAGER = "delivery_manager"
    BSG_LEADERSHIP = "bsg_leadership"
    SUPER_ADMIN = "super_admin"


class DeliverySite(StrEnum):
    INDIA = "india"
    KOSOVO = "kosovo"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    RAMPING = "ramping"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MilestoneStatus(StrEnum):
    PENDING = "pending"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    COMPLETED = "completed"
    MISSED = "missed"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(StrEnum):
    DELIVERY_RISK = "delivery_risk"
    QUALITY_DRIFT = "quality_drift"
    MILESTONE_AT_RISK = "milestone_at_risk"
    WORKFORCE_IMBALANCE = "workforce_imbalance"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class RecommendationSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OwnerType(StrEnum):
    USER = "user"
    TEAM = "team"


class CommunicationStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SENT = "sent"
    REJECTED = "rejected"


class CommunicationType(StrEnum):
    WEEKLY_SUMMARY = "weekly_summary"
    EXECUTIVE_SUMMARY = "executive_summary"
    AD_HOC = "ad_hoc"


class NotificationType(StrEnum):
    RISK_ALERT = "risk_alert"
    COMMUNICATION_PENDING = "communication_pending"
    MILESTONE_AT_RISK = "milestone_at_risk"
    QUALITY_DRIFT_DETECTED = "quality_drift_detected"
    SKILL_GAP_DETECTED = "skill_gap_detected"
    CALIBRATION_REQUIRED = "calibration_required"
    SOP_AMBIGUITY_FLAGGED = "sop_ambiguity_flagged"
    SYSTEM = "system"



class SignalType(StrEnum):
    QUALITY_RISK = "quality_risk"
    SKILL_GAP = "skill_gap"
    QUALITY_ESCALATION = "quality_escalation"


class SignalStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    FAILED = "failed"


class ScanTrigger(StrEnum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"


class ScanStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeFolderKind(StrEnum):
    SOPS = "sops"
    GUIDES = "guides"
    HISTORIES = "histories"
    CUSTOM = "custom"


class KnowledgeSourceType(StrEnum):
    SOP = "sop"
    GUIDE = "guide"
    TRAINING_DOCUMENT = "training_document"
    PROJECT_CHARTER = "project_charter"
    ESCALATION_NOTE = "escalation_note"
    LESSON_LEARNED = "lesson_learned"


class KnowledgeVisibility(StrEnum):
    INTERNAL_ONLY = "internal_only"
    LEADERSHIP_ONLY = "leadership_only"
    RESTRICTED = "restricted"
    CLIENT_SAFE = "client_safe"


class KnowledgeDocumentStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED_FOR_REVIEW = "submitted_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REINDEX = "needs_reindex"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class KnowledgeIndexingStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class KnowledgeProcessingStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class KnowledgeIngestionJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeSuggestionStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    APPLIED = "applied"


class KnowledgeSuggestionType(StrEnum):
    MISSING_METADATA = "missing_metadata"
    BETTER_TITLE = "better_title"
    IMPROVED_SUMMARY = "improved_summary"
    MISSING_TAGS = "missing_tags"
    FOLDER_PLACEMENT = "folder_placement"
    SUGGESTED_DEPARTMENT = "suggested_department"
    SUGGESTED_PROJECT = "suggested_project"
    SUGGESTED_SOURCE_TYPE = "suggested_source_type"
    GAP_RESOLUTION = "gap_resolution"
    DUPLICATE = "duplicate"
    RETRIEVAL_QUALITY = "retrieval_quality"


class ProficiencyLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class SkillRequirementPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillCoverageStatus(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CertificationStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    PENDING_REVIEW = "pending_review"
    REVOKED = "revoked"


class TrainingRecordStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class TrainingGapType(StrEnum):
    MANDATORY_TRAINING_INCOMPLETE = "mandatory_training_incomplete"
    EXPIRED_OR_FAILED_TRAINING = "expired_or_failed_training"
    EXPIRED_CERTIFICATION = "expired_certification"
    PENDING_CERTIFICATION_REVIEW = "pending_certification_review"


class CapabilityGapType(StrEnum):
    SKILL_SHORTAGE = "skill_shortage"
    SME_SHORTAGE = "sme_shortage"
    CERTIFICATION_GAP = "certification_gap"
    TRAINING_GAP = "training_gap"
    UTILIZATION_OVERLOAD = "utilization_overload"
    UTILIZATION_UNDERLOAD = "utilization_underload"


class CapabilityGapSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CapabilityGapStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class KnowledgeExtractionStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class KnowledgeFeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"


class GovernanceScopeStatus(StrEnum):
    APPROVED = "approved"
    PENDING_REVISION = "pending_revision"
    LOCKED = "locked"


class GovernanceDependencyType(StrEnum):
    CLIENT_ACTION = "client_action"
    INTERNAL = "internal"
    EXTERNAL = "external"


class GovernanceDependencyStatus(StrEnum):
    OPEN = "open"
    BLOCKING = "blocking"
    RESOLVED = "resolved"


class GovernanceEscalationSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GovernanceEscalationStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class GovernanceActionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class GovernanceSummaryStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class GovernanceJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"


class GovernanceCharterStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class GovernanceCharterPublicationStatus(StrEnum):
    NOT_PUBLISHED = "not_published"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class GovernanceCharterPublicationEventType(StrEnum):
    CHARTER_PUBLISHED = "charter_published"
    KNOWLEDGE_VERSION_CREATED = "knowledge_version_created"
    KNOWLEDGE_PUBLICATION_FAILED = "knowledge_publication_failed"
    KNOWLEDGE_REPUBLISHED = "knowledge_republished"
    KNOWLEDGE_PUBLICATION_RETRIED = "knowledge_publication_retried"
    KNOWLEDGE_VERSION_SUPERSEDED = "knowledge_version_superseded"
    ALREADY_PUBLISHED = "already_published"
    KNOWLEDGE_UNPUBLISHED = "knowledge_unpublished"


class GovernanceEvidenceSourceType(StrEnum):
    DEPENDENCY = "dependency"
    ESCALATION = "escalation"
    ACTION = "action"
    SCOPE_STATE = "scope_state"
    KNOWLEDGE_DOCUMENT = "knowledge_document"
    DELIVERY_SIGNAL = "delivery_signal"
    WEEKLY_SUMMARY = "weekly_summary"


class GovernanceEscalationSourceType(StrEnum):
    DELIVERY_RISK = "delivery_risk"
    KNOWLEDGE_DOCUMENT = "knowledge_document"
    QUALITY_RISK = "quality_risk"


class GovernanceAIRecommendationScope(StrEnum):
    PROJECT = "project"
    PORTFOLIO = "portfolio"


class GovernanceAIRecommendationType(StrEnum):
    DEPENDENCY_MITIGATION = "dependency_mitigation"
    ESCALATION_REQUIRED = "escalation_required"
    ACTION_FOLLOW_UP = "action_follow_up"
    SCOPE_CONTROL = "scope_control"
    DELIVERY_RISK = "delivery_risk"
    MILESTONE_RISK = "milestone_risk"
    OWNERSHIP_ALIGNMENT = "ownership_alignment"
    GOVERNANCE_CADENCE = "governance_cadence"
    PORTFOLIO_PATTERN = "portfolio_pattern"
    RESOURCE_OR_TEAM_SIGNAL = "resource_or_team_signal"
    GENERAL_GOVERNANCE = "general_governance"


class GovernanceAIRecommendationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GovernanceAIRecommendationStatus(StrEnum):
    ACTIVE = "active"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"
    GENERATION_FAILED = "generation_failed"
    STALE = "stale"
    SNOOZED = "snoozed"


class GovernanceEscalationTriggerType(StrEnum):
    OVERDUE_BLOCKING_DEPENDENCY = "overdue_blocking_dependency"
    REPEATED_OVERDUE_DEPENDENCY = "repeated_overdue_dependency"
    MULTIPLE_BLOCKING_DEPENDENCIES = "multiple_blocking_dependencies"
    CRITICAL_DELIVERY_RISK = "critical_delivery_risk"
    DECLINING_DELIVERY_CONFIDENCE = "declining_delivery_confidence"
    UNRESOLVED_SCOPE_RISK = "unresolved_scope_risk"
    OVERDUE_CRITICAL_ACTION = "overdue_critical_action"
    REPEATED_MITIGATION_FAILURE = "repeated_mitigation_failure"
    MILESTONE_AT_RISK = "milestone_at_risk"
    COMBINED_GOVERNANCE_RISK = "combined_governance_risk"


class GovernanceRecommendationAcceptanceStatus(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    ACCEPTED_AS_ACTION = "accepted_as_action"
    ACCEPTED_AS_ESCALATION = "accepted_as_escalation"


class GovernanceFalsePositiveStatus(StrEnum):
    CONFIRMED_FALSE_POSITIVE = "confirmed_false_positive"
    LIKELY_FALSE_POSITIVE = "likely_false_positive"
    NOT_FALSE_POSITIVE = "not_false_positive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class GovernanceRecommendationLifecycleEventType(StrEnum):
    CREATED = "created"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    CONVERTED = "converted"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    RESOLUTION_CANCELLED = "resolution_cancelled"
    CONVERSION_TARGET_CHANGED = "conversion_target_changed"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    FALSE_POSITIVE_CONFIRMED = "false_positive_confirmed"


class GovernanceLearningRuleStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SHADOW = "shadow"
    ACTIVE = "active"
    REVERTED = "reverted"
    REJECTED = "rejected"
    DISABLED = "disabled"


class GovernanceRecommendationShadowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GovernanceRecommendationEvaluationPeriod(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class GovernanceRecommendationDriftSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class GovernanceRecommendationConversionTarget(StrEnum):
    ACTION = "action"
    ESCALATION = "escalation"


class GovernanceRecordTargetType(StrEnum):
    ACTION = "action"
    ESCALATION = "escalation"


class GovernanceRecordEvidenceSourceType(StrEnum):
    AI_RECOMMENDATION = "ai_recommendation"
    PROJECT = "project"
    DEPENDENCY = "dependency"
    ESCALATION = "escalation"
    ACTION = "action"
    SCOPE_STATE = "scope_state"
    DELIVERY_SIGNAL = "delivery_signal"
    MILESTONE = "milestone"
    TREND = "trend"
    GOVERNANCE_METRIC = "governance_metric"
    RECENT_ACTIVITY = "recent_activity"


class GovernanceRecordLinkType(StrEnum):
    AI_RECOMMENDATION_SOURCE = "ai_recommendation_source"
    SUPPORTING_EVIDENCE = "supporting_evidence"
    CONVERTED_FROM = "converted_from"
    RELATED_DEPENDENCY = "related_dependency"
    RELATED_ESCALATION = "related_escalation"
    RELATED_ACTION = "related_action"
    RELATED_SCOPE_STATE = "related_scope_state"
    RELATED_DELIVERY_SIGNAL = "related_delivery_signal"


app_role = Enum(AppRole, name="app_role", values_callable=lambda x: [e.value for e in x])
delivery_site = Enum(DeliverySite, name="delivery_site", values_callable=lambda x: [e.value for e in x])
project_status = Enum(ProjectStatus, name="project_status", values_callable=lambda x: [e.value for e in x])
milestone_status = Enum(MilestoneStatus, name="milestone_status", values_callable=lambda x: [e.value for e in x])
risk_tier = Enum(RiskTier, name="risk_tier", values_callable=lambda x: [e.value for e in x])
alert_type = Enum(AlertType, name="alert_type", values_callable=lambda x: [e.value for e in x])
alert_status = Enum(AlertStatus, name="alert_status", values_callable=lambda x: [e.value for e in x])
recommendation_severity = Enum(
    RecommendationSeverity,
    name="recommendation_severity",
    values_callable=lambda x: [e.value for e in x],
)
recommendation_status = Enum(
    RecommendationStatus,
    name="recommendation_status",
    values_callable=lambda x: [e.value for e in x],
)
owner_type = Enum(OwnerType, name="owner_type", values_callable=lambda x: [e.value for e in x])
communication_status = Enum(
    CommunicationStatus,
    name="communication_status",
    values_callable=lambda x: [e.value for e in x],
)
communication_type = Enum(
    CommunicationType,
    name="communication_type",
    values_callable=lambda x: [e.value for e in x],
)
notification_type = Enum(
    NotificationType,
    name="notification_type",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_folder_kind = Enum(
    KnowledgeFolderKind,
    name="knowledge_folder_kind",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_source_type = Enum(
    KnowledgeSourceType,
    name="knowledge_source_type",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_visibility = Enum(
    KnowledgeVisibility,
    name="knowledge_visibility",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_document_status = Enum(
    KnowledgeDocumentStatus,
    name="knowledge_document_status",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_indexing_status = Enum(
    KnowledgeIndexingStatus,
    name="knowledge_indexing_status",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_processing_status = Enum(
    KnowledgeProcessingStatus,
    name="knowledge_processing_status",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_ingestion_job_status = Enum(
    KnowledgeIngestionJobStatus,
    name="knowledge_ingestion_job_status",
    values_callable=lambda x: [e.value for e in x],
    native_enum=False,
)
knowledge_extraction_status = Enum(
    KnowledgeExtractionStatus,
    name="knowledge_extraction_status",
    values_callable=lambda x: [e.value for e in x],
)
knowledge_feedback_rating = Enum(
    KnowledgeFeedbackRating,
    name="knowledge_feedback_rating",
    values_callable=lambda x: [e.value for e in x],
)
governance_scope_status = Enum(
    GovernanceScopeStatus,
    name="governance_scope_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_dependency_type = Enum(
    GovernanceDependencyType,
    name="governance_dependency_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_dependency_status = Enum(
    GovernanceDependencyStatus,
    name="governance_dependency_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_escalation_severity = Enum(
    GovernanceEscalationSeverity,
    name="governance_escalation_severity",
    values_callable=lambda x: [e.value for e in x],
)
governance_escalation_status = Enum(
    GovernanceEscalationStatus,
    name="governance_escalation_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_action_status = Enum(
    GovernanceActionStatus,
    name="governance_action_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_summary_status = Enum(
    GovernanceSummaryStatus,
    name="governance_summary_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_job_status = Enum(
    GovernanceJobStatus,
    name="governance_job_status",
    values_callable=lambda x: [e.value for e in x],
    native_enum=False,
)
governance_charter_status = Enum(
    GovernanceCharterStatus,
    name="governance_charter_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_charter_publication_status = Enum(
    GovernanceCharterPublicationStatus,
    name="governance_charter_publication_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_charter_publication_event_type = Enum(
    GovernanceCharterPublicationEventType,
    name="governance_charter_publication_event_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_evidence_source_type = Enum(
    GovernanceEvidenceSourceType,
    name="governance_evidence_source_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_escalation_source_type = Enum(
    GovernanceEscalationSourceType,
    name="governance_escalation_source_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_ai_recommendation_scope = Enum(
    GovernanceAIRecommendationScope,
    name="governance_ai_recommendation_scope",
    values_callable=lambda x: [e.value for e in x],
)
governance_ai_recommendation_type = Enum(
    GovernanceAIRecommendationType,
    name="governance_ai_recommendation_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_ai_recommendation_priority = Enum(
    GovernanceAIRecommendationPriority,
    name="governance_ai_recommendation_priority",
    values_callable=lambda x: [e.value for e in x],
)
governance_ai_recommendation_status = Enum(
    GovernanceAIRecommendationStatus,
    name="governance_ai_recommendation_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_escalation_trigger_type = Enum(
    GovernanceEscalationTriggerType,
    name="governance_escalation_trigger_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_recommendation_acceptance_status = Enum(
    GovernanceRecommendationAcceptanceStatus,
    name="governance_recommendation_acceptance_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_recommendation_conversion_target = Enum(
    GovernanceRecommendationConversionTarget,
    name="governance_recommendation_conversion_target",
    values_callable=lambda x: [e.value for e in x],
)
governance_false_positive_status = Enum(
    GovernanceFalsePositiveStatus,
    name="governance_false_positive_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_recommendation_lifecycle_event_type = Enum(
    GovernanceRecommendationLifecycleEventType,
    name="governance_recommendation_lifecycle_event_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_learning_rule_status = Enum(
    GovernanceLearningRuleStatus,
    name="governance_learning_rule_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_recommendation_shadow_status = Enum(
    GovernanceRecommendationShadowStatus,
    name="governance_recommendation_shadow_status",
    values_callable=lambda x: [e.value for e in x],
)
governance_recommendation_evaluation_period = Enum(
    GovernanceRecommendationEvaluationPeriod,
    name="governance_recommendation_evaluation_period",
    values_callable=lambda x: [e.value for e in x],
)
governance_recommendation_drift_severity = Enum(
    GovernanceRecommendationDriftSeverity,
    name="governance_recommendation_drift_severity",
    values_callable=lambda x: [e.value for e in x],
)
governance_record_target_type = Enum(
    GovernanceRecordTargetType,
    name="governance_record_target_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_record_evidence_source_type = Enum(
    GovernanceRecordEvidenceSourceType,
    name="governance_record_evidence_source_type",
    values_callable=lambda x: [e.value for e in x],
)
governance_record_link_type = Enum(
    GovernanceRecordLinkType,
    name="governance_record_link_type",
    values_callable=lambda x: [e.value for e in x],
)


class VectorType(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect):  # type: ignore[no-untyped-def]
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, dialect, coltype):  # type: ignore[no-untyped-def]
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            text = str(value).strip().strip("[]")
            if not text:
                return []
            return [float(item) for item in text.split(",")]

        return process


class Organisation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    vertical: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class User(Base, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "users"
    __table_args__ = (Index("users_org_id_idx", "org_id"), Index("users_role_idx", "role"))

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    email: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[AppRole] = mapped_column(app_role)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Program(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    """Client-facing 'Project' container; child scopes live in `projects`."""

    __tablename__ = "programs"
    __table_args__ = (Index("programs_org_id_idx", "org_id"),)

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Project(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "projects"
    __table_args__ = (
        Index("projects_org_id_idx", "org_id"),
        Index("projects_status_idx", "status"),
        Index("projects_program_id_idx", "program_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    program_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    vertical: Mapped[str] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(project_status, default=ProjectStatus.ACTIVE)
    start_date: Mapped[date] = mapped_column(Date)
    target_end_date: Mapped[date] = mapped_column(Date)
    actual_end_date: Mapped[date | None] = mapped_column(Date)
    daily_target_units: Mapped[int | None] = mapped_column(Integer)


class ProjectAssignment(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "project_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="project_assignments_user_project_key"),
        Index("project_assignments_user_id_idx", "user_id"),
        Index("project_assignments_project_id_idx", "project_id"),
        Index("project_assignments_org_id_idx", "org_id"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Milestone(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "milestones"
    __table_args__ = (
        Index("milestones_project_id_idx", "project_id"),
        Index("milestones_org_id_idx", "org_id"),
        Index("milestones_planned_date_idx", "planned_date"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    planned_date: Mapped[date] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[MilestoneStatus] = mapped_column(milestone_status, default=MilestoneStatus.PENDING)


class ThroughputSnapshot(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "throughput_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "snapshot_date", name="throughput_snapshots_project_date_key"),
        Index("throughput_snapshots_project_id_date_idx", "project_id", "snapshot_date"),
        Index("throughput_snapshots_org_id_idx", "org_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    units_completed: Mapped[int] = mapped_column(Integer)
    units_forecast: Mapped[int | None] = mapped_column(Integer)
    rolling_7day_units: Mapped[int | None] = mapped_column(Integer)


class Team(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "teams"
    __table_args__ = (Index("teams_project_id_idx", "project_id"), Index("teams_org_id_idx", "org_id"))

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    site: Mapped[DeliverySite] = mapped_column(delivery_site)
    domain: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Annotator(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "annotators"
    __table_args__ = (
        Index("annotators_team_active_deleted_idx", "team_id", "is_active", "deleted_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)
    full_name: Mapped[str] = mapped_column(Text)
    site: Mapped[DeliverySite] = mapped_column(delivery_site)
    is_sme_certified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class UtilizationSnapshot(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "utilization_snapshots"
    __table_args__ = (
        Index("utilization_snapshots_org_id_idx", "org_id"),
        Index("utilization_snapshots_project_id_idx", "project_id"),
        Index("utilization_snapshots_team_id_idx", "team_id"),
        Index("utilization_snapshots_annotator_id_idx", "annotator_id"),
        Index("utilization_snapshots_snapshot_date_idx", "snapshot_date"),
        Index("utilization_snapshots_project_id_date_idx", "project_id", "snapshot_date"),
        Index("utilization_snapshots_team_id_date_idx", "team_id", "snapshot_date"),
        Index(
            "utilization_snapshots_project_team_annotator_deleted_date_idx",
            "project_id",
            "team_id",
            "annotator_id",
            "deleted_at",
            "snapshot_date",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    annotator_id: Mapped[UUID | None] = mapped_column(ForeignKey("annotators.id", ondelete="SET NULL"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    allocated_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    available_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    utilization_pct: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    billable_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    non_billable_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)


class Skill(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "skills"
    __table_args__ = (
        Index("skills_org_id_idx", "org_id"),
        Index("skills_name_idx", "name"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AnnotatorSkill(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "annotator_skills"
    __table_args__ = (
        Index("annotator_skills_org_id_idx", "org_id"),
        Index("annotator_skills_annotator_id_idx", "annotator_id"),
        Index("annotator_skills_skill_id_idx", "skill_id"),
        Index("annotator_skills_annotator_skill_deleted_idx", "annotator_id", "skill_id", "deleted_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="RESTRICT"))
    proficiency_level: Mapped[ProficiencyLevel] = mapped_column(Text)
    verified_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectSkillRequirement(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "project_skill_requirements"
    __table_args__ = (
        Index("project_skill_requirements_org_id_idx", "org_id"),
        Index("project_skill_requirements_project_id_idx", "project_id"),
        Index("project_skill_requirements_skill_id_idx", "skill_id"),
        Index("project_skill_requirements_project_deleted_idx", "project_id", "deleted_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="RESTRICT"))
    required_proficiency_level: Mapped[ProficiencyLevel] = mapped_column(Text)
    required_headcount: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    required_sme_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    priority: Mapped[SkillRequirementPriority] = mapped_column(Text, default=SkillRequirementPriority.MEDIUM)


class Certification(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "certifications"
    __table_args__ = (
        Index("certifications_org_id_idx", "org_id"),
        Index("certifications_name_idx", "name"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    issuing_body: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    validity_months: Mapped[int | None] = mapped_column(Integer)
    is_required_for_sme: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class EmployeeCertification(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "employee_certifications"
    __table_args__ = (
        Index("employee_certifications_org_id_idx", "org_id"),
        Index("employee_certifications_annotator_id_idx", "annotator_id"),
        Index("employee_certifications_certification_id_idx", "certification_id"),
        Index("employee_certifications_expires_at_idx", "expires_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    certification_id: Mapped[UUID] = mapped_column(ForeignKey("certifications.id", ondelete="RESTRICT"))
    issued_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[CertificationStatus] = mapped_column(Text, default=CertificationStatus.ACTIVE)
    evidence_url: Mapped[str | None] = mapped_column(Text)


class TrainingProgram(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "training_programs"
    __table_args__ = (
        Index("training_programs_org_id_idx", "org_id"),
        Index("training_programs_skill_id_idx", "skill_id"),
        Index("training_programs_name_idx", "name"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    skill_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    required_for_skill_level: Mapped[ProficiencyLevel | None] = mapped_column(Text)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    knowledge_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"),
    )


class TrainingRecord(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "training_records"
    __table_args__ = (
        Index("training_records_org_id_idx", "org_id"),
        Index("training_records_annotator_id_idx", "annotator_id"),
        Index("training_records_training_program_id_idx", "training_program_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    training_program_id: Mapped[UUID] = mapped_column(ForeignKey("training_programs.id", ondelete="RESTRICT"))
    status: Mapped[TrainingRecordStatus] = mapped_column(Text, default=TrainingRecordStatus.NOT_STARTED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class CapabilityGap(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "capability_gaps"
    __table_args__ = (
        Index("capability_gaps_org_id_idx", "org_id"),
        Index("capability_gaps_project_id_idx", "project_id"),
        Index("capability_gaps_team_id_idx", "team_id"),
        Index("capability_gaps_skill_id_idx", "skill_id"),
        Index("capability_gaps_gap_type_idx", "gap_type"),
        Index("capability_gaps_severity_idx", "severity"),
        Index("capability_gaps_status_idx", "status"),
        Index("capability_gaps_detected_at_idx", "detected_at"),
        Index(
            "capability_gaps_project_status_severity_deleted_idx",
            "project_id",
            "status",
            "severity",
            "deleted_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    skill_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))
    gap_type: Mapped[CapabilityGapType] = mapped_column(Text)
    severity: Mapped[CapabilityGapSeverity] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[CapabilityGapStatus] = mapped_column(Text, default=CapabilityGapStatus.OPEN)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QualitySnapshot(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "quality_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "team_id", "iso_year", "iso_week", name="quality_snapshots_project_team_week_key"),
        Index("quality_snapshots_project_id_idx", "project_id"),
        Index("quality_snapshots_org_id_idx", "org_id"),
        Index("quality_snapshots_week_idx", "iso_year", "iso_week"),
        Index(
            "quality_snapshots_project_week_idx",
            "project_id",
            desc("iso_year"),
            desc("iso_week"),
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    iso_week: Mapped[int] = mapped_column(Integer)
    iso_year: Mapped[int] = mapped_column(Integer)
    gold_set_accuracy_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    iaa_krippendorff_alpha: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    rework_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    evaluated_item_count: Mapped[int | None] = mapped_column(Integer)
    has_drift_alert: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    drift_alert_detail: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence_level: Mapped[str | None] = mapped_column(Text)


class QualityErrorCategory(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "quality_error_categories"

    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    severity_weight: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class QualityErrorEntry(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "quality_error_entries"

    quality_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("quality_snapshots.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    error_category: Mapped[str] = mapped_column(Text)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    recommended_action: Mapped[str | None] = mapped_column(Text)


class RiskAlert(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "risk_alerts"
    __table_args__ = (
        Index(
            "risk_alerts_project_type_status_deleted_idx",
            "project_id",
            "alert_type",
            "status",
            "deleted_at",
        ),
        Index(
            "risk_alerts_project_status_deleted_idx",
            "project_id",
            "status",
            "deleted_at",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    milestone_id: Mapped[UUID | None] = mapped_column(ForeignKey("milestones.id", ondelete="SET NULL"))
    alert_type: Mapped[AlertType] = mapped_column(alert_type)
    risk_tier: Mapped[RiskTier] = mapped_column(risk_tier)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    slippage_probability: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    contributing_causes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[AlertStatus] = mapped_column(alert_status, default=AlertStatus.OPEN)
    source_table: Mapped[str | None] = mapped_column(Text, index=True)
    source_row_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MitigationRecommendation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "mitigation_recommendations"
    __table_args__ = (
        Index("mitigation_recommendations_project_id_idx", "project_id"),
        Index("mitigation_recommendations_org_id_idx", "org_id"),
        Index("mitigation_recommendations_source_risk_id_idx", "source_risk_id"),
        Index("mitigation_recommendations_status_idx", "status"),
        Index(
            "mitigation_recommendations_project_source_risk_deleted_idx",
            "project_id",
            "source_risk_id",
            "deleted_at",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[RecommendationSeverity] = mapped_column(recommendation_severity)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    status: Mapped[RecommendationStatus] = mapped_column(
        recommendation_status,
        default=RecommendationStatus.PENDING,
    )
    owner_type: Mapped[OwnerType | None] = mapped_column(owner_type)
    owner_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    source_risk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("risk_alerts.id", ondelete="SET NULL"),
    )


class Bottleneck(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "bottlenecks"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[AlertStatus] = mapped_column(alert_status, default=AlertStatus.OPEN)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ClientCommunication(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "client_communications"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    comm_type: Mapped[CommunicationType] = mapped_column(communication_type)
    subject: Mapped[str] = mapped_column(Text)
    body_draft: Mapped[str] = mapped_column(Text)
    body_approved: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CommunicationStatus] = mapped_column(communication_status, default=CommunicationStatus.DRAFT)
    drafted_by_agent: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_mode: Mapped[str | None] = mapped_column(Text)
    generation_warning: Mapped[str | None] = mapped_column(Text)


class CommunicationEvidenceLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "communication_evidence_links"

    communication_id: Mapped[UUID] = mapped_column(ForeignKey("client_communications.id", ondelete="CASCADE"), index=True)
    source_table: Mapped[str] = mapped_column(Text)
    source_row_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(Text)


class AgentQuery(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "agent_queries"
    __table_args__ = (
        Index("agent_queries_org_agent_created_idx", "org_id", "agent_name", "created_at"),
        Index("agent_queries_org_user_agent_project_created_idx", "org_id", "user_id", "agent_name", "project_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    agent_name: Mapped[str] = mapped_column(Text)
    query_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    retrieval_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_queries.id", ondelete="SET NULL"),
        index=True,
    )


class AgentQueryEvidenceLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "agent_query_evidence_links"

    agent_query_id: Mapped[UUID] = mapped_column(ForeignKey("agent_queries.id", ondelete="CASCADE"), index=True)
    source_table: Mapped[str] = mapped_column(Text)
    source_row_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(Text)


class DeliveryConversation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "delivery_conversations"
    __table_args__ = (
        Index("delivery_conversations_user_updated_idx", "user_id", "updated_at"),
        Index(
            "delivery_conversations_org_user_project_updated_idx",
            "org_id",
            "user_id",
            "project_id",
            "updated_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(Text, default="New conversation", server_default="New conversation")


class DeliveryMessage(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "delivery_messages"
    __table_args__ = (Index("delivery_messages_conversation_created_idx", "conversation_id", "created_at"),)

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("delivery_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    agent_query_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_queries.id", ondelete="SET NULL"),
        index=True,
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class ClientCsatScore(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "client_csat_scores"
    __table_args__ = (
        UniqueConstraint("project_id", "submitted_by", "reporting_period_month", name="client_csat_scores_project_user_month_key"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    score: Mapped[Decimal] = mapped_column(Numeric(2, 1))
    reporting_period_month: Mapped[date] = mapped_column(Date, index=True)
    comment: Mapped[str | None] = mapped_column(Text)


class MetricConfiguration(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "metric_configurations"
    __table_args__ = (
        Index(
            "metric_configurations_global_key_active_uidx",
            "metric_key",
            unique=True,
            postgresql_where=text("org_id IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "metric_configurations_org_key_active_uidx",
            "org_id",
            "metric_key",
            unique=True,
            postgresql_where=text("org_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    org_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    metric_key: Mapped[str] = mapped_column(Text)
    display_label: Mapped[str] = mapped_column(Text)
    is_client_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    description: Mapped[str | None] = mapped_column(Text)
    threshold_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class DeliveryConfidenceScore(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "delivery_confidence_scores"
    __table_args__ = (
        Index(
            "delivery_confidence_scores_project_created_idx",
            "project_id",
            desc("created_at"),
        ),
        Index(
            "delivery_confidence_scores_milestone_created_idx",
            "milestone_id",
            desc("created_at"),
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    milestone_id: Mapped[UUID] = mapped_column(ForeignKey("milestones.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    score_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    forecast_completion_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[MilestoneStatus] = mapped_column(milestone_status)
    model_version: Mapped[str | None] = mapped_column(Text)


class Notification(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "notifications"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    notification_type: Mapped[NotificationType] = mapped_column(notification_type)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    source_table: Mapped[str | None] = mapped_column(Text)
    source_row_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))



class QualityScanRun(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "quality_scan_runs"

    trigger: Mapped[ScanTrigger] = mapped_column(Text)
    triggered_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    status: Mapped[ScanStatus] = mapped_column(Text, default=ScanStatus.RUNNING)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    projects_scanned: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    snapshots_evaluated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    alerts_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    data_gaps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    per_project_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)


class KnowledgeLesson(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_lessons"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    linked_quality_event_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    linked_alert_id: Mapped[UUID | None] = mapped_column(ForeignKey("risk_alerts.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class SopDocument(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "sop_documents"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    content_text: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    effective_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ReviewerScorecard(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "reviewer_scorecards"
    __table_args__ = (
        UniqueConstraint("annotator_id", "project_id", "iso_year", "iso_week", name="reviewer_scorecards_unique_week"),
        Index("reviewer_scorecards_project_idx", "project_id"),
    )

    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    items_evaluated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    accuracy_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    error_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CalibrationBrief(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "calibration_briefs"
    __table_args__ = (
        UniqueConstraint("project_id", "iso_year", "iso_week", name="calibration_briefs_unique_week"),
        Index("calibration_briefs_project_idx", "project_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    candidates: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    brief_text: Mapped[str | None] = mapped_column(Text)
    signal_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GoldSetEvaluationLog(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "gold_set_evaluation_logs"

    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    item_id: Mapped[str] = mapped_column(Text)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    error_category: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IaaMeasurementRecord(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "iaa_measurement_records"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    reviewer_a_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    reviewer_b_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    task_type: Mapped[str | None] = mapped_column(Text)
    krippendorff_alpha: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)


class ReworkLog(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "rework_logs"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    annotator_id: Mapped[UUID | None] = mapped_column(ForeignKey("annotators.id", ondelete="SET NULL"))
    item_id: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    rework_date: Mapped[date] = mapped_column(Date)


class OnboardingRecord(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "onboarding_records"

    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    onboarding_date: Mapped[date] = mapped_column(Date)
    calibration_status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    notes: Mapped[str | None] = mapped_column(Text)


class SopVersionHistory(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "sop_version_history"

    sop_document_id: Mapped[UUID] = mapped_column(ForeignKey("sop_documents.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    version: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date] = mapped_column(Date)


class GoldSetMetadata(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "gold_set_metadata"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    version: Mapped[str] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QualityLessonLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "quality_lesson_links"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    quality_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("quality_snapshots.id", ondelete="SET NULL"))
    risk_alert_id: Mapped[UUID | None] = mapped_column(ForeignKey("risk_alerts.id", ondelete="SET NULL"))
    knowledge_lesson_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_lessons.id", ondelete="CASCADE"), index=True)


class QualitySopLink(Base, UuidPrimaryKey, CreatedAt):
    """Audit trail linking a quality SOP ambiguity event to a resolved SOP version (BR-09)."""

    __tablename__ = "quality_sop_links"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    risk_alert_id: Mapped[UUID] = mapped_column(ForeignKey("risk_alerts.id", ondelete="CASCADE"), index=True)
    sop_version_id: Mapped[UUID] = mapped_column(ForeignKey("sop_version_history.id", ondelete="CASCADE"), index=True)
    confirmed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class InterAgentSignal(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "inter_agent_signals"

    signal_type: Mapped[str] = mapped_column(Text, index=True)
    source_agent: Mapped[str] = mapped_column(Text, default="quality_intelligence_agent")
    target_agent: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(Text, default=SignalStatus.PENDING, server_default="pending", index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))


class WorkforceSkill(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "workforce_skills"
    __table_args__ = (
        UniqueConstraint("annotator_id", "skill_code", name="workforce_skills_annotator_skill_key"),
        Index("workforce_skills_annotator_id_idx", "annotator_id"),
        Index("workforce_skills_org_id_idx", "org_id"),
    )

    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    skill_code: Mapped[str] = mapped_column(Text)
    proficiency_level: Mapped[str] = mapped_column(Text)
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkforceUtilizationSnapshot(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "workforce_utilization_snapshots"
    __table_args__ = (
        UniqueConstraint("team_id", "iso_year", "iso_week", name="workforce_utilization_team_week_key"),
        Index("workforce_utilization_team_id_idx", "team_id"),
        Index("workforce_utilization_org_id_idx", "org_id"),
    )

    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    target_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    logged_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    utilization_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class KnowledgeFolder(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "knowledge_folders"
    __table_args__ = (
        Index("knowledge_folders_org_idx", "org_id"),
        Index("knowledge_folders_org_deleted_order_idx", "org_id", "deleted_at", "display_order"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    folder_kind: Mapped[KnowledgeFolderKind] = mapped_column(knowledge_folder_kind)
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class KnowledgeDocument(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("knowledge_documents_org_folder_idx", "org_id", "folder_id"),
        Index("knowledge_documents_retrieval_idx", "org_id", "status", "indexing_status", "visibility"),
        Index(
            "knowledge_documents_org_deleted_title_idx",
            "org_id",
            "deleted_at",
            "title",
        ),
        Index(
            "knowledge_documents_org_folder_deleted_title_idx",
            "org_id",
            "folder_id",
            "deleted_at",
            "title",
        ),
        Index(
            "knowledge_documents_org_uploaded_created_idx",
            "org_id",
            "uploaded_by",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "knowledge_documents_org_status_created_idx",
            "org_id",
            "status",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "knowledge_documents_org_document_type_created_idx",
            "org_id",
            "document_type",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "knowledge_documents_org_source_updated_idx",
            "org_id",
            "status",
            "source_type",
            "updated_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "knowledge_documents_retrieval_scope_idx",
            "org_id",
            "status",
            "indexing_status",
            "processing_status",
            "visibility",
            "project",
            "department",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    folder_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_folders.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[KnowledgeSourceType] = mapped_column(knowledge_source_type)
    document_type: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    visibility: Mapped[KnowledgeVisibility] = mapped_column(knowledge_visibility, default=KnowledgeVisibility.INTERNAL_ONLY)
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(knowledge_document_status, default=KnowledgeDocumentStatus.DRAFT)
    project: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    owner_approver: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    approver: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    file_name: Mapped[str] = mapped_column(Text)
    file_mime_type: Mapped[str] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_url: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    processing_error: Mapped[str | None] = mapped_column(Text)
    indexing_status: Mapped[KnowledgeIndexingStatus] = mapped_column(
        knowledge_indexing_status,
        default=KnowledgeIndexingStatus.NOT_INDEXED,
    )
    processing_status: Mapped[KnowledgeProcessingStatus] = mapped_column(
        knowledge_processing_status,
        default=KnowledgeProcessingStatus.UPLOADED,
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="SET NULL"))
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    upload_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    executive_summary: Mapped[str | None] = mapped_column(Text)
    key_procedures: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    important_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    affected_departments: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    related_document_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), default=list, server_default="{}")
    summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentVersion(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="knowledge_document_versions_document_version_key"),
        Index("knowledge_document_versions_document_idx", "document_id"),
        Index("knowledge_document_versions_active_idx", "document_id", "is_active"),
        Index("knowledge_document_versions_document_uploaded_idx", "document_id", "uploaded_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    file_mime_type: Mapped[str] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_url: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    supersedes_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="SET NULL"))
    superseded_by_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="SET NULL"))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDocumentApprovalEvent(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "knowledge_document_approval_events"
    __table_args__ = (
        Index("knowledge_document_approval_events_document_idx", "document_id", "created_at"),
        Index("knowledge_document_approval_events_org_idx", "org_id", "created_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class KnowledgeIngestionJob(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_ingestion_jobs"
    __table_args__ = (
        Index("knowledge_ingestion_jobs_status_idx", "status"),
        Index("knowledge_ingestion_jobs_document_id_idx", "document_id"),
        Index("knowledge_ingestion_jobs_next_retry_at_idx", "next_retry_at"),
        Index("knowledge_ingestion_jobs_document_created_idx", "document_id", "created_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="SET NULL"))
    status: Mapped[KnowledgeIngestionJobStatus] = mapped_column(
        knowledge_ingestion_job_status,
        default=KnowledgeIngestionJobStatus.PENDING,
    )
    progress_percentage: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_retries: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    extraction_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentExtraction(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_document_extractions"
    __table_args__ = (
        UniqueConstraint("version_id", name="knowledge_document_extractions_version_key"),
        Index("knowledge_document_extractions_document_idx", "document_id"),
        Index("knowledge_document_extractions_version_idx", "version_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    version_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[KnowledgeExtractionStatus] = mapped_column(
        knowledge_extraction_status,
        default=KnowledgeExtractionStatus.PENDING,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quality_score: Mapped[int | None] = mapped_column(Integer)


class KnowledgeDocumentChunk(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_document_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="knowledge_document_chunks_version_index_key"),
        Index("knowledge_document_chunks_document_idx", "document_id"),
        Index("knowledge_document_chunks_version_idx", "version_id"),
        Index("knowledge_document_chunks_document_version_index_idx", "document_id", "version_id", "chunk_index"),
        Index("knowledge_document_chunks_org_document_index_idx", "org_id", "document_id", "chunk_index"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    folder_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_folders.id", ondelete="RESTRICT"))
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)
    section_title: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    chunk_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[KnowledgeVisibility | None] = mapped_column(knowledge_visibility)
    project: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    chunk_type: Mapped[str] = mapped_column(Text, default="text", server_default="text")
    section_path: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(VectorType(1536))


class KnowledgeDocumentEmbedding(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "knowledge_document_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model", name="knowledge_document_embeddings_chunk_model_key"),
        Index("knowledge_document_embeddings_document_idx", "document_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_document_chunks.id", ondelete="CASCADE"))
    embedding_model: Mapped[str] = mapped_column(Text)
    embedding_dimensions: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[dict[str, Any]] = mapped_column(JSONB)


class KnowledgeEvidenceLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "knowledge_evidence_links"
    __table_args__ = (
        Index("knowledge_evidence_links_query_idx", "agent_query_id"),
        Index("knowledge_evidence_links_document_idx", "document_id"),
        Index("knowledge_evidence_links_query_document_idx", "agent_query_id", "document_id"),
        Index("knowledge_evidence_links_org_document_created_idx", "org_id", "document_id", "created_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    agent_query_id: Mapped[UUID] = mapped_column(ForeignKey("agent_queries.id", ondelete="CASCADE"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="RESTRICT"))
    chunk_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_chunks.id", ondelete="SET NULL"))
    citation_label: Mapped[str] = mapped_column(Text)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))


class KnowledgeQueryFeedback(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_query_feedback"
    __table_args__ = (
        UniqueConstraint("agent_query_id", "user_id", name="knowledge_query_feedback_query_user_key"),
        Index("knowledge_query_feedback_org_idx", "org_id"),
        Index("knowledge_query_feedback_query_idx", "agent_query_id"),
        Index("knowledge_query_feedback_rating_idx", "org_id", "rating"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    agent_query_id: Mapped[UUID] = mapped_column(ForeignKey("agent_queries.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    rating: Mapped[KnowledgeFeedbackRating] = mapped_column(knowledge_feedback_rating)
    comment: Mapped[str | None] = mapped_column(Text)
    feedback_reason: Mapped[str | None] = mapped_column(Text)
    answer_confidence: Mapped[float | None] = mapped_column()
    query_type: Mapped[str | None] = mapped_column(Text)
    selected_source_ids: Mapped[list[str] | None] = mapped_column(JSONB)


class KnowledgeSuggestion(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_suggestions"
    __table_args__ = (
        Index("knowledge_suggestions_org_status_idx", "org_id", "status", "created_at"),
        Index("knowledge_suggestions_document_idx", "document_id", "created_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    suggestion_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    proposed_changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(Text, default=KnowledgeSuggestionStatus.OPEN.value, server_default="open")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectScopeState(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "project_scope_states"
    __table_args__ = (
        Index("project_scope_states_org_id_idx", "org_id"),
        Index("project_scope_states_project_id_idx", "project_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    scope_status: Mapped[GovernanceScopeStatus] = mapped_column(
        governance_scope_status,
        default=GovernanceScopeStatus.APPROVED,
    )
    version_label: Mapped[str] = mapped_column(Text, default="v1")
    notes: Mapped[str | None] = mapped_column(Text)
    linked_charter_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProjectDependency(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "project_dependencies"
    __table_args__ = (
        Index("project_dependencies_org_id_idx", "org_id"),
        Index("project_dependencies_project_id_idx", "project_id"),
        Index("project_dependencies_status_idx", "org_id", "status"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    dependency_type: Mapped[GovernanceDependencyType] = mapped_column(governance_dependency_type)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[GovernanceDependencyStatus] = mapped_column(
        governance_dependency_status,
        default=GovernanceDependencyStatus.OPEN,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class GovernanceEscalation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "governance_escalations"
    __table_args__ = (
        Index("governance_escalations_org_id_idx", "org_id"),
        Index("governance_escalations_project_id_idx", "project_id"),
        Index("governance_escalations_status_idx", "org_id", "status"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[GovernanceEscalationSeverity] = mapped_column(
        governance_escalation_severity,
        default=GovernanceEscalationSeverity.MEDIUM,
    )
    status: Mapped[GovernanceEscalationStatus] = mapped_column(
        governance_escalation_status,
        default=GovernanceEscalationStatus.OPEN,
    )
    raised_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[GovernanceEscalationSourceType | None] = mapped_column(
        governance_escalation_source_type
    )
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    client_summary: Mapped[str | None] = mapped_column(Text)
    client_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    client_published_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    client_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceAction(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "governance_actions"
    __table_args__ = (
        Index("governance_actions_org_id_idx", "org_id"),
        Index("governance_actions_project_id_idx", "project_id"),
        Index("governance_actions_status_idx", "org_id", "status"),
        Index("governance_actions_due_date_idx", "org_id", "due_date"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[GovernanceActionStatus] = mapped_column(
        governance_action_status,
        default=GovernanceActionStatus.OPEN,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_knowledge_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProjectGovernanceSummary(Base, UuidPrimaryKey, UpdatedAt):
    __tablename__ = "project_governance_summary"
    __table_args__ = (
        Index(
            "project_governance_summary_org_project_key",
            "org_id",
            "project_id",
            unique=True,
        ),
        Index("project_governance_summary_org_id_idx", "org_id"),
        Index("project_governance_summary_project_id_idx", "project_id"),
        Index("project_governance_summary_org_updated_idx", "org_id", "updated_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    open_dependencies_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blocked_dependencies_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blocking_overdue_dependencies_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    open_actions_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    overdue_actions_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_escalations_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    critical_escalations_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pending_scope_changes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class GovernanceWeeklySummary(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "governance_weekly_summaries"
    __table_args__ = (
        Index("governance_weekly_summaries_org_id_idx", "org_id"),
        Index("governance_weekly_summaries_week_idx", "org_id", "summary_week"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    summary_week: Mapped[date] = mapped_column(Date)
    summary_text: Mapped[str] = mapped_column(Text)
    status: Mapped[GovernanceSummaryStatus] = mapped_column(
        governance_summary_status,
        default=GovernanceSummaryStatus.DRAFT,
    )
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceJob(Base, UuidPrimaryKey, UpdatedAt):
    __tablename__ = "governance_jobs"
    __table_args__ = (
        Index(
            "governance_jobs_active_idempotency_uidx",
            "idempotency_key",
            unique=True,
            postgresql_where=text(
                "status IN ('queued', 'running', 'retry_scheduled', 'cancellation_requested')"
            ),
        ),
        Index("governance_jobs_org_requested_idx", "org_id", "requested_at"),
        Index("governance_jobs_project_requested_idx", "project_id", "requested_at"),
        Index("governance_jobs_requester_requested_idx", "requested_by", "requested_at"),
        Index("governance_jobs_queue_idx", "status", "next_attempt_at", "requested_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(Text)
    status: Mapped[GovernanceJobStatus] = mapped_column(
        governance_job_status,
        default=GovernanceJobStatus.QUEUED,
        server_default="queued",
    )
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_stage: Mapped[str] = mapped_column(Text, default="queued", server_default="queued")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(Text)
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    result_record_type: Mapped[str | None] = mapped_column(Text)
    result_record_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queue_wait_ms: Mapped[int | None] = mapped_column(BigInteger)
    processing_ms: Mapped[int | None] = mapped_column(BigInteger)


class GovernanceJobEvent(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_job_events"
    __table_args__ = (
        Index("governance_job_events_job_created_idx", "job_id", "created_at"),
        Index("governance_job_events_org_created_idx", "org_id", "created_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("governance_jobs.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )


class GovernanceEvidenceLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_evidence_links"
    __table_args__ = (
        Index("governance_evidence_links_summary_idx", "summary_id"),
        Index("governance_evidence_links_charter_idx", "charter_id"),
        Index("governance_evidence_links_org_idx", "org_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    summary_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_weekly_summaries.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_charters.id", ondelete="CASCADE")
    )
    source_type: Mapped[GovernanceEvidenceSourceType] = mapped_column(governance_evidence_source_type)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))


class ProjectCharter(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "project_charters"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="project_charters_project_version_key"),
        Index("project_charters_org_id_idx", "org_id"),
        Index("project_charters_project_id_idx", "project_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(Text)
    status: Mapped[GovernanceCharterStatus] = mapped_column(
        governance_charter_status,
        default=GovernanceCharterStatus.DRAFT,
    )
    generated_text: Mapped[str] = mapped_column(Text)
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    previous_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_charters.id", ondelete="SET NULL")
    )
    knowledge_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    knowledge_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="SET NULL")
    )
    visibility: Mapped[KnowledgeVisibility] = mapped_column(
        knowledge_visibility,
        default=KnowledgeVisibility.INTERNAL_ONLY,
    )
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_status: Mapped[GovernanceCharterPublicationStatus] = mapped_column(
        governance_charter_publication_status,
        default=GovernanceCharterPublicationStatus.NOT_PUBLISHED,
        server_default="not_published",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    publication_error: Mapped[str | None] = mapped_column(Text)
    publication_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_publication_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceCharterPublicationEvent(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_charter_publication_events"
    __table_args__ = (
        Index(
            "governance_charter_publication_events_charter_idx",
            "charter_id",
            "created_at",
        ),
        Index(
            "governance_charter_publication_events_org_type_idx",
            "org_id",
            "event_type",
            "created_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_charters.id", ondelete="CASCADE")
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    event_type: Mapped[GovernanceCharterPublicationEventType] = mapped_column(
        governance_charter_publication_event_type
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    knowledge_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    knowledge_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="SET NULL")
    )
    previous_knowledge_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="SET NULL")
    )
    charter_version: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict] = mapped_column(
        "event_metadata", JSONB, default=dict, server_default="{}"
    )


class GovernanceCharterPublicationAudit(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_charter_publication_audits"
    __table_args__ = (
        Index(
            "governance_charter_publication_audits_charter_idx",
            "charter_id",
            "created_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_charters.id", ondelete="CASCADE")
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text)
    knowledge_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    knowledge_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="SET NULL")
    )
    previous_knowledge_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="SET NULL")
    )
    charter_version: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    audit_metadata: Mapped[dict] = mapped_column(
        "audit_metadata", JSONB, default=dict, server_default="{}"
    )


class GovernanceAIRecommendation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "governance_ai_recommendations"
    __table_args__ = (
        Index(
            "governance_ai_recommendations_org_status_generated_idx",
            "org_id",
            "status",
            "generated_at",
        ),
        Index(
            "governance_ai_recommendations_org_project_status_idx",
            "org_id",
            "project_id",
            "status",
        ),
        Index("governance_ai_recommendations_evidence_hash_idx", "org_id", "evidence_hash"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    scope: Mapped[GovernanceAIRecommendationScope] = mapped_column(
        governance_ai_recommendation_scope
    )
    recommendation_type: Mapped[GovernanceAIRecommendationType] = mapped_column(
        governance_ai_recommendation_type
    )
    title: Mapped[str] = mapped_column(Text)
    narrative: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    priority: Mapped[GovernanceAIRecommendationPriority] = mapped_column(
        governance_ai_recommendation_priority,
        default=GovernanceAIRecommendationPriority.MEDIUM,
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    status: Mapped[GovernanceAIRecommendationStatus] = mapped_column(
        governance_ai_recommendation_status,
        default=GovernanceAIRecommendationStatus.ACTIVE,
    )
    suggested_actions: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_hash: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(Text)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    model_name: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    generation_request_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    generated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    dismissed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acceptance_status: Mapped[GovernanceRecommendationAcceptanceStatus] = mapped_column(
        governance_recommendation_acceptance_status,
        default=GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        server_default="not_accepted",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    converted_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_actions.id", ondelete="SET NULL")
    )
    converted_escalation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_escalations.id", ondelete="SET NULL")
    )
    accepted_suggested_action_index: Mapped[int | None] = mapped_column(Integer)
    acceptance_note: Mapped[str | None] = mapped_column(Text)
    auto_detected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    trigger_type: Mapped[GovernanceEscalationTriggerType | None] = mapped_column(
        governance_escalation_trigger_type
    )
    trigger_entity_type: Mapped[str | None] = mapped_column(Text)
    trigger_entity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    trigger_fingerprint: Mapped[str | None] = mapped_column(Text)
    severity_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snooze_reason: Mapped[str | None] = mapped_column(Text)
    false_positive_status: Mapped[GovernanceFalsePositiveStatus | None] = mapped_column(
        governance_false_positive_status
    )
    false_positive_reason: Mapped[str | None] = mapped_column(Text)
    false_positive_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    false_positive_confirmed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    quality_band: Mapped[str | None] = mapped_column(Text)
    quality_score_version: Mapped[str | None] = mapped_column(Text)
    quality_components: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    quality_provisional: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    calibrated_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    confidence_band: Mapped[str | None] = mapped_column(Text)
    calibration_version: Mapped[str | None] = mapped_column(Text)
    calibration_gap: Mapped[float | None] = mapped_column(Numeric(6, 4))
    observed_success_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    expected_calibration_error: Mapped[float | None] = mapped_column(Numeric(6, 4))
    brier_score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    explanation_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")
    recurrence_after_acceptance_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    recurrence_after_dismissal_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    strategy_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")
    confidence_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")
    learning_rule_version: Mapped[str | None] = mapped_column(Text)
    resolution_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class GovernanceAIRecommendationConversion(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_ai_recommendation_conversions"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "suggested_action_index",
            name="governance_ai_recommendation_conversions_suggestion_key",
        ),
        UniqueConstraint(
            "org_id",
            "idempotency_key",
            name="governance_ai_recommendation_conversions_idempotency_key",
        ),
        Index(
            "governance_ai_recommendation_conversions_recommendation_idx",
            "recommendation_id",
        ),
        Index("governance_ai_recommendation_conversions_org_idx", "org_id"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_ai_recommendations.id", ondelete="CASCADE")
    )
    suggested_action_index: Mapped[int] = mapped_column(Integer)
    conversion_target: Mapped[GovernanceRecommendationConversionTarget] = mapped_column(
        governance_recommendation_conversion_target
    )
    created_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_actions.id", ondelete="SET NULL")
    )
    created_escalation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_escalations.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    request_fingerprint: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class GovernanceAIRecommendationFeedback(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_ai_recommendation_feedback"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "user_id",
            name="governance_ai_recommendation_feedback_user_key",
        ),
        Index(
            "governance_ai_recommendation_feedback_recommendation_idx",
            "recommendation_id",
        ),
        Index("governance_ai_recommendation_feedback_org_idx", "org_id"),
    )

    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_ai_recommendations.id", ondelete="CASCADE")
    )
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    helpful: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    accurate: Mapped[bool | None] = mapped_column(Boolean)
    useful: Mapped[bool | None] = mapped_column(Boolean)
    actionable: Mapped[bool | None] = mapped_column(Boolean)
    clear: Mapped[bool | None] = mapped_column(Boolean)
    missing_evidence: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    duplicate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    already_handled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    feedback_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")


class GovernanceRecommendationLifecycleEvent(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_recommendation_lifecycle_events"
    __table_args__ = (
        Index(
            "governance_recommendation_lifecycle_events_rec_idx",
            "recommendation_id",
            "created_at",
        ),
        Index(
            "governance_recommendation_lifecycle_events_org_type_idx",
            "org_id",
            "event_type",
            "created_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_ai_recommendations.id", ondelete="CASCADE")
    )
    event_type: Mapped[GovernanceRecommendationLifecycleEventType] = mapped_column(
        governance_recommendation_lifecycle_event_type
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    conversion_target: Mapped[str | None] = mapped_column(Text)
    conversion_target_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")


class GovernanceRecommendationLearningRule(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "governance_recommendation_learning_rules"
    __table_args__ = (
        Index(
            "governance_recommendation_learning_rules_org_status_idx",
            "org_id",
            "status",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    rule_type: Mapped[str] = mapped_column(Text)
    rule_payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[GovernanceLearningRuleStatus] = mapped_column(
        governance_learning_rule_status,
        default=GovernanceLearningRuleStatus.DRAFT,
        server_default="draft",
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_recommendation_learning_rules.id", ondelete="SET NULL")
    )
    change_summary: Mapped[str | None] = mapped_column(Text)
    evaluation_mode: Mapped[str] = mapped_column(Text, default="none", server_default="none")
    shadow_evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_recommendation_shadow_evaluations.id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    config_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    previous_config_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    performance_before: Mapped[dict | None] = mapped_column(JSONB)
    performance_after: Mapped[dict | None] = mapped_column(JSONB)
    allowed_effects: Mapped[list] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default="{}",
    )


class GovernanceRecommendationStrategyVersion(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "governance_recommendation_strategy_versions"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "strategy_version",
            name="governance_recommendation_strategy_versions_org_version_key",
        ),
        Index(
            "governance_recommendation_strategy_versions_org_active_idx",
            "org_id",
            "is_active",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    strategy_version: Mapped[str] = mapped_column(Text)
    confidence_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")
    quality_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")
    explanation_version: Mapped[str] = mapped_column(Text, default="v1", server_default="v1")
    learning_rule_version: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    config_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class GovernanceRecommendationShadowEvaluation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "governance_recommendation_shadow_evaluations"
    __table_args__ = (
        Index(
            "governance_recommendation_shadow_evaluations_org_status_idx",
            "org_id",
            "status",
            "created_at",
        ),
        Index(
            "governance_recommendation_shadow_evaluations_rule_idx",
            "learning_rule_id",
            "created_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    learning_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_recommendation_learning_rules.id", ondelete="SET NULL")
    )
    strategy_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_recommendation_strategy_versions.id", ondelete="SET NULL")
    )
    status: Mapped[GovernanceRecommendationShadowStatus] = mapped_column(
        governance_recommendation_shadow_status,
        default=GovernanceRecommendationShadowStatus.PENDING,
        server_default="pending",
    )
    sample_size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    baseline_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    shadow_metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    comparison_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    expected_impact: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class GovernanceRecommendationDriftAlert(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_recommendation_drift_alerts"
    __table_args__ = (
        Index(
            "governance_recommendation_drift_alerts_org_created_idx",
            "org_id",
            "created_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    alert_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[GovernanceRecommendationDriftSeverity] = mapped_column(
        governance_recommendation_drift_severity,
        default=GovernanceRecommendationDriftSeverity.WARNING,
        server_default="warning",
    )
    metric_name: Mapped[str] = mapped_column(Text)
    baseline_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    current_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    threshold_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    strategy_version: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class GovernanceRecommendationEvaluationReport(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "governance_recommendation_evaluation_reports"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "period",
            "period_start",
            "period_end",
            name="governance_recommendation_evaluation_reports_period_key",
        ),
        Index(
            "governance_recommendation_evaluation_reports_org_period_idx",
            "org_id",
            "period",
            "generated_at",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    period: Mapped[GovernanceRecommendationEvaluationPeriod] = mapped_column(
        governance_recommendation_evaluation_period
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    strategy_version: Mapped[str | None] = mapped_column(Text)
    report_payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    generated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GovernanceRecordEvidenceLink(Base, UuidPrimaryKey, CreatedAt, SoftDelete):
    __tablename__ = "governance_record_evidence_links"
    __table_args__ = (
        Index(
            "governance_record_evidence_links_target_idx",
            "org_id",
            "target_type",
            "target_id",
        ),
        Index(
            "governance_record_evidence_links_recommendation_idx",
            "org_id",
            "recommendation_id",
        ),
        Index(
            "governance_record_evidence_links_source_idx",
            "source_type",
            "source_id",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    target_type: Mapped[GovernanceRecordTargetType] = mapped_column(governance_record_target_type)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    source_type: Mapped[GovernanceRecordEvidenceSourceType] = mapped_column(
        governance_record_evidence_source_type
    )
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_ai_recommendations.id", ondelete="SET NULL")
    )
    conversion_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_ai_recommendation_conversions.id", ondelete="SET NULL")
    )
    evidence_id: Mapped[str | None] = mapped_column(Text)
    link_type: Mapped[GovernanceRecordLinkType] = mapped_column(governance_record_link_type)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status_snapshot: Mapped[str | None] = mapped_column(Text)
    severity_snapshot: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
