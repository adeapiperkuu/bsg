from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.db.models.entities import KnowledgeDocument, KnowledgeDocumentChunk, KnowledgeSourceType
from app.schemas.domain import KnowledgeConversationTurn, KnowledgeRetrievalSettingsRead
from app.services.knowledge import (
    _analyze_extraction_quality,
    _build_standalone_retrieval_query,
    _compute_answer_confidence,
    _build_retrieval_query,
    _diversify_ranked_candidates,
    _filter_latest_valid_versions,
    _fast_retrieval_query,
    _ground_generation,
    _loaded_datetime,
    _needs_llm_query_rewrite,
    _query_rewrite_gate,
    _rank_chunks_by_terms,
    _rerank_hybrid_candidates,
    _validate_answer_citations,
    _validate_client_safe_answer,
    classify_knowledge_query,
    normalize_conversation_history,
)


def _chunk(
    text: str,
    *,
    document_id=None,
    index: int = 0,
    section_title: str | None = None,
) -> KnowledgeDocumentChunk:
    return KnowledgeDocumentChunk(
        id=uuid4(),
        org_id=uuid4(),
        document_id=document_id or uuid4(),
        chunk_index=index,
        section_title=section_title,
        content=text,
        chunk_text=text,
    )


def _doc(
    document_id,
    *,
    title: str,
    approved_days_ago: int,
    source_type: KnowledgeSourceType = KnowledgeSourceType.SOP,
    version: str = "v1.0",
    project: str | None = None,
    department: str | None = None,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=document_id,
        org_id=uuid4(),
        folder_id=uuid4(),
        title=title,
        source_type=source_type,
        version=version,
        project=project,
        department=department,
        owner_approver="Ops",
        file_name="source.md",
        file_mime_type="text/markdown",
        approved_at=datetime.now(timezone.utc) - timedelta(days=approved_days_ago),
    )


def test_retrieval_settings_validation_enforces_safe_bounds() -> None:
    settings = KnowledgeRetrievalSettingsRead(
        only_approved=False,
        max_sources=12,
        max_candidates=2,
        min_relevance=1.5,
        min_confidence=-1,
    )

    assert settings.only_approved is True
    assert settings.max_sources == 10
    assert settings.max_candidates == 10
    assert settings.min_relevance == 1.0
    assert settings.min_confidence == 0.0


def test_query_classification_examples() -> None:
    assert classify_knowledge_query("What is the escalation threshold?") == "factual"
    assert classify_knowledge_query("How do I escalate a missed milestone?") == "procedural"
    assert classify_knowledge_query("Give me an overview of rework handling") == "broad_summary"
    assert classify_knowledge_query("Why does this process keep failing?") == "troubleshooting"
    assert classify_knowledge_query("What happened during Batch 14?") == "historical"
    assert classify_knowledge_query("Compare the old and new approval process") == "comparative"
    assert classify_knowledge_query("Which compliance policy is required?") == "policy_or_compliance"


def test_retrieval_query_includes_recent_history_for_follow_up() -> None:
    history = [
        KnowledgeConversationTurn(
            role="user",
            content="How does Project Alpha handle client escalations?",
        ),
        KnowledgeConversationTurn(
            role="assistant",
            content="Use the escalation SOP and notify the delivery manager.",
        ),
    ]

    query = _build_retrieval_query("What about approvals?", history)

    assert "Project Alpha" in query
    assert "What about approvals?" in query


async def test_standalone_retrieval_query_skips_rewrite_without_history(monkeypatch) -> None:
    def fail_if_called():
        raise AssertionError("OpenAI client should not be used for first-turn queries")

    monkeypatch.setattr("app.services.knowledge.get_openai_client", fail_if_called)

    query = await _build_standalone_retrieval_query("What is the escalation SOP?", [])

    assert query == "What is the escalation SOP?"


async def test_standalone_retrieval_query_preserves_follow_up_rewrite(monkeypatch) -> None:
    class _Message:
        content = "Project Alpha approval workflow"

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    class _Completions:
        async def create(self, **_kwargs):
            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr("app.services.knowledge.get_openai_client", lambda: _Client())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    history = [
        KnowledgeConversationTurn(
            role="user",
            content="How does Project Alpha handle client escalations?",
        ),
    ]

    query = await _build_standalone_retrieval_query("What about approvals?", history)

    assert query == "Project Alpha approval workflow"


def test_fast_retrieval_skips_llm_rewrite_for_self_contained_follow_up() -> None:
    history = [
        KnowledgeConversationTurn(
            role="user",
            content="How does Project Alpha handle client escalations?",
        ),
    ]

    assert _needs_llm_query_rewrite("What is the calibration SOP?", history) is False
    query = _fast_retrieval_query("What is the calibration SOP?", history)
    assert query == "What is the calibration SOP?"


def test_fast_retrieval_rewrite_needed_for_pronoun_follow_up() -> None:
    history = [
        KnowledgeConversationTurn(
            role="user",
            content="How does Project Alpha handle client escalations?",
        ),
    ]

    assert _needs_llm_query_rewrite("What about that?", history) is True


