from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ApiError
from app.db.models.entities import KnowledgeFeedbackRating
from app.services.knowledge import (
    _compute_answer_confidence,
    _validate_client_safe_answer,
    record_knowledge_feedback,
)


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _WorkflowSession:
    def __init__(self, *, agent_query=None, existing_feedback=None):
        self.agent_query = agent_query
        self.existing_feedback = existing_feedback
        self.added = []
        self.flushed = False

    async def execute(self, stmt):
        stmt_text = str(stmt)
        if "agent_queries" in stmt_text:
            return _ScalarResult(self.agent_query)
        if "knowledge_query_feedback" in stmt_text:
            return _ScalarResult(self.existing_feedback)
        return _ScalarResult(None)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flushed = True
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid4()


def test_client_safe_validation_rejects_non_client_safe_source(knowledge_document_states, knowledge_chunk_factory) -> None:
    internal = knowledge_document_states["internal"]
    chunk = knowledge_chunk_factory(document_id=internal.id, text="Internal-only staffing rationale.")

    result = _validate_client_safe_answer(
        "Internal-only staffing rationale should not be shared.",
        None,
        [{"title": internal.title, "visibility": "internal_only", "text": chunk.chunk_text}],
    )

    assert result["valid"] is False
    assert "non_client_safe_source" in result["reasons"]


def test_confidence_formula_avoids_brittle_scores_but_penalizes_client_safe_violation(
    knowledge_document_states,
    knowledge_chunk_factory,
) -> None:
    doc = knowledge_document_states["client_safe"]
    chunk = knowledge_chunk_factory(document_id=doc.id, text="Client-safe escalation update.")

    confidence = _compute_answer_confidence(
        raw_confidence=0.95,
        matches=[(chunk, 0.9)],
        eligible_docs=[doc],
        doc_map={doc.id: doc},
        grounding={"grounded": True, "support": 0.95, "citation_validity": {"valid": True, "missing": []}},
        query_type="factual",
        has_structured_context=False,
        client_safe_result={"valid": False, "reasons": ["non_client_safe_source"]},
        fallback_level=0,
    )

    assert confidence["score"] < 0.75
    assert "client_safe_violation" in confidence["breakdown"]["penalties"]


@pytest.mark.asyncio
async def test_negative_missing_knowledge_feedback_persists_reason_without_creating_gap(
    knowledge_users,
    knowledge_query_factory,
) -> None:
    user = knowledge_users["delivery_manager"]
    query_id = uuid4()
    agent_query = knowledge_query_factory(
        query_id=query_id,
        org_id=user.org_id,
        user_id=user.id,
        retrieval_params={
            "confidence_score": 0.22,
            "query_type": "factual",
            "project": "Alpha",
            "department": "Ops",
            "answer_mode": "internal",
            "sources": [{"chunk_id": str(uuid4()), "document_id": str(uuid4())}],
        },
    )
    session = _WorkflowSession(agent_query=agent_query)

    result = await record_knowledge_feedback(
        session,  # type: ignore[arg-type]
        user,
        query_id=query_id,
        rating="down",
        comment="Missing hypercare checklist",
        feedback_reason="missing_knowledge",
    )

    assert result.feedback_reason == "missing_knowledge"
    feedback = next(item for item in session.added if item.__class__.__name__ == "KnowledgeQueryFeedback")
    assert feedback.feedback_reason == "missing_knowledge"
    assert feedback.answer_confidence == 0.22
    assert feedback.query_type == "factual"
    assert feedback.selected_source_ids
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_feedback_rejects_cross_org_query(knowledge_users, knowledge_query_factory) -> None:
    user = knowledge_users["delivery_manager"]
    other_query = knowledge_query_factory(org_id=knowledge_users["other_org_manager"].org_id)
    session = _WorkflowSession(agent_query=None)

    with pytest.raises(ApiError) as exc:
        await record_knowledge_feedback(
            session,  # type: ignore[arg-type]
            user,
            query_id=other_query.id,
            rating="down",
            feedback_reason="missing_knowledge",
        )

    assert exc.value.status_code == 404


def test_document_state_fixture_covers_readiness_matrix(knowledge_document_states) -> None:
    assert set(knowledge_document_states) == {
        "approved",
        "draft",
        "failed",
        "expired",
        "unindexed",
        "internal",
        "client_safe",
        "restricted",
    }
