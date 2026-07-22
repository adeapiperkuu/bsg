"""Mitigation recommendation section."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import MitigationRecommendation
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "recommendations", "Recommendations"
    try:
        stmt = select(MitigationRecommendation).where(
            MitigationRecommendation.org_id == context.org_id,
            MitigationRecommendation.deleted_at.is_(None),
        )
        if context.project_id is not None:
            stmt = stmt.where(MitigationRecommendation.project_id == context.project_id)
        rows = list(
            (
                await session.execute(
                    stmt.order_by(MitigationRecommendation.created_at.desc()).limit(
                        min(int(options.get("limit", 20)), 100)
                    )
                )
            ).scalars()
        )
        items = [
            {
                "id": str(row.id),
                "title": row.title,
                "description": row.description,
                "severity": row.severity.value,
                "confidence_score": str(row.confidence_score),
                "status": row.status.value,
                "source_risk_id": str(row.source_risk_id) if row.source_risk_id else None,
            }
            for row in rows
        ]
        evidence = tuple(
            EvidenceReference(
                source_table="mitigation_recommendations",
                source_id=row.id,
                label=row.title,
                metadata={"severity": row.severity.value, "status": row.status.value},
            )
            for row in rows
        )
        lines = [
            f"- **{item['title']}** — {item['severity']}: "
            f"{item['description'] or 'No additional detail'}"
            for item in items
        ]
        return ReportSectionResult(
            key=key,
            title=title,
            payload={"items": items, "domain": options.get("domain")},
            markdown="## Recommendations\n\n" + ("\n".join(lines) or "No recommendations found."),
            evidence=evidence,
        )
    except Exception as exc:
        return failed_section(key, title, exc)
