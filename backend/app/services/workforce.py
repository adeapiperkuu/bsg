"""Workforce teams and annotators access control and mutations."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import Annotator, AppRole, Project, Team
from app.schemas.domain import AnnotatorCreate, AnnotatorUpdate, TeamCreate, TeamUpdate

WORKFORCE_WRITE_ROLES = frozenset({AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN})
ANNOTATOR_READ_ROLES = frozenset(
    {AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN},
)


def can_manage_workforce(current_user: CurrentUser) -> bool:
    return current_user.role in WORKFORCE_WRITE_ROLES


def can_read_annotators(current_user: CurrentUser) -> bool:
    return current_user.role in ANNOTATOR_READ_ROLES


def assert_can_manage_workforce(current_user: CurrentUser) -> None:
    if not can_manage_workforce(current_user):
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")


def assert_can_read_annotators(current_user: CurrentUser) -> None:
    if not can_read_annotators(current_user):
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")


def team_visible_to_user(team: Team, current_user: CurrentUser) -> bool:
    if current_user.role == AppRole.SUPER_ADMIN:
        return True
    if current_user.role == AppRole.BSG_LEADERSHIP:
        return True
    if current_user.role in {AppRole.DELIVERY_MANAGER, AppRole.CLIENT}:
        return team.org_id == current_user.org_id
    return False


def annotator_visible_to_user(annotator: Annotator, current_user: CurrentUser) -> bool:
    if not can_read_annotators(current_user):
        return False
    if current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        return True
    return annotator.org_id == current_user.org_id


async def get_team_or_404(
    session: AsyncSession,
    team_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> Team:
    team = (
        await session.execute(
            select(Team).where(Team.id == team_id, Team.deleted_at.is_(None)),
        )
    ).scalar_one_or_none()
    if team is None:
        raise ApiError(404, "NOT_FOUND", "Team was not found.", {"team_id": str(team_id)})

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and team.org_id != current_user.org_id:
            raise ApiError(404, "NOT_FOUND", "Team was not found.", {"team_id": str(team_id)})
        return team

    if not team_visible_to_user(team, current_user):
        if current_user.role == AppRole.CLIENT:
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
        raise ApiError(404, "NOT_FOUND", "Team was not found.", {"team_id": str(team_id)})
    return team


async def get_annotator_or_404(
    session: AsyncSession,
    annotator_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> Annotator:
    annotator = (
        await session.execute(
            select(Annotator).where(Annotator.id == annotator_id, Annotator.deleted_at.is_(None)),
        )
    ).scalar_one_or_none()
    if annotator is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Annotator was not found.",
            {"annotator_id": str(annotator_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and annotator.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Annotator was not found.",
                {"annotator_id": str(annotator_id)},
            )
        return annotator

    assert_can_read_annotators(current_user)
    if not annotator_visible_to_user(annotator, current_user):
        raise ApiError(
            404,
            "NOT_FOUND",
            "Annotator was not found.",
            {"annotator_id": str(annotator_id)},
        )
    return annotator


async def create_team(session: AsyncSession, project: Project, payload: TeamCreate) -> Team:
    team = Team(
        project_id=project.id,
        org_id=project.org_id,
        **payload.model_dump(),
    )
    session.add(team)
    await session.flush()
    return team


async def update_team(session: AsyncSession, team: Team, payload: TeamUpdate) -> Team:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(team, key, value)
    return team


async def soft_delete_team(session: AsyncSession, team: Team) -> None:
    team.deleted_at = datetime.now(timezone.utc)
    team.is_active = False


async def create_annotator(session: AsyncSession, team: Team, payload: AnnotatorCreate) -> Annotator:
    annotator = Annotator(
        team_id=team.id,
        org_id=team.org_id,
        **payload.model_dump(),
    )
    session.add(annotator)
    await session.flush()
    return annotator


async def update_annotator(
    session: AsyncSession,
    annotator: Annotator,
    payload: AnnotatorUpdate,
    *,
    current_user: CurrentUser,
) -> Annotator:
    data = payload.model_dump(exclude_unset=True)
    if "team_id" in data:
        new_team = await get_team_or_404(session, data["team_id"], current_user, for_mutation=True)
        if new_team.org_id != annotator.org_id:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "Annotator org_id must match the team org_id.",
            )
        data["team_id"] = new_team.id
    for key, value in data.items():
        setattr(annotator, key, value)
    return annotator


async def soft_delete_annotator(session: AsyncSession, annotator: Annotator) -> None:
    annotator.deleted_at = datetime.now(timezone.utc)
    annotator.is_active = False
