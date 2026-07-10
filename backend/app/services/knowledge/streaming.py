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

from app.services.knowledge.grounding import (
    _compute_answer_confidence,
    _ground_generation,
    _source_label,
    _validate_client_safe_answer,
)
from app.services.knowledge.qa import (
    _answer_metadata_in_retrieval_params,
    _build_retrieval_params,
    _finalize_knowledge_agent_query,
    _validate_knowledge_conversation_id,
    normalize_conversation_history,
)
from app.services.knowledge.retrieval import (
    _build_context_chunks_from_matches,
    _build_structured_operational_context,
    _retrieve_knowledge_context,
)
from app.services.knowledge.utils import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_SOURCES,
    KNOWLEDGE_AGENT_NAME,
    LOW_CONFIDENCE_THRESHOLD,
    NO_APPROVED_ANSWER,
    _AskTimings,
    _VectorChunk,
    _get_knowledge_answer_cache,
    _knowledge_cache_key,
    _knowledge_scope_fingerprint,
    _needs_structured_operational_context,
    _set_knowledge_answer_cache,
    _sse,
)



# --- streaming (Phase 8) ---

@dataclass
class StreamKnowledgePrepared:
    """Retrieval context for LLM streaming without holding a request DB session."""

    current_user: CurrentUser
    query_text: str
    answer_mode: str
    client_safe_mode: bool
    history: list[KnowledgeConversationTurn]
    matches: list[tuple[KnowledgeDocumentChunk | _VectorChunk, float]]
    doc_map: dict[UUID, KnowledgeDocument]
    folders_map: dict[UUID, KnowledgeFolder]
    eligible_docs: list[KnowledgeDocument]
    vector_scores: dict[UUID, float]
    keyword_scores: dict[UUID, float]
    top_score: float
    retrieval_query: str
    has_embeddings: bool
    structured_context: str
    include_histories: bool
    max_sources: int
    max_candidates: int
    min_relevance_score: float
    project: str | None
    department: str | None
    started: datetime
    timings: _AskTimings | None = None
    cache_key: tuple[str, ...] | None = None
    scope_hash: str | None = None
    conversation_id: UUID | None = None
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

