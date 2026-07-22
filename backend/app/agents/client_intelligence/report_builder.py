"""Configurable Client Report Builder with modular sections (Phase 17.5)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.client_intelligence.contracts import ClientEvidencePack, ClientIntelligenceModel
from app.agents.client_intelligence.delivery_confidence_intelligence import (
    assess_delivery_confidence,
)
from app.agents.client_intelligence.go_live import assess_go_live_readiness
from app.agents.client_intelligence.go_live_contracts import go_live_decision_label
from app.agents.client_intelligence.milestone_intelligence import (
    assess_milestone_intelligence,
)
from app.agents.client_intelligence.project_health import assess_project_health
from app.agents.client_intelligence.readiness import assess_project_readiness
from app.agents.client_intelligence.readiness_contracts import readiness_status_label
from app.agents.client_intelligence.recommendations import (
    generate_readiness_recommendations,
)
from app.agents.client_intelligence.risk_transparency import assess_risk_transparency
from app.agents.governance.services.charter_export import (
    CharterExportDocument,
    generate_charter_docx,
    generate_charter_pdf,
)


class ReportSectionKey(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    PROJECT_STATUS = "project_status"
    RISKS = "risks"
    MILESTONES = "milestones"
    CONFIDENCE = "confidence"
    TIMELINE = "timeline"
    READINESS = "readiness"
    GO_LIVE = "go_live"
    RECOMMENDATIONS = "recommendations"


class ReportExportFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


DEFAULT_SECTION_ORDER: tuple[ReportSectionKey, ...] = (
    ReportSectionKey.EXECUTIVE_SUMMARY,
    ReportSectionKey.PROJECT_STATUS,
    ReportSectionKey.CONFIDENCE,
    ReportSectionKey.MILESTONES,
    ReportSectionKey.RISKS,
    ReportSectionKey.TIMELINE,
    ReportSectionKey.READINESS,
    ReportSectionKey.GO_LIVE,
    ReportSectionKey.RECOMMENDATIONS,
)


class ReportSectionConfig(ClientIntelligenceModel):
    section: ReportSectionKey
    enabled: bool = True


class ReportBuilderRequest(ClientIntelligenceModel):
    title: str = "Client Status Report"
    sections: list[ReportSectionConfig] = Field(default_factory=list)
    export_format: ReportExportFormat = ReportExportFormat.PDF

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("title must be non-empty")
        return text


class ReportSectionContent(ClientIntelligenceModel):
    section: ReportSectionKey
    heading: str
    markdown: str
    enabled: bool = True


class BuiltClientReport(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    title: str
    generated_at: datetime
    source_fingerprint: str
    sections: list[ReportSectionContent]
    markdown: str


def build_client_report(
    pack: ClientEvidencePack,
    *,
    request: ReportBuilderRequest | None = None,
    assessed_at: datetime | None = None,
) -> BuiltClientReport:
    """Assemble a modular client report from governed intelligence engines."""
    cfg = request or ReportBuilderRequest()
    enabled = _enabled_sections(cfg.sections)

    readiness = assess_project_readiness(pack, assessed_at=assessed_at)
    go_live = assess_go_live_readiness(pack, assessed_at=assessed_at)
    recommendations = generate_readiness_recommendations(
        pack, assessed_at=assessed_at, readiness=readiness
    )
    try:
        health = assess_project_health(pack, policy=None)
        health_status = health.status.value
        health_obj = health
    except Exception:
        health_status = "unavailable"
        health_obj = None
    try:
        confidence = assess_delivery_confidence(pack, explanation_policy=None)
        confidence_score = (
            f"{confidence.score_pct}%" if confidence.score_pct is not None else "n/a"
        )
        confidence_availability = confidence.availability.value
    except Exception:
        confidence_score = "n/a"
        confidence_availability = "unavailable"
    try:
        risk = assess_risk_transparency(pack, policy=None)
        risk_markdown = _risks_markdown(risk)
    except Exception:
        risk_markdown = "- Risk transparency unavailable from current evidence\n"
    try:
        milestones = assess_milestone_intelligence(pack)
        milestones_markdown = _milestones_markdown(milestones)
    except Exception:
        milestones_markdown = "- Milestone intelligence unavailable from current evidence\n"

    section_bodies: dict[ReportSectionKey, ReportSectionContent] = {
        ReportSectionKey.EXECUTIVE_SUMMARY: ReportSectionContent(
            section=ReportSectionKey.EXECUTIVE_SUMMARY,
            heading="Executive Summary",
            markdown=_executive_summary(pack, readiness, go_live, health_status),
        ),
        ReportSectionKey.PROJECT_STATUS: ReportSectionContent(
            section=ReportSectionKey.PROJECT_STATUS,
            heading="Project Status",
            markdown=(
                f"- Health status: **{health_status}**\n"
                f"- Project status: **{pack.project.project_status}**\n"
                f"- Data quality: **{pack.overall_data_quality.value}**\n"
            ),
        ),
        ReportSectionKey.CONFIDENCE: ReportSectionContent(
            section=ReportSectionKey.CONFIDENCE,
            heading="Confidence",
            markdown=(
                f"- Delivery confidence: **{confidence_score}**\n"
                f"- Availability: **{confidence_availability}**\n"
            ),
        ),
        ReportSectionKey.MILESTONES: ReportSectionContent(
            section=ReportSectionKey.MILESTONES,
            heading="Milestones",
            markdown=milestones_markdown,
        ),
        ReportSectionKey.RISKS: ReportSectionContent(
            section=ReportSectionKey.RISKS,
            heading="Risks",
            markdown=risk_markdown,
        ),
        ReportSectionKey.TIMELINE: ReportSectionContent(
            section=ReportSectionKey.TIMELINE,
            heading="Timeline",
            markdown=(
                f"- Reporting period: "
                f"{pack.reporting_period.start_date.isoformat()} – "
                f"{pack.reporting_period.end_date.isoformat()}\n"
                f"- As of: {pack.reporting_period.as_of.isoformat()}\n"
            ),
        ),
        ReportSectionKey.READINESS: ReportSectionContent(
            section=ReportSectionKey.READINESS,
            heading="Readiness",
            markdown=_readiness_markdown(readiness),
        ),
        ReportSectionKey.GO_LIVE: ReportSectionContent(
            section=ReportSectionKey.GO_LIVE,
            heading="Go-Live Readiness",
            markdown=(
                f"- Decision: **{go_live_decision_label(go_live.decision)}**\n"
                f"- Confidence: **{go_live.confidence_score}**\n"
                + "".join(f"- Reason: {reason}\n" for reason in go_live.reasons[:5])
                + "".join(
                    f"- Blocking item: {item}\n" for item in go_live.blocking_items[:5]
                )
            ),
        ),
        ReportSectionKey.RECOMMENDATIONS: ReportSectionContent(
            section=ReportSectionKey.RECOMMENDATIONS,
            heading="Recommendations",
            markdown=_recommendations_markdown(recommendations.recommendations),
        ),
    }

    sections: list[ReportSectionContent] = []
    parts: list[str] = []
    for key in DEFAULT_SECTION_ORDER:
        content = section_bodies[key]
        content = content.model_copy(update={"enabled": key in enabled})
        sections.append(content)
        if key not in enabled:
            continue
        parts.append(f"## {content.heading}")
        parts.append("")
        parts.append(content.markdown.rstrip())
        parts.append("")

    _ = health_obj  # retained for future section enrichment
    return BuiltClientReport(
        org_id=pack.project.org_id,
        project_id=pack.project.project_id,
        title=cfg.title,
        generated_at=readiness.assessed_at,
        source_fingerprint=pack.source_fingerprint,
        sections=sections,
        markdown="\n".join(parts).strip() + "\n",
    )


def export_client_report(
    report: BuiltClientReport,
    *,
    export_format: ReportExportFormat = ReportExportFormat.PDF,
) -> tuple[bytes, str, str]:
    """Export a built report to PDF or DOCX. Returns (bytes, media_type, extension)."""
    document = CharterExportDocument(
        title=report.title,
        metadata=[
            ("Project ID", str(report.project_id)),
            ("Generated", report.generated_at.strftime("%Y-%m-%d %H:%M UTC")),
            ("Evidence fingerprint", report.source_fingerprint[:12] + "…"),
        ],
        markdown=report.markdown,
    )
    if export_format == ReportExportFormat.DOCX:
        return (
            generate_charter_docx(document),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        )
    return generate_charter_pdf(document), "application/pdf", "pdf"


def _enabled_sections(
    configured: list[ReportSectionConfig],
) -> set[ReportSectionKey]:
    if not configured:
        return set(DEFAULT_SECTION_ORDER)
    enabled = {item.section for item in configured if item.enabled}
    return enabled or set(DEFAULT_SECTION_ORDER)


def _executive_summary(pack, readiness, go_live, health_status: str) -> str:
    score = (
        f"{readiness.overall_score_pct}%"
        if readiness.overall_score_pct is not None
        else "n/a"
    )
    return (
        f"- Project: **{pack.project.project_name}**\n"
        f"- Health: **{health_status}**\n"
        f"- Overall readiness: **{score}** "
        f"({readiness_status_label(readiness.status)})\n"
        f"- Go-live: **{go_live_decision_label(go_live.decision)}**\n"
    )


def _milestones_markdown(milestones) -> str:
    counts = milestones.period_counts
    lines = [
        f"- Selected-period milestones: **{counts.total_count}**",
        f"- On track: **{counts.on_track_count}**",
        f"- At risk: **{counts.at_risk_count}**",
        f"- Missed: **{counts.missed_count}**",
    ]
    next_ms = milestones.next_key_milestone
    if next_ms is not None and next_ms.name:
        lines.append(
            f"- Next key milestone: **{next_ms.name}** ({next_ms.planned_date})"
        )
    return "\n".join(lines) + "\n"


def _risks_markdown(risk) -> str:
    lines = [
        f"- Material risks selected: **{len(risk.risk_items)}**",
        f"- Availability: **{risk.availability.value}**",
    ]
    for item in risk.risk_items[:5]:
        tier = item.risk_tier or "unspecified"
        lines.append(
            f"- {item.source_type.value} `{item.source_row_id}` ({tier})"
        )
    if not risk.risk_items:
        lines.append("- No material risks selected from current evidence")
    return "\n".join(lines) + "\n"


def _readiness_markdown(readiness) -> str:
    score = (
        f"{readiness.overall_score_pct}%"
        if readiness.overall_score_pct is not None
        else "n/a"
    )
    lines = [
        f"- Overall readiness: **{score}**",
        f"- Status: **{readiness_status_label(readiness.status)}**",
        f"- Assessment confidence: **{readiness.assessment_confidence}**",
    ]
    for category in readiness.categories:
        cat_score = (
            f"{category.score_pct}%" if category.score_pct is not None else "n/a"
        )
        lines.append(f"- {category.category.value}: **{cat_score}**")
    return "\n".join(lines) + "\n"


def _recommendations_markdown(recommendations) -> str:
    if not recommendations:
        return "- No readiness recommendations generated\n"
    lines: list[str] = []
    for rec in recommendations[:10]:
        lines.append(
            f"- **{rec.title}** ({rec.priority.value}) — {rec.expected_business_impact}"
        )
    return "\n".join(lines) + "\n"
