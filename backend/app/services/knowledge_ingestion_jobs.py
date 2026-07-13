"""DB-backed knowledge ingestion job queue and worker."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models.entities import (
    AppRole,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentExtraction,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    KnowledgeIngestionJobStatus,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
)
from app.db.session import AsyncSessionLocal
from app.schemas.domain import KnowledgeIngestionProgressRead

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300
QUEUE_POLL_BATCH_SIZE = 5

_dispatch_tasks: set[asyncio.Task[None]] = set()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _backoff_seconds(retry_count: int) -> int:
    return min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2**retry_count))


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    message = str(exc).lower()
    transient_markers = (
        "rate limit",
        "429",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection refused",
        "server disconnected",
        "service unavailable",
        "503",
        "502",
        "504",
    )
    return any(marker in message for marker in transient_markers)


def _format_failure_reason(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def _to_progress_read(job: KnowledgeIngestionJob) -> KnowledgeIngestionProgressRead:
    return KnowledgeIngestionProgressRead(
        job_id=job.id,
        document_id=job.document_id,
        version_id=job.version_id,
        status=job.status.value,
        progress_percentage=job.progress_percentage,
        retry_count=job.retry_count,
        failure_reason=job.failure_reason,
        extraction_warnings=list(job.extraction_warnings or []),
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _get_job_or_none(session: AsyncSession, job_id: UUID) -> KnowledgeIngestionJob | None:
    return (
        await session.execute(select(KnowledgeIngestionJob).where(KnowledgeIngestionJob.id == job_id))
    ).scalar_one_or_none()


async def update_ingestion_job_progress(
    session: AsyncSession,
    job_id: UUID,
    progress: int,
    *,
    warnings: list[str] | None = None,
) -> None:
    job = await _get_job_or_none(session, job_id)
    if job is None:
        return
    job.progress_percentage = max(0, min(100, progress))
    if warnings:
        merged = list(job.extraction_warnings or [])
        for warning in warnings:
            if warning and warning not in merged:
                merged.append(warning)
        job.extraction_warnings = merged
    await session.flush()


async def enqueue_knowledge_ingestion_job(
    session: AsyncSession,
    document_id: UUID,
    version_id: UUID | None = None,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> KnowledgeIngestionJob:
    doc = (
        await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge document not found.")

    resolved_version_id = version_id or doc.active_version_id
    if resolved_version_id is not None:
        version = (
            await session.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.id == resolved_version_id,
                    KnowledgeDocumentVersion.document_id == doc.id,
                )
            )
        ).scalar_one_or_none()
        if version is None:
            resolved_version_id = None

    job = KnowledgeIngestionJob(
        org_id=doc.org_id,
        document_id=document_id,
        version_id=resolved_version_id,
        status=KnowledgeIngestionJobStatus.PENDING,
        progress_percentage=0,
        retry_count=0,
        max_retries=max_retries,
        failure_reason=None,
        extraction_warnings=[],
        next_retry_at=None,
        started_at=None,
        completed_at=None,
    )
    session.add(job)
    await session.flush()
    return job


async def get_document_ingestion_progress(
    session: AsyncSession,
    document_id: UUID,
    *,
    current_user: CurrentUser | None = None,
) -> KnowledgeIngestionProgressRead:
    doc_query = select(KnowledgeDocument).where(
        KnowledgeDocument.id == document_id,
        KnowledgeDocument.deleted_at.is_(None),
    )
    if current_user is not None:
        doc_query = doc_query.where(KnowledgeDocument.org_id == current_user.org_id)
        if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
            raise ApiError(403, "FORBIDDEN", "You cannot view ingestion progress for this document.")

    doc = (await session.execute(doc_query)).scalar_one_or_none()
    if doc is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge document not found.")

    job = (
        await session.execute(
            select(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.document_id == document_id)
            .order_by(KnowledgeIngestionJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "No ingestion job found for this document.")
    return _to_progress_read(job)


async def cleanup_version_ingestion_artifacts(session: AsyncSession, version_id: UUID) -> None:
    await session.execute(delete(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.version_id == version_id))
    await session.execute(delete(KnowledgeDocumentExtraction).where(KnowledgeDocumentExtraction.version_id == version_id))


async def cleanup_document_ingestion_artifacts(session: AsyncSession, document_id: UUID) -> None:
    await session.execute(delete(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.document_id == document_id))
    await session.execute(delete(KnowledgeDocumentExtraction).where(KnowledgeDocumentExtraction.document_id == document_id))


async def _claim_job(session: AsyncSession, job_id: UUID) -> KnowledgeIngestionJob | None:
    now = _utcnow()
    locked = (
        await session.execute(
            select(KnowledgeIngestionJob)
            .where(
                KnowledgeIngestionJob.id == job_id,
                KnowledgeIngestionJob.status == KnowledgeIngestionJobStatus.PENDING,
                or_(KnowledgeIngestionJob.next_retry_at.is_(None), KnowledgeIngestionJob.next_retry_at <= now),
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if locked is None:
        return None

    locked.status = KnowledgeIngestionJobStatus.PROCESSING
    locked.started_at = now
    locked.failure_reason = None
    locked.completed_at = None
    locked.progress_percentage = 0
    await session.flush()
    return locked


async def _mark_job_completed(session: AsyncSession, job: KnowledgeIngestionJob) -> None:
    now = _utcnow()
    job.status = KnowledgeIngestionJobStatus.COMPLETED
    job.progress_percentage = 100
    job.completed_at = now
    job.failure_reason = None
    job.next_retry_at = None
    await session.flush()


async def _mark_job_failed(
    session: AsyncSession,
    job: KnowledgeIngestionJob,
    *,
    failure_reason: str,
    retry_scheduled: bool,
) -> None:
    now = _utcnow()
    if retry_scheduled:
        job.retry_count += 1
        job.status = KnowledgeIngestionJobStatus.PENDING
        job.next_retry_at = now + timedelta(seconds=_backoff_seconds(job.retry_count))
        job.failure_reason = failure_reason
        job.completed_at = None
        job.progress_percentage = 0
    else:
        job.status = KnowledgeIngestionJobStatus.FAILED
        job.failure_reason = failure_reason
        job.completed_at = now
        job.next_retry_at = None
    await session.flush()


async def run_knowledge_ingestion_job(session: AsyncSession | None, job_id: UUID) -> None:
    """Worker entry: claim job, run ingestion pipeline, apply retry policy."""
    from app.services.knowledge import _invalidate_knowledge_answer_cache, _process_document_version, _read_stored_file

    async with AsyncSessionLocal() as claim_session:
        job = await _claim_job(claim_session, job_id)
        if job is None:
            return
        await claim_session.commit()

    async with AsyncSessionLocal() as work_session:
        try:
            job = (await work_session.execute(select(KnowledgeIngestionJob).where(KnowledgeIngestionJob.id == job_id))).scalar_one()
            doc = (
                await work_session.execute(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.id == job.document_id,
                        KnowledgeDocument.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if doc is None:
                job.status = KnowledgeIngestionJobStatus.FAILED
                job.failure_reason = "Document no longer exists."
                job.completed_at = _utcnow()
                await work_session.commit()
                return

            version = None
            if job.version_id is not None:
                version = (
                    await work_session.execute(
                        select(KnowledgeDocumentVersion).where(
                            KnowledgeDocumentVersion.id == job.version_id,
                            KnowledgeDocumentVersion.document_id == doc.id,
                        )
                    )
                ).scalar_one_or_none()
            if version is None:
                version = (
                    await work_session.execute(
                        select(KnowledgeDocumentVersion)
                        .where(KnowledgeDocumentVersion.document_id == doc.id, KnowledgeDocumentVersion.is_active.is_(True))
                        .order_by(KnowledgeDocumentVersion.uploaded_at.desc())
                    )
                ).scalars().first()
            if version is None or not version.storage_path:
                doc.processing_status = KnowledgeProcessingStatus.FAILED
                doc.indexing_status = KnowledgeIndexingStatus.FAILED
                doc.processing_error = "Document has no stored file to process."
                job.status = KnowledgeIngestionJobStatus.FAILED
                job.failure_reason = doc.processing_error
                job.completed_at = _utcnow()
                await work_session.commit()
                return

            if job.version_id is None:
                job.version_id = version.id

            if job.retry_count > 0:
                await cleanup_version_ingestion_artifacts(work_session, version.id)
                doc.processing_status = KnowledgeProcessingStatus.EXTRACTING
                doc.indexing_status = KnowledgeIndexingStatus.INDEXING
                doc.processing_error = None
                doc.indexed_at = None
                await work_session.flush()

            file_bytes = await _read_stored_file(version.storage_path)
            await _process_document_version(work_session, doc, version, file_bytes, job_id=job.id)
            await work_session.refresh(job)

            if doc.processing_status == KnowledgeProcessingStatus.FAILED:
                raise RuntimeError(doc.processing_error or "Document ingestion failed.")

            await _mark_job_completed(work_session, job)
            await work_session.commit()
            _invalidate_knowledge_answer_cache(doc.org_id)
        except Exception as exc:
            if _is_transient_error(exc):
                logger.warning("Transient ingestion failure for job %s", job_id, exc_info=exc)
            else:
                logger.exception("Knowledge ingestion job failed", extra={"job_id": str(job_id)})
            await work_session.rollback()

            async with AsyncSessionLocal() as failure_session:
                job = await _get_job_or_none(failure_session, job_id)
                doc = None
                if job is not None:
                    doc = (
                        await failure_session.execute(
                            select(KnowledgeDocument).where(KnowledgeDocument.id == job.document_id)
                        )
                    ).scalar_one_or_none()

                if job is None:
                    return

                failure_reason = _format_failure_reason(exc)
                can_retry = job.retry_count < job.max_retries
                if can_retry and job.version_id is not None:
                    await cleanup_version_ingestion_artifacts(failure_session, job.version_id)
                await _mark_job_failed(
                    failure_session,
                    job,
                    failure_reason=failure_reason,
                    retry_scheduled=can_retry,
                )
                if doc is not None and not can_retry:
                    doc.processing_status = KnowledgeProcessingStatus.FAILED
                    doc.indexing_status = KnowledgeIndexingStatus.FAILED
                    doc.processing_error = failure_reason
                await failure_session.commit()


async def process_ingestion_job_queue(session: AsyncSession | None = None, batch_size: int = QUEUE_POLL_BATCH_SIZE) -> int:
    """Poll DB for pending or retry-ready jobs and dispatch workers."""
    from sqlalchemy.exc import ProgrammingError

    now = _utcnow()
    try:
        async with AsyncSessionLocal() as poll_session:
            jobs = (
                await poll_session.execute(
                    select(KnowledgeIngestionJob.id)
                    .where(
                        KnowledgeIngestionJob.status == KnowledgeIngestionJobStatus.PENDING,
                        or_(KnowledgeIngestionJob.next_retry_at.is_(None), KnowledgeIngestionJob.next_retry_at <= now),
                    )
                    .order_by(KnowledgeIngestionJob.created_at.asc())
                    .limit(batch_size)
                )
            ).scalars().all()
    except ProgrammingError as exc:
        # Migration not applied yet — avoid poisoning the event loop / connection pool.
        logger.warning("Skipping ingestion queue poll; table unavailable: %s", exc.orig if hasattr(exc, "orig") else exc)
        return 0

    for job_id in jobs:
        dispatch_knowledge_ingestion_job(session, job_id)
    return len(jobs)


def dispatch_knowledge_ingestion_job(session: AsyncSession | None, job_id: UUID) -> None:
    """Fire-and-forget dispatch for a single ingestion job."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running event loop; ingestion job %s will be picked up by the queue poller.", job_id)
        return

    async def _runner() -> None:
        await run_knowledge_ingestion_job(session, job_id)

    task = loop.create_task(_runner(), name=f"knowledge-ingestion-{job_id}")
    _dispatch_tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        _dispatch_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("Ingestion dispatch task failed", exc_info=t.exception())

    task.add_done_callback(_done)


async def enqueue_and_dispatch_knowledge_ingestion_job(
    session: AsyncSession,
    document_id: UUID,
    version_id: UUID | None = None,
) -> KnowledgeIngestionJob:
    job = await enqueue_knowledge_ingestion_job(session, document_id, version_id)
    dispatch_knowledge_ingestion_job(session, job.id)
    return job
