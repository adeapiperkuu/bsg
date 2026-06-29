import hashlib
import csv
import difflib
import io
import asyncio
import logging
import mimetypes
import re
import math
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.agents.knowledge.retrieval import keyword_search
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
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
    KnowledgeGap,
    KnowledgeGapStatus,
    KnowledgeIndexingStatus,
    KnowledgeLesson,
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
from app.schemas.domain import (
    KnowledgeAskRead,
    KnowledgeCitationRead,
    KnowledgeConversationTurn,
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentVersionRead,
    KnowledgeEvalMetricsRead,
    KnowledgeEvalQuestionCreate,
    KnowledgeEvalQuestionRead,
    KnowledgeEvalQuestionUpdate,
    KnowledgeEvalRunItemRead,
    KnowledgeEvalRunRead,
    KnowledgeFeedbackRead,
    KnowledgeGapRead,
    KnowledgeGapTodoRead,
    KnowledgeLibraryHealthRead,
    KnowledgeLessonCreate,
    KnowledgeLessonRead,
    KnowledgeChunkRead,
    KnowledgeQualityCriterion,
    KnowledgeQualityScore,
    KnowledgeRetrievalSettingsRead,
    KnowledgeRetrievalSettingsUpdate,
    KnowledgeSearchResult,
    KnowledgeStructuredAnswer,
    KnowledgeVersionCompareRead,
)
from app.services.llm.client import FAST_PATH_THRESHOLD, LLMClient, RAG_CONTEXT_CHUNK_CHARS
from app.services.llm.openai_client import get_openai_client
from app.services.notifications import create_notification

logger = logging.getLogger(__name__)
KNOWLEDGE_AGENT_NAME = "operational_knowledge_agent"


