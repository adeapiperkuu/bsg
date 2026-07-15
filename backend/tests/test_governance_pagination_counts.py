from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.services.governance_service import (
    PAGINATION_TOTAL_LABEL,
    PaginatedGovernanceRows,
    _apply_dependency_page_filters,
    _bounded_list_filters,
    _dependency_count_stmt,
    _dependency_enriched_page_stmt,
    _dependency_list_stmt,
    _execute_dependency_paginated_page,
    _execute_paginated_rows,
    _invalidate_dependencies_list_cache,
    _is_default_dependencies_cacheable,
    list_governance_dependencies_page,
    map_dependency_list_row,
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
async def test_execute_paginated_rows_uses_window_count_in_single_execute() -> None:
    row = MagicMock(project_id=uuid4(), title="Alpha")
    setattr(row, PAGINATION_TOTAL_LABEL, 7)
    rows_result = MagicMock()
    rows_result.all.return_value = [row]
    session = AsyncMock()
    captured: dict[str, str] = {}

    async def _capture_execute(stmt, *_args, **_kwargs):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        return rows_result

    session.execute.side_effect = _capture_execute

    page = await _execute_paginated_rows(
        session,
        _dependency_list_stmt(_user()),
        limit=2,
        offset=0,
        count_stmt=_dependency_count_stmt(_user()),
    )

    assert page.total == 7
    assert page.items == [row]
    assert page.db_executes == 1
    assert session.execute.await_count == 1
    assert "count(*) over" in captured["sql"].lower()
    assert PAGINATION_TOTAL_LABEL in captured["sql"]


@pytest.mark.asyncio
async def test_execute_paginated_rows_falls_back_to_count_for_empty_offset_page() -> None:
    rows_result = MagicMock()
    rows_result.all.return_value = []
    count_result = MagicMock()
    count_result.scalar_one.return_value = 12
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[rows_result, count_result])

    page = await _execute_paginated_rows(
        session,
        _dependency_list_stmt(_user()),
        limit=25,
        offset=50,
        count_stmt=_dependency_count_stmt(_user()),
    )

    assert page.items == []
    assert page.total == 12
    assert page.db_executes == 2
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_execute_paginated_rows_returns_zero_total_for_empty_first_page() -> None:
    rows_result = MagicMock()
    rows_result.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=rows_result)

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
    assert page.db_executes == 1
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_dependency_count_query_preserves_filters(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def capture_statement(_session, _user, filters, *, limit, offset):
        captured["page_sql"] = str(
            _dependency_enriched_page_stmt(_user, filters, limit=limit, offset=offset).compile(
                compile_kwargs={"literal_binds": False}
            )
        )
        return PaginatedGovernanceRows(items=[], total=3, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
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

    page_sql = captured["page_sql"]
    assert "project_dependencies.project_id" in page_sql
    assert "project_dependencies.status" in page_sql
    assert "project_dependencies.title" in page_sql.lower() or "ilike" in page_sql.lower()
    assert page.total == 3
    assert page.limit == 10
    assert page.offset == 5


@pytest.mark.asyncio
async def test_execute_dependency_paginated_page_uses_scalar_count_not_window() -> None:
    row = MagicMock(project_id=uuid4(), title="Alpha")
    setattr(row, PAGINATION_TOTAL_LABEL, 7)
    rows_result = MagicMock()
    rows_result.all.return_value = [row]
    session = AsyncMock()
    captured: dict[str, str] = {}

    async def _capture_execute(stmt, *_args, **_kwargs):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        return rows_result

    session.execute.side_effect = _capture_execute

    page = await _execute_dependency_paginated_page(
        session,
        _user(),
        _bounded_list_filters(limit=2, offset=0),
        limit=2,
        offset=0,
    )

    assert page.total == 7
    assert page.items == [row]
    assert page.db_executes == 1
    assert session.execute.await_count == 1
    sql = captured["sql"].lower()
    assert "dep_page_ids" in sql
    assert "over()" not in sql


def test_dependency_enriched_page_stmt_limits_before_joins() -> None:
    sql = str(
        _dependency_enriched_page_stmt(
            _user(),
            _bounded_list_filters(limit=25, offset=0),
            limit=25,
            offset=0,
        ).compile(compile_kwargs={"literal_binds": False})
    ).lower()

    assert "dep_page_ids" in sql
    assert "limit" in sql
    assert "over()" not in sql
    assert sql.index("dep_page_ids") < sql.index("join projects")


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


def test_dependency_list_selects_only_table_columns() -> None:
    sql = str(_dependency_list_stmt(_user()).compile(compile_kwargs={"literal_binds": False}))

    assert "project_dependencies.id" in sql
    assert "project_dependencies.title" in sql
    assert "project_dependencies.description" not in sql.lower()
    assert "projects.name" in sql.lower()


def test_map_dependency_list_row_response_shape() -> None:
    row = MagicMock(
        id=uuid4(),
        project_id=uuid4(),
        title="Vendor sign-off",
        dependency_type="client_action",
        owner_id=uuid4(),
        due_date=None,
        status="open",
        project_name="Alpha",
        owner_name="Alex Owner",
    )

    payload = map_dependency_list_row(row)

    assert payload.model_dump() == {
        "id": row.id,
        "project_id": row.project_id,
        "title": "Vendor sign-off",
        "dependency_type": "client_action",
        "owner_id": row.owner_id,
        "due_date": None,
        "status": "open",
        "overdue_days": 0,
        "project_name": "Alpha",
        "owner_name": "Alex Owner",
    }


def test_default_dependencies_request_is_cacheable() -> None:
    """First-paint limit=6 and legacy limit=50 are both cacheable when unfiltered."""
    filters = _bounded_list_filters(limit=50, offset=0)
    assert _is_default_dependencies_cacheable(filters) is True

    filtered = _bounded_list_filters(limit=50, offset=0, search="vendor")
    assert _is_default_dependencies_cacheable(filtered) is False

    assert _is_default_dependencies_cacheable(_bounded_list_filters(limit=25, offset=0)) is False
    assert _is_default_dependencies_cacheable(_bounded_list_filters(limit=50, offset=50)) is False
    # Production dashboard first page (TABLE_PAGE_SIZE=6) is cacheable after Phase 1.
    assert _is_default_dependencies_cacheable(_bounded_list_filters(limit=6, offset=0)) is True


@pytest.mark.asyncio
async def test_list_governance_dependencies_page_uses_cache_for_legacy_limit_50(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    user = _user()
    cached_page = PaginatedGovernanceRows(
        items=[MagicMock()],
        total=1,
        limit=50,
        offset=0,
        db_executes=1,
    )
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return cached_page

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    first = await list_governance_dependencies_page(session, user, limit=50, offset=0)
    second = await list_governance_dependencies_page(session, user, limit=50, offset=0)

    assert calls == 1
    assert first.total == second.total
    assert first.db_executes == 1
    assert second.db_executes == 0
    _invalidate_dependencies_list_cache()


@pytest.mark.asyncio
async def test_list_governance_dependencies_page_uses_cache_for_dashboard_limit_6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Frontend first-page shape (limit=6) hits the in-process cache on repeat."""
    _invalidate_dependencies_list_cache()
    user = _user()
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows(items=[], total=0, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    first = await list_governance_dependencies_page(session, user, limit=6, offset=0)
    second = await list_governance_dependencies_page(session, user, limit=6, offset=0)

    assert calls == 1
    assert first.db_executes == 1
    assert second.db_executes == 0
    _invalidate_dependencies_list_cache()


@pytest.mark.asyncio
async def test_list_governance_dependencies_page_skips_cache_for_non_default_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows(items=[], total=0, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    await list_governance_dependencies_page(session, _user(), limit=25, offset=0)
    await list_governance_dependencies_page(session, _user(), limit=25, offset=0)

    assert calls == 2
    _invalidate_dependencies_list_cache()
