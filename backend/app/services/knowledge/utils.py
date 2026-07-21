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


# --- utils (Phase 8) ---

KNOWLEDGE_AGENT_NAME = "operational_knowledge_agent"

PROMPT_STRATEGY_VERSION = "knowledge_qa_phase5"

CONVERSATION_HISTORY_MAX_TURNS = 6

CONVERSATION_HISTORY_TURN_CHARS = 2000

def _is_missing_schema_error(exc: BaseException) -> bool:
    if isinstance(exc, ProgrammingError):
        message = str(exc).lower()
        return "does not exist" in message
    orig = getattr(exc, "orig", None)
    if orig is not None:
        name = type(orig).__name__.lower()
        return "undefinedtable" in name or "undefinedcolumn" in name
    return False

TEXT_EXTENSIONS = {".txt", ".md"}

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

METADATA_BOOST_MAX = 0.08

LOW_CONFIDENCE_THRESHOLD = 0.5

CLIENT_SAFE_BLOCKLIST_PATTERNS = (
    re.compile(r"\binternal[-\s]?only\b", re.IGNORECASE),
    re.compile(r"\bconfidential\b", re.IGNORECASE),
    re.compile(r"\broot cause\b", re.IGNORECASE),
    re.compile(r"\bstaffing\b|\bheadcount\b|\bfte\b", re.IGNORECASE),
    re.compile(r"\bmargin\b|\brevenue\b|\bbudget\b|\bcost\b", re.IGNORECASE),
    re.compile(r"\brisk register\b|\bgovernance\b", re.IGNORECASE),
)

DEFAULT_MAX_SOURCES = 3

DEFAULT_MAX_CANDIDATES = 20

KNOWLEDGE_ANSWER_CACHE_TTL_S = 300

EXTRACTION_MIN_CHARS = 200

EXTRACTION_MIN_CHARS_PER_PAGE = 80

EXTRACTION_MIN_CHUNKS = 2

SECTION_LARGE_TOKEN_THRESHOLD = 1200

OPERATIONAL_KEYWORD_TERMS = (
    "sop",
    "procedure",
    "policy",
    "escalation",
    "approval",
    "workflow",
    "onboarding",
    "training",
    "milestone",
    "quality",
    "compliance",
    "standard",
    "checklist",
    "runbook",
    "playbook",
    "incident",
    "resolution",
    "guidance",
    "process",
)

SOP_STALE_DAYS = 365

UPLOAD_APPROVED_MIN_METADATA_SCORE = 4  # out of 6 metadata criteria before indexing as Approved

QUERY_TYPES = {
    "factual",
    "procedural",
    "broad_summary",
    "troubleshooting",
    "historical",
    "comparative",
    "project_specific",
    "policy_or_compliance",
}

HISTORY_SOURCE_TYPES = {KnowledgeSourceType.ESCALATION_NOTE, KnowledgeSourceType.LESSON_LEARNED}

CURRENT_POLICY_SOURCE_TYPES = {
    KnowledgeSourceType.SOP,
    KnowledgeSourceType.GUIDE,
    KnowledgeSourceType.TRAINING_DOCUMENT,
}

IDENTIFIER_EXACT_BOOST_MAX = 0.18

PHRASE_MATCH_BOOST_MAX = 0.06

SOURCE_TYPE_BOOST_MAX = 0.08

QUERY_TYPE_BOOST_MAX = 0.1

ENTITY_MATCH_BOOST_MAX = 0.16

VERSION_PREFERENCE_MAX = 0.07

DUPLICATE_PENALTY_MAX = 0.18

_EMBED_CACHE_TTL_S = 300      # 5 minutes

_EMBED_CACHE_MAX = 1000       # max entries before eviction

_embed_cache: dict[tuple[str, str], tuple[list[float], float]] = {}

def _knowledge_pkg():
    """Return the knowledge package module (supports test monkeypatches on package attrs)."""
    import app.services.knowledge as knowledge_services

    return knowledge_services


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

_knowledge_answer_cache: dict[tuple[str, ...], tuple[float, dict[str, object]]] = {}

@dataclass
class _AskTimings:
    """Per-phase latency markers for knowledge ask requests."""

    def __init__(self) -> None:
        self._start = perf_counter()
        self._marks: dict[str, float] = {}

    def mark(self, name: str) -> None:
        self._marks[name] = round((perf_counter() - self._start) * 1000, 1)

    def to_dict(self) -> dict[str, float]:
        return dict(self._marks)

def _invalidate_knowledge_answer_cache(org_id: UUID) -> None:
    org_key = str(org_id)
    for key in list(_knowledge_answer_cache):
        if key[0] == org_key:
            del _knowledge_answer_cache[key]

