"""Delivery Performance Agent cron/manual entrypoint."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.confidence import (
    ConfidenceStatus,
    ON_TRACK_THRESHOLD,
    classify_confidence_status,
)
from app.agents.delivery.services.scoring_service import (
    DeliveryScoringRunResult,
    run_delivery_scoring,
)

__all__ = [
    "ConfidenceStatus",
    "DeliveryScoringRunResult",
    "ON_TRACK_THRESHOLD",
    "classify_confidence_status",
    "classify_delivery_confidence",
    "run_delivery_scoring",
    "run_delivery_scoring_for_all_projects",
    "run_delivery_scoring_for_project",
]


def classify_delivery_confidence(
    score_pct: Decimal,
    *,
    on_track_threshold: Decimal = ON_TRACK_THRESHOLD,
) -> ConfidenceStatus:
    """Backward-compatible alias for milestone confidence classification."""
    return classify_confidence_status(score_pct, on_track_threshold=on_track_threshold)


async def run_delivery_scoring_for_project(
    session: AsyncSession,
    project_id: UUID,
    *,
    as_of_date: date | None = None,
) -> DeliveryScoringRunResult:
    """Run delivery scoring for one project inside the caller's transaction."""
    return await run_delivery_scoring(
        session,
        project_id=project_id,
        as_of_date=as_of_date,
    )


async def run_delivery_scoring_for_all_projects(
    session: AsyncSession,
    *,
    as_of_date: date | None = None,
) -> list[DeliveryScoringRunResult]:
    """Run delivery scoring for every active project inside the caller's transaction."""
    from sqlalchemy import select

    from app.db.models import Project

    project_rows = await session.execute(
        select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name.asc())
    )
    results: list[DeliveryScoringRunResult] = []
    for project in project_rows.scalars():
        results.append(
            await run_delivery_scoring(
                session,
                project_id=project.id,
                as_of_date=as_of_date,
                project=project,
            )
        )
    return results
