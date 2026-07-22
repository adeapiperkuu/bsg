"""Built-in report section plugin registry."""

from __future__ import annotations

from typing import Any

from app.reports.contracts import ReportSectionResult, SectionBuilder


def failed_section(key: str, title: str, exc: Exception) -> ReportSectionResult:
    """Return a safe, explicit limitation instead of failing the whole report."""
    return ReportSectionResult(
        key=key,
        title=title,
        payload={"items": []},
        markdown=f"## {title}\n\nData was unavailable while this section was generated.",
        limitations=(f"{key}: {type(exc).__name__}: {str(exc)[:240]}",),
        provenance={"status": "unavailable"},
    )


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    return value


from app.reports.sections.ai_summary import build as build_ai_summary
from app.reports.sections.appendix import build as build_appendix
from app.reports.sections.charts import build as build_charts
from app.reports.sections.comparisons import build as build_comparisons
from app.reports.sections.evidence import build as build_evidence
from app.reports.sections.forecasts import build as build_forecasts
from app.reports.sections.kpi_summary import build as build_kpi_summary
from app.reports.sections.milestones import build as build_milestones
from app.reports.sections.recommendations import build as build_recommendations
from app.reports.sections.risks import build as build_risks
from app.reports.sections.trends import build as build_trends

SECTION_BUILDERS: dict[str, SectionBuilder] = {
    "kpi_summary": build_kpi_summary,
    "trends": build_trends,
    "comparisons": build_comparisons,
    "forecasts": build_forecasts,
    "milestones": build_milestones,
    "risks": build_risks,
    "recommendations": build_recommendations,
    "ai_executive_summary": build_ai_summary,
    "evidence": build_evidence,
    "appendix": build_appendix,
    "charts": build_charts,
}

__all__ = ["SECTION_BUILDERS", "failed_section", "jsonable"]
