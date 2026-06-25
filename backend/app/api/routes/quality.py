from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, QualityErrorEntry, QualitySnapshot, RiskAlert, ScanTrigger, Team
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    AdminProjectRead,
    CalibrationBriefRead,
    GoldSetMetadataCreate,
    GoldSetMetadataRead,
    IaaMeasurementCreate,
    IaaMeasurementRead,
    InterAgentSignalRead,
    OnboardingRecordCreate,
    OnboardingRecordRead,
    QualityDashboardRead,
    QualityErrorEntryCreate,
    QualityPortfolioRead,
    QualityScanRunRead,
    QualitySnapshotCreate,
    QualitySnapshotRead,
    QualitySnapshotUpdate,
    QualitySummaryRead,
    ReviewerScorecardCreate,
    ReviewerScorecardRead,
    RiskAlertRead,
    RiskAlertResolve,
    SopAmbiguityFlagRead,
    SopVersionCreate,
    SopVersionRead,
)
from app.services.quality import (
    build_quality_dashboard,
    create_iaa_measurement,
    create_onboarding_record,
    create_reviewer_scorecard,
    create_sop_version,
    evaluate_snapshot,
    generate_quality_summary,
    get_calibration_brief_for_project,
    get_leadership_quality_portfolio,
    get_sop_ambiguity_flags,
    list_admin_projects,
    list_inter_agent_signals,
    list_quality_scan_runs,
    list_reviewer_scorecards,
    load_snapshot_with_errors,
    resolve_risk_alert,
    scan_all_projects,
    upsert_gold_set_metadata,
    upsert_quality_snapshot,
)
from app.services.scoping import get_visible_project

router = APIRouter(tags=["quality"])


@router.post("/internal/quality-scan", response_model=DataResponse[QualityScanRunRead])
async def trigger_quality_scan(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[QualityScanRunRead]:
    run = await scan_all_projects(
        session,
        trigger=ScanTrigger.MANUAL,
        triggered_by=current_user.id,
    )
    return DataResponse(data=QualityScanRunRead.model_validate(run))


@router.get("/internal/quality-scan-runs", response_model=ListResponse[QualityScanRunRead])
async def get_quality_scan_runs(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.SUPER_ADMIN)),
) -> ListResponse[QualityScanRunRead]:
    rows = await list_quality_scan_runs(session)
    return ListResponse(
        data=[QualityScanRunRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=50),
    )


@router.get("/internal/projects", response_model=ListResponse[AdminProjectRead])
async def list_internal_projects(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.SUPER_ADMIN)),
) -> ListResponse[AdminProjectRead]:
    rows = await list_admin_projects(session)
    return ListResponse(data=rows, pagination=Pagination(limit=200))


