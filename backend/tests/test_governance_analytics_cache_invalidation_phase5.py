"""Phase 5: analytics summary/detail cache invalidation after governance writes."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsDetailRead,
    GovernanceAnalyticsSummaryRead,
)
from app.agents.governance.services import analytics_service
from app.agents.governance.services.analytics_service import (
    _analytics_cache_key,
    _DetailBundle,
    clear_governance_analytics_caches,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.agents.governance.services.governance_service import (
    invalidate_governance_read_caches_after_commit,
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


def _summary(days: int = 30) -> GovernanceAnalyticsSummaryRead:
    return GovernanceAnalyticsSummaryRead(
        generated_at=datetime.now(UTC),
        date_range_days=days,
        project_health=[],
        portfolio_risk_ranking=[],
        charts={},
        export_sections=["Governance Health"],
    )


def _detail(days: int = 30) -> GovernanceAnalyticsDetailRead:
    return GovernanceAnalyticsDetailRead(
        generated_at=datetime.now(UTC),
        date_range_days=days,
        insights=[],
        recommendations=[],
        trends=[],
        charts={
            "dependencies_by_type": [],
            "escalations_by_severity": [],
            "actions_by_status": [],
            "health_distribution": [],
            "most_active_projects": [],
        },
        recent_activity=[],
        export_sections=["Charts", "Executive Insights", "Evidence Appendix"],
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


def test_clear_analytics_caches_removes_org_and_cross_org_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_a = uuid4()
    org_b = uuid4()
    user_a = _user(org_id=org_a)
    user_b = _user(org_id=org_b)
    super_admin = _user(AppRole.SUPER_ADMIN, org_id=org_a)
    now = datetime.now(UTC)
    summary_cache = {
        _analytics_cache_key(user_a, 30): (now, _summary()),
        _analytics_cache_key(user_a, 7): (now, _summary(7)),
        _analytics_cache_key(user_b, 30): (now, _summary()),
        _analytics_cache_key(super_admin, 30): (now, _summary()),
    }
    detail_cache = {
        _analytics_cache_key(user_a, 30): (now, _detail()),
        _analytics_cache_key(user_b, 30): (now, _detail()),
        _analytics_cache_key(super_admin, 30): (now, _detail()),
    }
    monkeypatch.setattr(analytics_service, "_analytics_summary_cache", summary_cache)
    monkeypatch.setattr(analytics_service, "_analytics_detail_cache", detail_cache)

    result = clear_governance_analytics_caches(org_id=org_a)

    assert result.summary_removed == 3
    assert result.detail_removed == 2
    assert list(summary_cache) == [_analytics_cache_key(user_b, 30)]
    assert list(detail_cache) == [_analytics_cache_key(user_b, 30)]


def test_clear_analytics_caches_without_org_clears_all_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_a = _user()
    user_b = _user()
    now = datetime.now(UTC)
    summary_cache = {
        _analytics_cache_key(user_a, 30): (now, _summary()),
        _analytics_cache_key(user_b, 30): (now, _summary()),
    }
    detail_cache = {
        _analytics_cache_key(user_a, 30): (now, _detail()),
        _analytics_cache_key(user_b, 30): (now, _detail()),
    }
    monkeypatch.setattr(analytics_service, "_analytics_summary_cache", summary_cache)
    monkeypatch.setattr(analytics_service, "_analytics_detail_cache", detail_cache)

    result = clear_governance_analytics_caches(org_id=None)

    assert result.summary_removed == 2
    assert result.detail_removed == 2
    assert summary_cache == {}
    assert detail_cache == {}


@pytest.mark.asyncio
async def test_post_commit_invalidation_forces_next_summary_and_detail_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    now = datetime.now(UTC)
    monkeypatch.setattr(
        analytics_service,
        "_analytics_summary_cache",
        {_analytics_cache_key(user, 30): (now, _summary())},
    )
    monkeypatch.setattr(
        analytics_service,
        "_analytics_detail_cache",
        {_analytics_cache_key(user, 30): (now, _detail())},
    )
    summary_bundle_calls = 0
    project_bundle_calls = 0
    source_bundle_calls = 0

    async def _summary_bundle(_session, _current_user, *, today):
        nonlocal summary_bundle_calls
        summary_bundle_calls += 1
        return ([], {}, {}, {}, {}, {}, {})

    async def _project_bundle(_session, _current_user, *, today):
        nonlocal project_bundle_calls
        project_bundle_calls += 1
        return ([], {}, {}, {}, {})

    async def _source_bundle(_session, _current_user, *, today, days, include_signals):
        nonlocal source_bundle_calls
        source_bundle_calls += 1
        return _empty_detail_bundle()

    monkeypatch.setattr(analytics_service, "_fetch_summary_metric_bundle", _summary_bundle)
    monkeypatch.setattr(analytics_service, "_fetch_detail_project_bundle", _project_bundle)
    monkeypatch.setattr(analytics_service, "_fetch_detail_second_bundle", _source_bundle)
    monkeypatch.setattr(
        analytics_service,
        "_fetch_ai_recommendations_for_insights",
        AsyncMock(return_value=[]),
    )

    result = invalidate_governance_read_caches_after_commit(org_id=user.org_id)
    assert result.analytics_summary_removed == 1
    assert result.analytics_detail_removed == 1

    session = AsyncMock()
    await get_governance_analytics_summary(session, user, days=30)
    await get_governance_analytics_detail(session, user, days=30)

    assert summary_bundle_calls == 1
    assert project_bundle_calls == 1
    assert source_bundle_calls == 1
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_write_before_post_commit_helper_leaves_analytics_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    cached_summary = _summary()
    cached_detail = _detail()
    now = datetime.now(UTC)
    monkeypatch.setattr(
        analytics_service,
        "_analytics_summary_cache",
        {_analytics_cache_key(user, 30): (now, cached_summary)},
    )
    monkeypatch.setattr(
        analytics_service,
        "_analytics_detail_cache",
        {_analytics_cache_key(user, 30): (now, cached_detail)},
    )

    async def _write_that_rolls_back() -> None:
        raise RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        await _write_that_rolls_back()

    session = AsyncMock()
    summary = await get_governance_analytics_summary(session, user, days=30)
    detail = await get_governance_analytics_detail(session, user, days=30)

    assert summary is cached_summary
    assert detail is cached_detail
    session.execute.assert_not_awaited()
