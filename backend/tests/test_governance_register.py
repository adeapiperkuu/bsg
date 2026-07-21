from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.services.register_service import (
    _compute_register_health,
    list_governance_register_page,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceScopeStatus


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def test_compute_register_health_marks_critical_escalations_red() -> None:
    assert (
        _compute_register_health(
            scope_status=None,
            critical_escalations=1,
            blocking_overdue_dependencies=0,
            open_escalations=1,
            overdue_actions=0,
        )
        == "red"
    )


def test_compute_register_health_marks_pending_scope_amber() -> None:
    assert (
        _compute_register_health(
            scope_status=GovernanceScopeStatus.PENDING_REVISION,
            critical_escalations=0,
            blocking_overdue_dependencies=0,
            open_escalations=0,
            overdue_actions=0,
        )
        == "amber"
    )


@pytest.mark.asyncio
async def test_register_page_maps_rows_from_paginated_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    project_id = uuid4()
    row = MagicMock(
        project_id=project_id,
        project_name="Alpha",
        scope_status=None,
        scope_version=None,
        open_dependencies=1,
        blocking_dependencies=0,
        blocking_overdue_dependencies=0,
        open_actions=0,
        overdue_actions=0,
        open_escalations=0,
        critical_escalations=0,
    )

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        return MagicMock(items=[row], total=1, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        _paginate,
    )
    page = await list_governance_register_page(session, _user())

    assert page.total == 1
    assert page.items[0].project_name == "Alpha"
    assert page.items[0].health == "green"


@pytest.mark.asyncio
async def test_register_client_empty_state_uses_scoped_projects_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def _paginate(_session, stmt, *, limit, offset, count_stmt):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        return MagicMock(items=[], total=0, limit=limit, offset=offset, db_executes=1)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        _paginate,
    )
    page = await list_governance_register_page(AsyncMock(), _user(AppRole.CLIENT))

    assert page.total == 0
    assert page.items == []
    assert "project_assignments" in captured["sql"].lower()


@pytest.mark.asyncio
async def test_register_super_admin_uses_only_the_page_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        AsyncMock(return_value=MagicMock(items=[], total=0, limit=50, offset=0, db_executes=1)),
    )

    super_admin = CurrentUser(
        id=uuid4(),
        org_id=None,
        email="admin@example.com",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )
    page = await list_governance_register_page(AsyncMock(), super_admin)

    assert page.db_executes == 1
