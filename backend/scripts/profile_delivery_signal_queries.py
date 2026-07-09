"""Time each delivery signal sub-query individually (warm session)."""

from __future__ import annotations

import asyncio
import os
import sys
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.agents.delivery.services.dashboard_service import (  # noqa: E402
    _fetch_latest_quality_by_project,
    _fetch_throughput_by_project,
)
from app.agents.governance.services.delivery_signals import (  # noqa: E402
    GOVERNANCE_THROUGHPUT_LIMIT,
    _fetch_active_milestones_by_project,
    _fetch_open_bottleneck_stubs_by_project,
    _fetch_open_risk_tiers_by_project,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, Project  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.scoping import scoped_project_query  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def _timed(label: str, fn) -> None:
    started = perf_counter()
    await fn()
    print(f"{label}: {(perf_counter() - started) * 1000:.1f} ms")


async def main() -> None:
    user = _user()
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
        project_ids = list(
            (await session.execute(scoped_project_query(user).with_only_columns(Project.id))).scalars()
        )

    async with AsyncSessionLocal() as session:
        await _timed(
            "throughput",
            lambda: _fetch_throughput_by_project(
                session, project_ids, limit=GOVERNANCE_THROUGHPUT_LIMIT
            ),
        )
        await _timed("quality", lambda: _fetch_latest_quality_by_project(session, project_ids))
        await _timed("milestones", lambda: _fetch_active_milestones_by_project(session, project_ids))
        await _timed("risks", lambda: _fetch_open_risk_tiers_by_project(session, project_ids))
        await _timed(
            "bottlenecks",
            lambda: _fetch_open_bottleneck_stubs_by_project(session, project_ids),
        )


if __name__ == "__main__":
    asyncio.run(main())
