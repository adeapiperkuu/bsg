"""Phase 15.5 — Delivery knowledge evidence via existing Knowledge RAG.

Reuses ``_retrieve_knowledge_context`` / ``_build_context_chunks_from_matches``.
Does not embed, index, or invent a second retrieval stack.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AppRole, KnowledgeSourceType, Project
from app.services.knowledge import (
    _build_context_chunks_from_matches,
    _retrieve_knowledge_context,
)
from app.services.scoping import get_visible_project

logger = logging.getLogger(__name__)

# Map Phase 15.5 source labels → existing KnowledgeSourceType values.
# PM notes / meeting notes / risk logs are not separate enums; they index as guides
# or escalation notes in the Knowledge library.
DELIVERY_KNOWLEDGE_SOURCE_TYPES: tuple[str, ...] = tuple(
    item.value for item in KnowledgeSourceType
)

SOURCE_CATEGORY_HINTS: dict[str, str] = {
    "pm_notes": KnowledgeSourceType.GUIDE.value,
    "project_charters": KnowledgeSourceType.PROJECT_CHARTER.value,
    "delivery_sops": KnowledgeSourceType.SOP.value,
    "escalation_history": KnowledgeSourceType.ESCALATION_NOTE.value,
    "retrospectives": KnowledgeSourceType.LESSON_LEARNED.value,
    "risk_logs": KnowledgeSourceType.ESCALATION_NOTE.value,
    "meeting_notes": KnowledgeSourceType.GUIDE.value,
}


def build_delivery_knowledge_query(
    *,
    project_name: str,
    root_cause_labels: list[str] | None = None,
    risk_titles: list[str] | None = None,
    bottleneck_titles: list[str] | None = None,
    milestone_names: list[str] | None = None,
    focus: str | None = None,
) -> str:
    """Shape a retrieval query from Delivery signals (no invented facts)."""
    parts = [
        f"Delivery evidence for project {project_name}.",
        "Prefer PM notes, project charters, delivery SOPs, escalation history,",
        "retrospectives, risk logs, and meeting notes when present.",
    ]
    if focus and focus.strip():
        parts.append(f"Focus: {focus.strip()}")
    if root_cause_labels:
        parts.append("Root causes: " + "; ".join(root_cause_labels[:4]))
    if risk_titles:
        parts.append("Risks: " + "; ".join(risk_titles[:4]))
    if bottleneck_titles:
        parts.append("Bottlenecks: " + "; ".join(bottleneck_titles[:3]))
    if milestone_names:
        parts.append("Milestones: " + "; ".join(milestone_names[:3]))
    return " ".join(parts)


def citation_from_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Knowledge context chunk into a Delivery citation DTO."""
    text = str(chunk.get("text") or "").strip()
    excerpt = text if len(text) <= 400 else text[:397].rstrip() + "..."
    return {
        "document_id": str(chunk.get("document_id") or ""),
        "chunk_id": str(chunk.get("chunk_id") or "") or None,
        "title": str(chunk.get("title") or "Knowledge document"),
        "source_type": str(chunk.get("source_type") or ""),
        "folder": str(chunk.get("folder") or "") or None,
        "section_title": str(chunk.get("section_title") or "") or None,
        "page": str(chunk.get("page") or "") or None,
        "version": chunk.get("version"),
        "relevance_score": float(chunk.get("relevance_score") or 0),
        "excerpt": excerpt,
        "visibility": str(chunk.get("visibility") or "") or None,
    }


async def retrieve_delivery_knowledge_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    project: Project | None = None,
    query_text: str | None = None,
    root_cause_labels: list[str] | None = None,
    risk_titles: list[str] | None = None,
    bottleneck_titles: list[str] | None = None,
    milestone_names: list[str] | None = None,
    focus: str | None = None,
    source_types: list[str] | None = None,
    max_sources: int | None = None,
) -> dict[str, Any]:
    """Retrieve Knowledge citations for Delivery. Fail-open to empty evidence."""
    settings = get_settings()
    empty = {
        "project_id": str(project_id) if project_id else None,
        "project_name": None,
        "query_text": query_text,
        "citations": [],
        "enabled": bool(settings.delivery_knowledge_evidence_enabled),
        "empty_reason": None,
    }

    if current_user.role == AppRole.CLIENT:
        empty["empty_reason"] = "clients_excluded"
        empty["enabled"] = False
        return empty

    if not settings.delivery_knowledge_evidence_enabled:
        empty["empty_reason"] = "feature_disabled"
        return empty

    try:
        resolved = project
        if resolved is None:
            if project_id is None:
                empty["empty_reason"] = "project_required"
                return empty
            resolved = await get_visible_project(session, project_id, current_user)

        project_name = resolved.name
        empty["project_id"] = str(resolved.id)
        empty["project_name"] = project_name

        shaped = query_text or build_delivery_knowledge_query(
            project_name=project_name,
            root_cause_labels=root_cause_labels,
            risk_titles=risk_titles,
            bottleneck_titles=bottleneck_titles,
            milestone_names=milestone_names,
            focus=focus,
        )
        empty["query_text"] = shaped

        limit = max_sources or int(settings.delivery_knowledge_evidence_max_sources)
        limit = max(1, min(limit, 10))
        types = source_types or list(DELIVERY_KNOWLEDGE_SOURCE_TYPES)

        retrieval = await _retrieve_knowledge_context(
            session,
            current_user,
            shaped,
            answer_mode="internal",
            include_histories=True,
            max_sources=limit,
            project=project_name,
            source_types=types,
            only_approved=True,
            prefer_fast_retrieval=True,
        )
        chunks = _build_context_chunks_from_matches(
            retrieval.matches,
            retrieval.doc_map,
            retrieval.folders_map,
        )
        citations = [citation_from_chunk(chunk) for chunk in chunks if isinstance(chunk, dict)]
        return {
            "project_id": str(resolved.id),
            "project_name": project_name,
            "query_text": shaped,
            "citations": citations,
            "enabled": True,
            "empty_reason": retrieval.empty_eligible_reason if not citations else None,
            "applied_filters": retrieval.applied_filters,
            "fallback_level": retrieval.fallback_level,
        }
    except Exception:
        logger.exception(
            "event=delivery_knowledge_evidence_failed project_id=%s user_id=%s",
            project_id,
            current_user.id,
        )
        empty["empty_reason"] = "retrieval_failed"
        return empty


async def retrieve_delivery_knowledge_evidence_for_dashboard(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID,
    dashboard: dict[str, Any],
    root_cause_summary: dict[str, Any] | None = None,
    max_sources: int | None = None,
) -> dict[str, Any]:
    """Build query inputs from an already-loaded dashboard + optional root causes."""
    risks = [
        str(item.get("title"))
        for item in (dashboard.get("risks") or [])
        if isinstance(item, dict) and item.get("title")
    ]
    bottlenecks = [
        str(item.get("title"))
        for item in (dashboard.get("bottlenecks") or [])
        if isinstance(item, dict) and item.get("title")
    ]
    milestones = [
        str(item.get("name"))
        for item in (dashboard.get("milestones") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    labels: list[str] = []
    if isinstance(root_cause_summary, dict):
        for cause in root_cause_summary.get("top_causes") or []:
            if isinstance(cause, dict):
                label = cause.get("label") or cause.get("factor")
                if label:
                    labels.append(str(label))

    return await retrieve_delivery_knowledge_evidence(
        session,
        current_user,
        project_id=project_id,
        root_cause_labels=labels,
        risk_titles=risks,
        bottleneck_titles=bottlenecks,
        milestone_names=milestones,
        max_sources=max_sources,
    )