async def list_lessons(
    session: AsyncSession,
    org_id,
    *,
    limit: int = 50,
) -> list[KnowledgeLesson]:
    return list(
        (
            await session.execute(
                select(KnowledgeLesson)
                .where(KnowledgeLesson.org_id == org_id)
                .order_by(KnowledgeLesson.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def create_lesson(
    session: AsyncSession,
    org_id,
    payload: KnowledgeLessonCreate,
    created_by: UUID,
) -> KnowledgeLesson:
    lesson = KnowledgeLesson(
        org_id=org_id,
        title=payload.title,
        body=payload.body,
        tags=payload.tags,
        linked_quality_event_id=payload.linked_quality_event_id,
        linked_alert_id=payload.linked_alert_id,
        created_by=created_by,
    )
    session.add(lesson)
    await session.flush()
    return lesson


async def search_knowledge(
    session: AsyncSession,
    org_id,
    query: str,
) -> list[KnowledgeSearchResult]:
    hits = await keyword_search(session, org_id, query)
    return [KnowledgeSearchResult.model_validate(h) for h in hits]


def _is_missing_schema_error(exc: BaseException) -> bool:
    if isinstance(exc, ProgrammingError):
        message = str(exc).lower()
        return "does not exist" in message
    orig = getattr(exc, "orig", None)
    if orig is not None:
        name = type(orig).__name__.lower()
        return "undefinedtable" in name or "undefinedcolumn" in name
    return False


FOLDER_SEED = (
    (KnowledgeFolderKind.SOPS, "SOPs", 0),
    (KnowledgeFolderKind.GUIDES, "Guides", 1),
    (KnowledgeFolderKind.HISTORIES, "Histories", 2),
)
FOLDER_DEFAULTS = {kind: (name, order) for kind, name, order in FOLDER_SEED}

LIST_DOCUMENT_LOAD_OPTIONS = load_only(
    KnowledgeDocument.id,
    KnowledgeDocument.org_id,
    KnowledgeDocument.folder_id,
    KnowledgeDocument.title,
    KnowledgeDocument.source_type,
    KnowledgeDocument.version,
    KnowledgeDocument.visibility,
    KnowledgeDocument.status,
    KnowledgeDocument.owner_approver,
    KnowledgeDocument.effective_date,
    KnowledgeDocument.file_name,
    KnowledgeDocument.file_mime_type,
    KnowledgeDocument.file_url,
    KnowledgeDocument.processing_status,
    KnowledgeDocument.processing_error,
    KnowledgeDocument.indexing_status,
    KnowledgeDocument.approved_by,
    KnowledgeDocument.approved_at,
    KnowledgeDocument.created_at,
    KnowledgeDocument.updated_at,
    KnowledgeDocument.active_version_id,
)

TEXT_EXTENSIONS = {".txt", ".md"}
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}
NO_APPROVED_ANSWER = "I could not find this information in the uploaded knowledge base."
STRONG_RELEVANCE_THRESHOLD = 0.6
CHUNK_TARGET_TOKENS = 900
CHUNK_OVERLAP_TOKENS = 120
EMBEDDING_BATCH_SIZE = 64
EMBEDDING_INPUT_MAX_CHARS = 2000
TERM_FALLBACK_CHUNK_LIMIT = 500
RERANK_CANDIDATE_LIMIT = 20
NEIGHBOR_CHUNK_WINDOW = 1
HYBRID_VECTOR_WEIGHT = 0.68
HYBRID_KEYWORD_WEIGHT = 0.32
RECENCY_BOOST_MAX = 0.12
EXACT_TERM_BOOST_MAX = 0.1
LOW_CONFIDENCE_THRESHOLD = 0.5  # retry with strong model if first-pass confidence is below this
SOP_STALE_DAYS = 365
UPLOAD_APPROVED_MIN_METADATA_SCORE = 4  # out of 6 metadata criteria before indexing as Approved

# ── Embedding TTL cache (in-process, per org) ─────────────────────────────────
_EMBED_CACHE_TTL_S = 300      # 5 minutes
_EMBED_CACHE_MAX = 1000       # max entries before eviction

# {(org_id, embedding_input) → (vector, expires_monotonic)}
_embed_cache: dict[tuple[str, str], tuple[list[float], float]] = {}


def _embed_cache_get(org_id: str, text: str) -> list[float] | None:
    entry = _embed_cache.get((org_id, text))
    if entry is None:
        return None
    vector, expires = entry
    if time.monotonic() > expires:
        _embed_cache.pop((org_id, text), None)
        return None
    return vector


def _embed_cache_set(org_id: str, text: str, vector: list[float]) -> None:
    key = (org_id, text)
    if len(_embed_cache) >= _EMBED_CACHE_MAX and key not in _embed_cache:
        now = time.monotonic()
        expired_keys = [k for k, (_, exp) in _embed_cache.items() if exp <= now]
        for k in expired_keys:
            del _embed_cache[k]
        if len(_embed_cache) >= _EMBED_CACHE_MAX:
            for k in list(_embed_cache.keys())[:100]:
                del _embed_cache[k]
    _embed_cache[key] = (vector, time.monotonic() + _EMBED_CACHE_TTL_S)


# ── Lightweight chunk carrier from single-SQL vector search ───────────────────

@dataclass
class _VectorChunk:
    """All chunk fields needed for RAG — no second ORM round-trip required."""
    id: UUID
    document_id: UUID
    version_id: UUID | None
    chunk_index: int
    chunk_text: str | None
    content: str | None
    page_number: int | None
    section_title: str | None


def _sse(data: dict[str, object]) -> str:
    """Format a dict as a single SSE line."""
    import json as _json
    return f"data: {_json.dumps(data, default=str)}\n\n"


def can_access_visibility(role: AppRole, visibility: KnowledgeVisibility) -> bool:
    if role == AppRole.SUPER_ADMIN:
        return True
    if role == AppRole.BSG_LEADERSHIP:
        return visibility in {
            KnowledgeVisibility.INTERNAL_ONLY,
            KnowledgeVisibility.LEADERSHIP_ONLY,
            KnowledgeVisibility.CLIENT_SAFE,
        }
    if role == AppRole.DELIVERY_MANAGER:
        return visibility in {KnowledgeVisibility.INTERNAL_ONLY, KnowledgeVisibility.CLIENT_SAFE}
    if role == AppRole.CLIENT:
        return visibility == KnowledgeVisibility.CLIENT_SAFE
    return False


async def list_knowledge_folders(session: AsyncSession, org_id: UUID) -> list[KnowledgeFolder]:
    rows = list(
        (
            await session.execute(
                select(KnowledgeFolder).where(KnowledgeFolder.org_id == org_id, KnowledgeFolder.deleted_at.is_(None))
            )
        ).scalars()
    )
    return sorted(rows, key=lambda row: (row.display_order, row.name.lower()))


async def ensure_knowledge_folders(session: AsyncSession, org_id: UUID) -> list[KnowledgeFolder]:
    existing = await list_knowledge_folders(session, org_id)
    if existing:
        return existing
    created: list[KnowledgeFolder] = []
    for kind, name, order in FOLDER_SEED:
        folder = KnowledgeFolder(org_id=org_id, name=name, folder_kind=kind, display_order=order)
        session.add(folder)
        created.append(folder)
    await session.flush()
    return created


async def create_knowledge_folder(
    session: AsyncSession,
    org_id: UUID,
    *,
    folder_kind: KnowledgeFolderKind,
    name: str,
    display_order: int | None = None,
) -> KnowledgeFolder:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ApiError(400, "VALIDATION_ERROR", "Folder name is required.")

    if folder_kind != KnowledgeFolderKind.CUSTOM:
        existing = (
            await session.execute(
                select(KnowledgeFolder).where(
                    KnowledgeFolder.org_id == org_id,
                    KnowledgeFolder.folder_kind == folder_kind,
                    KnowledgeFolder.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.name = cleaned_name
            await session.flush()
            return existing

        default_name, default_order = FOLDER_DEFAULTS[folder_kind]
        folder = KnowledgeFolder(
            org_id=org_id,
            name=cleaned_name or default_name,
            folder_kind=folder_kind,
            display_order=default_order if display_order is None else display_order,
        )
        session.add(folder)
        await session.flush()
        return folder

    existing_folders = await list_knowledge_folders(session, org_id)
    next_order = display_order
    if next_order is None:
        next_order = max((row.display_order for row in existing_folders), default=len(FOLDER_SEED) - 1) + 1
    folder = KnowledgeFolder(
        org_id=org_id,
        name=cleaned_name,
        folder_kind=KnowledgeFolderKind.CUSTOM,
        display_order=next_order,
    )
    session.add(folder)
    await session.flush()
    return folder


def _infer_folder_kind(name: str, taken_seed_kinds: set[KnowledgeFolderKind]) -> KnowledgeFolderKind:
    lowered = name.lower()
    if "sop" in lowered and KnowledgeFolderKind.SOPS not in taken_seed_kinds:
        return KnowledgeFolderKind.SOPS
    if "guide" in lowered and KnowledgeFolderKind.GUIDES not in taken_seed_kinds:
        return KnowledgeFolderKind.GUIDES
    if "histor" in lowered and KnowledgeFolderKind.HISTORIES not in taken_seed_kinds:
        return KnowledgeFolderKind.HISTORIES
    for kind in (KnowledgeFolderKind.SOPS, KnowledgeFolderKind.GUIDES, KnowledgeFolderKind.HISTORIES):
        if kind not in taken_seed_kinds:
            return kind
    return KnowledgeFolderKind.CUSTOM


async def create_knowledge_folder_by_name(session: AsyncSession, org_id: UUID, *, name: str) -> KnowledgeFolder:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ApiError(400, "VALIDATION_ERROR", "Folder name is required.")

    existing = await list_knowledge_folders(session, org_id)
    if any(row.name.lower() == cleaned_name.lower() for row in existing):
        raise ApiError(409, "CONFLICT", "A folder with this name already exists.")

    taken_seed_kinds = {
        row.folder_kind
        for row in existing
        if row.folder_kind in {KnowledgeFolderKind.SOPS, KnowledgeFolderKind.GUIDES, KnowledgeFolderKind.HISTORIES}
    }
    folder_kind = _infer_folder_kind(cleaned_name, taken_seed_kinds)
    return await create_knowledge_folder(session, org_id, folder_kind=folder_kind, name=cleaned_name)


async def get_folder_by_id(session: AsyncSession, org_id: UUID, folder_id: UUID) -> KnowledgeFolder:
    folder = (
        await session.execute(
            select(KnowledgeFolder).where(
                KnowledgeFolder.id == folder_id,
                KnowledgeFolder.org_id == org_id,
                KnowledgeFolder.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge folder not found.")
    return folder


async def get_folder_for_kind(session: AsyncSession, org_id: UUID, folder_kind: KnowledgeFolderKind) -> KnowledgeFolder:
    folder = (
        await session.execute(
            select(KnowledgeFolder).where(
                KnowledgeFolder.org_id == org_id,
                KnowledgeFolder.folder_kind == folder_kind,
                KnowledgeFolder.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if folder is not None:
        return folder

    default_name, display_order = FOLDER_DEFAULTS[folder_kind]
    folder = KnowledgeFolder(org_id=org_id, name=default_name, folder_kind=folder_kind, display_order=display_order)
    session.add(folder)
    await session.flush()
    return folder


async def list_documents(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    source_type: str | None = None,
    owner: str | None = None,
    visibility: str | None = None,
    ready: bool | None = None,
    workflow_state: str | None = None,
    effective_date_from: date | None = None,
    effective_date_to: date | None = None,
    semantic_query: str | None = None,
    folders_ready: bool = False,
) -> list[KnowledgeDocumentRead]:
    cross_org = current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}
    if not cross_org and not folders_ready:
        await ensure_knowledge_folders(session, current_user.org_id)

    doc_filters = [KnowledgeDocument.deleted_at.is_(None)]
    if not cross_org:
        doc_filters.append(KnowledgeDocument.org_id == current_user.org_id)

    docs = list(
        (
            await session.execute(
                select(KnowledgeDocument)
                .options(LIST_DOCUMENT_LOAD_OPTIONS)
                .where(*doc_filters)
                .order_by(KnowledgeDocument.title)
            )
        ).scalars()
    )
    if cross_org:
        for org_id in {doc.org_id for doc in docs}:
            await ensure_knowledge_folders(session, org_id)

    folder_filters = [KnowledgeFolder.deleted_at.is_(None)]
    if not cross_org:
        folder_filters.append(KnowledgeFolder.org_id == current_user.org_id)
    folders = {
        row.id: row
        for row in (await session.execute(select(KnowledgeFolder).where(*folder_filters))).scalars()
    }
    visible = [doc for doc in docs if can_access_visibility(current_user.role, doc.visibility)]

    if source_type:
        visible = [doc for doc in visible if doc.source_type.value == source_type]
    if owner:
        owner_q = owner.strip().lower()
        visible = [doc for doc in visible if owner_q in (doc.owner_approver or "").lower()]
    if visibility:
        visible = [doc for doc in visible if doc.visibility.value == visibility]
    if effective_date_from:
        visible = [doc for doc in visible if doc.effective_date and doc.effective_date >= effective_date_from]
    if effective_date_to:
        visible = [doc for doc in visible if doc.effective_date and doc.effective_date <= effective_date_to]

    preload_map = await _batch_document_list_stats(session, visible)

    reads: list[KnowledgeDocumentRead] = []
    for doc in visible:
        folder = folders.get(doc.folder_id)
        if folder is None:
            continue
        preload = preload_map.get(doc.id)
        if preload is None:
            continue
        read = _to_document_list_read(doc, folder, preload)
        if ready is not None:
            is_ready = _is_retrieval_ready(doc)
            if ready != is_ready:
                continue
        if workflow_state and read.workflow_state != workflow_state:
            continue
        reads.append(read)

    if semantic_query and semantic_query.strip():
        reads = await _rank_documents_semantic(session, semantic_query.strip(), reads)

    return reads


async def get_knowledge_bootstrap(
    session: AsyncSession,
    current_user: CurrentUser,
) -> tuple[list[KnowledgeFolder], list[KnowledgeDocumentRead], KnowledgeLibraryHealthRead]:
    cross_org = current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}
    if not cross_org:
        await ensure_knowledge_folders(session, current_user.org_id)
    folders = await list_knowledge_folders(session, current_user.org_id)
    documents = await list_documents(session, current_user, folders_ready=True)
    health = await build_library_health(session, current_user.org_id, documents)
    return folders, documents, health


async def get_document(session: AsyncSession, current_user: CurrentUser, document_id: UUID) -> KnowledgeDocumentRead:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot access this document.")
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)


async def get_document_file_download(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
) -> tuple[bytes, str, str]:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot download this document.")
    if not doc.storage_path:
        raise ApiError(404, "NOT_FOUND", "The uploaded file is not available for download.")
    file_bytes = await _read_stored_file(doc.storage_path)
    return file_bytes, doc.file_name, doc.file_mime_type or "application/octet-stream"


async def update_document(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentUpdate,
) -> KnowledgeDocumentRead:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "You cannot update knowledge documents.")
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot update this document.")
    if payload.title is not None:
        doc.title = payload.title.strip()
    if payload.folder_id is not None:
        doc.folder_id = (await get_folder_by_id(session, current_user.org_id, payload.folder_id)).id
    elif payload.folder_kind is not None:
        doc.folder_id = (await get_folder_for_kind(session, current_user.org_id, KnowledgeFolderKind(payload.folder_kind))).id
    if payload.source_type is not None:
        doc.source_type = KnowledgeSourceType(payload.source_type)
    if payload.version is not None:
        new_version = payload.version.strip()
        version_changed = new_version != doc.version
        doc.version = new_version
    else:
        version_changed = False
    if payload.visibility is not None:
        doc.visibility = KnowledgeVisibility(payload.visibility)
    if payload.status is not None:
        doc.status = KnowledgeDocumentStatus(payload.status)
        if doc.status == KnowledgeDocumentStatus.APPROVED:
            doc.approved_by = current_user.id
            doc.approved_at = datetime.now(UTC)
    if payload.owner_approver is not None:
        doc.owner_approver = payload.owner_approver.strip()
    if payload.effective_date is not None:
        doc.effective_date = payload.effective_date
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    if version_changed and doc.active_version_id:
        version_row = (
            await session.execute(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == doc.active_version_id)
            )
        ).scalar_one_or_none()
        if version_row and version_row.storage_path:
            file_bytes = await _read_stored_file(version_row.storage_path)
            doc.processing_status = KnowledgeProcessingStatus.UPLOADED
            doc.indexing_status = KnowledgeIndexingStatus.NOT_INDEXED
            doc.indexed_at = None
            doc.processing_error = None
            await session.flush()
            await _process_document_version(session, doc, version_row, file_bytes)
    await _notify_knowledge_stakeholders(
        session,
        doc,
        title="Knowledge document updated",
        body=f'"{doc.title}" was updated and may need review or re-approval.',
        actor_id=current_user.id,
    )
    return await _to_document_read(session, doc, folder)


async def delete_document(session: AsyncSession, current_user: CurrentUser, document_id: UUID) -> None:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "You cannot delete knowledge documents.")
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot delete this document.")
    doc.deleted_at = datetime.now(UTC)


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
    if Path(file_name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ApiError(400, "VALIDATION_ERROR", "Unsupported file type. Use PDF, DOCX, TXT, MD, or CSV.")

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
        indexing_status=KnowledgeIndexingStatus.NOT_INDEXED,
        processing_status=KnowledgeProcessingStatus.UPLOADED,
        uploaded_by=current_user.id,
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
        doc.upload_date = datetime.now(UTC)
        doc.description = description.strip() if description else doc.description
        doc.processing_status = KnowledgeProcessingStatus.UPLOADED
        doc.indexing_status = KnowledgeIndexingStatus.NOT_INDEXED
        doc.indexed_at = None
        doc.processing_error = None
    else:
        session.add(doc)
    if status == KnowledgeDocumentStatus.APPROVED:
        doc.approved_by = current_user.id
        doc.approved_at = datetime.now(UTC)
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
        version = f"{version}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    storage = await _store_upload(current_user.org_id, doc.id, version, file_name, file_bytes, file_mime_type)
    previous_versions = list(
        (await session.execute(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == doc.id))).scalars()
    )
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
        uploaded_by=current_user.id,
    )
    session.add(version_row)
    await session.flush()

    doc.active_version_id = version_row.id
    doc.version = version
    doc.file_url = storage["file_url"]
    doc.storage_path = storage["storage_path"]
    await session.flush()

    await _process_document_version(session, doc, version_row, file_bytes)
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
    post_index_warnings = _post_index_quality_warnings(read)
    if post_index_warnings:
        return read.model_copy(update={"quality_warnings": post_index_warnings})
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
    file_bytes = await _read_stored_file(source_version.storage_path)
    reindex_version = f"{source_version.version}-reindex-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
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
    doc.indexing_status = KnowledgeIndexingStatus.NOT_INDEXED
    doc.indexed_at = None
    doc.processing_error = None
    await session.flush()
    await _process_document_version(session, doc, version, file_bytes)
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)


async def ask_knowledge_agent(
    session: AsyncSession,
    current_user: CurrentUser,
    query_text: str,
    *,
    conversation_history: list[KnowledgeConversationTurn] | None = None,
    answer_mode: str = "internal",
    include_histories: bool = True,
    max_sources: int = 5,
    min_relevance_score: float = 0.25,
    project: str | None = None,
    department: str | None = None,
) -> KnowledgeAskRead:
    started = datetime.now(UTC)
    max_sources = max(1, min(max_sources, 10))
    min_relevance_score = max(0.0, min(min_relevance_score, 1.0))
    client_safe_mode = answer_mode == "client_safe"
    history = conversation_history or []
    retrieval_query = await _build_standalone_retrieval_query(query_text, history)
    embedding_input = (
        retrieval_query[:EMBEDDING_INPUT_MAX_CHARS]
        if len(retrieval_query) > EMBEDDING_INPUT_MAX_CHARS
        else retrieval_query
    )
    # Use cached embedding if available for this org+query, otherwise embed in parallel
    org_id_str = str(current_user.org_id)
    cached_vec = _embed_cache_get(org_id_str, embedding_input)
    if cached_vec is not None:
        query_embedding = cached_vec
        has_embeddings = True
        embedding_task = None
    else:
        embedding_task = asyncio.create_task(_embed_texts([embedding_input]))

    doc_filters = (
        KnowledgeDocument.org_id == current_user.org_id,
        KnowledgeDocument.deleted_at.is_(None),
        KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
        KnowledgeDocument.indexing_status == KnowledgeIndexingStatus.INDEXED,
        KnowledgeDocument.processing_status == KnowledgeProcessingStatus.READY,
    )
    docs_result, folders_result = await asyncio.gather(
        session.execute(select(KnowledgeDocument).where(*doc_filters)),
        session.execute(
            select(KnowledgeFolder).where(
                KnowledgeFolder.org_id == current_user.org_id,
                KnowledgeFolder.deleted_at.is_(None),
            )
        ),
    )
    docs = list(docs_result.scalars())
    folders_map: dict[UUID, KnowledgeFolder] = {row.id: row for row in folders_result.scalars()}
    eligible_docs = [doc for doc in docs if can_access_visibility(current_user.role, doc.visibility)]
    if client_safe_mode:
        eligible_docs = [
            doc for doc in eligible_docs if doc.visibility == KnowledgeVisibility.CLIENT_SAFE
        ]
    if not eligible_docs:
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="No approved documents are available for your role.",
        )

    if not include_histories:
        eligible_docs = [
            doc
            for doc in eligible_docs
            if folders_map.get(doc.folder_id) and folders_map[doc.folder_id].folder_kind != KnowledgeFolderKind.HISTORIES
        ]
    if project:
        project_query = project.strip().lower()
        eligible_docs = [doc for doc in eligible_docs if (doc.project or "").lower() == project_query]
    if department:
        department_query = department.strip().lower()
        eligible_docs = [doc for doc in eligible_docs if (doc.department or "").lower() == department_query]
    if not eligible_docs:
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="No documents matched the project or department filters.",
        )

    doc_ids = [doc.id for doc in eligible_docs]
    active_version_ids = [doc.active_version_id for doc in eligible_docs if doc.active_version_id]
    doc_map = {doc.id: doc for doc in eligible_docs}

    # ── Resolve embedding (cached or newly computed) ──────────────────────────
    if embedding_task is not None:
        try:
            query_embedding = (await embedding_task)[0]
            has_embeddings = True
            _embed_cache_set(org_id_str, embedding_input, query_embedding)
        except Exception:
            query_embedding = []
            has_embeddings = False

    # ── Single SQL: ANN vector search returning full chunk columns ────────────
    candidate_limit = max(RERANK_CANDIDATE_LIMIT, max_sources)
    vector_scores: dict[UUID, float] = {}
    vector_by_id: dict[UUID, _VectorChunk] = {}

    if has_embeddings:
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_embedding) + "]"
        chunk_filter_clauses = ["c.document_id = ANY(:doc_ids)"]
        sql_params: dict[str, object] = {"doc_ids": doc_ids, "vec": vec_literal, "top_k": candidate_limit}
        if active_version_ids:
            chunk_filter_clauses.append("c.version_id = ANY(:ver_ids)")
            sql_params["ver_ids"] = active_version_ids
        where_clause = " AND ".join(chunk_filter_clauses)
        sql = text(
            f"""
            SELECT c.id, c.document_id, c.version_id, c.chunk_index,
                   c.chunk_text, c.content, c.page_number, c.section_title,
                   1 - (c.embedding <=> CAST(:vec AS vector)) AS score
            FROM knowledge_document_chunks c
            WHERE {where_clause}
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
            """
        )
        for row in (await session.execute(sql, sql_params)).all():
            chunk_id = row[0]
            score = float(row[8])
            vector_scores[chunk_id] = score
            vector_by_id[chunk_id] = _VectorChunk(
                id=chunk_id,
                document_id=row[1],
                version_id=row[2],
                chunk_index=row[3],
                chunk_text=row[4],
                content=row[5],
                page_number=row[6],
                section_title=row[7],
            )

    # ── Keyword candidates (for hybrid scoring) ───────────────────────────────
    chunk_filters = [KnowledgeDocumentChunk.document_id.in_(doc_ids)]
    if active_version_ids:
        chunk_filters.append(KnowledgeDocumentChunk.version_id.in_(active_version_ids))
    keyword_pool = list(
        (
            await session.execute(
                select(KnowledgeDocumentChunk).where(*chunk_filters).limit(TERM_FALLBACK_CHUNK_LIMIT)
            )
        ).scalars()
    )
    keyword_scores = {chunk.id: score for chunk, score in _rank_chunks_by_terms(retrieval_query, keyword_pool)}

    # Merge: ORM objects for keyword hits, _VectorChunk for vector-only hits
    keyword_by_id: dict[UUID, KnowledgeDocumentChunk] = {
        chunk.id: chunk for chunk in keyword_pool if chunk.id in set(vector_scores) | set(keyword_scores)
    }
    candidate_by_id: dict[UUID, KnowledgeDocumentChunk | _VectorChunk] = {
        **vector_by_id,
        **keyword_by_id,  # ORM objects override where overlap exists
    }

    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]] = [
        (chunk, score)
        for chunk, score in _rerank_hybrid_candidates(
            list(candidate_by_id.values()),
            vector_scores=vector_scores,
            keyword_scores=keyword_scores,
            doc_map=doc_map,
            query_text=retrieval_query,
        )
        if score >= min_relevance_score
    ][:max_sources]

    top_score = matches[0][1] if matches else 0.0

    if not matches:
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="No relevant chunks met the minimum relevance threshold.",
            eligible_docs=eligible_docs,
            retrieval_params=_build_retrieval_params(
                query_text=query_text,
                retrieval_query=retrieval_query,
                answer_mode=answer_mode,
                include_histories=include_histories,
                max_sources=max_sources,
                min_relevance_score=min_relevance_score,
                project=project,
                department=department,
                eligible_doc_count=len(eligible_docs),
                has_embeddings=has_embeddings,
                matches=[],
                doc_map=doc_map,
                vector_scores=vector_scores,
                keyword_scores=keyword_scores,
            ),
        )

    # ── 5. Build context for GPT and call LLMClient ───────────────────────────
    fast_path = top_score >= FAST_PATH_THRESHOLD
    settings = get_settings()
    fast_model = settings.openai_model or settings.llm_model or "gpt-4o-mini"
    strong_model = settings.knowledge_strong_model

    llm = LLMClient()
    context_chunks: list[dict[str, str]] = []
    neighbor_context = await _neighbor_context_for_matches(session, matches)
    for chunk, _score in matches:
        doc = doc_map[chunk.document_id]
        folder = folders_map.get(doc.folder_id)
        raw_chunk_text = neighbor_context.get(chunk.id) or (chunk.chunk_text or chunk.content or "").strip()
        context_chunks.append(
            {
                "title": doc.title,
                "source_type": _source_label(doc.source_type),
                "folder": folder.name if folder else doc.folder_id.hex,
                "page": str(chunk.page_number) if chunk.page_number else "",
                "text": (
                    raw_chunk_text
                    if len(raw_chunk_text) <= RAG_CONTEXT_CHUNK_CHARS
                    else raw_chunk_text[: RAG_CONTEXT_CHUNK_CHARS - 3].rstrip() + "..."
                ),
            }
        )

    structured_context = await _build_structured_operational_context(
        session,
        current_user,
        query_text=query_text,
        explicit_project=project,
        client_safe=client_safe_mode,
    )
    llm_history = [{"role": turn.role, "content": turn.content} for turn in history]
    llm_result = await llm.generate_rag_answer(
        query_text,
        context_chunks,
        model=fast_model,
        conversation_history=llm_history,
        answer_mode="client_safe" if client_safe_mode else "internal",
        structured_context=structured_context,
        fast_path=fast_path,
    )

    # ── Low-confidence retry with stronger model ──────────────────────────────
    if (
        not fast_path
        and fast_model != strong_model
        and float(llm_result.get("confidence") or 0.0) < LOW_CONFIDENCE_THRESHOLD
    ):
        retry_result = await llm.generate_rag_answer(
            query_text,
            context_chunks,
            model=strong_model,
            conversation_history=llm_history,
            answer_mode="client_safe" if client_safe_mode else "internal",
            structured_context=structured_context,
            fast_path=False,
        )
        if float(retry_result.get("confidence") or 0.0) > float(llm_result.get("confidence") or 0.0):
            llm_result = retry_result

    answer_text = str(llm_result.get("answer") or NO_APPROVED_ANSWER)
    next_step = str(llm_result.get("next_step") or "")
    raw_confidence = float(llm_result.get("confidence") or 0.0)
    model_used: str | None = str(llm_result["model"]) if "model" in llm_result else None
    structured_raw = llm_result.get("structured")
    structured_answer = None
    if isinstance(structured_raw, dict):
        structured_answer = KnowledgeStructuredAnswer(
            policy=str(structured_raw.get("policy") or ""),
            steps=str(structured_raw.get("steps") or ""),
            owner=str(structured_raw.get("owner") or ""),
            evidence=str(structured_raw.get("evidence") or ""),
            next_action=str(structured_raw.get("next_action") or next_step),
        )
    grounding = _ground_generation(answer_text, structured_answer, context_chunks, structured_context)

    gap_retrieval_params = _build_retrieval_params(
        query_text=query_text,
        retrieval_query=retrieval_query,
        answer_mode=answer_mode,
        include_histories=include_histories,
        max_sources=max_sources,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
        eligible_doc_count=len(eligible_docs),
        has_embeddings=has_embeddings,
        matches=matches,
        doc_map=doc_map,
        vector_scores=vector_scores,
        keyword_scores=keyword_scores,
    )
    if answer_text.strip() == NO_APPROVED_ANSWER:
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="Retrieved chunks did not contain a confident answer.",
            eligible_docs=eligible_docs,
            matches=matches,
            retrieval_params=gap_retrieval_params,
        )
    if not grounding["grounded"]:
        if grounding["support"] < 0.2:
            return await _persist_empty_ask_response(
                session,
                current_user,
                query_text,
                started=started,
                reason="Generated answer could not be grounded in retrieved evidence.",
                eligible_docs=eligible_docs,
                matches=matches,
                retrieval_params=gap_retrieval_params,
            )
        raw_confidence = min(raw_confidence, grounding["support"])

    retrieval_signal = matches[0][1] if matches else 0.0
    confidence_score = round(0.6 * raw_confidence + 0.4 * min(retrieval_signal, 1.0), 4)
    confidence_reasons = _build_confidence_reasons(matches, eligible_docs, doc_map, query_text)
    if not grounding["grounded"]:
        confidence_reasons.append("Some generated claims had weak support in retrieved evidence")
    if structured_context:
        confidence_reasons.append("Included structured project data in answer context")
    if client_safe_mode:
        confidence_reasons.append("Restricted retrieval and wording to client-safe sources")

    # ── 6. Persist AgentQuery ─────────────────────────────────────────────────
    retrieval_params = _build_retrieval_params(
        query_text=query_text,
        retrieval_query=retrieval_query,
        answer_mode=answer_mode,
        include_histories=include_histories,
        max_sources=max_sources,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
        eligible_doc_count=len(eligible_docs),
        has_embeddings=has_embeddings,
        matches=matches,
        doc_map=doc_map,
        vector_scores=vector_scores,
        keyword_scores=keyword_scores,
        confidence_score=confidence_score,
    )
    agent_query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=None,
        agent_name=KNOWLEDGE_AGENT_NAME,
        query_text=query_text,
        answer_text=answer_text,
        model_used=model_used,
        latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        retrieval_params=retrieval_params,
    )
    session.add(agent_query)
    await session.flush()

    # ── 7. Persist evidence links + build citations (one per chunk) ───────────
    citations: list[KnowledgeCitationRead] = []
    cited_docs: set[UUID] = set()
    for chunk, score in matches:
        doc = doc_map[chunk.document_id]
        folder = folders_map.get(doc.folder_id)
        label = f"{_source_label(doc.source_type)}: {doc.title} {doc.version}"
        session.add(
            KnowledgeEvidenceLink(
                org_id=current_user.org_id,
                agent_query_id=agent_query.id,
                document_id=doc.id,
                chunk_id=chunk.id,
                citation_label=label,
                relevance_score=Decimal(str(round(score, 4))),
            )
        )
        chunk_text = (chunk.chunk_text or chunk.content or "").strip()
        citations.append(
            KnowledgeCitationRead(
                document_id=doc.id,
                chunk_id=chunk.id,
                citation_label=label,
                title=doc.title,
                source_type=doc.source_type.value,
                version=doc.version,
                folder_name=folder.name if folder else "",
                folder_kind=folder.folder_kind.value if folder else "",
                relevance_score=round(score, 4),
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                chunk_preview=chunk_text[:240] + ("..." if len(chunk_text) > 240 else ""),
                section_title=chunk.section_title,
            )
        )
        cited_docs.add(doc.id)

    return KnowledgeAskRead(
        answer_text=answer_text,
        next_step=next_step,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        structured_answer=structured_answer,
        knowledge_gap=None,
        citations=citations,
        query_id=agent_query.id,
        model_used=model_used,
        retrieval_debug=retrieval_params,
    )


