"""Durable snapshot job queue and scheduler helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    KpiSnapshotSchedule,
    Organisation,
    Project,
    TimeSeriesSnapshotJob,
    TimeSeriesSnapshotJobEvent,
)
from app.db.rls import set_service_role_context
from app.kpis.evaluation import evaluate_kpi
from app.time_series.aggregation import _bucket_start
from app.time_series.rollups import generate_rollups_for_scope
from app.time_series.retention import prune_expired_observations

logger = logging.getLogger(__name__)


def _system_user(org_id: UUID) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="time-series-engine@internal",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )


async def enqueue_snapshot_job(
    session: AsyncSession,
    *,
    org_id: UUID,
    job_type: str,
    idempotency_key: str,
    project_id: UUID | None = None,
    kpi_key: str | None = None,
    interval: str | None = None,
    bucket_start: datetime | None = None,
    bucket_end: datetime | None = None,
    request_payload: dict | None = None,
) -> TimeSeriesSnapshotJob:
    existing = (
        await session.execute(
            select(TimeSeriesSnapshotJob).where(
                TimeSeriesSnapshotJob.idempotency_key == idempotency_key,
                TimeSeriesSnapshotJob.status.in_(
                    ("queued", "running", "retry_scheduled", "cancellation_requested")
                ),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    job = TimeSeriesSnapshotJob(
        org_id=org_id,
        project_id=project_id,
        job_type=job_type,
        kpi_key=kpi_key,
        interval=interval,
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        idempotency_key=idempotency_key,
        request_payload=request_payload or {},
        next_attempt_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    session.add(
        TimeSeriesSnapshotJobEvent(
            org_id=org_id,
            job_id=job.id,
            event_type="enqueued",
            event_metadata={"job_type": job_type, "kpi_key": kpi_key},
        )
    )
    await session.flush()
    return job


async def plan_scheduled_jobs(session: AsyncSession) -> int:
    """Create bounded snapshot jobs from enabled schedules for all orgs."""
    await set_service_role_context(session)
    schedules = list(
        (
            await session.execute(
                select(KpiSnapshotSchedule).where(KpiSnapshotSchedule.is_enabled.is_(True))
            )
        ).scalars()
    )
    orgs = list((await session.execute(select(Organisation))).scalars())
    now = datetime.now(UTC)
    created = 0
    settings = get_settings()
    batch_limit = getattr(settings, "time_series_plan_batch_size", 50)
    for org in orgs:
        for schedule in schedules:
            interval_map = {
                "daily": "day",
                "weekly": "week",
                "monthly": "month",
                "quarterly": "quarter",
            }
            bucket_interval = interval_map[schedule.interval]
            bucket_start = _bucket_start(now, bucket_interval)
            if schedule.scope == "org":
                key = f"sched:{org.id}:{schedule.kpi_key}:{schedule.interval}:{bucket_start.isoformat()}"
                await enqueue_snapshot_job(
                    session,
                    org_id=org.id,
                    job_type="scheduled_snapshot",
                    idempotency_key=key,
                    kpi_key=schedule.kpi_key,
                    interval=schedule.interval,
                    bucket_start=bucket_start,
                    request_payload={"scope": "org"},
                )
                created += 1
            else:
                projects = list(
                    (
                        await session.execute(
                            select(Project).where(
                                Project.org_id == org.id,
                                Project.deleted_at.is_(None),
                            ).limit(batch_limit)
                        )
                    ).scalars()
                )
                for project in projects:
                    key = (
                        f"sched:{org.id}:{project.id}:{schedule.kpi_key}:"
                        f"{schedule.interval}:{bucket_start.isoformat()}"
                    )
                    await enqueue_snapshot_job(
                        session,
                        org_id=org.id,
                        project_id=project.id,
                        job_type="scheduled_snapshot",
                        idempotency_key=key,
                        kpi_key=schedule.kpi_key,
                        interval=schedule.interval,
                        bucket_start=bucket_start,
                        request_payload={"scope": "project"},
                    )
                    created += 1
                    if created >= batch_limit:
                        await session.flush()
                        logger.info("event=time_series_jobs_planned created=%s truncated=true", created)
                        return created
    await session.flush()
    logger.info("event=time_series_jobs_planned created=%s", created)
    return created


async def claim_jobs(session: AsyncSession, *, limit: int = 5) -> list[TimeSeriesSnapshotJob]:
    await set_service_role_context(session)
    now = datetime.now(UTC)
    settings = get_settings()
    stale_seconds = getattr(settings, "time_series_job_stale_seconds", 180)
    # Recover stale running jobs.
    await session.execute(
        update(TimeSeriesSnapshotJob)
        .where(
            TimeSeriesSnapshotJob.status == "running",
            TimeSeriesSnapshotJob.heartbeat_at < now - timedelta(seconds=stale_seconds),
        )
        .values(status="retry_scheduled", next_attempt_at=now)
    )
    rows = list(
        (
            await session.execute(
                select(TimeSeriesSnapshotJob)
                .where(
                    TimeSeriesSnapshotJob.status.in_(("queued", "retry_scheduled")),
                    or_(
                        TimeSeriesSnapshotJob.next_attempt_at.is_(None),
                        TimeSeriesSnapshotJob.next_attempt_at <= now,
                    ),
                )
                .order_by(TimeSeriesSnapshotJob.requested_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    worker_id = getattr(settings, "time_series_job_worker_id", "") or f"worker-{uuid4()}"
    for job in rows:
        job.status = "running"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.worker_id = worker_id
        job.attempt_count = (job.attempt_count or 0) + 1
        if job.queue_wait_ms is None:
            job.queue_wait_ms = int((now - job.requested_at).total_seconds() * 1000)
        session.add(
            TimeSeriesSnapshotJobEvent(
                org_id=job.org_id,
                job_id=job.id,
                event_type="claimed",
                event_metadata={"attempt": job.attempt_count, "worker_id": worker_id},
            )
        )
    await session.flush()
    return rows


async def process_job(session: AsyncSession, job: TimeSeriesSnapshotJob) -> None:
    started = perf_counter()
    await set_service_role_context(session)
    try:
        if job.job_type == "scheduled_snapshot" and job.kpi_key:
            user = _system_user(job.org_id)
            result = await evaluate_kpi(
                session,
                user,
                job.kpi_key,
                org_id=job.org_id,
                project_id=job.project_id,
                as_of=job.bucket_start,
                version=None if job.bucket_start is None else "1.0.0",
                persist_observation=True,
                source_type="scheduled",
                include_explainability=False,
            )
            # Also ensure daily rollup materialization for the KPI.
            if job.interval in {"daily", "weekly", "monthly", "quarterly"}:
                interval_map = {
                    "daily": "day",
                    "weekly": "week",
                    "monthly": "month",
                    "quarterly": "quarter",
                }
                await generate_rollups_for_scope(
                    session,
                    org_id=job.org_id,
                    kpi_key=job.kpi_key,
                    interval=interval_map[job.interval],
                    project_id=job.project_id,
                )
            job.result_data = {
                "status": result.status,
                "numeric_value": str(result.numeric_value) if result.numeric_value is not None else None,
            }
        elif job.job_type == "rollup" and job.kpi_key and job.interval:
            count = await generate_rollups_for_scope(
                session,
                org_id=job.org_id,
                kpi_key=job.kpi_key,
                interval=job.interval,
                project_id=job.project_id,
            )
            job.result_data = {"rollups": count}
        elif job.job_type == "retention":
            result = await prune_expired_observations(session, dry_run=False)
            job.result_data = {
                "raw_deleted": result.raw_deleted,
                "daily_rollups_deleted": result.daily_rollups_deleted,
            }
        else:
            # event_snapshot and others use request payload.
            payload = job.request_payload or {}
            kpi_key = job.kpi_key or payload.get("kpi_key")
            if kpi_key:
                user = _system_user(job.org_id)
                result = await evaluate_kpi(
                    session,
                    user,
                    kpi_key,
                    org_id=job.org_id,
                    project_id=job.project_id,
                    version=payload.get("version", "1.0.0"),
                    inputs=payload.get("inputs"),
                    persist_observation=True,
                    source_type="agent_event",
                    include_explainability=False,
                )
                job.result_data = {"status": result.status}
        job.status = "succeeded"
        job.completed_at = datetime.now(UTC)
        job.processing_ms = int((perf_counter() - started) * 1000)
        session.add(
            TimeSeriesSnapshotJobEvent(
                org_id=job.org_id,
                job_id=job.id,
                event_type="succeeded",
                event_metadata={"processing_ms": job.processing_ms},
            )
        )
        logger.info(
            "event=time_series_job_succeeded job_id=%s job_type=%s kpi_key=%s processing_ms=%s",
            job.id,
            job.job_type,
            job.kpi_key,
            job.processing_ms,
        )
    except Exception as exc:
        job.error_code = type(exc).__name__
        job.error_message = str(exc)[:500]
        if job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.completed_at = datetime.now(UTC)
        else:
            job.status = "retry_scheduled"
            job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=30 * job.attempt_count)
        job.processing_ms = int((perf_counter() - started) * 1000)
        session.add(
            TimeSeriesSnapshotJobEvent(
                org_id=job.org_id,
                job_id=job.id,
                event_type="failed",
                event_metadata={
                    "error_code": job.error_code,
                    "attempt": job.attempt_count,
                    "retry": job.status == "retry_scheduled",
                },
            )
        )
        logger.exception(
            "event=time_series_job_failed job_id=%s job_type=%s attempt=%s",
            job.id,
            job.job_type,
            job.attempt_count,
        )
    await session.flush()


async def process_snapshot_queue(session: AsyncSession) -> int:
    settings = get_settings()
    batch = getattr(settings, "time_series_job_poll_batch_size", 5)
    jobs = await claim_jobs(session, limit=batch)
    for job in jobs:
        await process_job(session, job)
    return len(jobs)
