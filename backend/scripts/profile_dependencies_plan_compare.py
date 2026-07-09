"""Compare EXPLAIN plans: window-count vs paginate-then-join."""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.orm import aliased  # noqa: E402

from app.agents.governance.services.governance_service import (  # noqa: E402
    _apply_dependency_page_filters,
    _apply_org_filter,
    _bounded_list_filters,
    _dependency_count_stmt,
    _dependency_list_stmt,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, Project, ProjectDependency, User  # noqa: E402
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


def _paginate_then_join_sql(limit: int = 50, offset: int = 0) -> str:
    user = _user()
    filters = _bounded_list_filters(limit=limit, offset=offset)
    id_base = select(ProjectDependency.id).where(ProjectDependency.deleted_at.is_(None))
    id_base = _apply_org_filter(id_base, ProjectDependency.org_id, user)
    id_base = _apply_dependency_page_filters(id_base, filters)
    id_base = id_base.order_by(
        ProjectDependency.due_date.asc().nulls_last(),
        ProjectDependency.created_at.desc(),
    )
    page_ids = id_base.limit(limit).offset(offset).subquery("dep_page_ids")

    count_stmt = _dependency_count_stmt(user)
    count_stmt = _apply_dependency_page_filters(count_stmt, filters)
    total_scalar = count_stmt.scalar_subquery()

    owner = aliased(User)
    stmt = (
        select(
            ProjectDependency.id,
            ProjectDependency.project_id,
            ProjectDependency.title,
            ProjectDependency.dependency_type,
            ProjectDependency.owner_id,
            ProjectDependency.due_date,
            ProjectDependency.status,
            Project.name.label("project_name"),
            func.coalesce(owner.full_name, owner.email).label("owner_name"),
            total_scalar.label("_pagination_total"),
        )
        .select_from(page_ids)
        .join(ProjectDependency, ProjectDependency.id == page_ids.c.id)
        .join(Project, Project.id == ProjectDependency.project_id)
        .outerjoin(owner, owner.id == ProjectDependency.owner_id)
        .order_by(
            ProjectDependency.due_date.asc().nulls_last(),
            ProjectDependency.created_at.desc(),
        )
    )
    return str(stmt.compile(compile_kwargs={"literal_binds": True}, dialect=engine.dialect))


def _window_sql(limit: int = 50, offset: int = 0) -> str:
    from app.agents.governance.services.governance_service import PAGINATION_TOTAL_LABEL

    user = _user()
    filters = _bounded_list_filters(limit=limit, offset=offset)
    stmt = _dependency_list_stmt(user)
    stmt = _apply_dependency_page_filters(stmt, filters)
    stmt = stmt.order_by(
        ProjectDependency.due_date.asc().nulls_last(),
        ProjectDependency.created_at.desc(),
    )
    stmt = stmt.add_columns(func.count().over().label(PAGINATION_TOTAL_LABEL)).limit(limit).offset(offset)
    return str(stmt.compile(compile_kwargs={"literal_binds": True}, dialect=engine.dialect))


async def explain(label: str, sql: str) -> None:
    print(f"\n=== {label} ===\n")
    async with engine.connect() as conn:
        result = await conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}"))
        for row in result:
            print(row[0])


async def main() -> None:
    await explain("CURRENT (window count + join all)", _window_sql())
    await explain("PROPOSED (paginate ids, then join page)", _paginate_then_join_sql())


if __name__ == "__main__":
    asyncio.run(main())