def test_keyword_ranker_preserves_exact_operational_terms() -> None:
    alpha = _chunk(
        "Project Alpha escalation SOP requires a delivery manager approval within one business day."
    )
    generic = _chunk("Escalation approval is reviewed by the operations team.")

    ranked = _rank_chunks_by_terms("Project Alpha escalation approval", [generic, alpha])

    assert ranked[0][0] == alpha
    assert ranked[0][1] > ranked[1][1]


def test_hybrid_rerank_boosts_recent_approved_documents() -> None:
    old_doc_id = uuid4()
    new_doc_id = uuid4()
    old_chunk = _chunk("Escalation approval policy legacy", document_id=old_doc_id)
    new_chunk = _chunk("Escalation approval policy current", document_id=new_doc_id)
    docs = {
        old_doc_id: _doc(old_doc_id, title="Old Escalation SOP", approved_days_ago=360),
        new_doc_id: _doc(new_doc_id, title="Current Escalation SOP", approved_days_ago=2),
    }

    ranked = _rerank_hybrid_candidates(
        [old_chunk, new_chunk],
        vector_scores={old_chunk.id: 0.65, new_chunk.id: 0.65},
        keyword_scores={old_chunk.id: 0.5, new_chunk.id: 0.5},
        doc_map=docs,
        folders_map={},
        query_text="Escalation SOP approval",
    )

    assert ranked[0][0] == new_chunk
    assert ranked[0][1] > ranked[1][1]


def test_exact_identifier_boost_outranks_semantic_neighbor() -> None:
    exact_doc_id = uuid4()
    generic_doc_id = uuid4()
    exact = _chunk("SOP-014 requires escalation approval stage beta.", document_id=exact_doc_id)
    generic = _chunk("The escalation procedure requires approval by the delivery manager.", document_id=generic_doc_id)
    docs = {
        exact_doc_id: _doc(exact_doc_id, title="Escalation SOP-014", approved_days_ago=30),
        generic_doc_id: _doc(generic_doc_id, title="Escalation Guide", approved_days_ago=1),
    }

    ranked = _rerank_hybrid_candidates(
        [generic, exact],
        vector_scores={generic.id: 0.82, exact.id: 0.68},
        keyword_scores={generic.id: 0.55, exact.id: 0.6},
        doc_map=docs,
        folders_map={},
        query_text="What does SOP-014 say about approval stage beta?",
    )

    assert ranked[0][0] == exact


def test_procedural_query_boosts_steps_and_sops() -> None:
    sop_doc_id = uuid4()
    note_doc_id = uuid4()
    steps = _chunk("1. Confirm milestone miss.\n2. Notify approver.\n3. Escalate to delivery manager.", document_id=sop_doc_id)
    prose = _chunk("Escalation is discussed in project notes and may involve managers.", document_id=note_doc_id)
    docs = {
        sop_doc_id: _doc(sop_doc_id, title="Milestone Escalation SOP", approved_days_ago=20),
        note_doc_id: _doc(note_doc_id, title="Project Notes", approved_days_ago=1, source_type=KnowledgeSourceType.ESCALATION_NOTE),
    }

    ranked = _rerank_hybrid_candidates(
        [prose, steps],
        vector_scores={prose.id: 0.7, steps.id: 0.7},
        keyword_scores={prose.id: 0.4, steps.id: 0.4},
        doc_map=docs,
        folders_map={},
        query_text="How do I escalate a missed milestone?",
        query_type="procedural",
    )

    assert ranked[0][0] == steps


def test_historical_query_boosts_lessons() -> None:
    lesson_doc_id = uuid4()
    sop_doc_id = uuid4()
    lesson = _chunk("Batch 14 lesson learned: warning signs were missed and the issue was resolved on 2025-06-02.", document_id=lesson_doc_id)
    sop = _chunk("Batch processing follows the standard approval workflow.", document_id=sop_doc_id)
    docs = {
        lesson_doc_id: _doc(lesson_doc_id, title="Batch 14 Lesson", approved_days_ago=40, source_type=KnowledgeSourceType.LESSON_LEARNED),
        sop_doc_id: _doc(sop_doc_id, title="Batch SOP", approved_days_ago=1),
    }

    ranked = _rerank_hybrid_candidates(
        [sop, lesson],
        vector_scores={sop.id: 0.74, lesson.id: 0.7},
        keyword_scores={sop.id: 0.4, lesson.id: 0.4},
        doc_map=docs,
        folders_map={},
        query_text="What happened during Batch 14?",
        query_type="historical",
    )

    assert ranked[0][0] == lesson


