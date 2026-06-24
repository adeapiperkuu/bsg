from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, QualityErrorEntry, QualitySnapshot, Team
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    QualityDashboardRead,
    QualityErrorEntryCreate,
    QualitySnapshotCreate,
    QualitySnapshotRead,
    QualitySnapshotUpdate,
    QualitySummaryRead,
)
from app.services.quality import (
    build_quality_dashboard,
    evaluate_snapshot,
    generate_quality_summary,
    load_snapshot_with_errors,
    scan_all_projects,
    upsert_quality_snapshot,
)
from app.services.scoping import get_visible_project

router = APIRouter(tags=["quality"])


@router.post("/internal/quality-scan", response_model=DataResponse[dict])
async def trigger_quality_scan(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[dict]:
    totals = await scan_all_projects(session)
    return DataResponse(data=totals)


async def _snapshot_to_read(session: SessionDep, snapshot: QualitySnapshot) -> QualitySnapshotRead:
    entries = (
        await session.execute(
            select(QualityErrorEntry).where(QualityErrorEntry.quality_snapshot_id == snapshot.id)
        )
    ).scalars()
    data = QualitySnapshotRead.model_validate(snapshot)
    data.error_entries = [entry for entry in entries]
    return data


@router.get("/projects/{project_id}/quality-dashboard", response_model=DataResponse[QualityDashboardRead])
async def get_quality_dashboard(
    project_id: UUID, session: SessionDep, current_user: UserDep
) -> DataResponse[QualityDashboardRead]:
    project = await get_visible_project(session, project_id, current_user)
    dashboard = await build_quality_dashboard(session, project, current_user)
    return DataResponse(data=dashboard)


@router.get("/projects/{project_id}/quality-snapshots", response_model=ListResponse[QualitySnapshotRead])
async def list_quality_snapshots(
    project_id: UUID, session: SessionDep, current_user: UserDep
) -> ListResponse[QualitySnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(QualitySnapshot)
            .where(QualitySnapshot.project_id == project.id)
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
        )
    ).scalars()
    data = [await _snapshot_to_read(session, row) for row in rows]
    return ListResponse(data=data, pagination=Pagination(limit=50))


@router.post("/projects/{project_id}/quality-snapshots", response_model=DataResponse[QualitySnapshotRead])
async def create_quality_snapshot(
    project_id: UUID,
    payload: QualitySnapshotCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[QualitySnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    team = (
        await session.execute(select(Team).where(Team.id == payload.team_id, Team.project_id == project.id))
    ).scalar_one_or_none()
    if team is None:
        raise ApiError(404, "NOT_FOUND", "Team was not found.")

    snapshot = await upsert_quality_snapshot(session, project, team, payload)
    await evaluate_snapshot(session, snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=await _snapshot_to_read(session, snapshot))


@router.get("/quality-snapshots/{snapshot_id}", response_model=DataResponse[QualitySnapshotRead])
async def get_quality_snapshot(
    snapshot_id: UUID, session: SessionDep, current_user: UserDep
) -> DataResponse[QualitySnapshotRead]:
    snapshot = await load_snapshot_with_errors(session, snapshot_id)
    if snapshot is None or (current_user.role != AppRole.SUPER_ADMIN and snapshot.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Quality snapshot was not found.")
    return DataResponse(data=await _snapshot_to_read(session, snapshot))


@router.patch("/quality-snapshots/{snapshot_id}", response_model=DataResponse[QualitySnapshotRead])
async def update_quality_snapshot(
    snapshot_id: UUID,
    payload: QualitySnapshotUpdate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[QualitySnapshotRead]:
    snapshot = await load_snapshot_with_errors(session, snapshot_id)
    if snapshot is None or (current_user.role != AppRole.SUPER_ADMIN and snapshot.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Quality snapshot was not found.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(snapshot, field, value)

    await evaluate_snapshot(session, snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=await _snapshot_to_read(session, snapshot))


@router.post("/quality-snapshots/{snapshot_id}/error-entries", response_model=DataResponse[QualitySnapshotRead])
async def add_error_entry(
    snapshot_id: UUID,
    payload: QualityErrorEntryCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[QualitySnapshotRead]:
    snapshot = await load_snapshot_with_errors(session, snapshot_id)
    if snapshot is None or (current_user.role != AppRole.SUPER_ADMIN and snapshot.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Quality snapshot was not found.")

    session.add(
        QualityErrorEntry(
            quality_snapshot_id=snapshot.id,
            org_id=snapshot.org_id,
            **payload.model_dump(),
        )
    )
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=await _snapshot_to_read(session, snapshot))


@router.get("/projects/{project_id}/quality-summary", response_model=DataResponse[QualitySummaryRead])
async def get_quality_summary(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    iso_year: int = Query(default=None),
    iso_week: int = Query(default=None),
) -> DataResponse[QualitySummaryRead]:
    from datetime import datetime, timezone
    project = await get_visible_project(session, project_id, current_user)
    if iso_year is None or iso_week is None:
        now = datetime.now(timezone.utc)
        cal = now.isocalendar()
        iso_year = cal[0]
        iso_week = cal[1]
    summary = await generate_quality_summary(session, project, iso_year, iso_week, current_user)
    return DataResponse(data=summary)
