"""Durable report generation and export job queue."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    ReportInstance,
    ReportJob,
    ReportJobEvent,
    ReportSchedule,
    ReportTemplate,
    User,
)
from app.db.rls import set_service_role_context
from app.reports.adapters import backfill_historical_reports
from app.reports.contracts import ReportBuildContext
from app.reports.engine import build_report
from app.reports.exports import create_report_export

logger = logging.getLogger(__name__)
JOB_TYPES = frozenset(
    {"on_demand_generate", "scheduled_generate", "export_render", "regenerate", "backfill"}
)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _job_user(session: AsyncSession, job: ReportJob) -> CurrentUser:
    requested_by = (job.request_payload or {}).get("requested_by")
    if requested_by:
        user = await session.get(User, UUID(str(requested_by)))
        if user is not None:
            return CurrentUser(
                id=user.id,
                org_id=user.org_id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
            )
    return CurrentUser(
        id=uuid4(),
        org_id=job.org_id,
        email="report-worker@internal",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )


async def enqueue_report_job(
    session: AsyncSession,
    *,
    org_id: UUID,
    job_type: str,
    idempotency_key: str,
    project_id: UUID | None = None,
    report_instance_id: UUID | None = None,
    template_id: UUID | None = None,
    export_format: str | None = None,
    request_payload: dict[str, Any] | None = None,
) -> ReportJob:
    if job_type not in JOB_TYPES:
        raise ValueError(f"Unknown report job type '{job_type}'.")
    existing = (
        await session.execute(
            select(ReportJob).where(
                ReportJob.idempotency_key == idempotency_key,
                ReportJob.status.in_(
                    ("queued", "running", "retry_scheduled", "cancellation_requested")
                ),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    job = ReportJob(
        org_id=org_id,
        project_id=project_id,
        job_type=job_type,
        report_instance_id=report_instance_id,
        template_id=template_id,
        export_format=export_format,
        idempotency_key=idempotency_key,
        request_payload=request_payload or {},
        next_attempt_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    session.add(
        ReportJobEvent(
            org_id=org_id,
            job_id=job.id,
            event_type="enqueued",
            event_metadata={"job_type": job_type},
        )
    )
    await session.flush()
    return job


def _next_run(now: datetime, interval: str) -> datetime:
    if interval == "daily":
        return now + timedelta(days=1)
    if interval == "weekly":
        return now + timedelta(weeks=1)
    if interval == "monthly":
        return now + timedelta(days=30)
    if interval == "quarterly":
        return now + timedelta(days=91)
    raise ValueError(f"Unsupported schedule interval '{interval}'.")


async def plan_scheduled_jobs(session: AsyncSession) -> int:
    """Enqueue due schedules. Scheduled generation is always draft-only."""
    await set_service_role_context(session)
    now = datetime.now(UTC)
    schedules = list(
        (
            await session.execute(
                select(ReportSchedule)
                .where(
                    ReportSchedule.is_enabled.is_(True),
                    or_(
                        ReportSchedule.next_run_at.is_(None),
                        ReportSchedule.next_run_at <= now,
                    ),
                )
                .order_by(ReportSchedule.next_run_at.asc().nullsfirst())
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).scalars()
    )
    for schedule in schedules:
        if schedule.create_as_status != "draft":
            raise ValueError("Report schedules may only create drafts.")
        run_key = schedule.next_run_at or now.replace(second=0, microsecond=0)
        request_payload = {
            **dict(schedule.config or {}),
            "schedule_id": str(schedule.id),
            "audience": schedule.audience,
            "create_as_status": "draft",
            "requested_by": str(schedule.created_by) if schedule.created_by else None,
        }
        await enqueue_report_job(
            session,
            org_id=schedule.org_id,
            project_id=schedule.project_id,
            template_id=schedule.template_id,
            job_type="scheduled_generate",
            idempotency_key=f"report-schedule:{schedule.id}:{run_key.isoformat()}",
            request_payload=request_payload,
        )
        schedule.last_run_at = now
        schedule.next_run_at = _next_run(now, schedule.interval)
    await session.flush()
    logger.info("event=report_jobs_planned created=%s", len(schedules))
    return len(schedules)


async def claim_jobs(session: AsyncSession, *, limit: int = 5) -> list[ReportJob]:
    await set_service_role_context(session)
    now = datetime.now(UTC)
    settings = get_settings()
    await session.execute(
        update(ReportJob)
        .where(
            ReportJob.status == "running",
            ReportJob.heartbeat_at < now - timedelta(seconds=settings.report_job_stale_seconds),
        )
        .values(status="retry_scheduled", next_attempt_at=now)
    )
    jobs = list(
        (
            await session.execute(
                select(ReportJob)
                .where(
                    ReportJob.status.in_(("queued", "retry_scheduled")),
                    or_(ReportJob.next_attempt_at.is_(None), ReportJob.next_attempt_at <= now),
                )
                .order_by(ReportJob.requested_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).scalars()
    )
    worker_id = settings.report_job_worker_id or f"report-worker-{uuid4()}"
    for job in jobs:
        job.status = "running"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.worker_id = worker_id
        job.attempt_count = (job.attempt_count or 0) + 1
        if job.queue_wait_ms is None:
            job.queue_wait_ms = int((now - job.requested_at).total_seconds() * 1000)
        session.add(
            ReportJobEvent(
                org_id=job.org_id,
                job_id=job.id,
                event_type="claimed",
                event_metadata={"attempt": job.attempt_count, "worker_id": worker_id},
            )
        )
    await session.flush()
    return jobs


async def _generate(session: AsyncSession, job: ReportJob) -> ReportInstance:
    payload = job.request_payload or {}
    template = await session.get(ReportTemplate, job.template_id) if job.template_id else None
    if template is None:
        raise ValueError("Generation job requires an existing template_id.")
    user = await _job_user(session, job)
    context = ReportBuildContext(
        org_id=job.org_id,
        project_id=job.project_id,
        period_start=_as_datetime(payload.get("period_start")),
        period_end=_as_datetime(payload.get("period_end")),
        title=payload.get("title"),
        generation_mode=str(payload.get("generation_mode", "structured")),
        inputs={
            "system_generated": job.job_type == "scheduled_generate"
            or not payload.get("requested_by")
        },
        generated_by_job_id=job.id,
        idempotency_key=payload.get("report_idempotency_key") or job.idempotency_key,
    )
    report = await build_report(
        session,
        user,
        template,
        context,
        section_options=payload.get("section_options"),
    )
    if job.job_type == "scheduled_generate" and report.status != "draft":
        raise RuntimeError("Scheduled report generation must remain draft.")
    return report


async def process_job(session: AsyncSession, job: ReportJob) -> None:
    started = perf_counter()
    await set_service_role_context(session)
    try:
        if job.job_type in {"on_demand_generate", "scheduled_generate"}:
            report = await _generate(session, job)
            job.report_instance_id = report.id
            job.result_data = {"report_instance_id": str(report.id), "status": report.status}
        elif job.job_type == "export_render":
            report = await session.get(ReportInstance, job.report_instance_id)
            if report is None or not job.export_format:
                raise ValueError("Export job requires report_instance_id and export_format.")
            artifact = await create_report_export(session, report, job.export_format)
            job.result_data = {"report_export_id": str(artifact.id)}
        elif job.job_type == "regenerate":
            original = await session.get(ReportInstance, job.report_instance_id)
            if original is None:
                raise ValueError("Regenerate job requires an existing report instance.")
            job.template_id = original.template_id
            job.project_id = original.project_id
            report = await _generate(session, job)
            report.supersedes_instance_id = original.id
            job.report_instance_id = report.id
            job.result_data = {"report_instance_id": str(report.id)}
        elif job.job_type == "backfill":
            counts = await backfill_historical_reports(
                session, limit=int((job.request_payload or {}).get("limit", 100))
            )
            job.result_data = {"backfilled": counts, "total": sum(counts.values())}
        else:
            raise ValueError(f"Unsupported report job type '{job.job_type}'.")
        job.status = "succeeded"
        job.completed_at = datetime.now(UTC)
        job.processing_ms = int((perf_counter() - started) * 1000)
        session.add(
            ReportJobEvent(
                org_id=job.org_id,
                job_id=job.id,
                event_type="succeeded",
                event_metadata={"processing_ms": job.processing_ms},
            )
        )
        logger.info(
            "event=report_job_succeeded job_id=%s job_type=%s processing_ms=%s",
            job.id,
            job.job_type,
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
            ReportJobEvent(
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
            "event=report_job_failed job_id=%s job_type=%s attempt=%s",
            job.id,
            job.job_type,
            job.attempt_count,
        )
    await session.flush()


async def process_report_queue(session: AsyncSession) -> int:
    jobs = await claim_jobs(session, limit=get_settings().report_job_poll_batch_size)
    for job in jobs:
        await process_job(session, job)
    return len(jobs)
