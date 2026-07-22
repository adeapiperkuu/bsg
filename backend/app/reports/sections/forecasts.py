"""Deterministic KPI forecast section."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult
from app.time_series.aggregation import latest_observation
from app.time_series.forecasting import forecast_kpi


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "forecasts", "Forecasts"
    forecasts: list[dict[str, Any]] = []
    evidence: list[EvidenceReference] = []
    limitations: list[str] = []
    for kpi_key in options.get("kpi_keys", []):
        try:
            result = await forecast_kpi(
                session,
                current_user,
                str(kpi_key),
                horizon=int(options.get("horizon", 4)),
                org_id=context.org_id,
                project_id=context.project_id,
                date_from=context.period_start,
                date_to=context.period_end,
            )
            forecasts.append(result.model_dump(mode="json"))
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
                        label=f"{kpi_key} forecast baseline",
                    )
                )
        except Exception as exc:
            limitations.append(f"{kpi_key}: {type(exc).__name__}: {str(exc)[:200]}")
    if not forecasts and limitations:
        return failed_section(key, title, RuntimeError("; ".join(limitations)))
    lines = [
        f"- **{item['kpi_key']}**: {item['status']}, "
        f"{len(item.get('points') or [])} forecast points"
        for item in forecasts
    ]
    return ReportSectionResult(
        key=key,
        title=title,
        payload={"forecasts": forecasts},
        markdown="## Forecasts\n\n" + ("\n".join(lines) or "No forecasts were configured."),
        limitations=tuple(limitations),
        evidence=tuple(evidence),
        provenance={"method": "deterministic_time_series"},
    )
