"""Deterministic MVP executive narrative (governed as AI-authored content)."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.reports.contracts import ReportBuildContext, ReportSectionResult


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    del session, current_user
    kpis: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    for section in context.section_results:
        if section.key == "kpi_summary":
            kpis.extend(section.payload.get("items", []))
        elif section.key == "risks":
            risks.extend(section.payload.get("items", []))
        elif section.key == "recommendations":
            recommendations.extend(section.payload.get("items", []))

    highlights = [
        f"{item.get('kpi_key')}: "
        f"{item.get('numeric_value') or item.get('text_value') or 'no data'} "
        f"{item.get('unit') or ''}".strip()
        for item in kpis[:5]
    ]
    concerns = [
        f"{item.get('title')} ({item.get('risk_tier', 'unrated')})" for item in risks[:5]
    ]
    if highlights:
        opening = "Current KPI evidence shows " + "; ".join(highlights) + "."
    else:
        opening = "No current KPI values were available for this reporting period."
    risk_text = (
        f" There are {len(risks)} open or acknowledged risks and "
        f"{len(recommendations)} recorded mitigation recommendations."
    )
    summary = opening + risk_text
    headline = (
        "Attention required on reported risks"
        if risks
        else "No open risks identified in available evidence"
    )
    markdown = (
        "## Executive Summary\n\n"
        f"**{headline}.** {summary}\n\n"
        "_This deterministic narrative is governed as an AI section and requires human approval._"
    )
    return ReportSectionResult(
        key="ai_executive_summary",
        title="Executive Summary",
        payload={
            "headline": headline,
            "summary": summary,
            "highlights": highlights,
            "concerns": concerns,
        },
        markdown=markdown,
        provenance={"generator": "deterministic_template_v1", "llm_called": False},
        limitations=("Narrative is template-generated and does not add facts beyond prior sections.",),
        has_ai=True,
        requires_approval=bool(options.get("requires_approval", True)),
    )
