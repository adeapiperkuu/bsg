from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.agents.governance.services.project_sheet_service import (
    PROJECT_SHEET_SECTION_LIMIT,
    PROJECT_SHEET_SQL,
    get_governance_project_sheet,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole
from tests.conftest import override_user


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _sheet_row(project_id, *, item_count: int = 6, total: int = 8):
    now = datetime.now(UTC)
    dependencies = [
        {
            "id": str(uuid4()),
            "project_id": str(project_id),
            "title": f"Dependency {index}",
            "dependency_type": "external",
            "owner_id": None,
            "due_date": "2026-07-20",
            "status": "open",
            "overdue_days": 0,
            "project_name": "Atlas",
            "owner_name": None,
        }
        for index in range(item_count)
    ]
    return SimpleNamespace(
        id=project_id,
        name="Atlas",
        description="Bounded sheet",
        vertical="Retail",
        status="active",
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        scope_status="approved",
        scope_version="v2",
        open_dependencies=total,
        blocking_dependencies=1,
        blocking_overdue_dependencies=0,
        open_actions=0,
        overdue_actions=0,
        open_escalations=0,
        critical_escalations=0,
        scope=None,
        dependencies=dependencies,
        dependency_total=total,
        actions=[],
        action_total=0,
        escalations=[],
        escalation_total=0,
        delivery_risks=[
            {
                "id": str(uuid4()),
                "project_id": str(project_id),
                "title": "Late milestone",
                "detail": "Milestone is trending late.",
                "risk_tier": "high",
                "status": "open",
                "created_at": now.isoformat(),
            }
        ],
        risk_total=1,
    )


class _MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _Session:
    def __init__(self, row, *, existence=None):
        self.row = row
        self.existence = existence
        self.calls: list[tuple[object, dict | None]] = []

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
        if len(self.calls) == 1:
            return _MappingResult(self.row)
        return SimpleNamespace(scalar_one_or_none=lambda: self.existence)


@pytest.mark.asyncio
async def test_internal_project_sheet_is_bounded_and_uses_one_execute() -> None:
    project_id = uuid4()
    session = _Session(_sheet_row(project_id))

    result = await get_governance_project_sheet(
        session,  # type: ignore[arg-type]
        _user(),
        project_id=project_id,
    )

    assert len(session.calls) == 1
    assert session.calls[0][1]["section_limit"] == PROJECT_SHEET_SECTION_LIMIT
    assert len(result.dependencies.items) == 6
    assert result.dependencies.total == 8
    assert result.dependencies.has_more is True
    assert result.actions.items == []
    assert result.actions.has_more is False
    assert result.project.id == project_id
    assert result.permissions.can_view_internal is True
    assert result.permissions.can_view_delivery_risks is True


@pytest.mark.asyncio
async def test_client_parameters_preserve_assignment_and_publish_visibility() -> None:
    project_id = uuid4()
    row = _sheet_row(project_id, item_count=0, total=0)
    row.delivery_risks = []
    row.risk_total = 0
    session = _Session(row)

    result = await get_governance_project_sheet(
        session,  # type: ignore[arg-type]
        _user(AppRole.CLIENT),
        project_id=project_id,
    )

    params = session.calls[0][1]
    assert params["is_client"] is True
    assert params["can_view_internal"] is False
    assert params["can_view_delivery_risks"] is False
    assert result.dependencies.items == []
    assert result.actions.items == []
    assert result.scope is None
    assert result.permissions.can_write is False
    sql = PROJECT_SHEET_SQL.text.lower()
    assert "project_assignments" in sql
    assert "client_visible is true" in sql
    assert "then e.client_summary else e.description" in sql
    assert "then null else e.source_id" in sql


@pytest.mark.asyncio
async def test_super_admin_with_no_org_uses_cross_org_authorization_branch() -> None:
    project_id = uuid4()
    session = _Session(_sheet_row(project_id, item_count=0, total=0))
    user = CurrentUser(
        id=uuid4(),
        org_id=None,
        email="super-admin@example.com",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )

    result = await get_governance_project_sheet(
        session,  # type: ignore[arg-type]
        user,
        project_id=project_id,
    )

    assert result.project.id == project_id
    assert session.calls[0][1]["is_super_admin"] is True
    assert session.calls[0][1]["org_id"] is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_unauthorized_project_uses_only_the_failure_existence_check() -> None:
    project_id = uuid4()
    session = _Session(None, existence=project_id)

    with pytest.raises(ApiError) as exc_info:
        await get_governance_project_sheet(
            session,  # type: ignore[arg-type]
            _user(AppRole.CLIENT),
            project_id=project_id,
        )

    assert exc_info.value.status_code == 403
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_missing_project_returns_not_found_in_two_executes() -> None:
    project_id = uuid4()
    session = _Session(None, existence=None)

    with pytest.raises(ApiError) as exc_info:
        await get_governance_project_sheet(
            session,  # type: ignore[arg-type]
            _user(),
            project_id=project_id,
        )

    assert exc_info.value.status_code == 404
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_http_endpoint_returns_the_explicit_composite_contract(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    result = await get_governance_project_sheet(
        _Session(_sheet_row(project_id, item_count=1, total=1)),  # type: ignore[arg-type]
        delivery_manager,
        project_id=project_id,
    )
    monkeypatch.setattr(
        "app.agents.governance.routes.governance.get_governance_project_sheet",
        AsyncMock(return_value=result),
    )
    override_user(delivery_manager)

    response = await api_client.get(f"/api/v1/governance/project-sheet/{project_id}")

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["project"]["id"] == str(project_id)
    assert body["dependencies"]["total"] == 1
    assert body["dependencies"]["has_more"] is False
    assert body["actions"] == {"items": [], "total": 0, "has_more": False}
    assert body["permissions"]["can_view_internal"] is True
