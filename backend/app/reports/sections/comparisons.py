"""Cross-period and cross-scope KPI comparisons."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.reports.contracts import ReportBuildContext, ReportSectionResult
from app.time_series.aggregation import compare_scopes


def _kpi_keys(context: ReportBuildContext, options: Mapping[str, Any]) -> list[str]:
    configured = [str(value) for value in options.get("kpi_keys", [])]
    if configured:
        return configured
    for section in context.section_results:
        if section.key == "kpi_summary":
            return [str(item["kpi_key"]) for item in section.payload.get("items", [])]
    return []


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "comparisons", "Comparisons"
    values: list[dict[str, Any]] = []
    limitations: list[str] = []
    mode = str(options.get("mode", "period"))
    interval = str(options.get("interval", "week"))
    for kpi_key in _kpi_keys(context, options):
        try:
            result = await compare_scopes(
                session,
                current_user,
                kpi_key,
                mode=mode,
                interval=interval,
                org_id=context.org_id,
                project_id=context.project_id,
                date_from=context.period_start,
                date_to=context.period_end,
            )
            values.append(result.model_dump(mode="json"))
        except Exception as exc:
            limitations.append(f"{kpi_key}: {type(exc).__name__}: {str(exc)[:200]}")
    if not values and limitations:
        return failed_section(key, title, RuntimeError("; ".join(limitations)))
    lines = [f"- **{item['kpi_key']}**: {len(item['series'])} comparison series" for item in values]
    return ReportSectionResult(
        key=key,
        title=title,
        payload={"comparisons": values, "mode": mode, "interval": interval},
        markdown="## Comparisons\n\n" + ("\n".join(lines) or "No comparison data was configured."),
        limitations=tuple(limitations),
    )
