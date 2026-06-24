import hashlib
import csv
import difflib
import io
import mimetypes
import re
import math
from dataclasses import dataclass
from decimal import Decimal
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import httpx
from openai import AsyncOpenAI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models.entities import (
    AppRole,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentExtraction,
    KnowledgeDocumentVersion,
    KnowledgeDocumentStatus,
    KnowledgeExtractionStatus,
    KnowledgeEvidenceLink,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
    AgentQuery,
    NotificationType,
    User,
)
from app.schemas.domain import (
    KnowledgeAskRead,
    KnowledgeCitationRead,
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentVersionRead,
    KnowledgeGapRead,
    KnowledgeChunkRead,
    KnowledgeQualityCriterion,
    KnowledgeQualityScore,
    KnowledgeRetrievalSettingsRead,
    KnowledgeRetrievalSettingsUpdate,
    KnowledgeStructuredAnswer,
    KnowledgeVersionCompareRead,
)
from app.services.llm.client import LLMClient
from app.services.notifications import create_notification

FOLDER_SEED = (
    (KnowledgeFolderKind.SOPS, "SOPs", 0),
    (KnowledgeFolderKind.GUIDES, "Guides", 1),
    (KnowledgeFolderKind.HISTORIES, "Histories", 2),
)
FOLDER_DEFAULTS = {kind: (name, order) for kind, name, order in FOLDER_SEED}

