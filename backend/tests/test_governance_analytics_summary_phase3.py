"""Phase 3: analytics summary single-execute unified query."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsSummaryRead,
    GovernanceHealthProjectRead,
)
from app.agents.governance.services.analytics_service import (
    ANALYTICS_CACHE_TTL,
    _analytics_cache_key,
    _fetch_summary_metric_bundle,
    _fetch_summary_metric_bundle_two_query,
    _merge_project_metrics,
    _project_from_summary_row,
    _score_project_from_metrics,
    _signal_tuples_from_json,
    _summary_health_charts,
    _summary_include_delivery_signals,
    _summary_unified_sql,
    get_governance_analytics_summary,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, Project, ProjectStatus


def _user(role: AppRole = AppRole.DELIVERY_MANAGER, *, org_id=None, user_id=None) -> CurrentUser:
    return CurrentUser(
        id=user_id or uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _health(**overrides) -> GovernanceHealthProjectRead:
    base = GovernanceHealthProjectRead(
        project_id=uuid4(),
        project_name="Alpha",
        score=88,
        risk_level="healthy",
        priority=10,
        blocking_dependencies=1,
        open_dependencies=2,
        open_escalations=1,
        critical_escalations=0,
        overdue_actions=0,
        pending_scope_revisions=0,
        delivery_confidence=72.5,
        delivery_traffic_light="yellow",
        quality_risk="elevated",
        workforce_risk=None,
        trend="stable",
        evidence=[],
    )
    return base.model_copy(update=overrides)


def test_summary_contract_serializes_all_public_fields() -> None:
    summary = GovernanceAnalyticsSummaryRead(
        generated_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        date_range_days=30,
        project_health=[_health()],
        portfolio_risk_ranking=[_health()],
        charts={
            "health_distribution": [
                {"label": "Healthy", "value": 1.0, "secondary_value": None},
            ]
        },
        export_sections=["Governance Health"],
    )
    payload = TypeAdapter(GovernanceAnalyticsSummaryRead).dump_python(summary, mode="json")

    assert set(payload.keys()) == {
        "generated_at",
        "date_range_days",
        "project_health",
        "portfolio_risk_ranking",
        "charts",
        "export_sections",
    }
    health = payload["project_health"][0]
    assert set(health.keys()) == {
        "project_id",
        "project_name",
        "score",
        "risk_level",
        "priority",
        "blocking_dependencies",
        "open_dependencies",
        "open_escalations",
        "critical_escalations",
        "overdue_actions",
        "pending_scope_revisions",
        "delivery_confidence",
        "delivery_traffic_light",
        "quality_risk",
        "workforce_risk",
        "trend",
        "evidence",
    }
    assert payload["export_sections"] == ["Governance Health"]
    assert payload["date_range_days"] == 30


def test_unified_sql_includes_independent_aggregate_ctes_and_signals() -> None:
    sql = str(_summary_unified_sql(include_signals=True)).lower()
    assert "visible_projects" in sql
    assert "summary_dep_agg" in sql
    assert "summary_esc_agg" in sql
    assert "summary_overdue_agg" in sql
    assert "summary_scope_agg" in sql
    assert "signal_bundle" in sql
    assert "signals_agg" in sql
    assert "jsonb_agg" in sql
    # Aggregates are independent CTEs — not joined raw fact tables together.
    assert "left join summary_dep_agg" in sql
    assert "left join signals_agg" in sql


def test_unified_sql_omits_signals_for_client_path() -> None:
    sql = str(_summary_unified_sql(include_signals=False)).lower()
    assert "signal_bundle" not in sql
    assert "null::jsonb as delivery_signals" in sql


def test_include_delivery_signals_role_gate() -> None:
    assert _summary_include_delivery_signals(_user(AppRole.DELIVERY_MANAGER)) is True
    assert _summary_include_delivery_signals(_user(AppRole.BSG_LEADERSHIP)) is True
    assert _summary_include_delivery_signals(_user(AppRole.SUPER_ADMIN)) is True
    assert _summary_include_delivery_signals(_user(AppRole.CLIENT)) is False


def test_signal_json_does_not_multiply_metric_counts() -> None:
    """One project row carries many signal payloads; metrics stay scalar."""
    project_id = uuid4()
    signals = [
        {"kind": "throughput", "payload": {"units_completed": 1}},
        {"kind": "throughput", "payload": {"units_completed": 2}},
        {"kind": "quality", "payload": {"has_drift_alert": False, "rework_rate_pct": 1.0}},
        {"kind": "risk", "payload": {"project_id": str(project_id), "risk_tier": "medium"}},
        {"kind": "bottleneck", "payload": {"open_count": 3}},
    ]
    tuples = _signal_tuples_from_json(project_id, signals)
    assert len(tuples) == 5

    metrics = _merge_project_metrics(
        project_id,
        dependency_counts={project_id: (2, 1)},
        escalation_counts={project_id: (2, 1)},
        overdue_actions={project_id: 3},
        pending_scopes={project_id: 1},
    )
    assert metrics.open_dependencies == 2
    assert metrics.blocking_dependencies == 1
    assert metrics.open_escalations == 2
    assert metrics.critical_escalations == 1
    assert metrics.overdue_actions == 3
    assert metrics.pending_scope_revisions == 1


def test_project_from_summary_row_preserves_delivery_fields() -> None:
    project_id = uuid4()
    org_id = uuid4()
    project = _project_from_summary_row(
        {
            "id": project_id,
            "org_id": org_id,
            "name": "Gamma",
            "description": "desc",
            "vertical": "cv",
            "status": "active",
            "start_date": date(2026, 1, 1),
            "target_end_date": date(2026, 12, 31),
            "actual_end_date": None,
            "daily_target_units": 10,
        }
    )
    assert project.id == project_id
    assert project.org_id == org_id
    assert project.name == "Gamma"
    assert project.status == ProjectStatus.ACTIVE
    assert project.daily_target_units == 10


@pytest.mark.asyncio
async def test_summary_cache_miss_performs_one_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    project = Project(id=uuid4(), org_id=dm.org_id, name="Alpha", vertical="cv")
    project.status = ProjectStatus.ACTIVE
    project.start_date = date(2026, 1, 1)
    project.target_end_date = date(2026, 12, 31)

    row = {
        "id": project.id,
        "org_id": project.org_id,
        "name": project.name,
        "description": None,
        "vertical": "cv",
        "status": "active",
        "start_date": project.start_date,
        "target_end_date": project.target_end_date,
        "actual_end_date": None,
        "daily_target_units": None,
        "dep_open": 2,
        "dep_blocking": 1,
        "esc_open": 1,
        "esc_critical": 0,
        "overdue_actions": 0,
        "pending_scopes": 0,
        "delivery_signals": [],
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        {},
    )

    summary = await get_governance_analytics_summary(session, dm, days=30)

    assert session.execute.await_count == 1
    assert isinstance(summary, GovernanceAnalyticsSummaryRead)
    assert summary.date_range_days == 30
    assert summary.project_health[0].open_dependencies == 2
    assert summary.project_health[0].blocking_dependencies == 1
    assert summary.export_sections == ["Governance Health"]


@pytest.mark.asyncio
async def test_summary_cache_hit_performs_zero_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    now = datetime.now(UTC)
    cached = GovernanceAnalyticsSummaryRead(
        generated_at=now,
        date_range_days=30,
        project_health=[_health()],
        portfolio_risk_ranking=[_health()],
        charts=_summary_health_charts([_health()]),
        export_sections=["Governance Health"],
    )
    cache = {_analytics_cache_key(dm, 30): (now, cached)}
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        cache,
    )
    session = AsyncMock()

    summary = await get_governance_analytics_summary(session, dm, days=30)

    assert summary is cached
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_summary_cache_isolated_by_days_and_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    user_a = _user(org_id=org_id)
    user_b = _user(org_id=org_id)
    now = datetime.now(UTC)
    cached = GovernanceAnalyticsSummaryRead(
        generated_at=now,
        date_range_days=30,
        export_sections=["Governance Health"],
    )
    cache = {_analytics_cache_key(user_a, 30): (now, cached)}
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        cache,
    )

    assert _analytics_cache_key(user_a, 30) != _analytics_cache_key(user_a, 7)
    assert _analytics_cache_key(user_a, 30) != _analytics_cache_key(user_b, 30)
    assert ANALYTICS_CACHE_TTL.total_seconds() == 180

    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    # Different days must miss and execute.
    await get_governance_analytics_summary(session, user_a, days=7)
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_client_summary_skips_delivery_signal_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _user(AppRole.CLIENT)
    captured: dict[str, bool] = {}

    async def _fake_bundle(session, current_user, *, today):
        captured["include"] = _summary_include_delivery_signals(current_user)
        return ([], {}, {}, {}, {}, {}, {})

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_summary_metric_bundle",
        _fake_bundle,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._analytics_summary_cache",
        {},
    )

    summary = await get_governance_analytics_summary(AsyncMock(), client, days=30)
    assert captured["include"] is False
    assert summary.project_health == []


@pytest.mark.asyncio
async def test_fetch_summary_metric_bundle_single_execute_and_builds_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    project_id = uuid4()
    row = {
        "id": project_id,
        "org_id": dm.org_id,
        "name": "Alpha",
        "description": None,
        "vertical": "cv",
        "status": "active",
        "start_date": date(2026, 1, 1),
        "target_end_date": date(2026, 12, 31),
        "actual_end_date": None,
        "daily_target_units": None,
        "dep_open": 2,
        "dep_blocking": 1,
        "esc_open": 2,
        "esc_critical": 1,
        "overdue_actions": 3,
        "pending_scopes": 1,
        "delivery_signals": [
            {"kind": "quality", "payload": {"has_drift_alert": True, "rework_rate_pct": 4.0}},
        ],
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service.build_governance_delivery_signals_from_inputs",
        lambda *args, **kwargs: {
            project_id: {
                "dashboard": {
                    "confidence": 55.0,
                    "traffic_light": "red",
                    "overview": {"quality_snapshot": {"has_drift_alert": True}},
                }
            }
        },
    )

    (
        projects,
        dependency_counts,
        escalation_counts,
        overdue_by_project,
        pending_by_project,
        delivery_by_project,
        timings,
    ) = await _fetch_summary_metric_bundle(session, dm, today=date(2026, 7, 10))

    assert session.execute.await_count == 1
    assert "summary_unified" in timings
    assert len(projects) == 1
    assert dependency_counts[project_id] == (2, 1)
    assert escalation_counts[project_id] == (2, 1)
    assert overdue_by_project[project_id] == 3
    assert pending_by_project[project_id] == 1
    assert delivery_by_project[project_id]["dashboard"]["traffic_light"] == "red"

    # Counts must remain unmultiplied despite signal payloads on the same row.
    scored = _score_project_from_metrics(
        projects[0],
        _merge_project_metrics(
            project_id,
            dependency_counts=dependency_counts,
            escalation_counts=escalation_counts,
            overdue_actions=overdue_by_project,
            pending_scopes=pending_by_project,
        ),
        delivery_signal=delivery_by_project[project_id],
    )
    assert scored.open_dependencies == 2
    assert scored.blocking_dependencies == 1
    assert scored.open_escalations == 2
    assert scored.overdue_actions == 3


@pytest.mark.asyncio
async def test_two_query_legacy_path_still_callable_for_equivalence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm = _user()
    project = Project(
        id=uuid4(),
        org_id=dm.org_id,
        name="Alpha",
        vertical="cv",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
    )
    signals = {
        project.id: {
            "dashboard": {
                "confidence": 80.0,
                "traffic_light": "green",
                "overview": {},
            }
        }
    }

    async def _metrics(*_args, **_kwargs):
        return (
            [project],
            {project.id: (2, 1)},
            {project.id: (1, 0)},
            {project.id: 0},
            {project.id: 0},
        )

    async def _delivery(*_args, **_kwargs):
        return signals

    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_summary_project_metrics",
        _metrics,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.analytics_service._fetch_delivery_by_project",
        _delivery,
    )

    two_query = await _fetch_summary_metric_bundle_two_query(
        AsyncMock(),
        dm,
        today=date(2026, 7, 10),
    )
    assert two_query[0][0].id == project.id
    assert two_query[1][project.id] == (2, 1)
    assert two_query[5][project.id]["dashboard"]["confidence"] == 80.0


def test_empty_state_scoring_defaults() -> None:
    project = Project(
        id=uuid4(),
        org_id=uuid4(),
        name="Empty",
        vertical="cv",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
    )
    metrics = _merge_project_metrics(
        project.id,
        dependency_counts={},
        escalation_counts={},
        overdue_actions={},
        pending_scopes={},
    )
    scored = _score_project_from_metrics(project, metrics, delivery_signal=None)
    assert scored.score == 100
    assert scored.risk_level == "excellent"
    assert scored.open_dependencies == 0
    assert scored.delivery_confidence is None
    assert scored.trend == "stable"


def test_days_clamp_options_unchanged() -> None:
    from app.agents.governance.services.analytics_service import RANGE_DAY_OPTIONS, _clamp_range

    assert {7, 30, 90, 365} == RANGE_DAY_OPTIONS
    assert _clamp_range(30) == 30
    assert _clamp_range(7) == 7
    assert _clamp_range(90) == 90
    assert _clamp_range(12) == 30
