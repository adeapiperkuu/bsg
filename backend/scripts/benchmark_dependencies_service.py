"""Benchmark dependencies list: cache miss vs cache hit.

Dashboard first-page shape uses limit=6 (frontend TABLE_PAGE_SIZE). Phase 1 made
limit=6 cache-eligible alongside the legacy limit=50 shape.
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

from app.agents.governance.services.governance_service import (  # noqa: E402
    _invalidate_dependencies_list_cache,
    list_governance_dependencies_page,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
DASHBOARD_LIMIT = 6
LEGACY_CACHEABLE_LIMIT = 50
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


async def _run(limit: int) -> tuple[float, int, int]:
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_dependencies_page(session, _user(), limit=limit, offset=0)
    return (perf_counter() - started) * 1000, page.db_executes, len(page.items)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    print(f"=== production first-page shape limit={DASHBOARD_LIMIT} ===")
    miss_timings: list[float] = []
    for index in range(MISS_RUNS):
        _invalidate_dependencies_list_cache()
        ms, executes, rows = await _run(DASHBOARD_LIMIT)
        miss_timings.append(ms)
        print(f"limit=6 miss {index + 1}: {ms:.1f} ms (db_executes={executes}, rows={rows})")
    warm = miss_timings[1:] or miss_timings
    print(
        f"limit=6 warm miss: min={min(warm):.1f}ms avg={statistics.mean(warm):.1f}ms "
        f"max={max(warm):.1f}ms"
    )

    _invalidate_dependencies_list_cache()
    await _run(DASHBOARD_LIMIT)
    hit_timings: list[float] = []
    for index in range(HIT_RUNS):
        ms, executes, rows = await _run(DASHBOARD_LIMIT)
        hit_timings.append(ms)
        print(f"limit=6 hit {index + 1}: {ms:.3f} ms (db_executes={executes}, rows={rows})")
    print(
        f"limit=6 cache hit: min={min(hit_timings):.3f}ms "
        f"avg={statistics.mean(hit_timings):.3f}ms max={max(hit_timings):.3f}ms"
    )

    print(f"\n=== legacy cacheable shape limit={LEGACY_CACHEABLE_LIMIT} ===")
    legacy_miss: list[float] = []
    for index in range(MISS_RUNS):
        _invalidate_dependencies_list_cache()
        ms, executes, rows = await _run(LEGACY_CACHEABLE_LIMIT)
        legacy_miss.append(ms)
        print(f"cache miss {index + 1}: {ms:.1f} ms (db_executes={executes}, rows={rows})")

    _invalidate_dependencies_list_cache()
    await _run(LEGACY_CACHEABLE_LIMIT)
    legacy_hit: list[float] = []
    for index in range(HIT_RUNS):
        ms, executes, rows = await _run(LEGACY_CACHEABLE_LIMIT)
        legacy_hit.append(ms)
        print(f"cache hit {index + 1}: {ms:.3f} ms (db_executes={executes}, rows={rows})")

    warm_miss = legacy_miss[1:] or legacy_miss
    print(
        f"\ncache miss (warm, limit=50): min={min(warm_miss):.1f}ms "
        f"avg={statistics.mean(warm_miss):.1f}ms db_executes=1"
    )
    print(
        f"cache hit (limit=50): min={min(legacy_hit):.3f}ms "
        f"avg={statistics.mean(legacy_hit):.3f}ms "
        f"max={max(legacy_hit):.3f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
