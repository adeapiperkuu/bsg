from datetime import date, datetime
from decimal import Decimal
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

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


app_role = Enum(AppRole, name="app_role", values_callable=lambda x: [e.value for e in x])
delivery_site = Enum(DeliverySite, name="delivery_site", values_callable=lambda x: [e.value for e in x])
project_status = Enum(ProjectStatus, name="project_status", values_callable=lambda x: [e.value for e in x])
milestone_status = Enum(MilestoneStatus, name="milestone_status", values_callable=lambda x: [e.value for e in x])
risk_tier = Enum(RiskTier, name="risk_tier", values_callable=lambda x: [e.value for e in x])
alert_type = Enum(AlertType, name="alert_type", values_callable=lambda x: [e.value for e in x])
alert_status = Enum(AlertStatus, name="alert_status", values_callable=lambda x: [e.value for e in x])
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
    threshold_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


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


class WorkforceSkill(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "workforce_skills"
    __table_args__ = (UniqueConstraint("annotator_id", "skill_code", name="workforce_skills_annotator_skill_key"),)

    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("annotators.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    skill_code: Mapped[str] = mapped_column(Text)
    proficiency_level: Mapped[str] = mapped_column(Text)
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkforceUtilizationSnapshot(Base, UuidPrimaryKey, CreatedAt, UpdatedAt):
    __tablename__ = "workforce_utilization_snapshots"
    __table_args__ = (
        UniqueConstraint("team_id", "iso_year", "iso_week", name="workforce_utilization_team_week_key"),
    )

    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"), index=True)
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    target_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    logged_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    utilization_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class InterAgentSignal(Base, UuidPrimaryKey, CreatedAt):
    __tablename__ = "inter_agent_signals"

    signal_type: Mapped[str] = mapped_column(Text, index=True)
    source_agent: Mapped[str] = mapped_column(Text, default="quality_intelligence_agent")
    target_agent: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(Text, default=SignalStatus.PENDING, server_default="pending", index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
