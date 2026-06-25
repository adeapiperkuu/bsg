from datetime import date, datetime
from decimal import Decimal
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
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
    SYSTEM = "system"


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
    CLIENT_SAFE = "client_safe"


class KnowledgeDocumentStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
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


class KnowledgeExtractionStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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
knowledge_extraction_status = Enum(
    KnowledgeExtractionStatus,
    name="knowledge_extraction_status",
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


class Project(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "projects"
    __table_args__ = (Index("projects_org_id_idx", "org_id"), Index("projects_status_idx", "status"))

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
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


class QualitySnapshot(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "quality_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "team_id", "iso_year", "iso_week", name="quality_snapshots_project_team_week_key"),
        Index("quality_snapshots_project_id_idx", "project_id"),
        Index("quality_snapshots_org_id_idx", "org_id"),
        Index("quality_snapshots_week_idx", "iso_year", "iso_week"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    iso_week: Mapped[int] = mapped_column(Integer)
    iso_year: Mapped[int] = mapped_column(Integer)
    gold_set_accuracy_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    iaa_krippendorff_alpha: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    rework_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    has_drift_alert: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    drift_alert_detail: Mapped[str | None] = mapped_column(Text)


class QualityErrorEntry(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "quality_error_entries"

    quality_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("quality_snapshots.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    error_category: Mapped[str] = mapped_column(Text)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    recommended_action: Mapped[str | None] = mapped_column(Text)


class RiskAlert(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "risk_alerts"

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
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MitigationRecommendation(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "mitigation_recommendations"
    __table_args__ = (
        Index("mitigation_recommendations_project_id_idx", "project_id"),
        Index("mitigation_recommendations_org_id_idx", "org_id"),
        Index("mitigation_recommendations_source_risk_id_idx", "source_risk_id"),
        Index("mitigation_recommendations_status_idx", "status"),
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


class CommunicationEvidenceLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "communication_evidence_links"

    communication_id: Mapped[UUID] = mapped_column(ForeignKey("client_communications.id", ondelete="CASCADE"), index=True)
    source_table: Mapped[str] = mapped_column(Text)
    source_row_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(Text)


class AgentQuery(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "agent_queries"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    agent_name: Mapped[str] = mapped_column(Text)
    query_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class AgentQueryEvidenceLink(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "agent_query_evidence_links"

    agent_query_id: Mapped[UUID] = mapped_column(ForeignKey("agent_queries.id", ondelete="CASCADE"), index=True)
    source_table: Mapped[str] = mapped_column(Text)
    source_row_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(Text)


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

    metric_key: Mapped[str] = mapped_column(Text, unique=True)
    display_label: Mapped[str] = mapped_column(Text)
    is_client_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    description: Mapped[str | None] = mapped_column(Text)


class DeliveryConfidenceScore(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "delivery_confidence_scores"

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


class KnowledgeFolder(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "knowledge_folders"
    __table_args__ = (Index("knowledge_folders_org_idx", "org_id"),)

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    folder_kind: Mapped[KnowledgeFolderKind] = mapped_column(knowledge_folder_kind)
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class KnowledgeDocument(Base, UuidPrimaryKey, CreatedAt, UpdatedAt, SoftDelete):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("knowledge_documents_org_folder_idx", "org_id", "folder_id"),
        Index("knowledge_documents_retrieval_idx", "org_id", "status", "indexing_status", "visibility"),
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
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentVersion(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="knowledge_document_versions_document_version_key"),
        Index("knowledge_document_versions_document_idx", "document_id"),
        Index("knowledge_document_versions_active_idx", "document_id", "is_active"),
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
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class KnowledgeDocumentChunk(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "knowledge_document_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="knowledge_document_chunks_version_index_key"),
        Index("knowledge_document_chunks_document_idx", "document_id"),
        Index("knowledge_document_chunks_version_idx", "version_id"),
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
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    agent_query_id: Mapped[UUID] = mapped_column(ForeignKey("agent_queries.id", ondelete="CASCADE"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="RESTRICT"))
    chunk_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_document_chunks.id", ondelete="SET NULL"))
    citation_label: Mapped[str] = mapped_column(Text)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
