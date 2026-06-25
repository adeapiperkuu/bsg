from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectDependency


async def list_project_dependencies(
    session: AsyncSession,
    project_id,
) -> list[ProjectDependency]:
    return list(
        (
            await session.execute(
                select(ProjectDependency).where(
                    or_(
                        ProjectDependency.from_project_id == project_id,
                        ProjectDependency.to_project_id == project_id,
                    )
                )
                .order_by(ProjectDependency.created_at.desc())
            )
        ).scalars()
    )


async def create_project_dependency(
    session: AsyncSession,
    project: Project,
    *,
    to_project_id,
    dependency_type: str,
    due_date=None,
    notes: str | None = None,
) -> ProjectDependency:
    dep = ProjectDependency(
        from_project_id=project.id,
        to_project_id=to_project_id,
        org_id=project.org_id,
        dependency_type=dependency_type,
        status="open",
        due_date=due_date,
        notes=notes,
    )
    session.add(dep)
    await session.flush()
    return dep
