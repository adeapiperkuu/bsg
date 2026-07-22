"""API contracts for the Cross-Agent Reporting Framework."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ReportSectionConfig(BaseModel):
    key: str
    options: dict[str, Any] = Field(default_factory=dict)


class ReportEvidencePayload(BaseModel):
    source_table: str
    source_id: UUID | None = None
    kpi_key: str | None = None
    observation_id: UUID | None = None
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KpiSummaryItem(BaseModel):
    kpi_key: str
    status: str
    numeric_value: str | None = None
    text_value: str | None = None
    unit: str | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class KpiSummarySectionPayload(BaseModel):
    items: list[KpiSummaryItem] = Field(default_factory=list)


class TrendSectionPayload(BaseModel):
    trends: list[dict[str, Any]] = Field(default_factory=list)


class ComparisonSectionPayload(BaseModel):
    comparisons: list[dict[str, Any]] = Field(default_factory=list)


class ForecastSectionPayload(BaseModel):
    forecasts: list[dict[str, Any]] = Field(default_factory=list)


class DomainListSectionPayload(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class NarrativeSectionPayload(BaseModel):
    headline: str
    summary: str
    highlights: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class EvidenceSectionPayload(BaseModel):
    references: list[ReportEvidencePayload] = Field(default_factory=list)


class ChartSectionPayload(BaseModel):
    charts: list[dict[str, Any]] = Field(default_factory=list)


class ReportSectionPayload(BaseModel):
    key: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    markdown: str = ""
    limitations: list[str] = Field(default_factory=list)
    has_ai: bool = False
    requires_approval: bool = False


class ReportTemplateBase(BaseModel):
    template_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    audience: str
    domain: str
    version: str = Field(min_length=1, max_length=40)
    status: Literal["draft", "active", "archived"] = "draft"
    section_config: list[ReportSectionConfig] = Field(default_factory=list)
    export_formats: list[Literal["json", "csv", "pdf", "docx"]] = Field(
        default_factory=lambda: ["json", "csv", "pdf", "docx"]
    )
    requires_approval: bool = True
    allowed_roles: list[str] = Field(default_factory=list)
    is_client_visible: bool = False


class ReportTemplateCreate(ReportTemplateBase):
    org_id: UUID | None = None


class ReportTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    audience: str | None = None
    domain: str | None = None
    status: Literal["draft", "active", "archived"] | None = None
    section_config: list[ReportSectionConfig] | None = None
    export_formats: list[Literal["json", "csv", "pdf", "docx"]] | None = None
    requires_approval: bool | None = None
    allowed_roles: list[str] | None = None
    is_client_visible: bool | None = None


class ReportTemplateRead(ReportTemplateBase, OrmModel):
    id: UUID
    org_id: UUID | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ReportGenerateRequest(BaseModel):
    template_key: str
    template_version: str | None = None
    project_id: UUID | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    title: str | None = None
    section_options: dict[str, dict[str, Any]] = Field(default_factory=dict)
    idempotency_key: str | None = None
    generation_mode: str = "structured"

    @model_validator(mode="after")
    def validate_period(self) -> "ReportGenerateRequest":
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be before period_end")
        return self


class ReportInstanceListItem(OrmModel):
    id: UUID
    org_id: UUID
    project_id: UUID | None
    template_key: str
    template_version: str
    audience: str
    domain: str
    status: str
    title: str
    period_start: datetime | None
    period_end: datetime | None
    has_ai_sections: bool
    evidence_fingerprint: str | None
    created_at: datetime
    updated_at: datetime


class ReportInstanceRead(ReportInstanceListItem):
    template_id: UUID
    body_markdown: str | None
    content_payload: dict[str, Any]
    provenance: dict[str, Any]
    limitations: list[Any]
    generation_mode: str
    generated_by_user_id: UUID | None
    generated_by_job_id: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    rejected_by: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    distributed_at: datetime | None


class ReportScheduleBase(BaseModel):
    project_id: UUID | None = None
    template_id: UUID
    interval: Literal["daily", "weekly", "monthly", "quarterly"]
    is_enabled: bool = True
    audience: str
    config: dict[str, Any] = Field(default_factory=dict)
    next_run_at: datetime | None = None
    create_as_status: Literal["draft"] = "draft"


class ReportScheduleCreate(ReportScheduleBase):
    pass


class ReportScheduleUpdate(BaseModel):
    interval: Literal["daily", "weekly", "monthly", "quarterly"] | None = None
    is_enabled: bool | None = None
    audience: str | None = None
    config: dict[str, Any] | None = None
    next_run_at: datetime | None = None
    create_as_status: Literal["draft"] | None = None


class ReportScheduleRead(ReportScheduleBase, OrmModel):
    id: UUID
    org_id: UUID
    last_run_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ReportExportRead(OrmModel):
    id: UUID
    report_instance_id: UUID
    format: str
    storage_backend: str
    storage_path: str
    file_name: str
    content_type: str
    size_bytes: int | None
    checksum_sha256: str | None
    content_hash: str | None
    generated_at: datetime


class ReportApprovalEventRead(OrmModel):
    id: UUID
    report_instance_id: UUID
    actor_user_id: UUID | None
    from_status: str | None
    to_status: str
    action: str
    note: str | None
    event_metadata: dict[str, Any]
    created_at: datetime


class ReportJobStartRead(OrmModel):
    id: UUID
    job_type: str
    status: str
    report_instance_id: UUID | None
    idempotency_key: str
    requested_at: datetime


class ReportPreviewRead(BaseModel):
    template: ReportTemplateRead
    title: str
    body_markdown: str
    sections: list[ReportSectionPayload]
    limitations: list[str] = Field(default_factory=list)
    evidence_fingerprint: str | None = None
    has_ai_sections: bool = False
    requires_approval: bool = False
