from datetime import date, datetime, UTC
from uuid import uuid4

import pytest

from app.agents.governance.analytics.sla import (
    calculate_sla_adherence_pct,
    count_blocking_dependencies,
    count_open_actions,
    count_overdue_actions,
    dependency_overdue_days,
    effective_action_status,
)
from app.agents.governance.services.governance_service import (
    assert_can_read_governance,
    assert_can_write_governance,
    can_read_internal_governance,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceDependencyType,
    ProjectDependency,
)


def _user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def test_delivery_manager_can_read_and_write() -> None:
    dm = _user(AppRole.DELIVERY_MANAGER)
    assert_can_read_governance(dm)
    assert_can_write_governance(dm)
    assert can_read_internal_governance(dm)


def test_leadership_read_only() -> None:
    lead = _user(AppRole.BSG_LEADERSHIP)
    assert_can_read_governance(lead)
    with pytest.raises(ApiError) as exc:
        assert_can_write_governance(lead)
    assert exc.value.status_code == 403


def test_client_cannot_read_internal_governance() -> None:
    client = _user(AppRole.CLIENT)
    assert_can_read_governance(client)
    assert not can_read_internal_governance(client)
    with pytest.raises(ApiError):
        assert_can_write_governance(client)


def test_effective_action_status_overdue() -> None:
    action = GovernanceAction(
        id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        title="Late item",
        due_date=date(2026, 6, 1),
        status=GovernanceActionStatus.OPEN,
    )
    assert effective_action_status(action, today=date(2026, 6, 10)) == GovernanceActionStatus.OVERDUE


def test_sla_adherence_all_on_time() -> None:
    org = uuid4()
    project = uuid4()
    actions = [
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="Done",
            due_date=date(2026, 6, 20),
            status=GovernanceActionStatus.COMPLETED,
            completed_at=datetime(2026, 6, 18, tzinfo=UTC),
        )
    ]
    assert calculate_sla_adherence_pct(actions, today=date(2026, 6, 25)) == 100.0


def test_blocking_dependency_count() -> None:
    deps = [
        ProjectDependency(
            id=uuid4(),
            org_id=uuid4(),
            project_id=uuid4(),
            title="A",
            dependency_type=GovernanceDependencyType.CLIENT_ACTION,
            status=GovernanceDependencyStatus.BLOCKING,
        ),
        ProjectDependency(
            id=uuid4(),
            org_id=uuid4(),
            project_id=uuid4(),
            title="B",
            dependency_type=GovernanceDependencyType.INTERNAL,
            status=GovernanceDependencyStatus.RESOLVED,
        ),
    ]
    assert count_blocking_dependencies(deps) == 1


def test_dependency_overdue_days() -> None:
    dep = ProjectDependency(
        id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        title="Late",
        dependency_type="client_action",
        due_date=date(2026, 6, 1),
        status=GovernanceDependencyStatus.BLOCKING,
    )
    assert dependency_overdue_days(dep, today=date(2026, 6, 5)) == 4


def test_open_and_overdue_action_counts() -> None:
    org = uuid4()
    project = uuid4()
    actions = [
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="Open",
            status=GovernanceActionStatus.OPEN,
        ),
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="Late",
            due_date=date(2026, 6, 1),
            status=GovernanceActionStatus.OPEN,
        ),
        GovernanceAction(
            id=uuid4(),
            org_id=org,
            project_id=project,
            title="Done",
            status=GovernanceActionStatus.COMPLETED,
        ),
    ]
    today = date(2026, 6, 10)
    assert count_open_actions(actions, today=today) == 2
    assert count_overdue_actions(actions, today=today) == 1
