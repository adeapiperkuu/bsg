from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsDetailRead,
    GovernanceAnalyticsRead,
    GovernanceAnalyticsSummaryRead,
    GovernanceHealthProjectRead,
)
from app.agents.governance.services.analytics_service import (
    SUMMARY_RANKING_LIMIT,
    _analytics_cache,
    _analytics_detail_cache,
    _analytics_summary_cache,
    get_governance_analytics,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, Project
from tests.conftest import delivery_manager, override_user


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _sample_health(project_id: UUID | None = None) -> GovernanceHealthProjectRead:
    pid = project_id or uuid4()
    return GovernanceHealthProjectRead(
        project_id=pid,
        project_name="Alpha",
        score=88,
        risk_level="healthy",
        priority=10,
        blocking_dependencies=1,
        open_dependencies=1,
        open_escalations=0,
        critical_escalations=0,
        overdue_actions=0,
        pending_scope_revisions=0,
        trend="stable",
    )


@pytest.mark.asyncio
async def test_get_governance_analytics_summary_limits_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    session = AsyncMock()
    projects = [
        Project(id=uuid4(), org_id=dm.org_id, name=f"Project {index}")
        for index in range(12)
    ]

    async def _fake_visible(_session, _user):
        return projects

    async def _dep_counts(_session, _user):
        return {project.id: (0, 0) for project in projects}

    async def _esc_counts(_session, _user):
        return {project.id: (0, 0) for project in projects}

    async def _overdue_counts(_session, _user, *, today):
        return {project.id: 0 for project in projects}

    async def _pending_counts(_session, _user):
        return {project.id: 0 for project in projects}

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_visible_projects",
        _fake_visible,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_dependency_counts_by_project",
        _dep_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_escalation_counts_by_project",
        _esc_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_overdue_action_counts_by_project",
        _overdue_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_pending_scope_counts_by_project",
        _pending_counts,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        {},
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_delivery_by_project",
        AsyncMock(return_value={}),
    )

    summary = await get_governance_analytics_summary(session, dm, days=30)

    assert isinstance(summary, GovernanceAnalyticsSummaryRead)
    assert len(summary.portfolio_risk_ranking) <= SUMMARY_RANKING_LIMIT
    assert len(summary.project_health) <= SUMMARY_RANKING_LIMIT
    assert "health_distribution" in summary.charts
    assert summary.export_sections == ["Governance Health"]


@pytest.mark.asyncio
async def test_detail_does_not_call_get_portfolio_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    session = AsyncMock()

    async def _portfolio_should_not_run(*_args, **_kwargs):
        raise AssertionError("get_portfolio_data must not be called for analytics detail")

    monkeypatch.setattr(
        "app.agents.delivery.services.dashboard_service.get_portfolio_data",
        _portfolio_should_not_run,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service.fetch_governance_delivery_signals",
        AsyncMock(return_value={}),
    )

    async def _empty_list(*_args, **_kwargs):
        return []

    async def _empty_mapping(_session, _user):
        return {}

    async def _empty_mapping_today(_session, _user, *, today):
        return {}

    async def _empty_counter(*_args, **_kwargs):
        from collections import Counter

        return Counter()

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_visible_projects",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_dependency_counts_by_project",
        _empty_mapping,
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
        "app.agents.governance.services.analytics_service._fetch_blocking_dependencies",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_critical_escalations",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_project_evidence",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_trend_series_bundle",
        AsyncMock(return_value=([], [], [], [])),
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
        "app.agents.governance.services.analytics_service._fetch_overdue_actions",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_recent_activity",
        _empty_list,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_detail_cache",
        {},
    )

    detail = await get_governance_analytics_detail(session, dm, days=7)

    assert isinstance(detail, GovernanceAnalyticsDetailRead)
    assert detail.date_range_days == 7
    assert len(detail.trends) == 7
    assert detail.recommendations == []
    assert detail.export_sections == ["Charts", "Executive Insights", "Evidence Appendix"]


@pytest.mark.asyncio
async def test_governance_analytics_summary_endpoint_contract(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    async def _summary(_session, _user, *, days: int) -> GovernanceAnalyticsSummaryRead:
        return GovernanceAnalyticsSummaryRead(
            generated_at=datetime.now(UTC),
            date_range_days=days,
            project_health=[_sample_health()],
            portfolio_risk_ranking=[_sample_health()],
            charts={},
            export_sections=["Governance Health"],
        )

    monkeypatch.setattr(
        "app.agents.governance.routes.governance.get_governance_analytics_summary",
        _summary,
    )

    override_user(delivery_manager)
    response = await api_client.get("/api/v1/governance/analytics/summary?days=30")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["date_range_days"] == 30
    assert len(body["data"]["portfolio_risk_ranking"]) == 1


@pytest.mark.asyncio
async def test_governance_analytics_detail_endpoint_contract(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    async def _detail(_session, _user, *, days: int) -> GovernanceAnalyticsDetailRead:
        return GovernanceAnalyticsDetailRead(
            generated_at=datetime.now(UTC),
            date_range_days=days,
            insights=[],
            recommendations=[],
            trends=[],
            charts={"dependencies_by_type": []},
            recent_activity=[],
            export_sections=["Charts"],
        )

    monkeypatch.setattr(
        "app.agents.governance.routes.governance.get_governance_analytics_detail",
        _detail,
    )

    override_user(delivery_manager)
    response = await api_client.get("/api/v1/governance/analytics/detail?days=30")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["date_range_days"] == 30
    assert "dependencies_by_type" in body["data"]["charts"]


@pytest.mark.asyncio
async def test_governance_analytics_full_endpoint_still_works(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    async def _analytics(_session, _user, *, days: int) -> GovernanceAnalyticsRead:
        health = _sample_health()
        return GovernanceAnalyticsRead(
            generated_at=datetime.now(UTC),
            date_range_days=days,
            project_health=[health],
            portfolio_risk_ranking=[health],
            insights=[],
            recommendations=[],
            trends=[],
            charts={},
            recent_activity=[],
            export_sections=["Charts"],
        )

    monkeypatch.setattr(
        "app.agents.governance.routes.governance.get_governance_analytics",
        _analytics,
    )

    override_user(delivery_manager)
    response = await api_client.get("/api/v1/governance/analytics?days=30")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["export_sections"] == ["Charts"]
