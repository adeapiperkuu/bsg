"""Benchmark dependencies list: cache miss vs cache hit."""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.agents.governance.services.governance_service import (  # noqa: E402
    _invalidate_dependencies_list_cache,
    list_governance_dependencies_page,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
MISS_RUNS = 3
HIT_RUNS = 5


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def _miss_run() -> tuple[float, int]:
    _invalidate_dependencies_list_cache()
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_dependencies_page(session, _user(), limit=50, offset=0)
    return (perf_counter() - started) * 1000, page.db_executes


async def _hit_run() -> tuple[float, int]:
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_dependencies_page(session, _user(), limit=50, offset=0)
    return (perf_counter() - started) * 1000, page.db_executes


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    miss_timings: list[float] = []
    for index in range(MISS_RUNS):
        ms, executes = await _miss_run()
        miss_timings.append(ms)
        print(f"cache miss {index + 1}: {ms:.1f} ms (db_executes={executes})")

  # Prime cache once for hit runs.
    async with AsyncSessionLocal() as session:
        await list_governance_dependencies_page(session, _user(), limit=50, offset=0)

    hit_timings: list[float] = []
    hit_executes: list[int] = []
    for index in range(HIT_RUNS):
        ms, executes = await _hit_run()
        hit_timings.append(ms)
        hit_executes.append(executes)
        print(f"cache hit {index + 1}: {ms:.3f} ms (db_executes={executes})")

    warm_miss = miss_timings[1:] or miss_timings
    print(
        f"\ncache miss (warm): min={min(warm_miss):.1f}ms "
        f"avg={statistics.mean(warm_miss):.1f}ms db_executes=1"
    )
    print(
        f"cache hit: min={min(hit_timings):.3f}ms avg={statistics.mean(hit_timings):.3f}ms "
        f"max={max(hit_timings):.3f}ms db_executes={hit_executes[0]}"
    )


if __name__ == "__main__":
    asyncio.run(main())