async def prepare_stream_knowledge_ask(
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
) -> tuple[list[str], StreamKnowledgePrepared | None]:
    """
    Run retrieval and context assembly while the request session is open.
    Returns (early_sse_events, prepared_context). When early events are returned,
    the stream is complete and prepared_context is None.
    """
    started = datetime.now(timezone.utc)
    timings = _AskTimings()
    max_sources = max(1, min(max_sources, 10))
    max_candidates = max(max_sources, min(max_candidates, 80))
    min_relevance_score = max(0.0, min(min_relevance_score, 1.0))
    client_safe_mode = answer_mode == "client_safe"
    history_norm = normalize_conversation_history(conversation_history)
    history = history_norm.history
    early_events = [
        _sse({"type": "accepted"}),
        _sse({"type": "status", "phase": "searching"}),
        _sse({"type": "searching_sources"}),
    ]
    resolved_conversation_id = await _validate_knowledge_conversation_id(
        session, current_user, conversation_id
    )

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
    early_events.append(
        _sse({
            "type": "sources_found",
            "source_count": len(retrieval.matches),
            "eligible_doc_count": len(retrieval.eligible_docs),
        })
    )
    early_events.append(_sse({"type": "status", "phase": "reading"}))
    if retrieval.empty_eligible_reason == "no_accessible_docs":
        return early_events + [_sse({
            "type": "error",
            "code": "NO_APPROVED_DOCUMENTS",
            "message": "No approved documents are available.",
            "retryable": False,
        })], None
    if retrieval.empty_eligible_reason == "no_filtered_docs":
        return early_events + [_sse({
            "type": "error",
            "code": "NO_FILTERED_DOCUMENTS",
            "message": "No documents matched the filters.",
            "retryable": False,
        })], None

    matches = retrieval.matches
    doc_map = retrieval.doc_map
    folders_map = retrieval.folders_map
    retrieval_query = retrieval.retrieval_query
    has_embeddings = retrieval.has_embeddings
    eligible_docs = retrieval.eligible_docs
    vector_scores = retrieval.vector_scores
    keyword_scores = retrieval.keyword_scores
    top_score = retrieval.top_score
    scope_hash = retrieval.scope_hash or _knowledge_scope_fingerprint(eligible_docs)

    cache_key = _knowledge_cache_key(
        current_user.org_id,
        query_text,
        answer_mode=answer_mode,
        scope_hash=scope_hash,
        include_histories=include_histories,
        project=project,
        department=department,
        folder_id=folder_id,
        source_type=source_type,
    )
    cached = _get_knowledge_answer_cache(cache_key)
    if cached and not history:
        early_events.append(_sse({"type": "status", "phase": "generating"}))
        agent_query = AgentQuery(
            user_id=current_user.id,
            org_id=current_user.org_id,
            project_id=None,
            agent_name=KNOWLEDGE_AGENT_NAME,
            query_text=query_text,
            answer_text=str(cached.get("answer_text") or NO_APPROVED_ANSWER),
            model_used=str(cached.get("model_used")) if cached.get("model_used") else None,
            latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            retrieval_params={**(cached.get("retrieval_params") or {}), "cache_hit": True},
            conversation_id=resolved_conversation_id,
        )
        session.add(agent_query)
        await session.flush()
        active_conversation_id = await _finalize_knowledge_agent_query(
            session,
            agent_query,
            conversation_id=resolved_conversation_id,
        )
        return early_events + [
            _sse({"type": "meta", "query_id": str(agent_query.id), "confidence_estimate": cached.get("confidence_score", 0.0)}),
            _sse({
                "type": "done",
                "query_id": str(agent_query.id),
                "conversation_id": str(active_conversation_id),
                "answer_text": cached.get("answer_text"),
                "confidence_score": cached.get("confidence_score", 0.0),
                "confidence_reasons": cached.get("confidence_reasons", []),
                "next_step": cached.get("next_step", ""),
                "structured_answer": cached.get("structured_answer"),
                "model_used": cached.get("model_used"),
                "retrieval_debug": agent_query.retrieval_params,
            }),
        ], None

    if not matches:
        empty_retrieval_params = _build_retrieval_params(
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
            timings=retrieval.timings,
            rewrite_diagnostics=retrieval.rewrite_diagnostics,
            history_diagnostics=history_norm.diagnostics(),
        )
        agent_query = AgentQuery(
            user_id=current_user.id, org_id=current_user.org_id, project_id=None,
            agent_name=KNOWLEDGE_AGENT_NAME, query_text=query_text,
            answer_text=NO_APPROVED_ANSWER, model_used=None,
            latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            retrieval_params=empty_retrieval_params,
            conversation_id=resolved_conversation_id,
        )
        session.add(agent_query)
        await session.flush()
        active_conversation_id = await _finalize_knowledge_agent_query(
            session,
            agent_query,
            conversation_id=resolved_conversation_id,
        )
        return early_events + [
            _sse({"type": "meta", "query_id": str(agent_query.id), "confidence_estimate": 0.0}),
            _sse({
                "type": "done",
                "query_id": str(agent_query.id),
                "conversation_id": str(active_conversation_id),
                "answer_text": NO_APPROVED_ANSWER,
                "confidence_score": 0.0,
                "next_step": "Upload or approve a related document if this answer is needed.",
                "structured_answer": None,
                "model_used": None,
                "retrieval_debug": empty_retrieval_params,
            }),
        ], None

    structured_context = ""
    if _needs_structured_operational_context(query_text, explicit_project=project):
        import app.services.knowledge as knowledge_services

        structured_context = await knowledge_services._build_structured_operational_context(
            session, current_user, query_text=query_text, explicit_project=project, client_safe=client_safe_mode,
        )
    timings.mark("context_build_ms")
    return early_events, StreamKnowledgePrepared(
        current_user=current_user,
        query_text=query_text,
        answer_mode=answer_mode,
        client_safe_mode=client_safe_mode,
        history=history,
        matches=matches,
        doc_map=doc_map,
        folders_map=folders_map,
        eligible_docs=eligible_docs,
        vector_scores=vector_scores,
        keyword_scores=keyword_scores,
        top_score=top_score,
        retrieval_query=retrieval_query,
        has_embeddings=has_embeddings,
        structured_context=structured_context,
        include_histories=include_histories,
        max_sources=max_sources,
        max_candidates=max_candidates,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
        started=started,
        timings=timings,
        cache_key=cache_key,
        scope_hash=scope_hash,
        conversation_id=resolved_conversation_id,
        query_type=retrieval.query_type,
        normalized_query=retrieval.normalized_query,
        fallback_level=retrieval.fallback_level,
        applied_filters=retrieval.applied_filters,
        score_breakdowns=retrieval.score_breakdowns,
        rejected_reasons=retrieval.rejected_reasons,
        candidate_count=retrieval.candidate_count,
        vector_candidate_count=retrieval.vector_candidate_count,
        keyword_candidate_count=retrieval.keyword_candidate_count,
        candidates_after_deduplication=retrieval.candidates_after_deduplication,
        rewrite_diagnostics=retrieval.rewrite_diagnostics,
        history_diagnostics=history_norm.diagnostics(),
    )