async def stream_knowledge_ask(
    session: AsyncSession,
    current_user: CurrentUser,
    query_text: str,
    *,
    conversation_history: list[KnowledgeConversationTurn] | None = None,
    answer_mode: str = "internal",
    include_histories: bool = True,
    max_sources: int = 5,
    min_relevance_score: float = 0.25,
    project: str | None = None,
    department: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted lines for the streaming /knowledge/ask/stream endpoint.

    Event shapes:
      data: {"type": "meta",  "query_id": "...", "citations": [...], "confidence_estimate": 0.7}
      data: {"type": "delta", "text": "<token>"}
      data: {"type": "done",  "answer_text": "...", "confidence_score": 0.82, "next_step": "...",
                              "structured_answer": {...}|null, "model_used": "..."}
      data: {"type": "error", "message": "..."}
    """
    import json as _json

    started = datetime.now(UTC)
    max_sources = max(1, min(max_sources, 10))
    min_relevance_score = max(0.0, min(min_relevance_score, 1.0))
    client_safe_mode = answer_mode == "client_safe"
    history = conversation_history or []

    # ── Retrieval (identical to ask_knowledge_agent up to LLM call) ───────────
    retrieval_query = await _build_standalone_retrieval_query(query_text, history)
    embedding_input = retrieval_query[:EMBEDDING_INPUT_MAX_CHARS]
    org_id_str = str(current_user.org_id)

    cached_vec = _embed_cache_get(org_id_str, embedding_input)
    if cached_vec is not None:
        query_embedding: list[float] = cached_vec
        has_embeddings = True
        embed_task = None
    else:
        embed_task = asyncio.create_task(_embed_texts([embedding_input]))

    doc_filters = (
        KnowledgeDocument.org_id == current_user.org_id,
        KnowledgeDocument.deleted_at.is_(None),
        KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
        KnowledgeDocument.indexing_status == KnowledgeIndexingStatus.INDEXED,
        KnowledgeDocument.processing_status == KnowledgeProcessingStatus.READY,
    )
    docs_result, folders_result = await asyncio.gather(
        session.execute(select(KnowledgeDocument).where(*doc_filters)),
        session.execute(
            select(KnowledgeFolder).where(
                KnowledgeFolder.org_id == current_user.org_id,
                KnowledgeFolder.deleted_at.is_(None),
            )
        ),
    )
    docs = list(docs_result.scalars())
    folders_map: dict[UUID, KnowledgeFolder] = {row.id: row for row in folders_result.scalars()}
    eligible_docs = [doc for doc in docs if can_access_visibility(current_user.role, doc.visibility)]
    if client_safe_mode:
        eligible_docs = [doc for doc in eligible_docs if doc.visibility == KnowledgeVisibility.CLIENT_SAFE]

    if not eligible_docs:
        yield _sse({"type": "error", "message": "No approved documents are available."})
        return

    if not include_histories:
        eligible_docs = [
            doc for doc in eligible_docs
            if folders_map.get(doc.folder_id) and
            folders_map[doc.folder_id].folder_kind != KnowledgeFolderKind.HISTORIES
        ]
    if project:
        pq = project.strip().lower()
        eligible_docs = [d for d in eligible_docs if (d.project or "").lower() == pq]
    if department:
        dq = department.strip().lower()
        eligible_docs = [d for d in eligible_docs if (d.department or "").lower() == dq]
    if not eligible_docs:
        yield _sse({"type": "error", "message": "No documents matched the filters."})
        return

    doc_ids = [doc.id for doc in eligible_docs]
    active_version_ids = [doc.active_version_id for doc in eligible_docs if doc.active_version_id]
    doc_map = {doc.id: doc for doc in eligible_docs}

    if embed_task is not None:
        try:
            query_embedding = (await embed_task)[0]
            has_embeddings = True
            _embed_cache_set(org_id_str, embedding_input, query_embedding)
        except Exception:
            query_embedding = []
            has_embeddings = False

    candidate_limit = max(RERANK_CANDIDATE_LIMIT, max_sources)
    vector_scores: dict[UUID, float] = {}
    vector_by_id: dict[UUID, _VectorChunk] = {}

    if has_embeddings:
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_embedding) + "]"
        clauses = ["c.document_id = ANY(:doc_ids)"]
        sql_params: dict[str, object] = {"doc_ids": doc_ids, "vec": vec_literal, "top_k": candidate_limit}
        if active_version_ids:
            clauses.append("c.version_id = ANY(:ver_ids)")
            sql_params["ver_ids"] = active_version_ids
        sql = text(
            f"""
            SELECT c.id, c.document_id, c.version_id, c.chunk_index,
                   c.chunk_text, c.content, c.page_number, c.section_title,
                   1 - (c.embedding <=> CAST(:vec AS vector)) AS score
            FROM knowledge_document_chunks c
            WHERE {" AND ".join(clauses)} AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
            """
        )
        for row in (await session.execute(sql, sql_params)).all():
            cid = row[0]
            score = float(row[8])
            vector_scores[cid] = score
            vector_by_id[cid] = _VectorChunk(
                id=cid, document_id=row[1], version_id=row[2], chunk_index=row[3],
                chunk_text=row[4], content=row[5], page_number=row[6], section_title=row[7],
            )

    chunk_filters = [KnowledgeDocumentChunk.document_id.in_(doc_ids)]
    if active_version_ids:
        chunk_filters.append(KnowledgeDocumentChunk.version_id.in_(active_version_ids))
    keyword_pool = list(
        (await session.execute(
            select(KnowledgeDocumentChunk).where(*chunk_filters).limit(TERM_FALLBACK_CHUNK_LIMIT)
        )).scalars()
    )
    keyword_scores = {c.id: s for c, s in _rank_chunks_by_terms(retrieval_query, keyword_pool)}
    keyword_by_id: dict[UUID, KnowledgeDocumentChunk] = {
        c.id: c for c in keyword_pool if c.id in set(vector_scores) | set(keyword_scores)
    }
    candidate_by_id: dict[UUID, KnowledgeDocumentChunk | _VectorChunk] = {**vector_by_id, **keyword_by_id}

    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]] = [
        (chunk, score)
        for chunk, score in _rerank_hybrid_candidates(
            list(candidate_by_id.values()),
            vector_scores=vector_scores,
            keyword_scores=keyword_scores,
            doc_map=doc_map,
            query_text=retrieval_query,
        )
        if score >= min_relevance_score
    ][:max_sources]

    top_score = matches[0][1] if matches else 0.0

    if not matches:
        agent_query = AgentQuery(
            user_id=current_user.id, org_id=current_user.org_id, project_id=None,
            agent_name=KNOWLEDGE_AGENT_NAME, query_text=query_text,
            answer_text=NO_APPROVED_ANSWER, model_used=None,
            latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            retrieval_params=None,
        )
        session.add(agent_query)
        await session.flush()
        gap = _build_knowledge_gap(
            query_text,
            reason="No relevant chunks met the minimum relevance threshold.",
        )
        await _record_knowledge_gap(
            session,
            current_user,
            query_text=query_text,
            gap=gap,
            agent_query_id=agent_query.id,
        )
        yield _sse({"type": "meta", "query_id": str(agent_query.id), "citations": [],
                    "confidence_estimate": 0.0})
        yield _sse({"type": "done", "answer_text": NO_APPROVED_ANSWER, "confidence_score": 0.0,
                    "next_step": "", "structured_answer": None, "model_used": None})
        return

    # ── Build citations for meta event ────────────────────────────────────────
    neighbor_context = await _neighbor_context_for_matches(session, matches)
    context_chunks: list[dict[str, str]] = []
    citations_raw: list[dict[str, object]] = []
    for chunk, score in matches:
        doc = doc_map[chunk.document_id]
        folder = folders_map.get(doc.folder_id)
        raw_text = neighbor_context.get(chunk.id) or (chunk.chunk_text or chunk.content or "").strip()
        context_chunks.append({
            "title": doc.title,
            "source_type": _source_label(doc.source_type),
            "folder": folder.name if folder else doc.folder_id.hex,
            "page": str(chunk.page_number) if chunk.page_number else "",
            "text": raw_text if len(raw_text) <= RAG_CONTEXT_CHUNK_CHARS
                    else raw_text[: RAG_CONTEXT_CHUNK_CHARS - 3].rstrip() + "...",
        })
        chunk_text = (chunk.chunk_text or chunk.content or "").strip()
        citations_raw.append({
            "document_id": str(doc.id),
            "chunk_id": str(chunk.id),
            "citation_label": f"{_source_label(doc.source_type)}: {doc.title} {doc.version}",
            "title": doc.title,
            "source_type": doc.source_type.value,
            "version": doc.version,
            "folder_name": folder.name if folder else "",
            "folder_kind": folder.folder_kind.value if folder else "",
            "relevance_score": round(score, 4),
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "chunk_preview": chunk_text[:240] + ("..." if len(chunk_text) > 240 else ""),
            "section_title": chunk.section_title,
        })

    # Yield meta immediately — client can render citations while LLM streams
    confidence_estimate = round(0.4 * min(top_score, 1.0), 4)
    yield _sse({"type": "meta", "citations": citations_raw,
                "confidence_estimate": confidence_estimate})

    # ── Stream LLM answer ─────────────────────────────────────────────────────
    fast_path = top_score >= FAST_PATH_THRESHOLD
    settings_obj = get_settings()
    fast_model = settings_obj.openai_model or settings_obj.llm_model or "gpt-4o-mini"
    strong_model = settings_obj.knowledge_strong_model
    structured_context = await _build_structured_operational_context(
        session, current_user, query_text=query_text, explicit_project=project, client_safe=client_safe_mode,
    )
    llm_history = [{"role": turn.role, "content": turn.content} for turn in history]

    llm = LLMClient()
    accumulated_answer = ""
    llm_done_event: dict[str, object] = {}

    async for event in llm.stream_rag_answer(
        query_text, context_chunks,
        model=fast_model,
        conversation_history=llm_history,
        answer_mode="client_safe" if client_safe_mode else "internal",
        structured_context=structured_context,
        fast_path=fast_path,
    ):
        if event["type"] == "delta":
            accumulated_answer += str(event.get("text", ""))
            yield _sse(event)
        elif event["type"] == "done":
            llm_done_event = event
            break

    raw_confidence = float(llm_done_event.get("confidence") or 0.0)
    model_used = str(llm_done_event.get("model") or fast_model)

    # Low-confidence retry with strong model (non-streaming for simplicity)
    if not fast_path and fast_model != strong_model and raw_confidence < LOW_CONFIDENCE_THRESHOLD:
        retry = await llm.generate_rag_answer(
            query_text, context_chunks,
            model=strong_model,
            conversation_history=llm_history,
            answer_mode="client_safe" if client_safe_mode else "internal",
            structured_context=structured_context,
            fast_path=False,
        )
        if float(retry.get("confidence") or 0.0) > raw_confidence:
            new_answer = str(retry.get("answer") or "")
            if new_answer and new_answer != accumulated_answer:
                # Emit a replace event so client can swap the streamed text
                yield _sse({"type": "replace", "text": new_answer})
                accumulated_answer = new_answer
            llm_done_event = {
                "type": "done",
                "answer_text": new_answer,
                "next_step": str(retry.get("next_step") or ""),
                "confidence": float(retry.get("confidence") or 0.0),
                "structured": retry.get("structured"),
                "model": strong_model,
            }
            raw_confidence = float(llm_done_event["confidence"])
            model_used = strong_model

    answer_text = accumulated_answer or str(llm_done_event.get("answer_text") or NO_APPROVED_ANSWER)
    next_step = str(llm_done_event.get("next_step") or "")
    structured_raw = llm_done_event.get("structured")
    structured_answer: KnowledgeStructuredAnswer | None = None
    if isinstance(structured_raw, dict) and not fast_path:
        structured_answer = KnowledgeStructuredAnswer(
            policy=str(structured_raw.get("policy") or ""),
            steps=str(structured_raw.get("steps") or ""),
            owner=str(structured_raw.get("owner") or ""),
            evidence=str(structured_raw.get("evidence") or ""),
            next_action=str(structured_raw.get("next_action") or next_step),
        )

    grounding = _ground_generation(answer_text, structured_answer, context_chunks, structured_context)
    if (
        not grounding["grounded"]
        and grounding["support"] < 0.2
        and answer_text.strip() != NO_APPROVED_ANSWER
        and not (matches and matches[0][1] >= 0.45 and len(answer_text.strip()) > 80)
    ):
        answer_text = NO_APPROVED_ANSWER
        raw_confidence = 0.0

    retrieval_signal = matches[0][1] if matches else 0.0
    confidence_score = round(0.6 * raw_confidence + 0.4 * min(retrieval_signal, 1.0), 4)

    if not answer_text.strip():
        answer_text = NO_APPROVED_ANSWER

    # ── Persist (best-effort — still return answer if save fails) ─────────────
    query_id: str | None = None
    try:
        retrieval_params = _build_retrieval_params(
            query_text=query_text, retrieval_query=retrieval_query, answer_mode=answer_mode,
            include_histories=include_histories, max_sources=max_sources, min_relevance_score=min_relevance_score,
            project=project, department=department, eligible_doc_count=len(eligible_docs),
            has_embeddings=has_embeddings, matches=matches, doc_map=doc_map,
            vector_scores=vector_scores, keyword_scores=keyword_scores, confidence_score=confidence_score,
        )
        agent_query = AgentQuery(
            user_id=current_user.id, org_id=current_user.org_id, project_id=None,
            agent_name=KNOWLEDGE_AGENT_NAME, query_text=query_text, answer_text=answer_text,
            model_used=model_used,
            latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            retrieval_params=retrieval_params,
        )
        session.add(agent_query)
        await session.flush()
        query_id = str(agent_query.id)

        for chunk, score in matches:
            doc = doc_map[chunk.document_id]
            label = f"{_source_label(doc.source_type)}: {doc.title} {doc.version}"
            session.add(KnowledgeEvidenceLink(
                org_id=current_user.org_id, agent_query_id=agent_query.id,
                document_id=doc.id, chunk_id=chunk.id,
                citation_label=label, relevance_score=Decimal(str(round(score, 4))),
            ))
    except Exception:
        logger.exception("Failed to persist streamed knowledge ask")
        await session.rollback()

    confidence_reasons = _build_confidence_reasons(matches, eligible_docs, doc_map, query_text)
    if not grounding["grounded"]:
        confidence_reasons.append("Some generated claims had weak support in retrieved evidence")
    if structured_context:
        confidence_reasons.append("Included structured project data in answer context")
    if client_safe_mode:
        confidence_reasons.append("Restricted retrieval and wording to client-safe sources")
    if fast_path:
        confidence_reasons.append("Fast path: high-relevance chunks used short prompt")

    yield _sse({
        "type": "done",
        "query_id": query_id,
        "answer_text": answer_text,
        "confidence_score": confidence_score,
        "confidence_reasons": confidence_reasons,
        "next_step": next_step,
        "structured_answer": (
            {
                "policy": structured_answer.policy,
                "steps": structured_answer.steps,
                "owner": structured_answer.owner,
                "evidence": structured_answer.evidence,
                "next_action": structured_answer.next_action,
            }
            if structured_answer else None
        ),
        "model_used": model_used,
        "retrieval_debug": retrieval_params,
    })


async def list_document_versions(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
) -> list[KnowledgeDocumentVersionRead]:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot access this document.")
    versions = list(
        (
            await session.execute(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id == doc.id)
                .order_by(KnowledgeDocumentVersion.uploaded_at.desc())
            )
        ).scalars()
    )
    result: list[KnowledgeDocumentVersionRead] = []
    for version in versions:
        chunk_count = int(
            (
                await session.execute(
                    select(func.count(KnowledgeDocumentChunk.id)).where(KnowledgeDocumentChunk.version_id == version.id)
                )
            ).scalar_one()
            or 0
        )
        result.append(
            KnowledgeDocumentVersionRead(
                id=version.id,
                version=version.version,
                is_active=version.is_active,
                uploaded_at=version.uploaded_at,
                uploaded_by_name=await _user_display_name(session, version.uploaded_by),
                approved_by_name=await _user_display_name(session, doc.approved_by) if doc.approved_by else None,
                approved_at=doc.approved_at if version.is_active else None,
                checksum_sha256=version.checksum_sha256,
                chunk_count=chunk_count,
            )
        )
    return result


async def compare_document_versions(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    left_version_id: UUID,
    right_version_id: UUID,
) -> KnowledgeVersionCompareRead:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot access this document.")
    left = (
        await session.execute(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.id == left_version_id,
                KnowledgeDocumentVersion.document_id == doc.id,
            )
        )
    ).scalar_one_or_none()
    right = (
        await session.execute(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.id == right_version_id,
                KnowledgeDocumentVersion.document_id == doc.id,
            )
        )
    ).scalar_one_or_none()
    if left is None or right is None:
        raise ApiError(404, "NOT_FOUND", "One or both versions were not found.")

    left_text = await _version_extracted_text(session, left.id)
    right_text = await _version_extracted_text(session, right.id)
    left_lines = left_text.splitlines()
    right_lines = right_text.splitlines()
    diff = list(difflib.unified_diff(left_lines, right_lines, lineterm=""))
    added = [line[1:].strip() for line in diff if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:].strip() for line in diff if line.startswith("-") and not line.startswith("---")]
    added_sections = [line for line in added if line][:8]
    removed_sections = [line for line in removed if line][:8]
    if not added_sections and not removed_sections:
        summary = "No substantive text differences detected between versions."
    else:
        summary = f"{len(added_sections)} section(s) added or changed, {len(removed_sections)} section(s) removed or replaced."

    return KnowledgeVersionCompareRead(
        left_version=left.version,
        right_version=right.version,
        left_approved_by=await _user_display_name(session, doc.approved_by) if left.is_active and doc.approved_by else None,
        right_approved_by=await _user_display_name(session, doc.approved_by) if right.is_active and doc.approved_by else None,
        summary=summary,
        added_sections=added_sections,
        removed_sections=removed_sections,
    )


async def get_retrieval_settings(session: AsyncSession, org_id: UUID) -> KnowledgeRetrievalSettingsRead:
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT only_approved, include_histories, min_confidence, max_sources, project, department
                    FROM knowledge_retrieval_settings
                    WHERE org_id = :org_id
                    """
                ),
                {"org_id": org_id},
            )
        ).mappings().first()
    except Exception:
        return KnowledgeRetrievalSettingsRead()
    if row is None:
        return KnowledgeRetrievalSettingsRead()
    return KnowledgeRetrievalSettingsRead(
        only_approved=bool(row["only_approved"]),
        include_histories=bool(row["include_histories"]),
        min_confidence=float(row["min_confidence"]),
        max_sources=int(row["max_sources"]),
        project=row["project"],
        department=row["department"],
    )


