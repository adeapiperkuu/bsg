"""Phase 4: synchronous AI report draft generation."""

from __future__ import annotations

import inspect
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, CommunicationStatus, CommunicationType
from app.services.communications import (
    GENERATION_FALLBACK_WARNING,
    DraftEvidenceBundle,
    DraftGenerationResult,
    DraftGenerationTimings,
    build_comms_prompt_parts,
    create_communication_draft,
    create_draft,
    gather_draft_evidence,
    generate_comms_draft_body,
)
from app.services.evidence import EvidenceInput
from tests.conftest import FakeResult, FakeSession


def _project(**overrides: object) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "org_id": uuid4(),
        "name": "Helios Bank",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _throughput() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        snapshot_date=date(2026, 7, 10),
        units_completed=88,
        units_forecast=100,
        rolling_7day_units=600,
    )


def _user() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.openai_api_key = None
    settings.llm_api_key = None
    settings.communications_llm_model = "gpt-4o-mini"
    settings.openai_model = "gpt-4o-mini"
    settings.llm_model = "gpt-4o-mini"
    settings.communications_llm_timeout_seconds = 2.5
    settings.communications_llm_max_tokens = 350
    settings.communications_max_body_words = 150
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _evidence(throughput_id=None) -> list[EvidenceInput]:
    return [
        EvidenceInput(
            source_table="throughput_snapshots",
            source_row_id=throughput_id or uuid4(),
            description="Latest throughput",
        )
    ]


@pytest.mark.asyncio
async def test_create_draft_persists_draft_status_and_generation_metadata() -> None:
    session = FakeSession()
    added: list[object] = []
    session.add = added.append  # type: ignore[method-assign]

    communication = await create_draft(
        session,  # type: ignore[arg-type]
        _project(),
        "Weekly Delivery Summary — Helios Bank",
        "Evidence-backed body",
        CommunicationType.WEEKLY_SUMMARY,
        _evidence(),
        generation_mode="ai",
        generation_warning=None,
    )

    assert communication.status == CommunicationStatus.DRAFT
    assert communication.generation_mode == "ai"
    assert communication.generation_warning is None
    assert communication.sent_at is None
    assert communication.approved_at is None
    assert communication.approved_by is None
    # communication + one evidence link
    assert len(added) == 2


