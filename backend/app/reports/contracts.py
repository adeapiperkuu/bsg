"""Contracts shared by report templates, builders, and exporters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser

KPI_SUMMARY = "kpi_summary"
TRENDS = "trends"
COMPARISONS = "comparisons"
FORECASTS = "forecasts"
MILESTONES = "milestones"
RISKS = "risks"
RECOMMENDATIONS = "recommendations"
AI_EXECUTIVE_SUMMARY = "ai_executive_summary"
EVIDENCE = "evidence"
APPENDIX = "appendix"
CHARTS = "charts"

SECTION_KEYS = frozenset(
    {
        KPI_SUMMARY,
        TRENDS,
        COMPARISONS,
        FORECASTS,
        MILESTONES,
        RISKS,
        RECOMMENDATIONS,
        AI_EXECUTIVE_SUMMARY,
        EVIDENCE,
        APPENDIX,
        CHARTS,
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    source_table: str
    source_id: UUID | None = None
    kpi_key: str | None = None
    observation_id: UUID | None = None
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportSectionResult:
    key: str
    title: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    markdown: str = ""
    evidence: tuple[EvidenceReference, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    has_ai: bool = False
    requires_approval: bool = False


@dataclass(slots=True)
class ReportBuildContext:
    org_id: UUID
    project_id: UUID | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    template_key: str | None = None
    template_version: str | None = None
    audience: str = "internal"
    title: str | None = None
    generation_mode: str = "structured"
    inputs: Mapping[str, Any] = field(default_factory=dict)
    section_results: list[ReportSectionResult] = field(default_factory=list)
    generated_by_job_id: UUID | None = None
    source_table: str | None = None
    source_id: UUID | None = None
    idempotency_key: str | None = None


SectionBuilder = Callable[
    [AsyncSession, CurrentUser, ReportBuildContext, Mapping[str, Any]],
    Awaitable[ReportSectionResult],
]
