"""Tests for Governance AI recommendations (Phase 6)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.governance.schemas.governance import (
    GovernanceAIRecommendationCandidate,
    GovernanceAIRecommendationGenerationResult,
    GovernanceAIRecommendationLLMResponse,
    GovernanceSuggestedAction,
)
from app.agents.governance.services.recommendation_evidence import (
    GovernanceRecommendationEvidence,
    GovernanceRecommendationEvidenceBundle,
    build_rule_signals,
    compute_evidence_hash,
)
from app.agents.governance.services.recommendation_grounding import (
    recommendation_fingerprint,
    titles_are_near_duplicates,
    validate_candidate_grounding,
)
from app.agents.governance.services.recommendation_service import (
    build_rule_based_recommendation_reads,
    get_recommendation_metrics,
    reset_recommendation_metrics,
)
from app.db.models import GovernanceAIRecommendationScope, GovernanceAIRecommendationType


def _evidence(
    *,
    evidence_id: str = "dependency:11111111-1111-1111-1111-111111111111",
    entity_type: str = "dependency",
    project_id=None,
    title: str = "Vendor integration",
    owner_name: str | None = "Alex Rivera",
    due_date: date | None = date(2026, 7, 1),
    status: str = "blocking",
    severity: str = "high",
    attributes: dict | None = None,
) -> GovernanceRecommendationEvidence:
    pid = project_id or uuid4()
    return GovernanceRecommendationEvidence(
        evidence_id=evidence_id,
        entity_type=entity_type,  # type: ignore[arg-type]
        entity_id=uuid4(),
        project_id=pid,
        title=title,
        summary=f"{title}; status={status}; due={due_date}",
        status=status,
        severity=severity,
        owner_name=owner_name,
        due_date=due_date,
        attributes=attributes or {"project_name": "Project Alpha", "overdue_days": 2},
    )


def _bundle(evidence: list[GovernanceRecommendationEvidence] | None = None):
    items = evidence or [_evidence()]
    project_id = items[0].project_id
    signals = build_rule_signals(items, project_id=project_id, project_name="Project Alpha")
    return GovernanceRecommendationEvidenceBundle(
        scope=GovernanceAIRecommendationScope.PROJECT,
        org_id=uuid4(),
        project_id=project_id,
        project_name="Project Alpha",
        evidence=items,
        signals=signals,
        evidence_hash=compute_evidence_hash(items),
        owner_names={i.owner_name for i in items if i.owner_name},
        project_names={"Project Alpha"},
        dates={i.due_date.isoformat() for i in items if i.due_date},
        counts={
            "blocking_dependencies": sum(1 for i in items if i.status == "blocking"),
            "critical_escalations": 0,
            "overdue_actions": 0,
            "evidence_items": len(items),
            "signals": len(signals),
        },
    )


def test_structured_candidate_schema_valid() -> None:
    project_id = uuid4()
    candidate = GovernanceAIRecommendationCandidate(
        scope="project",
        project_id=project_id,
        recommendation_type=GovernanceAIRecommendationType.DEPENDENCY_MITIGATION,
        title="Resolve blocking vendor dependency",
        narrative="Project Alpha has unresolved blocking dependencies.",
        rationale="Blocking dependencies increase milestone risk.",
        priority="high",
        confidence=0.82,
        evidence_ids=["dependency:11111111-1111-1111-1111-111111111111"],
        suggested_actions=[
            GovernanceSuggestedAction(
                label="Assign owner",
                description="Assign one accountable owner across teams.",
                action_type="assign_owner",
            )
        ],
    )
    assert candidate.confidence == 0.82


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confidence": 1.5},
        {"recommendation_type": "invented_type"},
        {"evidence_ids": []},
        {"title": "x" * 300},
        {
            "suggested_actions": [
                {
                    "label": "Bad",
                    "description": "Bad",
                    "action_type": "invented",
                }
            ]
        },
    ],
)
def test_structured_candidate_schema_rejects_invalid(kwargs) -> None:
    base = {
        "scope": "project",
        "project_id": str(uuid4()),
        "recommendation_type": "dependency_mitigation",
        "title": "Resolve blocking vendor dependency",
        "narrative": "Narrative",
        "rationale": "Rationale",
        "priority": "high",
        "confidence": 0.5,
        "evidence_ids": ["dependency:11111111-1111-1111-1111-111111111111"],
        "suggested_actions": [],
    }
    base.update(kwargs)
    with pytest.raises(ValidationError):
        GovernanceAIRecommendationCandidate.model_validate(base)


def test_llm_response_parses_multiple_candidates() -> None:
    payload = {
        "recommendations": [
            {
                "scope": "project",
                "project_id": str(uuid4()),
                "recommendation_type": "dependency_mitigation",
                "title": "One",
                "narrative": "N1",
                "rationale": "R1",
                "priority": "high",
                "confidence": 0.7,
                "evidence_ids": ["e1"],
                "suggested_actions": [],
            },
            {
                "scope": "project",
                "project_id": str(uuid4()),
                "recommendation_type": "escalation_required",
                "title": "Two",
                "narrative": "N2",
                "rationale": "R2",
                "priority": "critical",
                "confidence": 0.9,
                "evidence_ids": ["e2"],
                "suggested_actions": [],
            },
        ]
    }
    parsed = GovernanceAIRecommendationLLMResponse.model_validate(payload)
    assert len(parsed.recommendations) == 2


def test_grounding_accepts_valid_candidate() -> None:
    bundle = _bundle()
    candidate = GovernanceAIRecommendationCandidate(
        scope="project",
        project_id=bundle.project_id,
        recommendation_type=GovernanceAIRecommendationType.DEPENDENCY_MITIGATION,
        title="Resolve blocking dependencies",
        narrative=(
            "Project Alpha has blocking dependencies. "
            "This increases milestone risk. "
            "Review this within the next governance cycle."
        ),
        rationale="Observed blocking dependencies support prioritized mitigation.",
        priority="high",
        confidence=0.8,
        evidence_ids=[bundle.evidence[0].evidence_id],
        suggested_actions=[],
    )
    ok, reasons = validate_candidate_grounding(candidate, bundle)
    assert ok, reasons


def test_grounding_rejects_unknown_evidence_and_owner_and_date() -> None:
    bundle = _bundle()
    candidate = GovernanceAIRecommendationCandidate(
        scope="project",
        project_id=uuid4(),
        recommendation_type=GovernanceAIRecommendationType.DEPENDENCY_MITIGATION,
        title="Escalate",
        narrative=(
            "owned by Totally Fake Person and due 2099-01-01. "
            "Also cites missing evidence."
        ),
        rationale="Bad",
        priority="high",
        confidence=0.5,
        evidence_ids=["missing:evidence"],
        suggested_actions=[],
    )
    ok, reasons = validate_candidate_grounding(candidate, bundle)
    assert not ok
    assert any(r.startswith("unknown_evidence_id") for r in reasons)
    assert any(r.startswith("unknown_project_id") for r in reasons)
    assert any(r.startswith("unsupported_owner") for r in reasons)
    assert any(r.startswith("unsupported_date") for r in reasons)


def test_grounding_rejects_unsupported_count() -> None:
    bundle = _bundle()
    candidate = GovernanceAIRecommendationCandidate(
        scope="project",
        project_id=bundle.project_id,
        recommendation_type=GovernanceAIRecommendationType.DEPENDENCY_MITIGATION,
        title="Counts",
        narrative="There are 99 blocking dependencies on this project.",
        rationale="Bad count",
        priority="high",
        confidence=0.5,
        evidence_ids=[bundle.evidence[0].evidence_id],
        suggested_actions=[],
    )
    ok, reasons = validate_candidate_grounding(candidate, bundle)
    assert not ok
    assert any(r.startswith("unsupported_count") for r in reasons)


def test_rule_signals_and_fallback_reads() -> None:
    project_id = uuid4()
    items = [
        _evidence(
            evidence_id="dependency:aaaa",
            project_id=project_id,
            status="blocking",
            attributes={"project_name": "Project Alpha", "overdue_days": 3},
        ),
        _evidence(
            evidence_id="dependency:bbbb",
            project_id=project_id,
            status="blocking",
            attributes={"project_name": "Project Alpha", "overdue_days": 1},
        ),
    ]
    signals = build_rule_signals(items, project_id=project_id, project_name="Project Alpha")
    assert signals
    assert signals[0].signal_type == "blocking_dependencies"
    bundle = GovernanceRecommendationEvidenceBundle(
        scope=GovernanceAIRecommendationScope.PROJECT,
        org_id=uuid4(),
        project_id=project_id,
        project_name="Project Alpha",
        evidence=items,
        signals=signals,
        evidence_hash=compute_evidence_hash(items),
        owner_names=set(),
        project_names={"Project Alpha"},
        dates=set(),
        counts={"blocking_dependencies": 2, "critical_escalations": 0, "overdue_actions": 0},
    )
    reads = build_rule_based_recommendation_reads(bundle)
    assert reads
    assert reads[0].source_type == "rule_based"
    assert reads[0].is_ai_generated is False


def test_fingerprint_and_near_duplicate() -> None:
    left = recommendation_fingerprint(
        recommendation_type="dependency_mitigation",
        project_id=uuid4(),
        title="Resolve blocking vendor dependency",
        evidence_hash="abc",
    )
    right = recommendation_fingerprint(
        recommendation_type="dependency_mitigation",
        project_id=uuid4(),
        title="Resolve blocking vendor dependency",
        evidence_hash="abc",
    )
    assert left != right  # different project
    assert titles_are_near_duplicates(
        "Resolve blocking vendor dependency",
        "Resolve blocking vendor dependency now",
    )


def test_evidence_hash_stable() -> None:
    item = _evidence()
    assert compute_evidence_hash([item]) == compute_evidence_hash([item])


def test_healthy_project_receives_governance_cadence_signal() -> None:
    project_id = uuid4()
    project = _evidence(
        evidence_id=f"project:{project_id}",
        entity_type="project",
        project_id=project_id,
        title="Healthy Project",
        owner_name=None,
        due_date=None,
        status="active",
        severity="low",
        attributes={"project_name": "Healthy Project"},
    )

    signals = build_rule_signals(
        [project],
        project_id=project_id,
        project_name="Healthy Project",
    )

    assert len(signals) == 1
    assert signals[0].signal_type == "governance_cadence"
    assert signals[0].project_id == project_id


@pytest.mark.asyncio
async def test_generate_without_project_id_attempts_every_visible_project(monkeypatch) -> None:
    from app.agents.governance.services import recommendation_service as svc
    from app.core.security import CurrentUser
    from app.db.models import AppRole

    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="dm@example.com",
        is_active=True,
    )
    projects = [
        SimpleNamespace(id=uuid4(), name="Alpha"),
        SimpleNamespace(id=uuid4(), name="Beta"),
        SimpleNamespace(id=uuid4(), name="Gamma"),
    ]
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: projects)
    )
    session.rollback = AsyncMock()
    per_project = AsyncMock(
        side_effect=[
            GovernanceAIRecommendationGenerationResult(
                recommendations=[],
                reused=True,
            ),
            GovernanceAIRecommendationGenerationResult(
                recommendations=[],
                fallback_used=True,
                fallback_reason="provider_error",
            ),
            GovernanceAIRecommendationGenerationResult(recommendations=[]),
        ]
    )
    monkeypatch.setattr(svc, "generate_governance_ai_recommendations", per_project)

    result = await svc._generate_recommendations_for_all_projects(
        session,
        user,
        force=False,
    )

    assert result.projects_attempted == 3
    assert per_project.await_count == 3
    assert [call.kwargs["project_id"] for call in per_project.await_args_list] == [
        project.id for project in projects
    ]
    assert result.projects_reused == 1
    assert result.projects_using_fallback == 1


@pytest.mark.asyncio
async def test_portfolio_generation_records_failure_after_rollback(monkeypatch) -> None:
    """Regression: accessing expired ORM attrs after rollback caused MissingGreenlet 500s."""
    from app.agents.governance.services import recommendation_service as svc
    from app.core.security import CurrentUser
    from app.db.models import AppRole

    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="dm@example.com",
        is_active=True,
    )
    failed_id = uuid4()
    ok_id = uuid4()
    projects = [
        SimpleNamespace(id=failed_id, name="Broken"),
        SimpleNamespace(id=ok_id, name="Ok"),
    ]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: projects))
    session.rollback = AsyncMock()

    async def _side_effect(_session, _user, **kwargs):
        if kwargs["project_id"] == failed_id:
            raise RuntimeError("provider boom")
        return GovernanceAIRecommendationGenerationResult(recommendations=[], reused=True)

    monkeypatch.setattr(svc, "generate_governance_ai_recommendations", AsyncMock(side_effect=_side_effect))

    result = await svc._generate_recommendations_for_all_projects(
        session,
        user,
        force=False,
    )

    assert result.projects_attempted == 2
    assert result.project_failures[str(failed_id)] == "generation_failed"
    assert result.projects_reused == 1
    session.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_generate_falls_back_when_disabled(monkeypatch) -> None:
    from app.agents.governance.services import recommendation_service as svc
    from app.core.security import CurrentUser
    from app.db.models import AppRole

    reset_recommendation_metrics()
    monkeypatch.setattr(svc, "ai_recommendations_enabled", lambda: False)
    monkeypatch.setattr(svc, "assert_can_generate_ai_recommendations", lambda _user: None)

    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="dm@example.com",
        is_active=True,
    )
    project_id = uuid4()
    bundle = _bundle([_evidence(project_id=project_id)])

    session = AsyncMock()
    session.commit = AsyncMock()

    with (
        patch.object(svc, "build_governance_recommendation_evidence", AsyncMock(return_value=bundle)),
        patch.object(svc, "get_visible_project", AsyncMock(return_value=type("P", (), {"org_id": user.org_id, "id": project_id})())),
        patch.object(svc, "log_governance_event", AsyncMock()),
    ):
        result = await svc.generate_governance_ai_recommendations(
            session,
            user,
            project_id=project_id,
            scope=GovernanceAIRecommendationScope.PROJECT,
            force=False,
        )

    assert result.fallback_used is True
    assert result.fallback_reason == "disabled"
    assert result.rule_based_fallback
    assert get_recommendation_metrics()["fallback_used"] >= 1


@pytest.mark.asyncio
async def test_generate_falls_back_on_invalid_schema(monkeypatch) -> None:
    from app.agents.governance.services import recommendation_service as svc
    from app.core.security import CurrentUser
    from app.db.models import AppRole

    reset_recommendation_metrics()
    monkeypatch.setattr(svc, "ai_recommendations_enabled", lambda: True)
    monkeypatch.setattr(svc, "assert_can_generate_ai_recommendations", lambda _user: None)

    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="dm@example.com",
        is_active=True,
    )
    project_id = uuid4()
    bundle = _bundle([_evidence(project_id=project_id)])
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=type("R", (), {"scalars": lambda self: type("S", (), {"all": lambda self: []})()})())

    with (
        patch.object(svc, "build_governance_recommendation_evidence", AsyncMock(return_value=bundle)),
        patch.object(svc, "get_visible_project", AsyncMock(return_value=type("P", (), {"org_id": user.org_id, "id": project_id})())),
        patch.object(svc, "log_governance_event", AsyncMock()),
        patch.object(svc, "_call_llm", AsyncMock(return_value=([], 12.0, "invalid_schema"))),
        patch.object(svc, "_load_related_rows", AsyncMock(return_value=[])),
    ):
        result = await svc.generate_governance_ai_recommendations(
            session,
            user,
            project_id=project_id,
            scope=GovernanceAIRecommendationScope.PROJECT,
        )

    assert result.fallback_used is True
    assert result.fallback_reason == "invalid_schema"


@pytest.mark.asyncio
async def test_generate_rejects_ungrounded_and_falls_back(monkeypatch) -> None:
    from app.agents.governance.services import recommendation_service as svc
    from app.core.security import CurrentUser
    from app.db.models import AppRole

    reset_recommendation_metrics()
    monkeypatch.setattr(svc, "ai_recommendations_enabled", lambda: True)
    monkeypatch.setattr(svc, "assert_can_generate_ai_recommendations", lambda _user: None)

    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        email="dm@example.com",
        is_active=True,
    )
    project_id = uuid4()
    bundle = _bundle([_evidence(project_id=project_id)])
    bad = GovernanceAIRecommendationCandidate(
        scope="project",
        project_id=uuid4(),
        recommendation_type=GovernanceAIRecommendationType.DEPENDENCY_MITIGATION,
        title="Invented",
        narrative="Invented owner Totally Fake Person due 2099-01-01",
        rationale="Bad",
        priority="high",
        confidence=0.9,
        evidence_ids=["nope"],
        suggested_actions=[],
    )
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    with (
        patch.object(svc, "build_governance_recommendation_evidence", AsyncMock(return_value=bundle)),
        patch.object(svc, "get_visible_project", AsyncMock(return_value=type("P", (), {"org_id": user.org_id, "id": project_id})())),
        patch.object(svc, "log_governance_event", AsyncMock()),
        patch.object(svc, "_call_llm", AsyncMock(return_value=([bad], 10.0, None))),
        patch.object(svc, "_load_related_rows", AsyncMock(return_value=[])),
    ):
        result = await svc.generate_governance_ai_recommendations(
            session,
            user,
            project_id=project_id,
            scope=GovernanceAIRecommendationScope.PROJECT,
        )

    assert result.fallback_used is True
    assert result.candidates_rejected_grounding >= 1
    assert result.recommendations == []


def test_analytics_detail_does_not_import_recommendation_generation() -> None:
    """Latency guard: analytics module must not call AI generation."""
    import inspect

    from app.agents.governance.services import analytics_service

    source = inspect.getsource(analytics_service)
    assert "generate_governance_ai_recommendations" not in source
    assert "LLMClient" not in source
    assert "_build_recommendations" in source
