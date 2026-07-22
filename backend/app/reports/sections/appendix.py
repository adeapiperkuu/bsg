"""Report generation appendix."""

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
    payload = {
        "template_key": context.template_key,
        "template_version": context.template_version,
        "audience": context.audience,
        "period_start": context.period_start.isoformat() if context.period_start else None,
        "period_end": context.period_end.isoformat() if context.period_end else None,
        "generation_mode": context.generation_mode,
        "section_keys": [section.key for section in context.section_results],
    }
    markdown = (
        "## Appendix\n\n"
        f"- Template: `{context.template_key}@{context.template_version}`\n"
        f"- Audience: {context.audience}\n"
        f"- Generation mode: {context.generation_mode}\n"
        f"- Reporting period: {payload['period_start'] or 'unspecified'} to "
        f"{payload['period_end'] or 'current'}"
    )
    return ReportSectionResult(
        key="appendix",
        title="Appendix",
        payload=payload,
        markdown=markdown,
        provenance={"framework_version": "18.3-mvp"},
    )
