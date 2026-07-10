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

from app.services.knowledge.permissions import (
    _knowledge_permissions_for_role,
)
from app.services.knowledge.utils import (
    SOP_STALE_DAYS,
    _loaded_datetime,
)



# --- analytics (Phase 8) ---

BOOTSTRAP_RECENT_DOCUMENT_LIMIT = 30

def _health_counts_from_documents(
    docs: list[KnowledgeDocument],
    *,
    org_id: UUID | None = None,
) -> KnowledgeLibraryHealthCountsRead:
    return compute_library_readiness_counts(docs, org_id=org_id)

def _document_counts_from_documents(docs: list[KnowledgeDocument]) -> KnowledgeDocumentCountsRead:
    by_folder: dict[str, int] = {}
    for doc in docs:
        key = str(doc.folder_id)
        by_folder[key] = by_folder.get(key, 0) + 1
    return KnowledgeDocumentCountsRead(total=len(docs), by_folder_id=by_folder)

async def get_knowledge_bootstrap(
    session: AsyncSession,
    current_user: CurrentUser,
) -> KnowledgeBootstrapRead:
    import app.services.knowledge as knowledge_services

    cross_org = current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}
    if not cross_org:
        await knowledge_services.ensure_knowledge_folders(session, current_user.org_id)
    folders = await knowledge_services.list_knowledge_folders(session, current_user.org_id)
    visible_docs, folder_map = await knowledge_services._list_visible_documents_with_folders(
        session,
        current_user,
        folders_ready=True,
    )
    health = _health_counts_from_documents(visible_docs, org_id=current_user.org_id)
    document_counts = _document_counts_from_documents(visible_docs)
    recent_docs = sorted(visible_docs, key=lambda doc: _loaded_datetime(doc, "updated_at"), reverse=True)[
        :BOOTSTRAP_RECENT_DOCUMENT_LIMIT
    ]
    recent_documents = [
        knowledge_services._to_document_summary_read(doc, folder_map[doc.folder_id])
        for doc in recent_docs
        if doc.folder_id in folder_map
    ]
    folder_tree = [
        KnowledgeFolderTreeNodeRead(
            id=folder.id,
            name=folder.name,
            folder_kind=folder.folder_kind.value,
            display_order=folder.display_order,
            document_count=document_counts.by_folder_id.get(str(folder.id), 0),
        )
        for folder in folders
    ]
    return KnowledgeBootstrapRead(
        folders=[
            KnowledgeFolderRead(
                id=folder.id,
                name=folder.name,
                folder_kind=folder.folder_kind.value,
                display_order=folder.display_order,
            )
            for folder in folders
        ],
        folder_tree=folder_tree,
        recent_documents=recent_documents,
        document_counts=document_counts,
        permissions=_knowledge_permissions_for_role(current_user.role),
        library_health=health,
    )

async def get_knowledge_library_health(
    session: AsyncSession,
    current_user: CurrentUser,
) -> KnowledgeLibraryHealthRead:
    import app.services.knowledge as knowledge_services
    from app.services.knowledge.learning import compute_knowledge_health_score

    visible_docs, _ = await knowledge_services._list_visible_documents_with_folders(session, current_user)
    counts = _health_counts_from_documents(visible_docs, org_id=current_user.org_id)
    health = compute_knowledge_health_score(counts)
    return KnowledgeLibraryHealthRead(
        ready_count=counts.ready_for_retrieval_count,
        ready_for_retrieval_count=counts.ready_for_retrieval_count,
        approved_and_indexed_count=counts.approved_and_indexed_count,
        needs_review_count=counts.needs_review_count,
        expired_count=counts.expired_count,
        needs_reindex_count=counts.needs_reindex_count,
        failed_processing_count=counts.failed_processing_count,
        missing_metadata_count=counts.missing_metadata_count,
        indexing_count=counts.indexing_count,
        draft_count=counts.draft_count,
        archived_count=counts.archived_count,
        approaching_expiry_count=counts.approaching_expiry_count,
        outdated_count=counts.outdated_count,
        health_score=health.score,
        health_band=health.band,
        health_recommendations=health.recommendations,
    )

def _is_document_expired(doc: KnowledgeDocument) -> bool:
    if getattr(doc, "status", None) == KnowledgeDocumentStatus.EXPIRED:
        return True
    expiry_date = getattr(doc, "expiry_date", None)
    if expiry_date is not None and expiry_date < date.today():
        return True
    return (
        doc.source_type == KnowledgeSourceType.SOP
        and doc.status == KnowledgeDocumentStatus.APPROVED
        and doc.approved_at is not None
        and doc.effective_date is None
        and (datetime.now(timezone.utc) - doc.approved_at).days > SOP_STALE_DAYS
    )

