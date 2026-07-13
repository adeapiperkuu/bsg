from collections import Counter
from datetime import UTC, datetime
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
    _DetailBundle,
    _summary_project_metrics_stmt,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, Project
from tests.conftest import override_user


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


def test_summary_project_metrics_stmt_joins_aggregates() -> None:
    from datetime import date

    sql = str(
        _summary_project_metrics_stmt(_user(), today=date(2026, 7, 6)).compile(
            compile_kwargs={"literal_binds": False}
        )
    ).lower()

    assert "summary_dep_agg" in sql
    assert "summary_esc_agg" in sql
    assert "summary_overdue_agg" in sql
    assert "summary_scope_agg" in sql
    assert "outer join" in sql


def test_summary_unified_sql_keeps_aggregate_aliases() -> None:
    from app.agents.governance.services.analytics_service import _summary_unified_sql

    sql = str(_summary_unified_sql(include_signals=True)).lower()
    assert "summary_dep_agg" in sql
    assert "summary_esc_agg" in sql
    assert "summary_overdue_agg" in sql
    assert "summary_scope_agg" in sql
    assert "signal_bundle" in sql
    assert "visible_projects" in sql


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

    async def _fake_bundle(_session, _user, *, today):
        return (
            projects,
            {project.id: (0, 0) for project in projects},
            {project.id: (0, 0) for project in projects},
            {project.id: 0 for project in projects},
            {project.id: 0 for project in projects},
            {},
            {},
        )

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_summary_metric_bundle",
        _fake_bundle,
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

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_detail_project_bundle",
        AsyncMock(return_value=([], {}, {}, {}, {})),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_detail_second_bundle",
        AsyncMock(
            return_value=_DetailBundle(
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
        ),
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
async def test_detail_cache_miss_uses_two_bundles_then_cache_hit_uses_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    session = AsyncMock()
    project = Project(id=uuid4(), org_id=dm.org_id, name="Alpha")
    project_bundle_calls = 0
    source_bundle_calls = 0

    async def _project_bundle(_session, _user, *, today):
        nonlocal project_bundle_calls
        project_bundle_calls += 1
        return (
            [project],
            {project.id: (1, 1)},
            {project.id: (0, 0)},
            {project.id: 0},
            {project.id: 0},
        )

    async def _source_bundle(_session, _user, *, today, days, include_signals):
        nonlocal source_bundle_calls
        source_bundle_calls += 1
        return _DetailBundle(
            trend_dependencies=[],
            trend_escalations=[],
            trend_actions=[],
            trend_scopes=[],
            blocking_dependencies=[],
            critical_escalations=[],
            overdue_actions=[],
            dep_type_counter=Counter({"internal": 1}),
            esc_severity_counter=Counter(),
            action_status_counter=Counter(),
            recent_activity=[],
            delivery_signal_tuples=[],
        )

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_detail_project_bundle",
        _project_bundle,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_detail_second_bundle",
        _source_bundle,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_detail_cache",
        {},
    )

    first = await get_governance_analytics_detail(session, dm, days=30)
    second = await get_governance_analytics_detail(session, dm, days=30)

    assert first is second
    assert project_bundle_calls == 1
    assert source_bundle_calls == 1
    assert session.execute.await_count == 0


def test_detail_endpoint_complete_empty_contract_shape() -> None:
    detail = GovernanceAnalyticsDetailRead(
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
        date_range_days=30,
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

    assert detail.model_dump(mode="json") == {
        "generated_at": "2026-07-13T00:00:00Z",
        "date_range_days": 30,
        "insights": [],
        "recommendations": [],
        "trends": [],
        "charts": {
            "dependencies_by_type": [],
            "escalations_by_severity": [],
            "actions_by_status": [],
            "health_distribution": [],
            "most_active_projects": [],
        },
        "recent_activity": [],
        "export_sections": ["Charts", "Executive Insights", "Evidence Appendix"],
    }


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
