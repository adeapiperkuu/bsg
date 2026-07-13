"""Phase 1: first-page cache eligibility for limit=6 dependencies and register."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.constants import (
    GOVERNANCE_FIRST_PAINT_LIMIT,
    LEGACY_DEPENDENCIES_CACHE_LIMIT,
    REGISTER_CACHEABLE_LIMITS,
)
from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
    _bounded_list_filters,
    _invalidate_dependencies_list_cache,
    _is_default_dependencies_cacheable,
    invalidate_governance_read_caches_after_commit,
    list_governance_dependencies_page,
)
from app.agents.governance.services.register_service import (
    _is_default_register_cacheable,
    _register_list_cache,
    invalidate_register_list_cache,
    list_governance_register_page,
)
from app.core.security import CurrentUser
from app.db.models import AppRole


def _user(
    role: AppRole = AppRole.DELIVERY_MANAGER,
    *,
    org_id=None,
    user_id=None,
) -> CurrentUser:
    return CurrentUser(
        id=user_id or uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def test_first_paint_limit_constant_matches_frontend() -> None:
    assert GOVERNANCE_FIRST_PAINT_LIMIT == 6
    assert LEGACY_DEPENDENCIES_CACHE_LIMIT == 50
    assert 6 in REGISTER_CACHEABLE_LIMITS
    assert 25 in REGISTER_CACHEABLE_LIMITS
    assert 50 in REGISTER_CACHEABLE_LIMITS


def test_dependencies_limit_6_and_legacy_50_are_cacheable() -> None:
    assert _is_default_dependencies_cacheable(_bounded_list_filters(limit=6, offset=0)) is True
    assert _is_default_dependencies_cacheable(_bounded_list_filters(limit=50, offset=0)) is True


def test_dependencies_filtered_and_offset_are_not_cacheable() -> None:
    assert (
        _is_default_dependencies_cacheable(
            _bounded_list_filters(limit=6, offset=0, search="vendor")
        )
        is False
    )
    assert (
        _is_default_dependencies_cacheable(_bounded_list_filters(limit=6, offset=6)) is False
    )
    assert (
        _is_default_dependencies_cacheable(_bounded_list_filters(limit=25, offset=0)) is False
    )
    assert (
        _is_default_dependencies_cacheable(
            _bounded_list_filters(limit=6, offset=0, status="open")
        )
        is False
    )


@pytest.mark.asyncio
async def test_dependencies_limit_6_second_request_is_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    user = _user()
    page = PaginatedGovernanceRows(
        items=[MagicMock()],
        total=1,
        limit=6,
        offset=0,
        db_executes=1,
    )
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return page

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
    assert first.total == second.total
    assert first.limit == second.limit == 6
    _invalidate_dependencies_list_cache()


@pytest.mark.asyncio
async def test_dependencies_limit_6_does_not_reuse_limit_50_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    user = _user()
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows(
            items=[MagicMock()],
            total=1,
            limit=limit,
            offset=offset,
            db_executes=1,
        )

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    await list_governance_dependencies_page(session, user, limit=50, offset=0)
    await list_governance_dependencies_page(session, user, limit=6, offset=0)
    assert calls == 2
    _invalidate_dependencies_list_cache()


@pytest.mark.asyncio
async def test_dependencies_cache_isolates_orgs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    org_a = uuid4()
    org_b = uuid4()
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows(
            items=[MagicMock(org=_user.org_id)],
            total=1,
            limit=limit,
            offset=offset,
            db_executes=1,
        )

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    await list_governance_dependencies_page(session, _user(org_id=org_a), limit=6, offset=0)
    await list_governance_dependencies_page(session, _user(org_id=org_b), limit=6, offset=0)
    assert calls == 2
    _invalidate_dependencies_list_cache()


@pytest.mark.asyncio
async def test_dependencies_cache_isolates_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    org_id = uuid4()
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows(
            items=[],
            total=0,
            limit=limit,
            offset=offset,
            db_executes=1,
        )

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    await list_governance_dependencies_page(
        session, _user(org_id=org_id, user_id=uuid4()), limit=6, offset=0
    )
    await list_governance_dependencies_page(
        session, _user(org_id=org_id, user_id=uuid4()), limit=6, offset=0
    )
    assert calls == 2
    _invalidate_dependencies_list_cache()


@pytest.mark.asyncio
async def test_dependencies_write_invalidation_clears_limit_6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _invalidate_dependencies_list_cache()
    user = _user()
    calls = 0

    async def _fake_execute(_session, _user, _filters, *, limit, offset):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows(
            items=[],
            total=0,
            limit=limit,
            offset=offset,
            db_executes=1,
        )

    monkeypatch.setattr(
        "app.agents.governance.services.governance_service._execute_dependency_paginated_page",
        _fake_execute,
    )

    session = AsyncMock()
    await list_governance_dependencies_page(session, user, limit=6, offset=0)
    invalidate_governance_read_caches_after_commit()
    await list_governance_dependencies_page(session, user, limit=6, offset=0)
    assert calls == 2
    _invalidate_dependencies_list_cache()


def test_register_limit_6_is_cacheable() -> None:
    assert (
        _is_default_register_cacheable(
            limit=6, offset=0, project_id=None, status=None, search=None
        )
        is True
    )
    assert (
        _is_default_register_cacheable(
            limit=25, offset=0, project_id=None, status=None, search=None
        )
        is True
    )
    assert (
        _is_default_register_cacheable(
            limit=50, offset=0, project_id=None, status=None, search=None
        )
        is True
    )
    assert (
        _is_default_register_cacheable(
            limit=6, offset=0, project_id=uuid4(), status=None, search=None
        )
        is False
    )
    assert (
        _is_default_register_cacheable(
            limit=6, offset=6, project_id=None, status=None, search=None
        )
        is False
    )


@pytest.mark.asyncio
async def test_register_limit_6_second_request_is_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalidate_register_list_cache()
    user = _user()
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
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return MagicMock(items=[row], total=1, limit=limit, offset=offset, db_executes=1)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        _paginate,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.register_service.ensure_org_time_sensitive_summary_counts",
        AsyncMock(return_value=0),
    )

    session = AsyncMock()
    first = await list_governance_register_page(session, user, limit=6, offset=0)
    second = await list_governance_register_page(session, user, limit=6, offset=0)

    assert calls == 1
    assert first.db_executes == 1
    assert second.db_executes == 0
    assert first.total == second.total == 1
    assert first.limit == 6
    invalidate_register_list_cache()


@pytest.mark.asyncio
async def test_register_cache_isolates_orgs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalidate_register_list_cache()
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return MagicMock(items=[], total=0, limit=limit, offset=offset, db_executes=1)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        _paginate,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.register_service.ensure_org_time_sensitive_summary_counts",
        AsyncMock(return_value=0),
    )

    session = AsyncMock()
    await list_governance_register_page(session, _user(), limit=6, offset=0)
    await list_governance_register_page(session, _user(), limit=6, offset=0)
    assert calls == 2
    invalidate_register_list_cache()


@pytest.mark.asyncio
async def test_register_write_invalidation_clears_limit_6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalidate_register_list_cache()
    user = _user()
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return MagicMock(items=[], total=0, limit=limit, offset=offset, db_executes=1)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        _paginate,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.register_service.ensure_org_time_sensitive_summary_counts",
        AsyncMock(return_value=0),
    )

    session = AsyncMock()
    await list_governance_register_page(session, user, limit=6, offset=0)
    assert len(_register_list_cache) == 1
    invalidate_governance_read_caches_after_commit()
    assert len(_register_list_cache) == 0
    await list_governance_register_page(session, user, limit=6, offset=0)
    assert calls == 2
    invalidate_register_list_cache()
