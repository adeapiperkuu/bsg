"""Scheduler operations; transaction ownership remains with the caller."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.rls import set_service_role_context
from app.reports.jobs import plan_scheduled_jobs, process_report_queue

logger = logging.getLogger(__name__)


async def run_report_planner(session: AsyncSession) -> int:
    settings = get_settings()
    if not settings.report_jobs_enabled:
        return 0
    await set_service_role_context(session)
    created = await plan_scheduled_jobs(session)
    if created:
        logger.info("event=report_planner_complete created=%s", created)
    return created


async def run_report_queue_poll(session: AsyncSession) -> int:
    settings = get_settings()
    if not settings.report_jobs_enabled:
        return 0
    await set_service_role_context(session)
    processed = await process_report_queue(session)
    if processed:
        logger.info("event=report_queue_poll_complete processed=%s", processed)
    return processed
