from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser, can_read_all_orgs
from app.db.models import Project


def scoped_project_query(current_user: CurrentUser) -> Select[tuple[Project]]:
    query = select(Project).where(Project.deleted_at.is_(None))
    if not can_read_all_orgs(current_user.role):
        query = query.where(Project.org_id == current_user.org_id)
    return query


async def get_visible_project(session: AsyncSession, project_id: UUID, current_user: CurrentUser) -> Project:
    query = scoped_project_query(current_user).where(Project.id == project_id)
    project = (await session.execute(query)).scalar_one_or_none()
    if project is None:
        raise ApiError(404, "NOT_FOUND", "Project was not found.", {"project_id": str(project_id)})
    return project
