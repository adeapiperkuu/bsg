"""Benchmark governance register against dev DB."""

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
        page = await list_governance_register_page(session, _user(), limit=25, offset=0)
    return (perf_counter() - started) * 1000, page.total, page.db_executes


async def _warm_run() -> tuple[float, int, int]:
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_register_page(session, _user(), limit=25, offset=0)
    return (perf_counter() - started) * 1000, page.total, page.db_executes


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    cold_timings: list[float] = []
    warm_timings: list[float] = []
    db_executes: list[int] = []

    for index in range(RUNS):
        ms, total, executes = await _cold_run()
        cold_timings.append(ms)
        db_executes.append(executes)
        print(f"cold run {index + 1}: {ms:.1f} ms (total={total}, db_executes={executes})")

    for index in range(3):
        ms, total, executes = await _warm_run()
        warm_timings.append(ms)
        print(f"warm run {index + 1}: {ms:.1f} ms (total={total}, db_executes={executes})")

    print(
        f"register cold: min={min(cold_timings):.1f}ms avg={statistics.mean(cold_timings):.1f}ms "
        f"max={max(cold_timings):.1f}ms db_executes={db_executes[0]}"
    )
    print(
        f"register warm/cache: min={min(warm_timings):.1f}ms "
        f"avg={statistics.mean(warm_timings):.1f}ms max={max(warm_timings):.1f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
