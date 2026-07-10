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
    NO_APPROVED_ANSWER,
)



# --- gaps (Phase 8) ---

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
    answer_mode: str = "internal",
    project: str | None = None,
    department: str | None = None,
) -> KnowledgeAskRead:
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
        latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        retrieval_params=retrieval_params,
    )
    session.add(agent_query)
    await session.flush()
    return KnowledgeAskRead(
        answer_text=NO_APPROVED_ANSWER,
        next_step="Upload or approve a related document if this answer is needed.",
        confidence_score=0.0,
        confidence_band="very_low",
        confidence_reasons=confidence_reasons,
        structured_answer=None,
        query_id=agent_query.id,
        model_used=None,
    )
