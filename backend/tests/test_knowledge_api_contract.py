from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.api.routes import knowledge as knowledge_routes
from app.core.exceptions import ApiError
from app.schemas.domain import (
    KnowledgeFeedbackRead,
    KnowledgeRetrievalSettingsRead,
)
from tests.conftest import override_user


def _sse_json_lines(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in text.splitlines():
        if raw.startswith("data: "):
            rows.append(json.loads(raw[6:]))
    return rows


@pytest.mark.asyncio
async def test_knowledge_document_list_and_detail_contract(
    api_client,
    knowledge_users,
    sample_document_read,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])

    async def _list_documents(*_args, **_kwargs):
        return [sample_document_read]

    async def _get_document(*_args, **_kwargs):
        return sample_document_read

    monkeypatch.setattr(knowledge_routes, "list_documents", _list_documents)
    monkeypatch.setattr(knowledge_routes, "get_document", _get_document)

    list_response = await api_client.get("/api/v1/knowledge/documents")
    detail_response = await api_client.get(f"/api/v1/knowledge/documents/{sample_document_read.id}")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    listed = list_response.json()["data"][0]
    detailed = detail_response.json()["data"]
    assert listed["title"] == "Escalation SOP"
    assert detailed["retrieval_ready"] is True
    assert detailed["retrieval_readiness_reason"] == "Ready"
    assert detailed["chunks"] == []


@pytest.mark.asyncio
async def test_knowledge_document_routes_reject_client_role(api_client, knowledge_users) -> None:
    override_user(knowledge_users["client"])

    response = await api_client.get("/api/v1/knowledge/documents")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_ask_contract_uses_settings_and_returns_diagnostics(
    api_client,
    knowledge_users,
    sample_knowledge_answer,
    sample_retrieval_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])
    captured: dict[str, object] = {}

    async def _settings(*_args, **_kwargs):
        return sample_retrieval_settings

    async def _ask(_session, _current_user, query_text: str, **kwargs):
        captured["query_text"] = query_text
        captured.update(kwargs)
        return sample_knowledge_answer

    monkeypatch.setattr(knowledge_routes, "get_retrieval_settings", _settings)
    monkeypatch.setattr(knowledge_routes, "ask_knowledge_agent", _ask)

    response = await api_client.post(
        "/api/v1/knowledge/ask",
        json={"query_text": "  How do escalations work?  ", "answer_mode": "internal"},
        headers={"X-BSG-User-Action": "true"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert captured["query_text"] == "How do escalations work?"
    assert captured["only_approved"] is True
    assert payload["confidence_band"] == "high"
    assert payload["retrieval_debug"]["citations"][0]["title"] == "Escalation SOP"
    assert payload["retrieval_debug"]["grounding"]["grounded"] is True


@pytest.mark.asyncio
async def test_stream_contract_emits_phase6_and_legacy_events(
    api_client,
    knowledge_users,
    sample_retrieval_settings,
    fake_async_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])

    async def _settings(*_args, **_kwargs):
        return sample_retrieval_settings

    async def _rls(*_args, **_kwargs):
        return None

    async def _prepare(*_args, **_kwargs):
        return [
            'data: {"type": "accepted"}\n\n',
            'data: {"type": "searching_sources"}\n\n',
            'data: {"type": "sources_found", "source_count": 1}\n\n',
        ], object()

    async def _stream(_prepared) -> AsyncIterator[str]:
        yield 'data: {"type": "generating_answer"}\n\n'
        yield 'data: {"type": "answer_delta", "text": "hello"}\n\n'
        yield 'data: {"type": "delta", "text": "hello"}\n\n'
        yield 'data: {"type": "validating_grounding"}\n\n'
        final = {
            "type": "final",
            "answer_text": "hello",
            "confidence_score": 0.8,
            "confidence_band": "high",
            "confidence_reasons": [],
            "next_step": "",
            "structured_answer": None,
            "model_used": "mock",
            "retrieval_debug": {"grounding": {"grounded": True, "support": 1.0}},
        }
        yield f"data: {json.dumps(final)}\n\n"
        final["type"] = "done"
        yield f"data: {json.dumps(final)}\n\n"

    monkeypatch.setattr(knowledge_routes, "AsyncSessionLocal", fake_async_session_factory)
    monkeypatch.setattr(knowledge_routes, "set_rls_context", _rls)
    monkeypatch.setattr(knowledge_routes, "get_retrieval_settings", _settings)
    monkeypatch.setattr(knowledge_routes, "prepare_stream_knowledge_ask", _prepare)
    monkeypatch.setattr(knowledge_routes, "stream_prepared_knowledge_ask", _stream)

    response = await api_client.post(
        "/api/v1/knowledge/ask/stream",
        json={"query_text": "How do escalations work?"},
        headers={"X-BSG-User-Action": "true"},
    )

    assert response.status_code == 200
    events = _sse_json_lines(response.text)
    event_types = [event["type"] for event in events]
    assert event_types[:3] == ["accepted", "searching_sources", "sources_found"]
    assert "answer_delta" in event_types
    assert "delta" in event_types
    assert event_types[-2:] == ["final", "done"]


@pytest.mark.asyncio
async def test_stream_contract_returns_stable_no_documents_error(
    api_client,
    knowledge_users,
    sample_retrieval_settings,
    fake_async_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])

    async def _settings(*_args, **_kwargs):
        return sample_retrieval_settings

    async def _rls(*_args, **_kwargs):
        return None

    async def _prepare(*_args, **_kwargs):
        return [
            'data: {"type": "accepted"}\n\n',
            'data: {"type": "error", "code": "NO_APPROVED_DOCUMENTS", "message": "No approved documents are available.", "retryable": false}\n\n',
        ], None

    monkeypatch.setattr(knowledge_routes, "AsyncSessionLocal", fake_async_session_factory)
    monkeypatch.setattr(knowledge_routes, "set_rls_context", _rls)
    monkeypatch.setattr(knowledge_routes, "get_retrieval_settings", _settings)
    monkeypatch.setattr(knowledge_routes, "prepare_stream_knowledge_ask", _prepare)

    response = await api_client.post(
        "/api/v1/knowledge/ask/stream",
        json={"query_text": "What is missing?"},
        headers={"X-BSG-User-Action": "true"},
    )

    assert response.status_code == 200
    events = _sse_json_lines(response.text)
    assert events[-1]["code"] == "NO_APPROVED_DOCUMENTS"
    assert events[-1]["retryable"] is False


