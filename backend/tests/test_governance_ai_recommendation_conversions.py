"""Tests for Governance AI recommendation conversion guardrails (Phase 7)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.governance.services import recommendation_service as svc
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationPriority,
    GovernanceAIRecommendationScope,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceRecommendationConversionTarget,
)


def _user(org_id):
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _recommendation(*, org_id, project_id, suggested_actions):
    return GovernanceAIRecommendation(
        org_id=org_id,
        project_id=project_id,
        scope=GovernanceAIRecommendationScope.PROJECT,
        recommendation_type=GovernanceAIRecommendationType.GENERAL_GOVERNANCE,
        title="Review governance risk",
        narrative="Review governance risk.",
        rationale="Evidence supports review.",
        priority=GovernanceAIRecommendationPriority.HIGH,
        confidence=0.8,
        status=GovernanceAIRecommendationStatus.ACTIVE,
        suggested_actions=suggested_actions,
        evidence_refs=[],
        evidence_hash="hash",
        fingerprint="fingerprint",
        source_snapshot={},
        model_name="test",
        model_version=None,
        prompt_version="v1",
        generation_request_id=uuid4(),
        generated_by_user_id=uuid4(),
    )


def test_conversion_fingerprint_normalizes_title() -> None:
    recommendation_id = uuid4()
    project_id = uuid4()

    left = svc._conversion_fingerprint(
        recommendation_id=recommendation_id,
        suggested_action_index=0,
        target=GovernanceRecommendationConversionTarget.ACTION,
        project_id=project_id,
        title="  Create   Owner Action ",
    )
    right = svc._conversion_fingerprint(
        recommendation_id=recommendation_id,
        suggested_action_index=0,
        target=GovernanceRecommendationConversionTarget.ACTION,
        project_id=project_id,
        title="create owner action",
    )

    assert left == right


@pytest.mark.asyncio
async def test_conversion_context_rejects_incompatible_suggested_action(monkeypatch) -> None:
    org_id = uuid4()
    project_id = uuid4()
    recommendation = _recommendation(
        org_id=org_id,
        project_id=project_id,
        suggested_actions=[
            {
                "label": "Assign owner",
                "description": "Assign an accountable owner.",
                "action_type": "assign_owner",
            }
        ],
    )
    session = AsyncMock()
    current_user = _user(org_id)

    monkeypatch.setattr(
        svc,
        "get_governance_ai_recommendation",
        AsyncMock(return_value=recommendation),
    )
    monkeypatch.setattr(svc, "log_governance_event", AsyncMock())

    with pytest.raises(ApiError) as exc:
        await svc._conversion_context(
            session,
            current_user,
            recommendation_id=uuid4(),
            requested_project_id=project_id,
            suggested_action_index=0,
            target=GovernanceRecommendationConversionTarget.ESCALATION,
        )

    assert exc.value.code == "RECOMMENDATION_CONVERSION_REJECTED"
    assert "cannot be converted" in exc.value.message
    session.commit.assert_awaited_once()
