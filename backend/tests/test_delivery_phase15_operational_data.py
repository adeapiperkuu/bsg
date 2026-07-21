"""Phase 15.2 operational data sources — validation, severity, RBAC."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.agents.delivery.analytics.operational_signals import (
    absenteeism_severity,
    backlog_queue_severity,
    capacity_shortage_severity,
    combine_max,
    review_queue_severity,
    team_availability_severity,
    timesheet_underfill_severity,
)
from app.agents.delivery.analytics.root_cause import build_factor_signals
from app.agents.delivery.schemas.operational_data import (
    AbsenteeismSnapshotCreate,
    BacklogQueueSnapshotCreate,
    ReviewQueueSnapshotCreate,
)
from app.agents.delivery.services.operational_signals import DbOperationalSignalProvider
from app.core.security import CurrentUser
from app.db.models import AppRole
from tests.conftest import client_a, delivery_manager, override_user

PROJECT_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_timesheet_underfill_severity() -> None:
    assert timesheet_underfill_severity(
        hours_logged=Decimal("40"), expected_hours=Decimal("40")
    ) == Decimal("0.00")
    assert timesheet_underfill_severity(
        hours_logged=Decimal("20"), expected_hours=Decimal("40")
    ) == Decimal("50.00")
    assert timesheet_underfill_severity(hours_logged=Decimal("10"), expected_hours=None) is None


def test_absenteeism_and_review_severity() -> None:
    assert absenteeism_severity(absence_rate_pct=Decimal("10")) == Decimal("20.00")
    sev = review_queue_severity(
        pending_count=5,
        avg_turnaround_hours=Decimal("48"),
        sla_breach_count=2,
    )
    assert sev > Decimal("0")


def test_backlog_and_capacity_severity() -> None:
    assert backlog_queue_severity(item_count=20, aging_item_count=5, oldest_item_age_days=10) > 0
    assert capacity_shortage_severity(
        planned_capacity_hours=Decimal("100"),
        available_capacity_hours=Decimal("70"),
    ) == Decimal("30.00")
    assert team_availability_severity(available_headcount=8, planned_headcount=10) == Decimal(
        "20.00"
    )


def test_combine_max() -> None:
    assert combine_max(None, None) is None
    assert combine_max(Decimal("10"), Decimal("25"), None) == Decimal("25.00")


def test_operational_overrides_win_in_root_cause() -> None:
    signals = build_factor_signals(
        bottlenecks=[],
        rework_rate_pct=None,
        headcount_decline_pct=None,
        throughput_decline_pct=Decimal("0"),
        throughput_shortfall_pct=None,
        days_until_milestone=None,
        overdue_milestone_count=0,
        has_quality_drift=False,
        warning_window_days=14,
        review_turnaround_signal=Decimal("40"),
        queue_signal=Decimal("35"),
        capacity_signal=Decimal("50"),
        absenteeism_signal=Decimal("22"),
    )
    by_factor = {item.factor: item for item in signals}
    assert by_factor["review_turnaround"].data_available is True
    assert by_factor["review_turnaround"].severity_signal == Decimal("40.00")
    assert by_factor["queue"].severity_signal == Decimal("35.00")
    assert by_factor["capacity"].severity_signal == Decimal("50.00")
    assert by_factor["absenteeism"].severity_signal == Decimal("22.00")


def test_schema_rejects_invalid_absenteeism() -> None:
    with pytest.raises(ValidationError):
        AbsenteeismSnapshotCreate(
            snapshot_date="2026-07-20",
            absent_fte=Decimal("5"),
            planned_fte=Decimal("3"),
        )


def test_schema_rejects_aging_gt_items() -> None:
    with pytest.raises(ValidationError):
        BacklogQueueSnapshotCreate(
            snapshot_date="2026-07-20",
            item_count=2,
            aging_item_count=5,
        )


def test_schema_rejects_sla_gt_pending() -> None:
    with pytest.raises(ValidationError):
        ReviewQueueSnapshotCreate(
            snapshot_date="2026-07-20",
            pending_count=1,
            avg_turnaround_hours=Decimal("8"),
            sla_breach_count=3,
        )


@pytest.fixture
def bsg_leadership() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="leadership@example.com",
        role=AppRole.BSG_LEADERSHIP,
        is_active=True,
    )


OPS_GET_PATHS = (
    f"/api/v1/delivery/projects/{PROJECT_ID}/timesheets",
    f"/api/v1/delivery/projects/{PROJECT_ID}/absenteeism",
    f"/api/v1/delivery/projects/{PROJECT_ID}/review-queue",
    f"/api/v1/delivery/projects/{PROJECT_ID}/backlog-queue",
    f"/api/v1/delivery/projects/{PROJECT_ID}/capacity",
    f"/api/v1/delivery/projects/{PROJECT_ID}/team-availability",
)


@pytest.mark.parametrize("path", OPS_GET_PATHS)
@pytest.mark.asyncio
async def test_operational_reads_client_forbidden(
    api_client: AsyncClient, client_a, path: str
) -> None:
    override_user(client_a)
    response = await api_client.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", OPS_GET_PATHS)
@pytest.mark.asyncio
async def test_operational_reads_dm_not_role_blocked(
    api_client: AsyncClient, delivery_manager, path: str
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_operational_write_client_forbidden(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/delivery/projects/{PROJECT_ID}/absenteeism",
        headers={"Authorization": "Bearer test-token"},
        json={
            "snapshot_date": "2026-07-20",
            "absent_fte": 1,
            "planned_fte": 10,
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_operational_write_dm_not_role_blocked(
    api_client: AsyncClient, delivery_manager
) -> None:
    override_user(delivery_manager)
    response = await api_client.post(
        f"/api/v1/delivery/projects/{PROJECT_ID}/capacity",
        headers={"Authorization": "Bearer test-token"},
        json={
            "snapshot_date": "2026-07-20",
            "planned_capacity_hours": 80,
            "available_capacity_hours": 60,
        },
    )
    assert response.status_code != 403


def test_default_provider_is_db_backed() -> None:
    from app.agents.delivery.services.operational_signals import (
        DEFAULT_OPERATIONAL_SIGNAL_PROVIDER,
    )

    assert isinstance(DEFAULT_OPERATIONAL_SIGNAL_PROVIDER, DbOperationalSignalProvider)
