"""Benchmark governance register against dev DB.

Uses the dashboard Register-tab page size (limit=6). Phase 1 made limit=6
cache-eligible alongside legacy limits 25 and 50.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.agents.governance.services.project_governance_summary_service import (
    _org_summary_day_refreshed,
)
from app.agents.governance.services.register_service import (
    _register_list_cache,
    list_governance_register_page,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole  # noqa: E402
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
    _org_summary_day_refreshed.clear()
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

    # Prime then measure cache hits (do not clear day cache so rollover stays warm).
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

    print(
        f"register cold limit=6: min={min(cold_timings):.1f}ms "
        f"avg={statistics.mean(cold_timings):.1f}ms "
        f"max={max(cold_timings):.1f}ms db_executes={db_executes[0]}"
    )
    print(
        f"register cache-hit limit=6: min={min(hit_timings):.3f}ms "
        f"avg={statistics.mean(hit_timings):.3f}ms max={max(hit_timings):.3f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
