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

from app.services.knowledge.utils import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_SOURCES,
)



# --- settings (Phase 8) ---

async def get_retrieval_settings(session: AsyncSession, org_id: UUID) -> KnowledgeRetrievalSettingsRead:
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT to_jsonb(knowledge_retrieval_settings) AS data
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
    data = dict(row.get("data") or {})
    source_types = data.get("source_types")
    folder_ids = data.get("folder_ids")
    return KnowledgeRetrievalSettingsRead(
        only_approved=True,
        include_histories=bool(data.get("include_histories", True)),
        min_relevance=float(data.get("min_relevance") or data.get("min_confidence") or 0.25),
        min_confidence=float(data.get("min_confidence") or 0.25),
        max_sources=int(data.get("max_sources") or DEFAULT_MAX_SOURCES),
        max_candidates=int(data.get("max_candidates") or DEFAULT_MAX_CANDIDATES),
        project=data.get("project"),
        department=data.get("department"),
        source_types=list(source_types or []),
        folder_ids=[UUID(str(item)) for item in (folder_ids or [])],
        recency_preference=float(data.get("recency_preference") or 0.5),
        exact_term_preference=float(data.get("exact_term_preference") or 0.5),
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
    merged_data["only_approved"] = True
    merged = KnowledgeRetrievalSettingsRead(**merged_data)
    try:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_retrieval_settings
                  (org_id, only_approved, include_histories, min_relevance, min_confidence,
                   max_sources, max_candidates, project, department, source_types, folder_ids,
                   recency_preference, exact_term_preference, updated_at)
                VALUES
                  (:org_id, true, :include_histories, :min_relevance, :min_confidence,
                   :max_sources, :max_candidates, :project, :department, CAST(:source_types AS jsonb),
                   CAST(:folder_ids AS jsonb), :recency_preference, :exact_term_preference, now())
                ON CONFLICT (org_id) DO UPDATE SET
                  only_approved = true,
                  include_histories = EXCLUDED.include_histories,
                  min_relevance = EXCLUDED.min_relevance,
                  min_confidence = EXCLUDED.min_confidence,
                  max_sources = EXCLUDED.max_sources,
                  max_candidates = EXCLUDED.max_candidates,
                  project = EXCLUDED.project,
                  department = EXCLUDED.department,
                  source_types = EXCLUDED.source_types,
                  folder_ids = EXCLUDED.folder_ids,
                  recency_preference = EXCLUDED.recency_preference,
                  exact_term_preference = EXCLUDED.exact_term_preference,
                  updated_at = now()
                """
            ),
            {
                "org_id": current_user.org_id,
                "only_approved": merged.only_approved,
                "include_histories": merged.include_histories,
                "min_relevance": merged.min_relevance,
                "min_confidence": merged.min_confidence,
                "max_sources": merged.max_sources,
                "max_candidates": merged.max_candidates,
                "project": merged.project,
                "department": merged.department,
                "source_types": json.dumps(merged.source_types),
                "folder_ids": json.dumps([str(item) for item in merged.folder_ids]),
                "recency_preference": merged.recency_preference,
                "exact_term_preference": merged.exact_term_preference,
            },
        )
    except Exception as exc:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Retrieval settings storage is not available. Apply the latest database migration.") from exc
    return merged
