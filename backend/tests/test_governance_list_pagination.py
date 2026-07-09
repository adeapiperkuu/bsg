from datetime import date
from uuid import uuid4

import pytest

from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
    _bounded_list_filters,
    _dependency_enriched_page_stmt,
    list_governance_actions_page,
    list_governance_dependencies_page,
)
from app.core.security import CurrentUser
from app.db.models import AppRole
from app.schemas.common import Pagination


def test_governance_list_filters_apply_defaults() -> None:
    filters = _bounded_list_filters()

    assert filters.limit == 50
    assert filters.offset == 0
    assert filters.project_id is None
    assert filters.status is None


def test_governance_list_filters_bound_pagination() -> None:
    filters = _bounded_list_filters(limit=500, offset=-10)

    assert filters.limit == 100
    assert filters.offset == 0


def test_governance_list_filters_trim_filter_values() -> None:
    project_id = uuid4()
    filters = _bounded_list_filters(
        limit=25,
        offset=50,
        project_id=project_id,
        status=" open ",
        severity=" high ",
        dependency_type=" internal ",
        search=" escalation ",
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
    )

    assert filters.limit == 25
    assert filters.offset == 50
    assert filters.project_id == project_id
    assert filters.status == "open"
    assert filters.severity == "high"
    assert filters.dependency_type == "internal"
    assert filters.search == "escalation"
    assert filters.date_from == date(2026, 7, 1)
    assert filters.date_to == date(2026, 7, 31)


def test_paginated_governance_rows_has_more() -> None:
    page = PaginatedGovernanceRows(items=[object(), object()], total=5, limit=2, offset=2)

    assert page.has_more is True


def test_paginated_governance_rows_empty_results() -> None:
    page = PaginatedGovernanceRows(items=[], total=0, limit=50, offset=0)

    assert page.has_more is False


def test_pagination_metadata_supports_offset_totals() -> None:
    pagination = Pagination(limit=2, offset=4, total=7, items=2, has_more=True)

    assert pagination.model_dump() == {
        "limit": 2,
        "offset": 4,
        "total": 7,
        "items": 2,
        "has_more": True,
        "next_cursor": None,
    }


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_dependency_list_applies_status_project_and_search_filters(monkeypatch) -> None:
    captured = {}

    async def capture_statement(_session, user, filters, *, limit, offset):
        captured["sql"] = str(
            _dependency_enriched_page_stmt(user, filters, limit=limit, offset=offset).compile(
                compile_kwargs={"literal_binds": False}
            )
        )
        return PaginatedGovernanceRows(items=[], total=0, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        capture_statement,
    )

    await list_governance_dependencies_page(
        None,
        _user(),
        project_id=uuid4(),
        status="blocking",
        dependency_type="client_action",
        search="vendor",
    )

    sql = captured["sql"]
    assert "project_dependencies.project_id" in sql
    assert "project_dependencies.status" in sql
    assert "projects" in sql.lower()
    assert "over()" not in sql.lower()
    assert "dep_page_ids" in sql.lower()


@pytest.mark.asyncio
async def test_action_list_applies_default_pagination_and_empty_client_results() -> None:
    page = await list_governance_actions_page(None, _user(AppRole.CLIENT))

    assert page.items == []
    assert page.total == 0
    assert page.limit == 50
    assert page.offset == 0
