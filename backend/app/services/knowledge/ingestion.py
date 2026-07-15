from __future__ import annotations

import hashlib
import csv
import difflib
import io
import asyncio
import json
import logging
import mimetypes
import re
import math
import time
from time import perf_counter
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import load_only

from app.core.config import get_settings
from app.core.constants import SUPPORTED_KNOWLEDGE_EXTENSIONS
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.rls import set_rls_context
from app.db.session import AsyncSessionLocal
from app.db.models.entities import (
    AppRole,
    AlertStatus,
    Bottleneck,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentExtraction,
    KnowledgeDocumentVersion,
    KnowledgeDocumentStatus,
    KnowledgeExtractionStatus,
    KnowledgeEvidenceLink,
    KnowledgeFeedbackRating,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeQueryFeedback,
    KnowledgeSourceType,
    KnowledgeVisibility,
    Milestone,
    AgentQuery,
    NotificationType,
    Project,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
    User,
)
from app.schemas.common import Pagination
from app.schemas.domain import (
    KnowledgeAskRead,
    KnowledgeBootstrapRead,
    KnowledgeConversationRead,
    KnowledgeConversationSummaryRead,
    KnowledgeConversationTurn,
    KnowledgeConversationTurnRead,
    KnowledgeDocumentCountsRead,
    KnowledgeDocumentRead,
    KnowledgeDocumentSummaryRead,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentVersionRead,
    KnowledgeFeedbackRead,
    KnowledgeFolderRead,
    KnowledgeFolderTreeNodeRead,
    KnowledgeLibraryAnalyticsRead,
    KnowledgeLibraryHealthCountsRead,
    KnowledgeLibraryHealthRead,
    KnowledgeChunkRead,
    KnowledgeExtractionScoreBreakdown,
    KnowledgePermissionsRead,
    KnowledgeQualityCriterion,
    KnowledgeQualityScore,
    KnowledgeRetrievalSettingsRead,
    KnowledgeRetrievalSettingsUpdate,
    KnowledgeStructuredAnswer,
    KnowledgeVersionCompareRead,
)
from app.services.llm.client import FAST_PATH_THRESHOLD, LLMClient, RAG_CONTEXT_CHUNK_CHARS
from app.services.llm.openai_client import get_openai_client
from app.services.notifications import create_notification
from app.services.knowledge_intelligence import (
    aggregate_cross_references,
    aggregate_document_entities,
    analyze_chunk_content,
    build_library_analytics,
    chunk_sections_semantic,
    compute_extraction_score_breakdown,
    count_operational_keywords,
    detect_document_duplicates,
    is_table_like_text,
)


logger = logging.getLogger(__name__)

from app.services.knowledge.library import (
    _get_document_or_404,
    _notify_knowledge_stakeholders,
    _to_document_read,
    get_folder_by_id,
    get_folder_for_kind,
)
from app.services.knowledge.permissions import (
    can_access_visibility,
)
from app.services.knowledge.utils import (
    EMBEDDING_BATCH_SIZE,
    TEXT_EXTENSIONS,
    UPLOAD_APPROVED_MIN_METADATA_SCORE,
    _clean_optional,
    _invalidate_knowledge_answer_cache,
)



# --- ingestion (Phase 8) ---