async def update_retrieval_settings(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: KnowledgeRetrievalSettingsUpdate,
) -> KnowledgeRetrievalSettingsRead:
    if current_user.role not in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "Only leadership can update retrieval settings.")
    current = await get_retrieval_settings(session, current_user.org_id)
    merged_data = current.model_dump()
    merged_data.update(payload.model_dump(exclude_unset=True))
    merged = KnowledgeRetrievalSettingsRead(**merged_data)
    try:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_retrieval_settings
                  (org_id, only_approved, include_histories, min_confidence, max_sources, project, department, updated_at)
                VALUES
                  (:org_id, :only_approved, :include_histories, :min_confidence, :max_sources, :project, :department, now())
                ON CONFLICT (org_id) DO UPDATE SET
                  only_approved = EXCLUDED.only_approved,
                  include_histories = EXCLUDED.include_histories,
                  min_confidence = EXCLUDED.min_confidence,
                  max_sources = EXCLUDED.max_sources,
                  project = EXCLUDED.project,
                  department = EXCLUDED.department,
                  updated_at = now()
                """
            ),
            {
                "org_id": current_user.org_id,
                "only_approved": merged.only_approved,
                "include_histories": merged.include_histories,
                "min_confidence": merged.min_confidence,
                "max_sources": merged.max_sources,
                "project": merged.project,
                "department": merged.department,
            },
        )
    except Exception as exc:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Retrieval settings storage is not available. Apply the latest database migration.") from exc
    return merged


async def record_knowledge_feedback(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    query_id: UUID,
    rating: str,
    comment: str | None = None,
) -> KnowledgeFeedbackRead:
    agent_query = (
        await session.execute(
            select(AgentQuery).where(
                AgentQuery.id == query_id,
                AgentQuery.org_id == current_user.org_id,
                AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
            )
        )
    ).scalar_one_or_none()
    if agent_query is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge query not found.")

    normalized_comment = comment.strip() if comment and comment.strip() else None
    feedback_rating = KnowledgeFeedbackRating(rating)

    existing = (
        await session.execute(
            select(KnowledgeQueryFeedback).where(
                KnowledgeQueryFeedback.agent_query_id == query_id,
                KnowledgeQueryFeedback.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.rating = feedback_rating
        existing.comment = normalized_comment
        feedback = existing
    else:
        feedback = KnowledgeQueryFeedback(
            org_id=current_user.org_id,
            agent_query_id=query_id,
            user_id=current_user.id,
            rating=feedback_rating,
            comment=normalized_comment,
        )
        session.add(feedback)
    await session.flush()

    if feedback_rating == KnowledgeFeedbackRating.DOWN:
        logger.info(
            "knowledge_query_downvote query_id=%s user_id=%s retrieval_params=%s comment=%r",
            query_id,
            current_user.id,
            agent_query.retrieval_params,
            normalized_comment,
        )

    return KnowledgeFeedbackRead(
        id=feedback.id or uuid4(),
        query_id=query_id,
        rating=feedback.rating.value,
        comment=feedback.comment,
        created_at=feedback.created_at or datetime.now(UTC),
    )


async def get_knowledge_query_answer(
    session: AsyncSession,
    current_user: CurrentUser,
    query_id: UUID,
) -> KnowledgeAskRead:
    agent_query = (
        await session.execute(
            select(AgentQuery).where(
                AgentQuery.id == query_id,
                AgentQuery.org_id == current_user.org_id,
                AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
            )
        )
    ).scalar_one_or_none()
    if agent_query is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge query not found.")

    links = list(
        (
            await session.execute(
                select(KnowledgeEvidenceLink).where(KnowledgeEvidenceLink.agent_query_id == query_id)
            )
        ).scalars()
    )
    doc_ids = {link.document_id for link in links}
    chunk_ids = {link.chunk_id for link in links if link.chunk_id}
    docs = {
        doc.id: doc
        for doc in (
            await session.execute(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(doc_ids)))
        ).scalars()
    }
    chunks = {
        chunk.id: chunk
        for chunk in (
            await session.execute(select(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.id.in_(chunk_ids)))
        ).scalars()
    }
    folder_ids = {doc.folder_id for doc in docs.values()}
    folders = {
        folder.id: folder
        for folder in (
            await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id.in_(folder_ids)))
        ).scalars()
    }

    citations: list[KnowledgeCitationRead] = []
    for link in links:
        doc = docs.get(link.document_id)
        if doc is None or not can_access_visibility(current_user.role, doc.visibility):
            continue
        folder = folders.get(doc.folder_id)
        chunk = chunks.get(link.chunk_id) if link.chunk_id else None
        chunk_text = (chunk.chunk_text or chunk.content or "").strip() if chunk else ""
        citations.append(
            KnowledgeCitationRead(
                document_id=doc.id,
                chunk_id=link.chunk_id,
                citation_label=link.citation_label,
                title=doc.title,
                source_type=doc.source_type.value,
                version=doc.version,
                folder_name=folder.name if folder else "",
                folder_kind=folder.folder_kind.value if folder else "",
                relevance_score=float(link.relevance_score or 0),
                page_number=chunk.page_number if chunk else None,
                chunk_index=chunk.chunk_index if chunk else None,
                chunk_preview=chunk_text[:240] + ("..." if len(chunk_text) > 240 else ""),
                section_title=chunk.section_title if chunk else None,
            )
        )

    retrieval_debug = agent_query.retrieval_params if isinstance(agent_query.retrieval_params, dict) else None
    confidence_score = 0.0
    if retrieval_debug and isinstance(retrieval_debug.get("confidence_score"), int | float):
        confidence_score = float(retrieval_debug["confidence_score"])
    elif citations:
        confidence_score = max((citation.relevance_score for citation in citations), default=0.0)

    reasons = ["Reopened saved answer with persisted evidence links"]
    if retrieval_debug:
        reasons.append("Retrieval debug metadata is available")

    return KnowledgeAskRead(
        answer_text=agent_query.answer_text,
        next_step="",
        confidence_score=round(confidence_score, 4),
        confidence_reasons=reasons,
        structured_answer=None,
        knowledge_gap=None,
        citations=citations,
        query_id=agent_query.id,
        model_used=agent_query.model_used,
        retrieval_debug=retrieval_debug,
    )


async def list_knowledge_eval_questions(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[KnowledgeEvalQuestionRead]:
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, question_text, expected_document_ids, expected_answer_notes,
                           is_active, created_at, updated_at
                    FROM knowledge_eval_questions
                    WHERE org_id = :org_id
                    ORDER BY is_active DESC, created_at DESC
                    """
                ),
                {"org_id": current_user.org_id},
            )
        ).mappings()
    except ProgrammingError as exc:
        if not _is_missing_schema_error(exc):
            raise
        logger.warning("knowledge_eval_questions table missing; returning empty list")
        await session.rollback()
        return []
    return [
        KnowledgeEvalQuestionRead(
            id=row["id"],
            question_text=row["question_text"],
            expected_document_ids=list(row["expected_document_ids"] or []),
            expected_answer_notes=row["expected_answer_notes"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


async def create_knowledge_eval_question(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: KnowledgeEvalQuestionCreate,
) -> KnowledgeEvalQuestionRead:
    _ensure_eval_manager(current_user)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO knowledge_eval_questions
                  (org_id, question_text, expected_document_ids, expected_answer_notes, created_by)
                VALUES
                  (:org_id, :question_text, CAST(:expected_document_ids AS uuid[]),
                   :expected_answer_notes, :created_by)
                RETURNING id, question_text, expected_document_ids, expected_answer_notes,
                          is_active, created_at, updated_at
                """
            ),
            {
                "org_id": current_user.org_id,
                "question_text": payload.question_text.strip(),
                "expected_document_ids": [str(item) for item in payload.expected_document_ids],
                "expected_answer_notes": payload.expected_answer_notes,
                "created_by": current_user.id,
            },
        )
    ).mappings().one()
    return KnowledgeEvalQuestionRead(
        id=row["id"],
        question_text=row["question_text"],
        expected_document_ids=list(row["expected_document_ids"] or []),
        expected_answer_notes=row["expected_answer_notes"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def update_knowledge_eval_question(
    session: AsyncSession,
    current_user: CurrentUser,
    question_id: UUID,
    payload: KnowledgeEvalQuestionUpdate,
) -> KnowledgeEvalQuestionRead:
    _ensure_eval_manager(current_user)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        existing = [item for item in await list_knowledge_eval_questions(session, current_user) if item.id == question_id]
        if not existing:
            raise ApiError(404, "NOT_FOUND", "Eval question not found.")
        return existing[0]

    set_clauses = ["updated_at = now()"]
    params: dict[str, object] = {"org_id": current_user.org_id, "question_id": question_id}
    if "question_text" in data and data["question_text"] is not None:
        set_clauses.append("question_text = :question_text")
        params["question_text"] = str(data["question_text"]).strip()
    if "expected_document_ids" in data and data["expected_document_ids"] is not None:
        set_clauses.append("expected_document_ids = CAST(:expected_document_ids AS uuid[])")
        params["expected_document_ids"] = [str(item) for item in data["expected_document_ids"]]
    if "expected_answer_notes" in data:
        set_clauses.append("expected_answer_notes = :expected_answer_notes")
        params["expected_answer_notes"] = data["expected_answer_notes"]
    if "is_active" in data and data["is_active"] is not None:
        set_clauses.append("is_active = :is_active")
        params["is_active"] = bool(data["is_active"])

    row = (
        await session.execute(
            text(
                f"""
                UPDATE knowledge_eval_questions
                SET {", ".join(set_clauses)}
                WHERE id = :question_id AND org_id = :org_id
                RETURNING id, question_text, expected_document_ids, expected_answer_notes,
                          is_active, created_at, updated_at
                """
            ),
            params,
        )
    ).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Eval question not found.")
    return KnowledgeEvalQuestionRead(
        id=row["id"],
        question_text=row["question_text"],
        expected_document_ids=list(row["expected_document_ids"] or []),
        expected_answer_notes=row["expected_answer_notes"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_knowledge_eval_metrics(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
) -> KnowledgeEvalMetricsRead:
    days = max(1, min(days, 365))
    try:
        query_metrics = (
            await session.execute(
                text(
                    """
                    WITH recent AS (
                      SELECT *
                      FROM agent_queries
                      WHERE org_id = :org_id
                        AND agent_name = :agent_name
                        AND created_at >= now() - make_interval(days => :days)
                    )
                    SELECT
                      COUNT(DISTINCT recent.id)::int AS total_queries,
                      COALESCE(AVG(CASE WHEN recent.answer_text = :empty_answer THEN 1.0 ELSE 0.0 END), 0) AS empty_rate,
                      percentile_cont(0.95) WITHIN GROUP (ORDER BY recent.latency_ms)
                        FILTER (WHERE recent.latency_ms IS NOT NULL) AS latency_p95_ms,
                      COALESCE(
                        COUNT(DISTINCT CASE WHEN feedback.rating::text = 'down' THEN recent.id END)::float
                        / NULLIF(COUNT(DISTINCT recent.id), 0),
                        0
                      ) AS downvote_rate
                    FROM recent
                    LEFT JOIN knowledge_query_feedback feedback ON feedback.agent_query_id = recent.id
                    """
                ),
                {
                    "org_id": current_user.org_id,
                    "agent_name": KNOWLEDGE_AGENT_NAME,
                    "days": days,
                    "empty_answer": NO_APPROVED_ANSWER,
                },
            )
        ).mappings().one()
    except ProgrammingError as exc:
        if not _is_missing_schema_error(exc):
            raise
        logger.warning("knowledge eval metrics query unavailable; returning zeros")
        await session.rollback()
        query_metrics = {
            "total_queries": 0,
            "empty_rate": 0,
            "latency_p95_ms": None,
            "downvote_rate": 0,
        }
    try:
        eval_metrics = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT COUNT(*)::int FROM knowledge_eval_questions
                       WHERE org_id = :org_id AND is_active IS TRUE) AS question_count,
                      COUNT(runs.id)::int AS run_count,
                      COALESCE(AVG(CASE WHEN runs.citation_hit THEN 1.0 ELSE 0.0 END), 0) AS citation_hit_rate
                    FROM knowledge_eval_runs runs
                    WHERE runs.org_id = :org_id
                      AND runs.created_at >= now() - make_interval(days => :days)
                    """
                ),
                {"org_id": current_user.org_id, "days": days},
            )
        ).mappings().one()
    except ProgrammingError as exc:
        if not _is_missing_schema_error(exc):
            raise
        logger.warning("knowledge_eval_runs table missing; returning zeros")
        await session.rollback()
        eval_metrics = {"question_count": 0, "run_count": 0, "citation_hit_rate": 0}
    latency = query_metrics["latency_p95_ms"]
    return KnowledgeEvalMetricsRead(
        days=days,
        total_queries=int(query_metrics["total_queries"] or 0),
        empty_answer_rate=round(float(query_metrics["empty_rate"] or 0), 4),
        latency_p95_ms=int(latency) if latency is not None else None,
        downvote_rate=round(float(query_metrics["downvote_rate"] or 0), 4),
        eval_question_count=int(eval_metrics["question_count"] or 0),
        eval_run_count=int(eval_metrics["run_count"] or 0),
        citation_hit_rate=round(float(eval_metrics["citation_hit_rate"] or 0), 4),
    )


