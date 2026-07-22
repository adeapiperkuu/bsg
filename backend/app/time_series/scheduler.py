"""Scheduler entrypoints for the Platform Time-Series Engine."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.db.rls import set_service_role_context
from app.db.session import session_scope
from app.time_series.jobs import plan_scheduled_jobs, process_snapshot_queue
from app.time_series.retention import prune_expired_observations

logger = logging.getLogger(__name__)


async def run_time_series_planner() -> None:
    settings = get_settings()
    if not settings.time_series_jobs_enabled:
        return
    async with session_scope() as session:
        try:
            await set_service_role_context(session)
            created = await plan_scheduled_jobs(session)
            await session.commit()
            if created:
                logger.info("event=time_series_planner_complete created=%s", created)
        except Exception:
            await session.rollback()
            logger.exception("event=time_series_planner_failed")


async def run_time_series_queue_poll() -> None:
    settings = get_settings()
    if not settings.time_series_jobs_enabled:
        return
    async with session_scope() as session:
        try:
            await set_service_role_context(session)
            processed = await process_snapshot_queue(session)
            await session.commit()
            if processed:
                logger.info("event=time_series_queue_poll_complete processed=%s", processed)
        except Exception:
            await session.rollback()
            logger.exception("event=time_series_queue_poll_failed")


async def run_time_series_retention() -> None:
    settings = get_settings()
    if not settings.time_series_retention_enabled:
        return
    async with session_scope() as session:
        try:
            await set_service_role_context(session)
            result = await prune_expired_observations(session, dry_run=False)
            await session.commit()
            logger.info(
                "event=time_series_retention_complete raw_deleted=%s daily_rollups_deleted=%s",
                result.raw_deleted,
                result.daily_rollups_deleted,
            )
        except Exception:
            await session.rollback()
            logger.exception("event=time_series_retention_failed")
