from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.delivery.schemas.operations import (
    BottleneckAcknowledgeRequest,
    BottleneckDetectionRunResponse,
    BottleneckResolveRequest,
    BottleneckResponse,
    TeamThroughputSnapshotCreate,
    TeamThroughputSnapshotResponse,
    TeamThroughputSnapshotUpdate,
)
from app.agents.delivery.schemas.root_cause import (
    ProjectRootCausesResponse,
    RootCauseAnalyticsResponse,
    RootCauseRecalculateResponse,
    RootCauseSnapshotRead,
    RootCauseTrendsResponse,
)
from app.agents.delivery.schemas.operational_data import (
    AbsenteeismSnapshotCreate,
    AbsenteeismSnapshotResponse,
    BacklogQueueSnapshotCreate,
    BacklogQueueSnapshotResponse,
    CapacitySnapshotCreate,
    CapacitySnapshotResponse,
    ReviewQueueSnapshotCreate,
    ReviewQueueSnapshotResponse,
    TeamAvailabilitySnapshotCreate,
    TeamAvailabilitySnapshotResponse,
    TimesheetEntryCreate,
    TimesheetEntryResponse,
)
from app.agents.delivery.schemas.pm_actions import (
    PmDailyActionCompleteRequest,
    PmDailyActionGenerateRequest,
    PmDailyActionRead,
    PmDailyActionsResponse,
)
from app.agents.delivery.schemas.operational_briefing import (
    OperationalBriefingGenerateRequest,
    OperationalBriefingSchema,
)
from app.agents.delivery.schemas.knowledge_evidence import KnowledgeEvidenceResponse
from app.agents.delivery.services.bottleneck_service import (
    acknowledge_bottleneck,
    detect_project_bottlenecks,
    get_project_bottleneck,
    resolve_bottleneck,
)
from app.agents.delivery.services.dashboard_service import clear_delivery_portfolio_cache
from app.agents.delivery.services.delivery_root_cause_service import (
    get_org_root_cause_analytics,
    get_project_root_causes,
    get_root_cause_trends,
    recalculate_root_causes,
)
from app.agents.delivery.services.operational_ingestion_service import (
    upsert_absenteeism_snapshot,
    upsert_backlog_queue_snapshot,
    upsert_capacity_snapshot,
    upsert_review_queue_snapshot,
    upsert_team_availability_snapshot,
    upsert_timesheet_entry,
)
from app.agents.delivery.services.pm_daily_action_service import (
    action_to_payload,
    complete_daily_action,
    generate_daily_actions,
    list_daily_actions,
)
from app.agents.delivery.services.operational_briefing_service import (
    build_project_operational_briefing,
)
from app.agents.delivery.services.delivery_knowledge_evidence_service import (
    retrieve_delivery_knowledge_evidence,
)
from app.agents.delivery.services.recommendation_service import (
    fetch_recommendation_row,
    get_recommendation_for_mutation,
    group_recommendations_by_title,
    grouped_recommendation_to_read,
    list_project_recommendations,
    recommendation_row_to_read,
    validate_owner_assignment,
)
from app.agents.delivery.services.team_throughput_service import (
    correct_team_snapshot,
    create_or_update_team_snapshot,
    get_team_snapshot,
)
from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
from app.db.models import (
    AlertStatus,
    AppRole,
    Bottleneck,
    DeliveryAbsenteeismSnapshot,
    DeliveryBacklogQueueSnapshot,
    DeliveryCapacitySnapshot,
    DeliveryConfidenceScore,
    DeliveryReviewQueueSnapshot,
    DeliveryTeamAvailabilitySnapshot,
    DeliveryTimesheetEntry,
    MilestoneStatus,
    OwnerType,
    PmDailyActionStatus,
    RecommendationStatus,
    RiskAlert,
    RiskTier,
    TeamThroughputSnapshot,
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
InternalDeliveryUser = Depends(
    require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
)
DeliveryOperator = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN))


