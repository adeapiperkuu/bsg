"""Knowledge helpers kept after Continuous Learning removal: health, summaries, related docs."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models.entities import (
    AgentQuery,
    AppRole,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
)
from app.schemas.domain import (
    KnowledgeDocumentAiSummaryRead,
    KnowledgeHealthScoreRead,
    KnowledgeLibraryHealthCountsRead,
    KnowledgeRelatedItemRead,
    KnowledgeRelatedKnowledgeRead,
)
from app.services.knowledge.utils import KNOWLEDGE_AGENT_NAME, _tokenize_search_text
from app.services.knowledge_intelligence import extract_cross_references, extract_operational_entities

# Optional AI hook — tests inject a mock; production may leave None (heuristics only).
AiSummaryFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def compute_knowledge_health_score(counts: KnowledgeLibraryHealthCountsRead) -> KnowledgeHealthScoreRead:
    total = max(
        counts.ready_for_retrieval_count
        + counts.needs_review_count
        + counts.expired_count
        + counts.needs_reindex_count
        + counts.failed_processing_count
        + counts.draft_count
        + counts.archived_count,
        1,
    )
    score = 100.0
    score -= min(35.0, (counts.failed_processing_count / total) * 100)
    score -= min(20.0, (counts.expired_count / total) * 80)
    score -= min(15.0, (counts.needs_reindex_count / total) * 60)
    score -= min(12.0, (counts.missing_metadata_count / total) * 50)
    score -= min(10.0, (counts.needs_review_count / total) * 40)
    score -= min(8.0, (counts.outdated_count / total) * 40)
    score += min(10.0, (counts.ready_for_retrieval_count / total) * 10)
    score = max(0.0, min(100.0, round(score, 1)))

    recommendations: list[str] = []
    if counts.failed_processing_count:
        recommendations.append("Reprocess failed documents to restore retrieval coverage.")
    if counts.expired_count:
        recommendations.append("Review expired documents and renew or archive them.")
    if counts.needs_reindex_count:
        recommendations.append("Re-index documents marked needs_reindex before relying on answers.")
    if counts.missing_metadata_count:
        recommendations.append("Complete owner and effective-date metadata on incomplete documents.")
    if counts.needs_review_count:
        recommendations.append("Clear the approval queue to increase ready-for-retrieval coverage.")
    if not recommendations:
        recommendations.append("Library health is strong — continue monitoring document readiness.")

    band = "excellent" if score >= 85 else "good" if score >= 70 else "fair" if score >= 50 else "poor"
    return KnowledgeHealthScoreRead(
        score=score,
        band=band,
        recommendations=recommendations,
        ready_ratio=round(counts.ready_for_retrieval_count / total, 4),
    )


def generate_document_summary_payload(
    *,
    title: str,
    text: str,
    department: str | None = None,
    related_document_ids: list[UUID] | None = None,
    ai_fn: AiSummaryFn | None = None,
) -> dict[str, Any]:
    body = (text or "").strip()
    if ai_fn is not None:
        return ai_fn(body, {"title": title, "department": department})

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    procedures = [line for line in lines if re.match(r"^\d+[\.)]\s+", line)][:8]
    warnings = [
        line
        for line in lines
        if any(line.lower().startswith(prefix) for prefix in ("warning:", "caution:", "important:", "note:", "alert:"))
    ][:6]
    entities = extract_operational_entities(body)
    departments = list(entities.get("departments") or [])
    if department and department not in departments:
        departments.insert(0, department)
    executive = " ".join(body.split())[:320] if body else f"Summary pending for {title}."
    if procedures and not executive.lower().startswith("summary"):
        executive = f"{title}: covers {len(procedures)} key procedure step(s). {executive}"[:400]
    refs = extract_cross_references(body)
    related_from_text = [str(ref.get("referenced_document")) for ref in refs if ref.get("referenced_document")]
    return {
        "executive_summary": executive,
        "key_procedures": procedures or [line for line in lines if "step" in line.lower()][:5],
        "important_warnings": warnings,
        "affected_departments": departments[:8],
        "related_document_ids": [str(item) for item in (related_document_ids or [])],
        "related_references": related_from_text[:8],
    }


def suggest_related_knowledge(
    *,
    document: KnowledgeDocument,
    candidates: list[KnowledgeDocument],
    recent_questions: list[str] | None = None,
) -> KnowledgeRelatedKnowledgeRead:
    source_text = (document.extracted_text or document.title or "").lower()
    source_tokens = set(_tokenize_search_text(source_text)[:80])
    related_sops: list[KnowledgeRelatedItemRead] = []
    related_guides: list[KnowledgeRelatedItemRead] = []
    related_lessons: list[KnowledgeRelatedItemRead] = []
    related_projects: list[str] = []
    similar_questions: list[str] = []

    scored: list[tuple[float, KnowledgeDocument]] = []
    for other in candidates:
        if other.id == document.id:
            continue
        other_text = (other.extracted_text or other.title or "").lower()
        other_tokens = set(_tokenize_search_text(other_text)[:80])
        if not source_tokens or not other_tokens:
            overlap = 0.0
        else:
            overlap = len(source_tokens & other_tokens) / max(len(source_tokens | other_tokens), 1)
        title_sim = SequenceMatcher(None, document.title.lower(), other.title.lower()).ratio()
        score = round(0.7 * overlap + 0.3 * title_sim, 4)
        if document.project and other.project and document.project == other.project:
            score = min(1.0, score + 0.1)
        if score >= 0.12:
            scored.append((score, other))
    scored.sort(key=lambda item: item[0], reverse=True)

    for score, other in scored[:12]:
        item = KnowledgeRelatedItemRead(
            document_id=other.id,
            title=other.title,
            source_type=other.source_type.value,
            score=score,
            reason="Shared terminology and metadata overlap",
        )
        if other.source_type == KnowledgeSourceType.SOP:
            related_sops.append(item)
        elif other.source_type == KnowledgeSourceType.GUIDE:
            related_guides.append(item)
        elif other.source_type == KnowledgeSourceType.LESSON_LEARNED:
            related_lessons.append(item)
        if other.project and other.project not in related_projects:
            related_projects.append(other.project)

    stored_ids = list(getattr(document, "related_document_ids", None) or [])
    by_id = {doc.id: doc for doc in candidates}
    for related_id in stored_ids:
        other = by_id.get(related_id)
        if other is None or other.id == document.id:
            continue
        item = KnowledgeRelatedItemRead(
            document_id=other.id,
            title=other.title,
            source_type=other.source_type.value,
            score=0.99,
            reason="Stored related document link",
        )
        if other.source_type == KnowledgeSourceType.SOP and all(i.document_id != other.id for i in related_sops):
            related_sops.insert(0, item)
        elif other.source_type == KnowledgeSourceType.GUIDE and all(i.document_id != other.id for i in related_guides):
            related_guides.insert(0, item)
        elif other.source_type == KnowledgeSourceType.LESSON_LEARNED and all(
            i.document_id != other.id for i in related_lessons
        ):
            related_lessons.insert(0, item)

    for question in recent_questions or []:
        q_tokens = set(_tokenize_search_text(question))
        if source_tokens & q_tokens:
            similar_questions.append(question)
        if len(similar_questions) >= 5:
            break

    return KnowledgeRelatedKnowledgeRead(
        related_sops=related_sops[:5],
        related_guides=related_guides[:5],
        related_lessons=related_lessons[:5],
        related_projects=related_projects[:8],
        similar_questions=similar_questions,
    )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False


def _require_learning_manager(current_user: CurrentUser) -> None:
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError("forbidden", "Document summary tools require delivery manager access.", 403)


async def _visible_org_documents(session: AsyncSession, org_id: UUID) -> list[KnowledgeDocument]:
    result = await session.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.org_id == org_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def generate_document_ai_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
    *,
    ai_fn: AiSummaryFn | None = None,
) -> KnowledgeDocumentAiSummaryRead:
    _require_learning_manager(current_user)
    doc = await session.get(KnowledgeDocument, document_id)
    if doc is None or doc.org_id != current_user.org_id or doc.deleted_at is not None:
        raise ApiError("not_found", "Document not found.", 404)
    if doc.status != KnowledgeDocumentStatus.APPROVED:
        raise ApiError("conflict", "Summaries can only be generated for approved documents.", 409)

    payload = generate_document_summary_payload(
        title=doc.title,
        text=doc.extracted_text or "",
        department=doc.department,
        related_document_ids=list(doc.related_document_ids or []),
        ai_fn=ai_fn,
    )
    doc.executive_summary = str(payload.get("executive_summary") or "")
    doc.key_procedures = [str(item) for item in payload.get("key_procedures") or []]
    doc.important_warnings = [str(item) for item in payload.get("important_warnings") or []]
    doc.affected_departments = [str(item) for item in payload.get("affected_departments") or []]
    related_ids = []
    for item in payload.get("related_document_ids") or []:
        if _is_uuid(str(item)):
            related_ids.append(UUID(str(item)))
    if related_ids:
        doc.related_document_ids = related_ids
    doc.summary_generated_at = datetime.now(UTC)
    await session.flush()
    return KnowledgeDocumentAiSummaryRead(
        document_id=doc.id,
        executive_summary=doc.executive_summary,
        key_procedures=list(doc.key_procedures or []),
        important_warnings=list(doc.important_warnings or []),
        affected_departments=list(doc.affected_departments or []),
        related_document_ids=list(doc.related_document_ids or []),
        summary_generated_at=doc.summary_generated_at,
    )


async def get_related_knowledge_for_document(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
) -> KnowledgeRelatedKnowledgeRead:
    docs = await _visible_org_documents(session, current_user.org_id)
    document = next((doc for doc in docs if doc.id == document_id), None)
    if document is None:
        raise ApiError("not_found", "Document not found.", 404)
    query_rows = list(
        (
            await session.execute(
                select(AgentQuery)
                .where(
                    AgentQuery.org_id == current_user.org_id,
                    AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
                )
                .order_by(AgentQuery.created_at.desc())
                .limit(40)
            )
        ).scalars().all()
    )
    return suggest_related_knowledge(
        document=document,
        candidates=docs,
        recent_questions=[row.query_text for row in query_rows],
    )


async def get_knowledge_health_score(
    session: AsyncSession,
    current_user: CurrentUser,
) -> KnowledgeHealthScoreRead:
    import app.services.knowledge as knowledge_services

    visible_docs, _ = await knowledge_services._list_visible_documents_with_folders(
        session, current_user
    )
    counts = knowledge_services._health_counts_from_documents(
        visible_docs, org_id=current_user.org_id
    )
    return compute_knowledge_health_score(counts)