async def run_knowledge_eval(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    limit: int = 50,
) -> KnowledgeEvalRunRead:
    _ensure_eval_manager(current_user)
    limit = max(1, min(limit, 50))
    questions = list(
        (
            await session.execute(
                text(
                    """
                    SELECT id, question_text, expected_document_ids
                    FROM knowledge_eval_questions
                    WHERE org_id = :org_id AND is_active IS TRUE
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                ),
                {"org_id": current_user.org_id, "limit": limit},
            )
        ).mappings()
    )
    results: list[KnowledgeEvalRunItemRead] = []
    for question in questions:
        expected_ids = [UUID(str(item)) for item in (question["expected_document_ids"] or [])]
        answer = await ask_knowledge_agent(
            session,
            current_user,
            str(question["question_text"]),
            max_sources=10,
        )
        observed_ids = sorted({citation.document_id for citation in answer.citations}, key=str)
        expected_set = set(expected_ids)
        citation_hit = bool(expected_set and expected_set.intersection(observed_ids))
        empty_answer = answer.answer_text.strip() == NO_APPROVED_ANSWER
        latency_ms: int | None = None
        if answer.query_id is not None:
            latency_ms = (
                await session.execute(
                    select(AgentQuery.latency_ms).where(AgentQuery.id == answer.query_id)
                )
            ).scalar_one_or_none()
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_eval_runs
                      (org_id, eval_question_id, agent_query_id, expected_document_ids,
                       observed_document_ids, citation_hit, empty_answer, latency_ms)
                    VALUES
                      (:org_id, :eval_question_id, :agent_query_id,
                       CAST(:expected_document_ids AS uuid[]), CAST(:observed_document_ids AS uuid[]),
                       :citation_hit, :empty_answer, :latency_ms)
                    RETURNING id, eval_question_id, agent_query_id, citation_hit, empty_answer,
                              latency_ms, observed_document_ids, created_at
                    """
                ),
                {
                    "org_id": current_user.org_id,
                    "eval_question_id": question["id"],
                    "agent_query_id": answer.query_id,
                    "expected_document_ids": [str(item) for item in expected_ids],
                    "observed_document_ids": [str(item) for item in observed_ids],
                    "citation_hit": citation_hit,
                    "empty_answer": empty_answer,
                    "latency_ms": latency_ms,
                },
            )
        ).mappings().one()
        results.append(
            KnowledgeEvalRunItemRead(
                id=row["id"],
                eval_question_id=row["eval_question_id"],
                query_id=row["agent_query_id"],
                citation_hit=bool(row["citation_hit"]),
                empty_answer=bool(row["empty_answer"]),
                latency_ms=row["latency_ms"],
                observed_document_ids=list(row["observed_document_ids"] or []),
                created_at=row["created_at"],
            )
        )

    citation_hit_rate = _mean_bool([item.citation_hit for item in results])
    empty_answer_rate = _mean_bool([item.empty_answer for item in results])
    latencies = sorted(item.latency_ms for item in results if item.latency_ms is not None)
    return KnowledgeEvalRunRead(
        run_count=len(results),
        citation_hit_rate=round(citation_hit_rate, 4),
        empty_answer_rate=round(empty_answer_rate, 4),
        latency_p95_ms=_percentile_int(latencies, 0.95),
        results=results,
    )


async def _get_document_or_404(session: AsyncSession, org_id: UUID, document_id: UUID) -> KnowledgeDocument:
    doc = (
        await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.org_id == org_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge document not found.")
    return doc


@dataclass(frozen=True)
class _DocumentListPreload:
    chunk_count: int
    citation_count: int
    preview: list[str]
    approved_by_name: str | None


def _build_document_read(
    doc: KnowledgeDocument,
    folder: KnowledgeFolder,
    *,
    chunk_count: int,
    citation_count: int,
    preview: list[str],
    chunks: list[KnowledgeChunkRead],
    approved_by_name: str | None,
) -> KnowledgeDocumentRead:
    return KnowledgeDocumentRead(
        id=doc.id,
        folder_id=doc.folder_id,
        folder_name=folder.name,
        folder_kind=folder.folder_kind.value,
        title=doc.title,
        source_type=doc.source_type.value,
        version=doc.version,
        visibility=doc.visibility.value,
        status=doc.status.value,
        owner_approver=doc.owner_approver,
        effective_date=doc.effective_date,
        file_name=doc.file_name,
        file_mime_type=doc.file_mime_type,
        file_url=doc.file_url,
        processing_status=doc.processing_status.value,
        processing_error=doc.processing_error,
        indexing_status=doc.indexing_status.value,
        preview=preview,
        workflow_state=_compute_workflow_state(doc),
        quality_score=_compute_quality_score(doc, chunk_count, citation_count),
        chunk_count=chunk_count,
        citation_count=citation_count,
        approved_by_name=approved_by_name,
        approved_at=doc.approved_at,
        chunks=chunks,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _to_document_list_read(
    doc: KnowledgeDocument,
    folder: KnowledgeFolder,
    preload: _DocumentListPreload,
) -> KnowledgeDocumentRead:
    return _build_document_read(
        doc,
        folder,
        chunk_count=preload.chunk_count,
        citation_count=preload.citation_count,
        preview=preload.preview,
        chunks=[],
        approved_by_name=preload.approved_by_name,
    )


async def _batch_document_list_stats(
    session: AsyncSession,
    docs: list[KnowledgeDocument],
) -> dict[UUID, _DocumentListPreload]:
    if not docs:
        return {}

    doc_ids = [doc.id for doc in docs]
    doc_by_id = {doc.id: doc for doc in docs}

    stats_sql = text(
        """
        SELECT
            d.id AS document_id,
            COALESCE(citations.citation_count, 0)::int AS citation_count,
            COALESCE(chunks.chunk_count, 0)::int AS chunk_count
        FROM unnest(CAST(:doc_ids AS uuid[])) AS d(id)
        LEFT JOIN (
            SELECT document_id, COUNT(*)::int AS citation_count
            FROM knowledge_evidence_links
            WHERE document_id = ANY(CAST(:doc_ids AS uuid[]))
            GROUP BY document_id
        ) citations ON citations.document_id = d.id
        LEFT JOIN (
            SELECT c.document_id, COUNT(*)::int AS chunk_count
            FROM knowledge_document_chunks c
            JOIN knowledge_documents doc ON doc.id = c.document_id
            WHERE c.document_id = ANY(CAST(:doc_ids AS uuid[]))
              AND (doc.active_version_id IS NULL OR c.version_id = doc.active_version_id)
            GROUP BY c.document_id
        ) chunks ON chunks.document_id = d.id
        """
    )
    stats_rows = (await session.execute(stats_sql, {"doc_ids": doc_ids})).all()
    citation_counts = {row[0]: int(row[1]) for row in stats_rows}
    chunk_counts = {row[0]: int(row[2]) for row in stats_rows}

    approver_ids = {doc.approved_by for doc in docs if doc.approved_by}
    user_names = await _batch_user_display_names(session, approver_ids) if approver_ids else {}

    return {
        doc_id: _DocumentListPreload(
            chunk_count=chunk_counts.get(doc_id, 0),
            citation_count=citation_counts.get(doc_id, 0),
            preview=[],
            approved_by_name=(
                user_names.get(doc_by_id[doc_id].approved_by) if doc_by_id[doc_id].approved_by else None
            ),
        )
        for doc_id in doc_by_id
    }


async def _to_document_read(session: AsyncSession, doc: KnowledgeDocument, folder: KnowledgeFolder) -> KnowledgeDocumentRead:
    chunk_filters = [KnowledgeDocumentChunk.document_id == doc.id]
    if doc.active_version_id:
        chunk_filters.append(KnowledgeDocumentChunk.version_id == doc.active_version_id)
    all_chunks = list(
        (
            await session.execute(
                select(KnowledgeDocumentChunk)
                .where(*chunk_filters)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            )
        ).scalars()
    )
    preview = [chunk.chunk_text or chunk.content for chunk in all_chunks[:6]] or [
        f"{doc.title} is stored but has no indexed preview content yet.",
    ]
    citation_count = int(
        (
            await session.execute(
                select(func.count(KnowledgeEvidenceLink.id)).where(KnowledgeEvidenceLink.document_id == doc.id)
            )
        ).scalar_one()
        or 0
    )
    approved_by_name = await _user_display_name(session, doc.approved_by) if doc.approved_by else None
    chunk_reads = [
        KnowledgeChunkRead(
            id=chunk.id,
            chunk_index=chunk.chunk_index,
            section_title=chunk.section_title,
            page_number=chunk.page_number,
            chunk_text=(chunk.chunk_text or chunk.content or "").strip(),
            token_count=chunk.token_count,
        )
        for chunk in all_chunks
    ]
    return _build_document_read(
        doc,
        folder,
        chunk_count=len(all_chunks),
        citation_count=citation_count,
        preview=preview,
        chunks=chunk_reads,
        approved_by_name=approved_by_name,
    )


async def _process_document_version(
    session: AsyncSession,
    doc: KnowledgeDocument,
    version: KnowledgeDocumentVersion,
    file_bytes: bytes,
) -> None:
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
        cleaned_text = _clean_text(str(extracted["text"]))
        if not cleaned_text:
            raise ValueError("No extractable text found after cleaning.")
        cleaned_sections = _clean_sections(extracted["sections"])
        if not cleaned_sections:
            cleaned_sections = [{"text": cleaned_text, "page_number": None, "section_title": None}]
        extraction.extracted_text = cleaned_text
        extraction.extraction_status = KnowledgeExtractionStatus.SUCCEEDED
        extraction.extraction_error = None
        extraction.extracted_at = datetime.now(UTC)
        doc.extracted_text = cleaned_text
        doc.processing_status = KnowledgeProcessingStatus.EXTRACTED
        await session.flush()

        processing_phase = "chunking"
        doc.processing_status = KnowledgeProcessingStatus.CHUNKING
        chunks = _chunk_sections(cleaned_sections)
        chunk_rows: list[KnowledgeDocumentChunk] = []
        for index, chunk_data in enumerate(chunks):
            chunk = KnowledgeDocumentChunk(
                org_id=doc.org_id,
                document_id=doc.id,
                folder_id=doc.folder_id,
                version_id=version.id,
                chunk_index=index,
                heading=chunk_data["section_title"],
                section_title=chunk_data["section_title"],
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
        await session.flush()

        processing_phase = "embedding"
        doc.processing_status = KnowledgeProcessingStatus.EMBEDDING
        doc.indexing_status = KnowledgeIndexingStatus.INDEXING
        await session.flush()

        embeddings = await _embed_texts([chunk.chunk_text for chunk in chunk_rows])
        for chunk, embedding in zip(chunk_rows, embeddings, strict=True):
            chunk.embedding = embedding
        doc.processing_status = KnowledgeProcessingStatus.CHUNKED
        await session.flush()

        doc.processing_status = KnowledgeProcessingStatus.READY
        doc.indexing_status = KnowledgeIndexingStatus.INDEXED
        doc.indexed_at = datetime.now(UTC)
        doc.processing_error = None
        await session.flush()
    except Exception as exc:
        if processing_phase == "extraction":
            extraction.extraction_status = KnowledgeExtractionStatus.FAILED
            extraction.extraction_error = str(exc)
            extraction.extracted_at = datetime.now(UTC)
        doc.processing_status = KnowledgeProcessingStatus.FAILED
        doc.indexing_status = KnowledgeIndexingStatus.FAILED
        doc.processing_error = str(exc)
        await session.flush()


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


def _extract_text(file_name: str, file_bytes: bytes) -> dict[str, object]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
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
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        for index, page in enumerate(pdf, start=1):
            text = page.get_text("text", sort=True).strip()
            if text:
                sections.extend(_sections_from_text(text, page_number=index))
    full_text = "\n\n".join(str(item["text"]) for item in sections).strip()
    if not full_text:
        raise ValueError("No extractable text found in PDF.")
    return {"text": full_text, "sections": sections}


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


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _clean_text(value)
    return cleaned or None


def _clean_text(text: str) -> str:
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
        text = _clean_text(str(section.get("text") or ""))
        if not text:
            continue
        title = _clean_optional(str(section.get("section_title"))) if section.get("section_title") else None
        page_number = section.get("page_number")
        cleaned.append({"text": text, "page_number": page_number, "section_title": title})
    return cleaned


def _sections_from_text(text: str, page_number: int | None = None) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current_title: str | None = None
    buffer: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        detected = _detect_section_title(line)
        if detected:
            if buffer and _buffer_has_body(buffer, current_title):
                sections.append({"text": "\n".join(buffer).strip(), "page_number": page_number, "section_title": current_title})
                buffer = []
            current_title = detected
            buffer.append(line)
        else:
            buffer.append(line)
    if buffer:
        sections.append({"text": "\n".join(buffer).strip(), "page_number": page_number, "section_title": current_title})
    if not sections and text.strip():
        sections.append({"text": text.strip(), "page_number": page_number, "section_title": current_title})
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
    chunks: list[dict[str, object]] = []
    for section in sections:
        text = str(section.get("text") or "").strip()
        words = re.findall(r"\S+", text)
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + CHUNK_TARGET_TOKENS, len(words))
            chunk_words = words[start:end]
            chunk_text = _rebuild_chunk_text(text, chunk_words).strip()
            if chunk_text:
                chunks.append(
                    {
                        "chunk_text": chunk_text,
                        "token_count": len(chunk_words),
                        "page_number": section.get("page_number"),
                        "section_title": section.get("section_title"),
                    }
                )
            if end == len(words):
                break
            start = max(end - CHUNK_OVERLAP_TOKENS, start + 1)
    if not chunks:
        raise ValueError("No chunks could be created from extracted text.")
    return chunks


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


async def _rank_chunks(query_text: str, chunks: list[KnowledgeDocumentChunk]) -> list[tuple[KnowledgeDocumentChunk, float]]:
    vector_matches = await _rank_chunks_by_vector(query_text, chunks)
    if vector_matches:
        return vector_matches
    return _rank_chunks_by_terms(query_text, chunks)


async def _rank_chunks_by_vector(query_text: str, chunks: list[KnowledgeDocumentChunk]) -> list[tuple[KnowledgeDocumentChunk, float]]:
    if not any(chunk.embedding for chunk in chunks):
        return []
    try:
        query_embedding = (await _embed_texts([query_text]))[0]
    except Exception:
        return []
    scored: list[tuple[KnowledgeDocumentChunk, float]] = []
    for chunk in chunks:
        if not chunk.embedding:
            continue
        score = _cosine_similarity(query_embedding, chunk.embedding)
        if score > 0:
            scored.append((chunk, round(score, 4)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


async def _build_standalone_retrieval_query(
    query_text: str,
    conversation_history: list[KnowledgeConversationTurn],
) -> str:
    query = query_text.strip()
    if not conversation_history:
        return query

    settings = get_settings()
    api_key = settings.openai_api_key or settings.llm_api_key
    if not api_key:
        return _build_retrieval_query(query, conversation_history)

    history_lines = [f"{turn.role}: {turn.content[:1000]}" for turn in conversation_history[-4:]]
    prompt = (
        "Rewrite the user's latest question as a standalone search query for operational "
        "knowledge retrieval. "
        "Keep named projects, SOP names, acronyms, policy terms, and version hints. "
        "Return only the rewritten query.\n\n"
        f"Recent conversation:\n{chr(10).join(history_lines)}\n\n"
        f"Latest question: {query}"
    )
    model = settings.openai_model or settings.llm_model or "gpt-4o-mini"
    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You rewrite follow-up questions into concise standalone "
                        "retrieval queries."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        rewritten = (response.choices[0].message.content or "").strip().strip('"')
    except Exception:
        return _build_retrieval_query(query, conversation_history)
    if not rewritten:
        return _build_retrieval_query(query, conversation_history)
    return rewritten[:EMBEDDING_INPUT_MAX_CHARS]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _rank_chunks_by_terms(
    query_text: str,
    chunks: list[KnowledgeDocumentChunk],
) -> list[tuple[KnowledgeDocumentChunk, float]]:
    terms = _tokenize_search_text(query_text)
    if not terms:
        return []
    unique_terms = sorted(set(terms))
    tokenized_chunks = [
        (chunk, _tokenize_search_text(chunk.chunk_text or chunk.content))
        for chunk in chunks
    ]
    if not tokenized_chunks:
        return []
    avg_doc_len = sum(len(tokens) for _chunk, tokens in tokenized_chunks) / max(
        len(tokenized_chunks),
        1,
    )
    doc_freq = {
        term: sum(1 for _chunk, tokens in tokenized_chunks if term in set(tokens))
        for term in unique_terms
    }
    total_docs = len(tokenized_chunks)
    scored: list[tuple[KnowledgeDocumentChunk, float]] = []
    for chunk, tokens in tokenized_chunks:
        if not tokens:
            continue
        term_counts = {term: tokens.count(term) for term in unique_terms}
        bm25 = 0.0
        for term in unique_terms:
            frequency = term_counts.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denominator = frequency + 1.2 * (
                1 - 0.75 + 0.75 * (len(tokens) / max(avg_doc_len, 1))
            )
            bm25 += idf * ((frequency * 2.2) / denominator)
        exact_boost = _exact_term_boost(query_text, chunk.chunk_text or chunk.content)
        score = min(1.0, (bm25 / (bm25 + 6.0) if bm25 > 0 else 0.0) + exact_boost)
        if score > 0:
            scored.append((chunk, round(score, 4)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _rerank_hybrid_candidates(
    candidates: list[KnowledgeDocumentChunk | _VectorChunk],
    *,
    vector_scores: dict[UUID, float],
    keyword_scores: dict[UUID, float],
    doc_map: dict[UUID, KnowledgeDocument],
    query_text: str,
) -> list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]]:
    scored: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]] = []
    has_vector = bool(vector_scores)
    for chunk in candidates:
        doc = doc_map.get(chunk.document_id)
        if doc is None:
            continue
        vector_score = max(0.0, vector_scores.get(chunk.id, 0.0))
        keyword_score = max(0.0, keyword_scores.get(chunk.id, 0.0))
        if has_vector:
            combined = (HYBRID_VECTOR_WEIGHT * vector_score) + (
                HYBRID_KEYWORD_WEIGHT * keyword_score
            )
        else:
            combined = keyword_score
        exact_boost = _exact_term_boost(
            query_text,
            f"{doc.title}\n{chunk.section_title or ''}\n{chunk.chunk_text or chunk.content}",
        )
        combined += min(EXACT_TERM_BOOST_MAX, exact_boost)
        combined += _recency_boost(doc)
        if combined > 0:
            scored.append((chunk, round(min(1.0, combined), 4)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _tokenize_search_text(text_value: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9]+", text_value.lower()) if len(term) > 1]


def _exact_term_boost(query_text: str, target_text: str) -> float:
    exact_terms = _extract_exact_terms(query_text)
    if not exact_terms:
        return 0.0
    target = target_text.lower()
    hits = sum(1 for term in exact_terms if term.lower() in target)
    return min(EXACT_TERM_BOOST_MAX, (hits / len(exact_terms)) * EXACT_TERM_BOOST_MAX)


def _extract_exact_terms(query_text: str) -> list[str]:
    terms: set[str] = set()
    for match in re.findall(r'"([^"]{2,80})"', query_text):
        terms.add(match.strip())
    for match in re.findall(
        r"\b[A-Z][A-Za-z0-9-]+(?:\s+[A-Z][A-Za-z0-9-]+){1,4}\b",
        query_text,
    ):
        terms.add(match.strip())
    for match in re.findall(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b", query_text):
        terms.add(match.strip())
    for match in re.findall(r"\b[a-zA-Z]+[0-9][a-zA-Z0-9-]*\b", query_text):
        terms.add(match.strip())
    return sorted(term for term in terms if term)


def _recency_boost(doc: KnowledgeDocument) -> float:
    reference: datetime | None = (
        doc.approved_at or doc.indexed_at or doc.updated_at or doc.created_at
    )
    if reference is None and doc.effective_date is not None:
        reference = datetime.combine(doc.effective_date, datetime.min.time(), tzinfo=UTC)
    if reference is None:
        return 0.0
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    age_days = max(0, (datetime.now(UTC) - reference).days)
    return round(RECENCY_BOOST_MAX / (1 + (age_days / 90)), 4)


async def _neighbor_context_for_matches(
    session: AsyncSession,
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]],
) -> dict[UUID, str]:
    if not matches or NEIGHBOR_CHUNK_WINDOW <= 0:
        return {}
    context: dict[UUID, str] = {}
    for chunk, _score in matches:
        lower = max(0, chunk.chunk_index - NEIGHBOR_CHUNK_WINDOW)
        upper = chunk.chunk_index + NEIGHBOR_CHUNK_WINDOW
        filters = [
            KnowledgeDocumentChunk.document_id == chunk.document_id,
            KnowledgeDocumentChunk.chunk_index >= lower,
            KnowledgeDocumentChunk.chunk_index <= upper,
        ]
        if chunk.version_id is not None:
            filters.append(KnowledgeDocumentChunk.version_id == chunk.version_id)
        neighbors = list(
            (
                await session.execute(
                    select(KnowledgeDocumentChunk)
                    .where(*filters)
                    .order_by(KnowledgeDocumentChunk.chunk_index)
                )
            ).scalars()
        )
        parts = [(item.chunk_text or item.content or "").strip() for item in neighbors]
        combined = "\n\n".join(part for part in parts if part)
        if combined:
            context[chunk.id] = combined
    return context


async def _build_structured_operational_context(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    query_text: str,
    explicit_project: str | None,
    client_safe: bool,
) -> str:
    project_row = await _resolve_structured_context_project(
        session,
        current_user,
        query_text=query_text,
        explicit_project=explicit_project,
    )
    if project_row is None:
        return ""

    milestones = list(
        (
            await session.execute(
                select(Milestone)
                .where(
                    Milestone.project_id == project_row.id,
                    Milestone.deleted_at.is_(None),
                )
                .order_by(Milestone.planned_date.desc())
                .limit(5)
            )
        ).scalars()
    )
    risks = list(
        (
            await session.execute(
                select(RiskAlert)
                .where(
                    RiskAlert.project_id == project_row.id,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(RiskAlert.created_at.desc())
                .limit(3)
            )
        ).scalars()
    )
    bottlenecks = list(
        (
            await session.execute(
                select(Bottleneck)
                .where(
                    Bottleneck.project_id == project_row.id,
                    Bottleneck.deleted_at.is_(None),
                    Bottleneck.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(Bottleneck.created_at.desc())
                .limit(3)
            )
        ).scalars()
    )
    throughput = (
        await session.execute(
            select(ThroughputSnapshot)
            .where(ThroughputSnapshot.project_id == project_row.id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    quality = (
        await session.execute(
            select(QualitySnapshot)
            .where(QualitySnapshot.project_id == project_row.id)
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    lines = [
        f"Project: {project_row.name}",
        f"Status: {project_row.status.value}",
        f"Target end date: {project_row.target_end_date.isoformat()}",
    ]
    if not client_safe and project_row.description:
        lines.append(f"Description: {project_row.description[:240]}")
    if milestones:
        milestone_text = "; ".join(
            f"{item.name} ({item.status.value}, planned {item.planned_date.isoformat()})"
            for item in milestones
        )
        lines.append(f"Recent milestones: {milestone_text}")
    if throughput:
        lines.append(
            "Latest throughput: "
            f"{throughput.units_completed} completed"
            f"{' / forecast ' + str(throughput.units_forecast) if throughput.units_forecast is not None else ''}"
            f" on {throughput.snapshot_date.isoformat()}"
        )
    if quality:
        quality_bits = [
            f"week {quality.iso_year}-W{quality.iso_week}",
            f"gold accuracy {_format_decimal(quality.gold_set_accuracy_pct)}",
            f"IAA {_format_decimal(quality.iaa_krippendorff_alpha)}",
            f"rework {_format_decimal(quality.rework_rate_pct)}",
        ]
        if quality.has_drift_alert:
            quality_bits.append("drift alert active")
        lines.append(f"Latest quality: {', '.join(bit for bit in quality_bits if bit)}")
    if risks:
        if client_safe:
            lines.append(f"Open delivery risks: {len(risks)} active item(s)")
        else:
            risk_text = "; ".join(
                f"{item.title} ({item.risk_tier.value}, {item.alert_type.value})"
                for item in risks
            )
            lines.append(f"Open delivery risks: {risk_text}")
    if bottlenecks:
        if client_safe:
            lines.append(f"Open bottlenecks: {len(bottlenecks)} active item(s)")
        else:
            bottleneck_text = "; ".join(item.title for item in bottlenecks)
            lines.append(f"Open bottlenecks: {bottleneck_text}")
    return "\n".join(lines)


async def _resolve_structured_context_project(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    query_text: str,
    explicit_project: str | None,
) -> Project | None:
    filters = [
        Project.org_id == current_user.org_id,
        Project.deleted_at.is_(None),
    ]
    if explicit_project and explicit_project.strip():
        project_name = explicit_project.strip().lower()
        return (
            await session.execute(
                select(Project).where(*filters, func.lower(Project.name) == project_name).limit(1)
            )
        ).scalar_one_or_none()

    projects = list(
        (
            await session.execute(select(Project).where(*filters).order_by(Project.updated_at.desc()).limit(50))
        ).scalars()
    )
    query_lower = query_text.lower()
    for project in projects:
        if project.name.lower() in query_lower:
            return project
    return None


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):g}"


def _ground_generation(
    answer_text: str,
    structured_answer: KnowledgeStructuredAnswer | None,
    context_chunks: list[dict[str, str]],
    structured_context: str,
) -> dict[str, float | bool]:
    evidence_text = "\n".join([chunk.get("text", "") for chunk in context_chunks] + [structured_context])
    evidence_tokens = set(_tokenize_search_text(evidence_text))
    if not evidence_tokens:
        return {"grounded": False, "support": 0.0}

    claim_text = answer_text
    if structured_answer is not None:
        claim_text += "\n" + "\n".join(
            [
                structured_answer.policy,
                structured_answer.steps,
                structured_answer.owner,
                structured_answer.evidence,
                structured_answer.next_action,
            ]
        )
    claims = _extract_generation_claims(claim_text)
    if not claims:
        return {"grounded": True, "support": 1.0}

    supported = 0
    evidence_lower = evidence_text.lower()
    for claim in claims:
        normalized_claim = re.sub(r"\[doc:[^\]]+\]", "", claim, flags=re.IGNORECASE).strip()
        claim_tokens = set(_tokenize_search_text(normalized_claim))
        if len(claim_tokens) < 4:
            supported += 1
            continue
        overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens)
        exact_phrase = normalized_claim.lower()[:120] in evidence_lower
        if exact_phrase or overlap >= 0.45:
            supported += 1
    support = supported / len(claims)
    return {"grounded": support >= 0.65, "support": round(support, 4)}


def _extract_generation_claims(text_value: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text_value).strip()
    if not cleaned:
        return []
    candidates = re.split(r"(?<=[.!?])\s+|(?:^|\s)\d+[\.)]\s+", cleaned)
    return [item.strip(" -") for item in candidates if len(_tokenize_search_text(item)) >= 4]


def _ensure_eval_manager(current_user: CurrentUser) -> None:
    if current_user.role not in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "Only leadership can manage knowledge evals.")


def _mean_bool(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _percentile_int(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[int(position)]
    weighted = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return int(round(weighted))


def _source_label(source_type: KnowledgeSourceType) -> str:
    return source_type.value.replace("_", " ").title()


def _is_retrieval_ready(doc: KnowledgeDocument) -> bool:
    return (
        doc.status == KnowledgeDocumentStatus.APPROVED
        and doc.processing_status == KnowledgeProcessingStatus.READY
        and doc.indexing_status == KnowledgeIndexingStatus.INDEXED
    )


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
    if read.quality_score and read.status == "approved":
        if read.quality_score.score < UPLOAD_APPROVED_MIN_METADATA_SCORE:
            failed = [item.label for item in read.quality_score.criteria if not item.passed]
            if failed:
                warnings.append(f"Quality score {read.quality_score.score}/{read.quality_score.max_score}: missing {', '.join(failed)}.")
    return warnings


async def build_library_health(
    session: AsyncSession,
    org_id: UUID,
    documents: list[KnowledgeDocumentRead],
) -> KnowledgeLibraryHealthRead:
    counts = {
        "ready": 0,
        "needs_review": 0,
        "expired": 0,
        "needs_reindex": 0,
        "indexing": 0,
        "draft": 0,
        "archived": 0,
    }
    for doc in documents:
        if doc.workflow_state == "approved":
            counts["ready"] += 1
        elif doc.workflow_state == "expired":
            counts["expired"] += 1
        elif doc.workflow_state == "needs_reindex":
            counts["needs_reindex"] += 1
        elif doc.workflow_state == "archived":
            counts["archived"] += 1
        elif doc.workflow_state == "needs_review":
            counts["needs_review"] += 1
        if doc.status == "draft":
            counts["draft"] += 1
        if doc.indexing_status == "indexing" or doc.processing_status in {
            "uploaded",
            "extracting",
            "extracted",
            "chunking",
            "chunked",
            "embedding",
        }:
            counts["indexing"] += 1

    open_gaps: list[KnowledgeGapTodoRead] = []
    try:
        gap_rows = list(
            (
                await session.execute(
                    select(KnowledgeGap)
                    .where(
                        KnowledgeGap.org_id == org_id,
                        KnowledgeGap.status == KnowledgeGapStatus.OPEN,
                    )
                    .order_by(KnowledgeGap.created_at.desc())
                    .limit(20)
                )
            ).scalars()
        )
        open_gaps = [
            KnowledgeGapTodoRead(
                id=gap.id,
                query_text=gap.query_text,
                message=gap.message,
                suggested_title=gap.suggested_title,
                suggested_source_type=gap.suggested_source_type,
                suggested_folder_kind=gap.suggested_folder_kind,
                agent_query_id=gap.agent_query_id,
                created_at=gap.created_at,
            )
            for gap in gap_rows
        ]
    except ProgrammingError as exc:
        if not _is_missing_schema_error(exc):
            raise
        logger.warning("knowledge_gaps table missing; returning empty open_gaps")
        await session.rollback()

    return KnowledgeLibraryHealthRead(
        ready_count=counts["ready"],
        needs_review_count=counts["needs_review"],
        expired_count=counts["expired"],
        needs_reindex_count=counts["needs_reindex"],
        indexing_count=counts["indexing"],
        draft_count=counts["draft"],
        archived_count=counts["archived"],
        open_gaps=open_gaps,
    )


async def _record_knowledge_gap(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    query_text: str,
    gap: KnowledgeGapRead,
    agent_query_id: UUID | None = None,
) -> None:
    try:
        existing = (
            await session.execute(
                select(KnowledgeGap).where(
                    KnowledgeGap.org_id == current_user.org_id,
                    KnowledgeGap.status == KnowledgeGapStatus.OPEN,
                    KnowledgeGap.query_text == query_text.strip(),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.message = gap.message
            existing.suggested_title = gap.suggested_title
            existing.suggested_source_type = gap.suggested_source_type
            existing.suggested_folder_kind = gap.suggested_folder_kind
            if agent_query_id is not None:
                existing.agent_query_id = agent_query_id
            return
        session.add(
            KnowledgeGap(
                org_id=current_user.org_id,
                agent_query_id=agent_query_id,
                query_text=query_text.strip(),
                message=gap.message,
                suggested_title=gap.suggested_title,
                suggested_source_type=gap.suggested_source_type,
                suggested_folder_kind=gap.suggested_folder_kind,
                status=KnowledgeGapStatus.OPEN,
            )
        )
    except ProgrammingError as exc:
        if not _is_missing_schema_error(exc):
            raise
        logger.warning("knowledge_gaps table missing; skipping gap persistence")
        await session.rollback()


async def resolve_knowledge_gap(
    session: AsyncSession,
    current_user: CurrentUser,
    gap_id: UUID,
) -> KnowledgeGapTodoRead:
    gap = (
        await session.execute(
            select(KnowledgeGap).where(
                KnowledgeGap.id == gap_id,
                KnowledgeGap.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if gap is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge gap not found.")
    gap.status = KnowledgeGapStatus.RESOLVED
    gap.resolved_at = datetime.now(UTC)
    gap.resolved_by = current_user.id
    await session.flush()
    return KnowledgeGapTodoRead(
        id=gap.id,
        query_text=gap.query_text,
        message=gap.message,
        suggested_title=gap.suggested_title,
        suggested_source_type=gap.suggested_source_type,
        suggested_folder_kind=gap.suggested_folder_kind,
        agent_query_id=gap.agent_query_id,
        created_at=gap.created_at,
    )


def _compute_workflow_state(doc: KnowledgeDocument) -> str:
    if doc.status == KnowledgeDocumentStatus.DRAFT:
        return "needs_review"
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        return "archived"
    if (
        doc.source_type == KnowledgeSourceType.SOP
        and doc.status == KnowledgeDocumentStatus.APPROVED
        and doc.approved_at
        and doc.effective_date is None
        and (datetime.now(UTC) - doc.approved_at).days > SOP_STALE_DAYS
    ):
        return "expired"
    if (
        doc.status == KnowledgeDocumentStatus.APPROVED
        and (
            doc.indexing_status in {KnowledgeIndexingStatus.NOT_INDEXED, KnowledgeIndexingStatus.FAILED}
            or doc.processing_status in {KnowledgeProcessingStatus.FAILED, KnowledgeProcessingStatus.UPLOADED}
            or doc.processing_status != KnowledgeProcessingStatus.READY
        )
    ):
        return "needs_reindex"
    if _is_retrieval_ready(doc):
        return "approved"
    return "needs_review"


def _compute_quality_score(doc: KnowledgeDocument, chunk_count: int, citation_count: int) -> KnowledgeQualityScore:
    criteria = [
        KnowledgeQualityCriterion(key="approved", label="Approved", passed=doc.status == KnowledgeDocumentStatus.APPROVED),
        KnowledgeQualityCriterion(key="ready", label="Ready", passed=doc.processing_status == KnowledgeProcessingStatus.READY),
        KnowledgeQualityCriterion(key="has_owner", label="Has owner", passed=bool((doc.owner_approver or "").strip())),
        KnowledgeQualityCriterion(
            key="has_effective_date",
            label="Has effective date",
            passed=doc.effective_date is not None,
        ),
        KnowledgeQualityCriterion(key="has_chunks", label="Has chunks", passed=chunk_count > 0),
        KnowledgeQualityCriterion(key="has_citations", label="Has citations", passed=citation_count > 0),
    ]
    score = sum(1 for item in criteria if item.passed)
    return KnowledgeQualityScore(score=score, max_score=len(criteria), criteria=criteria)


def _build_confidence_reasons(
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]],
    eligible_docs: list[KnowledgeDocument],
    doc_map: dict[UUID, KnowledgeDocument],
    query_text: str,
) -> list[str]:
    reasons: list[str] = []
    unique_docs = len({chunk.document_id for chunk, _ in matches})
    strong = sum(1 for _, score in matches if score >= STRONG_RELEVANCE_THRESHOLD)
    reasons.append(f"Matched {unique_docs} approved document{'s' if unique_docs != 1 else ''}")
    if strong > 0:
        reasons.append(f"{strong} chunk{'s' if strong != 1 else ''} were strongly relevant")
    else:
        reasons.append("No chunks exceeded the strong relevance threshold")
    query_lower = query_text.lower()
    sop_hint = any(term in query_lower for term in ("sop", "procedure", "policy", "standard"))
    sop_matched = any(doc_map[chunk.document_id].source_type == KnowledgeSourceType.SOP for chunk, _ in matches)
    if sop_hint and not sop_matched:
        reasons.append("No exact SOP match found")
    elif not eligible_docs:
        reasons.append("No approved documents were eligible for retrieval")
    return reasons


def _build_retrieval_query(query_text: str, conversation_history: list[KnowledgeConversationTurn]) -> str:
    if not conversation_history:
        return query_text
    lines = [f"{turn.role}: {turn.content}" for turn in conversation_history[-4:]]
    lines.append(f"user: {query_text}")
    return "\n".join(lines)


def _build_knowledge_gap(query_text: str, reason: str | None = None) -> KnowledgeGapRead:
    cleaned = query_text.strip().rstrip("?.!")
    lower = cleaned.lower()
    suggested_source = "sop"
    suggested_folder = "sops"
    if any(term in lower for term in ("lesson", "history", "project alpha", "escalation")):
        suggested_source = "lesson_learned"
        suggested_folder = "histories"
    elif any(term in lower for term in ("guide", "onboarding", "training")):
        suggested_source = "guide"
        suggested_folder = "guides"
    title_bits = cleaned[:80] if cleaned else "Operational knowledge"
    message = reason or f"No approved knowledge found for: {cleaned}."
    if "sop" in lower or "calibration" in lower or "iaa" in lower:
        message = f"No approved SOP found for {cleaned.lower()}."
    return KnowledgeGapRead(
        message=message,
        suggested_title=title_bits,
        suggested_source_type=suggested_source,
        suggested_folder_kind=suggested_folder,
    )


def _build_retrieval_params(
    *,
    query_text: str,
    retrieval_query: str,
    answer_mode: str,
    include_histories: bool,
    max_sources: int,
    min_relevance_score: float,
    project: str | None,
    department: str | None,
    eligible_doc_count: int,
    has_embeddings: bool,
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]],
    doc_map: dict[UUID, KnowledgeDocument],
    vector_scores: dict[UUID, float],
    keyword_scores: dict[UUID, float],
    confidence_score: float | None = None,
) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    for chunk, score in matches:
        doc = doc_map.get(chunk.document_id)
        sources.append(
            {
                "document_id": str(chunk.document_id),
                "chunk_id": str(chunk.id),
                "title": doc.title if doc else "",
                "relevance_score": round(score, 4),
                "vector_score": round(vector_scores.get(chunk.id, 0.0), 4),
                "keyword_score": round(keyword_scores.get(chunk.id, 0.0), 4),
            }
        )
    params: dict[str, object] = {
        "query_text": query_text,
        "retrieval_query": retrieval_query,
        "answer_mode": answer_mode,
        "include_histories": include_histories,
        "max_sources": max_sources,
        "min_relevance_score": min_relevance_score,
        "project": project,
        "department": department,
        "eligible_doc_count": eligible_doc_count,
        "has_embeddings": has_embeddings,
        "sources": sources,
    }
    if confidence_score is not None:
        params["confidence_score"] = confidence_score
    return params


async def _persist_empty_ask_response(
    session: AsyncSession,
    current_user: CurrentUser,
    query_text: str,
    *,
    started: datetime,
    reason: str,
    eligible_docs: list[KnowledgeDocument] | None = None,
    matches: list[tuple[KnowledgeDocumentChunk, float]] | None = None,
    retrieval_params: dict[str, object] | None = None,
) -> KnowledgeAskRead:
    gap = _build_knowledge_gap(query_text, reason=reason)
    confidence_reasons = [reason]
    if eligible_docs is not None:
        confidence_reasons.append(f"Only {len(eligible_docs)} approved document(s) were eligible")
    if matches is not None and not matches:
        confidence_reasons.append("Retrieved chunks did not meet the relevance threshold")
    agent_query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=None,
        agent_name=KNOWLEDGE_AGENT_NAME,
        query_text=query_text,
        answer_text=NO_APPROVED_ANSWER,
        model_used=None,
        latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        retrieval_params=retrieval_params,
    )
    session.add(agent_query)
    await session.flush()
    await _record_knowledge_gap(
        session,
        current_user,
        query_text=query_text,
        gap=gap,
        agent_query_id=agent_query.id,
    )
    return KnowledgeAskRead(
        answer_text=NO_APPROVED_ANSWER,
        next_step="Upload or approve a related document to close this knowledge gap.",
        confidence_score=0.0,
        confidence_reasons=confidence_reasons,
        structured_answer=None,
        knowledge_gap=gap,
        citations=[],
        query_id=agent_query.id,
        model_used=None,
    )


async def _batch_user_display_names(session: AsyncSession, user_ids: set[UUID]) -> dict[UUID, str]:
    if not user_ids:
        return {}
    users = list((await session.execute(select(User).where(User.id.in_(user_ids)))).scalars())
    return {user.id: user.full_name or user.email for user in users}


async def _user_display_name(session: AsyncSession, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    names = await _batch_user_display_names(session, {user_id})
    return names.get(user_id)


async def _version_extracted_text(session: AsyncSession, version_id: UUID) -> str:
    extraction = (
        await session.execute(
            select(KnowledgeDocumentExtraction).where(KnowledgeDocumentExtraction.version_id == version_id)
        )
    ).scalar_one_or_none()
    if extraction and extraction.extracted_text:
        return extraction.extracted_text
    chunks = list(
        (
            await session.execute(
                select(KnowledgeDocumentChunk)
                .where(KnowledgeDocumentChunk.version_id == version_id)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            )
        ).scalars()
    )
    return "\n\n".join((chunk.chunk_text or chunk.content or "").strip() for chunk in chunks if (chunk.chunk_text or chunk.content))


async def _rank_documents_semantic(
    session: AsyncSession,
    semantic_query: str,
    reads: list[KnowledgeDocumentRead],
) -> list[KnowledgeDocumentRead]:
    if not reads:
        return reads
    try:
        query_embedding = (await _embed_texts([semantic_query]))[0]
    except Exception:
        return reads
    vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_embedding) + "]"
    doc_ids = [read.id for read in reads]
    sql = text(
        """
        SELECT c.document_id, MAX(1 - (c.embedding <=> CAST(:vec AS vector))) AS score
        FROM knowledge_document_chunks c
        WHERE c.document_id = ANY(:doc_ids)
          AND c.embedding IS NOT NULL
        GROUP BY c.document_id
        ORDER BY score DESC
        """
    )
    rows = (await session.execute(sql, {"vec": vec_literal, "doc_ids": doc_ids})).all()
    score_map = {row[0]: float(row[1]) for row in rows}
    ranked = []
    for read in reads:
        relevance = score_map.get(read.id, 0.0)
        ranked.append(read.model_copy(update={"semantic_relevance": round(relevance, 4)}))
    ranked.sort(key=lambda item: item.semantic_relevance or 0.0, reverse=True)
    return ranked


async def _notify_knowledge_stakeholders(
    session: AsyncSession,
    doc: KnowledgeDocument,
    *,
    title: str,
    body: str,
    actor_id: UUID,
) -> None:
    recipients = list(
        (
            await session.execute(
                select(User).where(
                    User.org_id == doc.org_id,
                    User.deleted_at.is_(None),
                    User.role.in_([AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN, AppRole.DELIVERY_MANAGER]),
                )
            )
        ).scalars()
    )
    owner_hint = (doc.owner_approver or doc.approver or "").strip().lower()
    notified: set[UUID] = set()
    for user in recipients:
        if user.id == actor_id:
            continue
        if owner_hint and owner_hint not in (user.full_name or "").lower() and owner_hint not in user.email.lower():
            if user.role not in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
                continue
        if user.id in notified:
            continue
        notified.add(user.id)
        await create_notification(
            session,
            user_id=user.id,
            org_id=doc.org_id,
            notification_type=NotificationType.SYSTEM,
            title=title,
            body=body,
            source_table="knowledge_documents",
            source_row_id=doc.id,
        )
