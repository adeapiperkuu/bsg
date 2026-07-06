from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from datetime import date

import pytest

from app.agents.governance.services.analytics_service import (
    ANALYTICS_CACHE_TTL,
    _analytics_cache,
    _analytics_cache_key,
    _merge_project_metrics,
    _score_project_from_metrics,
    _fetch_dependency_counts_by_project,
    _fetch_visible_projects,
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
        "app.agents.governance.services.analytics_service._fetch_visible_projects",
        AsyncMock(return_value=[project]),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_delivery_by_project",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_cache",
        {},
    )

    analytics = await get_governance_analytics(session, dm, days=7)

    assert analytics.project_health[0].project_name == "Alpha"
    assert analytics.project_health[0].score == 88
    assert analytics.kpis.blocking_dependencies == 1
    assert analytics.date_range_days == 7
    assert analytics.export_sections == [
        "KPIs",
        "Charts",
        "Executive Insights",
        "Governance Health",
        "Evidence Appendix",
    ]
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_governance_analytics_uses_in_process_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user(AppRole.DELIVERY_MANAGER)
    session = AsyncMock()
    project = Project(id=uuid4(), org_id=dm.org_id, name="Alpha")
    calls = 0

    async def _fake_visible_projects(_session, _user):
        nonlocal calls
        calls += 1
        return [project]

    async def _fake_dependency_counts(_session, _user):
        nonlocal calls
        calls += 1
        return {project.id: (0, 0)}

    async def _empty_mapping(_session, _user):
        return {}

    async def _empty_mapping_today(_session, _user, *, today):
        return {}

    async def _empty_list(*_args, **_kwargs):
        return []

    async def _inventory_totals(_session, _user, *, today):
        return 0, 0, 0, 0, 0, 100.0

    async def _zero_int(_session, _user, *, today):
        return 0

    async def _none_averages(_session, _user):
        return None, None, None

    async def _empty_counter(*_args, **_kwargs):
        from collections import Counter

        return Counter()

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_visible_projects",
        _fake_visible_projects,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_dependency_counts_by_project",
        _fake_dependency_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_escalation_counts_by_project",
        _empty_mapping,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_overdue_action_counts_by_project",
        _empty_mapping_today,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_pending_scope_counts_by_project",
        _empty_mapping,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_delivery_by_project",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_project_evidence",
        AsyncMock(return_value={}),
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
        "app.agents.governance.services.analytics_service._analytics_cache",
        {},
    )

    first = await get_governance_analytics(session, dm, days=30)
    second = await get_governance_analytics(session, dm, days=30)

    assert first is second
    assert calls == 2


@pytest.mark.asyncio
async def test_derive_project_evidence_filters_to_requested_projects() -> None:
    from app.agents.governance.services.analytics_service import _derive_project_evidence
    from app.db.models import (
        GovernanceDependencyStatus,
        GovernanceEscalationSeverity,
        GovernanceEscalationStatus,
        ProjectDependency,
        GovernanceEscalation,
    )

    project_id = uuid4()
    other_id = uuid4()
    dep = ProjectDependency(
        id=uuid4(),
        org_id=uuid4(),
        project_id=project_id,
        title="Blocked API",
        status=GovernanceDependencyStatus.BLOCKING,
    )
    esc = GovernanceEscalation(
        id=uuid4(),
        org_id=uuid4(),
        project_id=other_id,
        title="Critical vendor",
        severity=GovernanceEscalationSeverity.CRITICAL,
        status=GovernanceEscalationStatus.OPEN,
    )

    evidence = _derive_project_evidence(
        [dep],
        [esc],
        project_ids=[project_id],
        project_names={project_id: "Alpha"},
    )

    assert len(evidence[project_id]) == 1
    assert evidence[project_id][0].label == "Blocked API"
    assert other_id not in evidence


def test_analytics_cache_key_scopes_by_org_role_user_and_days() -> None:
    org_id = uuid4()
    user_id = uuid4()
    dm = CurrentUser(
        id=user_id,
        org_id=org_id,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    other = CurrentUser(
        id=uuid4(),
        org_id=org_id,
        email="other@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )

    assert _analytics_cache_key(dm, 30) == (org_id, "delivery_manager", user_id, 30)
    assert _analytics_cache_key(dm, 7) != _analytics_cache_key(dm, 30)
    assert _analytics_cache_key(dm, 30) != _analytics_cache_key(other, 30)
    assert ANALYTICS_CACHE_TTL.total_seconds() == 180