@router.get("/leadership/quality-portfolio", response_model=DataResponse[QualityPortfolioRead])
async def get_leadership_quality_portfolio_route(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[QualityPortfolioRead]:
    portfolio = await get_leadership_quality_portfolio(session)
    return DataResponse(data=portfolio)


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


@router.post("/projects/{project_id}/reviewer-scorecards", response_model=DataResponse[ReviewerScorecardRead])
async def post_reviewer_scorecard(
    project_id: UUID,
    payload: ReviewerScorecardCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ReviewerScorecardRead]:
    project = await get_visible_project(session, project_id, current_user)
    card = await create_reviewer_scorecard(session, project, payload)
    await session.commit()
    await session.refresh(card)
    return DataResponse(data=ReviewerScorecardRead.model_validate(card))


@router.get("/projects/{project_id}/reviewer-scorecards", response_model=ListResponse[ReviewerScorecardRead])
async def get_reviewer_scorecards(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    iso_year: int | None = Query(default=None),
    iso_week: int | None = Query(default=None),
) -> ListResponse[ReviewerScorecardRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = await list_reviewer_scorecards(session, project.id, iso_year=iso_year, iso_week=iso_week)
    return ListResponse(
        data=[ReviewerScorecardRead.model_validate(r) for r in rows],
        pagination=Pagination(limit=100),
    )


@router.post("/projects/{project_id}/iaa-measurements", response_model=DataResponse[IaaMeasurementRead])
async def post_iaa_measurement(
    project_id: UUID,
    payload: IaaMeasurementCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[IaaMeasurementRead]:
    project = await get_visible_project(session, project_id, current_user)
    row = await create_iaa_measurement(session, project, payload)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=IaaMeasurementRead.model_validate(row))


@router.post("/projects/{project_id}/sop-versions", response_model=DataResponse[SopVersionRead])
async def post_sop_version(
    project_id: UUID,
    payload: SopVersionCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[SopVersionRead]:
    project = await get_visible_project(session, project_id, current_user)
    row = await create_sop_version(session, project, payload)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=SopVersionRead.model_validate(row))


@router.post("/projects/{project_id}/gold-set-metadata", response_model=DataResponse[GoldSetMetadataRead])
async def post_gold_set_metadata(
    project_id: UUID,
    payload: GoldSetMetadataCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[GoldSetMetadataRead]:
    project = await get_visible_project(session, project_id, current_user)
    row = await upsert_gold_set_metadata(session, project, payload)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=GoldSetMetadataRead.model_validate(row))


@router.post("/projects/{project_id}/onboarding-records", response_model=DataResponse[OnboardingRecordRead])
async def post_onboarding_record(
    project_id: UUID,
    payload: OnboardingRecordCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[OnboardingRecordRead]:
    project = await get_visible_project(session, project_id, current_user)
    row = await create_onboarding_record(session, project, payload)
    await session.commit()
    await session.refresh(row)
    return DataResponse(data=OnboardingRecordRead.model_validate(row))


@router.get("/projects/{project_id}/calibration-brief", response_model=DataResponse[CalibrationBriefRead])
async def get_calibration_brief(
    project_id: UUID,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
    iso_year: int | None = Query(default=None),
    iso_week: int | None = Query(default=None),
) -> DataResponse[CalibrationBriefRead]:
    from datetime import datetime, timezone

    project = await get_visible_project(session, project_id, current_user)
    if iso_year is None or iso_week is None:
        now = datetime.now(timezone.utc)
        cal = now.isocalendar()
        iso_year = cal[0]
        iso_week = cal[1]
    brief = await get_calibration_brief_for_project(
        session, project, iso_year=iso_year, iso_week=iso_week
    )
    return DataResponse(data=brief)


@router.get("/projects/{project_id}/sop-ambiguity-flags", response_model=ListResponse[SopAmbiguityFlagRead])
async def get_sop_ambiguity_flags_route(
    project_id: UUID,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> ListResponse[SopAmbiguityFlagRead]:
    project = await get_visible_project(session, project_id, current_user)
    flags = await get_sop_ambiguity_flags(session, project.id)
    return ListResponse(data=flags, pagination=Pagination(limit=50))


@router.get("/inter-agent-signals", response_model=ListResponse[InterAgentSignalRead])
async def get_inter_agent_signals(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.SUPER_ADMIN)),
) -> ListResponse[InterAgentSignalRead]:
    rows = await list_inter_agent_signals(session)
    return ListResponse(
        data=[InterAgentSignalRead.model_validate(r) for r in rows],
        pagination=Pagination(limit=50),
    )


@router.patch("/risk-alerts/{alert_id}/resolve", response_model=DataResponse[RiskAlertRead])
async def resolve_risk_alert_route(
    alert_id: UUID,
    payload: RiskAlertResolve,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[RiskAlertRead]:
    alert = (await session.execute(select(RiskAlert).where(RiskAlert.id == alert_id))).scalar_one_or_none()
    if alert is None or (current_user.role != AppRole.SUPER_ADMIN and alert.org_id != current_user.org_id):
        raise ApiError(404, "NOT_FOUND", "Risk alert was not found.")
    alert = await resolve_risk_alert(
        session,
        alert,
        resolved_by=current_user.id,
        resolution_summary=payload.resolution_summary,
    )
    await session.commit()
    await session.refresh(alert)
    return DataResponse(data=RiskAlertRead.model_validate(alert))