async def create_document_from_upload(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    folder_id: UUID | None = None,
    folder_kind: KnowledgeFolderKind | None = None,
    title: str,
    source_type: KnowledgeSourceType,
    version: str,
    visibility: KnowledgeVisibility,
    status: KnowledgeDocumentStatus,
    owner_approver: str,
    description: str | None,
    approver: str | None,
    project: str | None,
    department: str | None,
    effective_date: date | None,
    file_name: str,
    file_mime_type: str,
    file_bytes: bytes,
) -> KnowledgeDocumentRead:
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "You cannot upload knowledge documents.")
    if Path(file_name).suffix.lower() not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise ApiError(400, "VALIDATION_ERROR", "Unsupported file type. Use PDF, DOCX, TXT, MD, or CSV.")
    if status != KnowledgeDocumentStatus.DRAFT:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Uploads must start as draft. Submit and approve documents through the lifecycle endpoints.",
        )

    folder = (
        await get_folder_by_id(session, current_user.org_id, folder_id)
        if folder_id is not None
        else await get_folder_for_kind(session, current_user.org_id, folder_kind or KnowledgeFolderKind.SOPS)
    )
    checksum = hashlib.sha256(file_bytes).hexdigest()
    title_clean = title.strip()
    owner_clean = owner_approver.strip()
    upload_warnings = _assess_upload_quality(source_type, status, owner_clean, effective_date)
    upload_block = _upload_block_message(status, owner_clean, effective_date)
    if upload_block:
        raise ApiError(400, "VALIDATION_ERROR", upload_block)
    existing = (
        await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.org_id == current_user.org_id,
                KnowledgeDocument.folder_id == folder.id,
                KnowledgeDocument.title == title_clean,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    doc = existing or KnowledgeDocument(
        org_id=current_user.org_id,
        folder_id=folder.id,
        title=title_clean,
        source_type=source_type,
        document_type=source_type.value,
        version=version,
        visibility=visibility,
        status=status,
        project=_clean_optional(project),
        department=_clean_optional(department),
        owner_approver=owner_clean,
        owner=owner_clean,
        approver=(approver or owner_clean).strip(),
        effective_date=effective_date,
        file_name=file_name,
        file_mime_type=file_mime_type,
        file_size_bytes=len(file_bytes),
        checksum_sha256=checksum,
        indexing_status=KnowledgeIndexingStatus.INDEXING,
        processing_status=KnowledgeProcessingStatus.EXTRACTING,
        uploaded_by=current_user.id,
        created_by=current_user.id,
        description=description.strip() if description else None,
    )
    if existing:
        doc.source_type = source_type
        doc.document_type = source_type.value
        doc.version = version
        doc.visibility = visibility
        doc.status = status
        doc.project = _clean_optional(project)
        doc.department = _clean_optional(department)
        doc.owner_approver = owner_clean
        doc.owner = owner_clean
        doc.approver = (approver or owner_clean).strip()
        doc.effective_date = effective_date
        doc.file_name = file_name
        doc.file_mime_type = file_mime_type
        doc.file_size_bytes = len(file_bytes)
        doc.checksum_sha256 = checksum
        doc.uploaded_by = current_user.id
        doc.upload_date = datetime.now(timezone.utc)
        doc.description = description.strip() if description else doc.description
        doc.processing_status = KnowledgeProcessingStatus.EXTRACTING
        doc.indexing_status = KnowledgeIndexingStatus.INDEXING
        doc.indexed_at = None
        doc.processing_error = None
    else:
        session.add(doc)
    if status == KnowledgeDocumentStatus.APPROVED:
        doc.approved_by = current_user.id
        doc.approved_at = datetime.now(timezone.utc)
        doc.reviewed_by = current_user.id
        doc.reviewed_at = doc.approved_at
    session.add(doc)
    await session.flush()

    existing_version = (
        await session.execute(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == doc.id,
                KnowledgeDocumentVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if existing_version is not None:
        version = f"{version}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    storage = await _store_upload(current_user.org_id, doc.id, version, file_name, file_bytes, file_mime_type)
    previous_versions = list(
        (await session.execute(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == doc.id))).scalars()
    )
    previous_active = next((item for item in previous_versions if item.is_active), None)
    for item in previous_versions:
        item.is_active = False

    version_row = KnowledgeDocumentVersion(
        org_id=current_user.org_id,
        document_id=doc.id,
        version=version,
        file_name=file_name,
        file_mime_type=file_mime_type,
        file_size_bytes=len(file_bytes),
        file_url=storage["file_url"],
        storage_path=storage["storage_path"],
        checksum_sha256=checksum,
        is_active=True,
        supersedes_version_id=previous_active.id if previous_active else None,
        uploaded_by=current_user.id,
    )
    session.add(version_row)
    await session.flush()
    if previous_active is not None:
        previous_active.superseded_by_version_id = version_row.id

    doc.active_version_id = version_row.id
    doc.version = version
    doc.file_url = storage["file_url"]
    doc.storage_path = storage["storage_path"]
    doc.processing_status = KnowledgeProcessingStatus.EXTRACTING
    doc.indexing_status = KnowledgeIndexingStatus.INDEXING
    doc.indexed_at = None
    doc.processing_error = None
    await session.flush()

    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    event = "uploaded" if existing is None else "updated with a new version"
    await _notify_knowledge_stakeholders(
        session,
        doc,
        title=f"Knowledge document {event}",
        body=f'"{doc.title}" ({doc.version}) was {event}. Review approval and indexing status.',
        actor_id=current_user.id,
    )
    read = await _to_document_read(session, doc, folder)
    if upload_warnings:
        return read.model_copy(update={"quality_warnings": upload_warnings})
    return read

async def reindex_document(session: AsyncSession, current_user: CurrentUser, document_id: UUID) -> KnowledgeDocumentRead:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "You cannot re-index knowledge documents.")
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot re-index this document.")
    version = None
    if doc.active_version_id:
        version = (
            await session.execute(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == doc.active_version_id)
            )
        ).scalar_one_or_none()
    if version is None:
        version = (
            await session.execute(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id == doc.id, KnowledgeDocumentVersion.is_active.is_(True))
                .order_by(KnowledgeDocumentVersion.uploaded_at.desc())
            )
        ).scalars().first()
    if version is None or not version.storage_path:
        raise ApiError(400, "VALIDATION_ERROR", "Document has no stored file to index.")
    source_version = version

    from app.services.knowledge_ingestion_jobs import cleanup_version_ingestion_artifacts

    await cleanup_version_ingestion_artifacts(session, source_version.id)

    reindex_version = f"{source_version.version}-reindex-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    previous_versions = list(
        (await session.execute(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == doc.id))).scalars()
    )
    for item in previous_versions:
        item.is_active = False
    version = KnowledgeDocumentVersion(
        org_id=doc.org_id,
        document_id=doc.id,
        version=reindex_version,
        file_name=source_version.file_name,
        file_mime_type=source_version.file_mime_type,
        file_size_bytes=source_version.file_size_bytes,
        file_url=source_version.file_url,
        storage_path=source_version.storage_path,
        checksum_sha256=source_version.checksum_sha256,
        is_active=True,
        uploaded_by=current_user.id,
    )
    session.add(version)
    await session.flush()
    doc.active_version_id = version.id
    doc.version = reindex_version
    doc.file_url = version.file_url
    doc.storage_path = version.storage_path
    doc.file_name = version.file_name
    doc.file_mime_type = version.file_mime_type
    doc.file_size_bytes = version.file_size_bytes
    doc.checksum_sha256 = version.checksum_sha256
    doc.processing_status = KnowledgeProcessingStatus.EXTRACTING
    doc.indexing_status = KnowledgeIndexingStatus.INDEXING
    doc.indexed_at = None
    doc.processing_error = None
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    _invalidate_knowledge_answer_cache(current_user.org_id)
    return await _to_document_read(session, doc, folder)

