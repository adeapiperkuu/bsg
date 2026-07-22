"""API schemas for Client Intelligence scheduled reports and governance."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.client_intelligence.contracts import ClientIntelligenceModel
from app.agents.client_intelligence.report_builder import (
    ReportExportFormat,
    ReportSectionConfig,
)
from app.db.models import (
    ClientReportCadence,
    ClientReportDeliveryStatus,
    ClientReportGovernanceStatus,
)


class ClientReportScheduleCreate(ClientIntelligenceModel):
    cadence: ClientReportCadence
    enabled: bool = True
    next_run_at: datetime | None = None
    sections: list[ReportSectionConfig] = Field(default_factory=list)


class ClientReportScheduleUpdate(ClientIntelligenceModel):
    enabled: bool | None = None
    next_run_at: datetime | None = None
    sections: list[ReportSectionConfig] | None = None


class ClientReportScheduleRead(ClientIntelligenceModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    cadence: ClientReportCadence
    enabled: bool
    section_config: list[dict] = Field(default_factory=list)
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_package_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ClientReportPackageRead(ClientIntelligenceModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    schedule_id: UUID | None = None
    communication_id: UUID | None = None
    report_type: ClientReportCadence
    title: str
    body_markdown: str
    section_config: list[dict] = Field(default_factory=list)
    version: int
    status: ClientReportGovernanceStatus
    source_fingerprint: str | None = None
    rejection_reason: str | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ClientReportApprovalRead(ClientIntelligenceModel):
    id: UUID
    org_id: UUID
    package_id: UUID
    from_status: ClientReportGovernanceStatus | None = None
    to_status: ClientReportGovernanceStatus
    actor_user_id: UUID | None = None
    comment: str | None = None
    rejection_reason: str | None = None
    created_at: datetime


class ClientReportDeliveryRead(ClientIntelligenceModel):
    id: UUID
    org_id: UUID
    package_id: UUID
    channel: str
    status: ClientReportDeliveryStatus
    recipient_summary: str | None = None
    error_detail: str | None = None
    delivered_at: datetime | None = None
    created_at: datetime


class ReportGovernanceTransitionRequest(ClientIntelligenceModel):
    action: str
    comment: str | None = None
    rejection_reason: str | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        allowed = {"submit", "approve", "reject", "resubmit"}
        cleaned = value.strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"action must be one of {sorted(allowed)}")
        return cleaned


class ReportBuilderExportRequest(ClientIntelligenceModel):
    export_format: ReportExportFormat = ReportExportFormat.PDF


class ReportDraftGenerateRequest(ClientIntelligenceModel):
    cadence: ClientReportCadence = ClientReportCadence.WEEKLY
    title: str | None = None
    sections: list[ReportSectionConfig] = Field(default_factory=list)
    schedule_id: UUID | None = None
