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



# --- permissions (Phase 8) ---

def can_access_visibility(role: AppRole, visibility: KnowledgeVisibility) -> bool:
    if role == AppRole.SUPER_ADMIN:
        return True
    if role == AppRole.BSG_LEADERSHIP:
        return visibility in {
            KnowledgeVisibility.INTERNAL_ONLY,
            KnowledgeVisibility.LEADERSHIP_ONLY,
            KnowledgeVisibility.RESTRICTED,
            KnowledgeVisibility.CLIENT_SAFE,
        }
    if role == AppRole.DELIVERY_MANAGER:
        return visibility in {KnowledgeVisibility.INTERNAL_ONLY, KnowledgeVisibility.CLIENT_SAFE}
    if role == AppRole.CLIENT:
        return visibility == KnowledgeVisibility.CLIENT_SAFE
    return False

def visibility_values_for_role(role: AppRole) -> list[KnowledgeVisibility] | None:
    """Return explicit visibility values for SQL filters, or None when unrestricted (super_admin)."""
    if role == AppRole.SUPER_ADMIN:
        return None
    if role == AppRole.BSG_LEADERSHIP:
        return [
            KnowledgeVisibility.INTERNAL_ONLY,
            KnowledgeVisibility.LEADERSHIP_ONLY,
            KnowledgeVisibility.RESTRICTED,
            KnowledgeVisibility.CLIENT_SAFE,
        ]
    if role == AppRole.DELIVERY_MANAGER:
        return [KnowledgeVisibility.INTERNAL_ONLY, KnowledgeVisibility.CLIENT_SAFE]
    if role == AppRole.CLIENT:
        return [KnowledgeVisibility.CLIENT_SAFE]
    return []

def _knowledge_permissions_for_role(role: AppRole) -> KnowledgePermissionsRead:
    allowed = {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
    leadership = {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}
    return KnowledgePermissionsRead(
        can_upload=role in allowed,
        can_manage_eval=role in leadership,
        can_adjust_retrieval_scope=role in leadership,
        can_review_approvals=role in leadership,
    )
