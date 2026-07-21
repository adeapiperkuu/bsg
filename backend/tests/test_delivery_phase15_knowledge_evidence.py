"""Phase 15.5 — Delivery knowledge evidence (reuse Knowledge RAG) unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.delivery.services.delivery_knowledge_evidence_service import (
    SOURCE_CATEGORY_HINTS,
    build_delivery_knowledge_query,
    citation_from_chunk,
    retrieve_delivery_knowledge_evidence,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, KnowledgeSourceType


def test_query_shaping_includes_delivery_signals() -> None:
    query = build_delivery_knowledge_query(
        project_name="Atlas",
        root_cause_labels=["Review turnaround"],
        risk_titles=["QA backlog"],
        bottleneck_titles=["Annotator capacity"],
        milestone_names=["UAT"],
        focus="escalation history",
    )
    assert "Atlas" in query
    assert "Review turnaround" in query
    assert "QA backlog" in query
    assert "Annotator capacity" in query
    assert "UAT" in query
    assert "escalation history" in query


def test_source_category_hints_cover_requested_sources() -> None:
    assert SOURCE_CATEGORY_HINTS["project_charters"] == KnowledgeSourceType.PROJECT_CHARTER.value
    assert SOURCE_CATEGORY_HINTS["delivery_sops"] == KnowledgeSourceType.SOP.value
    assert SOURCE_CATEGORY_HINTS["escalation_history"] == KnowledgeSourceType.ESCALATION_NOTE.value
    assert SOURCE_CATEGORY_HINTS["retrospectives"] == KnowledgeSourceType.LESSON_LEARNED.value
    assert SOURCE_CATEGORY_HINTS["pm_notes"] == KnowledgeSourceType.GUIDE.value
    assert SOURCE_CATEGORY_HINTS["meeting_notes"] == KnowledgeSourceType.GUIDE.value
    assert SOURCE_CATEGORY_HINTS["risk_logs"] == KnowledgeSourceType.ESCALATION_NOTE.value


def test_citation_from_chunk_truncates_excerpt() -> None:
    long_text = "x" * 500
    citation = citation_from_chunk(
        {
            "document_id": str(uuid4()),
            "chunk_id": str(uuid4()),
            "title": "Delivery SOP",
            "source_type": "sop",
            "text": long_text,
            "relevance_score": 0.81,
        }
    )
    assert citation["title"] == "Delivery SOP"
    assert citation["source_type"] == "sop"
    assert len(citation["excerpt"]) <= 400
    assert citation["relevance_score"] == 0.81


@pytest.mark.asyncio
async def test_retrieve_fail_open_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service.get_settings",
        lambda: SimpleNamespace(
            delivery_knowledge_evidence_enabled=False,
            delivery_knowledge_evidence_max_sources=5,
        ),
    )
    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="pm@bsg.dev",
        is_active=True,
    )
    result = await retrieve_delivery_knowledge_evidence(
        AsyncMock(),
        user,
        project_id=uuid4(),
    )
    assert result["citations"] == []
    assert result["empty_reason"] == "feature_disabled"


@pytest.mark.asyncio
async def test_retrieve_excludes_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service.get_settings",
        lambda: SimpleNamespace(
            delivery_knowledge_evidence_enabled=True,
            delivery_knowledge_evidence_max_sources=5,
        ),
    )
    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.CLIENT,
        email="client@bsg.dev",
        is_active=True,
    )
    result = await retrieve_delivery_knowledge_evidence(
        AsyncMock(),
        user,
        project_id=uuid4(),
    )
    assert result["citations"] == []
    assert result["empty_reason"] == "clients_excluded"


@pytest.mark.asyncio
async def test_retrieve_uses_knowledge_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    doc_id = uuid4()
    chunk_id = uuid4()
    project = SimpleNamespace(id=project_id, name="Atlas")

    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service.get_settings",
        lambda: SimpleNamespace(
            delivery_knowledge_evidence_enabled=True,
            delivery_knowledge_evidence_max_sources=5,
        ),
    )
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service.get_visible_project",
        AsyncMock(return_value=project),
    )

    retrieval = SimpleNamespace(
        matches=[(SimpleNamespace(), 0.9)],
        doc_map={},
        folders_map={},
        empty_eligible_reason=None,
        applied_filters={"project": "Atlas"},
        fallback_level=0,
    )
    retrieve_mock = AsyncMock(return_value=retrieval)
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service._retrieve_knowledge_context",
        retrieve_mock,
    )
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service._build_context_chunks_from_matches",
        lambda *_args, **_kwargs: [
            {
                "document_id": str(doc_id),
                "chunk_id": str(chunk_id),
                "title": "Atlas Charter",
                "source_type": "project_charter",
                "text": "Charter scope includes delivery gates.",
                "relevance_score": 0.9,
            }
        ],
    )

    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="pm@bsg.dev",
        is_active=True,
    )
    result = await retrieve_delivery_knowledge_evidence(
        MagicMock(),
        user,
        project_id=project_id,
        risk_titles=["Scope creep"],
    )

    assert len(result["citations"]) == 1
    assert result["citations"][0]["title"] == "Atlas Charter"
    assert result["project_name"] == "Atlas"
    retrieve_mock.assert_awaited_once()
    kwargs = retrieve_mock.await_args.kwargs
    assert kwargs["project"] == "Atlas"
    assert "sop" in kwargs["source_types"]
    assert "project_charter" in kwargs["source_types"]


@pytest.mark.asyncio
async def test_retrieve_fail_open_on_pipeline_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service.get_settings",
        lambda: SimpleNamespace(
            delivery_knowledge_evidence_enabled=True,
            delivery_knowledge_evidence_max_sources=5,
        ),
    )
    monkeypatch.setattr(
        "app.agents.delivery.services.delivery_knowledge_evidence_service.get_visible_project",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="pm@bsg.dev",
        is_active=True,
    )
    result = await retrieve_delivery_knowledge_evidence(
        AsyncMock(),
        user,
        project_id=uuid4(),
    )
    assert result["citations"] == []
    assert result["empty_reason"] == "retrieval_failed"
