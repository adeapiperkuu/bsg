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
    CURRENT_POLICY_SOURCE_TYPES,
    DUPLICATE_PENALTY_MAX,
    ENTITY_MATCH_BOOST_MAX,
    EXACT_TERM_BOOST_MAX,
    HISTORY_SOURCE_TYPES,
    HYBRID_KEYWORD_WEIGHT,
    HYBRID_VECTOR_WEIGHT,
    METADATA_BOOST_MAX,
    PHRASE_MATCH_BOOST_MAX,
    QUERY_TYPE_BOOST_MAX,
    RECENCY_BOOST_MAX,
    SOURCE_TYPE_BOOST_MAX,
    VERSION_PREFERENCE_MAX,
    _VectorChunk,
    _chunk_identity,
    _chunk_text,
    _loaded_datetime,
    _tokenize_search_text,
)



# --- ranking (Phase 8) ---

def _chunk_intelligence_for_scoring(chunk: KnowledgeDocumentChunk | _VectorChunk) -> dict[str, object]:
    text_value = _chunk_text(chunk)
    try:
        return analyze_chunk_content(text_value)
    except Exception:
        lower = text_value.lower()
        return {
            "contains_procedure": bool(re.search(r"^\d+[\.)]\s+", text_value, re.MULTILINE) or "step" in lower),
            "contains_warning": any(term in lower for term in ("warning", "risk", "caution")),
            "contains_decision": any(term in lower for term in ("if ", "unless ", "approve", "reject", "decision")),
            "contains_checklist": "checklist" in lower,
            "contains_table": getattr(chunk, "chunk_type", "") == "table",
            "contains_roles": any(term in lower for term in ("manager", "lead", "approver", "reviewer")),
            "contains_dates": bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", text_value)),
            "entities": {},
        }

def _phrase_match_boost(query_text: str, target_text: str) -> float:
    from app.services.knowledge.retrieval import _query_exact_identifiers

    phrases = [item.strip().lower() for item in re.findall(r'"([^"]{3,80})"', query_text)]
    phrases.extend(term.lower() for term in _query_exact_identifiers(query_text) if " " in term)
    if not phrases:
        return 0.0
    unique_phrases = set(phrases)
    target = target_text.lower()
    hits = sum(1 for phrase in unique_phrases if phrase and phrase in target)
    return min(PHRASE_MATCH_BOOST_MAX, (hits / max(len(unique_phrases), 1)) * PHRASE_MATCH_BOOST_MAX)

def _entity_match_boost(query_text: str, doc: KnowledgeDocument, chunk: KnowledgeDocumentChunk | _VectorChunk) -> float:
    from app.services.knowledge.retrieval import _query_exact_identifiers

    identifiers = _query_exact_identifiers(query_text)
    if not identifiers:
        return 0.0
    target = "\n".join(
        [
            doc.title or "",
            doc.version or "",
            doc.project or "",
            doc.department or "",
            chunk.section_title or "",
            _chunk_text(chunk),
        ]
    ).lower()
    target_dash = target.replace(" ", "-")
    hits = sum(
        1
        for term in identifiers
        if term.lower() in target or term.lower().replace(" ", "-") in target_dash
    )
    return min(ENTITY_MATCH_BOOST_MAX, (hits / len(identifiers)) * ENTITY_MATCH_BOOST_MAX)

def _source_type_boost(doc: KnowledgeDocument, folder: KnowledgeFolder | None, query_type: str) -> float:
    if query_type in {"procedural", "policy_or_compliance"} and doc.source_type in CURRENT_POLICY_SOURCE_TYPES:
        return SOURCE_TYPE_BOOST_MAX
    if query_type in {"historical", "troubleshooting"}:
        if doc.source_type in HISTORY_SOURCE_TYPES:
            return SOURCE_TYPE_BOOST_MAX
        if folder and folder.folder_kind == KnowledgeFolderKind.HISTORIES:
            return SOURCE_TYPE_BOOST_MAX
    return 0.0