def test_broad_summary_diversifies_repeated_sections() -> None:
    doc_id = uuid4()
    other_doc_id = uuid4()
    first = _chunk("Rework handling overview and intake rules.", document_id=doc_id, section_title="Overview")
    duplicate = _chunk("Rework handling overview and intake rules.", document_id=doc_id, section_title="Overview")
    other = _chunk("Rework reporting metrics and closure rules.", document_id=other_doc_id, section_title="Metrics")

    diversified = _diversify_ranked_candidates(
        [(first, 0.9), (duplicate, 0.88), (other, 0.82)],
        query_type="broad_summary",
        max_sources=3,
        rejected_reasons={},
    )

    assert [chunk for chunk, _ in diversified] == [first, other]


def test_version_preference_keeps_latest_valid_version() -> None:
    old_id = uuid4()
    new_id = uuid4()
    old = _doc(old_id, title="Approval SOP", approved_days_ago=60, version="v1")
    new = _doc(new_id, title="Approval SOP", approved_days_ago=5, version="Version 2.1")

    selected, diagnostics = _filter_latest_valid_versions([old, new])

    assert selected == [new]
    assert diagnostics


def test_grounding_check_accepts_supported_claims() -> None:
    result = _ground_generation(
        "Project Alpha requires delivery manager approval for escalation.",
        None,
        [{"text": "Project Alpha requires delivery manager approval for escalation."}],
        "",
    )

    assert result["grounded"] is True
    assert result["support"] == 1.0


def test_grounding_check_flags_unsupported_claims() -> None:
    result = _ground_generation(
        "Project Alpha requires executive approval and a 48 hour client notice.",
        None,
        [{"text": "Project Alpha requires delivery manager approval for escalation."}],
        "",
    )

    assert result["grounded"] is False
    assert result["support"] < 0.65


def test_history_normalization_limits_truncates_and_drops_invalid_turns() -> None:
    normalized = normalize_conversation_history(
        [
            KnowledgeConversationTurn(role="user", content="   "),
            KnowledgeConversationTurn(role="user", content="A" * 2200),
            KnowledgeConversationTurn(role="assistant", content="Use the escalation SOP."),
            KnowledgeConversationTurn(role="assistant", content="Use the escalation SOP."),
        ],
        max_turns=2,
        max_turn_chars=20,
    )

    assert len(normalized.history) == 2
    assert normalized.truncated is True
    assert normalized.messages_dropped == 2
    assert normalized.history[0].content.endswith("...")


def test_rewrite_gate_explains_follow_up_decision() -> None:
    diagnostics = _query_rewrite_gate(
        "What about this?",
        [KnowledgeConversationTurn(role="user", content="How do escalations work?")],
        prefer_fast=True,
    )

    assert diagnostics["attempted"] is True
    assert diagnostics["reason"] == "follow_up_reference"


def test_grounding_flags_unsupported_numbers_and_citations() -> None:
    result = _ground_generation(
        "Project Alpha requires 48 hour notice [Doc: Unknown SOP].",
        None,
        [{"title": "Escalation SOP", "text": "Project Alpha requires delivery manager notice."}],
        "",
    )

    assert result["support"] < 1.0
    assert "number:48" in result["unsupported_entities"]
    assert result["citation_validity"]["valid"] is False
    assert result["citation_validity"]["unknown"] == ["Unknown SOP"]


def test_client_safe_validator_rejects_internal_language() -> None:
    result = _validate_client_safe_answer(
        "The root cause is internal-only staffing pressure.",
        None,
        [{"title": "Client Update", "visibility": "client_safe"}],
    )

    assert result["valid"] is False
    assert result["reasons"]


def test_confidence_formula_bands_low_grounding() -> None:
    chunk = _chunk("Escalation requires manager approval.")
    doc = _doc(chunk.document_id, title="Escalation SOP", approved_days_ago=2)
    confidence = _compute_answer_confidence(
        raw_confidence=0.9,
        matches=[(chunk, 0.8)],
        eligible_docs=[doc],
        doc_map={doc.id: doc},
        grounding={"grounded": False, "support": 0.3, "citation_validity": {"missing": ["no_inline_citation"]}},
        query_type="factual",
        has_structured_context=False,
        client_safe_result=None,
        fallback_level=0,
    )

    assert confidence["band"] in {"low", "very_low"}
    assert confidence["breakdown"]["penalties"]


def test_analyze_extraction_quality_flags_scanned_pdf() -> None:
    warnings, score, diagnostics = _analyze_extraction_quality(
        file_name="scan.pdf",
        raw_text="tiny",
        cleaned_text="short",
        sections=[{"text": "short", "page_number": 1}],
        chunks=[{"chunk_text": "short"}],
        page_count=5,
    )
    assert any("OCR" in warning or "image-heavy" in warning for warning in warnings)
    assert score < 100
    assert diagnostics["page_count"] == 5


def test_loaded_datetime_reads_explicit_in_memory_value() -> None:
    now = datetime.now(timezone.utc)
    doc = _doc(uuid4(), title="Policy", approved_days_ago=3)
    doc.created_at = now
    doc.updated_at = now

    assert _loaded_datetime(doc, "created_at") == now
    assert _loaded_datetime(doc, "updated_at") == now
