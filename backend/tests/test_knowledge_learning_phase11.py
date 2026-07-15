"""Knowledge helpers retained after Continuous Learning removal."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.db.models.entities import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.schemas.domain import KnowledgeLibraryHealthCountsRead
from app.services.knowledge.evaluation import build_evaluation_report, run_static_golden_evaluation
from app.services.knowledge.learning import (
    compute_knowledge_health_score,
    generate_document_summary_payload,
    suggest_related_knowledge,
)


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


def test_related_knowledge_scoring() -> None:
    primary = _doc(
        title="Escalation SOP",
        text="Escalate delivery blockers to the delivery manager.",
        project="Alpha",
    )
    related = _doc(
        title="Delivery Escalation Guide",
        source_type=KnowledgeSourceType.GUIDE,
        text="Guide for escalating delivery blockers and milestone risk.",
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