def _knowledge_scope_fingerprint(eligible_docs: list[KnowledgeDocument]) -> str:
    parts = sorted(
        f"{doc.id}:{doc.version}:{_loaded_datetime(doc, 'updated_at').isoformat()}"
        for doc in eligible_docs
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

def _knowledge_cache_key(
    org_id: UUID,
    query_text: str,
    *,
    answer_mode: str,
    scope_hash: str,
    include_histories: bool,
    project: str | None,
    department: str | None,
    folder_id: UUID | None,
    source_type: str | None,
) -> tuple[str, ...]:
    return (
        str(org_id),
        query_text.strip().lower(),
        answer_mode,
        scope_hash,
        str(include_histories),
        (project or "").strip().lower(),
        (department or "").strip().lower(),
        str(folder_id) if folder_id else "",
        (source_type or "").strip().lower(),
    )

def _get_knowledge_answer_cache(key: tuple[str, ...]) -> dict[str, object] | None:
    entry = _knowledge_answer_cache.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if time.monotonic() > expires_at:
        _knowledge_answer_cache.pop(key, None)
        return None
    return payload

def _set_knowledge_answer_cache(key: tuple[str, ...], payload: dict[str, object]) -> None:
    _knowledge_answer_cache[key] = (time.monotonic() + KNOWLEDGE_ANSWER_CACHE_TTL_S, payload)

def _needs_structured_operational_context(query_text: str, *, explicit_project: str | None = None) -> bool:
    if explicit_project:
        return True
    lower = query_text.lower()
    operational_terms = (
        "project",
        "status",
        "escalation",
        "quality",
        "bottleneck",
        "csat",
        "delivery",
        "utilization",
        "milestone",
        "throughput",
    )
    return any(term in lower for term in operational_terms)

PROMPT_INJECTION_REWRITE_PATTERNS = (
    re.compile(r"\bignore (all |any |the )?(previous|prior|above|system|developer) instructions?\b", re.IGNORECASE),
    re.compile(r"\bdisregard (all |any |the )?(previous|prior|above|system|developer) instructions?\b", re.IGNORECASE),
    re.compile(r"\b(system|developer) (prompt|message|instructions?)\b", re.IGNORECASE),
    re.compile(r"\breveal\b.*\b(prompt|secret|api key|token|credentials?)\b", re.IGNORECASE),
    re.compile(r"\byou are now\b|\bact as\b|\broleplay as\b", re.IGNORECASE),
)

def _neutralize_rewrite_context(text_value: str) -> str:
    safe_lines: list[str] = []
    for raw_line in text_value.splitlines():
        line = raw_line.strip()
        if line and any(pattern.search(line) for pattern in PROMPT_INJECTION_REWRITE_PATTERNS):
            safe_lines.append("[Redacted prompt-injection instruction]")
        else:
            safe_lines.append(raw_line)
    return "\n".join(safe_lines)

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
    section_path: str | None = None
    chunk_type: str = "text"

@dataclass
class RetrievalResult:
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]]
    doc_map: dict[UUID, KnowledgeDocument]
    folders_map: dict[UUID, KnowledgeFolder]
    retrieval_query: str
    has_embeddings: bool
    eligible_docs: list[KnowledgeDocument]
    vector_scores: dict[UUID, float]
    keyword_scores: dict[UUID, float]
    top_score: float
    empty_eligible_reason: str | None = None
    timings: dict[str, float] | None = None
    scope_hash: str | None = None
    query_type: str = "factual"
    normalized_query: str = ""
    fallback_level: int = 0
    applied_filters: dict[str, object] | None = None
    candidate_count: int = 0
    vector_candidate_count: int = 0
    keyword_candidate_count: int = 0
    candidates_after_deduplication: int = 0
    score_breakdowns: dict[UUID, dict[str, float]] | None = None
    rejected_reasons: dict[str, list[str]] | None = None
    rewrite_diagnostics: dict[str, object] | None = None
    history_diagnostics: dict[str, object] | None = None

def _sse(data: dict[str, object]) -> str:
    """Format a dict as a single SSE line."""
    import json as _json
    return f"data: {_json.dumps(data, default=str)}\n\n"

def _prompt_size_diagnostics(
    *,
    query_text: str,
    context_chunks: list[dict[str, object]],
    structured_context: str,
    history: list[KnowledgeConversationTurn],
) -> dict[str, object]:
    evidence_chars = sum(len(str(chunk.get("text") or "")) for chunk in context_chunks)
    return {
        "strategy_version": PROMPT_STRATEGY_VERSION,
        "query_chars": len(query_text),
        "history_turns": len(history),
        "history_chars": sum(len(turn.content) for turn in history),
        "source_blocks": len(context_chunks),
        "evidence_chars": evidence_chars,
        "structured_context_chars": len(structured_context or ""),
        "estimated_total_chars": len(query_text)
        + evidence_chars
        + len(structured_context or "")
        + sum(len(turn.content) for turn in history),
    }

def _loaded_datetime(doc: KnowledgeDocument, attr: str) -> datetime:
    """Read a timestamp without triggering async lazy-load (MissingGreenlet)."""
    attr_state = sa_inspect(doc).attrs[attr]
    value = attr_state.loaded_value
    if isinstance(value, datetime):
        return value
    history = attr_state.history
    if history.added:
        return history.added[0]
    if history.unchanged:
        return history.unchanged[0]
    return datetime.now(timezone.utc)

def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    # Keep this independent of ingestion._clean_text to avoid circular imports.
    cleaned = re.sub(r"\s+", " ", value.replace("\x00", " ")).strip()
    return cleaned or None

_FOLLOW_UP_PRONOUN_RE = re.compile(
    r"\b(it|its|it's|this|that|these|those|they|them|their|there|above|previous|same)\b",
    re.IGNORECASE,
)

def _normalize_query_text(query_text: str) -> str:
    return re.sub(r"\s+", " ", query_text.strip().lower())

def _chunk_text(chunk: KnowledgeDocumentChunk | _VectorChunk) -> str:
    return (chunk.chunk_text or chunk.content or "").strip()

def _chunk_identity(chunk: KnowledgeDocumentChunk | _VectorChunk) -> str:
    text_value = _chunk_text(chunk).lower()
    return hashlib.sha256(re.sub(r"\s+", " ", text_value).encode()).hexdigest()[:16]

def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

def _tokenize_search_text(text_value: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9]+", text_value.lower()) if len(term) > 1]

def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):g}"

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