async def process_knowledge_document_job(document_id: UUID, version_id: UUID | None = None) -> None:
    """Backward-compatible entry point; enqueues and runs a persistent ingestion job."""
    from app.services.knowledge_ingestion_jobs import enqueue_knowledge_ingestion_job, run_knowledge_ingestion_job

    async with AsyncSessionLocal() as session:
        job = await enqueue_knowledge_ingestion_job(session, document_id, version_id)
        await session.commit()
        await run_knowledge_ingestion_job(session, job.id)

async def _collect_extraction_warnings(extracted: dict[str, object], file_name: str) -> list[str]:
    warnings: list[str] = []
    page_char_counts = extracted.get("page_char_counts")
    if isinstance(page_char_counts, list) and page_char_counts:
        low_pages = sum(1 for count in page_char_counts if int(count) < 40)
        if low_pages >= max(1, len(page_char_counts) // 3):
            warnings.append("Low-quality OCR: many pages contain very little extractable text.")
    page_count = extracted.get("page_count")
    text = str(extracted.get("text") or "")
    if isinstance(page_count, int) and page_count > 0:
        chars_per_page = len(text) / page_count
        if chars_per_page < 120:
            warnings.append("Sparse text extraction: average characters per page is low.")
    if Path(file_name).suffix.lower() == ".pdf" and len(text) < 500:
        warnings.append("Short PDF extraction: document may be image-only or poorly scanned.")
    return warnings

async def _process_document_version(
    session: AsyncSession,
    doc: KnowledgeDocument,
    version: KnowledgeDocumentVersion,
    file_bytes: bytes,
    *,
    job_id: UUID | None = None,
) -> None:
    from app.services.knowledge_ingestion_jobs import update_ingestion_job_progress

    async def _report_progress(progress: int, warnings: list[str] | None = None) -> None:
        if job_id is not None:
            await update_ingestion_job_progress(session, job_id, progress, warnings=warnings)

    extraction = KnowledgeDocumentExtraction(
        org_id=doc.org_id,
        document_id=doc.id,
        version_id=version.id,
        extraction_status=KnowledgeExtractionStatus.EXTRACTING,
    )
    session.add(extraction)
    doc.processing_status = KnowledgeProcessingStatus.EXTRACTING
    doc.processing_error = None
    await session.flush()

    processing_phase = "extraction"
    try:
        extracted = _extract_text(doc.file_name, file_bytes)
        cleaned_text = clean_extracted_text(str(extracted["text"]))
        if not cleaned_text:
            raise ValueError("No extractable text found after cleaning.")
        cleaned_sections = _clean_sections(extracted["sections"])
        cleaned_sections, headers_footers_removed = _strip_repeated_headers_footers(cleaned_sections)
        if not cleaned_sections:
            cleaned_sections = [{"text": cleaned_text, "page_number": None, "section_title": None}]
        extraction.extracted_text = cleaned_text
        extraction.extraction_status = KnowledgeExtractionStatus.SUCCEEDED
        extraction.extraction_error = None
        extraction.extracted_at = datetime.now(timezone.utc)
        doc.extracted_text = cleaned_text
        doc.processing_status = KnowledgeProcessingStatus.EXTRACTED
        if job_id is not None:
            extraction_warnings = await _collect_extraction_warnings(extracted, doc.file_name)
            await _report_progress(25, extraction_warnings)
        await session.flush()

        processing_phase = "chunking"
        doc.processing_status = KnowledgeProcessingStatus.CHUNKING
        chunks = _chunk_sections(cleaned_sections)
        metadata_complete = bool((doc.owner_approver or "").strip() and doc.effective_date is not None)
        duplicate_candidates = await _duplicate_candidate_documents(session, doc.org_id, exclude_id=doc.id)
        duplicate_warnings = detect_document_duplicates(
            org_id=str(doc.org_id),
            document_id=str(doc.id),
            title=doc.title,
            version=doc.version,
            file_name=doc.file_name,
            checksum_sha256=version.checksum_sha256 or "",
            cleaned_text=cleaned_text,
            candidates=duplicate_candidates,
        )
        page_char_counts = extracted.get("page_char_counts")
        quality_score, warnings, diagnostics = compute_extraction_score_breakdown(
            file_name=doc.file_name,
            cleaned_text=cleaned_text,
            sections=cleaned_sections,
            chunks=chunks,
            page_count=int(extracted["page_count"]) if extracted.get("page_count") is not None else None,
            headers_footers_removed=headers_footers_removed,
            metadata_complete=metadata_complete,
            duplicate_warnings=duplicate_warnings,
            page_char_counts=list(page_char_counts) if isinstance(page_char_counts, list) else None,
        )
        diagnostics["entities"] = aggregate_document_entities(chunks)
        diagnostics["cross_references"] = aggregate_cross_references(chunks)
        diagnostics["duplicate_warnings"] = duplicate_warnings
        diagnostics["chunk_intelligence"] = [_compact_chunk_intelligence(chunk) for chunk in chunks]
        diagnostics["library_analytics"] = build_library_analytics(
            chunks,
            estimated_retrieval_quality=quality_score,
        )
        extraction.diagnostics = diagnostics
        extraction.quality_score = quality_score
        chunk_rows: list[KnowledgeDocumentChunk] = []
        for index, chunk_data in enumerate(chunks):
            section_path = _encode_section_path(
                chunk_data.get("heading_level") if isinstance(chunk_data.get("heading_level"), int) else None,
                str(chunk_data.get("section_path") or chunk_data.get("section_title") or "") or None,
            )
            chunk = KnowledgeDocumentChunk(
                org_id=doc.org_id,
                document_id=doc.id,
                folder_id=doc.folder_id,
                version_id=version.id,
                chunk_index=index,
                heading=chunk_data.get("section_title"),
                section_title=chunk_data.get("section_title"),
                section_path=section_path,
                chunk_type=str(chunk_data.get("chunk_type") or "text"),
                page_number=chunk_data["page_number"],
                content=chunk_data["chunk_text"],
                chunk_text=chunk_data["chunk_text"],
                token_count=chunk_data["token_count"],
                visibility=doc.visibility,
                project=doc.project,
                department=doc.department,
            )
            session.add(chunk)
            chunk_rows.append(chunk)
        chunk_warnings = [str(item) for item in warnings]
        long_chunks = [index for index, chunk_data in enumerate(chunks) if int(chunk_data.get("token_count") or 0) > 1200]
        if long_chunks:
            chunk_warnings.append(
                f"Excessive token length: {len(long_chunks)} chunk(s) exceed 1200 tokens and may reduce retrieval quality."
            )
        if job_id is not None:
            await _report_progress(50, chunk_warnings)
        await session.flush()

        processing_phase = "embedding"
        doc.processing_status = KnowledgeProcessingStatus.EMBEDDING
        doc.indexing_status = KnowledgeIndexingStatus.INDEXING
        await session.flush()

        embeddings = await _embed_texts([chunk.chunk_text for chunk in chunk_rows])
        for chunk, embedding in zip(chunk_rows, embeddings, strict=True):
            chunk.embedding = embedding
        doc.processing_status = KnowledgeProcessingStatus.CHUNKED
        if job_id is not None:
            await _report_progress(75)
        await session.flush()

        doc.processing_status = KnowledgeProcessingStatus.READY
        doc.indexing_status = KnowledgeIndexingStatus.INDEXED
        doc.indexed_at = datetime.now(timezone.utc)
        doc.processing_error = None
        if job_id is not None:
            await _report_progress(100)
        await session.flush()
    except Exception as exc:
        if processing_phase == "extraction":
            extraction.extraction_status = KnowledgeExtractionStatus.FAILED
            extraction.extraction_error = str(exc)
            extraction.extracted_at = datetime.now(timezone.utc)
        doc.processing_status = KnowledgeProcessingStatus.FAILED
        doc.indexing_status = KnowledgeIndexingStatus.FAILED
        doc.processing_error = str(exc)
        await session.flush()
        if job_id is not None:
            raise

async def _store_upload(
    org_id: UUID,
    document_id: UUID,
    version: str,
    file_name: str,
    file_bytes: bytes,
    file_mime_type: str,
) -> dict[str, str]:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("._") or "document"
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", version).strip("._") or "version"
    storage_path = f"{org_id}/{document_id}/{safe_version}/{safe_name}"
    settings = get_settings()
    file_url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{settings.knowledge_storage_bucket}/{storage_path}"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": file_mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
        "x-upsert": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{settings.knowledge_storage_bucket}/{storage_path}",
                headers=headers,
                content=file_bytes,
            )
            response.raise_for_status()
        return {"storage_path": storage_path, "file_url": file_url}
    except Exception:
        if settings.environment != "dev":
            raise
        local_path = _save_upload_locally(org_id, document_id, version, file_name, file_bytes)
        return {"storage_path": str(local_path), "file_url": str(local_path)}

