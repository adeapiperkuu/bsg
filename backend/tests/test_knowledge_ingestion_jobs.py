from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.db.models.entities import (
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeIngestionJobStatus,
)
from app.schemas.domain import KnowledgeIngestionProgressRead
from app.services import knowledge_ingestion_jobs as jobs


def test_backoff_seconds_grows_with_retries() -> None:
    assert jobs._backoff_seconds(0) == 5
    assert jobs._backoff_seconds(1) == 10
    assert jobs._backoff_seconds(2) == 20
    assert jobs._backoff_seconds(10) == jobs.MAX_BACKOFF_SECONDS


def test_is_transient_error_detects_network_and_rate_limits() -> None:
    assert jobs._is_transient_error(TimeoutError("request timeout"))
    assert jobs._is_transient_error(RuntimeError("OpenAI rate limit exceeded"))
    assert not jobs._is_transient_error(ValueError("No extractable text found."))


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _IngestionSession:
    def __init__(
        self,
        *,
        document: KnowledgeDocument | None = None,
        job_rows: list[KnowledgeIngestionJob] | None = None,
        jobs_by_id: dict | None = None,
    ):
        self.document = document
        self.job_rows = job_rows or []
        self.jobs_by_id = jobs_by_id or {job.id: job for job in self.job_rows}

    async def execute(self, stmt):
        sql = str(stmt)
        if "knowledge_ingestion_jobs.id" in sql or "knowledge_ingestion_jobs_1.id" in sql:
            for job_id, job in self.jobs_by_id.items():
                if str(job_id) in sql:
                    return _ScalarResult(job)
            return _ScalarResult(None)
        if "knowledge_documents" in sql:
            return _ScalarResult(self.document)
        if "knowledge_ingestion_jobs" in sql:
            ordered = sorted(self.job_rows, key=lambda row: row.created_at, reverse=True)
            return _ScalarResult(ordered[0] if ordered else None)
        return _ScalarResult(None)

    def add(self, item: object) -> None:
        if isinstance(item, KnowledgeIngestionJob):
            self.job_rows.append(item)
            self.jobs_by_id[item.id] = item

    async def flush(self) -> None:
        return None


def _manager(org_id) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        role=AppRole.DELIVERY_MANAGER,
        email="pm@example.com",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_update_ingestion_job_progress_merges_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    job = KnowledgeIngestionJob(
        id=job_id,
        org_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        status=KnowledgeIngestionJobStatus.PROCESSING,
        progress_percentage=0,
        retry_count=0,
        max_retries=3,
        extraction_warnings=["Existing warning"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session = _IngestionSession()

    async def _get_job(_session, requested_job_id):
        assert requested_job_id == job_id
        return job

    monkeypatch.setattr(jobs, "_get_job_or_none", _get_job)

    await jobs.update_ingestion_job_progress(
        session,  # type: ignore[arg-type]
        job_id,
        25,
        warnings=["Low-quality OCR", "Existing warning"],
    )

    assert job.progress_percentage == 25
    assert job.extraction_warnings == ["Existing warning", "Low-quality OCR"]


@pytest.mark.asyncio
async def test_get_document_ingestion_progress_returns_latest_job(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = uuid4()
    user = _manager(org_id)
    document_id = uuid4()
    latest_job = KnowledgeIngestionJob(
        id=uuid4(),
        org_id=org_id,
        document_id=document_id,
        version_id=uuid4(),
        status=KnowledgeIngestionJobStatus.PROCESSING,
        progress_percentage=50,
        retry_count=0,
        max_retries=3,
        failure_reason=None,
        extraction_warnings=["Chunk quality warning"],
        created_at=datetime(2026, 7, 10, tzinfo=UTC),
        updated_at=datetime(2026, 7, 10, tzinfo=UTC),
    )
    session = _IngestionSession(
        document=KnowledgeDocument(
            id=document_id,
            org_id=org_id,
            folder_id=uuid4(),
            title="Escalation SOP",
            source_type="sop",
            document_type="sop",
            version="v1",
            visibility="internal_only",
            status="draft",
            owner_approver="Owner",
            file_name="escalation.pdf",
            file_mime_type="application/pdf",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )

    async def _progress(_session, _document_id, *, current_user=None):
        return jobs._to_progress_read(latest_job)

    monkeypatch.setattr(jobs, "get_document_ingestion_progress", _progress)

    progress = await jobs.get_document_ingestion_progress(session, document_id, current_user=user)  # type: ignore[arg-type]

    assert progress.job_id == latest_job.id
    assert progress.status == "processing"
    assert progress.progress_percentage == 50
    assert progress.extraction_warnings == ["Chunk quality warning"]


@pytest.mark.asyncio
async def test_knowledge_progress_route_contract(
    api_client,
    knowledge_users,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import override_user

    override_user(knowledge_users["delivery_manager"])
    expected = KnowledgeIngestionProgressRead(
        job_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        status="processing",
        progress_percentage=75,
        retry_count=0,
        failure_reason=None,
        extraction_warnings=["Low-quality OCR"],
        started_at=datetime.now(UTC),
        completed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def _progress(*_args, **_kwargs):
        return expected

    monkeypatch.setattr(
        "app.api.routes.knowledge.get_document_ingestion_progress",
        _progress,
    )

    response = await api_client.get(f"/api/v1/knowledge/documents/{expected.document_id}/progress")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "processing"
    assert payload["progress_percentage"] == 75
    assert payload["extraction_warnings"] == ["Low-quality OCR"]
