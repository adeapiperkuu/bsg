from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.governance.services.governance_service import create_dependency
from app.agents.governance.services.project_governance_summary_service import (
    compute_project_governance_counts,
    refresh_project_governance_summary,
    refresh_stale_governance_summary_counts,
)
from app.agents.governance.services.register_service import list_governance_register_page
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceDependencyStatus,
    GovernanceDependencyType,
    ProjectGovernanceSummary,
)


def _user(role: AppRole = AppRole.DELIVERY_MANAGER, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _count_result(**values):
    row = MagicMock()
    for key, value in values.items():
        setattr(row, key, value)
    result = MagicMock()
    result.one.return_value = row
    return result


@pytest.mark.asyncio
async def test_compute_project_governance_counts_aggregates_source_rows() -> None:
    org_id = uuid4()
    project_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=_count_result(
            open_dependencies=3,
            blocked=1,
            blocking_overdue=1,
            open_actions=4,
            overdue_actions=2,
            open_escalations=2,
            critical_escalations=1,
            pending_scope=1,
        )
    )

    counts = await compute_project_governance_counts(
        session, org_id, project_id, today=date(2026, 7, 6)
    )

    assert counts.open_dependencies_count == 3
    assert counts.blocked_dependencies_count == 1
    assert counts.blocking_overdue_dependencies_count == 1
    assert counts.open_actions_count == 4
    assert counts.overdue_actions_count == 2
    assert counts.open_escalations_count == 2
    assert counts.critical_escalations_count == 1
    assert counts.pending_scope_changes_count == 1
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_refresh_project_governance_summary_creates_summary_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    project_id = uuid4()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    existing = MagicMock()
    existing.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=existing)

    async def _fake_counts(_session, _org_id, _project_id, *, today=None):
        from app.agents.governance.services.project_governance_summary_service import (
            ProjectGovernanceCounts,
        )

        return ProjectGovernanceCounts(
            open_dependencies_count=1,
            blocked_dependencies_count=0,
            blocking_overdue_dependencies_count=0,
            open_actions_count=2,
            overdue_actions_count=0,
            open_escalations_count=0,
            critical_escalations_count=0,
            pending_scope_changes_count=0,
        )

    monkeypatch.setattr(
        "app.agents.governance.services.project_governance_summary_service.compute_project_governance_counts",
        _fake_counts,
    )

    summary = await refresh_project_governance_summary(session, org_id, project_id)

    assert isinstance(summary, ProjectGovernanceSummary)
    assert summary.org_id == org_id
    assert summary.project_id == project_id
    assert summary.open_actions_count == 2
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_project_governance_summary_updates_existing_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    project_id = uuid4()
    session = AsyncMock()
    session.flush = AsyncMock()

    existing_summary = ProjectGovernanceSummary(
        org_id=org_id,
        project_id=project_id,
        open_escalations_count=0,
    )
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = existing_summary
    session.execute = AsyncMock(return_value=lookup)

    async def _fake_counts(_session, _org_id, _project_id, *, today=None):
        from app.agents.governance.services.project_governance_summary_service import (
            ProjectGovernanceCounts,
        )

        return ProjectGovernanceCounts(
            open_dependencies_count=0,
            blocked_dependencies_count=0,
            blocking_overdue_dependencies_count=0,
            open_actions_count=0,
            overdue_actions_count=0,
            open_escalations_count=3,
            critical_escalations_count=1,
            pending_scope_changes_count=0,
        )

    monkeypatch.setattr(
        "app.agents.governance.services.project_governance_summary_service.compute_project_governance_counts",
        _fake_counts,
    )

    summary = await refresh_project_governance_summary(session, org_id, project_id)

    assert summary.open_escalations_count == 3
    assert summary.critical_escalations_count == 1
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_dependency_refreshes_project_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh = AsyncMock()
    monkeypatch.setattr(
        "app.agents.governance.services.governance_service.refresh_project_governance_summary",
        refresh,
    )
    monkeypatch.setattr(
        "app.agents.governance.services.governance_service.get_visible_project",
        AsyncMock(
            return_value=MagicMock(
                id=uuid4(),
                org_id=uuid4(),
            )
        ),
    )
    monkeypatch.setattr(
        "app.agents.governance.services.governance_service.log_governance_event",
        AsyncMock(return_value=0),
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dep = await create_dependency(
        session,
        uuid4(),
        _user(),
        title="Vendor sign-off",
        description=None,
        dependency_type=GovernanceDependencyType.CLIENT_ACTION,
        owner_id=None,
        due_date=None,
        status=GovernanceDependencyStatus.OPEN,
    )

    refresh.assert_awaited_once()
    assert refresh.await_args.args[1] == dep.org_id
    assert refresh.await_args.args[2] == dep.project_id


@pytest.mark.asyncio
async def test_register_query_reads_project_governance_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def capture_statement(_session, stmt, *, limit, offset, count_stmt):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        return MagicMock(items=[], total=0, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        capture_statement,
    )
    await list_governance_register_page(AsyncMock(), _user(), limit=10, offset=0)

    sql = captured["sql"].lower()
    assert "project_governance_summary" in sql
    assert "group by" not in sql
    assert "project_governance_summary.org_id" in sql
    assert "project_governance_summary.project_id" in sql


@pytest.mark.asyncio
async def test_register_page_still_applies_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, int] = {}

    async def capture_statement(_session, _stmt, *, limit, offset, count_stmt):
        captured["limit"] = limit
        captured["offset"] = offset
        return MagicMock(items=[], total=12, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        capture_statement,
    )
    page = await list_governance_register_page(AsyncMock(), _user(), limit=5, offset=5)

    assert captured["limit"] == 5
    assert captured["offset"] == 5
    assert page.total == 12


