from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ThroughputSnapshot
from app.schemas.domain import ThroughputSnapshotCreate


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

    rolling_7day_units = await calculate_rolling_7day_units(session, project.id)
    if existing is None:
        snapshot = ThroughputSnapshot(
            project_id=project.id,
            org_id=project.org_id,
            snapshot_date=payload.snapshot_date,
            units_completed=payload.units_completed,
            units_forecast=payload.units_forecast,
            rolling_7day_units=rolling_7day_units,
        )
        session.add(snapshot)
        await session.flush()
        return snapshot

    existing.units_completed = payload.units_completed
    existing.units_forecast = payload.units_forecast
    existing.rolling_7day_units = rolling_7day_units
    await session.flush()
    return existing


async def calculate_rolling_7day_units(session: AsyncSession, project_id: UUID) -> int | None:
    rows = (
        await session.execute(
            select(ThroughputSnapshot.units_completed)
            .where(ThroughputSnapshot.project_id == project_id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(6)
        )
    ).scalars()
    values = list(rows)
    return sum(values) if values else None
