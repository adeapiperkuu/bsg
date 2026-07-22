"""Interval rollup generation for KPI observations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import mean, median
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KpiObservation, KpiObservationRollup
from app.time_series.aggregation import _bucket_start

logger = logging.getLogger(__name__)


def _bucket_end(start: datetime, interval: str) -> datetime:
    if interval == "day":
        return start + timedelta(days=1)
    if interval == "week":
        return start + timedelta(days=7)
    if interval == "month":
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
    if interval == "quarter":
        month = start.month + 3
        year = start.year
        if month > 12:
            month -= 12
            year += 1
        return start.replace(year=year, month=month)
    return start + timedelta(hours=1)


async def generate_rollups_for_scope(
    session: AsyncSession,
    *,
    org_id: UUID,
    kpi_key: str,
    interval: str,
    project_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    """Build idempotent rollup rows from raw observations. Returns upsert count."""
    end = date_to or datetime.now(UTC)
    start = date_from or (end - timedelta(days=90))
    stmt = select(KpiObservation).where(
        KpiObservation.org_id == org_id,
        KpiObservation.kpi_key == kpi_key,
        KpiObservation.observed_at >= start,
        KpiObservation.observed_at <= end,
        KpiObservation.status == "ok",
    )
    if project_id is not None:
        stmt = stmt.where(KpiObservation.project_id == project_id)
    rows = list((await session.execute(stmt.order_by(KpiObservation.observed_at.asc()))).scalars())
    buckets: dict[tuple, list[KpiObservation]] = {}
    for row in rows:
        key = (
            row.project_id,
            row.department_key,
            row.agent_key,
            row.definition_version,
            row.calculator_version,
            _bucket_start(row.observed_at, interval),
        )
        buckets.setdefault(key, []).append(row)

    written = 0
    for (
        proj_id,
        department_key,
        agent_key,
        definition_version,
        calculator_version,
        bucket_start,
    ), items in buckets.items():
        values = [float(i.numeric_value) for i in items if i.numeric_value is not None]
        existing = (
            await session.execute(
                select(KpiObservationRollup).where(
                    KpiObservationRollup.org_id == org_id,
                    KpiObservationRollup.kpi_key == kpi_key,
                    KpiObservationRollup.bucket_interval == interval,
                    KpiObservationRollup.bucket_start == bucket_start,
                    KpiObservationRollup.project_id == proj_id,
                    KpiObservationRollup.department_key == department_key,
                    KpiObservationRollup.agent_key == agent_key,
                    KpiObservationRollup.definition_version == definition_version,
                    KpiObservationRollup.calculator_version == calculator_version,
                )
            )
        ).scalar_one_or_none()
        payload = {
            "observation_count": len(items),
            "min_value": Decimal(str(min(values))) if values else None,
            "max_value": Decimal(str(max(values))) if values else None,
            "avg_value": Decimal(str(mean(values))) if values else None,
            "median_value": Decimal(str(median(values))) if values else None,
            "latest_value": items[-1].numeric_value,
            "latest_text_value": items[-1].text_value,
            "source_observation_ids": [str(i.id) for i in items],
            "lineage_refs": {"source": "kpi_observations", "count": len(items)},
            "generated_at": datetime.now(UTC),
            "bucket_end": _bucket_end(bucket_start, interval),
            "calculator_key": items[-1].calculator_key,
        }
        if existing is None:
            session.add(
                KpiObservationRollup(
                    org_id=org_id,
                    project_id=proj_id,
                    department_key=department_key,
                    agent_key=agent_key,
                    kpi_key=kpi_key,
                    definition_version=definition_version,
                    calculator_version=calculator_version,
                    bucket_interval=interval,
                    bucket_start=bucket_start,
                    **payload,
                )
            )
            written += 1
        else:
            # Rollups are derived caches; regenerate in place is allowed only for rollup table.
            for key, value in payload.items():
                setattr(existing, key, value)
            written += 1
    await session.flush()
    logger.info(
        "event=kpi_rollups_generated org_id=%s kpi_key=%s interval=%s count=%s",
        org_id,
        kpi_key,
        interval,
        written,
    )
    return written
