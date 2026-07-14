"""Phase 6 hardening guards for governance latency instrumentation and caches."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.schemas.governance import GovernanceKpisRead
from app.agents.governance.services import analytics_service, dashboard_service
from app.agents.governance.services.analytics_service import (
    _DetailBundle,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.agents.governance.services.dashboard_service import (
    _bootstrap_cache_key,
    clear_governance_bootstrap_cache,
)
from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
    invalidate_governance_read_caches_after_commit,
    list_governance_actions_page,
    list_governance_scope_states_page,
)
from app.agents.governance.timing import (
    GovernanceEndpointTimer,
    _reset_governance_timer,
    _set_governance_timer,
)
from app.core.security import CurrentUser
from app.db.models import AppRole


def _user(
    role: AppRole = AppRole.DELIVERY_MANAGER,
    *,
    org_id=None,
    user_id=None,
) -> CurrentUser:
    return CurrentUser(
        id=user_id or uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _kpis() -> GovernanceKpisRead:
    return GovernanceKpisRead(
        open_actions=1,
        overdue_actions=0,
        open_escalations=1,
        blocking_dependencies=1,
        at_risk_items=2,
        sla_adherence_pct=100.0,
    )


def _empty_detail_bundle() -> _DetailBundle:
    return _DetailBundle(
        trend_dependencies=[],
        trend_escalations=[],
        trend_actions=[],
        trend_scopes=[],
        blocking_dependencies=[],
        critical_escalations=[],
        overdue_actions=[],
        dep_type_counter=Counter(),
        esc_severity_counter=Counter(),
        action_status_counter=Counter(),
        recent_activity=[],
        delivery_signal_tuples=[],
    )


def test_bootstrap_cache_invalidation_matches_org_and_cross_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_a = uuid4()
    org_b = uuid4()
    user_a = _user(org_id=org_a)
    user_b = _user(org_id=org_b)
    super_admin = _user(AppRole.SUPER_ADMIN, org_id=org_a)
    now = datetime.now(UTC)
    cache = {
        _bootstrap_cache_key(user_a): (now, _kpis()),
        _bootstrap_cache_key(user_b): (now, _kpis()),
        _bootstrap_cache_key(super_admin): (now, _kpis()),
    }
    monkeypatch.setattr(dashboard_service, "_bootstrap_kpi_cache", cache)

    removed = clear_governance_bootstrap_cache(org_id=org_a)

    assert removed == 2
    assert list(cache) == [_bootstrap_cache_key(user_b)]


def test_post_commit_invalidation_clears_bootstrap_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    now = datetime.now(UTC)
    monkeypatch.setattr(
        dashboard_service,
        "_bootstrap_kpi_cache",
        {_bootstrap_cache_key(user): (now, _kpis())},
    )

    result = invalidate_governance_read_caches_after_commit(org_id=user.org_id)

    assert result.bootstrap_removed == 1
    assert dashboard_service._bootstrap_kpi_cache == {}


@pytest.mark.asyncio
async def test_summary_and_detail_execute_count_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    monkeypatch.setattr(analytics_service, "_analytics_summary_cache", {})
    monkeypatch.setattr(analytics_service, "_analytics_detail_cache", {})

    async def _summary_bundle(_session, _current_user, *, today):
        return ([], {}, {}, {}, {}, {}, {})

    async def _project_bundle(_session, _current_user, *, today):
        return ([], {}, {}, {}, {})

    async def _source_bundle(_session, _current_user, *, today, days, include_signals):
        return _empty_detail_bundle()

    monkeypatch.setattr(analytics_service, "_fetch_summary_metric_bundle", _summary_bundle)
    monkeypatch.setattr(analytics_service, "_fetch_detail_project_bundle", _project_bundle)
    monkeypatch.setattr(analytics_service, "_fetch_detail_second_bundle", _source_bundle)
    monkeypatch.setattr(
        analytics_service,
        "_fetch_ai_recommendations_for_insights",
        AsyncMock(return_value=[]),
    )

    summary_timer = GovernanceEndpointTimer("GET /governance/analytics/summary", user)
    token = _set_governance_timer(summary_timer)
    try:
        await get_governance_analytics_summary(AsyncMock(), user, days=30)
    finally:
        _reset_governance_timer(token)

    detail_timer = GovernanceEndpointTimer("GET /governance/analytics/detail", user)
    token = _set_governance_timer(detail_timer)
    try:
        await get_governance_analytics_detail(AsyncMock(), user, days=30)
    finally:
        _reset_governance_timer(token)

    assert summary_timer.execute_count == 1
    assert summary_timer.cache_hit is False
    assert detail_timer.execute_count == 3
    assert detail_timer.cache_hit is False


@pytest.mark.asyncio
async def test_actions_and_scope_lists_record_execute_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    page = PaginatedGovernanceRows(
        items=[MagicMock()],
        total=1,
        limit=6,
        offset=0,
        db_executes=1,
    )

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        return page

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_paginated_rows",
        _paginate,
    )

    actions_timer = GovernanceEndpointTimer("GET /governance/actions", user)
    token = _set_governance_timer(actions_timer)
    try:
        await list_governance_actions_page(AsyncMock(), user, limit=6, offset=0)
    finally:
        _reset_governance_timer(token)

    scope_timer = GovernanceEndpointTimer("GET /governance/scope-states", user)
    token = _set_governance_timer(scope_timer)
    try:
        await list_governance_scope_states_page(AsyncMock(), user, limit=6, offset=0)
    finally:
        _reset_governance_timer(token)

    assert actions_timer.execute_count == 1
    assert actions_timer.cache_hit is False
    assert scope_timer.execute_count == 1
    assert scope_timer.cache_hit is False
