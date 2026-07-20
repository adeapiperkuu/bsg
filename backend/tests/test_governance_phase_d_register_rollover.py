"""Phase D register read-path and UTC rollover refresh guards."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app import main as app_main
from app.agents.governance.services import register_service
from app.agents.governance.services.project_governance_summary_service import (
    GovernanceDailySummaryRefreshResult,
    refresh_stale_governance_summary_counts,
)
from app.agents.governance.services.register_service import (
    _register_cache_key,
    _register_list_cache,
    invalidate_register_list_cache,
    list_governance_register_page,
)
from app.agents.governance.timing import (
    GovernanceEndpointTimer,
    _reset_governance_timer,
    _set_governance_timer,
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
        org_id=org_id,
        email=f"{role.value}-{uuid4()}@example.com",
        role=role,
        is_active=True,
    )


def _empty_page(*, limit: int = 6, offset: int = 0):
    return SimpleNamespace(items=[], total=0, limit=limit, offset=offset, db_executes=1)


@pytest.fixture(autouse=True)
def _clear_register_cache():
    invalidate_register_list_cache()
    yield
    invalidate_register_list_cache()


@pytest.mark.asyncio
async def test_same_day_register_miss_is_one_execute_and_hit_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return _empty_page(limit=limit, offset=offset)

    monkeypatch.setattr(register_service, "_execute_paginated_rows", _paginate)
    user = _user(org_id=uuid4())

    miss_timer = GovernanceEndpointTimer("GET /governance/register", user)
    token = _set_governance_timer(miss_timer)
    try:
        first = await list_governance_register_page(AsyncMock(), user, limit=6, offset=0)
    finally:
        _reset_governance_timer(token)

    hit_timer = GovernanceEndpointTimer("GET /governance/register", user)
    token = _set_governance_timer(hit_timer)
    try:
        second = await list_governance_register_page(AsyncMock(), user, limit=6, offset=0)
    finally:
        _reset_governance_timer(token)

    assert calls == 1
    assert first.db_executes == miss_timer.execute_count == 1
    assert second.db_executes == hit_timer.execute_count == 0
    assert miss_timer.cache_hit is False
    assert hit_timer.cache_hit is True
    assert miss_timer.summary_refresh_required is False
    assert miss_timer.summary_refresh_performed is False
    assert miss_timer.summary_refresh_ms == 0.0
    assert miss_timer.summary_rows_refreshed == 0
    assert miss_timer.register_row_count == hit_timer.register_row_count == 0


@pytest.mark.asyncio
async def test_filtered_register_requests_remain_uncached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _paginate(_session, _stmt, *, limit, offset, count_stmt):
        nonlocal calls
        calls += 1
        return _empty_page(limit=limit, offset=offset)

    monkeypatch.setattr(register_service, "_execute_paginated_rows", _paginate)
    user = _user(org_id=uuid4())
    await list_governance_register_page(AsyncMock(), user, limit=6, offset=0, search="risk")
    await list_governance_register_page(AsyncMock(), user, limit=6, offset=0, search="risk")
    assert calls == 2


@pytest.mark.asyncio
async def test_rollover_refresh_uses_explicit_utc_midnight_and_one_locked_update() -> None:
    session = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = []
    session.execute = AsyncMock(return_value=rows)
    refreshed_at = datetime(2026, 7, 14, 0, 5, tzinfo=UTC)

    result = await refresh_stale_governance_summary_counts(
        session,
        today=date(2026, 7, 14),
        refreshed_at=refreshed_at,
    )

    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile()
    sql = str(compiled).lower()
    datetime_params = [value for value in compiled.params.values() if isinstance(value, datetime)]
    assert session.execute.await_count == 1
    assert "pg_try_advisory_xact_lock" in sql
    assert "update project_governance_summary" in sql
    assert "governance_actions" in sql
    assert "project_dependencies" in sql
    assert datetime(2026, 7, 14, 0, 0, tzinfo=UTC) in datetime_params
    assert refreshed_at in datetime_params
    assert result.execute_count == 1


@pytest.mark.asyncio
async def test_rollover_refresh_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await refresh_stale_governance_summary_counts(
            AsyncMock(),
            today=date(2026, 7, 14),
            refreshed_at=datetime(2026, 7, 14, 0, 5),
        )


@pytest.mark.asyncio
async def test_concurrent_worker_results_are_idempotent_and_do_not_insert_rows() -> None:
    org_id = uuid4()
    project_id = uuid4()
    winner_rows = MagicMock()
    winner_rows.all.return_value = [MagicMock(org_id=org_id, project_id=project_id)]
    follower_rows = MagicMock()
    follower_rows.all.return_value = []
    winner = AsyncMock()
    winner.execute = AsyncMock(return_value=winner_rows)
    follower = AsyncMock()
    follower.execute = AsyncMock(return_value=follower_rows)

    first = await refresh_stale_governance_summary_counts(winner, today=date(2026, 7, 14))
    second = await refresh_stale_governance_summary_counts(follower, today=date(2026, 7, 14))

    first_sql = str(winner.execute.await_args.args[0]).lower()
    second_sql = str(follower.execute.await_args.args[0]).lower()
    assert first.rows_refreshed == 1
    assert second.rows_refreshed == 0
    assert first.execute_count == second.execute_count == 1
    assert "insert" not in first_sql
    assert "insert" not in second_sql
    assert "pg_try_advisory_xact_lock" in first_sql
    assert "pg_try_advisory_xact_lock" in second_sql


@pytest.mark.asyncio
async def test_scheduled_refresh_commits_before_cache_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    events: list[str] = []
    session = MagicMock()
    session.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def _session_scope():
        yield session

    result = GovernanceDailySummaryRefreshResult(
        business_date=date(2026, 7, 14),
        rows_refreshed=2,
        org_ids=(org_id,),
        execute_count=1,
        duration_ms=1.2,
    )
    monkeypatch.setattr(app_main, "session_scope", _session_scope)
    monkeypatch.setattr(
        app_main,
        "get_settings",
        lambda: SimpleNamespace(governance_register_daily_refresh_enabled=True),
    )
    monkeypatch.setattr(
        app_main,
        "refresh_stale_governance_summary_counts",
        AsyncMock(return_value=result),
    )
    monkeypatch.setattr(
        app_main,
        "invalidate_register_list_cache",
        lambda *, org_id: events.append("invalidate") or 1,
    )

    await app_main._scheduled_governance_register_summary_refresh()

    assert events == ["commit", "invalidate"]
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_scheduled_refresh_rolls_back_without_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    session = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    session.rollback = AsyncMock(side_effect=lambda: events.append("rollback"))

    @asynccontextmanager
    async def _session_scope():
        yield session

    result = GovernanceDailySummaryRefreshResult(
        business_date=date(2026, 7, 14),
        rows_refreshed=1,
        org_ids=(uuid4(),),
        execute_count=1,
        duration_ms=1.0,
    )
    monkeypatch.setattr(app_main, "session_scope", _session_scope)
    monkeypatch.setattr(
        app_main,
        "get_settings",
        lambda: SimpleNamespace(governance_register_daily_refresh_enabled=True),
    )
    monkeypatch.setattr(
        app_main,
        "refresh_stale_governance_summary_counts",
        AsyncMock(return_value=result),
    )
    monkeypatch.setattr(
        app_main,
        "invalidate_register_list_cache",
        lambda *, org_id: events.append("invalidate") or 1,
    )

    await app_main._scheduled_governance_register_summary_refresh()

    assert events == ["rollback"]


def test_register_invalidation_is_org_scoped_and_clears_super_admin_aggregate() -> None:
    org_a = uuid4()
    org_b = uuid4()
    user_a = _user(org_id=org_a)
    user_b = _user(org_id=org_b)
    super_admin = _user(AppRole.SUPER_ADMIN, org_id=None)
    now = datetime.now(UTC)
    for user in (user_a, user_b, super_admin):
        key = _register_cache_key(user, limit=6, offset=0)
        _register_list_cache[key] = (now, _empty_page())

    removed = invalidate_register_list_cache(org_id=org_a)

    assert removed == 2
    assert len(_register_list_cache) == 1
    assert next(iter(_register_list_cache))[0] == org_b