@pytest.mark.asyncio
async def test_create_draft_requires_evidence() -> None:
    with pytest.raises(ApiError) as exc:
        await create_draft(
            FakeSession(),  # type: ignore[arg-type]
            _project(),
            "Subject",
            "Body",
            CommunicationType.AD_HOC,
            [],
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "EVIDENCE_REQUIRED"


@pytest.mark.asyncio
async def test_gather_draft_evidence_requires_throughput() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=FakeResult(None))

    with pytest.raises(ApiError) as exc:
        await gather_draft_evidence(
            session,
            _project(),
            CommunicationType.WEEKLY_SUMMARY,
            _user(),
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "EVIDENCE_REQUIRED"


@pytest.mark.asyncio
async def test_gather_evidence_depth_by_comm_type() -> None:
    throughput = _throughput()

    async def _weekly_bundle(*_args, **_kwargs):
        return DraftEvidenceBundle(
            evidence=_evidence(throughput.id)
            + [
                EvidenceInput("milestones", uuid4(), "m"),
                EvidenceInput("risk_alerts", uuid4(), "r"),
                EvidenceInput("quality_summaries", uuid4(), "q"),
            ],
            throughput=throughput,  # type: ignore[arg-type]
            quality_snaps=[],
            drift_alerts=[],
            open_risks=[],
            milestones=[],
        )

    async def _exec_bundle(*_args, **_kwargs):
        return DraftEvidenceBundle(
            evidence=_evidence(throughput.id)
            + [
                EvidenceInput("delivery_confidence_scores", uuid4(), "c"),
                EvidenceInput("risk_alerts", uuid4(), "r1"),
                EvidenceInput("risk_alerts", uuid4(), "r2"),
                EvidenceInput("milestones", uuid4(), "m"),
            ],
            throughput=throughput,  # type: ignore[arg-type]
        )

    async def _adhoc_bundle(*_args, **_kwargs):
        return DraftEvidenceBundle(
            evidence=_evidence(throughput.id) + [EvidenceInput("risk_alerts", uuid4(), "r")],
            throughput=throughput,  # type: ignore[arg-type]
            open_risks=[],
        )

    # Source inspection: weekly path includes quality summary; executive does not call it.
    source = inspect.getsource(gather_draft_evidence)
    assert "generate_quality_summary" in source
    assert "EXECUTIVE_SUMMARY" in source
    assert "limit(2)" in source  # top two open risks for executive
    assert "asyncio.gather" not in source

    weekly = await _weekly_bundle()
    executive = await _exec_bundle()
    adhoc = await _adhoc_bundle()
    assert len(weekly.evidence) > len(adhoc.evidence)
    assert any(e.source_table == "quality_summaries" for e in weekly.evidence)
    assert any(e.source_table == "delivery_confidence_scores" for e in executive.evidence)
    assert not any(e.source_table == "quality_summaries" for e in executive.evidence)


def test_instructions_included_in_prompt_construction() -> None:
    with patch("app.services.communications.get_settings", return_value=_settings()):
        context, user_prompt = build_comms_prompt_parts(
            _project(),
            _throughput(),  # type: ignore[arg-type]
            CommunicationType.EXECUTIVE_SUMMARY,
            instructions="Keep the tone suitable for executive stakeholders.",
        )
    assert "Keep the tone suitable for executive stakeholders." in user_prompt
    assert "pm_instructions" in context


@pytest.mark.asyncio
async def test_llm_success_returns_generation_mode_ai() -> None:
    with (
        patch("app.services.communications.get_settings", return_value=_settings(llm_api_key="k")),
        patch("app.services.communications.LLMClient") as mock_llm_cls,
    ):
        mock_llm = AsyncMock()
        mock_llm.generate_structured.return_value = "AI drafted update."
        mock_llm_cls.return_value = mock_llm
        body, mode, warning, _ = await generate_comms_draft_body(
            _project(),
            _throughput(),  # type: ignore[arg-type]
            CommunicationType.WEEKLY_SUMMARY,
        )
    assert body == "AI drafted update."
    assert mode == "ai"
    assert warning is None


@pytest.mark.asyncio
async def test_llm_failure_fallback_is_evidence_backed() -> None:
    with (
        patch("app.services.communications.get_settings", return_value=_settings(openai_api_key="k")),
        patch("app.services.communications.LLMClient") as mock_llm_cls,
    ):
        mock_llm = AsyncMock()
        mock_llm.generate_structured.side_effect = ApiError(503, "LLM_PROVIDER_ERROR", "fail")
        mock_llm_cls.return_value = mock_llm
        body, mode, warning, _ = await generate_comms_draft_body(
            _project(),
            _throughput(),  # type: ignore[arg-type]
            CommunicationType.AD_HOC,
            instructions="Emphasize recovery plan.",
        )
    assert mode == "fallback"
    assert warning == GENERATION_FALLBACK_WARNING
    assert "88" in body
    assert "Emphasize recovery plan." in body
    assert "### Delivery posture" in body


@pytest.mark.asyncio
async def test_create_communication_draft_orchestrates_and_stays_draft() -> None:
    project = _project()
    throughput = _throughput()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    bundle = DraftEvidenceBundle(
        evidence=_evidence(throughput.id),
        throughput=throughput,  # type: ignore[arg-type]
    )

    with (
        patch(
            "app.services.communications.gather_draft_evidence",
            AsyncMock(return_value=bundle),
        ),
        patch(
            "app.services.communications.generate_comms_draft_body",
            AsyncMock(return_value=("AI body", "ai", None, 12.0)),
        ),
        patch("app.services.communications.get_settings", return_value=_settings()),
    ):
        result = await create_communication_draft(
            session,
            project,  # type: ignore[arg-type]
            subject="Weekly Delivery Summary — Helios Bank",
            comm_type=CommunicationType.WEEKLY_SUMMARY,
            instructions="Focus on blockers.",
            current_user=_user(),
            authorization_ms=1.5,
        )

    assert isinstance(result, DraftGenerationResult)
    assert result.generation_mode == "ai"
    assert result.communication.status == CommunicationStatus.DRAFT
    assert result.communication.sent_at is None
    assert result.communication.approved_at is None
    assert result.evidence_link_count == 1
    assert result.timings.authorization_ms == 1.5
    assert result.timings.llm_ms == 12.0
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_communication_draft_persist_failure_returns_503() -> None:
    project = _project()
    throughput = _throughput()
    session = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("db down"))
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    bundle = DraftEvidenceBundle(
        evidence=_evidence(throughput.id),
        throughput=throughput,  # type: ignore[arg-type]
    )

    with (
        patch(
            "app.services.communications.gather_draft_evidence",
            AsyncMock(return_value=bundle),
        ),
        patch(
            "app.services.communications.generate_comms_draft_body",
            AsyncMock(return_value=("body", "fallback", GENERATION_FALLBACK_WARNING, 3.0)),
        ),
        patch("app.services.communications.get_settings", return_value=_settings()),
        pytest.raises(ApiError) as exc,
    ):
        await create_communication_draft(
            session,
            project,  # type: ignore[arg-type]
            subject="Subject",
            comm_type=CommunicationType.AD_HOC,
            instructions=None,
            current_user=_user(),
        )

    assert exc.value.status_code == 503
    assert exc.value.code == "COMMUNICATION_GENERATION_FAILED"
    session.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_fallback_success_does_not_raise_503() -> None:
    project = _project()
    throughput = _throughput()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    with (
        patch(
            "app.services.communications.gather_draft_evidence",
            AsyncMock(
                return_value=DraftEvidenceBundle(
                    evidence=_evidence(throughput.id),
                    throughput=throughput,  # type: ignore[arg-type]
                )
            ),
        ),
        patch(
            "app.services.communications.generate_comms_draft_body",
            AsyncMock(return_value=("fallback body", "fallback", GENERATION_FALLBACK_WARNING, 4.0)),
        ),
        patch("app.services.communications.get_settings", return_value=_settings()),
    ):
        result = await create_communication_draft(
            session,
            project,  # type: ignore[arg-type]
            subject="Project Update — Helios Bank",
            comm_type=CommunicationType.AD_HOC,
            instructions=None,
            current_user=_user(),
        )

    assert result.generation_mode == "fallback"
    assert result.generation_warning == GENERATION_FALLBACK_WARNING