def _query_type_boost(
    chunk: KnowledgeDocumentChunk | _VectorChunk,
    doc: KnowledgeDocument,
    query_type: str,
) -> float:
    intel = _chunk_intelligence_for_scoring(chunk)
    lower = _chunk_text(chunk).lower()
    boost = 0.0
    if query_type == "procedural":
        if intel.get("contains_procedure"):
            boost += 0.055
        if intel.get("contains_checklist"):
            boost += 0.035
        if doc.source_type == KnowledgeSourceType.SOP:
            boost += 0.03
    elif query_type == "troubleshooting":
        if intel.get("contains_warning"):
            boost += 0.04
        if any(term in lower for term in ("resolution", "resolved", "known issue", "risk", "lesson")):
            boost += 0.06
    elif query_type == "historical":
        if intel.get("contains_dates"):
            boost += 0.035
        if doc.source_type in HISTORY_SOURCE_TYPES:
            boost += 0.06
    elif query_type == "broad_summary":
        if chunk.section_title:
            boost += 0.035
        if intel.get("contains_table") or intel.get("contains_roles"):
            boost += 0.025
    elif query_type == "comparative":
        if any(term in lower for term in ("version", "changed", "new", "old", "previous")):
            boost += 0.07
    elif query_type == "policy_or_compliance":
        if any(term in lower for term in ("policy", "must", "required", "effective", "approved")):
            boost += 0.07
    return min(QUERY_TYPE_BOOST_MAX, boost)

def _version_sort_key(doc: KnowledgeDocument) -> tuple[int, date, datetime]:
    version_text = (doc.version or "").lower()
    numbers = [int(item) for item in re.findall(r"\d+", version_text)]
    weighted_version = 0
    for index, number in enumerate(numbers[:4]):
        weighted_version += number * (100 ** max(0, 3 - index))
    effective = doc.effective_date or date.min
    updated = _loaded_datetime(doc, "approved_at") or _loaded_datetime(doc, "updated_at")
    return weighted_version, effective, updated

def _version_preference_boost(doc: KnowledgeDocument, active_docs: list[KnowledgeDocument]) -> float:
    siblings = [
        item
        for item in active_docs
        if item.id != doc.id
        and item.source_type == doc.source_type
        and (item.title or "").strip().lower() == (doc.title or "").strip().lower()
        and (item.project or "").strip().lower() == (doc.project or "").strip().lower()
        and (item.department or "").strip().lower() == (doc.department or "").strip().lower()
    ]
    if not siblings:
        return 0.0
    best = max([doc, *siblings], key=_version_sort_key)
    return VERSION_PREFERENCE_MAX if best.id == doc.id else -VERSION_PREFERENCE_MAX

