"""Open risk alerts section."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import RiskAlert
from app.reports.contracts import EvidenceReference, ReportBuildContext, ReportSectionResult


async def build(
    session: AsyncSession,
    current_user: CurrentUser,
    context: ReportBuildContext,
    options: Mapping[str, Any],
) -> ReportSectionResult:
    from app.reports.sections import failed_section

    key, title = "risks", "Risks"
    try:
        stmt = select(RiskAlert).where(
            RiskAlert.org_id == context.org_id,
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_(("open", "acknowledged")),
        )
        if context.project_id is not None:
            stmt = stmt.where(RiskAlert.project_id == context.project_id)
        rows = list(
            (
                await session.execute(
                    stmt.order_by(RiskAlert.created_at.desc()).limit(
                        min(int(options.get("limit", 20)), 100)
                    )
                )
            ).scalars()
        )
        items = [
            {
                "id": str(row.id),
                "title": row.title,
                "detail": row.detail,
                "risk_tier": row.risk_tier.value,
                "alert_type": row.alert_type.value,
                "status": row.status.value,
                "slippage_probability": (
                    str(row.slippage_probability) if row.slippage_probability is not None else None
                ),
            }
            for row in rows
        ]
        evidence = tuple(
            EvidenceReference(
                source_table="risk_alerts",
                source_id=row.id,
                label=row.title,
                metadata={"risk_tier": row.risk_tier.value},
            )
            for row in rows
        )
        lines = [f"- **{item['title']}** — {item['risk_tier']}: {item['detail']}" for item in items]
        return ReportSectionResult(
            key=key,
            title=title,
            payload={"items": items},
            markdown="## Risks\n\n" + ("\n".join(lines) or "No open risks found."),
            evidence=evidence,
        )
    except Exception as exc:
        return failed_section(key, title, exc)
