from __future__ import annotations

import socket
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.security import CurrentUser
from app.db.models import AppRole
from app.db.models.entities import (
    AgentQuery,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentStatus,
    KnowledgeFeedbackRating,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeIndexingStatus,
    KnowledgeProcessingStatus,
    KnowledgeQueryFeedback,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.schemas.domain import (
    KnowledgeAskRead,
    KnowledgeDocumentRead,
    KnowledgeFolderRead,
    KnowledgeRetrievalSettingsRead,
    KnowledgeStructuredAnswer,
)


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original_connect = socket.socket.connect

    def _blocked_connect(self: socket.socket, address):
        host = address[0] if isinstance(address, tuple) and address else ""
        if host in {"127.0.0.1", "::1", "localhost"}:
            return original_connect(self, address)
        raise AssertionError(f"Unexpected external network call to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    yield


@pytest.fixture
def org_a() -> UUID:
    return uuid4()


@pytest.fixture
def org_b() -> UUID:
    return uuid4()


def make_current_user(*, org_id: UUID, role: AppRole, email: str | None = None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        role=role,
        email=email or f"{role.value.replace('_', '-')}@example.com",
        is_active=True,
    )


@pytest.fixture
def knowledge_users(org_a: UUID, org_b: UUID) -> dict[str, CurrentUser]:
    return {
        "client": make_current_user(org_id=org_a, role=AppRole.CLIENT, email="client@example.com"),
        "delivery_manager": make_current_user(org_id=org_a, role=AppRole.DELIVERY_MANAGER, email="dm@example.com"),
        "leadership": make_current_user(org_id=org_a, role=AppRole.BSG_LEADERSHIP, email="lead@example.com"),
        "admin": make_current_user(org_id=org_a, role=AppRole.SUPER_ADMIN, email="admin@example.com"),
        "other_org_manager": make_current_user(org_id=org_b, role=AppRole.DELIVERY_MANAGER, email="dm-b@example.com"),
    }


@pytest.fixture
def knowledge_folder_factory(org_a: UUID) -> Callable[..., KnowledgeFolder]:
    def _factory(
        *,
        folder_id: UUID | None = None,
        org_id: UUID | None = None,
        name: str = "SOPs",
        kind: KnowledgeFolderKind = KnowledgeFolderKind.SOPS,
    ) -> KnowledgeFolder:
        return KnowledgeFolder(
            id=folder_id or uuid4(),
            org_id=org_id or org_a,
            name=name,
            folder_kind=kind,
            display_order=0,
        )

    return _factory


@pytest.fixture
def knowledge_document_factory(
    org_a: UUID,
    knowledge_folder_factory: Callable[..., KnowledgeFolder],
) -> Callable[..., KnowledgeDocument]:
    def _factory(
        *,
        doc_id: UUID | None = None,
        org_id: UUID | None = None,
        folder: KnowledgeFolder | None = None,
        title: str = "Escalation SOP",
        status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.APPROVED,
        processing_status: KnowledgeProcessingStatus = KnowledgeProcessingStatus.READY,
        indexing_status: KnowledgeIndexingStatus = KnowledgeIndexingStatus.INDEXED,
        visibility: KnowledgeVisibility = KnowledgeVisibility.INTERNAL_ONLY,
        source_type: KnowledgeSourceType = KnowledgeSourceType.SOP,
        owner_approver: str = "Ops Lead",
        effective_date: date | None = date(2026, 1, 1),
        approved_days_ago: int = 3,
    ) -> KnowledgeDocument:
        resolved_org = org_id or org_a
        resolved_folder = folder or knowledge_folder_factory(org_id=resolved_org)
        return KnowledgeDocument(
            id=doc_id or uuid4(),
            org_id=resolved_org,
            folder_id=resolved_folder.id,
            title=title,
            source_type=source_type,
            version="v1.0",
            visibility=visibility,
            status=status,
            owner_approver=owner_approver,
            effective_date=effective_date,
            file_name=f"{title.lower().replace(' ', '-')}.md",
            file_mime_type="text/markdown",
            processing_status=processing_status,
            indexing_status=indexing_status,
            approved_at=datetime.now(UTC) - timedelta(days=approved_days_ago),
            active_version_id=uuid4(),
        )

    return _factory


@pytest.fixture
def knowledge_document_states(knowledge_document_factory: Callable[..., KnowledgeDocument]) -> dict[str, KnowledgeDocument]:
    return {
        "approved": knowledge_document_factory(title="Approved SOP"),
        "draft": knowledge_document_factory(title="Draft SOP", status=KnowledgeDocumentStatus.DRAFT),
        "failed": knowledge_document_factory(
            title="Failed SOP",
            processing_status=KnowledgeProcessingStatus.FAILED,
            indexing_status=KnowledgeIndexingStatus.FAILED,
        ),
        "expired": knowledge_document_factory(
            title="Expired SOP",
            source_type=KnowledgeSourceType.SOP,
            effective_date=None,
            approved_days_ago=400,
        ),
        "unindexed": knowledge_document_factory(title="Unindexed SOP", indexing_status=KnowledgeIndexingStatus.NOT_INDEXED),
        "internal": knowledge_document_factory(title="Internal SOP", visibility=KnowledgeVisibility.INTERNAL_ONLY),
        "client_safe": knowledge_document_factory(title="Client SOP", visibility=KnowledgeVisibility.CLIENT_SAFE),
        "restricted": knowledge_document_factory(title="Restricted SOP", visibility=KnowledgeVisibility.RESTRICTED),
    }


@pytest.fixture
def knowledge_chunk_factory() -> Callable[..., KnowledgeDocumentChunk]:
    def _factory(
        *,
        document_id: UUID | None = None,
        version_id: UUID | None = None,
        text: str = "Escalation requires delivery manager approval.",
        index: int = 0,
        section_title: str = "Escalation",
    ) -> KnowledgeDocumentChunk:
        return KnowledgeDocumentChunk(
            id=uuid4(),
            org_id=uuid4(),
            document_id=document_id or uuid4(),
            version_id=version_id,
            chunk_index=index,
            section_title=section_title,
            section_path=section_title,
            page_number=1,
            chunk_text=text,
            content=text,
        )

    return _factory


@pytest.fixture
def knowledge_query_factory(org_a: UUID) -> Callable[..., AgentQuery]:
    def _factory(
        *,
        query_id: UUID | None = None,
        org_id: UUID | None = None,
        user_id: UUID | None = None,
        retrieval_params: dict[str, object] | None = None,
    ) -> AgentQuery:
        return AgentQuery(
            id=query_id or uuid4(),
            org_id=org_id or org_a,
            user_id=user_id or uuid4(),
            project_id=None,
            agent_name="operational_knowledge_agent",
            query_text="How do escalations work?",
            answer_text="Escalation requires delivery manager approval. [Doc: Escalation SOP]",
            model_used="mock-model",
            retrieval_params=retrieval_params or {"confidence_score": 0.8, "query_type": "procedural", "sources": []},
            created_at=datetime.now(UTC),
        )

    return _factory


@pytest.fixture
def knowledge_feedback_factory(org_a: UUID) -> Callable[..., KnowledgeQueryFeedback]:
    def _factory(
        *,
        agent_query_id: UUID | None = None,
        user_id: UUID | None = None,
        rating: KnowledgeFeedbackRating = KnowledgeFeedbackRating.DOWN,
    ) -> KnowledgeQueryFeedback:
        return KnowledgeQueryFeedback(
            id=uuid4(),
            org_id=org_a,
            agent_query_id=agent_query_id or uuid4(),
            user_id=user_id or uuid4(),
            rating=rating,
            comment="Missing source",
            feedback_reason="missing_knowledge",
            answer_confidence=0.2,
            query_type="factual",
            selected_source_ids=[],
            created_at=datetime.now(UTC),
        )

    return _factory


@pytest.fixture
def mock_llm_answer() -> dict[str, object]:
    return {
        "answer": "Escalation requires delivery manager approval. [Doc: Escalation SOP]",
        "next_step": "Follow the escalation SOP.",
        "confidence": 0.86,
        "structured": {
            "policy": "Escalation SOP",
            "steps": "1. Confirm trigger. 2. Notify delivery manager.",
            "owner": "Delivery manager",
            "evidence": "Escalation SOP",
            "next_action": "Notify delivery manager.",
        },
        "model": "mock-model",
    }


@pytest.fixture
def mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> list[list[float]]:
    vectors = [[0.1, 0.2, 0.3]]

    async def _embed_texts(_texts: list[str]) -> list[list[float]]:
        return vectors

    monkeypatch.setattr("app.services.knowledge._embed_texts", _embed_texts)
    return vectors


@pytest.fixture
def mock_query_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _rewrite(query_text: str, _history, *, prefer_fast: bool = False) -> str:
        return query_text.strip()

    monkeypatch.setattr("app.services.knowledge._build_retrieval_query_for_search", _rewrite)


@pytest.fixture
def mock_llm_client(monkeypatch: pytest.MonkeyPatch, mock_llm_answer: dict[str, object]) -> None:
    class _Client:
        async def generate_rag_answer(self, *_args, **_kwargs):
            return mock_llm_answer

        async def stream_rag_answer(self, *_args, **_kwargs):
            yield {"type": "delta", "text": str(mock_llm_answer["answer"])}
            yield {
                "type": "done",
                "answer_text": mock_llm_answer["answer"],
                "next_step": mock_llm_answer["next_step"],
                "confidence": mock_llm_answer["confidence"],
                "structured": mock_llm_answer["structured"],
                "model": mock_llm_answer["model"],
            }

    monkeypatch.setattr("app.services.knowledge.LLMClient", _Client)


@pytest.fixture
def mock_operational_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _context(*_args, **_kwargs) -> str:
        return "Project: Alpha\nStatus: active"

    monkeypatch.setattr("app.services.knowledge._build_structured_operational_context", _context)


@pytest.fixture
def mock_storage_and_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _stored_file(_path: str) -> bytes:
        return b"Mock knowledge document text."

    monkeypatch.setattr("app.services.knowledge._read_stored_file", _stored_file)


@pytest.fixture
def mock_grounding_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    def _grounded(*_args, **_kwargs) -> dict[str, object]:
        return {"grounded": True, "support": 1.0, "citation_validity": {"valid": True, "missing": [], "unknown": []}}

    monkeypatch.setattr("app.services.knowledge._ground_generation", _grounded)


@pytest.fixture
def sample_knowledge_answer() -> KnowledgeAskRead:
    return KnowledgeAskRead(
        answer_text="Escalation requires delivery manager approval. [Doc: Escalation SOP]",
        next_step="Follow the escalation SOP.",
        confidence_score=0.84,
        confidence_band="high",
        confidence_reasons=["Matched 1 approved document", "Grounding support 100%"],
        structured_answer=KnowledgeStructuredAnswer(
            policy="Escalation SOP",
            steps="1. Confirm trigger. 2. Notify delivery manager.",
            owner="Delivery manager",
            evidence="Escalation SOP",
            next_action="Notify delivery manager.",
        ),
        query_id=uuid4(),
        conversation_id=uuid4(),
        model_used="mock-model",
        retrieval_debug={
            "query_type": "procedural",
            "selected_source_count": 1,
            "citations": [
                {
                    "document_id": str(uuid4()),
                    "chunk_id": str(uuid4()),
                    "title": "Escalation SOP",
                    "source_type": "sop",
                    "relevance_score": 0.91,
                    "visibility": "internal_only",
                }
            ],
            "grounding": {"grounded": True, "support": 1.0},
        },
    )


@pytest.fixture
def sample_document_read(org_a: UUID) -> KnowledgeDocumentRead:
    folder_id = uuid4()
    return KnowledgeDocumentRead(
        id=uuid4(),
        folder_id=folder_id,
        folder_name="SOPs",
        folder_kind="sops",
        title="Escalation SOP",
        source_type="sop",
        version="v1.0",
        visibility="internal_only",
        status="approved",
        owner_approver="Ops Lead",
        effective_date=date(2026, 1, 1),
        file_name="escalation.md",
        file_mime_type="text/markdown",
        file_url=None,
        processing_status="ready",
        processing_error=None,
        indexing_status="indexed",
        preview=["Escalation requires delivery manager approval."],
        workflow_state="approved",
        retrieval_ready=True,
        retrieval_readiness_reason="Ready",
        retrieval_action=None,
        updated_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        chunk_count=1,
    )


@pytest.fixture
def sample_retrieval_settings() -> KnowledgeRetrievalSettingsRead:
    return KnowledgeRetrievalSettingsRead(
        only_approved=True,
        include_histories=True,
        min_relevance=0.25,
        min_confidence=0.25,
        max_sources=3,
        max_candidates=20,
    )


@pytest.fixture
def fake_async_session_factory():
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self):
            return None

    return _Session
