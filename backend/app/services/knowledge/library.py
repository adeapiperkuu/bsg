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
    KnowledgeDocumentApprovalEvent,
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
    KnowledgeDocumentApprovalEventRead,
    KnowledgeDocumentLifecycleAction,
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

from app.services.knowledge.analytics import (
    _is_document_expired,
    _is_retrieval_ready,
    assess_retrieval_readiness,
)
from app.services.knowledge.permissions import (
    can_access_visibility,
)
from app.services.knowledge.utils import (
    _batch_user_display_names,
    _invalidate_knowledge_answer_cache,
    _loaded_datetime,
    _user_display_name,
)



# --- library (Phase 8) ---

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
    KnowledgeDocument.created_by,
    KnowledgeDocument.submitted_by,
    KnowledgeDocument.submitted_at,
    KnowledgeDocument.reviewed_by,
    KnowledgeDocument.reviewed_at,
    KnowledgeDocument.rejection_reason,
    KnowledgeDocument.expiry_date,
    KnowledgeDocument.executive_summary,
    KnowledgeDocument.key_procedures,
    KnowledgeDocument.important_warnings,
    KnowledgeDocument.affected_departments,
    KnowledgeDocument.related_document_ids,
    KnowledgeDocument.summary_generated_at,
)

SUBMIT_STATUSES = {
    KnowledgeDocumentStatus.DRAFT,
    KnowledgeDocumentStatus.REJECTED,
    KnowledgeDocumentStatus.EXPIRED,
}
APPROVE_STATUSES = {KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW}
REJECT_STATUSES = {KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW}
RETURN_TO_DRAFT_STATUSES = {
    KnowledgeDocumentStatus.REJECTED,
    KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW,
    KnowledgeDocumentStatus.EXPIRED,
    KnowledgeDocumentStatus.NEEDS_REINDEX,
}
ARCHIVE_STATUSES = {
    KnowledgeDocumentStatus.APPROVED,
    KnowledgeDocumentStatus.EXPIRED,
    KnowledgeDocumentStatus.REJECTED,
    KnowledgeDocumentStatus.NEEDS_REINDEX,
}
RESTORE_STATUSES = {KnowledgeDocumentStatus.ARCHIVED}
APPROVAL_MANAGE_ROLES = {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
APPROVAL_REVIEW_ROLES = {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}

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

async def _list_visible_documents_with_folders(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    folders_ready: bool = False,
) -> tuple[list[KnowledgeDocument], dict[UUID, KnowledgeFolder]]:
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
    return visible, folders

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
    ai_rank: bool = False,
    folders_ready: bool = False,
) -> list[KnowledgeDocumentRead]:
    visible, folders = await _list_visible_documents_with_folders(
        session,
        current_user,
        folders_ready=folders_ready,
    )

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
            is_ready = _is_retrieval_ready(doc, org_id=current_user.org_id)
            if ready != is_ready:
                continue
        if workflow_state and read.workflow_state != workflow_state:
            continue
        reads.append(read)

    if ai_rank and semantic_query and semantic_query.strip():
        reads = await _rank_documents_semantic(session, semantic_query.strip(), reads)

    return reads

