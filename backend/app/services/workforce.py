"""Workforce teams and annotators access control and mutations."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import Annotator, AppRole, Project, Team, UtilizationSnapshot
from app.schemas.domain import (
    AnnotatorCreate,
    AnnotatorRead,
    AnnotatorUpdate,
    ProjectWorkforceSummaryRead,
    TeamCreate,
    TeamRead,
    TeamUpdate,
    UtilizationSnapshotCreate,
    UtilizationSnapshotUpdate,
)

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


async def get_project_workforce_summary(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    teams_limit: int = 100,
) -> ProjectWorkforceSummaryRead:
    """Return project teams and annotators in one query batch (matches per-team list limits)."""
    team_rows = (
        await session.execute(
            select(Team)
            .where(Team.project_id == project.id, Team.deleted_at.is_(None))
            .order_by(Team.name)
            .limit(teams_limit),
        )
    ).scalars()
    teams = list(team_rows)

    annotators: list[Annotator] = []
    if teams:
        annotator_limit = len(teams) * 100
        annotator_rows = (
            await session.execute(
                select(Annotator)
                .where(
                    Annotator.team_id.in_([team.id for team in teams]),
                    Annotator.deleted_at.is_(None),
                )
                .order_by(Annotator.full_name)
                .limit(annotator_limit),
            )
        ).scalars()
        annotators = list(annotator_rows)

    return ProjectWorkforceSummaryRead(
        project_id=project.id,
        teams=[TeamRead.model_validate(team) for team in teams],
        annotators=[AnnotatorRead.model_validate(annotator) for annotator in annotators],
    )


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


def can_read_utilization(current_user: CurrentUser) -> bool:
    return can_read_annotators(current_user)


def assert_can_read_utilization(current_user: CurrentUser) -> None:
    assert_can_read_annotators(current_user)


def utilization_visible_to_user(snapshot: UtilizationSnapshot, current_user: CurrentUser) -> bool:
    if not can_read_utilization(current_user):
        return False
    if current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        return True
    return snapshot.org_id == current_user.org_id


def resolve_utilization_pct(
    allocated_hours: Decimal,
    available_hours: Decimal,
    utilization_pct: Decimal | None,
) -> Decimal:
    if utilization_pct is not None:
        return utilization_pct
    if available_hours == 0:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "utilization_pct is required when available_hours is 0.",
        )
    return (allocated_hours / available_hours * Decimal("100")).quantize(Decimal("0.01"))


async def resolve_utilization_team(
    session: AsyncSession,
    project: Project,
    team_id: UUID | None,
    current_user: CurrentUser,
    *,
    for_mutation: bool,
) -> Team | None:
    if team_id is None:
        return None
    team = await get_team_or_404(session, team_id, current_user, for_mutation=for_mutation)
    if team.project_id != project.id or team.org_id != project.org_id:
        raise ApiError(404, "NOT_FOUND", "Team was not found.", {"team_id": str(team_id)})
    return team


async def resolve_utilization_annotator(
    session: AsyncSession,
    team: Team | None,
    annotator_id: UUID | None,
    current_user: CurrentUser,
    *,
    for_mutation: bool,
) -> Annotator | None:
    if annotator_id is None:
        return None
    if team is None:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "team_id is required when annotator_id is provided.",
        )
    annotator = await get_annotator_or_404(
        session,
        annotator_id,
        current_user,
        for_mutation=for_mutation,
    )
    if annotator.team_id != team.id or annotator.org_id != team.org_id:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Annotator was not found.",
            {"annotator_id": str(annotator_id)},
        )
    return annotator


async def get_utilization_snapshot_or_404(
    session: AsyncSession,
    snapshot_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> UtilizationSnapshot:
    snapshot = (
        await session.execute(
            select(UtilizationSnapshot).where(
                UtilizationSnapshot.id == snapshot_id,
                UtilizationSnapshot.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Utilization snapshot was not found.",
            {"snapshot_id": str(snapshot_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and snapshot.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Utilization snapshot was not found.",
                {"snapshot_id": str(snapshot_id)},
            )
        return snapshot

    assert_can_read_utilization(current_user)
    if not utilization_visible_to_user(snapshot, current_user):
        raise ApiError(
            404,
            "NOT_FOUND",
            "Utilization snapshot was not found.",
            {"snapshot_id": str(snapshot_id)},
        )
    return snapshot


async def create_utilization_snapshot(
    session: AsyncSession,
    project: Project,
    payload: UtilizationSnapshotCreate,
    current_user: CurrentUser,
) -> UtilizationSnapshot:
    team = await resolve_utilization_team(
        session,
        project,
        payload.team_id,
        current_user,
        for_mutation=True,
    )
    await resolve_utilization_annotator(
        session,
        team,
        payload.annotator_id,
        current_user,
        for_mutation=True,
    )
    utilization_pct = resolve_utilization_pct(
        payload.allocated_hours,
        payload.available_hours,
        payload.utilization_pct,
    )
    snapshot = UtilizationSnapshot(
        org_id=project.org_id,
        project_id=project.id,
        team_id=payload.team_id,
        annotator_id=payload.annotator_id,
        snapshot_date=payload.snapshot_date,
        allocated_hours=payload.allocated_hours,
        available_hours=payload.available_hours,
        utilization_pct=utilization_pct,
        billable_hours=payload.billable_hours,
        non_billable_hours=payload.non_billable_hours,
        notes=payload.notes,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def update_utilization_snapshot(
    session: AsyncSession,
    snapshot: UtilizationSnapshot,
    payload: UtilizationSnapshotUpdate,
    current_user: CurrentUser,
) -> UtilizationSnapshot:
    data = payload.model_dump(exclude_unset=True)
    explicit_pct = data.pop("utilization_pct", None)

    project = (
        await session.execute(select(Project).where(Project.id == snapshot.project_id))
    ).scalar_one_or_none()
    if project is None:
        raise ApiError(404, "NOT_FOUND", "Project was not found.")

    next_team_id = data["team_id"] if "team_id" in data else snapshot.team_id
    next_annotator_id = data["annotator_id"] if "annotator_id" in data else snapshot.annotator_id

    if next_annotator_id is not None and next_team_id is None:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "team_id is required when annotator_id is provided.",
        )

    team = await resolve_utilization_team(
        session,
        project,
        next_team_id,
        current_user,
        for_mutation=True,
    )
    await resolve_utilization_annotator(
        session,
        team,
        next_annotator_id,
        current_user,
        for_mutation=True,
    )

    for key, value in data.items():
        setattr(snapshot, key, value)

    if explicit_pct is not None:
        snapshot.utilization_pct = explicit_pct
    elif "allocated_hours" in data or "available_hours" in data:
        snapshot.utilization_pct = resolve_utilization_pct(
            snapshot.allocated_hours,
            snapshot.available_hours,
            None,
        )

    return snapshot


async def soft_delete_utilization_snapshot(session: AsyncSession, snapshot: UtilizationSnapshot) -> None:
    snapshot.deleted_at = datetime.now(timezone.utc)
