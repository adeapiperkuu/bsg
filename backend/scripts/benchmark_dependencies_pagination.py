"""Compare dependencies pagination strategies against dev DB."""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import aliased  # noqa: E402

from app.agents.governance.services.governance_service import (  # noqa: E402
    _apply_dependency_page_filters,
    _apply_org_filter,
    _bounded_list_filters,
    _dependency_count_stmt,
    _dependency_list_stmt,
    map_dependency_list_row,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, Project, ProjectDependency, User  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
RUNS = 5


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _rows_stmt(user: CurrentUser):
    filters = _bounded_list_filters(limit=50, offset=0)
    stmt = _dependency_list_stmt(user)
    stmt = _apply_dependency_page_filters(stmt, filters)
    return stmt.order_by(
        ProjectDependency.due_date.asc().nulls_last(),
        ProjectDependency.created_at.desc(),
    )


def _count_stmt(user: CurrentUser):
    filters = _bounded_list_filters(limit=50, offset=0)
    stmt = _dependency_count_stmt(user)
    return _apply_dependency_page_filters(stmt, filters)


def _window_stmt(user: CurrentUser):
    owner = aliased(User)
    filters = _bounded_list_filters(limit=50, offset=0)
    base = (
        select(
            ProjectDependency.id,
            ProjectDependency.project_id,
            ProjectDependency.title,
            ProjectDependency.dependency_type,
            ProjectDependency.owner_id,
            ProjectDependency.due_date,
            ProjectDependency.status,
            Project.name.label("project_name"),
            func.coalesce(owner.full_name, owner.email).label("owner_name"),
            func.count().over().label("total_count"),
        )
        .join(Project, Project.id == ProjectDependency.project_id)
        .outerjoin(owner, owner.id == ProjectDependency.owner_id)
        .where(ProjectDependency.deleted_at.is_(None))
    )
    base = _apply_org_filter(base, ProjectDependency.org_id, user)
    base = _apply_dependency_page_filters(base, filters)
    return base.order_by(
        ProjectDependency.due_date.asc().nulls_last(),
        ProjectDependency.created_at.desc(),
    ).limit(50).offset(0)


async def _parallel_count_rows(user: CurrentUser) -> tuple[int, int]:
    rows_stmt = _rows_stmt(user)
    count_stmt = _count_stmt(user)

    async def fetch_total():
        async with AsyncSessionLocal() as session:
            return int((await session.execute(count_stmt)).scalar_one())

    async def fetch_rows():
        async with AsyncSessionLocal() as session:
            return (await session.execute(rows_stmt.limit(50).offset(0))).all()

    total, rows = await asyncio.gather(fetch_total(), fetch_rows())
    return total, len(rows)


async def _sequential_count_rows(user: CurrentUser) -> tuple[int, int]:
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(_count_stmt(user))).scalar_one())
        rows = (await session.execute(_rows_stmt(user).limit(50).offset(0))).all()
    return total, len(rows)


async def _single_window_query(user: CurrentUser) -> tuple[int, int]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(_window_stmt(user))).all()
    total = int(rows[0].total_count) if rows else 0
    return total, len(rows)


async def _benchmark(label: str, fn) -> list[float]:
    timings: list[float] = []
    for index in range(RUNS):
        started = perf_counter()
        total, row_count = await fn(_user())
        elapsed = (perf_counter() - started) * 1000
        timings.append(elapsed)
        print(f"{label} run {index + 1}: {elapsed:.1f} ms (total={total}, rows={row_count})")
    print(
        f"{label} summary: min={min(timings):.1f}ms avg={statistics.mean(timings):.1f}ms "
        f"max={max(timings):.1f}ms"
    )
    return timings


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    print("=== parallel count+rows (current) ===")
    await _benchmark("parallel", _parallel_count_rows)
    print("=== sequential count+rows ===")
    await _benchmark("sequential", _sequential_count_rows)
    print("=== single query count() OVER() ===")
    await _benchmark("window", _single_window_query)


if __name__ == "__main__":
    asyncio.run(main())
