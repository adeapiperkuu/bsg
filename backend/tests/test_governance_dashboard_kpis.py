from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.analytics.sla import calculate_sla_adherence_pct
from app.agents.governance.schemas.governance import GovernanceBootstrapRead, GovernanceKpisRead
from app.agents.governance.services.dashboard_service import (
    _action_kpi_subquery,
    _bootstrap_kpi_cache,
    _escalation_kpi_subquery,
    _fetch_bootstrap_kpis_bundle,
    _sla_adherence_from_counts,
    compute_governance_kpis,
    get_governance_bootstrap,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceAction, GovernanceActionStatus


def _user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _execute_result(row: object) -> MagicMock:
    result = MagicMock()
    result.one.return_value = row
    return result


def test_sla_adherence_from_counts_matches_reference_helper() -> None:
    org = uuid4()
    project = uuid4()
    actions = [
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="On time",
            due_date=date(2026, 6, 20),
            status=GovernanceActionStatus.COMPLETED,
            completed_at=datetime(2026, 6, 18, tzinfo=UTC),
        ),
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="Late",
            due_date=date(2026, 6, 10),
            status=GovernanceActionStatus.COMPLETED,
            completed_at=datetime(2026, 6, 15, tzinfo=UTC),
        ),
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="No due date",
            status=GovernanceActionStatus.COMPLETED,
            completed_at=datetime(2026, 6, 12, tzinfo=UTC),
        ),
    ]

    recent_total = 3
    on_time = 2
    assert _sla_adherence_from_counts(on_time, recent_total) == calculate_sla_adherence_pct(
        actions,
        today=date(2026, 6, 25),
    )
    assert _sla_adherence_from_counts(0, 0) == 100.0


def test_bootstrap_kpi_subqueries_use_filter_aggregation() -> None:
    today = date(2026, 7, 7)
    window_start = today
    user = _user(AppRole.DELIVERY_MANAGER)

    action_sql = str(
        _action_kpi_subquery(user, today=today, window_start=window_start).compile(
            compile_kwargs={"literal_binds": False}
        )
    ).lower()
    escalation_sql = str(
        _escalation_kpi_subquery(user).compile(compile_kwargs={"literal_binds": False})
    ).lower()

    assert "count(" in action_sql
    assert "filter" in action_sql
    assert "governance_actions" in action_sql
    assert "governance_escalations" in escalation_sql
    assert "filter" in escalation_sql


@pytest.mark.asyncio
async def test_compute_governance_kpis_internal_user_uses_single_aggregate_query() -> None:
    dm = _user(AppRole.DELIVERY_MANAGER)
    session = AsyncMock()
    row = MagicMock(
        open_actions=3,
        overdue_actions=1,
        on_time_completed=8,
        total_completed=10,
        blocking_dependencies=2,
        pending_scope=1,
        open_escalations=4,
        critical_escalations=2,
    )
    session.execute = AsyncMock(return_value=_execute_result(row))

    kpis = await compute_governance_kpis(session, dm)

    assert kpis.open_actions == 3
    assert kpis.overdue_actions == 1
    assert kpis.open_escalations == 4
    assert kpis.blocking_dependencies == 2
    assert kpis.at_risk_items == 5
    assert kpis.sla_adherence_pct == 80.0
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_compute_governance_kpis_client_without_projects_returns_zeros() -> None:
    client = _user(AppRole.CLIENT)
    session = AsyncMock()
    escalation_row = MagicMock(open_escalations=0, critical_escalations=0)
    session.execute = AsyncMock(return_value=_execute_result(escalation_row))

    kpis = await compute_governance_kpis(session, client)

    assert kpis.open_actions == 0
    assert kpis.overdue_actions == 0
    assert kpis.open_escalations == 0
    assert kpis.blocking_dependencies == 0
    assert kpis.at_risk_items == 0
    assert kpis.sla_adherence_pct == 100.0
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_compute_governance_kpis_client_with_projects_uses_single_escalation_query() -> None:
    client = _user(AppRole.CLIENT)
    session = AsyncMock()
    escalation_row = MagicMock(open_escalations=2, critical_escalations=1)
    session.execute = AsyncMock(return_value=_execute_result(escalation_row))

    kpis = await compute_governance_kpis(session, client)

    assert kpis.open_escalations == 2
    assert kpis.at_risk_items == 1
    assert kpis.sla_adherence_pct == 100.0
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_get_governance_bootstrap_returns_cached_kpis_without_second_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bootstrap_kpi_cache.clear()
    dm = _user(AppRole.DELIVERY_MANAGER)
    session = AsyncMock()
    bundle_mock = AsyncMock(
        return_value=GovernanceKpisRead(
            open_actions=1,
            overdue_actions=0,
            open_escalations=2,
            blocking_dependencies=0,
            at_risk_items=0,
            sla_adherence_pct=100.0,
        )
    )

    monkeypatch.setattr(
        "app.agents.governance.services.dashboard_service.compute_governance_kpis",
        bundle_mock,
    )

    first = await get_governance_bootstrap(session, dm)
    second = await get_governance_bootstrap(session, dm)

    assert isinstance(first, GovernanceBootstrapRead)
    assert first.kpis is second.kpis
    bundle_mock.assert_awaited_once()
    _bootstrap_kpi_cache.clear()


@pytest.mark.asyncio
async def test_fetch_bootstrap_kpis_bundle_leadership_user_uses_internal_counts() -> None:
    leadership = _user(AppRole.BSG_LEADERSHIP)
    session = AsyncMock()
    row = MagicMock(
        open_actions=1,
        overdue_actions=0,
        on_time_completed=5,
        total_completed=5,
        blocking_dependencies=1,
        pending_scope=0,
        open_escalations=2,
        critical_escalations=0,
    )
    session.execute = AsyncMock(return_value=_execute_result(row))

    kpis = await _fetch_bootstrap_kpis_bundle(
        session,
        leadership,
        today=date(2026, 7, 7),
        window_start=date(2026, 4, 7),
    )

    assert kpis.open_actions == 1
    assert kpis.blocking_dependencies == 1
    session.execute.assert_awaited_once()
