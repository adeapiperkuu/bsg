"""Evidence index section built from prior section citations."""

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
    seen: set[tuple[str, str | None, str | None]] = set()
    references = []
    for section in context.section_results:
        for ref in section.evidence:
            identity = (
                ref.source_table,
                str(ref.source_id) if ref.source_id else None,
                str(ref.observation_id) if ref.observation_id else None,
            )
            if identity in seen:
                continue
            seen.add(identity)
            references.append(ref)
    payload = [
        {
            "source_table": ref.source_table,
            "source_id": str(ref.source_id) if ref.source_id else None,
            "kpi_key": ref.kpi_key,
            "observation_id": str(ref.observation_id) if ref.observation_id else None,
            "label": ref.label,
            "metadata": dict(ref.metadata),
        }
        for ref in references
    ]
    lines = [
        f"- {item['label'] or item['source_table']} "
        f"(`{item['source_table']}:{item['source_id'] or 'aggregate'}`)"
        for item in payload
    ]
    return ReportSectionResult(
        key="evidence",
        title="Evidence",
        payload={"references": payload},
        markdown="## Evidence\n\n" + ("\n".join(lines) or "No evidence references were captured."),
        evidence=tuple(references),
        provenance={"reference_count": len(references)},
    )
