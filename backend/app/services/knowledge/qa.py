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

from app.services.knowledge.analytics import (
    assess_retrieval_readiness,
)
from app.services.knowledge.gaps import (
    _persist_empty_ask_response,
)
from app.services.knowledge.grounding import (
    _compute_answer_confidence,
    _confidence_band,
    _ground_generation,
    _source_label,
    _validate_client_safe_answer,
)
from app.services.knowledge.retrieval import (
    _build_context_chunks_from_matches,
    _build_structured_operational_context,
    _retrieve_knowledge_context,
)
from app.services.knowledge.utils import (
    CONVERSATION_HISTORY_MAX_TURNS,
    CONVERSATION_HISTORY_TURN_CHARS,
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_SOURCES,
    KNOWLEDGE_AGENT_NAME,
    LOW_CONFIDENCE_THRESHOLD,
    NO_APPROVED_ANSWER,
    PROMPT_STRATEGY_VERSION,
    _AskTimings,
    _VectorChunk,
    _needs_structured_operational_context,
    _normalize_query_text,
    _prompt_size_diagnostics,
)



# --- qa (Phase 8) ---

@dataclass(frozen=True)
class KnowledgeHistoryNormalization:
    history: list[KnowledgeConversationTurn]
    messages_dropped: int
    total_characters: int
    truncated: bool

    def diagnostics(self) -> dict[str, object]:
        return {
            "turn_count": len(self.history),
            "messages_dropped": self.messages_dropped,
            "total_characters": self.total_characters,
            "truncated": self.truncated,
            "max_turns": CONVERSATION_HISTORY_MAX_TURNS,
            "max_turn_chars": CONVERSATION_HISTORY_TURN_CHARS,
        }

def normalize_conversation_history(
    conversation_history: list[KnowledgeConversationTurn] | None,
    *,
    max_turns: int = CONVERSATION_HISTORY_MAX_TURNS,
    max_turn_chars: int = CONVERSATION_HISTORY_TURN_CHARS,
) -> KnowledgeHistoryNormalization:
    total_characters = 0
    truncated = False
    dropped = 0
    normalized: list[KnowledgeConversationTurn] = []
    previous_key: tuple[str, str] | None = None

    for turn in conversation_history or []:
        role = str(getattr(turn, "role", "") or "").strip().lower()
        content = str(getattr(turn, "content", "") or "")
        if role not in {"user", "assistant"} or not content.strip():
            dropped += 1
            continue
        cleaned = re.sub(r"\s+", " ", content).strip()
        total_characters += len(cleaned)
        if len(cleaned) > max_turn_chars:
            cleaned = cleaned[: max_turn_chars - 3].rstrip() + "..."
            truncated = True
        key = (role, cleaned)
        if key == previous_key:
            dropped += 1
            continue
        previous_key = key
        normalized.append(KnowledgeConversationTurn(role=role, content=cleaned))

    if len(normalized) > max_turns:
        dropped += len(normalized) - max_turns
        normalized = normalized[-max_turns:]

    return KnowledgeHistoryNormalization(
        history=normalized,
        messages_dropped=dropped,
        total_characters=total_characters,
        truncated=truncated,
    )

def _conversation_key(agent_query: AgentQuery) -> UUID:
    return agent_query.conversation_id or agent_query.id

async def _validate_knowledge_conversation_id(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID | None,
) -> UUID | None:
    if conversation_id is None:
        return None
    anchor = (
        await session.execute(
            select(AgentQuery).where(
                AgentQuery.id == conversation_id,
                AgentQuery.org_id == current_user.org_id,
                AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
            )
        )
    ).scalar_one_or_none()
    if anchor is None:
        raise ApiError(404, "NOT_FOUND", "Knowledge conversation not found.")
    if anchor.user_id != current_user.id and current_user.role not in {
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
    }:
        raise ApiError(403, "FORBIDDEN", "You cannot continue this conversation.")
    return _conversation_key(anchor)