async def _read_stored_file(storage_path: str) -> bytes:
    path = Path(storage_path)
    if path.exists():
        return path.read_bytes()
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{settings.knowledge_storage_bucket}/{storage_path}",
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
            },
        )
        response.raise_for_status()
        return response.content

def _save_upload_locally(org_id: UUID, document_id: UUID, version: str, file_name: str, file_bytes: bytes) -> Path:
    root = Path(get_settings().knowledge_upload_dir)
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", version).strip("._") or "version"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("._") or "document"
    target_dir = root / str(org_id) / str(document_id) / safe_version
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / safe_name
    path.write_bytes(file_bytes)
    return path

def _strip_repeated_headers_footers(sections: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    if len(sections) < 3:
        return sections, 0
    line_counts: dict[str, int] = {}
    for section in sections:
        lines = str(section.get("text") or "").splitlines()
        for line in (*lines[:2], *lines[-2:]):
            cleaned = line.strip()
            if len(cleaned) < 8:
                continue
            line_counts[cleaned] = line_counts.get(cleaned, 0) + 1
    threshold = max(2, int(len(sections) * 0.4))
    repeated = {line for line, count in line_counts.items() if count >= threshold}
    if not repeated:
        return sections, 0
    removed_lines = 0
    cleaned_sections: list[dict[str, object]] = []
    for section in sections:
        lines = [line for line in str(section.get("text") or "").splitlines() if line.strip() not in repeated]
        removed_lines += len(str(section.get("text") or "").splitlines()) - len(lines)
        text = "\n".join(lines).strip()
        if text:
            cleaned_sections.append({**section, "text": text})
    return cleaned_sections or sections, removed_lines

def _parse_heading_line(line: str) -> tuple[str | None, int | None]:
    markdown_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
    if markdown_match:
        return markdown_match.group(2).strip(), len(markdown_match.group(1))
    detected = _detect_section_title(line)
    if detected:
        return detected, 2
    return None, None

def _encode_section_path(level: int | None, path: str | None) -> str | None:
    if level is None and not path:
        return None
    if level is not None:
        base = path or ""
        return f"H{level}|{base}" if base else f"H{level}"
    return path

def _decode_section_path(value: str | None) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    match = re.match(r"^H(\d+)\|?(.*)$", value)
    if match:
        level = int(match.group(1))
        path = match.group(2) or None
        return level, path
    return None, value

def _is_table_like_text(text: str) -> bool:
    return is_table_like_text(text)

def _count_operational_keywords(text: str) -> int:
    return count_operational_keywords(text)

def _compact_chunk_intelligence(chunk: dict[str, object]) -> dict[str, object]:
    return {
        "chunk_index": chunk.get("chunk_index"),
        "chunk_summary": chunk.get("chunk_summary"),
        "contains_procedure": chunk.get("contains_procedure"),
        "contains_warning": chunk.get("contains_warning"),
        "contains_decision": chunk.get("contains_decision"),
        "contains_checklist": chunk.get("contains_checklist"),
        "contains_table": chunk.get("contains_table"),
        "contains_roles": chunk.get("contains_roles"),
        "contains_dates": chunk.get("contains_dates"),
        "entities": chunk.get("entities"),
        "cross_references": chunk.get("cross_references"),
    }

async def _duplicate_candidate_documents(
    session: AsyncSession,
    org_id: UUID,
    *,
    exclude_id: UUID,
) -> list[dict[str, object]]:
    rows = list(
        (
            await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.org_id == org_id,
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeDocument.id != exclude_id,
                )
            )
        ).scalars()
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "version": row.version,
            "file_name": row.file_name,
            "checksum_sha256": row.checksum_sha256,
            "extracted_text": row.extracted_text,
        }
        for row in rows
    ]