@pytest.mark.asyncio
async def test_feedback_contract_accepts_structured_reason(
    api_client,
    knowledge_users,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])
    query_id = uuid4()

    async def _feedback(*_args, **kwargs):
        return KnowledgeFeedbackRead(
            id=uuid4(),
            query_id=kwargs["query_id"],
            rating=kwargs["rating"],
            comment=kwargs["comment"],
            feedback_reason=kwargs["feedback_reason"],
            created_at=datetime.now(UTC),
        )

    monkeypatch.setattr(knowledge_routes, "record_knowledge_feedback", _feedback)

    response = await api_client.post(
        "/api/v1/knowledge/feedback",
        json={
            "query_id": str(query_id),
            "rating": "down",
            "comment": "Source was stale",
            "feedback_reason": "outdated",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["feedback_reason"] == "outdated"


@pytest.mark.asyncio
async def test_retrieval_settings_permissions(
    api_client,
    knowledge_users,
    sample_retrieval_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])

    async def _settings(*_args, **_kwargs):
        return sample_retrieval_settings

    monkeypatch.setattr(knowledge_routes, "get_retrieval_settings", _settings)

    settings_get = await api_client.get("/api/v1/knowledge/retrieval-settings")
    settings_patch_denied = await api_client.patch("/api/v1/knowledge/retrieval-settings", json={"max_sources": 4})

    assert settings_get.status_code == 200
    assert settings_get.json()["data"]["only_approved"] is True
    assert settings_patch_denied.status_code == 403


@pytest.mark.asyncio
async def test_knowledge_error_response_does_not_leak_stack_trace(
    api_client,
    knowledge_users,
    sample_retrieval_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_user(knowledge_users["delivery_manager"])

    async def _settings(*_args, **_kwargs):
        return sample_retrieval_settings

    async def _ask(*_args, **_kwargs):
        raise ApiError(503, "KNOWLEDGE_RETRIEVAL_FAILED", "Knowledge retrieval failed.")

    monkeypatch.setattr(knowledge_routes, "get_retrieval_settings", _settings)
    monkeypatch.setattr(knowledge_routes, "ask_knowledge_agent", _ask)

    response = await api_client.post(
        "/api/v1/knowledge/ask",
        json={"query_text": "How do escalations work?"},
        headers={"X-BSG-User-Action": "true"},
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "KNOWLEDGE_RETRIEVAL_FAILED"
    assert "Traceback" not in json.dumps(error)