TEXT_EXTENSIONS = {".txt", ".md"}
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}
NO_APPROVED_ANSWER = "I could not find this information in the uploaded knowledge base."
STRONG_RELEVANCE_THRESHOLD = 0.6
CHUNK_TARGET_TOKENS = 900
CHUNK_OVERLAP_TOKENS = 120
EMBEDDING_BATCH_SIZE = 64


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
) -> list[KnowledgeDocumentRead]:
    cross_org = current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}
    if not cross_org:
        await ensure_knowledge_folders(session, current_user.org_id)

    doc_filters = [KnowledgeDocument.deleted_at.is_(None)]
    if not cross_org:
        doc_filters.append(KnowledgeDocument.org_id == current_user.org_id)

    docs = list(
        (
            await session.execute(
                select(KnowledgeDocument).where(*doc_filters).order_by(KnowledgeDocument.title)
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
            await ensure_knowledge_folders(session, doc.org_id)
            folder = (
                await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))
            ).scalar_one_or_none()
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
        doc.version = payload.version
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
    return await _to_document_read(session, doc, folder)


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
    include_histories: bool = True,
    max_sources: int = 5,
    min_relevance_score: float = 0.25,
    project: str | None = None,
    department: str | None = None,
) -> KnowledgeAskRead:
    started = datetime.now(UTC)
    max_sources = max(1, min(max_sources, 10))
    min_relevance_score = max(0.0, min(min_relevance_score, 1.0))

    # ── 1. Resolve approved + indexed documents visible to this role ──────────
    docs = list(
        (
            await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.org_id == current_user.org_id,
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
                    KnowledgeDocument.indexing_status == KnowledgeIndexingStatus.INDEXED,
                    KnowledgeDocument.processing_status == KnowledgeProcessingStatus.READY,
                )
            )
        ).scalars()
    )
    eligible_docs = [doc for doc in docs if can_access_visibility(current_user.role, doc.visibility)]
    if not eligible_docs:
        return _empty_ask_response(query_text, reason="No approved documents are available for your role.")

    # ── 2. Load folders for citation metadata ─────────────────────────────────
    folder_ids = {doc.folder_id for doc in eligible_docs}
    folders_map: dict[UUID, KnowledgeFolder] = {
        row.id: row
        for row in (
            await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id.in_(folder_ids)))
        ).scalars()
    }
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
        return _empty_ask_response(query_text, reason="No documents matched the project or department filters.")

    doc_ids = [doc.id for doc in eligible_docs]
    active_version_ids = [doc.active_version_id for doc in eligible_docs if doc.active_version_id]
    doc_map = {doc.id: doc for doc in eligible_docs}

    # ── 3. Embed the query ────────────────────────────────────────────────────
    try:
        query_embedding = (await _embed_texts([query_text]))[0]
        has_embeddings = True
    except Exception:
        query_embedding = []
        has_embeddings = False

    # ── 4. Retrieve top-5 chunks via pgvector ANN (or term fallback) ──────────
    TOP_K = max_sources
    matches: list[tuple[KnowledgeDocumentChunk, float]] = []

    if has_embeddings:
        # Format vector literal for pgvector: '[f1,f2,...]'
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_embedding) + "]"

        chunk_filter_clauses = ["c.document_id = ANY(:doc_ids)"]
        params: dict[str, object] = {"doc_ids": doc_ids, "vec": vec_literal, "top_k": TOP_K}
        if active_version_ids:
            chunk_filter_clauses.append("c.version_id = ANY(:ver_ids)")
            params["ver_ids"] = active_version_ids

        where_clause = " AND ".join(chunk_filter_clauses)
        sql = text(
            f"""
            SELECT c.id, 1 - (c.embedding <=> CAST(:vec AS vector)) AS score
            FROM knowledge_document_chunks c
            WHERE {where_clause}
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:vec AS vector)
            LIMIT :top_k
            """
        )
        rows = (await session.execute(sql, params)).all()

        if rows:
            chunk_ids = [row[0] for row in rows]
            score_map = {row[0]: float(row[1]) for row in rows}
            chunk_objs = list(
                (
                    await session.execute(
                        select(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.id.in_(chunk_ids))
                    )
                ).scalars()
            )
            chunk_by_id = {c.id: c for c in chunk_objs}
            matches = [
                (chunk_by_id[cid], score_map[cid])
                for cid in chunk_ids
                if cid in chunk_by_id and score_map[cid] >= min_relevance_score
            ]

    if not matches:
        # Term-frequency fallback when pgvector unavailable or returns nothing useful
        chunk_filters = [KnowledgeDocumentChunk.document_id.in_(doc_ids)]
        if active_version_ids:
            chunk_filters.append(KnowledgeDocumentChunk.version_id.in_(active_version_ids))
        all_chunks = list(
            (
                await session.execute(
                    select(KnowledgeDocumentChunk).where(*chunk_filters)
                )
            ).scalars()
        )
        matches = [
            (chunk, score)
            for chunk, score in _rank_chunks_by_terms(query_text, all_chunks)
            if score >= min_relevance_score
        ][:TOP_K]

    if not matches:
        return _empty_ask_response(
            query_text,
            reason="No relevant chunks met the minimum relevance threshold.",
            eligible_docs=eligible_docs,
        )

    # ── 5. Build context for GPT and call LLMClient ───────────────────────────
    llm = LLMClient()
    context_chunks: list[dict[str, str]] = []
    for chunk, _score in matches:
        doc = doc_map[chunk.document_id]
        folder = folders_map.get(doc.folder_id)
        context_chunks.append(
            {
                "title": doc.title,
                "source_type": _source_label(doc.source_type),
                "folder": folder.name if folder else doc.folder_id.hex,
                "page": str(chunk.page_number) if chunk.page_number else "",
                "text": (chunk.chunk_text or chunk.content or "").strip(),
            }
        )

    llm_result = await llm.generate_rag_answer(query_text, context_chunks)
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

    if answer_text.strip() == NO_APPROVED_ANSWER:
        return _empty_ask_response(
            query_text,
            reason="Retrieved chunks did not contain a confident answer.",
            eligible_docs=eligible_docs,
            matches=matches,
        )

    # ── 6. Persist AgentQuery ─────────────────────────────────────────────────
    agent_query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=None,
        agent_name="operational_knowledge_agent",
        query_text=query_text,
        answer_text=answer_text,
        model_used=model_used,
        latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
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

    retrieval_signal = matches[0][1] if matches else 0.0
    confidence_score = round(0.6 * raw_confidence + 0.4 * min(retrieval_signal, 1.0), 4)
    confidence_reasons = _build_confidence_reasons(matches, eligible_docs, doc_map, query_text)

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
    )


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

    citation_rows = (
        await session.execute(
            select(KnowledgeEvidenceLink.document_id, func.count(KnowledgeEvidenceLink.id))
            .where(KnowledgeEvidenceLink.document_id.in_(doc_ids))
            .group_by(KnowledgeEvidenceLink.document_id)
        )
    ).all()
    citation_counts = {row[0]: int(row[1]) for row in citation_rows}

    chunk_count_sql = text(
        """
        SELECT c.document_id, COUNT(*)::int
        FROM knowledge_document_chunks c
        JOIN knowledge_documents d ON d.id = c.document_id
        WHERE c.document_id = ANY(:doc_ids)
          AND (d.active_version_id IS NULL OR c.version_id = d.active_version_id)
        GROUP BY c.document_id
        """
    )
    chunk_count_rows = (await session.execute(chunk_count_sql, {"doc_ids": doc_ids})).all()
    chunk_counts = {row[0]: int(row[1]) for row in chunk_count_rows}

    preview_sql = text(
        """
        SELECT document_id, chunk_text, content
        FROM (
            SELECT c.document_id, c.chunk_text, c.content, c.chunk_index,
                   ROW_NUMBER() OVER (PARTITION BY c.document_id ORDER BY c.chunk_index) AS rn
            FROM knowledge_document_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.document_id = ANY(:doc_ids)
              AND (d.active_version_id IS NULL OR c.version_id = d.active_version_id)
        ) sub
        WHERE rn <= 6
        ORDER BY document_id, chunk_index
        """
    )
    preview_rows = (await session.execute(preview_sql, {"doc_ids": doc_ids})).all()
    previews: dict[UUID, list[str]] = {}
    for doc_id, chunk_text, content in preview_rows:
        text_value = (chunk_text or content or "").strip()
        if text_value:
            previews.setdefault(doc_id, []).append(text_value)

    user_names = await _batch_user_display_names(
        session,
        {doc.approved_by for doc in docs if doc.approved_by},
    )

    return {
        doc_id: _DocumentListPreload(
            chunk_count=chunk_counts.get(doc_id, 0),
            citation_count=citation_counts.get(doc_id, 0),
            preview=previews.get(doc_id)
            or [f"{doc_by_id[doc_id].title} is stored but has no indexed preview content yet."],
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
    api_key = settings.openai_api_key or settings.llm_api_key
    if not api_key:
        raise RuntimeError("OpenAI API key is not configured for document embeddings.")
    client_kwargs = {"api_key": api_key}
    base_url = settings.openai_base_url or settings.llm_base_url
    if base_url:
        client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)
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


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _rank_chunks_by_terms(query_text: str, chunks: list[KnowledgeDocumentChunk]) -> list[tuple[KnowledgeDocumentChunk, float]]:
    terms = [term for term in re.findall(r"[a-z0-9]+", query_text.lower()) if len(term) > 2]
    if not terms:
        return []
    scored: list[tuple[KnowledgeDocumentChunk, float]] = []
    for chunk in chunks:
        haystack = (chunk.chunk_text or chunk.content).lower()
        hits = sum(1 for term in terms if term in haystack)
        if hits:
            scored.append((chunk, round(hits / len(terms), 4)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _source_label(source_type: KnowledgeSourceType) -> str:
    return source_type.value.replace("_", " ").title()


def _is_retrieval_ready(doc: KnowledgeDocument) -> bool:
    return (
        doc.status == KnowledgeDocumentStatus.APPROVED
        and doc.processing_status == KnowledgeProcessingStatus.READY
        and doc.indexing_status == KnowledgeIndexingStatus.INDEXED
    )


def _compute_workflow_state(doc: KnowledgeDocument) -> str:
    today = datetime.now(UTC).date()
    if doc.status == KnowledgeDocumentStatus.DRAFT:
        return "needs_review"
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        return "archived"
    if doc.effective_date and doc.effective_date < today:
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
    matches: list[tuple[KnowledgeDocumentChunk, float]],
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


def _empty_ask_response(
    query_text: str,
    *,
    reason: str,
    eligible_docs: list[KnowledgeDocument] | None = None,
    matches: list[tuple[KnowledgeDocumentChunk, float]] | None = None,
) -> KnowledgeAskRead:
    gap = _build_knowledge_gap(query_text, reason=reason)
    confidence_reasons = [reason]
    if eligible_docs is not None:
        confidence_reasons.append(f"Only {len(eligible_docs)} approved document(s) were eligible")
    if matches is not None and not matches:
        confidence_reasons.append("Retrieved chunks did not meet the relevance threshold")
    return KnowledgeAskRead(
        answer_text=NO_APPROVED_ANSWER,
        next_step="Upload or approve a related document to close this knowledge gap.",
        confidence_score=0.0,
        confidence_reasons=confidence_reasons,
        structured_answer=None,
        knowledge_gap=gap,
        citations=[],
        query_id=None,
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