def _analyze_extraction_quality(
    *,
    file_name: str,
    raw_text: str,
    cleaned_text: str,
    sections: list[dict[str, object]],
    chunks: list[dict[str, object]],
    page_count: int | None = None,
    headers_footers_removed: int = 0,
) -> tuple[list[str], int, dict[str, object]]:
    del raw_text
    score, warnings, diagnostics = compute_extraction_score_breakdown(
        file_name=file_name,
        cleaned_text=cleaned_text,
        sections=sections,
        chunks=chunks,
        page_count=page_count,
        headers_footers_removed=headers_footers_removed,
        metadata_complete=True,
        duplicate_warnings=[],
        page_char_counts=None,
    )
    return warnings, score, diagnostics

def _extract_text(file_name: str, file_bytes: bytes) -> dict[str, object]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise ValueError("Unsupported file type.")
    if suffix == ".pdf":
        return _extract_pdf(file_bytes)
    if suffix == ".docx":
        return _extract_docx(file_bytes)
    if suffix == ".csv":
        return _extract_csv(file_bytes)
    if suffix in TEXT_EXTENSIONS:
        text = file_bytes.decode("utf-8", errors="replace").strip()
        return {"text": text, "sections": _sections_from_text(text)}
    raise ValueError("Unsupported file type.")

