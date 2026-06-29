import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.throughput import sum_recent_units_completed
from app.agents.delivery.services.scoring_service import run_delivery_scoring
from app.db.models import Project, ThroughputSnapshot
from app.schemas.domain import ThroughputSnapshotCreate

logger = logging.getLogger(__name__)


async def upsert_throughput_snapshot(
    session: AsyncSession,
    project: Project,
    payload: ThroughputSnapshotCreate,
) -> ThroughputSnapshot:
    existing = (
        await session.execute(
            select(ThroughputSnapshot).where(
                ThroughputSnapshot.project_id == project.id,
                ThroughputSnapshot.snapshot_date == payload.snapshot_date,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        snapshot = ThroughputSnapshot(
            project_id=project.id,
            org_id=project.org_id,
            snapshot_date=payload.snapshot_date,
            units_completed=payload.units_completed,
            units_forecast=payload.units_forecast,
            rolling_7day_units=None,
        )
        session.add(snapshot)
    else:
        existing.units_completed = payload.units_completed
        existing.units_forecast = payload.units_forecast
        existing.rolling_7day_units = None
        snapshot = existing

    # Flush before computing rolling so today's row is visible in the date window.
    await session.flush()
    snapshot.rolling_7day_units = await _compute_rolling_7day_units(
        session, project.id, payload.snapshot_date
    )
    await session.flush()

    # Scoring runs in a savepoint so a failure cannot corrupt the snapshot.
    try:
        async with session.begin_nested():
            await run_delivery_scoring(
                session,
                project_id=project.id,
                as_of_date=payload.snapshot_date,
                project=project,
            )
    except Exception:
        logger.warning(
            "Delivery scoring failed for project %s on %s; snapshot preserved.",
            project.id,
            payload.snapshot_date,
            exc_info=True,
        )

    return snapshot


async def _compute_rolling_7day_units(
    session: AsyncSession,
    project_id: UUID,
    snapshot_date: date,
) -> int | None:
    """Sum units_completed for the 7-calendar-day window ending on snapshot_date."""
    cutoff = snapshot_date - timedelta(days=6)
    rows = (
        await session.execute(
            select(ThroughputSnapshot.units_completed)
            .where(
                ThroughputSnapshot.project_id == project_id,
                ThroughputSnapshot.snapshot_date >= cutoff,
                ThroughputSnapshot.snapshot_date <= snapshot_date,
            )
            .order_by(ThroughputSnapshot.snapshot_date.desc())
        )
    ).scalars()
    return sum_recent_units_completed(list(rows))
