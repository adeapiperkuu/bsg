"""Validated idempotent ingestion for Phase 15.2 operational snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.delivery.schemas.operational_data import (
    AbsenteeismSnapshotCreate,
    BacklogQueueSnapshotCreate,
    CapacitySnapshotCreate,
    ReviewQueueSnapshotCreate,
    TeamAvailabilitySnapshotCreate,
    TimesheetEntryCreate,
)
from app.agents.delivery.services.dashboard_service import clear_delivery_portfolio_cache
from app.agents.delivery.services.delivery_root_cause_service import clear_root_cause_analytics_cache
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    DeliveryAbsenteeismSnapshot,
    DeliveryBacklogQueueSnapshot,
    DeliveryCapacitySnapshot,
    DeliveryReviewQueueSnapshot,
    DeliveryTeamAvailabilitySnapshot,
    DeliveryTimesheetEntry,
    OperationalDataSourceType,
    Project,
    Team,
)


@dataclass(frozen=True, slots=True)
class OperationalIngestResult:
    row: Any
    created: bool
    corrected: bool


def _reject_future_date(snapshot_date: date) -> None:
    today = datetime.now(UTC).date()
    if snapshot_date > today:
        raise ApiError(
            422,
            "FUTURE_SNAPSHOT_DATE",
            "Operational data cannot be reported for a future UTC date.",
        )


async def _lock_key(session: AsyncSession, key: str) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def _get_valid_team(session: AsyncSession, *, project: Project, team_id: UUID) -> Team:
    team = (
        await session.execute(
            select(Team).where(
                Team.id == team_id,
                Team.project_id == project.id,
                Team.org_id == project.org_id,
                Team.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise ApiError(404, "TEAM_NOT_FOUND", "Team was not found on this project.")
    return team


async def _audit(
    session: AsyncSession,
    *,
    event_type: str,
    project: Project,
    actor_id: UUID,
    payload: dict[str, Any],
) -> None:
    await AuditLogger(session).log(
        event_type=event_type,
        org_id=project.org_id,
        project_id=project.id,
        payload={"actor_id": str(actor_id), **payload},
    )


def _clear_caches(org_id: UUID) -> None:
    clear_delivery_portfolio_cache(org_id=org_id)
    clear_root_cause_analytics_cache(org_id=org_id)


async def upsert_timesheet_entry(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: TimesheetEntryCreate,
) -> OperationalIngestResult:
    _reject_future_date(payload.snapshot_date)
    team = await _get_valid_team(session, project=project, team_id=payload.team_id)
    lock = f"ts:{project.org_id}:{project.id}:{team.id}:{payload.snapshot_date.isoformat()}"
    await _lock_key(session, lock)
    existing = (
        await session.execute(
            select(DeliveryTimesheetEntry)
            .where(
                DeliveryTimesheetEntry.org_id == project.org_id,
                DeliveryTimesheetEntry.project_id == project.id,
                DeliveryTimesheetEntry.team_id == team.id,
                DeliveryTimesheetEntry.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and (
        existing.hours_logged == payload.hours_logged
        and existing.expected_hours == payload.expected_hours
        and existing.source_reference == payload.source_reference
        and existing.notes == payload.notes
    ):
        return OperationalIngestResult(row=existing, created=False, corrected=False)

    if existing is None:
        row = DeliveryTimesheetEntry(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            team_id=team.id,
            snapshot_date=payload.snapshot_date,
            hours_logged=payload.hours_logged,
            expected_hours=payload.expected_hours,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            event_type="operational_timesheet_created",
            project=project,
            actor_id=actor.id,
            payload={"id": str(row.id), "team_id": str(team.id)},
        )
        _clear_caches(project.org_id)
        return OperationalIngestResult(row=row, created=True, corrected=False)

    existing.hours_logged = payload.hours_logged
    existing.expected_hours = payload.expected_hours
    existing.source_type = OperationalDataSourceType.CORRECTION
    existing.source_reference = payload.source_reference
    existing.notes = payload.notes
    existing.updated_by = actor.id
    await session.flush()
    await _audit(
        session,
        event_type="operational_timesheet_corrected",
        project=project,
        actor_id=actor.id,
        payload={"id": str(existing.id), "team_id": str(team.id)},
    )
    _clear_caches(project.org_id)
    return OperationalIngestResult(row=existing, created=False, corrected=True)


async def upsert_absenteeism_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: AbsenteeismSnapshotCreate,
) -> OperationalIngestResult:
    _reject_future_date(payload.snapshot_date)
    rate = (payload.absent_fte / payload.planned_fte * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    await _lock_key(session, f"abs:{project.id}:{payload.snapshot_date.isoformat()}")
    existing = (
        await session.execute(
            select(DeliveryAbsenteeismSnapshot)
            .where(
                DeliveryAbsenteeismSnapshot.project_id == project.id,
                DeliveryAbsenteeismSnapshot.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and (
        existing.absent_fte == payload.absent_fte
        and existing.planned_fte == payload.planned_fte
        and existing.source_reference == payload.source_reference
        and existing.notes == payload.notes
    ):
        return OperationalIngestResult(row=existing, created=False, corrected=False)

    if existing is None:
        row = DeliveryAbsenteeismSnapshot(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            snapshot_date=payload.snapshot_date,
            absent_fte=payload.absent_fte,
            planned_fte=payload.planned_fte,
            absence_rate_pct=rate,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            event_type="operational_absenteeism_created",
            project=project,
            actor_id=actor.id,
            payload={"id": str(row.id), "absence_rate_pct": str(rate)},
        )
        _clear_caches(project.org_id)
        return OperationalIngestResult(row=row, created=True, corrected=False)

    existing.absent_fte = payload.absent_fte
    existing.planned_fte = payload.planned_fte
    existing.absence_rate_pct = rate
    existing.source_type = OperationalDataSourceType.CORRECTION
    existing.source_reference = payload.source_reference
    existing.notes = payload.notes
    existing.updated_by = actor.id
    await session.flush()
    await _audit(
        session,
        event_type="operational_absenteeism_corrected",
        project=project,
        actor_id=actor.id,
        payload={"id": str(existing.id)},
    )
    _clear_caches(project.org_id)
    return OperationalIngestResult(row=existing, created=False, corrected=True)


async def upsert_review_queue_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: ReviewQueueSnapshotCreate,
) -> OperationalIngestResult:
    _reject_future_date(payload.snapshot_date)
    await _lock_key(session, f"rev:{project.id}:{payload.snapshot_date.isoformat()}")
    existing = (
        await session.execute(
            select(DeliveryReviewQueueSnapshot)
            .where(
                DeliveryReviewQueueSnapshot.project_id == project.id,
                DeliveryReviewQueueSnapshot.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and (
        existing.pending_count == payload.pending_count
        and existing.avg_turnaround_hours == payload.avg_turnaround_hours
        and existing.sla_breach_count == payload.sla_breach_count
        and existing.source_reference == payload.source_reference
        and existing.notes == payload.notes
    ):
        return OperationalIngestResult(row=existing, created=False, corrected=False)

    if existing is None:
        row = DeliveryReviewQueueSnapshot(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            snapshot_date=payload.snapshot_date,
            pending_count=payload.pending_count,
            avg_turnaround_hours=payload.avg_turnaround_hours,
            sla_breach_count=payload.sla_breach_count,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            event_type="operational_review_queue_created",
            project=project,
            actor_id=actor.id,
            payload={"id": str(row.id)},
        )
        _clear_caches(project.org_id)
        return OperationalIngestResult(row=row, created=True, corrected=False)

    existing.pending_count = payload.pending_count
    existing.avg_turnaround_hours = payload.avg_turnaround_hours
    existing.sla_breach_count = payload.sla_breach_count
    existing.source_type = OperationalDataSourceType.CORRECTION
    existing.source_reference = payload.source_reference
    existing.notes = payload.notes
    existing.updated_by = actor.id
    await session.flush()
    await _audit(
        session,
        event_type="operational_review_queue_corrected",
        project=project,
        actor_id=actor.id,
        payload={"id": str(existing.id)},
    )
    _clear_caches(project.org_id)
    return OperationalIngestResult(row=existing, created=False, corrected=True)


async def upsert_backlog_queue_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: BacklogQueueSnapshotCreate,
) -> OperationalIngestResult:
    _reject_future_date(payload.snapshot_date)
    await _lock_key(session, f"bl:{project.id}:{payload.snapshot_date.isoformat()}")
    existing = (
        await session.execute(
            select(DeliveryBacklogQueueSnapshot)
            .where(
                DeliveryBacklogQueueSnapshot.project_id == project.id,
                DeliveryBacklogQueueSnapshot.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and (
        existing.item_count == payload.item_count
        and existing.aging_item_count == payload.aging_item_count
        and existing.oldest_item_age_days == payload.oldest_item_age_days
        and existing.source_reference == payload.source_reference
        and existing.notes == payload.notes
    ):
        return OperationalIngestResult(row=existing, created=False, corrected=False)

    if existing is None:
        row = DeliveryBacklogQueueSnapshot(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            snapshot_date=payload.snapshot_date,
            item_count=payload.item_count,
            aging_item_count=payload.aging_item_count,
            oldest_item_age_days=payload.oldest_item_age_days,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            event_type="operational_backlog_queue_created",
            project=project,
            actor_id=actor.id,
            payload={"id": str(row.id)},
        )
        _clear_caches(project.org_id)
        return OperationalIngestResult(row=row, created=True, corrected=False)

    existing.item_count = payload.item_count
    existing.aging_item_count = payload.aging_item_count
    existing.oldest_item_age_days = payload.oldest_item_age_days
    existing.source_type = OperationalDataSourceType.CORRECTION
    existing.source_reference = payload.source_reference
    existing.notes = payload.notes
    existing.updated_by = actor.id
    await session.flush()
    await _audit(
        session,
        event_type="operational_backlog_queue_corrected",
        project=project,
        actor_id=actor.id,
        payload={"id": str(existing.id)},
    )
    _clear_caches(project.org_id)
    return OperationalIngestResult(row=existing, created=False, corrected=True)


async def upsert_capacity_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: CapacitySnapshotCreate,
) -> OperationalIngestResult:
    _reject_future_date(payload.snapshot_date)
    await _lock_key(session, f"cap:{project.id}:{payload.snapshot_date.isoformat()}")
    existing = (
        await session.execute(
            select(DeliveryCapacitySnapshot)
            .where(
                DeliveryCapacitySnapshot.project_id == project.id,
                DeliveryCapacitySnapshot.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and (
        existing.planned_capacity_hours == payload.planned_capacity_hours
        and existing.available_capacity_hours == payload.available_capacity_hours
        and existing.source_reference == payload.source_reference
        and existing.notes == payload.notes
    ):
        return OperationalIngestResult(row=existing, created=False, corrected=False)

    if existing is None:
        row = DeliveryCapacitySnapshot(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            snapshot_date=payload.snapshot_date,
            planned_capacity_hours=payload.planned_capacity_hours,
            available_capacity_hours=payload.available_capacity_hours,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            event_type="operational_capacity_created",
            project=project,
            actor_id=actor.id,
            payload={"id": str(row.id)},
        )
        _clear_caches(project.org_id)
        return OperationalIngestResult(row=row, created=True, corrected=False)

    existing.planned_capacity_hours = payload.planned_capacity_hours
    existing.available_capacity_hours = payload.available_capacity_hours
    existing.source_type = OperationalDataSourceType.CORRECTION
    existing.source_reference = payload.source_reference
    existing.notes = payload.notes
    existing.updated_by = actor.id
    await session.flush()
    await _audit(
        session,
        event_type="operational_capacity_corrected",
        project=project,
        actor_id=actor.id,
        payload={"id": str(existing.id)},
    )
    _clear_caches(project.org_id)
    return OperationalIngestResult(row=existing, created=False, corrected=True)


async def upsert_team_availability_snapshot(
    session: AsyncSession,
    *,
    project: Project,
    actor: CurrentUser,
    payload: TeamAvailabilitySnapshotCreate,
) -> OperationalIngestResult:
    _reject_future_date(payload.snapshot_date)
    team = await _get_valid_team(session, project=project, team_id=payload.team_id)
    lock = f"avail:{project.org_id}:{project.id}:{team.id}:{payload.snapshot_date.isoformat()}"
    await _lock_key(session, lock)
    existing = (
        await session.execute(
            select(DeliveryTeamAvailabilitySnapshot)
            .where(
                DeliveryTeamAvailabilitySnapshot.org_id == project.org_id,
                DeliveryTeamAvailabilitySnapshot.project_id == project.id,
                DeliveryTeamAvailabilitySnapshot.team_id == team.id,
                DeliveryTeamAvailabilitySnapshot.snapshot_date == payload.snapshot_date,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and (
        existing.available_headcount == payload.available_headcount
        and existing.planned_headcount == payload.planned_headcount
        and existing.available_fte == payload.available_fte
        and existing.source_reference == payload.source_reference
        and existing.notes == payload.notes
    ):
        return OperationalIngestResult(row=existing, created=False, corrected=False)

    if existing is None:
        row = DeliveryTeamAvailabilitySnapshot(
            id=uuid4(),
            org_id=project.org_id,
            project_id=project.id,
            team_id=team.id,
            snapshot_date=payload.snapshot_date,
            available_headcount=payload.available_headcount,
            planned_headcount=payload.planned_headcount,
            available_fte=payload.available_fte,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            event_type="operational_team_availability_created",
            project=project,
            actor_id=actor.id,
            payload={"id": str(row.id), "team_id": str(team.id)},
        )
        _clear_caches(project.org_id)
        return OperationalIngestResult(row=row, created=True, corrected=False)

    existing.available_headcount = payload.available_headcount
    existing.planned_headcount = payload.planned_headcount
    existing.available_fte = payload.available_fte
    existing.source_type = OperationalDataSourceType.CORRECTION
    existing.source_reference = payload.source_reference
    existing.notes = payload.notes
    existing.updated_by = actor.id
    await session.flush()
    await _audit(
        session,
        event_type="operational_team_availability_corrected",
        project=project,
        actor_id=actor.id,
        payload={"id": str(existing.id), "team_id": str(team.id)},
    )
    _clear_caches(project.org_id)
    return OperationalIngestResult(row=existing, created=False, corrected=True)
