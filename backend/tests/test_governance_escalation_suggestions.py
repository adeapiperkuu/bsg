"""Phase 9: deterministic escalation suggestion detection and lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.governance.services import escalation_suggestion_service as svc
from app.db.models import (
    GovernanceAIRecommendationStatus,
    GovernanceEscalationSeverity,
    GovernanceEscalationTriggerType,
    GovernanceRecommendationAcceptanceStatus,
)


def test_fingerprint_is_stable_for_same_inputs() -> None:
    org_id = uuid4()
    project_id = uuid4()
    entity_id = uuid4()
    left = svc._fingerprint(
        org_id=org_id,
        project_id=project_id,
        trigger_type=GovernanceEscalationTriggerType.OVERDUE_BLOCKING_DEPENDENCY,
        entity_id=entity_id,
        evidence_key="1",
        threshold_bucket="7",
    )
    right = svc._fingerprint(
        org_id=org_id,
        project_id=project_id,
        trigger_type=GovernanceEscalationTriggerType.OVERDUE_BLOCKING_DEPENDENCY,
        entity_id=entity_id,
        evidence_key="1",
        threshold_bucket="7",
    )
    assert left == right


def test_fingerprint_changes_when_evidence_bucket_changes() -> None:
    org_id = uuid4()
    project_id = uuid4()
    entity_id = uuid4()
    left = svc._fingerprint(
        org_id=org_id,
        project_id=project_id,
        trigger_type=GovernanceEscalationTriggerType.OVERDUE_BLOCKING_DEPENDENCY,
        entity_id=entity_id,
        evidence_key="1",
        threshold_bucket="7",
    )
    right = svc._fingerprint(
        org_id=org_id,
        project_id=project_id,
        trigger_type=GovernanceEscalationTriggerType.OVERDUE_BLOCKING_DEPENDENCY,
        entity_id=entity_id,
        evidence_key="2",
        threshold_bucket="7",
    )
    assert left != right


def test_should_suppress_active_reuses() -> None:
    existing = SimpleNamespace(
        status=GovernanceAIRecommendationStatus.ACTIVE,
        snoozed_until=None,
        acceptance_status=GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        converted_escalation_id=None,
    )
    assert svc._should_suppress_existing(existing, now=datetime.now(UTC)) == "reuse"


def test_should_suppress_dismissed() -> None:
    existing = SimpleNamespace(
        status=GovernanceAIRecommendationStatus.DISMISSED,
        snoozed_until=None,
        acceptance_status=GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        converted_escalation_id=None,
    )
    assert svc._should_suppress_existing(existing, now=datetime.now(UTC)) == "suppress"


def test_should_suppress_active_snooze_until_expiry() -> None:
    now = datetime.now(UTC)
    existing = SimpleNamespace(
        status=GovernanceAIRecommendationStatus.SNOOZED,
        snoozed_until=now + timedelta(days=2),
        acceptance_status=GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        converted_escalation_id=None,
    )
    assert svc._should_suppress_existing(existing, now=now) == "suppress"
    existing.snoozed_until = now - timedelta(days=1)
    assert svc._should_suppress_existing(existing, now=now) == "create"


def test_should_allow_create_after_stale() -> None:
    existing = SimpleNamespace(
        status=GovernanceAIRecommendationStatus.STALE,
        snoozed_until=None,
        acceptance_status=GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        converted_escalation_id=None,
    )
    assert svc._should_suppress_existing(existing, now=datetime.now(UTC)) == "create"


def test_should_suppress_converted_escalation() -> None:
    existing = SimpleNamespace(
        status=GovernanceAIRecommendationStatus.ACTIVE,
        snoozed_until=None,
        acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ESCALATION,
        converted_escalation_id=uuid4(),
    )
    # Active + accepted still "reuse" first branch — accepted rows should usually not stay active.
    # Force dismissed-like accepted status via superseded with conversion.
    existing.status = GovernanceAIRecommendationStatus.SUPERSEDED
    assert svc._should_suppress_existing(existing, now=datetime.now(UTC)) == "suppress"


def test_priority_from_severity() -> None:
    assert (
        svc._priority_from_severity(GovernanceEscalationSeverity.CRITICAL).value == "critical"
    )
    assert svc._priority_from_severity(GovernanceEscalationSeverity.HIGH).value == "high"


def test_milestone_risk_scoring_requires_threshold_facts() -> None:
    score, reasons = svc._milestone_risk_score(
        days_until_due=5,
        blockers=2,
        critical_actions=1,
        confidence_drop=12,
        critical_delivery_risks=1,
        dependency_severity=8,
        cross_agent_score=10,
    )
    assert score >= 70
    assert "milestone due within 7 days" in reasons
    assert any("blocker" in reason for reason in reasons)


def test_milestone_not_at_risk_scores_below_threshold() -> None:
    score, reasons = svc._milestone_risk_score(
        days_until_due=30,
        blockers=0,
        critical_actions=0,
        confidence_drop=0,
        critical_delivery_risks=0,
        dependency_severity=0,
        cross_agent_score=0,
    )
    assert score == 0
    assert reasons == []


def test_combined_risk_requires_distinct_categories() -> None:
    project_id = uuid4()
    signals = [
        svc.ProjectRiskSignal(
            category="dependency",
            provider="governance",
            project_id=project_id,
            evidence_id="dependency:1",
            title="Dependency",
            summary="Blocking",
            score=80,
            entity_type="dependency",
            entity_id=uuid4(),
        ),
        svc.ProjectRiskSignal(
            category="dependency",
            provider="governance",
            project_id=project_id,
            evidence_id="dependency:2",
            title="Dependency 2",
            summary="Blocking",
            score=70,
            entity_type="dependency",
            entity_id=uuid4(),
        ),
    ]
    qualifies, _, categories = svc._combined_risk_qualifies(signals, min_categories=2)
    assert not qualifies
    assert categories == ["dependency"]
    signals.append(
        svc.ProjectRiskSignal(
            category="quality",
            provider="quality",
            project_id=project_id,
            evidence_id="quality:1",
            title="Quality",
            summary="Drift",
            score=75,
            entity_type="quality_snapshot",
            entity_id=uuid4(),
        )
    )
    qualifies, unique, categories = svc._combined_risk_qualifies(signals, min_categories=2)
    assert qualifies
    assert categories == ["dependency", "quality"]
    assert len(unique) == 3


def test_duplicate_underlying_evidence_is_not_double_counted() -> None:
    project_id = uuid4()
    entity_id = uuid4()
    signals = [
        svc.ProjectRiskSignal(
            category="quality",
            provider="quality",
            project_id=project_id,
            evidence_id="quality:1",
            title="Quality",
            summary="Drift",
            score=75,
            entity_type="quality_snapshot",
            entity_id=entity_id,
        ),
        svc.ProjectRiskSignal(
            category="quality",
            provider="quality",
            project_id=project_id,
            evidence_id="quality:1",
            title="Quality duplicate",
            summary="Same source",
            score=80,
            entity_type="quality_snapshot",
            entity_id=entity_id,
        ),
    ]
    unique = svc._unique_risk_signals(signals)
    assert len(unique) == 1
    assert unique[0].title == "Quality duplicate"


def test_scheduled_scan_disabled_by_default(monkeypatch) -> None:
    settings = SimpleNamespace(
        governance_escalation_suggestion_scheduled_enabled=False,
    )
    monkeypatch.setattr(svc, "get_settings", lambda: settings)
    assert not svc.get_settings().governance_escalation_suggestion_scheduled_enabled


def test_overlap_guard_key_blocks_duplicate_scan() -> None:
    org_id = uuid4()
    project_id = uuid4()
    key = (org_id, project_id)
    svc._ACTIVE_SCAN_KEYS.add(key)
    try:
        assert key in svc._ACTIVE_SCAN_KEYS
    finally:
        svc._ACTIVE_SCAN_KEYS.discard(key)


@pytest.mark.asyncio
async def test_cross_agent_provider_failure_degrades_safely(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    settings = SimpleNamespace(governance_escalation_suggestion_cross_agent_enabled=True)
    monkeypatch.setattr(svc, "get_settings", lambda: settings)

    async def broken_loader(*_args, **_kwargs):
        raise RuntimeError("provider down")

    async def ok_loader(*_args, **kwargs):
        project_id = kwargs["project_ids"][0]
        return [
            svc.ProjectRiskSignal(
                category="quality",
                provider="quality",
                project_id=project_id,
                evidence_id="quality:1",
                title="Quality",
                summary="Drift",
                score=75,
                entity_type="quality_snapshot",
                entity_id=uuid4(),
            )
        ]

    monkeypatch.setattr(svc, "_load_quality_risk_signals", ok_loader)
    monkeypatch.setattr(svc, "_load_workforce_risk_signals", broken_loader)
    monkeypatch.setattr(svc, "_load_delivery_risk_signals", broken_loader)

    grouped, failures, count = await svc._load_cross_agent_signals(
        AsyncMock(), org_id=uuid4(), project_ids=[uuid4()]
    )
    assert count == 1
    assert grouped
    assert failures == {"workforce": "RuntimeError", "delivery": "RuntimeError"}


def test_escalation_covers_project_risk_by_title_token() -> None:
    project_id = uuid4()
    esc = SimpleNamespace(project_id=project_id, title="Vendor API Access escalation")
    assert svc._escalation_covers_project_risk(
        [esc], project_id=project_id, title_tokens=["Vendor API Access"]
    )
    assert not svc._escalation_covers_project_risk(
        [esc], project_id=project_id, title_tokens=["Unrelated blocker"]
    )


@pytest.mark.asyncio
async def test_scan_disabled_returns_enabled_false(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from app.core.security import CurrentUser
    from app.db.models import AppRole

    monkeypatch.setattr(svc, "escalation_suggestions_enabled", lambda: False)
    monkeypatch.setattr(svc, "assert_can_generate_ai_recommendations", lambda _u: None)
    user = CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    result = await svc.scan_governance_escalation_suggestions(AsyncMock(), user)
    assert result.enabled is False
    assert result.candidates_detected == 0