def _answer_metadata_in_retrieval_params(
    retrieval_params: dict[str, object] | None,
    *,
    next_step: str,
    confidence_score: float,
    confidence_reasons: list[str],
    structured_answer: KnowledgeStructuredAnswer | None,
    confidence_band: str | None = None,
    confidence_breakdown: dict[str, object] | None = None,
    grounding: dict[str, object] | None = None,
    client_safe_validation: dict[str, object] | None = None,
) -> dict[str, object]:
    params = dict(retrieval_params or {})
    params["confidence_score"] = confidence_score
    params["confidence_band"] = confidence_band or _confidence_band(confidence_score)
    if confidence_breakdown is not None:
        params["confidence_breakdown"] = confidence_breakdown
    if grounding is not None:
        params["grounding"] = grounding
    if client_safe_validation is not None:
        params["client_safe_validation"] = client_safe_validation
    params["next_step"] = next_step
    params["confidence_reasons"] = confidence_reasons
    if structured_answer is not None:
        params["structured_answer"] = structured_answer.model_dump()
    return params

async def _finalize_knowledge_agent_query(
    session: AsyncSession,
    agent_query: AgentQuery,
    *,
    conversation_id: UUID | None,
) -> UUID:
    if conversation_id is None:
        agent_query.conversation_id = agent_query.id
    else:
        agent_query.conversation_id = conversation_id
    await session.flush()
    return agent_query.conversation_id or agent_query.id

def _knowledge_ask_read_from_agent_query(agent_query: AgentQuery) -> KnowledgeAskRead:
    retrieval_debug = agent_query.retrieval_params if isinstance(agent_query.retrieval_params, dict) else None
    confidence_score = 0.0
    confidence_band: str | None = None
    next_step = ""
    confidence_reasons: list[str] = []
    structured_answer: KnowledgeStructuredAnswer | None = None
    if retrieval_debug:
        raw_confidence = retrieval_debug.get("confidence_score")
        if isinstance(raw_confidence, int | float):
            confidence_score = float(raw_confidence)
        confidence_band = str(retrieval_debug.get("confidence_band") or "") or None
        next_step = str(retrieval_debug.get("next_step") or "")
        raw_reasons = retrieval_debug.get("confidence_reasons")
        if isinstance(raw_reasons, list):
            confidence_reasons = [str(item) for item in raw_reasons]
        raw_structured = retrieval_debug.get("structured_answer")
        if isinstance(raw_structured, dict):
            structured_answer = KnowledgeStructuredAnswer(
                policy=str(raw_structured.get("policy") or ""),
                steps=str(raw_structured.get("steps") or ""),
                owner=str(raw_structured.get("owner") or ""),
                evidence=str(raw_structured.get("evidence") or ""),
                next_action=str(raw_structured.get("next_action") or ""),
            )
    return KnowledgeAskRead(
        answer_text=agent_query.answer_text,
        next_step=next_step,
        confidence_score=round(confidence_score, 4),
        confidence_band=confidence_band or _confidence_band(confidence_score),
        confidence_reasons=confidence_reasons,
        structured_answer=structured_answer,
        query_id=agent_query.id,
        conversation_id=_conversation_key(agent_query),
        model_used=agent_query.model_used,
        retrieval_debug=retrieval_debug,
    )

async def list_knowledge_conversations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    limit: int = 30,
) -> list[KnowledgeConversationSummaryRead]:
    filters = [
        AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
        AgentQuery.org_id == current_user.org_id,
    ]
    if current_user.role not in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        filters.append(AgentQuery.user_id == current_user.id)
    rows = list(
        (
            await session.execute(
                select(AgentQuery)
                .where(*filters)
                .order_by(AgentQuery.created_at.desc())
                .limit(max(limit * 8, 120))
            )
        ).scalars()
    )
    grouped: dict[UUID, list[AgentQuery]] = {}
    for row in rows:
        key = _conversation_key(row)
        grouped.setdefault(key, []).append(row)
    summaries: list[KnowledgeConversationSummaryRead] = []
    for conv_id, turns in grouped.items():
        ordered = sorted(turns, key=lambda item: item.created_at)
        summaries.append(
            KnowledgeConversationSummaryRead(
                id=conv_id,
                title=ordered[0].query_text.strip()[:120] or "Knowledge chat",
                turn_count=len(ordered),
                updated_at=ordered[-1].created_at,
            )
        )
    summaries.sort(key=lambda item: item.updated_at, reverse=True)
    return summaries[:limit]

