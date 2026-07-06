from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from datetime import date

import pytest

from app.agents.governance.services.analytics_service import (
    _merge_project_metrics,
    _score_project_from_metrics,
    _fetch_dependency_counts_by_project,
    _trend_window_start,
    get_governance_analytics,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, Project


def _user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def test_trend_window_start_aligns_with_selected_range() -> None:
    today = date(2026, 7, 6)
    window_start = _trend_window_start(today=today, days=7)

    assert window_start.date() == date(2026, 6, 30)


@pytest.mark.asyncio
async def test_fetch_dependency_counts_by_project_uses_single_aggregate_query() -> None:
    dm = _user(AppRole.DELIVERY_MANAGER)
    session = AsyncMock()
    project_id = uuid4()
    row = MagicMock(project_id=project_id, open=4, blocking=2)
    session.execute = AsyncMock(return_value=MagicMock(all=lambda: [row]))

    counts = await _fetch_dependency_counts_by_project(session, dm)

    assert counts[project_id] == (4, 2)
    session.execute.assert_awaited_once()


def test_score_project_from_metrics_applies_expected_penalties() -> None:
    org_id = uuid4()
    project = Project(id=uuid4(), org_id=org_id, name="Beta")
    metrics = _merge_project_metrics(
        project.id,
        dependency_counts={project.id: (3, 2)},
        escalation_counts={project.id: (2, 1)},
        overdue_actions={project.id: 1},
        pending_scopes={project.id: 1},
    )

    scored = _score_project_from_metrics(project, metrics, delivery_signal=None)

    assert scored.blocking_dependencies == 2
    assert scored.critical_escalations == 1
    assert scored.score == 100 - (2 * 12 + 1 * 16 + 1 * 8 + 1 * 7 + 1 * 9)


@pytest.mark.asyncio
async def test_get_governance_analytics_scores_projects_from_aggregate_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user(AppRole.DELIVERY_MANAGER)
    session = AsyncMock()
    project = Project(id=uuid4(), org_id=dm.org_id, name="Alpha")
    project_id = project.id

    async def _fake_dependency_counts(_session, _user):
        return {project_id: (1, 1)}

    async def _fake_escalation_counts(_session, _user):
        return {project_id: (0, 0)}

    async def _fake_overdue_counts(_session, _user, *, today):
        return {project_id: 0}

    async def _fake_pending_counts(_session, _user):
        return {project_id: 0}

    async def _empty_list(*_args, **_kwargs):
        return []

    async def _empty_portfolio(**_kwargs):
        return {"projects": []}

    async def _inventory_totals(_session, _user, *, today):
        return 1, 1, 0, 0, 0, 100.0

    async def _zero_int(_session, _user, *, today):
        return 0

    async def _none_averages(_session, _user):
        return None, None, None

    async def _empty_counter(*_args, **_kwargs):
        from collections import Counter

        return Counter()

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_dependency_counts_by_project",
        _fake_dependency_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_escalation_counts_by_project",
        _fake_escalation_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_overdue_action_counts_by_project",
        _fake_overdue_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_pending_scope_counts_by_project",
        _fake_pending_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_project_evidence",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_inventory_totals",
        _inventory_totals,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_open_action_count",
        _zero_int,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_resolution_averages",
        _none_averages,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_trend_dependencies",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_trend_escalations",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_trend_actions",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_trend_scopes",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_enum_counter",
        _empty_counter,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_action_status_counter",
        _empty_counter,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_blocking_dependencies",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_critical_escalations",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_overdue_actions",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_recent_activity",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service.get_portfolio_data",
        _empty_portfolio,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_cache",
        {},
    )

    execute_result = MagicMock()
    execute_result.scalars.return_value = [project]
    session.execute = AsyncMock(return_value=execute_result)

    analytics = await get_governance_analytics(session, dm, days=7)

    assert analytics.project_health[0].project_name == "Alpha"
    assert analytics.project_health[0].score == 88
    assert analytics.kpis.blocking_dependencies == 1
    session.execute.assert_awaited_once()
