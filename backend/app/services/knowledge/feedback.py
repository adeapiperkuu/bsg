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
    KNOWLEDGE_AGENT_NAME,
)



# --- feedback (Phase 8) ---

POSITIVE_FEEDBACK_REASONS = frozenset({"accurate", "helpful", "clear", "good_sources", "complete"})

NEGATIVE_FEEDBACK_REASONS = frozenset(
    {
        "incorrect",
        "missing_knowledge",
        "weak_sources",
        "outdated",
        "unclear",
        "incomplete",
        "unsafe_for_client",
        "citation_problem",
        "too_slow",
        "other",
    }
)

async def record_knowledge_feedback(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    query_id: UUID,
    rating: str,
    comment: str | None = None,
    feedback_reason: str | None = None,
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
    allowed_reasons = POSITIVE_FEEDBACK_REASONS if feedback_rating == KnowledgeFeedbackRating.UP else NEGATIVE_FEEDBACK_REASONS
    normalized_reason = feedback_reason.strip().lower() if feedback_reason and feedback_reason.strip() else None
    if normalized_reason and normalized_reason not in allowed_reasons:
        normalized_reason = "other"
    retrieval_params = agent_query.retrieval_params if isinstance(agent_query.retrieval_params, dict) else {}
    raw_sources = retrieval_params.get("sources")
    selected_source_ids = [
        str(item.get("chunk_id") or item.get("document_id"))
        for item in raw_sources
        if isinstance(item, dict) and (item.get("chunk_id") or item.get("document_id"))
    ] if isinstance(raw_sources, list) else []
    raw_confidence = retrieval_params.get("confidence_score")
    answer_confidence = (
        float(raw_confidence)
        if isinstance(raw_confidence, (int, float))
        else None
    )
    query_type = str(retrieval_params.get("query_type") or "") or None

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
        existing.feedback_reason = normalized_reason
        existing.answer_confidence = answer_confidence
        existing.query_type = query_type
        existing.selected_source_ids = selected_source_ids
        feedback = existing
    else:
        feedback = KnowledgeQueryFeedback(
            org_id=current_user.org_id,
            agent_query_id=query_id,
            user_id=current_user.id,
            rating=feedback_rating,
            comment=normalized_comment,
            feedback_reason=normalized_reason,
            answer_confidence=answer_confidence,
            query_type=query_type,
            selected_source_ids=selected_source_ids,
        )
        session.add(feedback)
    await session.flush()

    if feedback_rating == KnowledgeFeedbackRating.DOWN:
        logger.info(
            "knowledge_query_downvote query_id=%s user_id=%s retrieval_params=%s comment=%r reason=%r",
            query_id,
            current_user.id,
            agent_query.retrieval_params,
            normalized_comment,
            normalized_reason,
        )

    return KnowledgeFeedbackRead(
        id=feedback.id or uuid4(),
        query_id=query_id,
        rating=feedback.rating.value,
        comment=feedback.comment,
        feedback_reason=feedback.feedback_reason,
        created_at=feedback.created_at or datetime.now(timezone.utc),
    )