async def get_knowledge_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID,
) -> KnowledgeConversationRead:
    await _validate_knowledge_conversation_id(session, current_user, conversation_id)
    rows = list(
        (
            await session.execute(
                select(AgentQuery)
                .where(
                    AgentQuery.org_id == current_user.org_id,
                    AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
                    (AgentQuery.conversation_id == conversation_id) | (AgentQuery.id == conversation_id),
                )
                .order_by(AgentQuery.created_at.asc())
            )
        ).scalars()
    )
    if not rows:
        raise ApiError(404, "NOT_FOUND", "Knowledge conversation not found.")
    return KnowledgeConversationRead(
        id=conversation_id,
        turns=[
            KnowledgeConversationTurnRead(
                query_id=row.id,
                query_text=row.query_text,
                answer=_knowledge_ask_read_from_agent_query(row),
            )
            for row in rows
        ],
    )

async def ask_knowledge_agent(
    session: AsyncSession,
    current_user: CurrentUser,
    query_text: str,
    *,
    conversation_history: list[KnowledgeConversationTurn] | None = None,
    answer_mode: str = "internal",
    include_histories: bool = True,
    max_sources: int = DEFAULT_MAX_SOURCES,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    min_relevance_score: float = 0.25,
    project: str | None = None,
    department: str | None = None,
    folder_id: UUID | None = None,
    folder_ids: list[UUID] | None = None,
    source_type: str | None = None,
    source_types: list[str] | None = None,
    effective_date_from: date | None = None,
    effective_date_to: date | None = None,
    only_approved: bool = True,
    conversation_id: UUID | None = None,
) -> KnowledgeAskRead:
    started = datetime.now(timezone.utc)
    timings = _AskTimings()
    resolved_conversation_id = await _validate_knowledge_conversation_id(
        session, current_user, conversation_id
    )
    max_sources = max(1, min(max_sources, 10))
    max_candidates = max(max_sources, min(max_candidates, 80))
    min_relevance_score = max(0.0, min(min_relevance_score, 1.0))
    client_safe_mode = answer_mode == "client_safe"
    history_norm = normalize_conversation_history(conversation_history)
    history = history_norm.history
    retrieval = await _retrieve_knowledge_context(
        session,
        current_user,
        query_text,
        conversation_history=history,
        answer_mode=answer_mode,
        include_histories=include_histories,
        max_sources=max_sources,
        max_candidates=max_candidates,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
        folder_id=folder_id,
        folder_ids=folder_ids,
        source_type=source_type,
        source_types=source_types,
        effective_date_from=effective_date_from,
        effective_date_to=effective_date_to,
        only_approved=True,
        prefer_fast_retrieval=True,
        timings=timings,
    )
    if retrieval.empty_eligible_reason == "no_accessible_docs":
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="No approved documents are available for your role.",
            retrieval_params=_build_retrieval_params(
                query_text=query_text,
                retrieval_query=retrieval.retrieval_query,
                answer_mode=answer_mode,
                include_histories=include_histories,
                max_sources=max_sources,
                max_candidates=max_candidates,
                min_relevance_score=min_relevance_score,
                project=project,
                department=department,
                eligible_doc_count=0,
                has_embeddings=retrieval.has_embeddings,
                matches=[],
                doc_map={},
                vector_scores={},
                keyword_scores={},
                query_type=retrieval.query_type,
                normalized_query=retrieval.normalized_query,
                applied_filters=retrieval.applied_filters,
                fallback_level=retrieval.fallback_level,
                rejected_reasons=retrieval.rejected_reasons,
                timings=retrieval.timings,
                rewrite_diagnostics=retrieval.rewrite_diagnostics,
                history_diagnostics=history_norm.diagnostics(),
            ),
            answer_mode=answer_mode,
            project=project,
            department=department,
        )
    if retrieval.empty_eligible_reason == "no_filtered_docs":
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="No documents matched the project or department filters.",
            retrieval_params=_build_retrieval_params(
                query_text=query_text,
                retrieval_query=retrieval.retrieval_query,
                answer_mode=answer_mode,
                include_histories=include_histories,
                max_sources=max_sources,
                max_candidates=max_candidates,
                min_relevance_score=min_relevance_score,
                project=project,
                department=department,
                eligible_doc_count=0,
                has_embeddings=retrieval.has_embeddings,
                matches=[],
                doc_map={},
                vector_scores={},
                keyword_scores={},
                query_type=retrieval.query_type,
                normalized_query=retrieval.normalized_query,
                applied_filters=retrieval.applied_filters,
                fallback_level=retrieval.fallback_level,
                rejected_reasons=retrieval.rejected_reasons,
                timings=retrieval.timings,
                rewrite_diagnostics=retrieval.rewrite_diagnostics,
                history_diagnostics=history_norm.diagnostics(),
            ),
            answer_mode=answer_mode,
            project=project,
            department=department,
        )

    matches = retrieval.matches
    doc_map = retrieval.doc_map
    folders_map = retrieval.folders_map
    retrieval_query = retrieval.retrieval_query
    has_embeddings = retrieval.has_embeddings
    eligible_docs = retrieval.eligible_docs
    vector_scores = retrieval.vector_scores
    keyword_scores = retrieval.keyword_scores
    top_score = retrieval.top_score

    if not matches:
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="No relevant chunks met the minimum relevance threshold.",
            eligible_docs=eligible_docs,
            retrieval_params=_build_retrieval_params(
                query_text=query_text,
                retrieval_query=retrieval_query,
                answer_mode=answer_mode,
                include_histories=include_histories,
                max_sources=max_sources,
                max_candidates=max_candidates,
                min_relevance_score=min_relevance_score,
                project=project,
                department=department,
                eligible_doc_count=len(eligible_docs),
                has_embeddings=has_embeddings,
                matches=[],
                doc_map=doc_map,
                vector_scores=vector_scores,
                keyword_scores=keyword_scores,
                query_type=retrieval.query_type,
                normalized_query=retrieval.normalized_query,
                score_breakdowns=retrieval.score_breakdowns,
                applied_filters=retrieval.applied_filters,
                fallback_level=retrieval.fallback_level,
                candidate_count=retrieval.candidate_count,
                vector_candidate_count=retrieval.vector_candidate_count,
                keyword_candidate_count=retrieval.keyword_candidate_count,
                candidates_after_deduplication=retrieval.candidates_after_deduplication,
                rejected_reasons=retrieval.rejected_reasons,
                rewrite_diagnostics=retrieval.rewrite_diagnostics,
                history_diagnostics=history_norm.diagnostics(),
            ),
            answer_mode=answer_mode,
            project=project,
            department=department,
        )

    # ── 5. Build context for GPT and call LLMClient ───────────────────────────
    timings.mark("context_build_ms")
    fast_path = top_score >= FAST_PATH_THRESHOLD
    settings = get_settings()
    fast_model = settings.openai_model or settings.llm_model or "gpt-4o-mini"

    import app.services.knowledge as knowledge_services

    llm = knowledge_services.LLMClient()
    context_chunks = _build_context_chunks_from_matches(matches, doc_map, folders_map)

    structured_context = ""
    if not fast_path and _needs_structured_operational_context(query_text, explicit_project=project):
        structured_context = await knowledge_services._build_structured_operational_context(
            session,
            current_user,
            query_text=query_text,
            explicit_project=project,
            client_safe=client_safe_mode,
        )
    prompt_diagnostics = _prompt_size_diagnostics(
        query_text=query_text,
        context_chunks=context_chunks,
        structured_context=structured_context,
        history=history,
    )
    llm_history = [{"role": turn.role, "content": turn.content} for turn in history]
    llm_start = perf_counter()
    llm_result = await llm.generate_rag_answer(
        query_text,
        context_chunks,
        model=fast_model,
        conversation_history=llm_history,
        answer_mode="client_safe" if client_safe_mode else "internal",
        structured_context=structured_context,
        fast_path=fast_path,
    )
    timings.mark("llm_complete_ms")
    timings._marks["llm_first_token_ms"] = round((perf_counter() - llm_start) * 1000, 1)

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
    grounding = knowledge_services._ground_generation(
        answer_text, structured_answer, context_chunks, structured_context
    )
    client_safe_validation = (
        _validate_client_safe_answer(answer_text, structured_answer, context_chunks)
        if client_safe_mode
        else None
    )

    gap_retrieval_params = _build_retrieval_params(
        query_text=query_text,
        retrieval_query=retrieval_query,
        answer_mode=answer_mode,
        include_histories=include_histories,
        max_sources=max_sources,
        max_candidates=max_candidates,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
        eligible_doc_count=len(eligible_docs),
        has_embeddings=has_embeddings,
        matches=matches,
        doc_map=doc_map,
        vector_scores=vector_scores,
        keyword_scores=keyword_scores,
        query_type=retrieval.query_type,
        normalized_query=retrieval.normalized_query,
        score_breakdowns=retrieval.score_breakdowns,
        applied_filters=retrieval.applied_filters,
        fallback_level=retrieval.fallback_level,
        candidate_count=retrieval.candidate_count,
        vector_candidate_count=retrieval.vector_candidate_count,
        keyword_candidate_count=retrieval.keyword_candidate_count,
        candidates_after_deduplication=retrieval.candidates_after_deduplication,
        rejected_reasons=retrieval.rejected_reasons,
        rewrite_diagnostics=retrieval.rewrite_diagnostics,
        history_diagnostics=history_norm.diagnostics(),
    )
    gap_retrieval_params["prompt"] = prompt_diagnostics
    gap_retrieval_params["grounding"] = grounding
    if client_safe_validation is not None:
        gap_retrieval_params["client_safe_validation"] = client_safe_validation
    if answer_text.strip() == NO_APPROVED_ANSWER:
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="Retrieved chunks did not contain a confident answer.",
            eligible_docs=eligible_docs,
            matches=matches,
            retrieval_params=gap_retrieval_params,
            answer_mode=answer_mode,
            project=project,
            department=department,
        )
    if not grounding["grounded"]:
        if float(grounding["support"]) < 0.2:
            return await _persist_empty_ask_response(
                session,
                current_user,
                query_text,
                started=started,
                reason="Generated answer could not be grounded in retrieved evidence.",
                eligible_docs=eligible_docs,
                matches=matches,
                retrieval_params=gap_retrieval_params,
                answer_mode=answer_mode,
                project=project,
                department=department,
            )
        raw_confidence = min(raw_confidence, float(grounding["support"]))
    if client_safe_validation is not None and not bool(client_safe_validation.get("valid", True)):
        return await _persist_empty_ask_response(
            session,
            current_user,
            query_text,
            started=started,
            reason="Generated answer was not safe for client-facing use.",
            eligible_docs=eligible_docs,
            matches=matches,
            retrieval_params=gap_retrieval_params,
            answer_mode=answer_mode,
            project=project,
            department=department,
        )

    confidence = _compute_answer_confidence(
        raw_confidence=raw_confidence,
        matches=matches,
        eligible_docs=eligible_docs,
        doc_map=doc_map,
        grounding=grounding,
        query_type=retrieval.query_type,
        has_structured_context=bool(structured_context),
        client_safe_result=client_safe_validation,
        fallback_level=retrieval.fallback_level,
    )
    confidence_score = float(confidence["score"])
    confidence_reasons = list(confidence["reasons"])
    if not grounding["grounded"]:
        confidence_reasons.append("Some generated claims had weak support in retrieved evidence")
    if structured_context:
        confidence_reasons.append("Included structured project data in answer context")
    if client_safe_mode:
        confidence_reasons.append("Restricted retrieval and wording to client-safe sources")

    # ── 6. Persist AgentQuery ─────────────────────────────────────────────────
    retrieval_params = _build_retrieval_params(
        query_text=query_text,
        retrieval_query=retrieval_query,
        answer_mode=answer_mode,
        include_histories=include_histories,
        max_sources=max_sources,
        max_candidates=max_candidates,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
        eligible_doc_count=len(eligible_docs),
        has_embeddings=has_embeddings,
        matches=matches,
        doc_map=doc_map,
        vector_scores=vector_scores,
        keyword_scores=keyword_scores,
        query_type=retrieval.query_type,
        normalized_query=retrieval.normalized_query,
        score_breakdowns=retrieval.score_breakdowns,
        applied_filters=retrieval.applied_filters,
        fallback_level=retrieval.fallback_level,
        candidate_count=retrieval.candidate_count,
        vector_candidate_count=retrieval.vector_candidate_count,
        keyword_candidate_count=retrieval.keyword_candidate_count,
        candidates_after_deduplication=retrieval.candidates_after_deduplication,
        rejected_reasons=retrieval.rejected_reasons,
        confidence_score=confidence_score,
        timings=retrieval.timings,
        rewrite_diagnostics=retrieval.rewrite_diagnostics,
        history_diagnostics=history_norm.diagnostics(),
    )
    if float(confidence_score) < LOW_CONFIDENCE_THRESHOLD:
        confidence_reasons.append("This answer may be incomplete. Try deeper search.")
    timings.mark("persistence_ms")
    retrieval_params = _answer_metadata_in_retrieval_params(
        retrieval_params,
        next_step=next_step,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        structured_answer=structured_answer,
        confidence_band=str(confidence["band"]),
        confidence_breakdown=confidence["breakdown"] if isinstance(confidence.get("breakdown"), dict) else None,
        grounding=grounding,
        client_safe_validation=client_safe_validation,
    )
    retrieval_params["prompt"] = prompt_diagnostics
    retrieval_params["timings"] = timings.to_dict()
    retrieval_params["total_ms"] = timings.to_dict().get("persistence_ms", 0)
    logger.info(
        "knowledge_ask_timing",
        extra={"org_id": str(current_user.org_id), "timings": timings.to_dict(), "stream": False},
    )
    agent_query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=None,
        agent_name=KNOWLEDGE_AGENT_NAME,
        query_text=query_text,
        answer_text=answer_text,
        model_used=model_used,
        latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        retrieval_params=retrieval_params,
        conversation_id=resolved_conversation_id,
    )
    session.add(agent_query)
    await session.flush()
    active_conversation_id = await _finalize_knowledge_agent_query(
        session,
        agent_query,
        conversation_id=resolved_conversation_id,
    )

    # ── 7. Persist evidence links (one per chunk) ─────────────────────────────
    for chunk, score in matches:
        doc = doc_map[chunk.document_id]
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
    return KnowledgeAskRead(
        answer_text=answer_text,
        next_step=next_step,
        confidence_score=confidence_score,
        confidence_band=str(confidence["band"]),
        confidence_reasons=confidence_reasons,
        structured_answer=structured_answer,
        query_id=agent_query.id,
        conversation_id=active_conversation_id,
        model_used=model_used,
        retrieval_debug=retrieval_params,
    )

