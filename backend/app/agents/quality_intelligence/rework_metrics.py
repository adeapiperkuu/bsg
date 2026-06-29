"""Derive rework volume and schedule impact from item-level rework logs."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReworkLog, ThroughputSnapshot


REWORK_MINUTES_PER_ITEM = 15
WORKING_MINUTES_PER_DAY = 480


def iso_week_date_range(iso_year: int, iso_week: int) -> tuple[date, date]:
    """Return Monday–Sunday dates for an ISO week."""
    start = date.fromisocalendar(iso_year, iso_week, 1)
    end = date.fromisocalendar(iso_year, iso_week, 7)
    return start, end


async def compute_rework_impact(
    session: AsyncSession,
    project_id: UUID,
    *,
    iso_year: int | None = None,
    iso_week: int | None = None,
    lookback_days: int = 14,
) -> dict[str, object]:
    """Aggregate rework logs into volume units, time estimate, and affected item ids."""
    end = date.today()
    start = end - timedelta(days=lookback_days)
    if iso_year is not None and iso_week is not None:
        start, end = iso_week_date_range(iso_year, iso_week)

    rows = list(
        (
            await session.execute(
                select(ReworkLog)
                .where(
                    ReworkLog.project_id == project_id,
                    ReworkLog.rework_date >= start,
                    ReworkLog.rework_date <= end,
                )
                .order_by(ReworkLog.rework_date.desc())
            )
        ).scalars()
    )

    volume = len(rows)
    item_ids = list({r.item_id for r in rows})
    minutes = volume * REWORK_MINUTES_PER_ITEM
    days_estimate = round(minutes / WORKING_MINUTES_PER_DAY, 1) if volume else 0.0

    throughput = (
        await session.execute(
            select(func.avg(ThroughputSnapshot.rolling_7day_units))
            .where(ThroughputSnapshot.project_id == project_id)
        )
    ).scalar_one_or_none()
    daily_units = float(throughput) if throughput else None
    if daily_units and daily_units > 0:
        days_from_throughput = round(volume / daily_units, 1)
        days_estimate = max(days_estimate, days_from_throughput)

    return {
        "rework_volume_units": volume,
        "rework_time_estimate_days": days_estimate,
        "affected_batch_ids": item_ids[:50],
        "window_start": str(start),
        "window_end": str(end),
    }