async def stream_prepared_knowledge_ask(
    prepared: StreamKnowledgePrepared,
) -> AsyncGenerator[str, None]:
    """Stream LLM tokens and persist results using a short-lived DB session."""
    current_user = prepared.current_user
    query_text = prepared.query_text
    client_safe_mode = prepared.client_safe_mode
    history = prepared.history
    matches = prepared.matches
    doc_map = prepared.doc_map
    folders_map = prepared.folders_map
    eligible_docs = prepared.eligible_docs
    vector_scores = prepared.vector_scores
    keyword_scores = prepared.keyword_scores
    top_score = prepared.top_score
    retrieval_query = prepared.retrieval_query
    has_embeddings = prepared.has_embeddings
    structured_context = prepared.structured_context
    started = prepared.started
    answer_mode = prepared.answer_mode

    confidence_estimate = round(0.4 * min(top_score, 1.0), 4)
    yield _sse({"type": "meta", "confidence_estimate": confidence_estimate})
    yield _sse({"type": "status", "phase": "generating"})
    yield _sse({"type": "generating_answer"})

    context_chunks = _build_context_chunks_from_matches(matches, doc_map, folders_map)

    fast_path = top_score >= FAST_PATH_THRESHOLD
    settings_obj = get_settings()
    fast_model = settings_obj.openai_model or settings_obj.llm_model or "gpt-4o-mini"
    llm_history = [{"role": turn.role, "content": turn.content} for turn in history]

    import app.services.knowledge as knowledge_services

    llm = knowledge_services.LLMClient()
    accumulated_answer = ""
    llm_done_event: dict[str, object] = {}
    llm_start = perf_counter()
    first_token_marked = False

    async for event in llm.stream_rag_answer(
        query_text, context_chunks,
        model=fast_model,
        conversation_history=llm_history,
        answer_mode="client_safe" if client_safe_mode else "internal",
        structured_context=structured_context,
        fast_path=fast_path,
    ):
        if event["type"] == "delta":
            if not first_token_marked and prepared.timings is not None:
                prepared.timings._marks["llm_first_token_ms"] = round((perf_counter() - llm_start) * 1000, 1)
                first_token_marked = True
            accumulated_answer += str(event.get("text", ""))
            yield _sse({"type": "answer_delta", "text": str(event.get("text", ""))})
            yield _sse(event)
        elif event["type"] == "done":
            llm_done_event = event
            break

    if prepared.timings is not None:
        prepared.timings.mark("llm_complete_ms")

    raw_confidence = float(llm_done_event.get("confidence") or 0.0)
    model_used = str(llm_done_event.get("model") or fast_model)

    answer_text = accumulated_answer or str(llm_done_event.get("answer_text") or NO_APPROVED_ANSWER)
    next_step = str(llm_done_event.get("next_step") or "")
    structured_raw = llm_done_event.get("structured")
    structured_answer: KnowledgeStructuredAnswer | None = None
    if isinstance(structured_raw, dict) and not fast_path:
        structured_answer = KnowledgeStructuredAnswer(
            policy=str(structured_raw.get("policy") or ""),
            steps=str(structured_raw.get("steps") or ""),
            owner=str(structured_raw.get("owner") or ""),
            evidence=str(structured_raw.get("evidence") or ""),
            next_action=str(structured_raw.get("next_action") or next_step),
        )

    yield _sse({"type": "validating_grounding"})
    grounding = knowledge_services._ground_generation(
        answer_text, structured_answer, context_chunks, structured_context
    )
    client_safe_validation = (
        _validate_client_safe_answer(answer_text, structured_answer, context_chunks)
        if client_safe_mode
        else None
    )
    grounding_rejected = False
    if (
        not grounding["grounded"]
        and float(grounding["support"]) < 0.2
        and answer_text.strip() != NO_APPROVED_ANSWER
        and not (matches and matches[0][1] >= 0.45 and len(answer_text.strip()) > 80)
    ):
        grounding_rejected = True
        answer_text = NO_APPROVED_ANSWER
        raw_confidence = 0.0
    if client_safe_validation is not None and not bool(client_safe_validation.get("valid", True)):
        grounding_rejected = True
        answer_text = NO_APPROVED_ANSWER
        raw_confidence = 0.0

    confidence = _compute_answer_confidence(
        raw_confidence=raw_confidence,
        matches=matches,
        eligible_docs=eligible_docs,
        doc_map=doc_map,
        grounding=grounding,
        query_type=prepared.query_type,
        has_structured_context=bool(structured_context),
        client_safe_result=client_safe_validation,
        fallback_level=prepared.fallback_level,
    )
    confidence_score = float(confidence["score"])

    if not answer_text.strip():
        answer_text = NO_APPROVED_ANSWER

    confidence_reasons = list(confidence["reasons"])
    if not grounding["grounded"]:
        confidence_reasons.append("Some generated claims had weak support in retrieved evidence")
    if structured_context:
        confidence_reasons.append("Included structured project data in answer context")
    if client_safe_mode:
        confidence_reasons.append("Restricted retrieval and wording to client-safe sources")
    if fast_path:
        confidence_reasons.append("Fast path: high-relevance chunks used short prompt")
    if float(confidence_score) < LOW_CONFIDENCE_THRESHOLD:
        confidence_reasons.append("This answer may be incomplete. Try deeper search.")

    query_id: str | None = None
    active_conversation_id: UUID | None = prepared.conversation_id
    retrieval_params: dict[str, object] | None = None
    try:
        async with AsyncSessionLocal() as persist_session:
            await set_rls_context(persist_session, json.dumps({"sub": str(current_user.id)}))
            retrieval_params = _build_retrieval_params(
                query_text=query_text, retrieval_query=retrieval_query, answer_mode=answer_mode,
                include_histories=prepared.include_histories, max_sources=prepared.max_sources,
                max_candidates=prepared.max_candidates,
                min_relevance_score=prepared.min_relevance_score,
                project=prepared.project, department=prepared.department, eligible_doc_count=len(eligible_docs),
                has_embeddings=has_embeddings, matches=matches, doc_map=doc_map,
                vector_scores=vector_scores, keyword_scores=keyword_scores, confidence_score=confidence_score,
                query_type=prepared.query_type,
                normalized_query=prepared.normalized_query,
                score_breakdowns=prepared.score_breakdowns,
                applied_filters=prepared.applied_filters,
                fallback_level=prepared.fallback_level,
                candidate_count=prepared.candidate_count,
                vector_candidate_count=prepared.vector_candidate_count,
                keyword_candidate_count=prepared.keyword_candidate_count,
                candidates_after_deduplication=prepared.candidates_after_deduplication,
                rejected_reasons=prepared.rejected_reasons,
                timings=prepared.timings.to_dict() if prepared.timings else None,
                rewrite_diagnostics=prepared.rewrite_diagnostics,
                history_diagnostics=prepared.history_diagnostics,
            )
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
            agent_query = AgentQuery(
                user_id=current_user.id, org_id=current_user.org_id, project_id=None,
                agent_name=KNOWLEDGE_AGENT_NAME, query_text=query_text, answer_text=answer_text,
                model_used=model_used,
                latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                retrieval_params=retrieval_params,
                conversation_id=prepared.conversation_id,
            )
            persist_session.add(agent_query)
            await persist_session.flush()
            active_conversation_id = await _finalize_knowledge_agent_query(
                persist_session,
                agent_query,
                conversation_id=prepared.conversation_id,
            )
            query_id = str(agent_query.id)

            for chunk, score in matches:
                doc = doc_map[chunk.document_id]
                label = f"{_source_label(doc.source_type)}: {doc.title} {doc.version}"
                persist_session.add(KnowledgeEvidenceLink(
                    org_id=current_user.org_id, agent_query_id=agent_query.id,
                    document_id=doc.id, chunk_id=chunk.id,
                    citation_label=label, relevance_score=Decimal(str(round(score, 4))),
                ))
            await persist_session.commit()
    except Exception:
        logger.exception("Failed to persist streamed knowledge ask")

    if prepared.timings is not None:
        prepared.timings.mark("persistence_ms")
    if prepared.timings is not None and retrieval_params is not None:
        retrieval_params["timings"] = prepared.timings.to_dict()
        retrieval_params["total_ms"] = prepared.timings.to_dict().get("persistence_ms", 0)
    logger.info(
        "knowledge_ask_timing",
        extra={
            "org_id": str(current_user.org_id),
            "timings": prepared.timings.to_dict() if prepared.timings else {},
            "stream": True,
        },
    )

    if prepared.cache_key and not prepared.history and answer_text.strip() != NO_APPROVED_ANSWER:
        _set_knowledge_answer_cache(
            prepared.cache_key,
            {
                "answer_text": answer_text,
                "confidence_score": confidence_score,
                "confidence_reasons": confidence_reasons,
                "next_step": next_step,
                "structured_answer": (
                    {
                        "policy": structured_answer.policy,
                        "steps": structured_answer.steps,
                        "owner": structured_answer.owner,
                        "evidence": structured_answer.evidence,
                        "next_action": structured_answer.next_action,
                    }
                    if structured_answer
                    else None
                ),
                "model_used": model_used,
                "retrieval_params": retrieval_params,
            },
        )

    final_payload = {
        "type": "done",
        "query_id": query_id,
        "conversation_id": str(active_conversation_id) if active_conversation_id else None,
        "answer_text": answer_text,
        "confidence_score": confidence_score,
        "confidence_band": str(confidence["band"]),
        "confidence_reasons": confidence_reasons,
        "next_step": "Upload or approve a related document if this answer is needed."
        if answer_text.strip() == NO_APPROVED_ANSWER
        else next_step,
        "structured_answer": (
            {
                "policy": structured_answer.policy,
                "steps": structured_answer.steps,
                "owner": structured_answer.owner,
                "evidence": structured_answer.evidence,
                "next_action": structured_answer.next_action,
            }
            if structured_answer else None
        ),
        "model_used": model_used,
        "retrieval_debug": retrieval_params,
    }
    yield _sse({**final_payload, "type": "final"})
    yield _sse(final_payload)

async def stream_knowledge_ask(
    session: AsyncSession,
    current_user: CurrentUser,
    query_text: str,
    *,
    conversation_history: list[KnowledgeConversationTurn] | None = None,
    answer_mode: str = "internal",
    include_histories: bool = True,
    max_sources: int = 5,
    min_relevance_score: float = 0.25,
    project: str | None = None,
    department: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted lines for the streaming /knowledge/ask/stream endpoint.

    Event shapes:
      data: {"type": "meta",  "query_id": "...", "confidence_estimate": 0.7}
      data: {"type": "delta", "text": "<token>"}
      data: {"type": "done",  "answer_text": "...", "confidence_score": 0.82, "next_step": "...",
                              "structured_answer": {...}|null, "model_used": "..."}
      data: {"type": "error", "message": "..."}
    """
    early_events, prepared = await prepare_stream_knowledge_ask(
        session,
        current_user,
        query_text,
        conversation_history=conversation_history,
        answer_mode=answer_mode,
        include_histories=include_histories,
        max_sources=max_sources,
        min_relevance_score=min_relevance_score,
        project=project,
        department=department,
    )
    for event in early_events:
        yield event
    if prepared is None:
        return
    async for chunk in stream_prepared_knowledge_ask(prepared):
        yield chunk
