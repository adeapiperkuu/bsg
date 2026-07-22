"""Project milestone section."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import Milestone
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "milestones", "Milestones"
    try:
        stmt = select(Milestone).where(
            Milestone.org_id == context.org_id,
            Milestone.deleted_at.is_(None),
        )
        if context.project_id is not None:
            stmt = stmt.where(Milestone.project_id == context.project_id)
        rows = list(
            (
                await session.execute(
                    stmt.order_by(Milestone.planned_date.asc()).limit(
                        min(int(options.get("limit", 20)), 100)
                    )
                )
            ).scalars()
        )
        items = [
            {
                "id": str(row.id),
                "name": row.name,
                "description": row.description,
                "planned_date": row.planned_date.isoformat(),
                "actual_date": row.actual_date.isoformat() if row.actual_date else None,
                "status": row.status.value,
            }
            for row in rows
        ]
        evidence = tuple(
            EvidenceReference(
                source_table="milestones",
                source_id=row.id,
                label=row.name,
                metadata={"status": row.status.value},
            )
            for row in rows
        )
        lines = [
            f"- **{item['name']}** — {item['status']} (planned {item['planned_date']})"
            for item in items
        ]
        return ReportSectionResult(
            key=key,
            title=title,
            payload={"items": items},
            markdown="## Milestones\n\n" + ("\n".join(lines) or "No milestones found."),
            evidence=evidence,
        )
    except Exception as exc:
        return failed_section(key, title, exc)