def _extract_pdf(file_bytes: bytes) -> dict[str, object]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires PyMuPDF.") from exc
    sections: list[dict[str, object]] = []
    page_char_counts: list[int] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        page_count = len(pdf)
        for index, page in enumerate(pdf, start=1):
            text = page.get_text("text", sort=True).strip()
            page_char_counts.append(len(text))
            if text:
                sections.extend(_sections_from_text(text, page_number=index))
    full_text = "\n\n".join(str(item["text"]) for item in sections).strip()
    if not full_text:
        raise ValueError("No extractable text found in PDF.")
    return {"text": full_text, "sections": sections, "page_count": page_count, "page_char_counts": page_char_counts}

def _extract_docx(file_bytes: bytes) -> dict[str, object]:
    try:
        import mammoth  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("DOCX extraction requires mammoth.") from exc
    result = mammoth.extract_raw_text(io.BytesIO(file_bytes))
    text = _normalize_compact_document_text(result.value.strip())
    if not text:
        raise ValueError("No extractable text found in DOCX.")
    return {"text": text, "sections": _sections_from_text(text)}

def _extract_csv(file_bytes: bytes) -> dict[str, object]:
    raw = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(raw))
    rows = []
    for index, row in enumerate(reader, start=1):
        cleaned = [cell.strip() for cell in row if cell.strip()]
        if cleaned:
            rows.append(f"Row {index}: " + " | ".join(cleaned))
    text = "\n".join(rows).strip()
    if not text:
        raise ValueError("No extractable text found in CSV.")
    return {"text": text, "sections": _sections_from_text(text)}

