"""Retention and safe pruning for KPI observations and rollups."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KpiObservation, KpiObservationRollup

logger = logging.getLogger(__name__)

RAW_RETENTION_DAYS = 400
DAILY_ROLLUP_RETENTION_DAYS = 365 * 3
BATCH_LIMIT = 500


@dataclass(frozen=True, slots=True)
class RetentionResult:
    raw_deleted: int
    daily_rollups_deleted: int
    dry_run: bool


async def prune_expired_observations(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RetentionResult:
    """Prune raw observations older than 400 days and daily rollups older than 3 years.

    Never deletes rows with legal/audit/report holds. Monthly/quarterly rollups are kept.
    """
    ref = now or datetime.now(UTC)
    raw_cutoff = ref - timedelta(days=RAW_RETENTION_DAYS)
    daily_cutoff = ref - timedelta(days=DAILY_ROLLUP_RETENTION_DAYS)

    raw_ids = list(
        (
            await session.execute(
                select(KpiObservation.id)
                .where(
                    KpiObservation.observed_at < raw_cutoff,
                    KpiObservation.legal_hold.is_(False),
                    KpiObservation.audit_hold.is_(False),
                    KpiObservation.report_hold.is_(False),
                    or_(
                        KpiObservation.retention_class == "raw",
                        KpiObservation.retention_class.is_(None),
                    ),
                )
                .limit(BATCH_LIMIT)
            )
        ).scalars()
    )
    daily_ids = list(
        (
            await session.execute(
                select(KpiObservationRollup.id)
                .where(
                    KpiObservationRollup.bucket_interval == "day",
                    KpiObservationRollup.bucket_start < daily_cutoff,
                    KpiObservationRollup.legal_hold.is_(False),
                    KpiObservationRollup.audit_hold.is_(False),
                    KpiObservationRollup.report_hold.is_(False),
                )
                .limit(BATCH_LIMIT)
            )
        ).scalars()
    )

    raw_deleted = len(raw_ids)
    daily_deleted = len(daily_ids)
    if not dry_run:
        if raw_ids:
            await session.execute(delete(KpiObservation).where(KpiObservation.id.in_(raw_ids)))
        if daily_ids:
            await session.execute(
                delete(KpiObservationRollup).where(KpiObservationRollup.id.in_(daily_ids))
            )
        await session.flush()

    logger.info(
        "event=kpi_retention_prune dry_run=%s raw_deleted=%s daily_rollups_deleted=%s",
        dry_run,
        raw_deleted,
        daily_deleted,
    )
    return RetentionResult(
        raw_deleted=raw_deleted,
        daily_rollups_deleted=daily_deleted,
        dry_run=dry_run,
    )
