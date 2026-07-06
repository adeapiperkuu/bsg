from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
    _apply_dependency_page_filters,
    _bounded_list_filters,
    _dependency_count_stmt,
    _dependency_list_stmt,
    _execute_paginated_rows,
    list_governance_dependencies_page,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, ProjectDependency


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_execute_paginated_rows_uses_separate_count_query() -> None:
    session = AsyncMock()
    row = MagicMock(project_id=uuid4(), title="Alpha")
    count_result = MagicMock()
    count_result.scalar_one.return_value = 7
    rows_result = MagicMock()
    rows_result.all.return_value = [row]

    captured = {}

    async def execute(stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        if "count(" in sql.lower() and "over" not in sql.lower() and "limit" not in sql.lower():
            captured["count_sql"] = sql
            return count_result
        captured["rows_sql"] = sql
        return rows_result

    session.execute = AsyncMock(side_effect=execute)

    stmt = _dependency_list_stmt(_user())
    count_stmt = _dependency_count_stmt(_user())
    page = await _execute_paginated_rows(
        session,
        stmt,
        limit=2,
        offset=4,
        count_stmt=count_stmt,
    )

    assert page.total == 7
    assert page.items == [row]
    assert page.limit == 2
    assert page.offset == 4
    assert "limit" in captured["rows_sql"].lower()
    assert "offset" in captured["rows_sql"].lower()
    assert "over()" not in captured["rows_sql"].lower()
    assert "users" not in captured["count_sql"].lower()


@pytest.mark.asyncio
async def test_execute_paginated_rows_returns_zero_total_for_empty_page() -> None:
    session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    rows_result = MagicMock()
    rows_result.all.return_value = []

    session.execute = AsyncMock(side_effect=[count_result, rows_result])

    page = await _execute_paginated_rows(
        session,
        _dependency_list_stmt(_user()),
        limit=25,
        offset=0,
        count_stmt=_dependency_count_stmt(_user()),
    )

    assert page.items == []
    assert page.total == 0
    assert page.has_more is False


@pytest.mark.asyncio
async def test_dependency_count_query_preserves_filters(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def capture_statement(_session, stmt, *, limit, offset, count_stmt):
        captured["count_sql"] = str(count_stmt.compile(compile_kwargs={"literal_binds": False}))
        return PaginatedGovernanceRows(items=[], total=3, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_paginated_rows",
        capture_statement,
    )

    project_id = uuid4()
    page = await list_governance_dependencies_page(
        None,
        _user(),
        project_id=project_id,
        status="blocking",
        search="vendor",
        limit=10,
        offset=5,
    )

    count_sql = captured["count_sql"]
    assert "project_dependencies.project_id" in count_sql
    assert "project_dependencies.status" in count_sql
    assert "project_dependencies.title" in count_sql.lower() or "ilike" in count_sql.lower()
    assert page.total == 3
    assert page.limit == 10
    assert page.offset == 5


def test_dependency_page_filters_apply_to_count_and_list_statements() -> None:
    user = _user()
    filters = _bounded_list_filters(project_id=uuid4(), status="open", search="vendor")
    list_sql = str(
        _apply_dependency_page_filters(_dependency_list_stmt(user), filters).compile(
            compile_kwargs={"literal_binds": False}
        )
    )
    count_sql = str(
        _apply_dependency_page_filters(_dependency_count_stmt(user), filters).compile(
            compile_kwargs={"literal_binds": False}
        )
    )

    for sql in (list_sql, count_sql):
        assert "project_dependencies.project_id" in sql
        assert "project_dependencies.status" in sql

    assert "order by" not in count_sql.lower()
    assert "users" not in count_sql.lower()
    assert "projects" not in count_sql.lower()


def test_dependency_list_sorting_is_stable() -> None:
    sql = str(
        _dependency_list_stmt(_user())
        .order_by(
            ProjectDependency.due_date.asc().nulls_last(),
            ProjectDependency.created_at.desc(),
        )
        .compile(compile_kwargs={"literal_binds": False})
    )

    assert "project_dependencies.due_date" in sql
    assert "project_dependencies.created_at" in sql
    assert sql.index("due_date") < sql.index("created_at")
