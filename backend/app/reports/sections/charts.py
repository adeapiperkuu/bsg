"""Portable chart specifications derived from structured report sections."""

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
    del session, current_user, options
    charts: list[dict[str, Any]] = []
    for section in context.section_results:
        if section.key == "trends":
            for item in section.payload.get("trends", []):
                summary = item.get("summary", {})
                series = item.get("series", {})
                charts.append(
                    {
                        "type": "line",
                        "title": f"{summary.get('kpi_key', 'KPI')} trend",
                        "kpi_key": summary.get("kpi_key"),
                        "points": series.get("points", []),
                    }
                )
        elif section.key == "comparisons":
            for item in section.payload.get("comparisons", []):
                charts.append(
                    {
                        "type": "comparison",
                        "title": f"{item.get('kpi_key', 'KPI')} comparison",
                        "kpi_key": item.get("kpi_key"),
                        "series": item.get("series", []),
                    }
                )
    return ReportSectionResult(
        key="charts",
        title="Charts",
        payload={"charts": charts},
        markdown=f"## Charts\n\n{len(charts)} structured chart specification(s) generated.",
        provenance={"format": "portable_json_spec"},
    )
