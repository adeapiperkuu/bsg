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
    CLIENT_SAFE_BLOCKLIST_PATTERNS,
    NO_APPROVED_ANSWER,
    STRONG_RELEVANCE_THRESHOLD,
    _VectorChunk,
    _tokenize_search_text,
)



# --- grounding (Phase 8) ---

def _ground_generation(
    answer_text: str,
    structured_answer: KnowledgeStructuredAnswer | None,
    context_chunks: list[dict[str, object]],
    structured_context: str,
) -> dict[str, object]:
    evidence_text = "\n".join([str(chunk.get("text", "")) for chunk in context_chunks] + [structured_context])
    evidence_tokens = set(_tokenize_search_text(evidence_text))
    if not evidence_tokens:
        return {
            "grounded": False,
            "support": 0.0,
            "unsupported_claim_count": 1,
            "unsupported_entities": ["no_evidence_text"],
            "citation_validity": {"valid": False, "missing": [], "unknown": []},
            "validator": "deterministic_v2",
        }

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
    citation_validity = _validate_answer_citations(answer_text, context_chunks)
    if not claims:
        return {
            "grounded": bool(citation_validity["valid"]),
            "support": 1.0 if citation_validity["valid"] else 0.75,
            "unsupported_claim_count": 0,
            "unsupported_entities": [],
            "citation_validity": citation_validity,
            "validator": "deterministic_v2",
        }

    supported = 0
    evidence_lower = evidence_text.lower()
    unsupported_claims: list[str] = []
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
        else:
            unsupported_claims.append(normalized_claim[:180])
    support = supported / len(claims)
    unsupported_entities = _unsupported_answer_entities(answer_text, evidence_text)
    entity_penalty = min(0.25, len(unsupported_entities) * 0.05)
    citation_penalty = 0.12 if not citation_validity["valid"] else 0.0
    adjusted_support = max(0.0, support - entity_penalty - citation_penalty)
    return {
        "grounded": adjusted_support >= 0.65,
        "support": round(adjusted_support, 4),
        "claim_support": round(support, 4),
        "unsupported_claim_count": len(unsupported_claims),
        "unsupported_claims": unsupported_claims[:5],
        "unsupported_entities": unsupported_entities[:12],
        "citation_validity": citation_validity,
        "validator": "deterministic_v2",
    }

def _extract_generation_claims(text_value: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text_value).strip()
    if not cleaned:
        return []
    candidates = re.split(r"(?<=[.!?])\s+|(?:^|\s)\d+[\.)]\s+", cleaned)
    return [item.strip(" -") for item in candidates if len(_tokenize_search_text(item)) >= 4]

def _extract_answer_numbers(text_value: str) -> set[str]:
    return {item.lower() for item in re.findall(r"\b\d+(?:\.\d+)?%?\b", text_value)}

def _extract_answer_dates(text_value: str) -> set[str]:
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
        r"\bq[1-4]\s+\d{4}\b",
    ]
    values: set[str] = set()
    for pattern in patterns:
        values.update(item.lower() for item in re.findall(pattern, text_value, flags=re.IGNORECASE))
    return values

def _extract_answer_names(text_value: str) -> set[str]:
    names = set()
    for match in re.findall(r"\b[A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+){1,4}\b", text_value):
        cleaned = match.strip()
        if cleaned.lower() not in {"I could", "Doc"} and not cleaned.startswith("Doc:"):
            names.add(cleaned.lower())
    return names

def _unsupported_answer_entities(answer_text: str, evidence_text: str) -> list[str]:
    evidence_lower = evidence_text.lower()
    unsupported: list[str] = []
    for label, extractor in (
        ("number", _extract_answer_numbers),
        ("date", _extract_answer_dates),
        ("name", _extract_answer_names),
    ):
        for value in sorted(extractor(answer_text)):
            if value and value not in evidence_lower:
                unsupported.append(f"{label}:{value}")
    return unsupported

def _validate_answer_citations(
    answer_text: str,
    context_chunks: list[dict[str, object]],
) -> dict[str, object]:
    cited_titles = [item.strip() for item in re.findall(r"\[Doc:\s*([^\]]+)\]", answer_text, flags=re.IGNORECASE)]
    available = {str(chunk.get("title") or "").strip().lower() for chunk in context_chunks if chunk.get("title")}
    unknown = [title for title in cited_titles if title.lower() not in available]
    return {
        "valid": not unknown,
        "cited_count": len(cited_titles),
        "available_count": len(available),
        "unknown": unknown,
        "missing": [] if cited_titles or not answer_text.strip() or answer_text.strip() == NO_APPROVED_ANSWER else ["no_inline_citation"],
    }

