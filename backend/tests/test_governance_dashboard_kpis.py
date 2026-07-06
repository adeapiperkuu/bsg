from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.agents.governance.analytics.sla import calculate_sla_adherence_pct
from app.agents.governance.services.dashboard_service import (
    _sla_adherence_from_counts,
    compute_governance_kpis,
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


@pytest.mark.asyncio
async def test_compute_governance_kpis_internal_user_uses_three_aggregate_queries() -> None:
    dm = _user(AppRole.DELIVERY_MANAGER)
    session = AsyncMock()

    action_row = MagicMock(
        open_actions=3,
        overdue_actions=1,
        on_time_completed=8,
        total_completed=10,
    )
    inventory_row = MagicMock(blocking_dependencies=2, pending_scope=1)
    escalation_row = MagicMock(open_escalations=4, critical_escalations=2)

    session.execute = AsyncMock(
        side_effect=[
            _execute_result(action_row),
            _execute_result(inventory_row),
            _execute_result(escalation_row),
        ]
    )

    kpis = await compute_governance_kpis(session, dm)

    assert kpis.open_actions == 3
    assert kpis.overdue_actions == 1
    assert kpis.open_escalations == 4
    assert kpis.blocking_dependencies == 2
    assert kpis.at_risk_items == 5
    assert kpis.sla_adherence_pct == 80.0
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_compute_governance_kpis_client_without_projects_skips_escalation_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _user(AppRole.CLIENT)
    session = AsyncMock()
    session.execute = AsyncMock()

    async def _no_projects(_session: object, _user: CurrentUser) -> list[UUID]:
        return []

    monkeypatch.setattr(
        "app.agents.governance.services.dashboard_service._client_project_ids",
        _no_projects,
    )

    kpis = await compute_governance_kpis(session, client)

    assert kpis.open_actions == 0
    assert kpis.overdue_actions == 0
    assert kpis.open_escalations == 0
    assert kpis.blocking_dependencies == 0
    assert kpis.at_risk_items == 0
    assert kpis.sla_adherence_pct == 100.0
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_compute_governance_kpis_client_with_projects_uses_single_escalation_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _user(AppRole.CLIENT)
    project_id = uuid4()
    session = AsyncMock()
    escalation_row = MagicMock(open_escalations=2, critical_escalations=1)
    session.execute = AsyncMock(return_value=_execute_result(escalation_row))

    async def _projects(_session: object, _user: CurrentUser) -> list[UUID]:
        return [project_id]

    monkeypatch.setattr(
        "app.agents.governance.services.dashboard_service._client_project_ids",
        _projects,
    )

    kpis = await compute_governance_kpis(session, client)

    assert kpis.open_escalations == 2
    assert kpis.at_risk_items == 1
    assert kpis.sla_adherence_pct == 100.0
    assert session.execute.await_count == 1
