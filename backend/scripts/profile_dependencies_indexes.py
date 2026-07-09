"""Check indexes and forced-index EXPLAIN for dependencies list."""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.agents.governance.services.governance_service import (  # noqa: E402
    PAGINATION_TOTAL_LABEL,
    _apply_dependency_page_filters,
    _bounded_list_filters,
    _dependency_list_stmt,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, ProjectDependency  # noqa: E402
from app.db.session import engine  # noqa: E402
from sqlalchemy import func  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _page_sql() -> str:
    filters = _bounded_list_filters(limit=50, offset=0)
    stmt = _dependency_list_stmt(_user())
    stmt = _apply_dependency_page_filters(stmt, filters)
    stmt = stmt.order_by(
        ProjectDependency.due_date.asc().nulls_last(),
        ProjectDependency.created_at.desc(),
    )
    stmt = stmt.add_columns(func.count().over().label(PAGINATION_TOTAL_LABEL)).limit(50).offset(0)
    return str(stmt.compile(compile_kwargs={"literal_binds": True}, dialect=engine.dialect))


async def main() -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'project_dependencies'
                ORDER BY indexname
                """
            )
        )
        print("=== project_dependencies indexes ===")
        for row in rows:
            print(f"{row.indexname}: {row.indexdef}")

        count = await conn.execute(
            text(
                "SELECT count(*) FROM project_dependencies WHERE deleted_at IS NULL AND org_id = :org"
            ),
            {"org": ORG_ID},
        )
        print(f"\nActive rows for org: {count.scalar_one()}")

        page_sql = _page_sql()
        print("\n=== EXPLAIN with enable_seqscan=off ===")
        await conn.execute(text("SET enable_seqscan = off"))
        result = await conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {page_sql}"))
        for row in result:
            print(row[0])
        await conn.execute(text("RESET enable_seqscan"))


if __name__ == "__main__":
    asyncio.run(main())
