from uuid import UUID

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, Project, ProjectAssignment


def _base_project_query() -> Select[tuple[Project]]:
    return select(Project).where(Project.deleted_at.is_(None))


def _client_assignment_filter(current_user: CurrentUser) -> Select[tuple[Project]]:
    assignment_exists = (
        select(ProjectAssignment.id)
        .where(
            ProjectAssignment.project_id == Project.id,
            ProjectAssignment.user_id == current_user.id,
            ProjectAssignment.is_active.is_(True),
            ProjectAssignment.deleted_at.is_(None),
        )
        .correlate(Project)
    )
    return _base_project_query().where(
        Project.org_id == current_user.org_id,
        exists(assignment_exists),
    )


def scoped_project_query(current_user: CurrentUser) -> Select[tuple[Project]]:
    """Return projects visible to the current user based on role."""
    if current_user.role == AppRole.SUPER_ADMIN:
        return _base_project_query()

    if current_user.role in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP}:
        return _base_project_query().where(Project.org_id == current_user.org_id)

    if current_user.role == AppRole.CLIENT:
        return _client_assignment_filter(current_user)

    return _base_project_query().where(Project.id.is_(None))


async def _has_active_assignment(
    session: AsyncSession,
    *,
    user_id: UUID,
    project_id: UUID,
) -> bool:
    assignment = (
        await session.execute(
            select(ProjectAssignment.id).where(
                ProjectAssignment.user_id == user_id,
                ProjectAssignment.project_id == project_id,
                ProjectAssignment.is_active.is_(True),
                ProjectAssignment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    return assignment is not None


def can_access_project(
    project: Project,
    current_user: CurrentUser,
    *,
    has_assignment: bool = False,
) -> bool:
    """Evaluate role-based project access without hitting the database."""
    if current_user.role == AppRole.SUPER_ADMIN:
        return True

    if project.org_id != current_user.org_id:
        return False

    if current_user.role in {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP}:
        return True

    if current_user.role == AppRole.CLIENT:
        return has_assignment

    return False


async def get_visible_project(session: AsyncSession, project_id: UUID, current_user: CurrentUser) -> Project:
    project = (
        await session.execute(
            _base_project_query().where(Project.id == project_id),
        )
    ).scalar_one_or_none()
    if project is None:
        raise ApiError(404, "NOT_FOUND", "Project was not found.", {"project_id": str(project_id)})

    has_assignment = False
    if current_user.role == AppRole.CLIENT:
        has_assignment = await _has_active_assignment(
            session,
            user_id=current_user.id,
            project_id=project_id,
        )

    if not can_access_project(project, current_user, has_assignment=has_assignment):
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    return project
