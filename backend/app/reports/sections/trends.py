"""KPI trend section."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult
from app.time_series.aggregation import build_trend_summary, series_for_kpi


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "trends", "Trends"
    trends: list[dict[str, Any]] = []
    evidence: list[EvidenceReference] = []
    limitations: list[str] = []
    interval = str(options.get("interval", "week"))
    for kpi_key in options.get("kpi_keys", []):
        try:
            summary = await build_trend_summary(
                session,
                current_user,
                str(kpi_key),
                org_id=context.org_id,
                project_id=context.project_id,
                date_from=context.period_start,
                date_to=context.period_end,
            )
            series = await series_for_kpi(
                session,
                current_user,
                str(kpi_key),
                interval=interval,
                org_id=context.org_id,
                project_id=context.project_id,
                date_from=context.period_start,
                date_to=context.period_end,
            )
            trends.append(
                {
                    "summary": summary.model_dump(mode="json"),
                    "series": series.model_dump(mode="json"),
                }
            )
            for observation in (summary.latest, summary.previous):
                if observation is not None:
                    evidence.append(
                        EvidenceReference(
                            source_table="kpi_observations",
                            source_id=observation.id,
                            observation_id=observation.id,
                            kpi_key=str(kpi_key),
                            label=f"{kpi_key} trend observation",
                        )
                    )
        except Exception as exc:
            limitations.append(f"{kpi_key}: {type(exc).__name__}: {str(exc)[:200]}")
    if not trends and limitations:
        return failed_section(key, title, RuntimeError("; ".join(limitations)))
    lines = [
        f"- **{item['summary']['kpi_key']}**: "
        f"{item['summary']['semantic_favorability']} "
        f"({item['summary'].get('percentage_change') or 'n/a'}%)"
        for item in trends
    ]
    return ReportSectionResult(
        key=key,
        title=title,
        payload={"trends": trends, "interval": interval},
        markdown="## Trends\n\n" + ("\n".join(lines) or "No trend data was available."),
        evidence=tuple(evidence),
        limitations=tuple(limitations),
    )
