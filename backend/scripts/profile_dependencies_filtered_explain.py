"""EXPLAIN ANALYZE for filtered dependency list queries."""

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
    _dependency_list_stmt,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, ProjectDependency  # noqa: E402
from app.db.session import engine  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")


def _user() -> CurrentUser:
    return CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        org_id=ORG_ID,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def _sql(**filter_kwargs) -> str:
    filters = _bounded_list_filters(limit=50, offset=0, **filter_kwargs)
    stmt = _dependency_list_stmt(_user())
    stmt = _apply_dependency_page_filters(stmt, filters)
    stmt = stmt.order_by(
        ProjectDependency.due_date.asc().nulls_last(),
        ProjectDependency.created_at.desc(),
    )
    stmt = stmt.add_columns(func.count().over().label(PAGINATION_TOTAL_LABEL)).limit(50).offset(0)
    return str(stmt.compile(compile_kwargs={"literal_binds": True}, dialect=engine.dialect))


async def explain(label: str, sql: str) -> None:
    print(f"\n=== {label} ===\n")
    async with engine.connect() as conn:
        result = await conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}"))
        for row in result:
            print(row[0])


async def main() -> None:
    await explain("DEFAULT", _sql())
    await explain("status=open", _sql(status="open"))
    await explain("project_id filter", _sql(project_id=ORG_ID))  # may return 0 rows


if __name__ == "__main__":
    asyncio.run(main())
