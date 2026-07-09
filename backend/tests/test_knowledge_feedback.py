from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ApiError
from app.db.models.entities import KnowledgeFeedbackRating
from app.services.knowledge import _build_retrieval_params, record_knowledge_feedback


def _chunk(*, document_id=None, chunk_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
    )


def test_build_retrieval_params_includes_filters_and_sources() -> None:
    doc_id = uuid4()
    chunk = _chunk(document_id=doc_id)
    doc = SimpleNamespace(id=doc_id, title="Escalation SOP")

    params = _build_retrieval_params(
        query_text="How do escalations work?",
        retrieval_query="Project Alpha escalation approval",
        answer_mode="internal",
        include_histories=False,
        max_sources=5,
        min_relevance_score=0.3,
        project="Alpha",
        department="Ops",
        eligible_doc_count=12,
        has_embeddings=True,
        matches=[(chunk, 0.82)],
        doc_map={doc_id: doc},
        vector_scores={chunk.id: 0.75},
        keyword_scores={chunk.id: 0.6},
        confidence_score=0.71,
    )

    assert params["project"] == "Alpha"
    assert params["department"] == "Ops"
    assert params["include_histories"] is False
    assert params["confidence_score"] == 0.71
    assert len(params["sources"]) == 1
    assert params["sources"][0]["title"] == "Escalation SOP"
    assert params["sources"][0]["vector_score"] == 0.75
    assert params["sources"][0]["keyword_score"] == 0.6


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FeedbackSession:
    def __init__(self, agent_query, existing_feedback=None):
        self.agent_query = agent_query
        self.existing_feedback = existing_feedback
        self.added = []

    async def execute(self, _stmt):
        stmt_text = str(_stmt)
        if "agent_queries" in stmt_text:
            return _ScalarResult(self.agent_query)
        if "knowledge_query_feedback" in stmt_text:
            return _ScalarResult(self.existing_feedback)
        raise AssertionError(f"Unexpected query: {stmt_text}")

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_record_knowledge_feedback_creates_row() -> None:
    query_id = uuid4()
    user_id = uuid4()
    org_id = uuid4()
    current_user = SimpleNamespace(id=user_id, org_id=org_id)
    agent_query = SimpleNamespace(
        id=query_id,
        org_id=org_id,
        agent_name="operational_knowledge_agent",
        retrieval_params={"max_sources": 5},
    )
    session = _FeedbackSession(agent_query)

    result = await record_knowledge_feedback(
        session,  # type: ignore[arg-type]
        current_user,  # type: ignore[arg-type]
        query_id=query_id,
        rating="up",
    )

    assert result.query_id == query_id
    assert result.rating == "up"
    assert len(session.added) == 1
    assert session.added[0].rating == KnowledgeFeedbackRating.UP


@pytest.mark.asyncio
async def test_record_knowledge_feedback_rejects_unknown_query() -> None:
    current_user = SimpleNamespace(id=uuid4(), org_id=uuid4())
    session = _FeedbackSession(agent_query=None)

    with pytest.raises(ApiError) as exc:
        await record_knowledge_feedback(
            session,  # type: ignore[arg-type]
            current_user,  # type: ignore[arg-type]
            query_id=uuid4(),
            rating="down",
            comment="Wrong SOP cited",
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_record_knowledge_feedback_updates_existing_row() -> None:
    query_id = uuid4()
    user_id = uuid4()
    org_id = uuid4()
    current_user = SimpleNamespace(id=user_id, org_id=org_id)
    agent_query = SimpleNamespace(
        id=query_id,
        org_id=org_id,
        agent_name="operational_knowledge_agent",
        retrieval_params={"sources": []},
    )
    existing = SimpleNamespace(
        id=uuid4(),
        rating=KnowledgeFeedbackRating.UP,
        comment=None,
        created_at=datetime.now(UTC),
    )
    session = _FeedbackSession(agent_query, existing_feedback=existing)

    result = await record_knowledge_feedback(
        session,  # type: ignore[arg-type]
        current_user,  # type: ignore[arg-type]
        query_id=query_id,
        rating="down",
        comment="Missing approval step",
    )

    assert result.rating == "down"
    assert existing.rating == KnowledgeFeedbackRating.DOWN
    assert existing.comment == "Missing approval step"
    assert session.added == []
