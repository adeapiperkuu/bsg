"""Per-query timing breakdown for analytics summary DB work."""

from __future__ import annotations

import asyncio
import os
import sys
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.agents.governance.services.analytics_service import (  # noqa: E402
    _fetch_summary_project_metrics,
)
from app.agents.governance.services.delivery_signals import (  # noqa: E402
    _gather_governance_signal_inputs,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.scoping import scoped_project_query  # noqa: E402
from app.db.models import Project  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def main() -> None:
    user = _user()
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))

    async with AsyncSessionLocal() as session:
        started = perf_counter()
        ids = list(
            (
                await session.execute(
                    scoped_project_query(user).with_only_columns(Project.id)
                )
            ).scalars()
        )
        print(f"visible_project_ids: {(perf_counter() - started) * 1000:.1f} ms ({len(ids)} projects)")

    async with AsyncSessionLocal() as session:
        started = perf_counter()
        projects, *_ = await _fetch_summary_project_metrics(
            session, user, today=__import__("datetime").date.today()
        )
        print(f"project_metrics: {(perf_counter() - started) * 1000:.1f} ms ({len(projects)} projects)")

    async with AsyncSessionLocal() as session:
        project_ids = [project.id for project in projects]
        started = perf_counter()
        await _gather_governance_signal_inputs(session, project_ids)
        print(f"delivery_signal_bundle (1 query): {(perf_counter() - started) * 1000:.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
