from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.governance.services.analytics_service import (
    get_governance_analytics_summary,
)
from app.agents.governance.services.delivery_signals import (
    _gather_governance_signal_inputs,
    _parse_governance_signal_bundle_rows,
    fetch_governance_delivery_signals,
)
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
    signals = {
        project.id: {
            "dashboard": {
                "confidence": 72.0,
                "traffic_light": "yellow",
                "overview": {"quality_snapshot": {"has_drift_alert": True}},
            }
        }
    }

    async def _portfolio_should_not_run(*_args, **_kwargs):
        raise AssertionError("get_portfolio_data must not be called for analytics summary")

    monkeypatch.setattr(
        "app.agents.delivery.services.dashboard_service.get_portfolio_data",
        _portfolio_should_not_run,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_summary_metric_bundle",
        AsyncMock(
            return_value=(
                [project],
                {project.id: (0, 0)},
                {project.id: (0, 0)},
                {project.id: 0},
                {project.id: 0},
                signals,
                {"project_metrics": 1.0, "delivery_signals": 1.0},
            )
        ),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        {},
    )

    summary = await get_governance_analytics_summary(session, dm, days=30)

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
                    projects_by_id={allowed_project.id: allowed_project},
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


def test_parse_governance_signal_bundle_rows_coerces_milestone_dates() -> None:
    project_id = uuid4()
    throughput, quality, milestones, risks, bottlenecks = _parse_governance_signal_bundle_rows(
        [
            (
                "milestone",
                project_id,
                {
                    "id": str(uuid4()),
                    "project_id": str(project_id),
                    "name": "M1",
                    "description": None,
                    "planned_date": "2026-07-10",
                    "actual_date": None,
                    "status": "on_track",
                },
            )
        ],
        [project_id],
    )

    assert milestones[project_id][0]["planned_date"] == date(2026, 7, 10)
    assert quality[project_id] is None
    assert risks[project_id] == []
    assert bottlenecks[project_id] == []


@pytest.mark.asyncio
async def test_gather_governance_signal_inputs_uses_single_execute() -> None:
    project_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(all=lambda: []))

    await _gather_governance_signal_inputs(session, [project_id])

    session.execute.assert_awaited_once()
