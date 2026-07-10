"""Phase 11 — continuous learning: suggestions, summaries, related knowledge, quality."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable
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
    KnowledgeEvidenceLink,
    KnowledgeFeedbackRating,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeQueryFeedback,
    KnowledgeSourceType,
    KnowledgeSuggestion,
    KnowledgeSuggestionStatus,
    KnowledgeSuggestionType,
)
from app.schemas.domain import (
    KnowledgeDocumentAiSummaryRead,
    KnowledgeDuplicateCompareRead,
    KnowledgeDuplicateMatchRead,
    KnowledgeEvaluationReportRead,
    KnowledgeGapSuggestionRead,
    KnowledgeHealthScoreRead,
    KnowledgeLibraryHealthCountsRead,
    KnowledgeRelatedKnowledgeRead,
    KnowledgeRelatedItemRead,
    KnowledgeRetrievalQualityRead,
    KnowledgeSuggestionRead,
)
from app.services.knowledge.evaluation import build_evaluation_report, run_static_golden_evaluation
from app.services.knowledge.utils import KNOWLEDGE_AGENT_NAME, NO_APPROVED_ANSWER, _tokenize_search_text
from app.services.knowledge_intelligence import (
    analyze_chunk_content,
    detect_document_duplicates,
    extract_cross_references,
    extract_operational_entities,
    similarity_ratio,
)

# Optional AI hook — tests inject a mock; production may leave None (heuristics only).
AiSummaryFn = Callable[[str, dict[str, Any]], dict[str, Any]]

APPLYABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "department",
        "project",
        "source_type",
        "folder_id",
        "owner_approver",
        "executive_summary",
        "key_procedures",
        "important_warnings",
        "affected_departments",
        "related_document_ids",
    }
)

SOURCE_TYPE_HINTS: list[tuple[KnowledgeSourceType, tuple[str, ...]]] = [
    (KnowledgeSourceType.SOP, ("sop", "standard operating", "procedure")),
    (KnowledgeSourceType.GUIDE, ("guide", "how to", "playbook")),
    (KnowledgeSourceType.TRAINING_DOCUMENT, ("training", "onboarding", "curriculum")),
    (KnowledgeSourceType.PROJECT_CHARTER, ("charter", "scope", "objectives")),
    (KnowledgeSourceType.ESCALATION_NOTE, ("escalation", "incident", "severity")),
    (KnowledgeSourceType.LESSON_LEARNED, ("lesson", "retrospective", "postmortem", "post-mortem")),
]

FOLDER_KIND_FOR_SOURCE: dict[KnowledgeSourceType, KnowledgeFolderKind] = {
    KnowledgeSourceType.SOP: KnowledgeFolderKind.SOPS,
    KnowledgeSourceType.GUIDE: KnowledgeFolderKind.GUIDES,
    KnowledgeSourceType.LESSON_LEARNED: KnowledgeFolderKind.HISTORIES,
    KnowledgeSourceType.ESCALATION_NOTE: KnowledgeFolderKind.HISTORIES,
    KnowledgeSourceType.TRAINING_DOCUMENT: KnowledgeFolderKind.GUIDES,
    KnowledgeSourceType.PROJECT_CHARTER: KnowledgeFolderKind.GUIDES,
}

TITLE_STOPWORDS = frozenset({"the", "a", "an", "of", "for", "and", "to", "in", "on", "v1", "v2", "final", "draft", "copy"})


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
        recommendations.append("Library health is strong — continue monitoring retrieval quality trends.")

    band = "excellent" if score >= 85 else "good" if score >= 70 else "fair" if score >= 50 else "poor"
    return KnowledgeHealthScoreRead(
        score=score,
        band=band,
        recommendations=recommendations,
        ready_ratio=round(counts.ready_for_retrieval_count / total, 4),
    )


def _suggest_title(title: str, text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", (title or "").strip())
    if not cleaned:
        first_heading = next(
            (line.strip("# ").strip() for line in text.splitlines() if line.strip().startswith("#")),
            None,
        )
        return first_heading[:120] if first_heading else None
    lower = cleaned.lower()
    if any(token in lower for token in ("untitled", "document", "new file", "copy of")):
        entities = extract_operational_entities(text)
        sop_ids = entities.get("sop_identifiers") or []
        if sop_ids:
            return f"{sop_ids[0]} — Operational Procedure"
        words = [w for w in _tokenize_search_text(text)[:8] if w not in TITLE_STOPWORDS]
        if words:
            return " ".join(w.capitalize() for w in words[:6])
    if len(cleaned) < 8:
        return f"{cleaned} — Operational Guidance"
    return None


def _infer_source_type(title: str, text: str, current: KnowledgeSourceType | None) -> KnowledgeSourceType | None:
    haystack = f"{title}\n{text[:4000]}".lower()
    for source_type, hints in SOURCE_TYPE_HINTS:
        if any(hint in haystack for hint in hints):
            if current is None or current != source_type:
                return source_type
            return None
    return None


def _infer_tags(text: str) -> list[str]:
    entities = extract_operational_entities(text)
    tags: list[str] = []
    for key in ("projects", "phases", "roles", "sop_identifiers"):
        for value in entities.get(key) or []:
            tag = str(value).strip()
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= 8:
                return tags
    analysis = analyze_chunk_content(text)
    if analysis.get("contains_procedure"):
        tags.append("procedure")
    if analysis.get("contains_warning"):
        tags.append("warning")
    if analysis.get("contains_checklist"):
        tags.append("checklist")
    return tags[:8]


def build_content_suggestions_for_document(
    doc: KnowledgeDocument,
    *,
    folder: KnowledgeFolder | None,
    folders_by_kind: dict[KnowledgeFolderKind, KnowledgeFolder],
    text: str,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    body = (text or doc.extracted_text or "").strip()

    missing: list[str] = []
    if not (doc.owner_approver or "").strip():
        missing.append("owner_approver")
    if doc.effective_date is None:
        missing.append("effective_date")
    if not (doc.department or "").strip():
        missing.append("department")
    if not (doc.project or "").strip():
        missing.append("project")
    if missing:
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.MISSING_METADATA.value,
                "title": f"Complete metadata for '{doc.title}'",
                "detail": f"Missing fields: {', '.join(missing)}.",
                "proposed_changes": {field: None for field in missing},
                "evidence": {"missing_fields": missing},
            }
        )

    better_title = _suggest_title(doc.title, body)
    if better_title and better_title != doc.title:
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.BETTER_TITLE.value,
                "title": f"Improve title for '{doc.title}'",
                "detail": f"Suggested title: {better_title}",
                "proposed_changes": {"title": better_title},
                "evidence": {"current_title": doc.title},
            }
        )

    if not (doc.description or "").strip() and body:
        summary_preview = " ".join(body.split())[:240]
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.IMPROVED_SUMMARY.value,
                "title": f"Add summary for '{doc.title}'",
                "detail": "Document has no description; a short summary would improve browsing.",
                "proposed_changes": {"description": summary_preview},
                "evidence": {"char_count": len(body)},
            }
        )

    tags = _infer_tags(body)
    if tags:
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.MISSING_TAGS.value,
                "title": f"Suggested tags for '{doc.title}'",
                "detail": f"Proposed tags: {', '.join(tags)}",
                "proposed_changes": {"tags": tags},
                "evidence": {"tag_count": len(tags)},
            }
        )

    inferred_source = _infer_source_type(doc.title, body, doc.source_type)
    if inferred_source is not None:
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.SUGGESTED_SOURCE_TYPE.value,
                "title": f"Source type for '{doc.title}'",
                "detail": f"Content looks like {inferred_source.value} (currently {doc.source_type.value}).",
                "proposed_changes": {"source_type": inferred_source.value},
                "evidence": {"current_source_type": doc.source_type.value},
            }
        )
        target_kind = FOLDER_KIND_FOR_SOURCE.get(inferred_source)
        target_folder = folders_by_kind.get(target_kind) if target_kind else None
        if target_folder and folder and target_folder.id != folder.id:
            suggestions.append(
                {
                    "suggestion_type": KnowledgeSuggestionType.FOLDER_PLACEMENT.value,
                    "title": f"Move '{doc.title}' to {target_folder.name}",
                    "detail": f"Based on inferred source type {inferred_source.value}.",
                    "proposed_changes": {"folder_id": str(target_folder.id)},
                    "evidence": {"current_folder": folder.name, "suggested_folder": target_folder.name},
                }
            )

    entities = extract_operational_entities(body)
    departments = list(entities.get("departments") or [])
    if departments and not (doc.department or "").strip():
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.SUGGESTED_DEPARTMENT.value,
                "title": f"Department for '{doc.title}'",
                "detail": f"Suggested department: {departments[0]}",
                "proposed_changes": {"department": departments[0]},
                "evidence": {"candidates": departments[:5]},
            }
        )
    projects = list(entities.get("projects") or [])
    if projects and not (doc.project or "").strip():
        suggestions.append(
            {
                "suggestion_type": KnowledgeSuggestionType.SUGGESTED_PROJECT.value,
                "title": f"Project for '{doc.title}'",
                "detail": f"Suggested project: {projects[0]}",
                "proposed_changes": {"project": projects[0]},
                "evidence": {"candidates": projects[:5]},
            }
        )

    return suggestions


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
        related_projects=related_projects[:5],
        similar_questions=similar_questions[:5],
    )


def build_gap_resolution_suggestions(
    *,
    gap_query: str,
    occurrence_count: int,
    documents: list[KnowledgeDocument],
    historical_questions: list[str],
) -> KnowledgeGapSuggestionRead:
    tokens = set(_tokenize_search_text(gap_query))
    may_resolve: list[KnowledgeRelatedItemRead] = []
    should_update: list[KnowledgeRelatedItemRead] = []
    lessons: list[KnowledgeRelatedItemRead] = []
    for doc in documents:
        hay = f"{doc.title}\n{doc.extracted_text or ''}".lower()
        doc_tokens = set(_tokenize_search_text(hay)[:100])
        overlap = len(tokens & doc_tokens) / max(len(tokens), 1) if tokens else 0.0
        if overlap < 0.2:
            continue
        item = KnowledgeRelatedItemRead(
            document_id=doc.id,
            title=doc.title,
            source_type=doc.source_type.value,
            score=round(overlap, 4),
            reason="Lexical overlap with repeated gap query",
        )
        if doc.source_type == KnowledgeSourceType.LESSON_LEARNED:
            lessons.append(item)
        elif doc.status == KnowledgeDocumentStatus.APPROVED and overlap >= 0.35:
            may_resolve.append(item)
        elif overlap >= 0.25:
            should_update.append(item)

    may_resolve.sort(key=lambda item: item.score, reverse=True)
    should_update.sort(key=lambda item: item.score, reverse=True)
    create_topics: list[str] = []
    if occurrence_count >= 2 and not may_resolve:
        create_topics.append(f"Create a document covering: {gap_query[:160]}")
    similar = [
        q
        for q in historical_questions
        if q.lower() != gap_query.lower() and len(set(_tokenize_search_text(q)) & tokens) >= max(1, len(tokens) // 3)
    ][:5]
    return KnowledgeGapSuggestionRead(
        gap_query=gap_query,
        occurrence_count=occurrence_count,
        existing_documents_that_may_resolve=may_resolve[:5],
        documents_that_should_be_updated=should_update[:5],
        documents_that_should_be_created=create_topics,
        related_lessons_learned=lessons[:5],
        similar_historical_questions=similar,
        auto_resolved=False,
    )


def analyze_retrieval_quality(
    *,
    queries: list[AgentQuery],
    evidence_links: list[KnowledgeEvidenceLink],
    feedback: list[KnowledgeQueryFeedback],
    documents_by_id: dict[UUID, KnowledgeDocument],
) -> KnowledgeRetrievalQualityRead:
    selected_counts: Counter[str] = Counter()
    cited_docs: Counter[str] = Counter()
    weak_citations: list[str] = []
    conflicting: list[str] = []
    failures = 0
    low_confidence = 0
    confidence_values: list[float] = []

    links_by_query: dict[UUID, list[KnowledgeEvidenceLink]] = defaultdict(list)
    for link in evidence_links:
        links_by_query[link.agent_query_id].append(link)
        cited_docs[str(link.document_id)] += 1
        if link.relevance_score is not None and float(link.relevance_score) < 0.35:
            doc = documents_by_id.get(link.document_id)
            label = doc.title if doc else str(link.document_id)
            weak_citations.append(f"{label} (score={float(link.relevance_score):.2f})")

    feedback_by_query = {row.agent_query_id: row for row in feedback}
    answers_by_norm: dict[str, set[str]] = defaultdict(set)

    for query in queries:
        params = query.retrieval_params or {}
        conf = params.get("confidence_score")
        if conf is not None:
            try:
                confidence_values.append(float(conf))
                if float(conf) < 0.45:
                    low_confidence += 1
            except (TypeError, ValueError):
                pass
        if query.answer_text.strip() == NO_APPROVED_ANSWER or not links_by_query.get(query.id):
            failures += 1
        norm_q = " ".join(_tokenize_search_text(query.query_text)[:12])
        answers_by_norm[norm_q].add(query.answer_text.strip()[:200])
        fb = feedback_by_query.get(query.id)
        if fb and fb.selected_source_ids:
            for source_id in fb.selected_source_ids:
                selected_counts[str(source_id)] += 1
        elif fb and fb.rating == KnowledgeFeedbackRating.UP:
            for link in links_by_query.get(query.id, []):
                selected_counts[str(link.document_id)] += 1

    for answers in answers_by_norm.values():
        if len(answers) >= 2:
            conflicting.append(next(iter(answers))[:120])

    ignored = []
    for doc_id, cite_count in cited_docs.most_common(20):
        if selected_counts.get(doc_id, 0) == 0 and cite_count >= 2:
            doc = documents_by_id.get(UUID(doc_id)) if _is_uuid(doc_id) else None
            ignored.append(doc.title if doc else doc_id)

    frequently_selected = []
    for doc_id, count in selected_counts.most_common(8):
        doc = documents_by_id.get(UUID(doc_id)) if _is_uuid(doc_id) else None
        frequently_selected.append(f"{doc.title if doc else doc_id} ({count})")

    recommendations: list[str] = []
    if failures:
        recommendations.append("Investigate repeated retrieval failures and fill coverage gaps.")
    if weak_citations:
        recommendations.append("Review weakly cited documents for chunk quality and metadata.")
    if ignored:
        recommendations.append("Documents are retrieved but rarely selected — improve ranking or content clarity.")
    if low_confidence:
        recommendations.append("Low-confidence answers are trending — expand approved coverage for those topics.")
    if conflicting:
        recommendations.append("Resolve conflicting answers by consolidating overlapping procedures.")
    if not recommendations:
        recommendations.append("Retrieval quality looks stable — keep monitoring selected vs ignored sources.")

    avg_conf = round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else None
    return KnowledgeRetrievalQualityRead(
        frequently_selected_documents=frequently_selected,
        frequently_ignored_documents=ignored[:8],
        weak_citations=list(dict.fromkeys(weak_citations))[:10],
        conflicting_answers=conflicting[:5],
        repeated_retrieval_failures=failures,
        low_confidence_trend_count=low_confidence,
        average_confidence=avg_conf,
        recommendations=recommendations,
    )


def compare_documents_for_duplicates(
    left: KnowledgeDocument,
    right: KnowledgeDocument,
) -> KnowledgeDuplicateCompareRead:
    left_text = left.extracted_text or ""
    right_text = right.extracted_text or ""
    ratio = similarity_ratio(left_text, right_text) if left_text and right_text else 0.0
    warnings = detect_document_duplicates(
        org_id=str(left.org_id),
        document_id=str(left.id),
        title=left.title,
        version=left.version,
        file_name=left.file_name,
        checksum_sha256=left.checksum_sha256 or "",
        cleaned_text=left_text,
        candidates=[
            {
                "id": str(right.id),
                "title": right.title,
                "version": right.version,
                "file_name": right.file_name,
                "checksum_sha256": right.checksum_sha256 or "",
                "extracted_text": right_text,
                "status": right.status.value,
            }
        ],
    )
    kind = warnings[0]["kind"] if warnings else ("near_duplicate" if ratio >= 0.82 else "related")
    return KnowledgeDuplicateCompareRead(
        left_document_id=left.id,
        right_document_id=right.id,
        left_title=left.title,
        right_title=right.title,
        similarity=round(ratio, 4),
        kind=kind,
        left_preview=(left_text[:500] if left_text else left.title),
        right_preview=(right_text[:500] if right_text else right.title),
        can_merge=False,
        message="Compare documents carefully. Merging is never automatic.",
        warnings=warnings,
    )


def find_duplicate_matches(
    document: KnowledgeDocument,
    candidates: list[KnowledgeDocument],
) -> list[KnowledgeDuplicateMatchRead]:
    warnings = detect_document_duplicates(
        org_id=str(document.org_id),
        document_id=str(document.id),
        title=document.title,
        version=document.version,
        file_name=document.file_name,
        checksum_sha256=document.checksum_sha256 or "",
        cleaned_text=document.extracted_text or "",
        candidates=[
            {
                "id": str(other.id),
                "title": other.title,
                "version": other.version,
                "file_name": other.file_name,
                "checksum_sha256": other.checksum_sha256 or "",
                "extracted_text": other.extracted_text or "",
                "status": other.status.value,
            }
            for other in candidates
            if other.id != document.id
        ],
    )
    return [
        KnowledgeDuplicateMatchRead(
            document_id=UUID(str(item["document_id"])),
            title=str(item.get("title") or ""),
            similarity=float(item.get("similarity") or 0.0),
            kind=str(item.get("kind") or "near_duplicate"),
            message=str(item.get("message") or ""),
        )
        for item in warnings
    ]


def suggestion_to_read(row: KnowledgeSuggestion) -> KnowledgeSuggestionRead:
    return KnowledgeSuggestionRead(
        id=row.id,
        org_id=row.org_id,
        document_id=row.document_id,
        suggestion_type=row.suggestion_type,
        title=row.title,
        detail=row.detail,
        proposed_changes=row.proposed_changes or {},
        evidence=row.evidence or {},
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False


def _require_learning_manager(current_user: CurrentUser) -> None:
    if current_user.role not in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError("forbidden", "Knowledge learning tools require delivery manager access.", 403)


async def _visible_org_documents(session: AsyncSession, org_id: UUID) -> list[KnowledgeDocument]:
    result = await session.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.org_id == org_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def generate_content_suggestions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    document_id: UUID | None = None,
) -> list[KnowledgeSuggestionRead]:
    _require_learning_manager(current_user)
    docs = await _visible_org_documents(session, current_user.org_id)
    if document_id is not None:
        docs = [doc for doc in docs if doc.id == document_id]
        if not docs:
            raise ApiError("not_found", "Document not found.", 404)

    folders = list(
        (
            await session.execute(
                select(KnowledgeFolder).where(KnowledgeFolder.org_id == current_user.org_id)
            )
        ).scalars().all()
    )
    folder_by_id = {folder.id: folder for folder in folders}
    folders_by_kind = {folder.folder_kind: folder for folder in folders if folder.folder_kind != KnowledgeFolderKind.CUSTOM}

    existing = list(
        (
            await session.execute(
                select(KnowledgeSuggestion).where(
                    KnowledgeSuggestion.org_id == current_user.org_id,
                    KnowledgeSuggestion.status == KnowledgeSuggestionStatus.OPEN.value,
                )
            )
        ).scalars().all()
    )
    existing_keys = {
        (row.document_id, row.suggestion_type, str(sorted((row.proposed_changes or {}).items())))
        for row in existing
    }

    created: list[KnowledgeSuggestion] = []
    for doc in docs:
        payloads = build_content_suggestions_for_document(
            doc,
            folder=folder_by_id.get(doc.folder_id),
            folders_by_kind=folders_by_kind,
            text=doc.extracted_text or "",
        )
        for payload in payloads:
            key = (doc.id, payload["suggestion_type"], str(sorted(payload["proposed_changes"].items())))
            if key in existing_keys:
                continue
            row = KnowledgeSuggestion(
                org_id=current_user.org_id,
                document_id=doc.id,
                suggestion_type=payload["suggestion_type"],
                title=payload["title"],
                detail=payload["detail"],
                proposed_changes=payload["proposed_changes"],
                evidence=payload["evidence"],
                status=KnowledgeSuggestionStatus.OPEN.value,
            )
            session.add(row)
            created.append(row)
            existing_keys.add(key)
    await session.flush()
    return [suggestion_to_read(row) for row in created]


async def list_knowledge_suggestions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    status: str | None = None,
    document_id: UUID | None = None,
) -> list[KnowledgeSuggestionRead]:
    _require_learning_manager(current_user)
    stmt = select(KnowledgeSuggestion).where(KnowledgeSuggestion.org_id == current_user.org_id)
    if status:
        stmt = stmt.where(KnowledgeSuggestion.status == status)
    if document_id is not None:
        stmt = stmt.where(KnowledgeSuggestion.document_id == document_id)
    stmt = stmt.order_by(KnowledgeSuggestion.created_at.desc())
    rows = list((await session.execute(stmt)).scalars().all())
    return [suggestion_to_read(row) for row in rows]


async def dismiss_knowledge_suggestion(
    session: AsyncSession,
    current_user: CurrentUser,
    suggestion_id: UUID,
) -> KnowledgeSuggestionRead:
    _require_learning_manager(current_user)
    row = await session.get(KnowledgeSuggestion, suggestion_id)
    if row is None or row.org_id != current_user.org_id:
        raise ApiError("not_found", "Suggestion not found.", 404)
    row.status = KnowledgeSuggestionStatus.DISMISSED.value
    row.reviewed_by = current_user.id
    row.reviewed_at = datetime.now(timezone.utc)
    await session.flush()
    return suggestion_to_read(row)


async def apply_knowledge_suggestion(
    session: AsyncSession,
    current_user: CurrentUser,
    suggestion_id: UUID,
) -> KnowledgeSuggestionRead:
    """Apply a reviewed suggestion. Never changes document status or merges content."""
    _require_learning_manager(current_user)
    row = await session.get(KnowledgeSuggestion, suggestion_id)
    if row is None or row.org_id != current_user.org_id:
        raise ApiError("not_found", "Suggestion not found.", 404)
    if row.status not in {KnowledgeSuggestionStatus.OPEN.value, KnowledgeSuggestionStatus.ACCEPTED.value}:
        raise ApiError("conflict", "Suggestion is not open for apply.", 409)

    changes = {k: v for k, v in (row.proposed_changes or {}).items() if k in APPLYABLE_FIELDS and v is not None}
    if row.document_id is not None and changes:
        doc = await session.get(KnowledgeDocument, row.document_id)
        if doc is None or doc.org_id != current_user.org_id:
            raise ApiError("not_found", "Suggestion document not found.", 404)
        if "title" in changes:
            doc.title = str(changes["title"])[:500]
        if "description" in changes:
            doc.description = str(changes["description"])[:4000]
        if "department" in changes:
            doc.department = str(changes["department"])[:200]
        if "project" in changes:
            doc.project = str(changes["project"])[:200]
        if "owner_approver" in changes:
            doc.owner_approver = str(changes["owner_approver"])[:200]
        if "source_type" in changes:
            try:
                doc.source_type = KnowledgeSourceType(str(changes["source_type"]))
            except ValueError as exc:
                raise ApiError("validation_error", "Invalid source_type in suggestion.", 422) from exc
        if "folder_id" in changes:
            folder = await session.get(KnowledgeFolder, UUID(str(changes["folder_id"])))
            if folder is None or folder.org_id != current_user.org_id:
                raise ApiError("validation_error", "Invalid folder_id in suggestion.", 422)
            doc.folder_id = folder.id
        if "executive_summary" in changes:
            doc.executive_summary = str(changes["executive_summary"])
        if "key_procedures" in changes and isinstance(changes["key_procedures"], list):
            doc.key_procedures = [str(item) for item in changes["key_procedures"]]
        if "important_warnings" in changes and isinstance(changes["important_warnings"], list):
            doc.important_warnings = [str(item) for item in changes["important_warnings"]]
        if "affected_departments" in changes and isinstance(changes["affected_departments"], list):
            doc.affected_departments = [str(item) for item in changes["affected_departments"]]
        if "related_document_ids" in changes and isinstance(changes["related_document_ids"], list):
            doc.related_document_ids = [UUID(str(item)) for item in changes["related_document_ids"]]

    row.status = KnowledgeSuggestionStatus.APPLIED.value
    row.reviewed_by = current_user.id
    row.reviewed_at = datetime.now(timezone.utc)
    await session.flush()
    return suggestion_to_read(row)


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
    doc.summary_generated_at = datetime.now(timezone.utc)
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


async def get_gap_resolution_suggestions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    min_occurrences: int = 2,
) -> list[KnowledgeGapSuggestionRead]:
    _require_learning_manager(current_user)
    docs = await _visible_org_documents(session, current_user.org_id)
    queries = list(
        (
            await session.execute(
                select(AgentQuery).where(
                    AgentQuery.org_id == current_user.org_id,
                    AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
                )
            )
        ).scalars().all()
    )
    feedback_rows = list(
        (
            await session.execute(
                select(KnowledgeQueryFeedback).where(KnowledgeQueryFeedback.org_id == current_user.org_id)
            )
        ).scalars().all()
    )
    missing_query_ids = {
        row.agent_query_id
        for row in feedback_rows
        if row.feedback_reason == "missing_knowledge"
    }
    gap_counter: Counter[str] = Counter()
    historical = [row.query_text for row in queries]
    for row in queries:
        if row.answer_text.strip() == NO_APPROVED_ANSWER or row.id in missing_query_ids:
            key = " ".join(_tokenize_search_text(row.query_text))
            if key:
                gap_counter[key] += 1

    suggestions: list[KnowledgeGapSuggestionRead] = []
    query_by_norm = {" ".join(_tokenize_search_text(q.query_text)): q.query_text for q in queries}
    existing_gap_keys = {
        str((row.proposed_changes or {}).get("gap_query") or "")
        for row in (
            await session.execute(
                select(KnowledgeSuggestion).where(
                    KnowledgeSuggestion.org_id == current_user.org_id,
                    KnowledgeSuggestion.suggestion_type == KnowledgeSuggestionType.GAP_RESOLUTION.value,
                    KnowledgeSuggestion.status == KnowledgeSuggestionStatus.OPEN.value,
                )
            )
        ).scalars().all()
    }
    for norm, count in gap_counter.most_common(20):
        if count < min_occurrences:
            continue
        original = query_by_norm.get(norm, norm)
        suggestions.append(
            build_gap_resolution_suggestions(
                gap_query=original,
                occurrence_count=count,
                documents=docs,
                historical_questions=historical,
            )
        )
        if original in existing_gap_keys:
            continue
        # Persist as reviewable suggestion (never auto-resolve).
        session.add(
            KnowledgeSuggestion(
                org_id=current_user.org_id,
                document_id=None,
                suggestion_type=KnowledgeSuggestionType.GAP_RESOLUTION.value,
                title=f"Gap resolution: {original[:80]}",
                detail=f"Repeated {count} time(s). Review suggested documents before acting.",
                proposed_changes={"gap_query": original, "auto_resolved": False},
                evidence={"occurrence_count": count},
                status=KnowledgeSuggestionStatus.OPEN.value,
            )
        )
        existing_gap_keys.add(original)
    await session.flush()
    return suggestions


async def get_retrieval_quality_analysis(
    session: AsyncSession,
    current_user: CurrentUser,
) -> KnowledgeRetrievalQualityRead:
    _require_learning_manager(current_user)
    docs = await _visible_org_documents(session, current_user.org_id)
    docs_by_id = {doc.id: doc for doc in docs}
    queries = list(
        (
            await session.execute(
                select(AgentQuery).where(
                    AgentQuery.org_id == current_user.org_id,
                    AgentQuery.agent_name == KNOWLEDGE_AGENT_NAME,
                )
            )
        ).scalars().all()
    )
    query_ids = [row.id for row in queries]
    evidence: list[KnowledgeEvidenceLink] = []
    if query_ids:
        evidence = list(
            (
                await session.execute(
                    select(KnowledgeEvidenceLink).where(KnowledgeEvidenceLink.agent_query_id.in_(query_ids))
                )
            ).scalars().all()
        )
    feedback = list(
        (
            await session.execute(
                select(KnowledgeQueryFeedback).where(KnowledgeQueryFeedback.org_id == current_user.org_id)
            )
        ).scalars().all()
    )
    return analyze_retrieval_quality(
        queries=queries,
        evidence_links=evidence,
        feedback=feedback,
        documents_by_id=docs_by_id,
    )


async def list_document_duplicates(
    session: AsyncSession,
    current_user: CurrentUser,
    document_id: UUID,
) -> list[KnowledgeDuplicateMatchRead]:
    _require_learning_manager(current_user)
    docs = await _visible_org_documents(session, current_user.org_id)
    document = next((doc for doc in docs if doc.id == document_id), None)
    if document is None:
        raise ApiError("not_found", "Document not found.", 404)
    return find_duplicate_matches(document, docs)


async def compare_duplicate_documents(
    session: AsyncSession,
    current_user: CurrentUser,
    left_id: UUID,
    right_id: UUID,
) -> KnowledgeDuplicateCompareRead:
    _require_learning_manager(current_user)
    left = await session.get(KnowledgeDocument, left_id)
    right = await session.get(KnowledgeDocument, right_id)
    if (
        left is None
        or right is None
        or left.org_id != current_user.org_id
        or right.org_id != current_user.org_id
        or left.deleted_at is not None
        or right.deleted_at is not None
    ):
        raise ApiError("not_found", "One or both documents were not found.", 404)
    return compare_documents_for_duplicates(left, right)


async def run_knowledge_evaluation_report(
    session: AsyncSession,
    current_user: CurrentUser,
) -> KnowledgeEvaluationReportRead:
    _require_learning_manager(current_user)
    if current_user.role not in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN, AppRole.DELIVERY_MANAGER}:
        raise ApiError("forbidden", "Evaluation reports require manager access.", 403)
    raw = run_static_golden_evaluation()
    report = build_evaluation_report(raw)
    return KnowledgeEvaluationReportRead(**report)


async def get_knowledge_health_score(
    session: AsyncSession,
    current_user: CurrentUser,
) -> KnowledgeHealthScoreRead:
    import app.services.knowledge as knowledge_services

    visible_docs, _ = await knowledge_services._list_visible_documents_with_folders(session, current_user)
    counts = knowledge_services._health_counts_from_documents(visible_docs, org_id=current_user.org_id)
    return compute_knowledge_health_score(counts)
