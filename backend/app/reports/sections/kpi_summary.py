"""Current KPI values section."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.kpis.evaluation import evaluate_kpi
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult
from app.time_series.aggregation import latest_observation


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "kpi_summary", "KPI Summary"
    items: list[dict[str, Any]] = []
    evidence: list[EvidenceReference] = []
    limitations: list[str] = []
    for kpi_key in options.get("kpi_keys", []):
        try:
            result = await evaluate_kpi(
                session,
                current_user,
                str(kpi_key),
                org_id=context.org_id,
                project_id=context.project_id,
                include_explainability=True,
            )
            items.append(result.model_dump(mode="json"))
            observation = await latest_observation(
                session,
                current_user,
                str(kpi_key),
                org_id=context.org_id,
                project_id=context.project_id,
                date_from=context.period_start,
                date_to=context.period_end,
            )
            if observation is not None:
                evidence.append(
                    EvidenceReference(
                        source_table="kpi_observations",
                        source_id=observation.id,
                        observation_id=observation.id,
                        kpi_key=str(kpi_key),
                        label=f"Latest {kpi_key} observation",
                        metadata={"observed_at": observation.observed_at.isoformat()},
                    )
                )
        except Exception as exc:
            limitations.append(f"{kpi_key}: {type(exc).__name__}: {str(exc)[:200]}")
    if not items and limitations:
        return failed_section(key, title, RuntimeError("; ".join(limitations)))
    lines = [
        f"- **{item['kpi_key']}**: "
        f"{item.get('numeric_value') or item.get('text_value') or 'No data'} "
        f"{item.get('unit') or ''} ({item.get('status', 'unknown')})".rstrip()
        for item in items
    ]
    return ReportSectionResult(
        key=key,
        title=title,
        payload={"items": items},
        markdown="## KPI Summary\n\n" + ("\n".join(lines) or "No KPI values were configured."),
        evidence=tuple(evidence),
        provenance={"kpi_keys": [str(key) for key in options.get("kpi_keys", [])]},
        limitations=tuple(limitations),
    )
