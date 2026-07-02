from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.models.entities import KnowledgeDocument, KnowledgeDocumentChunk, KnowledgeSourceType
from app.schemas.domain import KnowledgeConversationTurn
from app.services.knowledge import (
    _build_standalone_retrieval_query,
    _build_retrieval_query,
    _fast_retrieval_query,
    _ground_generation,
    _loaded_datetime,
    _needs_llm_query_rewrite,
    _rank_chunks_by_terms,
    _rerank_hybrid_candidates,
)


def _chunk(text: str, *, document_id=None, index: int = 0) -> KnowledgeDocumentChunk:
    return KnowledgeDocumentChunk(
        id=uuid4(),
        org_id=uuid4(),
        document_id=document_id or uuid4(),
        chunk_index=index,
        content=text,
        chunk_text=text,
    )


def _doc(document_id, *, title: str, approved_days_ago: int) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=document_id,
        org_id=uuid4(),
        folder_id=uuid4(),
        title=title,
        source_type=KnowledgeSourceType.SOP,
        version="v1.0",
        owner_approver="Ops",
        file_name="source.md",
        file_mime_type="text/markdown",
        approved_at=datetime.now(UTC) - timedelta(days=approved_days_ago),
    )


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
    old_chunk = _chunk("Escalation approval policy", document_id=old_doc_id)
    new_chunk = _chunk("Escalation approval policy", document_id=new_doc_id)
    docs = {
        old_doc_id: _doc(old_doc_id, title="Old Escalation SOP", approved_days_ago=360),
        new_doc_id: _doc(new_doc_id, title="Current Escalation SOP", approved_days_ago=2),
    }

    ranked = _rerank_hybrid_candidates(
        [old_chunk, new_chunk],
        vector_scores={old_chunk.id: 0.65, new_chunk.id: 0.65},
        keyword_scores={old_chunk.id: 0.5, new_chunk.id: 0.5},
        doc_map=docs,
        query_text="Escalation SOP approval",
    )

    assert ranked[0][0] == new_chunk
    assert ranked[0][1] > ranked[1][1]


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


def test_loaded_datetime_reads_explicit_in_memory_value() -> None:
    now = datetime.now(UTC)
    doc = _doc(uuid4(), title="Policy", approved_days_ago=3)
    doc.created_at = now
    doc.updated_at = now

    assert _loaded_datetime(doc, "created_at") == now
    assert _loaded_datetime(doc, "updated_at") == now