class DeliveryConfidenceScoreRead(ORMModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID
    score_pct: Decimal
    forecast_completion_date: date | None
    status: MilestoneStatus
    model_version: str | None
    created_at: datetime


def _team_snapshot_response(
    snapshot: TeamThroughputSnapshot,
    *,
    corrected: bool = False,
    detection_changed: bool = False,
    scoring_status: str | None = None,
    scoring_error: str | None = None,
) -> TeamThroughputSnapshotResponse:
    response = TeamThroughputSnapshotResponse.model_validate(snapshot)
    response.corrected = corrected
    response.detection_changed = detection_changed
    response.scoring_status = scoring_status
    response.scoring_error = scoring_error
    return response


@router.get(
    "/projects/{project_id}/team-throughput",
    response_model=ListResponse[TeamThroughputSnapshotResponse],
)
async def list_team_throughput(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    team_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[TeamThroughputSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ApiError(422, "INVALID_DATE_RANGE", "date_from must be on or before date_to.")
    query = select(TeamThroughputSnapshot).where(
        TeamThroughputSnapshot.org_id == project.org_id,
        TeamThroughputSnapshot.project_id == project.id,
    )
    if team_id is not None:
        query = query.where(TeamThroughputSnapshot.team_id == team_id)
    if date_from is not None:
        query = query.where(TeamThroughputSnapshot.snapshot_date >= date_from)
    if date_to is not None:
        query = query.where(TeamThroughputSnapshot.snapshot_date <= date_to)
    rows = (
        await session.execute(
            query.order_by(
                TeamThroughputSnapshot.snapshot_date.desc(),
                TeamThroughputSnapshot.team_id,
            )
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    data = [_team_snapshot_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(
            limit=limit,
            offset=offset,
            items=len(data),
            has_more=len(data) == limit,
        ),
    )


@router.post(
    "/projects/{project_id}/team-throughput",
    response_model=DataResponse[TeamThroughputSnapshotResponse],
)
async def create_team_throughput(
    project_id: UUID,
    payload: TeamThroughputSnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[TeamThroughputSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await create_or_update_team_snapshot(
        session,
        project=project,
        actor=current_user,
        payload=payload,
    )
    await session.commit()
    if result.created or result.corrected:
        clear_delivery_portfolio_cache(org_id=project.org_id)
    await session.refresh(result.snapshot)
    scoring = result.detection.scoring if result.detection is not None else None
    return DataResponse(
        data=_team_snapshot_response(
            result.snapshot,
            corrected=result.corrected,
            detection_changed=result.detection.changed if result.detection else False,
            scoring_status=scoring.scoring_status if scoring else None,
            scoring_error=scoring.scoring_error if scoring else None,
        )
    )


@router.get(
    "/projects/{project_id}/team-throughput/{snapshot_id}",
    response_model=DataResponse[TeamThroughputSnapshotResponse],
)
async def get_team_throughput(
    project_id: UUID,
    snapshot_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
) -> DataResponse[TeamThroughputSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    snapshot = await get_team_snapshot(
        session,
        project_id=project.id,
        snapshot_id=snapshot_id,
    )
    return DataResponse(data=_team_snapshot_response(snapshot))


@router.patch(
    "/projects/{project_id}/team-throughput/{snapshot_id}",
    response_model=DataResponse[TeamThroughputSnapshotResponse],
)
async def update_team_throughput(
    project_id: UUID,
    snapshot_id: UUID,
    payload: TeamThroughputSnapshotUpdate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[TeamThroughputSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    snapshot = await get_team_snapshot(
        session,
        project_id=project.id,
        snapshot_id=snapshot_id,
        for_update=True,
    )
    result = await correct_team_snapshot(
        session,
        project=project,
        snapshot=snapshot,
        actor=current_user,
        payload=payload,
    )
    await session.commit()
    if result.corrected:
        clear_delivery_portfolio_cache(org_id=project.org_id)
    await session.refresh(result.snapshot)
    scoring = result.detection.scoring if result.detection is not None else None
    return DataResponse(
        data=_team_snapshot_response(
            result.snapshot,
            corrected=result.corrected,
            detection_changed=result.detection.changed if result.detection else False,
            scoring_status=scoring.scoring_status if scoring else None,
            scoring_error=scoring.scoring_error if scoring else None,
        )
    )


@router.get(
    "/projects/{project_id}/bottlenecks",
    response_model=ListResponse[BottleneckResponse],
)
async def list_bottlenecks(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    status: AlertStatus | None = None,
    severity: RiskTier | None = None,
    team_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[BottleneckResponse]:
    project = await get_visible_project(session, project_id, current_user)
    query = select(Bottleneck).where(
        Bottleneck.org_id == project.org_id,
        Bottleneck.project_id == project.id,
        Bottleneck.deleted_at.is_(None),
    )
    if status is not None:
        query = query.where(Bottleneck.status == status)
    if severity is not None:
        query = query.where(Bottleneck.severity == severity)
    if team_id is not None:
        query = query.where(Bottleneck.team_id == team_id)
    if created_from is not None:
        query = query.where(Bottleneck.created_at >= created_from)
    if created_to is not None:
        query = query.where(Bottleneck.created_at <= created_to)
    rows = (
        await session.execute(
            query.order_by(Bottleneck.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars()
    data = [BottleneckResponse.model_validate(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(
            limit=limit,
            offset=offset,
            items=len(data),
            has_more=len(data) == limit,
        ),
    )


@router.get(
    "/projects/{project_id}/bottlenecks/{bottleneck_id}",
    response_model=DataResponse[BottleneckResponse],
)
async def get_bottleneck(
    project_id: UUID,
    bottleneck_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
) -> DataResponse[BottleneckResponse]:
    project = await get_visible_project(session, project_id, current_user)
    bottleneck = await get_project_bottleneck(
        session,
        project_id=project.id,
        bottleneck_id=bottleneck_id,
    )
    return DataResponse(data=BottleneckResponse.model_validate(bottleneck))


@router.post(
    "/projects/{project_id}/bottlenecks/{bottleneck_id}/acknowledge",
    response_model=DataResponse[BottleneckResponse],
)
async def acknowledge_project_bottleneck(
    project_id: UUID,
    bottleneck_id: UUID,
    payload: BottleneckAcknowledgeRequest,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[BottleneckResponse]:
    project = await get_visible_project(session, project_id, current_user)
    bottleneck = await get_project_bottleneck(
        session,
        project_id=project.id,
        bottleneck_id=bottleneck_id,
        for_update=True,
    )
    changed = await acknowledge_bottleneck(
        session,
        bottleneck=bottleneck,
        actor=current_user,
        note=payload.note,
    )
    await session.commit()
    if changed:
        clear_delivery_portfolio_cache(org_id=project.org_id)
    await session.refresh(bottleneck)
    return DataResponse(data=BottleneckResponse.model_validate(bottleneck))


@router.post(
    "/projects/{project_id}/bottlenecks/{bottleneck_id}/resolve",
    response_model=DataResponse[BottleneckResponse],
)
async def resolve_project_bottleneck(
    project_id: UUID,
    bottleneck_id: UUID,
    payload: BottleneckResolveRequest,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[BottleneckResponse]:
    project = await get_visible_project(session, project_id, current_user)
    bottleneck = await get_project_bottleneck(
        session,
        project_id=project.id,
        bottleneck_id=bottleneck_id,
        for_update=True,
    )
    changed, _ = await resolve_bottleneck(
        session,
        project=project,
        bottleneck=bottleneck,
        actor=current_user,
        reason=payload.reason,
    )
    await session.commit()
    if changed:
        clear_delivery_portfolio_cache(org_id=project.org_id)
    await session.refresh(bottleneck)
    return DataResponse(data=BottleneckResponse.model_validate(bottleneck))


@router.post(
    "/projects/{project_id}/bottlenecks/detect",
    response_model=DataResponse[BottleneckDetectionRunResponse],
)
async def detect_project_bottlenecks_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[BottleneckDetectionRunResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await detect_project_bottlenecks(session, project=project)
    await session.commit()
    if result.changed:
        clear_delivery_portfolio_cache(org_id=project.org_id)
    return DataResponse(
        data=BottleneckDetectionRunResponse(
            project_id=project.id,
            evaluated_teams=result.analysis.evaluated_teams,
            valid_observation_days=result.analysis.valid_observation_days,
            signals_detected=len(result.analysis.signals),
            created=result.created,
            updated=result.updated,
            resolved=result.resolved,
            reopened=result.reopened,
            skipped_reasons=[item.reason for item in result.analysis.skipped_reasons],
            scoring_status=result.scoring.scoring_status if result.scoring else None,
            scoring_error=result.scoring.scoring_error if result.scoring else None,
        )
    )


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
    ingest_result = await upsert_throughput_snapshot(session, project, payload)
    await session.commit()
    # Post-commit so a rolled-back write cannot evict still-valid cached reads.
    clear_delivery_portfolio_cache(org_id=project.org_id)
    await session.refresh(ingest_result.snapshot)
    response = ThroughputSnapshotRead.model_validate(ingest_result.snapshot)
    response.scoring_status = ingest_result.scoring_status
    response.scoring_error = ingest_result.scoring_error
    return DataResponse(data=response)


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
async def list_risk_alerts(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    limit: LimitQuery = 50,
) -> ListResponse[RiskAlertRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(RiskAlert)
            .where(RiskAlert.project_id == project.id, RiskAlert.deleted_at.is_(None))
            .order_by(RiskAlert.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return ListResponse(data=[RiskAlertRead.model_validate(row) for row in rows], pagination=Pagination(limit=limit))


@router.patch("/risk-alerts/{alert_id}", response_model=DataResponse[RiskAlertRead])
async def update_risk_alert(
    alert_id: UUID,
    payload: RiskAlertUpdate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[RiskAlertRead]:
    alert = (await session.execute(select(RiskAlert).where(RiskAlert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise ApiError(404, "NOT_FOUND", "Risk alert was not found.")
    try:
        await get_visible_project(session, alert.project_id, current_user)
    except ApiError as exc:
        # Only DELIVERY_MANAGER/SUPER_ADMIN can reach this route (require_role above), so
        # get_visible_project's org-scoping is equivalent to the prior manual org_id check —
        # normalized to 404 (not 403) to avoid confirming a cross-org alert's existence.
        if exc.status_code in (403, 404):
            raise ApiError(404, "NOT_FOUND", "Risk alert was not found.") from exc
        raise
    if alert.status in {AlertStatus.RESOLVED, AlertStatus.DISMISSED}:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Risk alert is already closed.")
    alert.status = payload.status
    if payload.status == AlertStatus.RESOLVED:
        alert.resolved_at = datetime.now(timezone.utc)
        alert.resolved_by = current_user.id
    await session.commit()
    # Open-risk lists feed the cached delivery portfolio payload.
    clear_delivery_portfolio_cache(org_id=alert.org_id)
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
    try:
        from app.time_series.recommendations import append_recommendation_timeline

        await append_recommendation_timeline(
            session,
            org_id=recommendation.org_id,
            project_id=recommendation.project_id,
            domain="delivery",
            subject_table="mitigation_recommendations",
            subject_id=recommendation.id,
            event_type="accepted",
            actor_user_id=current_user.id,
            source_agent="delivery",
            recommendation_type=recommendation.title,
            severity=recommendation.severity.value
            if hasattr(recommendation.severity, "value")
            else str(recommendation.severity),
            status_snapshot=recommendation.status.value
            if hasattr(recommendation.status, "value")
            else str(recommendation.status),
            idempotency_key=f"mitigation-accept:{recommendation.id}",
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "event=time_series_mitigation_accept_hook_failed recommendation_id=%s",
            recommendation_id,
        )
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
    try:
        from app.time_series.recommendations import append_recommendation_timeline

        await append_recommendation_timeline(
            session,
            org_id=recommendation.org_id,
            project_id=recommendation.project_id,
            domain="delivery",
            subject_table="mitigation_recommendations",
            subject_id=recommendation.id,
            event_type="rejected",
            actor_user_id=current_user.id,
            source_agent="delivery",
            recommendation_type=recommendation.title,
            severity=recommendation.severity.value
            if hasattr(recommendation.severity, "value")
            else str(recommendation.severity),
            status_snapshot=recommendation.status.value
            if hasattr(recommendation.status, "value")
            else str(recommendation.status),
            idempotency_key=f"mitigation-reject:{recommendation.id}",
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "event=time_series_mitigation_reject_hook_failed recommendation_id=%s",
            recommendation_id,
        )
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


# ---------------------------------------------------------------------------
# Phase 15.1 — Root-cause intelligence
# ---------------------------------------------------------------------------


@router.get(
    "/delivery/root-causes",
    response_model=DataResponse[RootCauseAnalyticsResponse],
)
async def get_delivery_root_cause_analytics(
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    org_id: UUID | None = None,
    lookback_days: int = Query(default=30, ge=1, le=365),
) -> DataResponse[RootCauseAnalyticsResponse]:
    payload = await get_org_root_cause_analytics(
        session,
        org_id=org_id,
        current_user=current_user,
        lookback_days=lookback_days,
    )
    return DataResponse(data=RootCauseAnalyticsResponse.model_validate(payload))


@router.get(
    "/delivery/root-causes/trends",
    response_model=DataResponse[RootCauseTrendsResponse],
)
async def get_delivery_root_cause_trends(
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    org_id: UUID | None = None,
    project_id: UUID | None = None,
) -> DataResponse[RootCauseTrendsResponse]:
    if project_id is not None:
        await get_visible_project(session, project_id, current_user)
    payload = await get_root_cause_trends(
        session,
        org_id=org_id,
        project_id=project_id,
        current_user=current_user,
    )
    return DataResponse(data=RootCauseTrendsResponse.model_validate(payload))


@router.get(
    "/delivery/projects/{project_id}/root-causes",
    response_model=DataResponse[ProjectRootCausesResponse],
)
async def get_project_delivery_root_causes(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    as_of: date | None = None,
    history_days: int = Query(default=30, ge=1, le=365),
) -> DataResponse[ProjectRootCausesResponse]:
    await get_visible_project(session, project_id, current_user)
    payload = await get_project_root_causes(
        session,
        project_id=project_id,
        as_of=as_of,
        history_days=history_days,
        current_user=current_user,
    )
    return DataResponse(data=ProjectRootCausesResponse.model_validate(payload))


@router.post(
    "/delivery/projects/{project_id}/recalculate-root-causes",
    response_model=DataResponse[RootCauseRecalculateResponse],
)
async def recalculate_project_root_causes(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
    snapshot_date: date | None = None,
) -> DataResponse[RootCauseRecalculateResponse]:
    project = await get_visible_project(session, project_id, current_user)
    try:
        snapshot = await recalculate_root_causes(
            session,
            project_id=project.id,
            org_id=project.org_id,
            snapshot_date=snapshot_date,
        )
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from exc
    await session.commit()
    refreshed = await get_project_root_causes(
        session,
        project_id=project.id,
        as_of=snapshot.snapshot_date,
        history_days=1,
        current_user=current_user,
    )
    latest = refreshed.get("latest")
    if latest is None:
        raise ApiError(500, "ROOT_CAUSE_PERSIST_FAILED", "Root-cause snapshot was not persisted.")
    return DataResponse(
        data=RootCauseRecalculateResponse(
            snapshot=RootCauseSnapshotRead.model_validate(latest),
            recalculated=True,
        )
    )


# ---------------------------------------------------------------------------
# Phase 15.2 — Operational data sources (internal only)
# ---------------------------------------------------------------------------


def _timesheet_response(row: DeliveryTimesheetEntry, *, created=False, corrected=False) -> TimesheetEntryResponse:
    response = TimesheetEntryResponse.model_validate(row)
    response.created = created
    response.corrected = corrected
    return response


def _absenteeism_response(
    row: DeliveryAbsenteeismSnapshot, *, created=False, corrected=False
) -> AbsenteeismSnapshotResponse:
    response = AbsenteeismSnapshotResponse.model_validate(row)
    response.created = created
    response.corrected = corrected
    return response


def _review_response(
    row: DeliveryReviewQueueSnapshot, *, created=False, corrected=False
) -> ReviewQueueSnapshotResponse:
    response = ReviewQueueSnapshotResponse.model_validate(row)
    response.created = created
    response.corrected = corrected
    return response


def _backlog_response(
    row: DeliveryBacklogQueueSnapshot, *, created=False, corrected=False
) -> BacklogQueueSnapshotResponse:
    response = BacklogQueueSnapshotResponse.model_validate(row)
    response.created = created
    response.corrected = corrected
    return response


def _capacity_response(
    row: DeliveryCapacitySnapshot, *, created=False, corrected=False
) -> CapacitySnapshotResponse:
    response = CapacitySnapshotResponse.model_validate(row)
    response.created = created
    response.corrected = corrected
    return response


def _availability_response(
    row: DeliveryTeamAvailabilitySnapshot, *, created=False, corrected=False
) -> TeamAvailabilitySnapshotResponse:
    response = TeamAvailabilitySnapshotResponse.model_validate(row)
    response.created = created
    response.corrected = corrected
    return response


@router.get(
    "/delivery/projects/{project_id}/timesheets",
    response_model=ListResponse[TimesheetEntryResponse],
)
async def list_project_timesheets(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    team_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[TimesheetEntryResponse]:
    await get_visible_project(session, project_id, current_user)
    stmt = select(DeliveryTimesheetEntry).where(DeliveryTimesheetEntry.project_id == project_id)
    if team_id is not None:
        stmt = stmt.where(DeliveryTimesheetEntry.team_id == team_id)
    if date_from is not None:
        stmt = stmt.where(DeliveryTimesheetEntry.snapshot_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(DeliveryTimesheetEntry.snapshot_date <= date_to)
    rows = (
        await session.execute(
            stmt.order_by(DeliveryTimesheetEntry.snapshot_date.desc()).offset(offset).limit(limit)
        )
    ).scalars()
    data = [_timesheet_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(limit=limit, offset=offset, items=len(data), has_more=len(data) == limit),
    )


@router.post(
    "/delivery/projects/{project_id}/timesheets",
    response_model=DataResponse[TimesheetEntryResponse],
)
async def create_project_timesheet(
    project_id: UUID,
    payload: TimesheetEntryCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[TimesheetEntryResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await upsert_timesheet_entry(
        session, project=project, actor=current_user, payload=payload
    )
    await session.commit()
    await session.refresh(result.row)
    return DataResponse(
        data=_timesheet_response(result.row, created=result.created, corrected=result.corrected)
    )


@router.get(
    "/delivery/projects/{project_id}/absenteeism",
    response_model=ListResponse[AbsenteeismSnapshotResponse],
)
async def list_project_absenteeism(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[AbsenteeismSnapshotResponse]:
    await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(DeliveryAbsenteeismSnapshot)
            .where(DeliveryAbsenteeismSnapshot.project_id == project_id)
            .order_by(DeliveryAbsenteeismSnapshot.snapshot_date.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    data = [_absenteeism_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(limit=limit, offset=offset, items=len(data), has_more=len(data) == limit),
    )


@router.post(
    "/delivery/projects/{project_id}/absenteeism",
    response_model=DataResponse[AbsenteeismSnapshotResponse],
)
async def create_project_absenteeism(
    project_id: UUID,
    payload: AbsenteeismSnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[AbsenteeismSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await upsert_absenteeism_snapshot(
        session, project=project, actor=current_user, payload=payload
    )
    await session.commit()
    await session.refresh(result.row)
    return DataResponse(
        data=_absenteeism_response(result.row, created=result.created, corrected=result.corrected)
    )


@router.get(
    "/delivery/projects/{project_id}/review-queue",
    response_model=ListResponse[ReviewQueueSnapshotResponse],
)
async def list_project_review_queue(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[ReviewQueueSnapshotResponse]:
    await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(DeliveryReviewQueueSnapshot)
            .where(DeliveryReviewQueueSnapshot.project_id == project_id)
            .order_by(DeliveryReviewQueueSnapshot.snapshot_date.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    data = [_review_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(limit=limit, offset=offset, items=len(data), has_more=len(data) == limit),
    )


@router.post(
    "/delivery/projects/{project_id}/review-queue",
    response_model=DataResponse[ReviewQueueSnapshotResponse],
)
async def create_project_review_queue(
    project_id: UUID,
    payload: ReviewQueueSnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[ReviewQueueSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await upsert_review_queue_snapshot(
        session, project=project, actor=current_user, payload=payload
    )
    await session.commit()
    await session.refresh(result.row)
    return DataResponse(
        data=_review_response(result.row, created=result.created, corrected=result.corrected)
    )


@router.get(
    "/delivery/projects/{project_id}/backlog-queue",
    response_model=ListResponse[BacklogQueueSnapshotResponse],
)
async def list_project_backlog_queue(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[BacklogQueueSnapshotResponse]:
    await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(DeliveryBacklogQueueSnapshot)
            .where(DeliveryBacklogQueueSnapshot.project_id == project_id)
            .order_by(DeliveryBacklogQueueSnapshot.snapshot_date.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    data = [_backlog_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(limit=limit, offset=offset, items=len(data), has_more=len(data) == limit),
    )


@router.post(
    "/delivery/projects/{project_id}/backlog-queue",
    response_model=DataResponse[BacklogQueueSnapshotResponse],
)
async def create_project_backlog_queue(
    project_id: UUID,
    payload: BacklogQueueSnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[BacklogQueueSnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await upsert_backlog_queue_snapshot(
        session, project=project, actor=current_user, payload=payload
    )
    await session.commit()
    await session.refresh(result.row)
    return DataResponse(
        data=_backlog_response(result.row, created=result.created, corrected=result.corrected)
    )


@router.get(
    "/delivery/projects/{project_id}/capacity",
    response_model=ListResponse[CapacitySnapshotResponse],
)
async def list_project_capacity(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[CapacitySnapshotResponse]:
    await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(DeliveryCapacitySnapshot)
            .where(DeliveryCapacitySnapshot.project_id == project_id)
            .order_by(DeliveryCapacitySnapshot.snapshot_date.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    data = [_capacity_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(limit=limit, offset=offset, items=len(data), has_more=len(data) == limit),
    )


@router.post(
    "/delivery/projects/{project_id}/capacity",
    response_model=DataResponse[CapacitySnapshotResponse],
)
async def create_project_capacity(
    project_id: UUID,
    payload: CapacitySnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[CapacitySnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await upsert_capacity_snapshot(
        session, project=project, actor=current_user, payload=payload
    )
    await session.commit()
    await session.refresh(result.row)
    return DataResponse(
        data=_capacity_response(result.row, created=result.created, corrected=result.corrected)
    )


@router.get(
    "/delivery/projects/{project_id}/team-availability",
    response_model=ListResponse[TeamAvailabilitySnapshotResponse],
)
async def list_project_team_availability(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    team_id: UUID | None = None,
    limit: LimitQuery = 100,
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ListResponse[TeamAvailabilitySnapshotResponse]:
    await get_visible_project(session, project_id, current_user)
    stmt = select(DeliveryTeamAvailabilitySnapshot).where(
        DeliveryTeamAvailabilitySnapshot.project_id == project_id
    )
    if team_id is not None:
        stmt = stmt.where(DeliveryTeamAvailabilitySnapshot.team_id == team_id)
    rows = (
        await session.execute(
            stmt.order_by(DeliveryTeamAvailabilitySnapshot.snapshot_date.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    data = [_availability_response(row) for row in rows]
    return ListResponse(
        data=data,
        pagination=Pagination(limit=limit, offset=offset, items=len(data), has_more=len(data) == limit),
    )


@router.post(
    "/delivery/projects/{project_id}/team-availability",
    response_model=DataResponse[TeamAvailabilitySnapshotResponse],
)
async def create_project_team_availability(
    project_id: UUID,
    payload: TeamAvailabilitySnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[TeamAvailabilitySnapshotResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await upsert_team_availability_snapshot(
        session, project=project, actor=current_user, payload=payload
    )
    await session.commit()
    await session.refresh(result.row)
    return DataResponse(
        data=_availability_response(result.row, created=result.created, corrected=result.corrected)
    )


# ---------------------------------------------------------------------------
# Phase 15.3 — PM Daily Action Planner
# ---------------------------------------------------------------------------


@router.get(
    "/delivery/projects/{project_id}/daily-actions",
    response_model=DataResponse[PmDailyActionsResponse],
)
async def get_project_daily_actions(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    plan_date: date | None = None,
    include_history: bool = Query(default=True),
    history_days: int = Query(default=14, ge=1, le=90),
) -> DataResponse[PmDailyActionsResponse]:
    await get_visible_project(session, project_id, current_user)
    payload = await list_daily_actions(
        session,
        project_id=project_id,
        plan_date=plan_date,
        include_history=include_history,
        history_days=history_days,
    )
    return DataResponse(data=PmDailyActionsResponse.model_validate(payload))


@router.post(
    "/delivery/projects/{project_id}/daily-actions/generate",
    response_model=DataResponse[PmDailyActionsResponse],
)
async def generate_project_daily_actions(
    project_id: UUID,
    session: SessionDep,
    payload: PmDailyActionGenerateRequest | None = None,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[PmDailyActionsResponse]:
    project = await get_visible_project(session, project_id, current_user)
    request = payload or PmDailyActionGenerateRequest()
    try:
        await generate_daily_actions(
            session,
            project_id=project.id,
            org_id=project.org_id,
            plan_date=request.plan_date,
            with_ai_rationale=request.with_ai_rationale,
            limit=request.limit,
        )
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from exc
    await session.commit()
    result = await list_daily_actions(
        session,
        project_id=project.id,
        plan_date=request.plan_date,
        include_history=True,
    )
    return DataResponse(data=PmDailyActionsResponse.model_validate(result))


@router.post(
    "/delivery/daily-actions/{action_id}/complete",
    response_model=DataResponse[PmDailyActionRead],
)
async def complete_project_daily_action(
    action_id: UUID,
    payload: PmDailyActionCompleteRequest,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[PmDailyActionRead]:
    row = await complete_daily_action(
        session,
        action_id=action_id,
        actor=current_user,
        status=PmDailyActionStatus(payload.status),
        note=payload.note,
    )
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=PmDailyActionRead.model_validate(action_to_payload(row)))


# ---------------------------------------------------------------------------
# Phase 15.4 — AI Daily Operational Briefing
# ---------------------------------------------------------------------------


@router.get(
    "/delivery/projects/{project_id}/operational-briefing",
    response_model=DataResponse[OperationalBriefingSchema],
)
async def get_project_operational_briefing(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    with_ai: bool = Query(default=True),
    as_of: date | None = None,
) -> DataResponse[OperationalBriefingSchema]:
    await get_visible_project(session, project_id, current_user)
    payload = await build_project_operational_briefing(
        session,
        project_id=project_id,
        current_user=current_user,
        as_of=as_of,
        with_ai=with_ai,
    )
    return DataResponse(data=OperationalBriefingSchema.model_validate(payload))


@router.post(
    "/delivery/projects/{project_id}/operational-briefing/generate",
    response_model=DataResponse[OperationalBriefingSchema],
)
async def generate_project_operational_briefing(
    project_id: UUID,
    payload: OperationalBriefingGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = DeliveryOperator,
) -> DataResponse[OperationalBriefingSchema]:
    await get_visible_project(session, project_id, current_user)
    briefing = await build_project_operational_briefing(
        session,
        project_id=project_id,
        current_user=current_user,
        with_ai=payload.with_ai,
    )
    return DataResponse(data=OperationalBriefingSchema.model_validate(briefing))


# ---------------------------------------------------------------------------
# Phase 15.5 — Delivery Knowledge Integration (reuse Knowledge RAG)
# ---------------------------------------------------------------------------


@router.get(
    "/delivery/projects/{project_id}/knowledge-evidence",
    response_model=DataResponse[KnowledgeEvidenceResponse],
)
async def get_project_knowledge_evidence(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = InternalDeliveryUser,
    focus: str | None = Query(default=None, max_length=500),
    max_sources: int = Query(default=5, ge=1, le=10),
) -> DataResponse[KnowledgeEvidenceResponse]:
    """Retrieve approved Knowledge citations for a Delivery project (fail-open)."""
    await get_visible_project(session, project_id, current_user)
    payload = await retrieve_delivery_knowledge_evidence(
        session,
        current_user,
        project_id=project_id,
        focus=focus,
        max_sources=max_sources,
    )
    return DataResponse(data=KnowledgeEvidenceResponse.model_validate(payload))
