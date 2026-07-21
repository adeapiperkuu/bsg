"""Phase B first-page cache and tenant-isolation guards for actions and escalations."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.agents.governance.services import governance_service
from app.agents.governance.services.governance_service import (
    ACTIONS_LIST_CACHE_TTL,
    ESCALATIONS_LIST_CACHE_TTL,
    PaginatedGovernanceRows,
    _actions_cache_key,
    _actions_list_cache,
    _apply_client_escalation_visibility,
    _bounded_list_filters,
    _escalation_count_stmt,
    _escalations_cache_key,
    _escalations_list_cache,
    _invalidate_actions_list_cache,
    _invalidate_escalations_list_cache,
    _is_default_actions_cacheable,
    _is_default_escalations_cacheable,
    create_action,
    invalidate_governance_read_caches_after_commit,
    list_governance_actions_page,
    list_governance_escalations_page,
)
from app.agents.governance.timing import (
    GovernanceEndpointTimer,
    _reset_governance_timer,
    _set_governance_timer,
)
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceActionStatus


def _user(
    role: AppRole = AppRole.DELIVERY_MANAGER,
    *,
    org_id=None,
    user_id=None,
) -> CurrentUser:
    return CurrentUser(
        id=user_id or uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}-{uuid4()}@example.com",
        role=role,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def _clear_phase_b_caches():
    _invalidate_actions_list_cache()
    _invalidate_escalations_list_cache()
    yield
    _invalidate_actions_list_cache()
    _invalidate_escalations_list_cache()


@pytest.mark.parametrize(
    ("helper", "extra"),
    [
        (_is_default_actions_cacheable, {"status": "open"}),
        (_is_default_escalations_cacheable, {"severity": "critical"}),
    ],
)
def test_only_unfiltered_limit_6_first_page_is_cacheable(helper, extra) -> None:
    assert helper(_bounded_list_filters(limit=6, offset=0)) is True
    assert helper(_bounded_list_filters(limit=6, offset=0, **extra)) is False
    assert helper(_bounded_list_filters(limit=6, offset=6)) is False
    assert helper(_bounded_list_filters(limit=50, offset=0)) is False
    assert helper(_bounded_list_filters(limit=6, offset=0, search="   ")) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "list_fn"),
    [
        ("GET /governance/actions", list_governance_actions_page),
        ("GET /governance/escalations", list_governance_escalations_page),
    ],
)
async def test_eligible_miss_is_one_execute_and_warm_hit_is_zero(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    list_fn,
) -> None:
    calls = 0
    row = SimpleNamespace(id=uuid4(), marker="safe")

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows([row], 1, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    user = _user()

    miss_timer = GovernanceEndpointTimer(path, user)
    token = _set_governance_timer(miss_timer)
    try:
        first = await list_fn(AsyncMock(), user, limit=6, offset=0)
    finally:
        _reset_governance_timer(token)

    hit_timer = GovernanceEndpointTimer(path, user)
    token = _set_governance_timer(hit_timer)
    started = perf_counter()
    try:
        second = await list_fn(AsyncMock(), user, limit=6, offset=0)
    finally:
        warm_ms = (perf_counter() - started) * 1000
        _reset_governance_timer(token)

    assert calls == 1
    assert first.items == second.items
    assert first.total == second.total == 1
    assert first.db_executes == miss_timer.execute_count == 1
    assert miss_timer.cache_hit is False
    assert second.db_executes == hit_timer.execute_count == 0
    assert hit_timer.cache_hit is True
    assert warm_ms < 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "list_fn",
    [list_governance_actions_page, list_governance_escalations_page],
)
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 6, "offset": 0, "project_id": uuid4()},
        {"limit": 6, "offset": 6},
        {"limit": 50, "offset": 0},
    ],
)
async def test_filtered_and_non_default_pages_bypass_cache(
    monkeypatch: pytest.MonkeyPatch,
    list_fn,
    params: dict,
) -> None:
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows([], 0, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    user = _user()
    await list_fn(AsyncMock(), user, **params)
    await list_fn(AsyncMock(), user, **params)
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("list_fn", "cache", "key_fn", "ttl"),
    [
        (
            list_governance_actions_page,
            _actions_list_cache,
            _actions_cache_key,
            ACTIONS_LIST_CACHE_TTL,
        ),
        (
            list_governance_escalations_page,
            _escalations_list_cache,
            _escalations_cache_key,
            ESCALATIONS_LIST_CACHE_TTL,
        ),
    ],
)
async def test_empty_results_cache_and_expire_without_sleeping(
    monkeypatch: pytest.MonkeyPatch,
    list_fn,
    cache: dict,
    key_fn,
    ttl: timedelta,
) -> None:
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return PaginatedGovernanceRows([], 0, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    user = _user()
    filters = _bounded_list_filters(limit=6, offset=0)
    first = await list_fn(AsyncMock(), user, limit=6, offset=0)
    second = await list_fn(AsyncMock(), user, limit=6, offset=0)
    assert calls == 1
    assert first.items == second.items == []
    key = key_fn(user, filters)
    cache[key] = (datetime.now(UTC) - ttl - timedelta(seconds=1), cache[key][1])
    await list_fn(AsyncMock(), user, limit=6, offset=0)
    assert calls == 2


@pytest.mark.asyncio
async def test_action_cache_isolates_orgs_and_users(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _paginate(session, _stmt, *, limit, offset, count_stmt):
        calls.append(session.marker)
        row = SimpleNamespace(marker=session.marker)
        return PaginatedGovernanceRows([row], 1, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    org_a = uuid4()
    user_a = _user(org_id=org_a)
    user_b = _user(org_id=org_a)
    user_c = _user(org_id=uuid4())

    pages = []
    for marker, user in (("A", user_a), ("B", user_b), ("C", user_c)):
        session = MagicMock(marker=marker)
        pages.append(await list_governance_actions_page(session, user, limit=6, offset=0))

    assert calls == ["A", "B", "C"]
    assert [page.items[0].marker for page in pages] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_escalation_cache_never_crosses_client_or_leadership_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _paginate(session, _stmt, *, limit, offset, count_stmt):
        calls.append(session.marker)
        row = SimpleNamespace(marker=session.marker)
        return PaginatedGovernanceRows([row], 1, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    org_id = uuid4()
    client_a = _user(AppRole.CLIENT, org_id=org_id)
    client_b = _user(AppRole.CLIENT, org_id=org_id)
    leadership = _user(AppRole.BSG_LEADERSHIP, org_id=org_id)

    pages = []
    for marker, user in (("project-a", client_a), ("project-b", client_b), ("all", leadership)):
        session = MagicMock(marker=marker)
        pages.append(await list_governance_escalations_page(session, user, limit=6, offset=0))

    assert calls == ["project-a", "project-b", "all"]
    assert [page.items[0].marker for page in pages] == ["project-a", "project-b", "all"]

    # Warm reads remain bound to the user-specific entries populated above.
    for marker, user in (("project-a", client_a), ("project-b", client_b), ("all", leadership)):
        page = await list_governance_escalations_page(
            MagicMock(marker="leak"), user, limit=6, offset=0
        )
        assert page.items[0].marker == marker
        assert page.db_executes == 0
    assert calls == ["project-a", "project-b", "all"]


def test_client_assignment_and_publish_filters_are_database_predicates() -> None:
    client = _user(AppRole.CLIENT)
    stmt = _apply_client_escalation_visibility(_escalation_count_stmt(client), client)
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "project_assignments" in sql
    assert str(client.id) in sql
    assert str(client.org_id) in sql
    assert "is_active IS true" in sql
    assert "deleted_at IS NULL" in sql
    assert "client_visible IS true" in sql


@pytest.mark.asyncio
async def test_org_scoped_invalidation_clears_target_and_super_admin_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        return PaginatedGovernanceRows([], 0, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    org_a = uuid4()
    org_b = uuid4()
    users = [_user(org_id=org_a), _user(org_id=org_b), _user(AppRole.SUPER_ADMIN)]
    for user in users:
        await list_governance_actions_page(AsyncMock(), user, limit=6, offset=0)
        await list_governance_escalations_page(AsyncMock(), user, limit=6, offset=0)

    result = invalidate_governance_read_caches_after_commit(org_id=org_a)

    assert result.actions_removed == 2
    assert result.escalations_removed == 2
    assert len(_actions_list_cache) == len(_escalations_list_cache) == 1
    remaining_action_key = next(iter(_actions_list_cache))
    remaining_escalation_key = next(iter(_escalations_list_cache))
    assert remaining_action_key[0] == remaining_escalation_key[0] == org_b


@pytest.mark.asyncio
async def test_action_mutation_invalidates_only_after_successful_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        return PaginatedGovernanceRows([], 0, limit, offset, db_executes=1)

    monkeypatch.setattr(governance_service, "_execute_paginated_rows", _paginate)
    user = _user()
    await list_governance_actions_page(AsyncMock(), user, limit=6, offset=0)
    await list_governance_escalations_page(AsyncMock(), user, limit=6, offset=0)
    assert len(_actions_list_cache) == len(_escalations_list_cache) == 1

    project_id = uuid4()
    monkeypatch.setattr(
        governance_service,
        "get_visible_project",
        AsyncMock(return_value=SimpleNamespace(id=project_id, org_id=user.org_id)),
    )
    monkeypatch.setattr(governance_service, "log_governance_event", AsyncMock())
    monkeypatch.setattr(governance_service, "refresh_project_governance_summary", AsyncMock())
    session = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError, match="commit failed"):
        await create_action(
            session,
            user,
            project_id=project_id,
            title="Do the thing",
            description=None,
            owner_id=None,
            due_date=date.today(),
            status=GovernanceActionStatus.OPEN,
        )

    assert len(_actions_list_cache) == len(_escalations_list_cache) == 1

    session.commit = AsyncMock()
    await create_action(
        session,
        user,
        project_id=project_id,
        title="Do the thing",
        description=None,
        owner_id=None,
        due_date=date.today(),
        status=GovernanceActionStatus.OPEN,
    )
    assert _actions_list_cache == {}
    assert _escalations_list_cache == {}
