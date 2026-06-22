from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, QualityErrorEntry, QualitySnapshot, Team
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import QualitySnapshotCreate, QualitySnapshotRead
from app.services.scoping import get_visible_project

router = APIRouter(tags=["quality"])


@router.get("/projects/{project_id}/quality-snapshots", response_model=ListResponse[QualitySnapshotRead])
async def list_quality_snapshots(project_id: UUID, session: SessionDep, current_user: UserDep) -> ListResponse[QualitySnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(QualitySnapshot)
            .where(QualitySnapshot.project_id == project.id)
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
        )
    ).scalars()
    return ListResponse(data=[QualitySnapshotRead.model_validate(row) for row in rows], pagination=Pagination(limit=50))


@router.post("/projects/{project_id}/quality-snapshots", response_model=DataResponse[QualitySnapshotRead])
async def create_quality_snapshot(
    project_id: UUID,
    payload: QualitySnapshotCreate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[QualitySnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    team = (
        await session.execute(select(Team).where(Team.id == payload.team_id, Team.project_id == project.id))
    ).scalar_one_or_none()
    if team is None:
        raise ApiError(404, "NOT_FOUND", "Team was not found.")

    snapshot = QualitySnapshot(
        project_id=project.id,
        team_id=team.id,
        org_id=project.org_id,
        iso_year=payload.iso_year,
        iso_week=payload.iso_week,
        gold_set_accuracy_pct=payload.gold_set_accuracy_pct,
        iaa_krippendorff_alpha=payload.iaa_krippendorff_alpha,
        rework_rate_pct=payload.rework_rate_pct,
    )
    session.add(snapshot)
    await session.flush()
    for entry in payload.error_entries:
        session.add(
            QualityErrorEntry(
                quality_snapshot_id=snapshot.id,
                org_id=project.org_id,
                **entry.model_dump(),
            )
        )
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=QualitySnapshotRead.model_validate(snapshot))


@router.get("/quality-snapshots/{snapshot_id}", response_model=DataResponse[QualitySnapshotRead])
async def get_quality_snapshot(snapshot_id: UUID, session: SessionDep, current_user: UserDep) -> DataResponse[QualitySnapshotRead]:
    snapshot = (await session.execute(select(QualitySnapshot).where(QualitySnapshot.id == snapshot_id))).scalar_one_or_none()
    if snapshot is None or (current_user.role != AppRole.SUPER_ADMIN and snapshot.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Quality snapshot was not found.")
    return DataResponse(data=QualitySnapshotRead.model_validate(snapshot))