def _has_valid_org_ownership(doc: KnowledgeDocument, org_id: UUID | None = None) -> bool:
    if doc.org_id is None:
        return False
    return org_id is None or doc.org_id == org_id

def _is_missing_metadata(doc: KnowledgeDocument) -> bool:
    return not (doc.owner_approver or "").strip() or doc.effective_date is None

def _is_approved_and_indexed(doc: KnowledgeDocument) -> bool:
    return (
        doc.status == KnowledgeDocumentStatus.APPROVED
        and doc.indexing_status == KnowledgeIndexingStatus.INDEXED
    )

@dataclass(frozen=True)
class RetrievalReadinessAssessment:
    is_ready: bool
    reason: str
    action: str | None = None

def assess_retrieval_readiness(
    doc: KnowledgeDocument,
    *,
    org_id: UUID | None = None,
) -> RetrievalReadinessAssessment:
    if not _has_valid_org_ownership(doc, org_id):
        return RetrievalReadinessAssessment(False, "Missing owner", "edit_metadata")
    if doc.status == KnowledgeDocumentStatus.ARCHIVED:
        return RetrievalReadinessAssessment(False, "Needs approval", "approve")
    if doc.status in {
        KnowledgeDocumentStatus.DRAFT,
        KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW,
        KnowledgeDocumentStatus.REJECTED,
    }:
        return RetrievalReadinessAssessment(False, "Needs approval", "approve")
    if doc.status == KnowledgeDocumentStatus.NEEDS_REINDEX:
        return RetrievalReadinessAssessment(False, "Needs re-index", "reindex")
    if doc.status == KnowledgeDocumentStatus.EXPIRED:
        return RetrievalReadinessAssessment(False, "Expired", "edit_metadata")
    if not (doc.owner_approver or "").strip():
        return RetrievalReadinessAssessment(False, "Missing owner", "edit_metadata")
    if _is_document_expired(doc):
        return RetrievalReadinessAssessment(False, "Expired", "edit_metadata")
    if doc.effective_date is None:
        return RetrievalReadinessAssessment(False, "Missing effective date", "edit_metadata")
    if (
        doc.processing_status == KnowledgeProcessingStatus.FAILED
        or doc.indexing_status == KnowledgeIndexingStatus.FAILED
    ):
        return RetrievalReadinessAssessment(False, "Processing failed", "retry_processing")
    if doc.status != KnowledgeDocumentStatus.APPROVED:
        return RetrievalReadinessAssessment(False, "Needs approval", "approve")
    if (
        doc.processing_status != KnowledgeProcessingStatus.READY
        or doc.indexing_status != KnowledgeIndexingStatus.INDEXED
    ):
        return RetrievalReadinessAssessment(False, "Needs re-index", "reindex")
    return RetrievalReadinessAssessment(True, "Ready", None)

def _is_retrieval_ready(doc: KnowledgeDocument, *, org_id: UUID | None = None) -> bool:
    return assess_retrieval_readiness(doc, org_id=org_id).is_ready

def _filter_retrieval_ready_docs(
    docs: list[KnowledgeDocument],
    org_id: UUID,
) -> list[KnowledgeDocument]:
    return [doc for doc in docs if _is_retrieval_ready(doc, org_id=org_id)]

