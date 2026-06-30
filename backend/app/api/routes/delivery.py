from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.delivery.services.recommendation_service import (
    fetch_recommendation_row,
    get_recommendation_for_mutation,
    group_recommendations_by_title,
    grouped_recommendation_to_read,
    list_project_recommendations,
    recommendation_row_to_read,
    validate_owner_assignment,
)
from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import (
    AlertStatus,
    AppRole,
    DeliveryConfidenceScore,
    MilestoneStatus,
    OwnerType,
    RecommendationStatus,
    RiskAlert,
    ThroughputSnapshot,
)
from app.schemas.common import DataResponse, ListResponse, ORMModel, Pagination
from app.schemas.domain import (
    GroupedMitigationRecommendationRead,
    MitigationRecommendationAssignOwner,
    MitigationRecommendationRead,
    OwnerOptionRead,
    ProjectRecommendationsResponse,
    RiskAlertRead,
    RiskAlertUpdate,
    ThroughputSnapshotCreate,
    ThroughputSnapshotRead,
)
from app.services.ingestion import upsert_throughput_snapshot
from app.services.scoping import get_visible_project

router = APIRouter(tags=["delivery"])


class DeliveryConfidenceScoreRead(ORMModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID
    score_pct: Decimal
    forecast_completion_date: date | None
    status: MilestoneStatus
    model_version: str | None
    created_at: datetime


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


@router.get(
    "/projects/{project_id}/delivery-confidence",
    response_model=ListResponse[DeliveryConfidenceScoreRead],
)
async def list_delivery_confidence(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    limit: LimitQuery = 100,
) -> ListResponse[DeliveryConfidenceScoreRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(DeliveryConfidenceScore)
            .where(DeliveryConfidenceScore.project_id == project.id)
            .order_by(DeliveryConfidenceScore.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return ListResponse(
        data=[DeliveryConfidenceScoreRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


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


@router.get("/projects/{project_id}/recommendations", response_model=ProjectRecommendationsResponse)
async def list_mitigation_recommendations(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> ProjectRecommendationsResponse:
    project = await get_visible_project(session, project_id, current_user)
    rows, owners = await list_project_recommendations(
        session,
        project_id=project.id,
        org_id=project.org_id,
    )
    grouped = group_recommendations_by_title(rows)
    return ProjectRecommendationsResponse(
        data=[
            GroupedMitigationRecommendationRead.model_validate(grouped_recommendation_to_read(group))
            for group in grouped
        ],
        assignable_owners=[
            OwnerOptionRead(
                owner_type=owner.owner_type.value,
                owner_id=owner.owner_id,
                label=owner.label,
            )
            for owner in owners
        ],
        pagination=Pagination(limit=100),
    )


@router.post("/recommendations/{recommendation_id}/accept", response_model=DataResponse[MitigationRecommendationRead])
async def accept_recommendation(
    recommendation_id: UUID,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[MitigationRecommendationRead]:
    recommendation = await get_recommendation_for_mutation(
        session,
        recommendation_id,
        org_id=current_user.org_id,
        is_super_admin=current_user.role == AppRole.SUPER_ADMIN,
    )
    if recommendation is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    if recommendation.status != RecommendationStatus.PENDING:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Only pending recommendations can be accepted.")

    recommendation.status = RecommendationStatus.ACCEPTED
    await session.flush()
    audit = AuditLogger(session)
    await audit.log(
        event_type="recommendation_accepted",
        org_id=recommendation.org_id,
        project_id=recommendation.project_id,
        payload={"recommendation_id": str(recommendation.id), "title": recommendation.title},
    )
    await session.commit()
    row = await fetch_recommendation_row(session, recommendation.id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    return DataResponse(data=MitigationRecommendationRead.model_validate(recommendation_row_to_read(row)))


@router.post("/recommendations/{recommendation_id}/reject", response_model=DataResponse[MitigationRecommendationRead])
async def reject_recommendation(
    recommendation_id: UUID,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[MitigationRecommendationRead]:
    recommendation = await get_recommendation_for_mutation(
        session,
        recommendation_id,
        org_id=current_user.org_id,
        is_super_admin=current_user.role == AppRole.SUPER_ADMIN,
    )
    if recommendation is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    if recommendation.status != RecommendationStatus.PENDING:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Only pending recommendations can be rejected.")

    recommendation.status = RecommendationStatus.REJECTED
    await session.flush()
    audit = AuditLogger(session)
    await audit.log(
        event_type="recommendation_rejected",
        org_id=recommendation.org_id,
        project_id=recommendation.project_id,
        payload={"recommendation_id": str(recommendation.id), "title": recommendation.title},
    )
    await session.commit()
    row = await fetch_recommendation_row(session, recommendation.id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    return DataResponse(data=MitigationRecommendationRead.model_validate(recommendation_row_to_read(row)))


@router.post(
    "/recommendations/{recommendation_id}/assign-owner",
    response_model=DataResponse[MitigationRecommendationRead],
)
async def assign_recommendation_owner(
    recommendation_id: UUID,
    payload: MitigationRecommendationAssignOwner,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[MitigationRecommendationRead]:
    recommendation = await get_recommendation_for_mutation(
        session,
        recommendation_id,
        org_id=current_user.org_id,
        is_super_admin=current_user.role == AppRole.SUPER_ADMIN,
    )
    if recommendation is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    if recommendation.status == RecommendationStatus.REJECTED:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Rejected recommendations cannot be reassigned.")

    owner_type = OwnerType(payload.owner_type) if payload.owner_type else None
    try:
        await validate_owner_assignment(
            session,
            project_id=recommendation.project_id,
            org_id=recommendation.org_id,
            owner_type=owner_type,
            owner_id=payload.owner_id,
        )
    except ValueError as exc:
        raise ApiError(400, "INVALID_OWNER", str(exc)) from exc

    recommendation.owner_type = owner_type
    recommendation.owner_id = payload.owner_id
    await session.flush()
    audit = AuditLogger(session)
    await audit.log(
        event_type="recommendation_owner_assigned",
        org_id=recommendation.org_id,
        project_id=recommendation.project_id,
        payload={
            "recommendation_id": str(recommendation.id),
            "owner_type": payload.owner_type,
            "owner_id": str(payload.owner_id) if payload.owner_id else None,
        },
    )
    await session.commit()
    row = await fetch_recommendation_row(session, recommendation.id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    return DataResponse(data=MitigationRecommendationRead.model_validate(recommendation_row_to_read(row)))
