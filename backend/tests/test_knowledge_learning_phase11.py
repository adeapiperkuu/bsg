"""Phase 11 continuous learning tests — AI services mocked, no real API calls."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from app.db.models.entities import (
    AgentQuery,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeEvidenceLink,
    KnowledgeFeedbackRating,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeQueryFeedback,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.schemas.domain import KnowledgeLibraryHealthCountsRead
from app.services.knowledge.evaluation import build_evaluation_report, run_static_golden_evaluation
from app.services.knowledge.learning import (
    analyze_retrieval_quality,
    build_content_suggestions_for_document,
    build_gap_resolution_suggestions,
    compare_documents_for_duplicates,
    compute_knowledge_health_score,
    find_duplicate_matches,
    generate_document_summary_payload,
    suggest_related_knowledge,
)
from app.services.knowledge.utils import KNOWLEDGE_AGENT_NAME, NO_APPROVED_ANSWER
from app.services.knowledge_intelligence import detect_document_duplicates


def _doc(
    *,
    title: str = "Escalation SOP",
    source_type: KnowledgeSourceType = KnowledgeSourceType.SOP,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.APPROVED,
    text: str = "",
    department: str | None = None,
    project: str | None = None,
    owner_approver: str = "Ops Lead",
    effective_date: date | None = date(2025, 1, 1),
    version: str = "v1.0",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=uuid4(),
        org_id=uuid4(),
        folder_id=uuid4(),
        title=title,
        source_type=source_type,
        version=version,
        visibility=KnowledgeVisibility.INTERNAL_ONLY,
        status=status,
        owner_approver=owner_approver,
        effective_date=effective_date,
        department=department,
        project=project,
        file_name=f"{title.lower().replace(' ', '-')}.md",
        file_mime_type="text/markdown",
        processing_status=KnowledgeProcessingStatus.READY,
        indexing_status=KnowledgeIndexingStatus.INDEXED,
        extracted_text=text,
        checksum_sha256="abc",
    )


def test_knowledge_health_score_penalizes_failures() -> None:
    healthy = compute_knowledge_health_score(
        KnowledgeLibraryHealthCountsRead(
            ready_for_retrieval_count=10,
            approved_and_indexed_count=10,
            draft_count=0,
            failed_processing_count=0,
            missing_metadata_count=0,
        )
    )
    unhealthy = compute_knowledge_health_score(
        KnowledgeLibraryHealthCountsRead(
            ready_for_retrieval_count=2,
            approved_and_indexed_count=2,
            failed_processing_count=5,
            expired_count=3,
            missing_metadata_count=4,
            needs_reindex_count=2,
            draft_count=1,
        )
    )
    assert healthy.score > unhealthy.score
    assert unhealthy.score < 70
    assert unhealthy.recommendations


def test_content_suggestions_are_deterministic() -> None:
    folder = KnowledgeFolder(
        id=uuid4(),
        org_id=uuid4(),
        name="SOPs",
        folder_kind=KnowledgeFolderKind.SOPS,
        display_order=0,
    )
    guides = KnowledgeFolder(
        id=uuid4(),
        org_id=folder.org_id,
        name="Guides",
        folder_kind=KnowledgeFolderKind.GUIDES,
        display_order=1,
    )
    doc = _doc(
        title="Untitled document",
        owner_approver="",
        effective_date=None,
        text=(
            "# Escalation Guide\n\n"
            "1. Notify delivery manager.\n"
            "Warning: Do not skip approval.\n"
            "Project Alpha requires QA sign-off."
        ),
        source_type=KnowledgeSourceType.SOP,
    )
    doc.folder_id = folder.id
    first = build_content_suggestions_for_document(
        doc,
        folder=folder,
        folders_by_kind={KnowledgeFolderKind.SOPS: folder, KnowledgeFolderKind.GUIDES: guides},
        text=doc.extracted_text or "",
    )
    second = build_content_suggestions_for_document(
        doc,
        folder=folder,
        folders_by_kind={KnowledgeFolderKind.SOPS: folder, KnowledgeFolderKind.GUIDES: guides},
        text=doc.extracted_text or "",
    )
    assert first
    assert [item["suggestion_type"] for item in first] == [item["suggestion_type"] for item in second]
    types = {item["suggestion_type"] for item in first}
    assert "missing_metadata" in types
    assert "better_title" in types or "suggested_source_type" in types


def test_gap_suggestions_never_auto_resolve() -> None:
    docs = [
        _doc(
            title="Escalation SOP",
            text="Escalation path for blocked delivery milestone with delivery manager ownership.",
        ),
        _doc(
            title="Incident Lesson",
            source_type=KnowledgeSourceType.LESSON_LEARNED,
            text="Lesson learned about blocked delivery milestone escalation delays.",
        ),
    ]
    suggestion = build_gap_resolution_suggestions(
        gap_query="blocked delivery milestone escalation",
        occurrence_count=3,
        documents=docs,
        historical_questions=[
            "blocked delivery milestone escalation",
            "how do we escalate blocked milestones",
            "unrelated payroll question",
        ],
    )
    assert suggestion.auto_resolved is False
    assert suggestion.occurrence_count == 3
    assert suggestion.existing_documents_that_may_resolve or suggestion.related_lessons_learned


def test_duplicate_detection_semantic_near_duplicate() -> None:
    left = "Escalation workflow for Project Alpha with approval and QA checklist steps."
    right = "Escalation workflow for Project Alpha with approval and QA checklist procedure."
    warnings = detect_document_duplicates(
        org_id=str(uuid4()),
        document_id=str(uuid4()),
        title="Escalation SOP",
        version="v2.0",
        file_name="escalation-v2.md",
        checksum_sha256="one",
        cleaned_text=left,
        candidates=[
            {
                "id": str(uuid4()),
                "title": "Escalation SOP Copy",
                "version": "v1.0",
                "file_name": "escalation.md",
                "checksum_sha256": "two",
                "extracted_text": right,
                "status": "approved",
            }
        ],
    )
    assert warnings
    assert warnings[0]["kind"] in {"near_duplicate", "overlapping_procedure", "semantic_near_duplicate"}


def test_duplicate_compare_never_merges() -> None:
    left = _doc(title="SOP A", text="1. Open tracker\n2. Notify manager\n3. Close ticket")
    right = _doc(title="SOP A", text="1. Open tracker\n2. Notify manager\n3. Close ticket", version="v0.9")
    right.status = KnowledgeDocumentStatus.EXPIRED
    comparison = compare_documents_for_duplicates(left, right)
    assert comparison.can_merge is False
    assert comparison.similarity >= 0.9
    matches = find_duplicate_matches(left, [left, right])
    assert matches


def test_related_knowledge_recommendations() -> None:
    primary = _doc(
        title="Escalation SOP",
        text="Escalation procedure for delivery blockers and milestone risk.",
        project="Alpha",
    )
    related = _doc(
        title="Escalation Guide",
        source_type=KnowledgeSourceType.GUIDE,
        text="Guide covering delivery blockers and milestone escalation steps.",
        project="Alpha",
    )
    lesson = _doc(
        title="Blocker Lesson",
        source_type=KnowledgeSourceType.LESSON_LEARNED,
        text="Lesson learned from delivery blockers on milestone risk.",
        project="Alpha",
    )
    result = suggest_related_knowledge(
        document=primary,
        candidates=[primary, related, lesson],
        recent_questions=["How do we escalate delivery blockers?"],
    )
    assert result.related_guides or result.related_lessons
    assert "Alpha" in result.related_projects
    assert result.similar_questions


def test_document_summary_generation_with_mocked_ai() -> None:
    heuristic = generate_document_summary_payload(
        title="Escalation SOP",
        text=(
            "1. Notify delivery manager.\n"
            "2. Log the incident.\n"
            "Warning: Do not skip approval.\n"
            "See SOP-014 for details."
        ),
        department="Operations",
    )
    assert heuristic["executive_summary"]
    assert heuristic["key_procedures"]
    assert heuristic["important_warnings"]
    assert "Operations" in heuristic["affected_departments"]

    def fake_ai(_text: str, _meta: dict) -> dict:
        return {
            "executive_summary": "Mocked executive summary",
            "key_procedures": ["Mock step"],
            "important_warnings": ["Mock warning"],
            "affected_departments": ["QA"],
            "related_document_ids": [],
        }

    mocked = generate_document_summary_payload(
        title="Escalation SOP",
        text="ignored body",
        ai_fn=fake_ai,
    )
    assert mocked["executive_summary"] == "Mocked executive summary"
    assert mocked["key_procedures"] == ["Mock step"]


def test_evaluation_report_tracks_metrics_and_regressions() -> None:
    current = run_static_golden_evaluation()
    assert current["total"] >= 8
    assert current["pass_rate"] == 1.0
    assert "answer_quality" in current
    assert "confidence_accuracy" in current
    assert "client_safe_compliance" in current
    report = build_evaluation_report(current, previous={**current, "pass_rate": 1.0, "answer_quality": 1.1})
    assert "report_text" in report
    assert report["regressions"]
    assert "answer_quality" in report["regressions"][0]


def test_retrieval_quality_analysis() -> None:
    org_id = uuid4()
    doc = _doc(title="Selected SOP", text="selected content")
    ignored = _doc(title="Ignored Guide", source_type=KnowledgeSourceType.GUIDE, text="ignored")
    q1 = AgentQuery(
        id=uuid4(),
        user_id=uuid4(),
        org_id=org_id,
        agent_name=KNOWLEDGE_AGENT_NAME,
        query_text="escalation path",
        answer_text="Use the SOP",
        retrieval_params={"confidence_score": 0.3},
    )
    q2 = AgentQuery(
        id=uuid4(),
        user_id=uuid4(),
        org_id=org_id,
        agent_name=KNOWLEDGE_AGENT_NAME,
        query_text="missing topic",
        answer_text=NO_APPROVED_ANSWER,
        retrieval_params={"confidence_score": 0.1},
    )
    evidence = [
        KnowledgeEvidenceLink(
            id=uuid4(),
            org_id=org_id,
            agent_query_id=q1.id,
            document_id=doc.id,
            citation_label="Selected SOP",
            relevance_score=0.9,
        ),
        KnowledgeEvidenceLink(
            id=uuid4(),
            org_id=org_id,
            agent_query_id=q1.id,
            document_id=ignored.id,
            citation_label="Ignored Guide",
            relevance_score=0.2,
        ),
    ]
    feedback = [
        KnowledgeQueryFeedback(
            id=uuid4(),
            org_id=org_id,
            agent_query_id=q1.id,
            user_id=uuid4(),
            rating=KnowledgeFeedbackRating.UP,
            selected_source_ids=[str(doc.id)],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    ]
    analysis = analyze_retrieval_quality(
        queries=[q1, q2],
        evidence_links=evidence,
        feedback=feedback,
        documents_by_id={doc.id: doc, ignored.id: ignored},
    )
    assert analysis.repeated_retrieval_failures >= 1
    assert analysis.low_confidence_trend_count >= 1
    assert analysis.weak_citations
    assert analysis.frequently_selected_documents
    assert analysis.recommendations