def compute_library_readiness_counts(
    docs: list[KnowledgeDocument],
    *,
    org_id: UUID | None = None,
) -> KnowledgeLibraryHealthCountsRead:
    counts = {
        "ready_for_retrieval": 0,
        "approved_and_indexed": 0,
        "needs_review": 0,
        "expired": 0,
        "needs_reindex": 0,
        "failed_processing": 0,
        "missing_metadata": 0,
        "indexing": 0,
        "draft": 0,
        "archived": 0,
        "approaching_expiry": 0,
        "outdated": 0,
    }
    today = date.today()
    review_cutoff = today - timedelta(days=SOP_STALE_DAYS)
    for doc in docs:
        assessment = assess_retrieval_readiness(doc, org_id=org_id)
        from app.services.knowledge.library import _compute_workflow_state

        workflow_state = _compute_workflow_state(doc)
        if assessment.is_ready:
            counts["ready_for_retrieval"] += 1
        if _is_approved_and_indexed(doc):
            counts["approved_and_indexed"] += 1
        if workflow_state == "needs_review":
            counts["needs_review"] += 1
        elif workflow_state == "expired":
            counts["expired"] += 1
        elif workflow_state == "needs_reindex":
            counts["needs_reindex"] += 1
        elif workflow_state == "archived":
            counts["archived"] += 1
        if doc.status in {
            KnowledgeDocumentStatus.DRAFT,
            KnowledgeDocumentStatus.SUBMITTED_FOR_REVIEW,
            KnowledgeDocumentStatus.REJECTED,
        }:
            counts["draft"] += 1
        if (
            doc.processing_status == KnowledgeProcessingStatus.FAILED
            or doc.indexing_status == KnowledgeIndexingStatus.FAILED
        ):
            counts["failed_processing"] += 1
        if _is_missing_metadata(doc) and doc.status != KnowledgeDocumentStatus.ARCHIVED:
            counts["missing_metadata"] += 1
        if doc.indexing_status == KnowledgeIndexingStatus.INDEXING or doc.processing_status in {
            KnowledgeProcessingStatus.UPLOADED,
            KnowledgeProcessingStatus.EXTRACTING,
            KnowledgeProcessingStatus.EXTRACTED,
            KnowledgeProcessingStatus.CHUNKING,
            KnowledgeProcessingStatus.CHUNKED,
            KnowledgeProcessingStatus.EMBEDDING,
        }:
            counts["indexing"] += 1
        expiry_date = getattr(doc, "expiry_date", None)
        if expiry_date is not None and today <= expiry_date <= today + timedelta(days=30):
            counts["approaching_expiry"] += 1
        if (
            doc.status == KnowledgeDocumentStatus.APPROVED
            and doc.effective_date is not None
            and doc.effective_date < review_cutoff
        ):
            counts["outdated"] += 1
    return KnowledgeLibraryHealthCountsRead(
        ready_count=counts["ready_for_retrieval"],
        ready_for_retrieval_count=counts["ready_for_retrieval"],
        approved_and_indexed_count=counts["approved_and_indexed"],
        needs_review_count=counts["needs_review"],
        expired_count=counts["expired"],
        needs_reindex_count=counts["needs_reindex"],
        failed_processing_count=counts["failed_processing"],
        missing_metadata_count=counts["missing_metadata"],
        indexing_count=counts["indexing"],
        draft_count=counts["draft"],
        archived_count=counts["archived"],
        approaching_expiry_count=counts["approaching_expiry"],
        outdated_count=counts["outdated"],
    )

async def build_library_health(
    session: AsyncSession,
    org_id: UUID,
    documents: list[KnowledgeDocumentRead],
) -> KnowledgeLibraryHealthRead:
    counts = compute_library_readiness_counts(
        [
            KnowledgeDocument(
                id=doc.id,
                org_id=org_id,
                folder_id=doc.folder_id,
                title=doc.title,
                source_type=KnowledgeSourceType(doc.source_type),
                version=doc.version,
                visibility=KnowledgeVisibility(doc.visibility),
                status=KnowledgeDocumentStatus(doc.status),
                owner_approver=doc.owner_approver,
                effective_date=doc.effective_date,
                expiry_date=doc.expiry_date,
                file_name=doc.file_name,
                file_mime_type=doc.file_mime_type,
                processing_status=KnowledgeProcessingStatus(doc.processing_status),
                processing_error=doc.processing_error,
                indexing_status=KnowledgeIndexingStatus(doc.indexing_status),
                approved_at=doc.approved_at,
            )
            for doc in documents
        ],
        org_id=org_id,
    )

    return KnowledgeLibraryHealthRead(
        ready_count=counts.ready_for_retrieval_count,
        ready_for_retrieval_count=counts.ready_for_retrieval_count,
        approved_and_indexed_count=counts.approved_and_indexed_count,
        needs_review_count=counts.needs_review_count,
        expired_count=counts.expired_count,
        needs_reindex_count=counts.needs_reindex_count,
        failed_processing_count=counts.failed_processing_count,
        missing_metadata_count=counts.missing_metadata_count,
        indexing_count=counts.indexing_count,
        draft_count=counts.draft_count,
        archived_count=counts.archived_count,
        approaching_expiry_count=counts.approaching_expiry_count,
        outdated_count=counts.outdated_count,
    )
