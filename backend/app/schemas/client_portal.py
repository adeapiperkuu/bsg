from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ClientProjectOverviewRead(BaseModel):
    project_id: UUID
    project_name: str
    description: str | None = None
    current_status: str
    overall_health: Literal["green", "amber", "red", "insufficient"]
    delivery_confidence: int | None = None
    delivery_confidence_label: str
    current_phase: str
    completion_percentage: int = Field(ge=0, le=100)
    start_date: date
    target_end_date: date


class ClientMilestoneRead(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    planned_date: date
    actual_date: date | None = None
    status: str
    progress_percentage: int = Field(ge=0, le=100)


class ClientRiskRead(BaseModel):
    id: UUID
    title: str
    severity: str
    impact: str | None = None
    mitigation: str | None = None
    status: str
    updated_at: datetime


class ClientActionRead(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    action_type: Literal["approval", "information_request", "client_action"]
    due_date: date | None = None
    status: str
    is_overdue: bool = False


class ClientReportRead(BaseModel):
    id: UUID
    title: str
    report_type: str
    executive_summary: str
    published_at: datetime
    pdf_download_url: str
    csv_download_url: str


class ClientAiSummaryRead(BaseModel):
    title: str
    summary: str
    current_progress: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    upcoming_work: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class ClientDocumentRead(BaseModel):
    id: UUID
    title: str
    document_type: str
    version: str
    description: str | None = None
    file_name: str
    file_url: str | None = None
    shared_at: datetime


class ClientDeliverableRead(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    status: str
    due_date: date | None = None
    completed_at: datetime | None = None
    file_name: str | None = None
    file_url: str | None = None


class ClientChangeRequestCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=5000)
    business_justification: str | None = Field(default=None, max_length=3000)
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class ClientChangeRequestRead(ORMModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    business_justification: str | None = None
    priority: str
    status: str
    decision_notes: str | None = None
    implemented_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ClientMeetingActionItemRead(BaseModel):
    title: str
    owner: str | None = None
    due_date: date | None = None
    status: str = "open"


class ClientMeetingRead(BaseModel):
    id: UUID
    title: str
    starts_at: datetime
    duration_minutes: int
    meeting_url: str | None = None
    agenda: str | None = None
    minutes: str | None = None
    action_items: list[ClientMeetingActionItemRead] = Field(default_factory=list)
    status: str


class ClientNotificationRead(BaseModel):
    id: str
    notification_type: Literal[
        "report_published",
        "milestone_completed",
        "risk_updated",
        "document_shared",
        "meeting_scheduled",
    ]
    title: str
    detail: str | None = None
    occurred_at: datetime
    href: str | None = None


class ClientProjectDashboardRead(BaseModel):
    overview: ClientProjectOverviewRead
    milestones: list[ClientMilestoneRead]
    risks: list[ClientRiskRead]
    client_actions: list[ClientActionRead]
    reports: list[ClientReportRead]
    ai_summary: ClientAiSummaryRead
    documents: list[ClientDocumentRead]
    deliverables: list[ClientDeliverableRead]
    change_requests: list[ClientChangeRequestRead]
    meetings: list[ClientMeetingRead]
    notifications: list[ClientNotificationRead]
    generated_at: datetime