def _to_document_summary_read(doc: KnowledgeDocument, folder: KnowledgeFolder) -> KnowledgeDocumentSummaryRead:
    readiness = assess_retrieval_readiness(doc, org_id=doc.org_id)
    return KnowledgeDocumentSummaryRead(
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
        expiry_date=doc.expiry_date,
        submitted_at=doc.submitted_at,
        reviewed_at=doc.reviewed_at,
        approved_at=doc.approved_at,
        rejection_reason=doc.rejection_reason,
        file_name=doc.file_name,
        processing_status=doc.processing_status.value,
        processing_error=doc.processing_error,
        indexing_status=doc.indexing_status.value,
        workflow_state=_compute_workflow_state(doc),
        retrieval_ready=readiness.is_ready,
        retrieval_readiness_reason=readiness.reason,
        retrieval_action=readiness.action,
        updated_at=_loaded_datetime(doc, "updated_at"),
    )

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
    import app.services.knowledge as knowledge_services

    file_bytes = await knowledge_services._read_stored_file(doc.storage_path)
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
    was_approved = doc.status == KnowledgeDocumentStatus.APPROVED
    content_changed = False
    if payload.title is not None:
        new_title = payload.title.strip()
        content_changed = content_changed or new_title != doc.title
        doc.title = new_title
    if payload.folder_id is not None:
        doc.folder_id = (await get_folder_by_id(session, current_user.org_id, payload.folder_id)).id
    elif payload.folder_kind is not None:
        doc.folder_id = (await get_folder_for_kind(session, current_user.org_id, KnowledgeFolderKind(payload.folder_kind))).id
    if payload.source_type is not None:
        new_source_type = KnowledgeSourceType(payload.source_type)
        content_changed = content_changed or new_source_type != doc.source_type
        doc.source_type = new_source_type
    if payload.version is not None:
        new_version = payload.version.strip()
        version_changed = new_version != doc.version
        content_changed = content_changed or version_changed
        doc.version = new_version
    else:
        version_changed = False
    if payload.visibility is not None:
        doc.visibility = KnowledgeVisibility(payload.visibility)
    if payload.owner_approver is not None:
        doc.owner_approver = payload.owner_approver.strip()
    if payload.effective_date is not None:
        doc.effective_date = payload.effective_date
    if payload.expiry_date is not None:
        doc.expiry_date = payload.expiry_date
    if was_approved and content_changed:
        doc.status = KnowledgeDocumentStatus.NEEDS_REINDEX
        doc.approved_at = None
        doc.approved_by = None
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    if version_changed and doc.active_version_id:
        if (
            await session.execute(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == doc.active_version_id)
            )
        ).scalar_one_or_none():
            doc.processing_status = KnowledgeProcessingStatus.UPLOADED
            doc.indexing_status = KnowledgeIndexingStatus.NOT_INDEXED
            doc.indexed_at = None
            doc.processing_error = None
            await session.flush()
    await _notify_knowledge_stakeholders(
        session,
        doc,
        title="Knowledge document updated",
        body=f'"{doc.title}" was updated and may need review or re-approval.',
        actor_id=current_user.id,
    )
    _invalidate_knowledge_answer_cache(current_user.org_id)
    return await _to_document_read(session, doc, folder)

def _assert_can_manage_approval(current_user: CurrentUser) -> None:
    if current_user.role not in APPROVAL_MANAGE_ROLES:
        raise ApiError(403, "FORBIDDEN", "You cannot manage knowledge approvals.")

def _assert_can_review_approval(current_user: CurrentUser) -> None:
    if current_user.role not in APPROVAL_REVIEW_ROLES:
        raise ApiError(403, "FORBIDDEN", "Only leadership or admins can approve or reject knowledge documents.")

async def _log_approval_event(
    session: AsyncSession,
    doc: KnowledgeDocument,
    current_user: CurrentUser,
    *,
    from_status: KnowledgeDocumentStatus | None,
    action: str,
    note: str | None = None,
) -> None:
    session.add(
        KnowledgeDocumentApprovalEvent(
            org_id=doc.org_id,
            document_id=doc.id,
            actor_id=current_user.id,
            from_status=from_status.value if from_status else None,
            to_status=doc.status.value,
            action=action,
            note=note.strip() if note and note.strip() else None,
        )
    )

def _require_transition(
    doc: KnowledgeDocument,
    allowed: set[KnowledgeDocumentStatus],
    *,
    action: str,
) -> KnowledgeDocumentStatus:
    previous = doc.status
    if previous not in allowed:
        allowed_values = ", ".join(sorted(item.value for item in allowed))
        raise ApiError(409, "INVALID_LIFECYCLE_TRANSITION", f"Cannot {action} a {previous.value} document. Allowed from: {allowed_values}.")
    return previous

def _separation_of_duties_enabled() -> bool:
    return bool(get_settings().knowledge_separation_of_duties)