def test_gather_draft_evidence_is_sequential_not_concurrent() -> None:
    source = inspect.getsource(gather_draft_evidence)
    assert "asyncio.gather" not in source
    assert "await session.execute" in source


@pytest.mark.asyncio
async def test_draft_route_fallback_returns_200_with_warning(api_client, delivery_manager) -> None:
    from collections.abc import AsyncIterator
    from datetime import datetime, timezone

    from app.db.session import get_db_session
    from app.main import app
    from app.schemas.domain import CommunicationRead
    from tests.conftest import FakeResult, override_user

    project = _project()
    now = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    throughput = _throughput()

    class _DraftSession:
        """Throughput lookup returns a row; snapshot/alert list queries return empty."""

        def add(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def execute(self, *_args: object, **_kwargs: object) -> FakeResult:
            return FakeResult(value=throughput, items=[])

        async def commit(self) -> None:
            return None

        async def refresh(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def flush(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    async def _session_override() -> AsyncIterator[_DraftSession]:
        yield _DraftSession()

    pack_ref = SimpleNamespace(
        source_table="throughput_snapshots",
        source_row_id=throughput.id,
        description="Latest throughput snapshot for communication grounding.",
        visibility=SimpleNamespace(value="internal"),
        observed_at=now,
        claim_keys=["throughput.units_completed"],
    )
    pack = SimpleNamespace(source_fingerprint="a" * 64, evidence=[pack_ref])

    communication = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        org_id=project.org_id,
        comm_type=CommunicationType.WEEKLY_SUMMARY,
        subject="Weekly Delivery Summary — Helios Bank",
        body_draft="Fallback body",
        body_approved=None,
        status=CommunicationStatus.DRAFT,
        drafted_by_agent="client_interaction_agent",
        reviewed_by=None,
        reviewed_at=None,
        approved_by=None,
        approved_at=None,
        sent_at=None,
        created_at=now,
        updated_at=now,
        generation_mode="fallback",
        generation_warning=GENERATION_FALLBACK_WARNING,
    )
    read_payload = CommunicationRead(
        id=communication.id,
        project_id=project.id,
        comm_type=CommunicationType.WEEKLY_SUMMARY,
        subject=communication.subject,
        body_draft=communication.body_draft,
        body_approved=None,
        status=CommunicationStatus.DRAFT,
        drafted_by_agent="client_interaction_agent",
        reviewed_by=None,
        reviewed_at=None,
        approved_by=None,
        approved_at=None,
        sent_at=None,
        created_at=now,
        updated_at=now,
        evidence_links=[],
        generation_mode=None,
        generation_warning=None,
    )

    read_payload.generation_mode = "fallback"
    read_payload.generation_warning = GENERATION_FALLBACK_WARNING

    override_user(delivery_manager)
    app.dependency_overrides[get_db_session] = _session_override
    with (
        patch(
            "app.api.routes.communications.get_visible_project",
            AsyncMock(return_value=project),
        ),
        patch(
            "app.agents.client_intelligence.evidence_pack.build_client_evidence_pack",
            AsyncMock(return_value=pack),
        ),
        patch(
            "app.api.routes.communications.generate_quality_summary",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.api.routes.communications.generate_comms_draft_body",
            AsyncMock(
                return_value=("Fallback body", "fallback", GENERATION_FALLBACK_WARNING, 5.0)
            ),
        ),
        patch(
            "app.api.routes.communications.create_draft",
            AsyncMock(return_value=communication),
        ),
        patch(
            "app.api.routes.communications._communication_read",
            AsyncMock(return_value=read_payload),
        ),
    ):
        response = await api_client.post(
            f"/api/v1/projects/{project.id}/communications/draft",
            json={
                "comm_type": "weekly_summary",
                "subject": "Weekly Delivery Summary — Helios Bank",
                "instructions": "Emphasize delayed milestone.",
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["generation_mode"] == "fallback"
    assert payload["generation_warning"] == GENERATION_FALLBACK_WARNING
    assert payload["status"] == "draft"
