from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, UtilizationSnapshot
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    UtilizationSnapshotCreate,
    UtilizationSnapshotRead,
    UtilizationSnapshotUpdate,
)
from app.services.scoping import get_visible_project
from app.services.workforce import (
    create_utilization_snapshot,
    get_utilization_snapshot_or_404,
    soft_delete_utilization_snapshot,
    update_utilization_snapshot,
)

router = APIRouter()


@router.get("/projects/{project_id}/utilization", response_model=ListResponse[UtilizationSnapshotRead])
async def list_utilization_snapshots(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    team_id: UUID | None = None,
    annotator_id: UUID | None = None,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: LimitQuery = 100,
) -> ListResponse[UtilizationSnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    query = (
        select(UtilizationSnapshot)
        .where(
            UtilizationSnapshot.project_id == project.id,
            UtilizationSnapshot.deleted_at.is_(None),
        )
        .order_by(UtilizationSnapshot.snapshot_date.desc())
        .limit(limit)
    )
    if team_id is not None:
        query = query.where(UtilizationSnapshot.team_id == team_id)
    if annotator_id is not None:
        query = query.where(UtilizationSnapshot.annotator_id == annotator_id)
    if from_date is not None:
        query = query.where(UtilizationSnapshot.snapshot_date >= from_date)
    if to_date is not None:
        query = query.where(UtilizationSnapshot.snapshot_date <= to_date)
    rows = (await session.execute(query)).scalars()
    return ListResponse(
        data=[UtilizationSnapshotRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/projects/{project_id}/utilization", response_model=DataResponse[UtilizationSnapshotRead])
async def create_utilization_snapshot_route(
    project_id: UUID,
    payload: UtilizationSnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[UtilizationSnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    snapshot = await create_utilization_snapshot(session, project, payload, current_user)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=UtilizationSnapshotRead.model_validate(snapshot))


@router.patch("/utilization/{snapshot_id}", response_model=DataResponse[UtilizationSnapshotRead])
async def update_utilization_snapshot_route(
    snapshot_id: UUID,
    payload: UtilizationSnapshotUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[UtilizationSnapshotRead]:
    snapshot = await get_utilization_snapshot_or_404(
        session,
        snapshot_id,
        current_user,
        for_mutation=True,
    )
    snapshot = await update_utilization_snapshot(session, snapshot, payload, current_user)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=UtilizationSnapshotRead.model_validate(snapshot))


@router.delete("/utilization/{snapshot_id}", status_code=204)
async def delete_utilization_snapshot_route(
    snapshot_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    snapshot = await get_utilization_snapshot_or_404(
        session,
        snapshot_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_utilization_snapshot(session, snapshot)
    await session.commit()
    return Response(status_code=204)