async def submit_document_for_review(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction | None = None,
) -> KnowledgeDocumentRead:
    _assert_can_manage_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    previous = _require_transition(doc, SUBMIT_STATUSES, action="submit")
    now = datetime.now(timezone.utc)
    doc.status = KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW
    doc.submitted_by = current_user.id
    doc.submitted_at = now
    doc.reviewed_by = None
    doc.reviewed_at = None
    doc.rejection_reason = None
    if payload and payload.effective_date is not None:
        doc.effective_date = payload.effective_date
    if payload and payload.expiry_date is not None:
        doc.expiry_date = payload.expiry_date
    await _log_approval_event(session, doc, current_user, from_status=previous, action="submit", note=payload.note if payload else None)
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)

async def approve_document(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction | None = None,
) -> KnowledgeDocumentRead:
    _assert_can_review_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    previous = _require_transition(doc, APPROVE_STATUSES, action="approve")
    if _separation_of_duties_enabled() and doc.submitted_by == current_user.id:
        raise ApiError(409, "SEPARATION_OF_DUTIES", "The submitter cannot approve this document.")
    if payload and payload.effective_date is not None:
        doc.effective_date = payload.effective_date
    if payload and payload.expiry_date is not None:
        doc.expiry_date = payload.expiry_date
    if doc.effective_date is None:
        raise ApiError(400, "VALIDATION_ERROR", "Approved documents require an effective date.")
    now = datetime.now(timezone.utc)
    doc.status = KnowledgeDocumentStatus.APPROVED
    doc.reviewed_by = current_user.id
    doc.reviewed_at = now
    doc.approved_by = current_user.id
    doc.approved_at = now
    doc.rejection_reason = None
    if doc.active_version_id:
        version = (
            await session.execute(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == doc.active_version_id))
        ).scalar_one_or_none()
        if version is not None:
            version.approved_by = current_user.id
            version.approved_at = now
    await _log_approval_event(session, doc, current_user, from_status=previous, action="approve", note=payload.note if payload else None)
    await session.flush()
    _invalidate_knowledge_answer_cache(current_user.org_id)
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)

async def reject_document(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction,
) -> KnowledgeDocumentRead:
    _assert_can_review_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    previous = _require_transition(doc, REJECT_STATUSES, action="reject")
    reason = (payload.rejection_reason or payload.note or "").strip()
    if not reason:
        raise ApiError(400, "VALIDATION_ERROR", "A rejection reason is required.")
    now = datetime.now(timezone.utc)
    doc.status = KnowledgeDocumentStatus.REJECTED
    doc.reviewed_by = current_user.id
    doc.reviewed_at = now
    doc.rejection_reason = reason
    doc.approved_by = None
    doc.approved_at = None
    await _log_approval_event(session, doc, current_user, from_status=previous, action="reject", note=reason)
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)

async def return_document_to_draft(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction | None = None,
) -> KnowledgeDocumentRead:
    _assert_can_manage_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    previous = _require_transition(doc, RETURN_TO_DRAFT_STATUSES, action="return to draft")
    doc.status = KnowledgeDocumentStatus.DRAFT
    doc.reviewed_by = None
    doc.reviewed_at = None
    doc.approved_by = None
    doc.approved_at = None
    await _log_approval_event(session, doc, current_user, from_status=previous, action="return_to_draft", note=payload.note if payload else None)
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)

async def archive_document(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction | None = None,
) -> KnowledgeDocumentRead:
    _assert_can_manage_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    previous = _require_transition(doc, ARCHIVE_STATUSES, action="archive")
    doc.status = KnowledgeDocumentStatus.ARCHIVED
    await _log_approval_event(session, doc, current_user, from_status=previous, action="archive", note=payload.note if payload else None)
    await session.flush()
    _invalidate_knowledge_answer_cache(current_user.org_id)
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)

async def restore_document(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction | None = None,
) -> KnowledgeDocumentRead:
    _assert_can_manage_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    previous = _require_transition(doc, RESTORE_STATUSES, action="restore")
    doc.status = KnowledgeDocumentStatus.DRAFT
    await _log_approval_event(session, doc, current_user, from_status=previous, action="restore", note=payload.note if payload else None)
    await session.flush()
    folder = (await session.execute(select(KnowledgeFolder).where(KnowledgeFolder.id == doc.folder_id))).scalar_one()
    return await _to_document_read(session, doc, folder)

