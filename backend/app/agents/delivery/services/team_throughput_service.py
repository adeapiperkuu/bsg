"""Secure idempotent ingestion for daily team-throughput snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.delivery.schemas.operations import (
    TeamThroughputSnapshotCreate,
    TeamThroughputSnapshotUpdate,
)
from app.agents.delivery.services.bottleneck_service import (
    BottleneckDetectionResult,
    detect_project_bottlenecks,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    Project,
    Team,
    TeamThroughputSnapshot,
    TeamThroughputSourceType,
)


@dataclass(frozen=True, slots=True)
class TeamThroughputIngestResult:
    snapshot: TeamThroughputSnapshot
    created: bool
    corrected: bool
    detection: BottleneckDetectionResult | None


async def create_or_update_team_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: TeamThroughputSnapshotCreate,
) -> TeamThroughputIngestResult:
    """Upsert one logical daily snapshot and run downstream work only on change."""
    reporting_date = datetime.now(UTC).date()
    if payload.snapshot_date > reporting_date:
        raise ApiError(
            422,
            "FUTURE_SNAPSHOT_DATE",
            "Team throughput cannot be reported for a future UTC date.",
        )
    team = await _get_valid_team(
        session,
        project=project,
        team_id=payload.team_id,
    )
    # Serialize this logical upsert across app processes. The database uniqueness
    # constraint remains the final guard; this lock makes the common race idempotent
    # instead of surfacing an integrity error to one caller.
    lock_key = f"{project.org_id}:{project.id}:{team.id}:{payload.snapshot_date.isoformat()}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
    existing = (
        await session.execute(
            select(TeamThroughputSnapshot)
            .where(
                TeamThroughputSnapshot.org_id == project.org_id,
                TeamThroughputSnapshot.project_id == project.id,
                TeamThroughputSnapshot.team_id == team.id,
                TeamThroughputSnapshot.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing is not None and _same_snapshot_values(
        existing,
        units_completed=payload.units_completed,
        active_headcount=payload.active_headcount,
        source_reference=payload.source_reference,
        notes=payload.notes,
    ):
        return TeamThroughputIngestResult(
            snapshot=existing,
            created=False,
            corrected=False,
            detection=None,
        )

    audit = AuditLogger(session)
    if existing is None:
        snapshot = TeamThroughputSnapshot(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            team_id=team.id,
            snapshot_date=payload.snapshot_date,
            units_completed=payload.units_completed,
            active_headcount=payload.active_headcount,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(snapshot)
        created = True
        corrected = False
        await _audit_snapshot(
            audit,
            "team_throughput_snapshot_created",
            snapshot,
            actor_id=actor.id,
            previous=None,
        )
    else:
        previous = _snapshot_values(existing)
        existing.units_completed = payload.units_completed
        existing.active_headcount = payload.active_headcount
        existing.source_type = TeamThroughputSourceType.CORRECTION
        existing.source_reference = payload.source_reference
        existing.notes = payload.notes
        existing.updated_by = actor.id
        snapshot = existing
        created = False
        corrected = True
        await _audit_snapshot(
            audit,
            "team_throughput_snapshot_corrected",
            snapshot,
            actor_id=actor.id,
            previous=previous,
        )

    await session.flush()
    detection = await detect_project_bottlenecks(
        session,
        project=project,
        as_of_date=reporting_date,
        trigger_scoring=True,
        score_when_unchanged=True,
    )
    return TeamThroughputIngestResult(
        snapshot=snapshot,
        created=created,
        corrected=corrected,
        detection=detection,
    )


async def correct_team_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    snapshot: TeamThroughputSnapshot,
    actor: CurrentUser,
    payload: TeamThroughputSnapshotUpdate,
) -> TeamThroughputIngestResult:
    """Correct mutable values while preserving the logical snapshot identity."""
    if snapshot.project_id != project.id or snapshot.org_id != project.org_id:
        raise ApiError(404, "NOT_FOUND", "Team throughput snapshot was not found.")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return TeamThroughputIngestResult(snapshot, False, False, None)

    units_completed = changes.get("units_completed", snapshot.units_completed)
    active_headcount = changes.get("active_headcount", snapshot.active_headcount)
    source_reference = changes.get("source_reference", snapshot.source_reference)
    notes = changes.get("notes", snapshot.notes)
    if _same_snapshot_values(
        snapshot,
        units_completed=units_completed,
        active_headcount=active_headcount,
        source_reference=source_reference,
        notes=notes,
    ):
        return TeamThroughputIngestResult(snapshot, False, False, None)

    previous = _snapshot_values(snapshot)
    snapshot.units_completed = units_completed
    snapshot.active_headcount = active_headcount
    snapshot.source_type = TeamThroughputSourceType.CORRECTION
    snapshot.source_reference = source_reference
    snapshot.notes = notes
    snapshot.updated_by = actor.id
    await _audit_snapshot(
        AuditLogger(session),
        "team_throughput_snapshot_corrected",
        snapshot,
        actor_id=actor.id,
        previous=previous,
    )
    await session.flush()
    detection = await detect_project_bottlenecks(
        session,
        project=project,
        as_of_date=datetime.now(UTC).date(),
        trigger_scoring=True,
        score_when_unchanged=True,
    )
    return TeamThroughputIngestResult(snapshot, False, True, detection)


async def get_team_snapshot(
    session: AsyncSession,
    *,
    project_id: UUID,
    snapshot_id: UUID,
    for_update: bool = False,
) -> TeamThroughputSnapshot:
    query = select(TeamThroughputSnapshot).where(
        TeamThroughputSnapshot.id == snapshot_id,
        TeamThroughputSnapshot.project_id == project_id,
    )
    if for_update:
        query = query.with_for_update()
    snapshot = (await session.execute(query)).scalar_one_or_none()
    if snapshot is None:
        raise ApiError(404, "NOT_FOUND", "Team throughput snapshot was not found.")
    return snapshot


async def _get_valid_team(
    session: AsyncSession,
    *,
    project: Project,
    team_id: UUID,
) -> Team:
    team = (
        await session.execute(
            select(Team).where(
                Team.id == team_id,
                Team.project_id == project.id,
                Team.org_id == project.org_id,
                Team.is_active.is_(True),
                Team.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise ApiError(
            422,
            "TEAM_PROJECT_MISMATCH",
            "Team must be active and belong to the selected project and organisation.",
        )
    return team


def _same_snapshot_values(
    snapshot: TeamThroughputSnapshot,
    *,
    units_completed: int,
    active_headcount: int | None,
    source_reference: str | None,
    notes: str | None,
) -> bool:
    return (
        snapshot.units_completed == units_completed
        and snapshot.active_headcount == active_headcount
        and snapshot.source_reference == source_reference
        and snapshot.notes == notes
    )


def _snapshot_values(snapshot: TeamThroughputSnapshot) -> dict[str, object]:
    return {
        "units_completed": snapshot.units_completed,
        "active_headcount": snapshot.active_headcount,
        "source_type": snapshot.source_type.value,
        "source_reference": snapshot.source_reference,
        "notes": snapshot.notes,
    }


async def _audit_snapshot(
    audit: AuditLogger,
    event_type: str,
    snapshot: TeamThroughputSnapshot,
    *,
    actor_id: UUID,
    previous: dict[str, object] | None,
) -> None:
    await audit.log(
        event_type=event_type,
        org_id=snapshot.org_id,
        project_id=snapshot.project_id,
        payload={
            "snapshot_id": str(snapshot.id),
            "team_id": str(snapshot.team_id),
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "actor_id": str(actor_id),
            "previous": previous,
            "current": _snapshot_values(snapshot),
        },
    )