def _validate_client_safe_answer(
    answer_text: str,
    structured_answer: KnowledgeStructuredAnswer | None,
    context_chunks: list[dict[str, object]],
) -> dict[str, object]:
    combined = answer_text
    if structured_answer is not None:
        combined += "\n" + "\n".join(
            [
                structured_answer.policy,
                structured_answer.steps,
                structured_answer.owner,
                structured_answer.evidence,
                structured_answer.next_action,
            ]
        )
    reasons: list[str] = []
    for pattern in CLIENT_SAFE_BLOCKLIST_PATTERNS:
        if pattern.search(combined):
            reasons.append(pattern.pattern)
    unsafe_sources = [
        str(chunk.get("title") or chunk.get("document_id") or "source")
        for chunk in context_chunks
        if str(chunk.get("visibility") or "").lower() != KnowledgeVisibility.CLIENT_SAFE.value
    ]
    if unsafe_sources:
        reasons.append("non_client_safe_source")
    return {
        "valid": not reasons,
        "reasons": reasons[:8],
        "unsafe_sources": unsafe_sources[:8],
        "validator": "client_safe_deterministic_v1",
    }

def _confidence_band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.3:
        return "low"
    return "very_low"

def _compute_answer_confidence(
    *,
    raw_confidence: float,
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]],
    eligible_docs: list[KnowledgeDocument],
    doc_map: dict[UUID, KnowledgeDocument],
    grounding: dict[str, object],
    query_type: str,
    has_structured_context: bool,
    client_safe_result: dict[str, object] | None,
    fallback_level: int,
) -> dict[str, object]:
    retrieval_top = min(matches[0][1], 1.0) if matches else 0.0
    retrieval_avg = min(sum(score for _chunk, score in matches) / len(matches), 1.0) if matches else 0.0
    retrieval_component = round(0.45 * ((retrieval_top * 0.7) + (retrieval_avg * 0.3)), 4)
    grounding_support = float(grounding.get("support") or 0.0)
    grounding_component = round(0.3 * grounding_support, 4)
    ready_docs: list[KnowledgeDocument] = []
    seen_doc_ids: set[UUID] = set()
    for chunk, _score in matches:
        doc = doc_map.get(chunk.document_id)
        if doc is not None and doc.id not in seen_doc_ids:
            ready_docs.append(doc)
            seen_doc_ids.add(doc.id)
    ready_component = 0.15 if ready_docs else 0.0
    if ready_docs and any(doc.effective_date is None for doc in ready_docs):
        ready_component = 0.1
    diversity_component = round(0.1 * min(len({chunk.document_id for chunk, _score in matches}) / 2, 1.0), 4)
    score = retrieval_component + grounding_component + ready_component + diversity_component
    score = min(score, raw_confidence) if raw_confidence > 0 else score
    penalties: dict[str, float] = {}
    if fallback_level:
        penalties["retrieval_fallback"] = 0.06 * fallback_level
    if not bool(grounding.get("grounded")):
        penalties["weak_grounding"] = 0.12
    citation_validity = grounding.get("citation_validity")
    if isinstance(citation_validity, dict) and citation_validity.get("missing"):
        penalties["missing_citation"] = 0.06
    if query_type in {"broad_summary", "comparative"} and len({chunk.document_id for chunk, _score in matches}) < 2:
        penalties["low_source_diversity"] = 0.08
    if client_safe_result is not None and not bool(client_safe_result.get("valid", True)):
        penalties["client_safe_violation"] = 0.35
    if has_structured_context:
        score += 0.03
    score = max(0.0, min(1.0, score - sum(penalties.values())))
    band = _confidence_band(score)
    reasons = _build_confidence_reasons(matches, eligible_docs, doc_map, "")
    reasons.append(f"Grounding support {round(grounding_support * 100)}%")
    if penalties:
        reasons.extend(f"Penalty: {name.replace('_', ' ')}" for name in penalties)
    if band in {"low", "very_low"}:
        reasons.append("This answer may be incomplete. Try deeper search.")
    return {
        "score": round(score, 4),
        "band": band,
        "breakdown": {
            "llm_raw_confidence": round(raw_confidence, 4),
            "retrieval_component": retrieval_component,
            "grounding_component": grounding_component,
            "source_readiness_component": round(ready_component, 4),
            "source_diversity_component": diversity_component,
            "penalties": {key: round(value, 4) for key, value in penalties.items()},
        },
        "reasons": reasons,
    }

def _source_label(source_type: KnowledgeSourceType) -> str:
    return source_type.value.replace("_", " ").title()

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
