"""Benchmark governance bootstrap against dev DB."""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.agents.governance.services.dashboard_service import (  # noqa: E402
    _bootstrap_kpi_cache,
    get_governance_bootstrap,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
RUNS = 5


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=role,
        is_active=True,
    )


async def _cold_run() -> float:
    _bootstrap_kpi_cache.clear()
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        await get_governance_bootstrap(session, _user())
    return (perf_counter() - started) * 1000


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    timings: list[float] = []
    for index in range(RUNS):
        ms = await _cold_run()
        timings.append(ms)
        print(f"cold run {index + 1}: {ms:.1f} ms")

    print(
        f"bootstrap cold-cache-cleared: min={min(timings):.1f}ms "
        f"avg={statistics.mean(timings):.1f}ms max={max(timings):.1f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