async def list_document_approval_history(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
) -> list[KnowledgeDocumentApprovalEventRead]:
    _assert_can_manage_approval(current_user)
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    rows = list(
        (
            await session.execute(
                select(KnowledgeDocumentApprovalEvent)
                .where(
                    KnowledgeDocumentApprovalEvent.org_id == current_user.org_id,
                    KnowledgeDocumentApprovalEvent.document_id == doc.id,
                )
                .order_by(KnowledgeDocumentApprovalEvent.created_at.asc())
            )
        ).scalars()
    )
    names = await _batch_user_display_names(session, {row.actor_id for row in rows if row.actor_id})
    return [
        KnowledgeDocumentApprovalEventRead(
            id=row.id,
            document_id=row.document_id,
            actor_id=row.actor_id,
            actor_name=names.get(row.actor_id) if row.actor_id else None,
            from_status=row.from_status,
            to_status=row.to_status,
            action=row.action,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]

async def delete_document(session: AsyncSession, current_user: CurrentUser, document_id: UUID) -> None:
    doc = await _get_document_or_404(session, current_user.org_id, document_id)
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "You cannot delete knowledge documents.")
    if not can_access_visibility(current_user.role, doc.visibility):
        raise ApiError(403, "FORBIDDEN", "You cannot delete this document.")
    doc.deleted_at = datetime.now(timezone.utc)
    _invalidate_knowledge_answer_cache(current_user.org_id)

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
                supersedes_version_id=version.supersedes_version_id,
                superseded_by_version_id=version.superseded_by_version_id,
                uploaded_at=version.uploaded_at,
                uploaded_by_name=await _user_display_name(session, version.uploaded_by),
                approved_by_name=await _user_display_name(session, version.approved_by) if version.approved_by else None,
                approved_at=version.approved_at,
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

async def _ensure_document_timestamps(session: AsyncSession, doc: KnowledgeDocument) -> None:
    state = sa_inspect(doc)
    missing = [
        name
        for name in ("created_at", "updated_at")
        if not isinstance(state.attrs[name].loaded_value, datetime)
    ]
    if missing:
        await session.refresh(doc, attribute_names=missing)

