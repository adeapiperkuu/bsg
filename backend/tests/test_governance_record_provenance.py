"""Phase 8: provenance links from AI-created governance records."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.services import record_provenance_service as provenance
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationConversion,
    GovernanceAIRecommendationPriority,
    GovernanceAIRecommendationScope,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceRecommendationConversionTarget,
    GovernanceRecordEvidenceSourceType,
    GovernanceRecordLinkType,
    GovernanceRecordTargetType,
)


def _dm(org_id):
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _client(org_id):
    return CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="client@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )


def _recommendation(*, org_id, project_id, evidence_refs):
    return GovernanceAIRecommendation(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        scope=GovernanceAIRecommendationScope.PROJECT,
        recommendation_type=GovernanceAIRecommendationType.GENERAL_GOVERNANCE,
        title="Review blocking dependency",
        narrative="Review blocking dependency.",
        rationale="Evidence supports review.",
        priority=GovernanceAIRecommendationPriority.HIGH,
        confidence=0.82,
        status=GovernanceAIRecommendationStatus.ACTIVE,
        suggested_actions=[{"label": "Create action", "action_type": "create_action"}],
        evidence_refs=evidence_refs,
        evidence_hash="hash",
        fingerprint="fp",
        source_snapshot={},
        model_name="test",
        model_version=None,
        prompt_version="v1",
        generation_request_id=uuid4(),
        generated_by_user_id=uuid4(),
    )


def _conversion(*, org_id, recommendation_id, action_id=None, escalation_id=None):
    return GovernanceAIRecommendationConversion(
        id=uuid4(),
        org_id=org_id,
        recommendation_id=recommendation_id,
        suggested_action_index=0,
        conversion_target=(
            GovernanceRecommendationConversionTarget.ACTION
            if action_id
            else GovernanceRecommendationConversionTarget.ESCALATION
        ),
        created_action_id=action_id,
        created_escalation_id=escalation_id,
        created_by_user_id=uuid4(),
        request_fingerprint="fp",
        idempotency_key="key-1",
        note=None,
    )


@pytest.mark.asyncio
async def test_create_provenance_links_source_and_supporting(monkeypatch) -> None:
    org_id = uuid4()
    project_id = uuid4()
    dependency_id = uuid4()
    recommendation = _recommendation(
        org_id=org_id,
        project_id=project_id,
        evidence_refs=[
            {
                "evidence_id": f"dependency:{dependency_id}",
                "entity_type": "dependency",
                "entity_id": str(dependency_id),
                "project_id": str(project_id),
                "title": "Vendor blocker",
                "status": "blocking",
                "severity": "high",
                "summary": "Blocked vendor work",
            },
            {
                "evidence_id": f"dependency:{dependency_id}",
                "entity_type": "dependency",
                "entity_id": str(dependency_id),
                "project_id": str(project_id),
                "title": "Vendor blocker duplicate",
            },
            {
                "evidence_id": "unknown:1",
                "entity_type": "not_a_real_type",
                "entity_id": str(uuid4()),
                "project_id": str(project_id),
                "title": "Bad",
            },
        ],
    )
    action_id = uuid4()
    conversion = _conversion(
        org_id=org_id,
        recommendation_id=recommendation.id,
        action_id=action_id,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None, all=lambda: [])
    )
    session.flush = AsyncMock()

    monkeypatch.setattr(provenance, "get_visible_project", AsyncMock(return_value=object()))
    monkeypatch.setattr(provenance, "_source_exists", AsyncMock(return_value=True))

    result = await provenance.create_conversion_provenance_links(
        session,
        _dm(org_id),
        recommendation=recommendation,
        conversion=conversion,
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=action_id,
    )

    assert result.created == 3  # source + converted_from + one supporting
    assert result.duplicates_suppressed == 1
    assert result.skipped == 1
    assert GovernanceRecordEvidenceSourceType.DEPENDENCY.value in result.source_types
    assert session.add.call_count == 3
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_create_provenance_links_idempotent_when_source_exists(monkeypatch) -> None:
    org_id = uuid4()
    project_id = uuid4()
    recommendation = _recommendation(org_id=org_id, project_id=project_id, evidence_refs=[])
    action_id = uuid4()
    conversion = _conversion(
        org_id=org_id,
        recommendation_id=recommendation.id,
        action_id=action_id,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: uuid4(), all=lambda: [])
    )

    result = await provenance.create_conversion_provenance_links(
        session,
        _dm(org_id),
        recommendation=recommendation,
        conversion=conversion,
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=action_id,
    )

    assert result.created == 0
    assert result.duplicates_suppressed == 1
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_provenance_summary_hidden_from_clients() -> None:
    summary = await provenance.provenance_summary_for_target(
        AsyncMock(),
        _client(uuid4()),
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=uuid4(),
        org_id=uuid4(),
    )
    assert summary["has_ai_source"] is False
    assert summary["evidence_link_count"] == 0
    assert summary["source_recommendation_id"] is None


@pytest.mark.asyncio
async def test_list_evidence_requires_internal_role() -> None:
    with pytest.raises(ApiError) as exc:
        await provenance.list_record_evidence_links(
            AsyncMock(),
            _client(uuid4()),
            target_type=GovernanceRecordTargetType.ACTION,
            target_id=uuid4(),
            org_id=uuid4(),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_provenance_summary_for_ai_source(monkeypatch) -> None:
    org_id = uuid4()
    project_id = uuid4()
    rec_id = uuid4()
    conversion_id = uuid4()
    link = SimpleNamespace(
        recommendation_id=rec_id,
        source_id=rec_id,
        conversion_id=conversion_id,
        title="Review blocking dependency",
        project_id=project_id,
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: link),
            SimpleNamespace(all=lambda: [(uuid4(),), (uuid4(),)]),
        ]
    )
    monkeypatch.setattr(provenance, "get_visible_project", AsyncMock(return_value=object()))

    summary = await provenance.provenance_summary_for_target(
        session,
        _dm(org_id),
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=uuid4(),
        org_id=org_id,
    )
    assert summary["has_ai_source"] is True
    assert summary["provenance_source_type"] == "ai_recommendation"
    assert summary["source_recommendation_id"] == rec_id
    assert summary["source_recommendation_title"] == "Review blocking dependency"
    assert summary["source_conversion_id"] == conversion_id
    assert summary["evidence_link_count"] == 2


@pytest.mark.asyncio
async def test_source_recommendation_unavailable_when_project_hidden(monkeypatch) -> None:
    org_id = uuid4()
    project_id = uuid4()
    rec_id = uuid4()
    link = SimpleNamespace(
        recommendation_id=rec_id,
        title="Hidden rec",
        occurred_at=None,
        created_at=None,
    )
    recommendation = SimpleNamespace(
        id=rec_id,
        project_id=project_id,
        title="Secret",
        recommendation_type=SimpleNamespace(value="general_governance"),
        priority=SimpleNamespace(value="high"),
        confidence=0.9,
        generated_at=None,
        status=SimpleNamespace(value="active"),
        accepted_at=None,
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: link),
            SimpleNamespace(scalar_one_or_none=lambda: recommendation),
        ]
    )
    monkeypatch.setattr(
        provenance,
        "get_visible_project",
        AsyncMock(side_effect=ApiError(403, "FORBIDDEN", "hidden")),
    )

    result = await provenance.get_source_recommendation_summary(
        session,
        _dm(org_id),
        target_type=GovernanceRecordTargetType.ESCALATION,
        target_id=uuid4(),
        org_id=org_id,
    )
    assert result is not None
    assert result.can_view is False
    assert result.source_available is False
    assert result.title == "Source unavailable"


def test_related_link_mapping() -> None:
    assert (
        provenance.ENTITY_TYPE_TO_RELATED_LINK["dependency"]
        == GovernanceRecordLinkType.RELATED_DEPENDENCY
    )
    assert (
        provenance.ENTITY_TYPE_TO_SOURCE["scope_state"]
        == GovernanceRecordEvidenceSourceType.SCOPE_STATE
    )
