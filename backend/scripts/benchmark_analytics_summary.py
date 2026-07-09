"""Benchmark GET /governance/analytics/summary service path against dev DB."""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID

# Allow running from backend/ without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.governance.services.analytics_service import (  # noqa: E402
    _analytics_summary_cache,
    get_governance_analytics_summary,
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


async def _run_once() -> float:
    _analytics_summary_cache.clear()
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        await get_governance_analytics_summary(session, _user(), days=30)
    return (perf_counter() - started) * 1000


async def main() -> None:
    # Warm connection pool.
    async with AsyncSessionLocal() as session:
        await session.execute(__import__("sqlalchemy").text("SELECT 1"))

    timings: list[float] = []
    for index in range(RUNS):
        timings.append(await _run_once())
        print(f"run {index + 1}: {timings[-1]:.1f} ms")

    print(
        f"summary benchmark runs={RUNS} "
        f"min={min(timings):.1f}ms avg={statistics.mean(timings):.1f}ms "
        f"max={max(timings):.1f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
