"""EXPLAIN ANALYZE for GET /governance/dependencies default list query."""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, text  # noqa: E402

from app.agents.governance.services.governance_service import (  # noqa: E402
    PAGINATION_TOTAL_LABEL,
    _apply_dependency_page_filters,
    _bounded_list_filters,
    _dependency_count_stmt,
    _dependency_list_stmt,
    _invalidate_dependencies_list_cache,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, ProjectDependency  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
LIMIT = 50
OFFSET = 0


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _default_page_stmt(current_user: CurrentUser):
    from app.agents.governance.services.governance_service import _dependency_enriched_page_stmt

    filters = _bounded_list_filters(limit=LIMIT, offset=OFFSET)
    return _dependency_enriched_page_stmt(current_user, filters, limit=LIMIT, offset=OFFSET)


def _default_count_stmt(current_user: CurrentUser):
    filters = _bounded_list_filters(limit=LIMIT, offset=OFFSET)
    count_stmt = _dependency_count_stmt(current_user)
    return _apply_dependency_page_filters(count_stmt, filters)


async def explain(label: str, compiled_sql: str) -> None:
    print(f"\n=== {label} ===\n")
    async with engine.connect() as conn:
        result = await conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {compiled_sql}"))
        for row in result:
            print(row[0])


async def main() -> None:
    user = _user()
    page_stmt = _default_page_stmt(user)
    count_stmt = _default_count_stmt(user)

    page_sql = str(
        page_stmt.compile(compile_kwargs={"literal_binds": True}, dialect=engine.dialect)
    )
    count_sql = str(
        count_stmt.compile(compile_kwargs={"literal_binds": True}, dialect=engine.dialect)
    )

    print("PAGE SQL:\n", page_sql)
    await explain("PAGE (paginate ids + scalar count + join page)", page_sql)
    print("\nCOUNT SQL:\n", count_sql)
    await explain("COUNT (fallback only)", count_sql)

    _invalidate_dependencies_list_cache()
    from time import perf_counter

    from app.agents.governance.services.governance_service import list_governance_dependencies_page

    async with AsyncSessionLocal() as session:
        started = perf_counter()
        page = await list_governance_dependencies_page(session, user, limit=LIMIT, offset=OFFSET)
        total_ms = (perf_counter() - started) * 1000
        print(
            f"\nService timing: total_ms={total_ms:.1f} db_executes={page.db_executes} "
            f"row_count={len(page.items)} total={page.total}"
        )


if __name__ == "__main__":
    asyncio.run(main())
