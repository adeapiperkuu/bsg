from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AlertStatus, AppRole, DeliveryConfidenceScore, RiskAlert, ThroughputSnapshot
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import RiskAlertRead, RiskAlertUpdate, ThroughputSnapshotCreate, ThroughputSnapshotRead
from app.services.ingestion import upsert_throughput_snapshot
from app.services.scoping import get_visible_project

router = APIRouter(tags=["delivery"])


@router.get("/projects/{project_id}/throughput", response_model=ListResponse[ThroughputSnapshotRead])
async def list_throughput(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    limit: LimitQuery = 100,
) -> ListResponse[ThroughputSnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(ThroughputSnapshot)
            .where(ThroughputSnapshot.project_id == project.id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(limit)
        )
    ).scalars()
    return ListResponse(data=[ThroughputSnapshotRead.model_validate(row) for row in rows], pagination=Pagination(limit=limit))


@router.post("/projects/{project_id}/throughput", response_model=DataResponse[ThroughputSnapshotRead])
async def create_throughput(
    project_id: UUID,
    payload: ThroughputSnapshotCreate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ThroughputSnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    snapshot = await upsert_throughput_snapshot(session, project, payload)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=ThroughputSnapshotRead.model_validate(snapshot))


@router.get("/projects/{project_id}/delivery-confidence")
async def list_delivery_confidence(project_id: UUID, session: SessionDep, current_user: UserDep, limit: LimitQuery = 100):
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(DeliveryConfidenceScore)
            .where(DeliveryConfidenceScore.project_id == project.id)
            .order_by(DeliveryConfidenceScore.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return {
        "data": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "milestone_id": str(row.milestone_id),
                "score_pct": str(row.score_pct),
                "forecast_completion_date": row.forecast_completion_date,
                "status": row.status,
                "model_version": row.model_version,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "pagination": {"limit": limit, "next_cursor": None},
    }


@router.get("/projects/{project_id}/risk-alerts", response_model=ListResponse[RiskAlertRead])
async def list_risk_alerts(project_id: UUID, session: SessionDep, current_user: UserDep) -> ListResponse[RiskAlertRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(RiskAlert)
            .where(RiskAlert.project_id == project.id, RiskAlert.deleted_at.is_(None))
            .order_by(RiskAlert.created_at.desc())
        )
    ).scalars()
    return ListResponse(data=[RiskAlertRead.model_validate(row) for row in rows], pagination=Pagination(limit=50))


@router.patch("/risk-alerts/{alert_id}", response_model=DataResponse[RiskAlertRead])
async def update_risk_alert(
    alert_id: UUID,
    payload: RiskAlertUpdate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[RiskAlertRead]:
    alert = (await session.execute(select(RiskAlert).where(RiskAlert.id == alert_id))).scalar_one_or_none()
    if alert is None or (current_user.role != AppRole.SUPER_ADMIN and alert.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Risk alert was not found.")
    if alert.status in {AlertStatus.RESOLVED, AlertStatus.DISMISSED}:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Risk alert is already closed.")
    alert.status = payload.status
    if payload.status == AlertStatus.RESOLVED:
        alert.resolved_at = datetime.now(timezone.utc)
        alert.resolved_by = current_user.id
    await session.commit()
    await session.refresh(alert)
    return DataResponse(data=RiskAlertRead.model_validate(alert))