def _build_document_read(
    doc: KnowledgeDocument,
    folder: KnowledgeFolder,
    *,
    chunk_count: int,
    citation_count: int,
    preview: list[str],
    chunks: list[KnowledgeChunkRead],
    approved_by_name: str | None,
    org_id: UUID | None = None,
    extraction_quality_score: int | None = None,
    extraction_warnings: list[str] | None = None,
    extraction_score_breakdown: KnowledgeExtractionScoreBreakdown | None = None,
    library_analytics: KnowledgeLibraryAnalyticsRead | None = None,
    ocr_needed: bool = False,
    reindex_recommended: bool = False,
) -> KnowledgeDocumentRead:
    readiness = assess_retrieval_readiness(doc, org_id=org_id or doc.org_id)
    read = KnowledgeDocumentRead(
        id=doc.id,
        folder_id=doc.folder_id,
        active_version_id=doc.active_version_id,
        folder_name=folder.name,
        folder_kind=folder.folder_kind.value,
        title=doc.title,
        source_type=doc.source_type.value,
        version=doc.version,
        visibility=doc.visibility.value,
        status=doc.status.value,
        owner_approver=doc.owner_approver,
        effective_date=doc.effective_date,
        expiry_date=doc.expiry_date,
        created_by=doc.created_by,
        submitted_by=doc.submitted_by,
        submitted_at=doc.submitted_at,
        reviewed_by=doc.reviewed_by,
        reviewed_at=doc.reviewed_at,
        approved_by=doc.approved_by,
        file_name=doc.file_name,
        file_mime_type=doc.file_mime_type,
        file_url=doc.file_url,
        processing_status=doc.processing_status.value,
        processing_error=doc.processing_error,
        indexing_status=doc.indexing_status.value,
        preview=preview,
        workflow_state=_compute_workflow_state(doc),
        retrieval_ready=readiness.is_ready,
        retrieval_readiness_reason=readiness.reason,
        retrieval_action=readiness.action,
        quality_score=_compute_quality_score(doc, chunk_count, citation_count),
        quality_warnings=list(extraction_warnings or []),
        extraction_quality_score=extraction_quality_score,
        extraction_score_breakdown=extraction_score_breakdown,
        library_analytics=library_analytics,
        ocr_needed=ocr_needed,
        reindex_recommended=reindex_recommended,
        chunk_count=chunk_count,
        citation_count=citation_count,
        approved_by_name=approved_by_name,
        approved_at=doc.approved_at,
        rejection_reason=doc.rejection_reason,
        executive_summary=getattr(doc, "executive_summary", None),
        key_procedures=list(getattr(doc, "key_procedures", None) or []),
        important_warnings=list(getattr(doc, "important_warnings", None) or []),
        affected_departments=list(getattr(doc, "affected_departments", None) or []),
        related_document_ids=list(getattr(doc, "related_document_ids", None) or []),
        summary_generated_at=getattr(doc, "summary_generated_at", None),
        chunks=chunks,
        created_at=_loaded_datetime(doc, "created_at"),
        updated_at=_loaded_datetime(doc, "updated_at"),
    )
    from app.services.knowledge.ingestion import _post_index_quality_warnings

    post_warnings = _post_index_quality_warnings(read)
    if post_warnings:
        merged = list(dict.fromkeys([*read.quality_warnings, *post_warnings]))
        return read.model_copy(update={"quality_warnings": merged})
    return read

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
    await _ensure_document_timestamps(session, doc)
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
    diagnostics = await _load_active_extraction_diagnostics(session, doc)
    extraction_score, extraction_warnings, ocr_needed, reindex_recommended, score_breakdown, library_analytics = (
        _extraction_quality_from_diagnostics(diagnostics)
    )
    intelligence_by_index = _chunk_intelligence_map(diagnostics)
    total_chunks = len(all_chunks)
    chunk_reads = []
    for index, chunk in enumerate(all_chunks):
        prev_id = all_chunks[index - 1].id if index > 0 else None
        next_id = all_chunks[index + 1].id if index < total_chunks - 1 else None
        chunk_reads.append(
            _chunk_to_read(
                chunk,
                doc,
                folder,
                intelligence=intelligence_by_index.get(chunk.chunk_index),
                previous_chunk_id=prev_id,
                next_chunk_id=next_id,
                total_chunks=total_chunks,
            )
        )
    return _build_document_read(
        doc,
        folder,
        chunk_count=len(all_chunks),
        citation_count=citation_count,
        preview=preview,
        chunks=chunk_reads,
        approved_by_name=approved_by_name,
        extraction_quality_score=extraction_score,
        extraction_warnings=extraction_warnings,
        extraction_score_breakdown=score_breakdown,
        library_analytics=library_analytics,
        ocr_needed=ocr_needed,
        reindex_recommended=reindex_recommended,
    )

