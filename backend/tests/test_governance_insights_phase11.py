"""Phase 11 — governance insights dashboard aggregates, filters, and contracts."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsDetailRead,
    GovernanceHealthProjectRead,
    GovernanceInsightsKpisRead,
)
from app.agents.governance.services import analytics_service
from app.agents.governance.services.analytics_service import (
    _DetailBundle,
    _analytics_cache_key,
    _build_insights_kpis,
    _build_most_affected_departments,
    _build_risk_heatmap,
    _build_top_mitigation_failures,
    _build_top_recurring_blockers,
    _build_trends,
    _filter_projects,
    _portfolio_governance_score,
    _rate_pct,
    clear_governance_analytics_caches,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceDependencyStatus,
    GovernanceEscalationTriggerType,
    GovernanceRecommendationAcceptanceStatus,
    Project,
)


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _health(
    *,
    score: int = 80,
    risk_level: str = "healthy",
    vertical: str | None = "Medical",
    name: str = "Alpha",
    blocking: int = 0,
    open_deps: int = 0,
    open_esc: int = 0,
    critical_esc: int = 0,
    overdue: int = 0,
    pending: int = 0,
) -> GovernanceHealthProjectRead:
    return GovernanceHealthProjectRead(
        project_id=uuid4(),
        project_name=name,
        score=score,
        risk_level=risk_level,
        priority=blocking * 20 + critical_esc * 30,
        blocking_dependencies=blocking,
        open_dependencies=open_deps,
        open_escalations=open_esc,
        critical_escalations=critical_esc,
        overdue_actions=overdue,
        pending_scope_revisions=pending,
        trend="stable",
        vertical=vertical,
    )


def _recommendation(**overrides):
    base = {
        "title": "Mitigate blocker",
        "generated_at": datetime.now(UTC),
        "accepted_at": None,
        "dismissed_at": None,
        "acceptance_status": GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        "status": GovernanceAIRecommendationStatus.ACTIVE,
        "auto_detected": False,
        "trigger_type": None,
        "recommendation_type": GovernanceAIRecommendationType.DEPENDENCY_MITIGATION,
        "project_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_portfolio_governance_score_is_mean_of_project_scores() -> None:
    rows = [_health(score=90), _health(score=70), _health(score=80)]
    assert _portfolio_governance_score(rows) == 80.0
    assert _portfolio_governance_score([]) == 100.0


def test_acceptance_and_dismissal_rate_math() -> None:
    recommendations = [
        _recommendation(
            acceptance_status=GovernanceRecommendationAcceptanceStatus.PARTIALLY_ACCEPTED,
            accepted_at=datetime.now(UTC),
        ),
        _recommendation(
            acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
            accepted_at=datetime.now(UTC),
        ),
        _recommendation(
            status=GovernanceAIRecommendationStatus.DISMISSED,
            dismissed_at=datetime.now(UTC),
        ),
        _recommendation(),
    ]
    kpis = _build_insights_kpis(
        project_health=[_health(score=50, risk_level="high_risk")],
        escalations_created=3,
        recommendations=recommendations,
        sla_adherence_pct=91.2,
    )
    assert isinstance(kpis, GovernanceInsightsKpisRead)
    assert kpis.portfolio_governance_score == 50.0
    assert kpis.projects_at_risk == 1
    assert kpis.recommendation_acceptance_rate_pct == 50.0
    assert kpis.recommendation_dismissal_rate_pct == 25.0
    assert kpis.escalations_created == 3
    assert kpis.recommendations_created == 4
    assert _rate_pct(1, 0) == 0.0


def test_filter_projects_by_project_id_and_vertical() -> None:
    org_id = uuid4()
    medical = Project(id=uuid4(), org_id=org_id, name="Med", vertical="Medical")
    finance = Project(id=uuid4(), org_id=org_id, name="Fin", vertical="Finance")
    projects = [medical, finance]

    assert _filter_projects(projects, project_id=medical.id) == [medical]
    assert _filter_projects(projects, vertical="finance") == [finance]
    assert _filter_projects(projects, project_id=medical.id, vertical="Finance") == []


def test_top_blockers_heatmap_and_departments() -> None:
    deps = [
        SimpleNamespace(
            status=GovernanceDependencyStatus.BLOCKING,
            dependency_type="external",
            project_id=uuid4(),
        ),
        SimpleNamespace(
            status=GovernanceDependencyStatus.BLOCKING,
            dependency_type="external",
            project_id=uuid4(),
        ),
        SimpleNamespace(
            status=GovernanceDependencyStatus.BLOCKING,
            dependency_type="internal",
            project_id=uuid4(),
        ),
    ]
    blockers = _build_top_recurring_blockers(deps)
    assert blockers[0].label == "External"
    assert blockers[0].count == 2

    health = [
        _health(score=30, risk_level="critical", vertical="Medical", blocking=2, overdue=1),
        _health(score=55, risk_level="high_risk", vertical="Medical", open_esc=1),
        _health(score=90, risk_level="excellent", vertical="Finance"),
    ]
    heatmap = _build_risk_heatmap(health)
    assert any(
        cell.vertical == "Medical" and cell.risk_level == "critical" and cell.project_count == 1
        for cell in heatmap
    )
    departments = _build_most_affected_departments(health)
    assert departments[0].vertical == "Medical"
    assert departments[0].count > 0


def test_mitigation_failure_aggregation() -> None:
    rows = [
        _recommendation(
            title="Retry mitigation",
            trigger_type=GovernanceEscalationTriggerType.REPEATED_MITIGATION_FAILURE,
        ),
        _recommendation(
            title="Retry mitigation",
            trigger_type=GovernanceEscalationTriggerType.REPEATED_MITIGATION_FAILURE,
        ),
        _recommendation(
            title="Dismissed mitigation",
            status=GovernanceAIRecommendationStatus.DISMISSED,
            dismissed_at=datetime.now(UTC),
        ),
    ]
    failures = _build_top_mitigation_failures(rows)
    assert failures[0].label == "Retry mitigation"
    assert failures[0].count == 2


def test_trends_include_recommendation_counters() -> None:
    now = datetime.now(UTC)
    recommendations = [
        _recommendation(generated_at=now, auto_detected=True),
        _recommendation(
            generated_at=now,
            accepted_at=now,
            acceptance_status=GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
        ),
        _recommendation(
            generated_at=now,
            dismissed_at=now,
            status=GovernanceAIRecommendationStatus.DISMISSED,
        ),
    ]
    points = _build_trends(
        days=7,
        project_health=[_health(score=88)],
        dependencies=[],
        escalations=[],
        actions=[],
        scopes=[],
        recommendations=recommendations,
    )
    assert len(points) == 7
    assert points[-1].portfolio_health == 88.0
    assert points[-1].recommendations_created >= 1
    assert points[-1].recommendations_accepted >= 1
    assert points[-1].recommendations_dismissed >= 1
    assert points[-1].escalation_suggestions_created >= 1


def test_analytics_cache_key_includes_filters() -> None:
    user = _user()
    project_id = uuid4()
    base = _analytics_cache_key(user, 30)
    filtered = _analytics_cache_key(user, 30, project_id=project_id, vertical="Medical")
    assert base != filtered
    assert base == (user.org_id, "delivery_manager", user.id, 30, None, None)
    assert filtered[4] == str(project_id)
    assert filtered[5] == "medical"


def test_cache_invalidation_clears_filtered_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    now = datetime.now(UTC)
    key = _analytics_cache_key(user, 30, vertical="Medical")
    summary_cache = {key: (now, object())}
    detail_cache = {key: (now, object())}
    monkeypatch.setattr(analytics_service, "_analytics_summary_cache", summary_cache)
    monkeypatch.setattr(analytics_service, "_analytics_detail_cache", detail_cache)

    result = clear_governance_analytics_caches(org_id=user.org_id)
    assert result.summary_removed == 1
    assert result.detail_removed == 1
    assert summary_cache == {}
    assert detail_cache == {}


@pytest.mark.asyncio
async def test_summary_excludes_heavy_insight_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    project = Project(id=uuid4(), org_id=user.org_id, name="Alpha", vertical="Medical")

    async def _fake_bundle(_session, _user, *, today):
        return (
            [project],
            {project.id: (0, 0)},
            {project.id: (0, 0)},
            {project.id: 0},
            {project.id: 0},
            {},
            {},
        )

    monkeypatch.setattr(analytics_service, "_fetch_summary_metric_bundle", _fake_bundle)
    monkeypatch.setattr(analytics_service, "_analytics_summary_cache", {})

    summary = await get_governance_analytics_summary(AsyncMock(), user, days=30)
    assert summary.insights_kpis is not None
    assert summary.portfolio_governance_score is not None
    assert not hasattr(summary, "risk_heatmap") or not getattr(summary, "risk_heatmap", None)
    assert "Insights KPIs" in summary.export_sections
    payload = summary.model_dump()
    assert "top_governance_risks" not in payload
    assert "risk_heatmap" not in payload


@pytest.mark.asyncio
async def test_detail_includes_insight_lists_and_respects_vertical_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    medical = Project(id=uuid4(), org_id=user.org_id, name="Med", vertical="Medical")
    finance = Project(id=uuid4(), org_id=user.org_id, name="Fin", vertical="Finance")

    async def _project_bundle(_session, _user, *, today):
        return (
            [medical, finance],
            {medical.id: (2, 2), finance.id: (0, 0)},
            {medical.id: (1, 1), finance.id: (0, 0)},
            {medical.id: 1, finance.id: 0},
            {medical.id: 0, finance.id: 0},
        )

    async def _source_bundle(_session, _user, *, today, days, include_signals):
        return _DetailBundle(
            trend_dependencies=[],
            trend_escalations=[],
            trend_actions=[],
            trend_scopes=[],
            blocking_dependencies=[
                SimpleNamespace(
                    status=GovernanceDependencyStatus.BLOCKING,
                    dependency_type="external",
                    project_id=medical.id,
                    id=uuid4(),
                    title="Vendor",
                    due_date=None,
                )
            ],
            critical_escalations=[],
            overdue_actions=[],
            dep_type_counter=Counter({"external": 1}),
            esc_severity_counter=Counter(),
            action_status_counter=Counter(),
            recent_activity=[],
            delivery_signal_tuples=[],
        )

    monkeypatch.setattr(analytics_service, "_fetch_detail_project_bundle", _project_bundle)
    monkeypatch.setattr(analytics_service, "_fetch_detail_second_bundle", _source_bundle)
    monkeypatch.setattr(
        analytics_service,
        "_fetch_ai_recommendations_for_insights",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(analytics_service, "_analytics_detail_cache", {})

    detail = await get_governance_analytics_detail(
        AsyncMock(),
        user,
        days=7,
        vertical="Medical",
    )
    assert isinstance(detail, GovernanceAnalyticsDetailRead)
    assert detail.insights_kpis is not None
    assert detail.risk_heatmap
    assert detail.top_recurring_blockers
    assert detail.most_affected_departments
    assert all(cell.vertical == "Medical" for cell in detail.risk_heatmap)
    assert "Insights KPIs" in detail.export_sections
