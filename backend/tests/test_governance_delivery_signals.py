from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.governance.services.analytics_service import (
    get_governance_analytics_summary,
)
from app.agents.governance.services.delivery_signals import fetch_governance_delivery_signals
from app.core.security import CurrentUser
from app.db.models import AppRole, Project


def _user(role: AppRole = AppRole.DELIVERY_MANAGER, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_summary_does_not_call_get_portfolio_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    session = AsyncMock()
    project = Project(id=uuid4(), org_id=dm.org_id, name="Alpha")

    async def _portfolio_should_not_run(*_args, **_kwargs):
        raise AssertionError("get_portfolio_data must not be called for analytics summary")

    monkeypatch.setattr(
        "app.agents.delivery.services.dashboard_service.get_portfolio_data",
        _portfolio_should_not_run,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_visible_projects",
        AsyncMock(return_value=[project]),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_dependency_counts_by_project",
        AsyncMock(return_value={project.id: (0, 0)}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_escalation_counts_by_project",
        AsyncMock(return_value={project.id: (0, 0)}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_overdue_action_counts_by_project",
        AsyncMock(return_value={project.id: 0}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_pending_scope_counts_by_project",
        AsyncMock(return_value={project.id: 0}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        {},
    )

    signals = {
        project.id: {
            "dashboard": {
                "confidence": 72.0,
                "traffic_light": "yellow",
                "overview": {"quality_snapshot": {"has_drift_alert": True}},
            }
        }
    }
    fetch_mock = AsyncMock(return_value=signals)
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service.fetch_governance_delivery_signals",
        fetch_mock,
    )

    summary = await get_governance_analytics_summary(session, dm, days=30)

    fetch_mock.assert_awaited_once()
    assert summary.project_health[0].delivery_confidence == 72.0
    assert summary.project_health[0].delivery_traffic_light == "yellow"
    assert summary.project_health[0].quality_risk == "elevated"


@pytest.mark.asyncio
async def test_fetch_governance_delivery_signals_filters_other_org_projects() -> None:
    org_id = uuid4()
    other_org = uuid4()
    dm = _user(org_id=org_id)
    session = AsyncMock()

    allowed_project = Project(id=uuid4(), org_id=org_id, name="Allowed")
    blocked_project = Project(id=uuid4(), org_id=other_org, name="Blocked")

    async def _fake_filter(_session, _user, project_ids):
        return [allowed_project.id]

    with patch(
        "app.agents.governance.services.delivery_signals._filter_accessible_project_ids",
        _fake_filter,
    ):
        with patch(
            "app.agents.governance.services.delivery_signals._gather_governance_signal_inputs",
            AsyncMock(
                return_value=({}, {}, {allowed_project.id: []}, {allowed_project.id: []}, {allowed_project.id: []})
            ),
        ):
            with patch(
                "app.agents.governance.services.delivery_signals._governance_delivery_signal_payload",
                return_value={"dashboard": {"confidence": 80.0, "traffic_light": "green", "overview": {}}},
            ):
                signals = await fetch_governance_delivery_signals(
                    session,
                    dm,
                    [allowed_project.id, blocked_project.id],
                    projects_by_id={
                        allowed_project.id: allowed_project,
                        blocked_project.id: blocked_project,
                    },
                )

    assert set(signals.keys()) == {allowed_project.id}


@pytest.mark.asyncio
async def test_fetch_governance_delivery_signals_returns_empty_for_clients() -> None:
    client = _user(role=AppRole.CLIENT)
    session = AsyncMock()
    project_id = uuid4()

    signals = await fetch_governance_delivery_signals(
        session,
        client,
        [project_id],
    )

    assert signals == {}
    session.execute.assert_not_awaited()