def _filter_latest_valid_versions(docs: list[KnowledgeDocument]) -> tuple[list[KnowledgeDocument], list[str]]:
    grouped: dict[tuple[str, str, str, str], list[KnowledgeDocument]] = {}
    for doc in docs:
        key = (
            (doc.title or "").strip().lower(),
            doc.source_type.value,
            (doc.project or "").strip().lower(),
            (doc.department or "").strip().lower(),
        )
        grouped.setdefault(key, []).append(doc)
    selected: list[KnowledgeDocument] = []
    diagnostics: list[str] = []
    for key, group in grouped.items():
        if len(group) == 1:
            selected.extend(group)
            continue
        ranked = sorted(group, key=_version_sort_key, reverse=True)
        selected.append(ranked[0])
        diagnostics.append(
            f"multiple_active_versions:{key[0] or 'untitled'}:{','.join(item.version for item in ranked)}"
        )
    return selected, diagnostics

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
    folders_map: dict[UUID, KnowledgeFolder],
    query_text: str,
    query_type: str = "factual",
    score_breakdowns: dict[UUID, dict[str, float]] | None = None,
) -> list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]]:
    scored: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]] = []
    has_vector = bool(vector_scores)
    active_docs = list(doc_map.values())
    seen_fingerprints: set[str] = set()
    for chunk in candidates:
        doc = doc_map.get(chunk.document_id)
        if doc is None:
            continue
        folder = folders_map.get(doc.folder_id)
        vector_score = max(0.0, vector_scores.get(chunk.id, 0.0))
        keyword_score = max(0.0, keyword_scores.get(chunk.id, 0.0))
        if has_vector:
            combined = (HYBRID_VECTOR_WEIGHT * vector_score) + (
                HYBRID_KEYWORD_WEIGHT * keyword_score
            )
        else:
            combined = keyword_score
        target_text = f"{doc.title}\n{doc.version}\n{doc.project or ''}\n{doc.department or ''}\n{chunk.section_title or ''}\n{_chunk_text(chunk)}"
        exact_boost = _exact_term_boost(
            query_text,
            target_text,
        )
        exact_boost = min(EXACT_TERM_BOOST_MAX, exact_boost)
        phrase_boost = _phrase_match_boost(query_text, target_text)
        metadata_boost = _metadata_match_boost(doc, folder, query_text)
        recency_boost = _recency_boost(doc)
        source_boost = _source_type_boost(doc, folder, query_type)
        query_boost = _query_type_boost(chunk, doc, query_type)
        entity_boost = _entity_match_boost(query_text, doc, chunk)
        version_preference = _version_preference_boost(doc, active_docs)
        fingerprint = _chunk_identity(chunk)
        duplicate_penalty = DUPLICATE_PENALTY_MAX if fingerprint in seen_fingerprints else 0.0
        seen_fingerprints.add(fingerprint)
        combined += (
            exact_boost
            + phrase_boost
            + metadata_boost
            + recency_boost
            + source_boost
            + query_boost
            + entity_boost
            + version_preference
            - duplicate_penalty
        )
        if combined > 0:
            final_score = round(max(0.0, min(1.0, combined)), 4)
            if score_breakdowns is not None:
                score_breakdowns[chunk.id] = {
                    "vector_score": round(vector_score, 4),
                    "keyword_score": round(keyword_score, 4),
                    "exact_term_boost": round(exact_boost, 4),
                    "phrase_match_boost": round(phrase_boost, 4),
                    "metadata_boost": round(metadata_boost, 4),
                    "recency_boost": round(recency_boost, 4),
                    "source_type_boost": round(source_boost, 4),
                    "query_type_boost": round(query_boost, 4),
                    "entity_match_boost": round(entity_boost, 4),
                    "version_preference": round(version_preference, 4),
                    "duplicate_penalty": round(duplicate_penalty, 4),
                    "final_score": final_score,
                }
            scored.append((chunk, final_score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored

def _metadata_match_boost(
    doc: KnowledgeDocument,
    folder: KnowledgeFolder | None,
    query_text: str,
) -> float:
    query_lower = query_text.lower()
    targets = [
        doc.title,
        doc.version,
        doc.owner_approver,
        doc.project or "",
        doc.department or "",
        doc.source_type.value.replace("_", " "),
        doc.status.value if doc.status is not None else "",
        folder.name if folder else "",
    ]
    hits = sum(1 for target in targets if target and target.lower() in query_lower)
    if not hits:
        return 0.0
    return min(METADATA_BOOST_MAX, (hits / max(len(targets), 1)) * METADATA_BOOST_MAX)

def _diversify_ranked_candidates(
    ranked: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]],
    *,
    query_type: str,
    max_sources: int,
    rejected_reasons: dict[str, list[str]] | None = None,
) -> list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]]:
    if query_type not in {"broad_summary", "comparative"}:
        return ranked[:max_sources]
    selected: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]] = []
    by_doc: dict[UUID, int] = {}
    section_keys: set[tuple[UUID, str]] = set()
    fingerprints: set[str] = set()
    per_doc_limit = 2 if query_type == "broad_summary" else 3
    for chunk, score in ranked:
        if len(selected) >= max_sources:
            break
        fingerprint = _chunk_identity(chunk)
        if fingerprint in fingerprints:
            if rejected_reasons is not None:
                rejected_reasons.setdefault(str(chunk.id), []).append("duplicate_fingerprint")
            continue
        section_key = (chunk.document_id, (chunk.section_title or getattr(chunk, "section_path", "") or "").lower())
        if section_key[1] and section_key in section_keys:
            if rejected_reasons is not None:
                rejected_reasons.setdefault(str(chunk.id), []).append("duplicate_section")
            continue
        if by_doc.get(chunk.document_id, 0) >= per_doc_limit:
            if rejected_reasons is not None:
                rejected_reasons.setdefault(str(chunk.id), []).append("document_diversity_limit")
            continue
        selected.append((chunk, score))
        by_doc[chunk.document_id] = by_doc.get(chunk.document_id, 0) + 1
        section_keys.add(section_key)
        fingerprints.add(fingerprint)
    if len(selected) < min(max_sources, 2):
        for item in ranked:
            if len(selected) >= max_sources:
                break
            if item[0].id not in {chunk.id for chunk, _ in selected}:
                selected.append(item)
    return selected

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
        reference = datetime.combine(doc.effective_date, datetime.min.time(), tzinfo=timezone.utc)
    if reference is None:
        return 0.0
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_days = max(0, (datetime.now(timezone.utc) - reference).days)
    return round(RECENCY_BOOST_MAX / (1 + (age_days / 90)), 4)
