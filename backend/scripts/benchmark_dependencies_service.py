"""Benchmark dependencies list with cache cleared between cold runs."""

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
RUNS = 5


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def _cold_run() -> tuple[float, int]:
    _invalidate_dependencies_list_cache()
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_dependencies_page(session, _user(), limit=50, offset=0)
    return (perf_counter() - started) * 1000, page.db_executes


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    timings: list[float] = []
    for index in range(RUNS):
        ms, executes = await _cold_run()
        timings.append(ms)
        print(f"cold run {index + 1}: {ms:.1f} ms (db_executes={executes})")

    print(
        f"dependencies cold-cache-cleared: min={min(timings):.1f}ms "
        f"avg={statistics.mean(timings):.1f}ms max={max(timings):.1f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
