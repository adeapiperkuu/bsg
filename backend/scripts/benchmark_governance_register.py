"""Benchmark Governance register same-day and simulated UTC-rollover paths against dev DB.

The rollover setup and refresh run inside a transaction that is always rolled back, so the
benchmark does not persist timestamp/count changes.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update  # noqa: E402

from app.agents.governance.services.project_governance_summary_service import (  # noqa: E402
    refresh_stale_governance_summary_counts,
)
from app.agents.governance.services.register_service import (
    _register_list_cache,
    list_governance_register_page,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, ProjectGovernanceSummary  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
DASHBOARD_LIMIT = 6
RUNS = 5


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _clear_caches() -> None:
    _register_list_cache.clear()


async def _cold_run() -> tuple[float, int, int]:
    _clear_caches()
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_register_page(
            session, _user(), limit=DASHBOARD_LIMIT, offset=0
        )
    return (perf_counter() - started) * 1000, page.total, page.db_executes


async def _hit_run() -> tuple[float, int, int]:
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_register_page(
            session, _user(), limit=DASHBOARD_LIMIT, offset=0
        )
    return (perf_counter() - started) * 1000, page.total, page.db_executes


async def _rollover_run() -> tuple[float, int, float, int, float, int, int]:
    """Return refresh, first-read, and second-read measurements; persist nothing."""
    _clear_caches()
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(ProjectGovernanceSummary)
                .where(ProjectGovernanceSummary.org_id == ORG_ID)
                .values(updated_at=now - timedelta(days=1))
            )

            refresh_started = perf_counter()
            refresh = await refresh_stale_governance_summary_counts(
                session,
                today=now.date(),
                refreshed_at=now,
            )
            refresh_ms = (perf_counter() - refresh_started) * 1000

            first_started = perf_counter()
            first = await list_governance_register_page(
                session, _user(), limit=DASHBOARD_LIMIT, offset=0
            )
            first_ms = (perf_counter() - first_started) * 1000

            second_started = perf_counter()
            second = await list_governance_register_page(
                session, _user(), limit=DASHBOARD_LIMIT, offset=0
            )
            second_ms = (perf_counter() - second_started) * 1000
        finally:
            await session.rollback()
            _clear_caches()
    return (
        refresh_ms,
        refresh.execute_count,
        first_ms,
        first.db_executes,
        second_ms,
        second.db_executes,
        refresh.rows_refreshed,
    )


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * 0.95
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    cold_timings: list[float] = []
    db_executes: list[int] = []

    for index in range(RUNS):
        ms, total, executes = await _cold_run()
        cold_timings.append(ms)
        db_executes.append(executes)
        print(
            f"cold run {index + 1}: {ms:.1f} ms "
            f"(total={total}, db_executes={executes}, limit={DASHBOARD_LIMIT})"
        )

    # Prime then measure cache hits.
    _register_list_cache.clear()
    await _hit_run()
    hit_timings: list[float] = []
    for index in range(3):
        ms, total, executes = await _hit_run()
        hit_timings.append(ms)
        print(
            f"cache hit {index + 1}: {ms:.3f} ms "
            f"(total={total}, db_executes={executes}, limit={DASHBOARD_LIMIT})"
        )

    refresh_timings: list[float] = []
    rollover_first_timings: list[float] = []
    rollover_second_timings: list[float] = []
    rollover_refresh_executes: list[int] = []
    rollover_first_executes: list[int] = []
    rollover_second_executes: list[int] = []
    for index in range(RUNS):
        (
            refresh_ms,
            refresh_executes,
            first_ms,
            first_executes,
            second_ms,
            second_executes,
            rows,
        ) = await _rollover_run()
        refresh_timings.append(refresh_ms)
        rollover_first_timings.append(first_ms)
        rollover_second_timings.append(second_ms)
        rollover_refresh_executes.append(refresh_executes)
        rollover_first_executes.append(first_executes)
        rollover_second_executes.append(second_executes)
        print(
            f"rollover run {index + 1}: refresh={refresh_ms:.1f}ms/{refresh_executes} execute "
            f"rows={rows}; first_read={first_ms:.1f}ms/{first_executes} execute; "
            f"second_read={second_ms:.3f}ms/{second_executes} executes"
        )

    print(
        f"register cold limit=6: min={min(cold_timings):.1f}ms "
        f"avg={statistics.mean(cold_timings):.1f}ms "
        f"max={max(cold_timings):.1f}ms db_executes={db_executes[0]}"
    )
    print(
        f"register cache-hit limit=6: min={min(hit_timings):.3f}ms "
        f"avg={statistics.mean(hit_timings):.3f}ms max={max(hit_timings):.3f}ms"
    )
    print(
        f"same-day cold p50={statistics.median(cold_timings):.1f}ms "
        f"p95={_p95(cold_timings):.1f}ms executes={db_executes[0]}"
    )
    print(
        f"warm hit p50={statistics.median(hit_timings):.3f}ms "
        f"p95={_p95(hit_timings):.3f}ms executes=0"
    )
    print(
        f"scheduled rollover refresh p50={statistics.median(refresh_timings):.1f}ms "
        f"p95={_p95(refresh_timings):.1f}ms executes={rollover_refresh_executes[0]}"
    )
    print(
        f"first read after rollover p50={statistics.median(rollover_first_timings):.1f}ms "
        f"p95={_p95(rollover_first_timings):.1f}ms "
        f"executes={rollover_first_executes[0]}"
    )
    print(
        f"second read after rollover p50={statistics.median(rollover_second_timings):.3f}ms "
        f"p95={_p95(rollover_second_timings):.3f}ms "
        f"executes={rollover_second_executes[0]}"
    )


if __name__ == "__main__":
    asyncio.run(main())
