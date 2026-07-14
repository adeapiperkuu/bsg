"""Phase 0 governance latency baseline against real production request shapes.

Measures service-layer latency for the same parameters the frontend sends on
first paint / first tab load. Does not change cache eligibility or SQL.

Usage (from backend/):
  python scripts/benchmark_governance_latency_baseline.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.agents.governance.services.analytics_service import (  # noqa: E402
    _analytics_detail_cache,
    _analytics_summary_cache,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.agents.governance.services.dashboard_service import (  # noqa: E402
    _bootstrap_kpi_cache,
    get_governance_bootstrap,
)
from app.agents.governance.services.governance_service import (  # noqa: E402
    _invalidate_dependencies_list_cache,
    list_governance_actions_page,
    list_governance_dependencies_page,
    list_governance_escalations_page,
    list_governance_scope_states_page,
)
from app.agents.governance.services.project_governance_summary_service import (  # noqa: E402
    _org_summary_day_refreshed,
)
from app.agents.governance.services.register_service import (  # noqa: E402
    _register_list_cache,
    list_governance_register_page,
)
from app.agents.governance.timing import (  # noqa: E402
    GovernanceEndpointTimer,
    _reset_governance_timer,
    _set_governance_timer,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, Project  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

# Matches frontend TABLE_PAGE_SIZE / GOVERNANCE_DEFAULT_TABLE_PARAMS.
DASHBOARD_PAGE_LIMIT = 6
DASHBOARD_PAGE_OFFSET = 0
ANALYTICS_DAYS = 30

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
INTERNAL_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
CLIENT_USER_ID = UUID("22222222-2222-2222-2222-222222222222")

COLD_RUNS = 5
REPEAT_RUNS = 5
CACHE_HIT_RUNS = 5


@dataclass
class Sample:
    total_ms: float
    db_ms: float
    serialization_ms: float
    db_executes: int | None
    cache_hit: bool
    row_count: int


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _summarize(label: str, samples: list[Sample]) -> None:
    timings = [s.total_ms for s in samples]
    ordered = sorted(timings)
    executes = [s.db_executes for s in samples if s.db_executes is not None]
    rows = [s.row_count for s in samples]
    cache_hits = sum(1 for s in samples if s.cache_hit)
    print(
        f"  {label}: n={len(samples)} "
        f"min={min(timings):.1f}ms avg={statistics.mean(timings):.1f}ms "
        f"median={statistics.median(timings):.1f}ms "
        f"p90={_percentile(ordered, 0.90):.1f}ms p95={_percentile(ordered, 0.95):.1f}ms "
        f"max={max(timings):.1f}ms "
        f"db_ms_avg={statistics.mean(s.db_ms for s in samples):.1f}ms "
        f"serialization_ms_avg={statistics.mean(s.serialization_ms for s in samples):.1f}ms "
        f"db_executes={executes[0] if executes else 'n/a'} "
        f"cache_hits={cache_hits}/{len(samples)} "
        f"row_count={rows[0] if rows else 0}"
    )


def _internal_user() -> CurrentUser:
    return CurrentUser(
        id=INTERNAL_USER_ID,
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _client_user() -> CurrentUser:
    return CurrentUser(
        id=CLIENT_USER_ID,
        org_id=ORG_ID,
        email="client@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )


def _clear_all_caches() -> None:
    _bootstrap_kpi_cache.clear()
    _analytics_summary_cache.clear()
    _analytics_detail_cache.clear()
    _invalidate_dependencies_list_cache()
    _register_list_cache.clear()
    _org_summary_day_refreshed.clear()


async def _warm_pool() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))


async def _first_project_id(user: CurrentUser) -> UUID | None:
    async with AsyncSessionLocal() as session:
        stmt = select(Project.id).where(Project.deleted_at.is_(None))
        if user.role != AppRole.SUPER_ADMIN:
            stmt = stmt.where(Project.org_id == user.org_id)
        return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def _measure_with_timer(
    endpoint: str,
    user: CurrentUser,
    fn: Callable[[], Awaitable[tuple[int | None, bool, int]]],
    *,
    prefer_returned_executes: bool = False,
) -> Sample:
    timer = GovernanceEndpointTimer(endpoint, user)
    token = _set_governance_timer(timer)
    try:
        db_executes, cache_hit, row_count = await fn()
        timer.finish(row_count=row_count)
    finally:
        _reset_governance_timer(token)
    return Sample(
        total_ms=timer.total_ms,
        db_ms=round(timer.db_ms, 1),
        serialization_ms=timer.serialization_ms,
        db_executes=(
            db_executes
            if prefer_returned_executes
            else timer.execute_count
            if timer.execute_count is not None
            else db_executes
        ),
        cache_hit=timer.cache_hit if timer.cache_hit is not None else cache_hit,
        row_count=row_count,
    )


async def _measure_bootstrap(user: CurrentUser, *, expect_cache: bool) -> Sample:
    return await _measure_with_timer(
        "GET /governance/bootstrap",
        user,
        lambda: _measure_bootstrap_inner(user, expect_cache=expect_cache),
    )


async def _measure_bootstrap_inner(
    user: CurrentUser,
    *,
    expect_cache: bool,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        await get_governance_bootstrap(session, user)
    return (0 if expect_cache else 1, expect_cache, 1)


async def _measure_dependencies(user: CurrentUser) -> Sample:
    return await _measure_with_timer(
        "GET /governance/dependencies",
        user,
        lambda: _measure_dependencies_inner(user),
    )


async def _measure_dependencies_inner(
    user: CurrentUser,
    *,
    project_id: UUID | None = None,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        page = await list_governance_dependencies_page(
            session,
            user,
            limit=DASHBOARD_PAGE_LIMIT,
            offset=DASHBOARD_PAGE_OFFSET,
            project_id=project_id,
        )
    return (page.db_executes, page.db_executes == 0, len(page.items))


async def _measure_actions(user: CurrentUser) -> Sample:
    return await _measure_with_timer(
        "GET /governance/actions",
        user,
        lambda: _measure_actions_inner(user),
    )


async def _measure_actions_inner(
    user: CurrentUser,
    *,
    project_id: UUID | None = None,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        page = await list_governance_actions_page(
            session,
            user,
            limit=DASHBOARD_PAGE_LIMIT,
            offset=DASHBOARD_PAGE_OFFSET,
            project_id=project_id,
        )
    return (page.db_executes, False, len(page.items))


async def _measure_escalations(user: CurrentUser) -> Sample:
    return await _measure_with_timer(
        "GET /governance/escalations",
        user,
        lambda: _measure_escalations_inner(user),
    )


async def _measure_escalations_inner(
    user: CurrentUser,
    *,
    project_id: UUID | None = None,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        page = await list_governance_escalations_page(
            session,
            user,
            limit=DASHBOARD_PAGE_LIMIT,
            offset=DASHBOARD_PAGE_OFFSET,
            project_id=project_id,
        )
    return (page.db_executes, False, len(page.items))


async def _measure_register(user: CurrentUser) -> Sample:
    return await _measure_with_timer(
        "GET /governance/register",
        user,
        lambda: _measure_register_inner(user),
    )


async def _measure_register_inner(
    user: CurrentUser,
    *,
    project_id: UUID | None = None,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        page = await list_governance_register_page(
            session,
            user,
            limit=DASHBOARD_PAGE_LIMIT,
            offset=DASHBOARD_PAGE_OFFSET,
            project_id=project_id,
        )
    return (page.db_executes, page.db_executes == 0, len(page.items))


async def _measure_scope_states_inner(
    user: CurrentUser,
    *,
    project_id: UUID | None = None,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        page = await list_governance_scope_states_page(
            session,
            user,
            limit=1 if project_id else DASHBOARD_PAGE_LIMIT,
            offset=DASHBOARD_PAGE_OFFSET,
            project_id=project_id,
        )
    return (page.db_executes, False, len(page.items))


async def _measure_analytics_summary(user: CurrentUser, *, expect_cache: bool) -> Sample:
    return await _measure_with_timer(
        "GET /governance/analytics/summary",
        user,
        lambda: _measure_analytics_summary_inner(user, expect_cache=expect_cache),
    )


async def _measure_analytics_summary_inner(
    user: CurrentUser,
    *,
    expect_cache: bool,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        data = await get_governance_analytics_summary(session, user, days=ANALYTICS_DAYS)
    return (0 if expect_cache else 1, expect_cache, len(data.portfolio_risk_ranking))


async def _measure_analytics_detail(user: CurrentUser, *, expect_cache: bool) -> Sample:
    return await _measure_with_timer(
        "GET /governance/analytics/detail",
        user,
        lambda: _measure_analytics_detail_inner(user, expect_cache=expect_cache),
    )


async def _measure_analytics_detail_inner(
    user: CurrentUser,
    *,
    expect_cache: bool,
) -> tuple[int | None, bool, int]:
    async with AsyncSessionLocal() as session:
        data = await get_governance_analytics_detail(session, user, days=ANALYTICS_DAYS)
    return (0 if expect_cache else 2, expect_cache, len(data.insights) + len(data.recommendations))


async def _measure_project_sheet(user: CurrentUser, project_id: UUID | None) -> Sample:
    if project_id is None:
        return Sample(
            total_ms=0.0,
            db_ms=0.0,
            serialization_ms=0.0,
            db_executes=0,
            cache_hit=False,
            row_count=0,
        )

    async def _inner() -> tuple[int | None, bool, int]:
        deps_executes, _, deps_rows = await _measure_dependencies_inner(user, project_id=project_id)
        actions_executes, _, actions_rows = await _measure_actions_inner(
            user, project_id=project_id
        )
        escalations_executes, _, escalation_rows = await _measure_escalations_inner(
            user, project_id=project_id
        )
        register_executes, _, register_rows = await _measure_register_inner(
            user, project_id=project_id
        )
        scope_executes, _, scope_rows = await _measure_scope_states_inner(
            user, project_id=project_id
        )
        executes = sum(
            item or 0
            for item in [
                deps_executes,
                actions_executes,
                escalations_executes,
                register_executes,
                scope_executes,
            ]
        )
        rows = deps_rows + actions_rows + escalation_rows + register_rows + scope_rows
        return (executes, False, rows)

    return await _measure_with_timer(
        "PROJECT SHEET governance filtered reads",
        user,
        _inner,
        prefer_returned_executes=True,
    )


async def _run_series(
    label: str,
    measure: Callable[[], Awaitable[Sample]],
    *,
    runs: int,
    clear_before_each: bool,
) -> list[Sample]:
    samples: list[Sample] = []
    for index in range(runs):
        if clear_before_each:
            _clear_all_caches()
        sample = await measure()
        samples.append(sample)
        cache_label = "hit" if sample.cache_hit else "miss"
        executes = "n/a" if sample.db_executes is None else str(sample.db_executes)
        print(
            f"    {label} run {index + 1}: {sample.total_ms:.1f} ms "
            f"(db_ms={sample.db_ms:.1f}, serialization_ms={sample.serialization_ms:.1f}, "
            f"db_executes={executes}, cache={cache_label}, rows={sample.row_count})"
        )
    return samples


async def _benchmark_endpoint(
    title: str,
    miss_measure: Callable[[], Awaitable[Sample]],
    *,
    cache_hit_measure: Callable[[], Awaitable[Sample]] | None = None,
) -> None:
    print(f"\n=== {title} ===")

    print("  A/B. Cleared in-process cache each run (warm DB pool after SELECT 1):")
    cold = await _run_series(
        "cold",
        miss_measure,
        runs=COLD_RUNS,
        clear_before_each=True,
    )
    # Drop first sample as connection/process warm-up when possible.
    _summarize("cold-cache / warm-pool", cold[1:] or cold)

    print("  C. Immediate repeated request (no cache clear between runs):")
    _clear_all_caches()
    await miss_measure()
    # After the prime above, cacheable endpoints hit in-process cache on repeats.
    repeat_measure = cache_hit_measure or miss_measure
    repeated = await _run_series(
        "repeat",
        repeat_measure,
        runs=REPEAT_RUNS,
        clear_before_each=False,
    )
    _summarize("immediate-repeat", repeated)

    if cache_hit_measure is None:
        print("  E. In-process cache hit: N/A (shape not eligible under current cache rules)")
        return

    print("  E. In-process cache hit:")
    _clear_all_caches()
    await miss_measure()
    hits = await _run_series(
        "cache-hit",
        cache_hit_measure,
        runs=CACHE_HIT_RUNS,
        clear_before_each=False,
    )
    _summarize("cache-hit", hits)


async def main() -> None:
    print("Governance latency baseline (Phase 0)")
    print(f"Dashboard page shape: limit={DASHBOARD_PAGE_LIMIT} offset={DASHBOARD_PAGE_OFFSET}")
    print(f"Analytics days={ANALYTICS_DAYS}")
    print(f"Org={ORG_ID}")
    print("Modes: A cold/cleared cache, B first request, C immediate repeat,")
    print("       D warm DB pool (all runs after SELECT 1), E cache hit where eligible")

    await _warm_pool()
    internal = _internal_user()
    client = _client_user()
    project_id = await _first_project_id(internal)

    print("\n######## INTERNAL USER PATH ########")

    await _benchmark_endpoint(
        "GET /governance/bootstrap (internal)",
        lambda: _measure_bootstrap(internal, expect_cache=False),
        cache_hit_measure=lambda: _measure_bootstrap(internal, expect_cache=True),
    )

    # Frontend first page uses limit=6; Phase 1 made this cache-eligible.
    await _benchmark_endpoint(
        "GET /governance/dependencies?limit=6&offset=0 (internal first page)",
        lambda: _measure_dependencies(internal),
        cache_hit_measure=lambda: _measure_dependencies(internal),
    )

    # Register tab uses TABLE_PAGE_SIZE=6; Phase 1 made this cache-eligible.
    await _benchmark_endpoint(
        "GET /governance/register?limit=6&offset=0 (register tab)",
        lambda: _measure_register(internal),
        cache_hit_measure=lambda: _measure_register(internal),
    )

    await _benchmark_endpoint(
        "GET /governance/actions?limit=6&offset=0 (actions tab)",
        lambda: _measure_actions(internal),
    )

    await _benchmark_endpoint(
        "GET /governance/escalations?limit=6&offset=0 (internal escalations tab)",
        lambda: _measure_escalations(internal),
    )

    await _benchmark_endpoint(
        "GET /governance/analytics/summary?days=30 (internal)",
        lambda: _measure_analytics_summary(internal, expect_cache=False),
        cache_hit_measure=lambda: _measure_analytics_summary(internal, expect_cache=True),
    )

    await _benchmark_endpoint(
        "GET /governance/analytics/detail?days=30 (internal progressive)",
        lambda: _measure_analytics_detail(internal, expect_cache=False),
        cache_hit_measure=lambda: _measure_analytics_detail(internal, expect_cache=True),
    )

    await _benchmark_endpoint(
        "PROJECT SHEET filtered governance reads (internal)",
        lambda: _measure_project_sheet(internal, project_id),
    )

    print("\n######## CLIENT USER PATH ########")

    await _benchmark_endpoint(
        "GET /governance/bootstrap (client)",
        lambda: _measure_bootstrap(client, expect_cache=False),
        cache_hit_measure=lambda: _measure_bootstrap(client, expect_cache=True),
    )

    await _benchmark_endpoint(
        "GET /governance/escalations?limit=6&offset=0 (client first page)",
        lambda: _measure_escalations(client),
    )

    print("\nBaseline run complete. Copy summary lines into docs/governance-latency-baseline.md.")


if __name__ == "__main__":
    asyncio.run(main())