async def get_knowledge_query_answer(
    session: AsyncSession,
    current_user: CurrentUser,
    query_id: UUID,
) -> KnowledgeAskRead:
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
    if agent_query.user_id != current_user.id and current_user.role not in {
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
    }:
        raise ApiError(403, "FORBIDDEN", "You cannot view this saved answer.")
    return _knowledge_ask_read_from_agent_query(agent_query)

def _build_retrieval_params(
    *,
    query_text: str,
    retrieval_query: str,
    answer_mode: str,
    include_histories: bool,
    max_sources: int,
    min_relevance_score: float,
    project: str | None,
    department: str | None,
    eligible_doc_count: int,
    has_embeddings: bool,
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]],
    doc_map: dict[UUID, KnowledgeDocument],
    vector_scores: dict[UUID, float],
    keyword_scores: dict[UUID, float],
    query_type: str = "factual",
    normalized_query: str | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    score_breakdowns: dict[UUID, dict[str, float]] | None = None,
    applied_filters: dict[str, object] | None = None,
    fallback_level: int = 0,
    candidate_count: int | None = None,
    vector_candidate_count: int | None = None,
    keyword_candidate_count: int | None = None,
    candidates_after_deduplication: int | None = None,
    rejected_reasons: dict[str, list[str]] | None = None,
    confidence_score: float | None = None,
    timings: dict[str, float] | None = None,
    rewrite_diagnostics: dict[str, object] | None = None,
    history_diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    citations: list[dict[str, object]] = []
    seen_citation_chunks: set[UUID] = set()
    for chunk, score in matches:
        doc = doc_map.get(chunk.document_id)
        breakdown = (score_breakdowns or {}).get(chunk.id)
        readiness = assess_retrieval_readiness(doc, org_id=doc.org_id) if doc else None
        citation = {
            "document_id": str(chunk.document_id),
            "chunk_id": str(chunk.id),
            "title": doc.title if doc else "",
            "section_path": getattr(chunk, "section_path", None) or getattr(chunk, "section_title", None) or "",
            "page": chunk.page_number,
            "source_type": doc.source_type.value if doc else "",
            "effective_date": doc.effective_date.isoformat() if doc and doc.effective_date else None,
            "readiness": readiness.reason if readiness else None,
            "visibility": doc.visibility.value if doc else None,
            "relevance_score": round(score, 4),
        }
        sources.append(
            {
                "document_id": str(chunk.document_id),
                "chunk_id": str(chunk.id),
                "title": doc.title if doc else "",
                "section_path": citation["section_path"],
                "page": citation["page"],
                "source_type": citation["source_type"],
                "effective_date": citation["effective_date"],
                "readiness": citation["readiness"],
                "visibility": citation["visibility"],
                "relevance_score": round(score, 4),
                "vector_score": round(vector_scores.get(chunk.id, 0.0), 4),
                "keyword_score": round(keyword_scores.get(chunk.id, 0.0), 4),
                "score_breakdown": breakdown,
            }
        )
        if chunk.id not in seen_citation_chunks:
            citations.append(citation)
            seen_citation_chunks.add(chunk.id)
    params: dict[str, object] = {
        "query_text": query_text,
        "query_type": query_type,
        "original_query": query_text,
        "normalized_query": normalized_query or _normalize_query_text(query_text),
        "retrieval_query": retrieval_query,
        "rewritten_query": retrieval_query if retrieval_query.strip() != query_text.strip() else None,
        "query_rewrite": rewrite_diagnostics or {
            "attempted": False,
            "reason": "not_recorded",
            "succeeded": retrieval_query.strip() != query_text.strip(),
            "original_query": query_text,
            "rewritten_query": retrieval_query,
        },
        "conversation_history": history_diagnostics or {},
        "prompt_strategy": PROMPT_STRATEGY_VERSION,
        "answer_mode": answer_mode,
        "include_histories": include_histories,
        "max_sources": max_sources,
        "max_candidates": max_candidates,
        "min_relevance_score": min_relevance_score,
        "project": project,
        "department": department,
        "applied_filters": applied_filters or {},
        "fallback_level": fallback_level,
        "eligible_doc_count": eligible_doc_count,
        "has_embeddings": has_embeddings,
        "candidate_count": candidate_count if candidate_count is not None else len(vector_scores) + len(keyword_scores),
        "vector_candidate_count": vector_candidate_count if vector_candidate_count is not None else len(vector_scores),
        "keyword_candidate_count": keyword_candidate_count if keyword_candidate_count is not None else len(keyword_scores),
        "candidates_after_deduplication": candidates_after_deduplication if candidates_after_deduplication is not None else len(matches),
        "selected_source_count": len(matches),
        "sources": sources,
        "citations": citations,
        "ranking_score_breakdown": {
            str(chunk_id): breakdown for chunk_id, breakdown in (score_breakdowns or {}).items()
        },
        "rejected_candidate_reasons": rejected_reasons or {},
    }
    if confidence_score is not None:
        params["confidence_score"] = confidence_score
    if timings:
        params["timings"] = timings
    return params