def clean_extracted_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = _normalize_compact_document_text(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    current = ""
    for line in lines:
        if not line:
            if current:
                paragraphs.append(current.strip())
                current = ""
            continue
        if _is_standalone_heading(line):
            if current:
                paragraphs.append(current.strip())
            paragraphs.append(line)
            current = ""
            continue
        if not current:
            current = line
            continue
        if _should_join_wrapped_line(current, line):
            current = f"{current} {line}"
        else:
            paragraphs.append(current.strip())
            current = line
    if current:
        paragraphs.append(current.strip())
    return "\n".join(paragraphs).strip()


# Compatibility export for callers that import the previous private helper.
_clean_text = clean_extracted_text

def _normalize_compact_document_text(text: str) -> str:
    replacements = [
        (r"(?<!\n)(Purpose)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Scope)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Procedure)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Responsibilities)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Requirements)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Project Summary)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Challenges Encountered)(?=[A-Z0-9-])", r"\n\1\n"),
        (r"(?<!\n)(Actions Taken)(?=[A-Z0-9-])", r"\n\1\n"),
        (r"(?<!\n)(Results)(?=[A-Z0-9-])", r"\n\1\n"),
        (r"(?<!\n)(Recommendations)(?=[A-Z0-9-])", r"\n\1\n"),
        (r"(?<!\n)(Best Practices)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Lessons Learned)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Quality Guidance)(?=[A-Z])", r"\n\1\n"),
        (r"(?<!\n)(Phase\s+\d+:\s*[^-]+)-\s*", r"\n\1\n- "),
        (r"(?<![\d\n])([1-9]\d?\.\s+)", r"\n\1"),
        (r"(?<=[a-z0-9\)%])-\s*(?=[A-Z][A-Za-z]+(?:\s|$))", r"\n- "),
        (r"(?<=[.;:])\s+-\s*(?=[A-Z][A-Za-z]+(?:\s|$))", r"\n- "),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text

def _is_standalone_heading(line: str) -> bool:
    if line.lstrip().startswith(("-", "*")):
        return False
    if re.match(r"^\d+[\.)]\s+", line):
        return False
    detected = _detect_section_title(line)
    return bool(detected and detected == line.strip().rstrip(":"))

def _should_join_wrapped_line(previous: str, current: str) -> bool:
    if _is_standalone_heading(current):
        return False
    if previous.lstrip().startswith("-") or current.lstrip().startswith("-"):
        return False
    if re.match(r"^\d+[\.)]\s+", previous.strip()) or re.match(r"^\d+[\.)]\s+", current.strip()):
        return False
    if len(previous) <= 80 and ":" in previous and ":" in current:
        return False
    if previous.endswith((".", "?", "!", ";")) and current[:1].isupper():
        return False
    return True

def _clean_sections(sections: object) -> list[dict[str, object]]:
    cleaned: list[dict[str, object]] = []
    if not isinstance(sections, list):
        return cleaned
    for section in sections:
        if not isinstance(section, dict):
            continue
        text = clean_extracted_text(str(section.get("text") or ""))
        if not text:
            continue
        title = _clean_optional(str(section.get("section_title"))) if section.get("section_title") else None
        page_number = section.get("page_number")
        heading_level = section.get("heading_level")
        section_path = section.get("section_path") or title
        chunk_type = "table" if _is_table_like_text(text) else str(section.get("chunk_type") or "text")
        cleaned.append(
            {
                "text": text,
                "page_number": page_number,
                "section_title": title,
                "section_path": section_path,
                "heading_level": heading_level,
                "chunk_type": chunk_type,
            }
        )
    return cleaned

def _sections_from_text(text: str, page_number: int | None = None) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current_title: str | None = None
    current_level: int | None = None
    path_stack: list[tuple[int, str]] = []
    buffer: list[str] = []

    def _append_section() -> None:
        nonlocal buffer, current_title, current_level
        if not buffer:
            return
        if not _buffer_has_body(buffer, current_title):
            return
        section_text = "\n".join(buffer).strip()
        section_path = " > ".join(item[1] for item in path_stack) if path_stack else current_title
        sections.append(
            {
                "text": section_text,
                "page_number": page_number,
                "section_title": current_title,
                "section_path": section_path,
                "heading_level": current_level,
                "chunk_type": "table" if _is_table_like_text(section_text) else "text",
            }
        )
        buffer = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        title, level = _parse_heading_line(line)
        if title:
            _append_section()
            if level is None:
                level = 2
            while path_stack and path_stack[-1][0] >= level:
                path_stack.pop()
            path_stack.append((level, title))
            current_title = title
            current_level = level
            buffer.append(line)
        else:
            buffer.append(line)
    if buffer:
        section_text = "\n".join(buffer).strip()
        section_path = " > ".join(item[1] for item in path_stack) if path_stack else current_title
        sections.append(
            {
                "text": section_text,
                "page_number": page_number,
                "section_title": current_title,
                "section_path": section_path,
                "heading_level": current_level,
                "chunk_type": "table" if _is_table_like_text(section_text) else "text",
            }
        )
    if not sections and text.strip():
        body = text.strip()
        sections.append(
            {
                "text": body,
                "page_number": page_number,
                "section_title": current_title,
                "section_path": current_title,
                "heading_level": current_level,
                "chunk_type": "table" if _is_table_like_text(body) else "text",
            }
        )
    return sections

def _buffer_has_body(buffer: list[str], current_title: str | None) -> bool:
    for line in buffer:
        if current_title and line.strip() == current_title.strip():
            continue
        if _is_standalone_heading(line):
            continue
        return True
    return False

def _detect_section_title(line: str) -> str | None:
    if line.startswith("#"):
        return line.lstrip("#").strip() or None
    if line.lstrip().startswith(("-", "*")):
        return None
    if re.match(r"^[A-Z][A-Za-z ]{2,}:$", line):
        return line.rstrip(":").strip()
    if re.match(r"^\d+[\.)]\s+", line):
        return None
    if len(line) <= 90 and line.isupper() and any(char.isalpha() for char in line):
        return line.strip()
    if (
        len(line) <= 90
        and any(char.isalpha() for char in line)
        and not re.search(r"[.!?]$", line)
        and len(line.split()) <= 8
        and sum(1 for word in line.split() if word[:1].isupper()) >= max(1, len(line.split()) - 1)
    ):
        return line.strip()
    if line in {
        "Project Summary",
        "Challenges Encountered",
        "Actions Taken",
        "Results",
        "Recommendations",
    }:
        return line
    return None

def _chunk_sections(sections: list[dict[str, object]]) -> list[dict[str, object]]:
    return chunk_sections_semantic(sections)

def _rebuild_chunk_text(source_text: str, chunk_words: list[str]) -> str:
    plain = " ".join(chunk_words).strip()
    if len(chunk_words) >= len(re.findall(r"\S+", source_text)):
        return source_text
    return plain

async def _embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    client = get_openai_client()
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        response = await client.embeddings.create(model=settings.knowledge_embedding_model, input=batch)
        ordered = sorted(response.data, key=lambda item: item.index)
        for item in ordered:
            vector = [float(value) for value in item.embedding]
            if len(vector) != settings.knowledge_embedding_dimensions:
                raise RuntimeError(
                    f"Embedding dimension mismatch: expected {settings.knowledge_embedding_dimensions}, got {len(vector)}."
                )
            embeddings.append(vector)
    return embeddings

def _assess_upload_quality(
    source_type: KnowledgeSourceType,
    status: KnowledgeDocumentStatus,
    owner_approver: str,
    effective_date: date | None,
) -> list[str]:
    warnings: list[str] = []
    owner_clean = owner_approver.strip()
    if not owner_clean:
        warnings.append("Add an owner/approver before approving for retrieval.")
    if effective_date is None:
        warnings.append("Set an effective date to avoid stale-document flags.")
    if source_type == KnowledgeSourceType.SOP and effective_date is None:
        warnings.append("SOPs without an effective date are auto-flagged stale after 12 months.")
    if status == KnowledgeDocumentStatus.APPROVED and not owner_clean:
        warnings.append("Approved documents require an owner/approver.")
    if status == KnowledgeDocumentStatus.APPROVED and effective_date is None:
        warnings.append("Approved documents require an effective date.")
    return warnings

def _upload_block_message(
    status: KnowledgeDocumentStatus,
    owner_approver: str,
    effective_date: date | None,
) -> str | None:
    if status != KnowledgeDocumentStatus.APPROVED:
        return None
    if not owner_approver.strip():
        return "Approved uploads require an owner/approver before indexing."
    if effective_date is None:
        return "Approved uploads require an effective date before indexing."
    return None

def _post_index_quality_warnings(read: KnowledgeDocumentRead) -> list[str]:
    warnings: list[str] = []
    if read.status == "approved" and read.chunk_count == 0:
        warnings.append("Document was approved but produced no indexed chunks — re-upload or re-index.")
    if read.extraction_quality_score is not None and read.extraction_quality_score < 70:
        warnings.append(
            f"Extraction quality score is {read.extraction_quality_score}/100 — review structure before relying on retrieval."
        )
    if read.reindex_recommended and read.processing_status == "ready":
        warnings.append("Re-index or re-upload is recommended to improve retrieval quality.")
    if read.ocr_needed:
        warnings.append("OCR is recommended for this document.")
    if read.quality_score and read.status == "approved":
        if read.quality_score.score < UPLOAD_APPROVED_MIN_METADATA_SCORE:
            failed = [item.label for item in read.quality_score.criteria if not item.passed]
            if failed:
                warnings.append(f"Quality score {read.quality_score.score}/{read.quality_score.max_score}: missing {', '.join(failed)}.")
    return warnings