@pytest.mark.asyncio
async def test_register_org_isolation_joins_summary_to_project_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_a = uuid4()
    captured: dict[str, str] = {}

    async def capture_statement(_session, stmt, *, limit, offset, count_stmt):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        return MagicMock(items=[], total=0, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        capture_statement,
    )
    await list_governance_register_page(
        AsyncMock(return_value=0),
        _user(org_id=org_a),
        limit=25,
        offset=0,
    )

    sql = captured["sql"]
    assert "project_governance_summary.org_id = projects.org_id" in sql.replace("\n", " ")


@pytest.mark.asyncio
async def test_register_count_query_omits_summary_join(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    async def capture_statement(_session, _stmt, *, limit, offset, count_stmt):
        captured["count_sql"] = str(count_stmt.compile(compile_kwargs={"literal_binds": False}))
        return MagicMock(items=[], total=4, limit=limit, offset=offset)

    monkeypatch.setattr(
        "app.agents.governance.services.register_service._execute_paginated_rows",
        capture_statement,
    )
    from app.agents.governance.services.register_service import list_governance_register_page

    page = await list_governance_register_page(AsyncMock(), _user(), limit=10, offset=0)

    count_sql = captured["count_sql"].lower()
    assert "project_governance_summary" not in count_sql
    assert "over()" not in count_sql
    assert page.total == 4


@pytest.mark.asyncio
async def test_daily_summary_refresh_is_one_locked_update_execute() -> None:
    org_id = uuid4()
    project_id = uuid4()
    result_rows = MagicMock()
    result_rows.all.return_value = [MagicMock(org_id=org_id, project_id=project_id)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_rows)

    result = await refresh_stale_governance_summary_counts(session, today=date(2026, 7, 6))

    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
    assert session.execute.await_count == 1
    assert "update project_governance_summary" in sql
    assert "pg_try_advisory_xact_lock" in sql
    assert "governance_actions" in sql
    assert "project_dependencies" in sql
    assert result.execute_count == 1
    assert result.rows_refreshed == 1
    assert result.org_ids == (org_id,)


@pytest.mark.asyncio
async def test_daily_summary_refresh_no_stale_rows_is_still_one_execute() -> None:
    session = AsyncMock()
    empty = MagicMock()
    empty.all.return_value = []
    session.execute = AsyncMock(return_value=empty)

    result = await refresh_stale_governance_summary_counts(session, today=date(2026, 7, 6))

    assert session.execute.await_count == 1
    assert result.rows_refreshed == 0
    assert result.org_ids == ()
