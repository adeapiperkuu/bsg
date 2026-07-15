"""Durable Governance job queue, lifecycle APIs, and worker execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceJob,
    GovernanceJobEvent,
    GovernanceJobStatus,
    User,
)
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

JOB_AI_RECOMMENDATION = "ai_recommendation_generate"
JOB_WEEKLY_SUMMARY = "weekly_summary_generate"
JOB_CHARTER = "project_charter_generate"
JOB_ANALYTICS_EXPORT = "governance_analytics_export"
SUPPORTED_JOB_TYPES = {
    JOB_AI_RECOMMENDATION,
    JOB_WEEKLY_SUMMARY,
    JOB_CHARTER,
    JOB_ANALYTICS_EXPORT,
}

ACTIVE_STATUSES = {
    GovernanceJobStatus.QUEUED,
    GovernanceJobStatus.RUNNING,
    GovernanceJobStatus.RETRY_SCHEDULED,
    GovernanceJobStatus.CANCELLATION_REQUESTED,
}
TERMINAL_STATUSES = {
    GovernanceJobStatus.SUCCEEDED,
    GovernanceJobStatus.FAILED,
    GovernanceJobStatus.CANCELLED,
}
CLAIMABLE_STATUSES = {
    GovernanceJobStatus.QUEUED,
    GovernanceJobStatus.RETRY_SCHEDULED,
}
ALLOWED_TRANSITIONS = {
    GovernanceJobStatus.QUEUED: {
        GovernanceJobStatus.RUNNING,
        GovernanceJobStatus.CANCELLED,
    },
    GovernanceJobStatus.RUNNING: {
        GovernanceJobStatus.SUCCEEDED,
        GovernanceJobStatus.FAILED,
        GovernanceJobStatus.RETRY_SCHEDULED,
        GovernanceJobStatus.CANCELLATION_REQUESTED,
    },
    GovernanceJobStatus.RETRY_SCHEDULED: {
        GovernanceJobStatus.RUNNING,
        GovernanceJobStatus.CANCELLED,
    },
    GovernanceJobStatus.CANCELLATION_REQUESTED: {
        GovernanceJobStatus.CANCELLED,
        GovernanceJobStatus.SUCCEEDED,
        GovernanceJobStatus.FAILED,
    },
    GovernanceJobStatus.FAILED: {GovernanceJobStatus.QUEUED},
    GovernanceJobStatus.SUCCEEDED: set(),
    GovernanceJobStatus.CANCELLED: set(),
}

TRANSIENT_CODES = {
    "AI_TIMEOUT",
    "RATE_LIMITED",
    "NETWORK_UNAVAILABLE",
    "DATABASE_UNAVAILABLE",
    "STORAGE_UNAVAILABLE",
    "WORKER_INTERRUPTED",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _worker_id() -> str:
    configured = get_settings().governance_job_worker_id.strip()
    return configured or f"{socket.gethostname()}:{os.getpid()}"


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def build_job_idempotency_key(
    *,
    job_type: str,
    org_id: UUID,
    project_id: UUID | None,
    requested_by: UUID,
    payload: dict[str, Any],
) -> str:
    material = {
        "job_type": job_type,
        "org_id": str(org_id),
        "project_id": str(project_id) if project_id else None,
        "requested_by": str(requested_by) if job_type == JOB_ANALYTICS_EXPORT else None,
        "payload": payload,
    }
    return hashlib.sha256(_canonical_payload(material).encode()).hexdigest()


def transition_job(job: GovernanceJob, status: GovernanceJobStatus) -> None:
    if status not in ALLOWED_TRANSITIONS[job.status]:
        raise ApiError(
            409,
            "INVALID_JOB_TRANSITION",
            f"Job cannot move from {job.status.value} to {status.value}.",
        )
    job.status = status


def _event(
    job: GovernanceJob,
    event_type: str,
    *,
    actor_user_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> GovernanceJobEvent:
    return GovernanceJobEvent(
        org_id=job.org_id,
        project_id=job.project_id,
        job_id=job.id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        event_metadata=metadata or {},
    )


async def enqueue_governance_job(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    job_type: str,
    org_id: UUID,
    project_id: UUID | None,
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> tuple[GovernanceJob, bool]:
    if job_type not in SUPPORTED_JOB_TYPES:
        raise ApiError(422, "UNSUPPORTED_JOB_TYPE", "Unsupported Governance job type.")
    if current_user.role == AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Clients cannot start Governance generation jobs.")

    key = build_job_idempotency_key(
        job_type=job_type,
        org_id=org_id,
        project_id=project_id,
        requested_by=current_user.id,
        payload=payload,
    )
    # Transaction-scoped advisory locking plus the partial unique index makes creation atomic.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
    )
    existing = (
        await session.execute(
            select(GovernanceJob)
            .where(
                GovernanceJob.idempotency_key == key,
                GovernanceJob.status.in_(ACTIVE_STATUSES),
            )
            .order_by(GovernanceJob.requested_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    job = GovernanceJob(
        org_id=org_id,
        project_id=project_id,
        job_type=job_type,
        status=GovernanceJobStatus.QUEUED,
        requested_by=current_user.id,
        progress_stage="queued",
        progress_percent=0,
        attempt_count=0,
        max_attempts=max(1, min(max_attempts, 10)),
        idempotency_key=key,
        request_payload=payload,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                select(GovernanceJob).where(
                    GovernanceJob.idempotency_key == key,
                    GovernanceJob.status.in_(ACTIVE_STATUSES),
                )
            )
        ).scalar_one()
        return existing, True
    session.add(_event(job, "requested", actor_user_id=current_user.id))
    await session.commit()
    await session.refresh(job)
    return job, False


def _visible_job_stmt(current_user: CurrentUser):
    stmt = select(GovernanceJob).where(GovernanceJob.requested_by == current_user.id)
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(GovernanceJob.org_id == current_user.org_id)
    return stmt


async def get_governance_job(
    session: AsyncSession, current_user: CurrentUser, job_id: UUID
) -> GovernanceJob:
    job = (
        await session.execute(_visible_job_stmt(current_user).where(GovernanceJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Governance job was not found.")
    return job


async def list_governance_jobs(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    job_type: str | None = None,
    project_id: UUID | None = None,
    active_only: bool = False,
    limit: int = 20,
) -> list[GovernanceJob]:
    stmt = _visible_job_stmt(current_user)
    if job_type:
        stmt = stmt.where(GovernanceJob.job_type == job_type)
    if project_id:
        stmt = stmt.where(GovernanceJob.project_id == project_id)
    if active_only:
        stmt = stmt.where(GovernanceJob.status.in_(ACTIVE_STATUSES))
    stmt = stmt.order_by(GovernanceJob.requested_at.desc()).limit(max(1, min(limit, 100)))
    return list((await session.execute(stmt)).scalars())


async def cancel_governance_job(
    session: AsyncSession, current_user: CurrentUser, job_id: UUID
) -> GovernanceJob:
    job = await get_governance_job(session, current_user, job_id)
    now = utcnow()
    if job.status in {GovernanceJobStatus.QUEUED, GovernanceJobStatus.RETRY_SCHEDULED}:
        transition_job(job, GovernanceJobStatus.CANCELLED)
        job.progress_stage = "cancelled"
        job.completed_at = now
        job.cancel_requested_at = now
        session.add(_event(job, "cancelled", actor_user_id=current_user.id))
    elif job.status == GovernanceJobStatus.RUNNING:
        transition_job(job, GovernanceJobStatus.CANCELLATION_REQUESTED)
        job.progress_stage = "cancellation_requested"
        job.cancel_requested_at = now
        session.add(_event(job, "cancellation_requested", actor_user_id=current_user.id))
    elif job.status not in TERMINAL_STATUSES:
        raise ApiError(409, "JOB_NOT_CANCELLABLE", "Job cannot be cancelled in its current state.")
    await session.commit()
    await session.refresh(job)
    return job


async def retry_governance_job(
    session: AsyncSession, current_user: CurrentUser, job_id: UUID
) -> GovernanceJob:
    job = await get_governance_job(session, current_user, job_id)
    if job.status != GovernanceJobStatus.FAILED or job.error_code not in TRANSIENT_CODES:
        raise ApiError(409, "JOB_NOT_RETRYABLE", "This job cannot be retried.")
    transition_job(job, GovernanceJobStatus.QUEUED)
    job.progress_stage = "queued"
    job.progress_percent = 0
    job.next_attempt_at = None
    job.completed_at = None
    job.error_code = None
    job.error_message = None
    session.add(_event(job, "requested", actor_user_id=current_user.id, metadata={"retry": True}))
    await session.commit()
    await session.refresh(job)
    return job


async def _claim_next_job(session: AsyncSession) -> GovernanceJob | None:
    now = utcnow()
    job = (
        await session.execute(
            select(GovernanceJob)
            .where(
                GovernanceJob.status.in_(CLAIMABLE_STATUSES),
                or_(GovernanceJob.next_attempt_at.is_(None), GovernanceJob.next_attempt_at <= now),
            )
            .order_by(GovernanceJob.requested_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    transition_job(job, GovernanceJobStatus.RUNNING)
    job.started_at = now
    job.heartbeat_at = now
    job.worker_id = _worker_id()
    job.progress_stage = "collecting_evidence"
    job.progress_percent = 10
    job.attempt_count += 1
    job.error_code = None
    job.error_message = None
    job.next_attempt_at = None
    job.queue_wait_ms = max(0, int((now - job.requested_at).total_seconds() * 1000))
    session.add(_event(job, "started", metadata={"attempt": job.attempt_count}))
    await session.flush()
    return job


async def _set_progress(job_id: UUID, stage: str, percent: int) -> bool:
    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(select(GovernanceJob).where(GovernanceJob.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            return False
        if job.status == GovernanceJobStatus.CANCELLATION_REQUESTED:
            transition_job(job, GovernanceJobStatus.CANCELLED)
            job.progress_stage = "cancelled"
            job.completed_at = utcnow()
            session.add(_event(job, "cancelled"))
            await session.commit()
            return False
        if job.status != GovernanceJobStatus.RUNNING:
            return False
        job.progress_stage = stage
        job.progress_percent = max(0, min(percent, 99))
        job.heartbeat_at = utcnow()
        await session.commit()
        return True


async def _heartbeat_loop(job_id: UUID, stop: asyncio.Event) -> None:
    interval = max(5, get_settings().governance_job_heartbeat_seconds)
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            async with AsyncSessionLocal() as session:
                job = (
                    await session.execute(select(GovernanceJob).where(GovernanceJob.id == job_id))
                ).scalar_one_or_none()
                if job is None or job.status not in {
                    GovernanceJobStatus.RUNNING,
                    GovernanceJobStatus.CANCELLATION_REQUESTED,
                }:
                    return
                job.heartbeat_at = utcnow()
                await session.commit()


@dataclass
class JobProduct:
    record_type: str
    record_id: UUID | None
    data: dict[str, Any]


async def _load_requester(session: AsyncSession, job: GovernanceJob) -> CurrentUser:
    user = (
        await session.execute(
            select(User).where(
                User.id == job.requested_by,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise ApiError(403, "REQUESTER_UNAVAILABLE", "The requesting user is no longer active.")
    return CurrentUser(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )


async def _execute_product(job: GovernanceJob) -> JobProduct:
    payload = dict(job.request_payload or {})
    async with AsyncSessionLocal() as session:
        user = await _load_requester(session, job)
        await session.commit()
        if job.job_type == JOB_AI_RECOMMENDATION:
            from app.agents.governance.services.recommendation_service import (
                generate_governance_ai_recommendations,
            )
            from app.db.models import GovernanceAIRecommendationScope

            result = await generate_governance_ai_recommendations(
                session,
                user,
                project_id=UUID(payload["project_id"]) if payload.get("project_id") else None,
                scope=GovernanceAIRecommendationScope(payload.get("scope", "project")),
                force=bool(payload.get("force", False)),
            )
            record_id = result.recommendations[0].id if result.recommendations else None
            return JobProduct(
                "governance_ai_recommendation",
                record_id,
                {
                    "candidates_persisted": result.candidates_persisted,
                    "projects_attempted": result.projects_attempted,
                    "projects_with_recommendations": result.projects_with_recommendations,
                    "fallback_used": result.fallback_used,
                },
            )
        if job.job_type == JOB_WEEKLY_SUMMARY:
            from datetime import date

            from app.agents.governance.services.summary_service import (
                generate_weekly_governance_summary,
            )

            week = (
                date.fromisoformat(payload["summary_week"]) if payload.get("summary_week") else None
            )
            result = await generate_weekly_governance_summary(session, user, summary_week=week)
            return JobProduct(
                "governance_weekly_summary",
                result.id,
                {"summary_week": result.summary_week.isoformat(), "status": result.status.value},
            )
        if job.job_type == JOB_CHARTER:
            from app.agents.governance.services.charter_service import generate_project_charter
            from app.db.models import KnowledgeVisibility

            result = await generate_project_charter(
                session,
                user,
                project_id=UUID(payload["project_id"]),
                visibility=KnowledgeVisibility(payload.get("visibility", "internal_only")),
            )
            return JobProduct(
                "project_charter",
                result.id,
                {"project_id": str(result.project_id), "version": result.version},
            )
        if job.job_type == JOB_ANALYTICS_EXPORT:
            from app.agents.governance.services.job_export_service import (
                generate_governance_analytics_export,
            )

            return await generate_governance_analytics_export(session, user, job.id, payload)
    raise ApiError(422, "UNSUPPORTED_JOB_TYPE", "Unsupported Governance job type.")


def _classify_error(exc: BaseException) -> tuple[str, str, bool]:
    if isinstance(exc, ApiError):
        return exc.code, exc.message[:500], exc.status_code >= 500
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "AI_TIMEOUT", "The AI provider timed out.", True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return "RATE_LIMITED", "The AI provider rate limit was reached.", True
    if isinstance(exc, httpx.NetworkError):
        return "NETWORK_UNAVAILABLE", "A required network service is temporarily unavailable.", True
    if isinstance(exc, OperationalError | DBAPIError):
        return "DATABASE_UNAVAILABLE", "The database is temporarily unavailable.", True
    if isinstance(exc, OSError):
        return "STORAGE_UNAVAILABLE", "Export storage is temporarily unavailable.", True
    if isinstance(exc, ValidationError):
        return "INVALID_RESULT", "Generated output failed validation.", False
    return "JOB_EXECUTION_FAILED", "The job could not be completed.", False


async def _finish_success(job_id: UUID, product: JobProduct, started: float) -> None:
    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(select(GovernanceJob).where(GovernanceJob.id == job_id))
        ).scalar_one()
        # Product persistence has already committed. A late cancellation must not hide that result.
        transition_job(job, GovernanceJobStatus.SUCCEEDED)
        job.progress_stage = "completed"
        job.progress_percent = 100
        job.completed_at = utcnow()
        job.heartbeat_at = job.completed_at
        job.processing_ms = int((perf_counter() - started) * 1000)
        job.result_record_type = product.record_type
        job.result_record_id = product.record_id
        job.result_data = product.data
        job.error_code = None
        job.error_message = None
        session.add(_event(job, "succeeded", metadata={"processing_ms": job.processing_ms}))
        await session.commit()
        _log_completion_metric(job)


async def _finish_failure(job_id: UUID, exc: BaseException, started: float) -> None:
    code, message, transient = _classify_error(exc)
    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(select(GovernanceJob).where(GovernanceJob.id == job_id))
        ).scalar_one()
        retry = (
            transient
            and job.status == GovernanceJobStatus.RUNNING
            and job.attempt_count < job.max_attempts
        )
        if retry:
            transition_job(job, GovernanceJobStatus.RETRY_SCHEDULED)
            delay = min(300, 5 * (2 ** max(0, job.attempt_count - 1)))
            job.next_attempt_at = utcnow() + timedelta(seconds=delay)
            job.progress_stage = "retry_scheduled"
            job.progress_percent = 0
            session.add(
                _event(
                    job,
                    "retry_scheduled",
                    metadata={
                        "attempt": job.attempt_count,
                        "delay_seconds": delay,
                        "error_code": code,
                    },
                )
            )
        else:
            target = (
                GovernanceJobStatus.CANCELLED
                if job.status == GovernanceJobStatus.CANCELLATION_REQUESTED
                else GovernanceJobStatus.FAILED
            )
            transition_job(job, target)
            job.completed_at = utcnow()
            job.progress_stage = (
                "cancelled" if target == GovernanceJobStatus.CANCELLED else "failed"
            )
            session.add(
                _event(
                    job,
                    "cancelled" if target == GovernanceJobStatus.CANCELLED else "failed",
                    metadata={"error_code": code},
                )
            )
        job.processing_ms = int((perf_counter() - started) * 1000)
        job.error_code = code
        job.error_message = message
        job.heartbeat_at = utcnow()
        await session.commit()
        _log_completion_metric(job)


def _log_completion_metric(job: GovernanceJob) -> None:
    logger.info(
        "governance_job_metric job_type=%s status=%s queue_wait_ms=%s processing_ms=%s "
        "attempt_count=%s error_code=%s",
        job.job_type,
        job.status.value,
        job.queue_wait_ms,
        job.processing_ms,
        job.attempt_count,
        job.error_code,
    )


async def run_governance_job(job_id: UUID) -> None:
    started = perf_counter()
    if not await _set_progress(job_id, "building_context", 25):
        return
    try:
        if not await _set_progress(job_id, "generating", 45):
            return
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            _heartbeat_loop(job_id, heartbeat_stop), name=f"governance-job-heartbeat-{job_id}"
        )
        try:
            product = await _execute_product(await _load_job_snapshot(job_id))
        finally:
            heartbeat_stop.set()
            await heartbeat
        # Domain services validate and commit the product before returning. A cancellation that
        # arrived during that work cannot undo the committed result, so success wins.
        await _finish_success(job_id, product, started)
    except Exception as exc:  # noqa: BLE001 - worker must persist every failure
        logger.exception("Governance job execution failed", extra={"job_id": str(job_id)})
        await _finish_failure(job_id, exc, started)


async def _load_job_snapshot(job_id: UUID) -> GovernanceJob:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(GovernanceJob).where(GovernanceJob.id == job_id))
        ).scalar_one()


async def recover_stale_governance_jobs() -> int:
    settings = get_settings()
    stale_before = utcnow() - timedelta(seconds=settings.governance_job_stale_seconds)
    recovered = 0
    async with AsyncSessionLocal() as session:
        jobs = list(
            (
                await session.execute(
                    select(GovernanceJob)
                    .where(
                        GovernanceJob.status.in_(
                            {
                                GovernanceJobStatus.RUNNING,
                                GovernanceJobStatus.CANCELLATION_REQUESTED,
                            }
                        ),
                        GovernanceJob.heartbeat_at < stale_before,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for job in jobs:
            if job.status == GovernanceJobStatus.CANCELLATION_REQUESTED:
                transition_job(job, GovernanceJobStatus.CANCELLED)
                job.completed_at = utcnow()
                job.progress_stage = "cancelled"
                session.add(_event(job, "cancelled", metadata={"stale_recovery": True}))
            elif job.attempt_count < job.max_attempts:
                transition_job(job, GovernanceJobStatus.RETRY_SCHEDULED)
                job.progress_stage = "retry_scheduled"
                job.progress_percent = 0
                job.next_attempt_at = utcnow()
                job.error_code = "WORKER_INTERRUPTED"
                job.error_message = "The worker stopped before completing the job."
                session.add(_event(job, "stale_job_recovered"))
            else:
                transition_job(job, GovernanceJobStatus.FAILED)
                job.completed_at = utcnow()
                job.progress_stage = "failed"
                job.error_code = "WORKER_INTERRUPTED"
                job.error_message = "The worker stopped before completing the job."
                session.add(_event(job, "failed", metadata={"stale_recovery": True}))
            recovered += 1
        await session.commit()
    if recovered:
        logger.info("governance_job_stale_recovery count=%s", recovered)
    return recovered


async def process_governance_job_queue(batch_size: int | None = None) -> int:
    settings = get_settings()
    try:
        await recover_stale_governance_jobs()
    except ProgrammingError as exc:
        logger.warning("Skipping Governance queue poll; migration unavailable: %s", exc)
        return 0
    processed = 0
    limit = batch_size or settings.governance_job_poll_batch_size
    for _ in range(max(1, limit)):
        try:
            async with AsyncSessionLocal() as session:
                job = await _claim_next_job(session)
                if job is None:
                    await session.rollback()
                    break
                job_id = job.id
                await session.commit()
        except ProgrammingError as exc:
            logger.warning("Skipping Governance queue poll; migration unavailable: %s", exc)
            return 0
        await run_governance_job(job_id)
        processed += 1
    await emit_governance_job_queue_metrics()
    return processed


async def emit_governance_job_queue_metrics() -> None:
    try:
        async with AsyncSessionLocal() as session:
            now = utcnow()
            rows = (
                await session.execute(
                    select(
                        GovernanceJob.job_type,
                        func.count(GovernanceJob.id),
                        func.min(GovernanceJob.requested_at),
                    )
                    .where(
                        GovernanceJob.status.in_(
                            {GovernanceJobStatus.QUEUED, GovernanceJobStatus.RETRY_SCHEDULED}
                        )
                    )
                    .group_by(GovernanceJob.job_type)
                )
            ).all()
        for job_type, depth, oldest in rows:
            age_ms = int((now - oldest).total_seconds() * 1000) if oldest else 0
            logger.info(
                "governance_job_queue_metric job_type=%s queue_depth=%s oldest_queued_age_ms=%s",
                job_type,
                depth,
                age_ms,
            )
    except ProgrammingError:
        return


__all__ = [
    "ACTIVE_STATUSES",
    "JOB_AI_RECOMMENDATION",
    "JOB_ANALYTICS_EXPORT",
    "JOB_CHARTER",
    "JOB_WEEKLY_SUMMARY",
    "SUPPORTED_JOB_TYPES",
    "TRANSIENT_CODES",
    "build_job_idempotency_key",
    "cancel_governance_job",
    "enqueue_governance_job",
    "get_governance_job",
    "list_governance_jobs",
    "process_governance_job_queue",
    "recover_stale_governance_jobs",
    "retry_governance_job",
    "run_governance_job",
    "transition_job",
]
