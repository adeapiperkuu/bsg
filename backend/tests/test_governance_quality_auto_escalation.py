"""Tests for quality→governance auto-escalation (BR-06)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.escalation import business_days_between, check_quality_escalations
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    GovernanceEscalationSourceType,
    RiskTier,
)


def test_business_days_between_skips_weekends() -> None:
    start = datetime(2026, 7, 10, 12, tzinfo=UTC)  # Friday
    end = datetime(2026, 7, 14, 12, tzinfo=UTC)  # Tuesday
    assert business_days_between(start, end) == 2


@pytest.mark.asyncio
async def test_check_quality_escalations_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.governance.escalation.get_settings",
        lambda: SimpleNamespace(governance_quality_auto_escalation_enabled=False),
    )
    session = AsyncMock()
    assert await check_quality_escalations(session) == 0
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_check_quality_escalations_promotes_critical_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.governance.escalation.get_settings",
        lambda: SimpleNamespace(governance_quality_auto_escalation_enabled=True),
    )
    monkeypatch.setattr(
        "app.agents.governance.escalation.refresh_project_governance_summary",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.agents.governance.escalation.create_governance_notification",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.agents.governance.escalation.invalidate_governance_read_caches_after_commit",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.agents.governance.escalation._system_actor_for_org",
        AsyncMock(
            return_value=CurrentUser(
                id=uuid4(),
                org_id=uuid4(),
                email="dm@example.com",
                role=AppRole.DELIVERY_MANAGER,
                is_active=True,
            )
        ),
    )

    org_id = uuid4()
    project_id = uuid4()
    alert_id = uuid4()
    alert = SimpleNamespace(
        id=alert_id,
        org_id=org_id,
        project_id=project_id,
        title="Accuracy dropped",
        created_at=datetime.now(UTC) - timedelta(hours=2),
        risk_tier=RiskTier.CRITICAL,
        alert_type=AlertType.QUALITY_DRIFT,
        status=AlertStatus.OPEN,
    )
    project = SimpleNamespace(id=project_id, org_id=org_id)

    session = AsyncMock()
    # open alerts query, existing escalation check, existing action check
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=[(alert, project)])),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    created = await check_quality_escalations(session)
    assert created == 1
    assert session.add.call_count >= 2
    escalation = session.add.call_args_list[0].args[0]
    assert escalation.source_type == GovernanceEscalationSourceType.QUALITY_RISK
    assert escalation.source_id == alert_id
    assert escalation.client_visible is False
    session.commit.assert_awaited()