def _chunk_to_read(
    chunk: KnowledgeDocumentChunk,
    doc: KnowledgeDocument,
    folder: KnowledgeFolder,
    *,
    intelligence: dict[str, object] | None = None,
    previous_chunk_id: UUID | None = None,
    next_chunk_id: UUID | None = None,
    total_chunks: int | None = None,
) -> KnowledgeChunkRead:
    from app.services.knowledge.ingestion import _decode_section_path

    heading_level, section_path = _decode_section_path(chunk.section_path)
    chunk_type = chunk.chunk_type or "text"
    intel = intelligence or {}
    contains_table = bool(intel.get("contains_table")) or chunk_type == "table"
    return KnowledgeChunkRead(
        id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        total_chunks=total_chunks,
        previous_chunk_id=previous_chunk_id,
        next_chunk_id=next_chunk_id,
        section_title=chunk.section_title,
        section_path=section_path,
        heading_level=heading_level,
        page_number=chunk.page_number,
        chunk_text=(chunk.chunk_text or chunk.content or "").strip(),
        token_count=chunk.token_count,
        chunk_summary=str(intel.get("chunk_summary") or "") or None,
        chunk_type=chunk_type,
        is_table=contains_table,
        contains_procedure=bool(intel.get("contains_procedure")),
        contains_warning=bool(intel.get("contains_warning")),
        contains_decision=bool(intel.get("contains_decision")),
        contains_checklist=bool(intel.get("contains_checklist")),
        contains_table=contains_table,
        contains_roles=bool(intel.get("contains_roles")),
        contains_dates=bool(intel.get("contains_dates")),
        source_type=doc.source_type.value,
        folder_name=folder.name,
        project=doc.project,
        department=doc.department,
        effective_date=doc.effective_date,
        owner_approver=doc.owner_approver,
    )

def _extraction_quality_from_diagnostics(
    diagnostics: dict[str, object] | None,
) -> tuple[
    int | None,
    list[str],
    bool,
    bool,
    KnowledgeExtractionScoreBreakdown | None,
    KnowledgeLibraryAnalyticsRead | None,
]:
    if not diagnostics:
        return None, [], False, False, None, None
    warnings = [str(item) for item in diagnostics.get("warnings", []) if str(item).strip()]
    for duplicate in diagnostics.get("duplicate_warnings", []) or []:
        if isinstance(duplicate, dict) and duplicate.get("message"):
            warnings.append(str(duplicate["message"]))
    score = diagnostics.get("quality_score")
    extraction_score = int(score) if isinstance(score, int) else None
    ocr_needed = bool(diagnostics.get("ocr_needed"))
    reindex_recommended = bool(diagnostics.get("reindex_recommended"))
    breakdown_raw = diagnostics.get("score_breakdown")
    breakdown = (
        KnowledgeExtractionScoreBreakdown(**breakdown_raw)
        if isinstance(breakdown_raw, dict)
        else None
    )
    analytics_raw = diagnostics.get("library_analytics")
    analytics = (
        KnowledgeLibraryAnalyticsRead(**analytics_raw)
        if isinstance(analytics_raw, dict)
        else None
    )
    return extraction_score, warnings, ocr_needed, reindex_recommended, breakdown, analytics

def _chunk_intelligence_map(diagnostics: dict[str, object] | None) -> dict[int, dict[str, object]]:
    if not diagnostics:
        return {}
    rows = diagnostics.get("chunk_intelligence")
    if not isinstance(rows, list):
        return {}
    mapped: dict[int, dict[str, object]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("chunk_index"), int):
            mapped[int(row["chunk_index"])] = row
    return mapped

async def _load_active_extraction_diagnostics(
    session: AsyncSession,
    doc: KnowledgeDocument,
) -> dict[str, object] | None:
    if not doc.active_version_id:
        return None
    extraction = (
        await session.execute(
            select(KnowledgeDocumentExtraction).where(
                KnowledgeDocumentExtraction.version_id == doc.active_version_id
            )
        )
    ).scalar_one_or_none()
    if extraction is None or not extraction.diagnostics:
        return None
    diagnostics = dict(extraction.diagnostics)
    if extraction.quality_score is not None:
        diagnostics.setdefault("quality_score", extraction.quality_score)
    return diagnostics

def _compute_workflow_state(doc: KnowledgeDocument) -> str:
    if doc.status in {
        KnowledgeDocumentStatus.DRAFT,
        KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW,
        KnowledgeDocumentStatus.REJECTED,
    }:
        return "needs_review"
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        return "archived"
    if doc.status == KnowledgeDocumentStatus.NEEDS_REINDEX:
        return "needs_reindex"
    if doc.status == KnowledgeDocumentStatus.EXPIRED:
        return "expired"
    if _is_document_expired(doc):
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
        import app.services.knowledge as knowledge_services

        query_embedding = (await knowledge_services._embed_texts([semantic_query]))[0]
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
