from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.agents.governance.schemas.governance import (
    GovernanceEffectivenessCalibrationRead,
    GovernanceEffectivenessCategoryStatRead,
    GovernanceEffectivenessDrilldownRead,
    GovernanceEffectivenessFalsePositiveRead,
    GovernanceEffectivenessFunnelRead,
    GovernanceEffectivenessQualityRead,
    GovernanceEffectivenessRecurrenceRead,
    GovernanceEffectivenessSummaryRead,
    GovernanceEffectivenessTimingRead,
    GovernanceEffectivenessTrendsRead,
    GovernanceRecommendationLifecycleEventRead,
    GovernanceStructuredFeedbackRead,
    GovernanceStructuredFeedbackRequest,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.effectiveness_service import (
    EffectivenessFilters,
    effectiveness_report_csv,
    get_effectiveness_calibration,
    get_effectiveness_drilldown,
    get_effectiveness_false_positives,
    get_effectiveness_funnel,
    get_effectiveness_quality,
    get_effectiveness_recurrence,
    get_effectiveness_report,
    get_effectiveness_summary,
    get_effectiveness_timing,
    get_effectiveness_trends,
    get_frequently_accepted,
    get_frequently_dismissed,
    get_recommendation_lifecycle,
    submit_structured_recommendation_feedback,
)
from app.agents.governance.timing import instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse
from app.services.pdf_export import generate_simple_pdf

router = APIRouter(tags=["governance"])

AI_RECOMMENDATION_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
)


def _effectiveness_filters(
    *,
    days: int = 30,
    project_id: UUID | None = None,
    vertical: str | None = None,
    trigger_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    confidence_band: str | None = None,
    quality_band: str | None = None,
    false_positive_status: str | None = None,
    recurring_only: bool = False,
) -> EffectivenessFilters:
    return EffectivenessFilters(
        days=days,
        project_id=project_id,
        vertical=vertical,
        trigger_type=trigger_type,
        severity=severity,
        status=status,
        confidence_band=confidence_band,
        quality_band=quality_band,
        false_positive_status=false_positive_status,
        recurring_only=recurring_only,
    )


@router.get(
    "/governance/insights/recommendations/effectiveness/summary",
    response_model=DataResponse[GovernanceEffectivenessSummaryRead],
)
async def governance_recommendation_effectiveness_summary(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    confidence_band: str | None = Query(default=None),
    quality_band: str | None = Query(default=None),
    false_positive_status: str | None = Query(default=None),
    recurring_only: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessSummaryRead]:
    data = await get_effectiveness_summary(
        session,
        current_user,
        _effectiveness_filters(
            days=days,
            project_id=project_id,
            vertical=vertical,
            trigger_type=trigger_type,
            severity=severity,
            status=status,
            confidence_band=confidence_band,
            quality_band=quality_band,
            false_positive_status=false_positive_status,
            recurring_only=recurring_only,
        ),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/trends",
    response_model=DataResponse[GovernanceEffectivenessTrendsRead],
)
async def governance_recommendation_effectiveness_trends(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessTrendsRead]:
    data = await get_effectiveness_trends(
        session,
        current_user,
        _effectiveness_filters(
            days=days,
            project_id=project_id,
            vertical=vertical,
            trigger_type=trigger_type,
        ),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/funnel",
    response_model=DataResponse[GovernanceEffectivenessFunnelRead],
)
async def governance_recommendation_effectiveness_funnel(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessFunnelRead]:
    data = await get_effectiveness_funnel(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/timing",
    response_model=DataResponse[GovernanceEffectivenessTimingRead],
)
async def governance_recommendation_effectiveness_timing(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessTimingRead]:
    data = await get_effectiveness_timing(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/quality",
    response_model=DataResponse[GovernanceEffectivenessQualityRead],
)
async def governance_recommendation_effectiveness_quality(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessQualityRead]:
    data = await get_effectiveness_quality(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/calibration",
    response_model=DataResponse[GovernanceEffectivenessCalibrationRead],
)
async def governance_recommendation_effectiveness_calibration(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessCalibrationRead]:
    data = await get_effectiveness_calibration(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/false-positives",
    response_model=DataResponse[GovernanceEffectivenessFalsePositiveRead],
)
async def governance_recommendation_effectiveness_false_positives(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessFalsePositiveRead]:
    data = await get_effectiveness_false_positives(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/frequently-dismissed",
    response_model=DataResponse[list[GovernanceEffectivenessCategoryStatRead]],
)
async def governance_recommendation_effectiveness_frequently_dismissed(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[list[GovernanceEffectivenessCategoryStatRead]]:
    data = await get_frequently_dismissed(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/frequently-accepted",
    response_model=DataResponse[list[GovernanceEffectivenessCategoryStatRead]],
)
async def governance_recommendation_effectiveness_frequently_accepted(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[list[GovernanceEffectivenessCategoryStatRead]]:
    data = await get_frequently_accepted(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/recurrence",
    response_model=DataResponse[GovernanceEffectivenessRecurrenceRead],
)
async def governance_recommendation_effectiveness_recurrence(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessRecurrenceRead]:
    data = await get_effectiveness_recurrence(
        session,
        current_user,
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/insights/recommendations/effectiveness/drilldown",
    response_model=DataResponse[GovernanceEffectivenessDrilldownRead],
)
async def governance_recommendation_effectiveness_drilldown(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceEffectivenessDrilldownRead]:
    data = await get_effectiveness_drilldown(
        session,
        current_user,
        _effectiveness_filters(
            days=days,
            project_id=project_id,
            vertical=vertical,
            trigger_type=trigger_type,
        ),
        limit=limit,
        offset=offset,
    )
    return DataResponse(data=data)


@router.get("/governance/insights/recommendations/effectiveness/export")
async def governance_recommendation_effectiveness_export(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    format: str = Query(default="csv", pattern="^(csv|json|pdf)$"),
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> Response:
    filters = _effectiveness_filters(days=days, project_id=project_id, vertical=vertical)
    report = await get_effectiveness_report(session, current_user, filters)
    await log_governance_event(
        session,
        current_user,
        event_type="dashboard.exported",
        org_id=current_user.org_id,
        source_table="governance_recommendation_effectiveness",
        metadata={"format": format, "days": report.date_range_days},
    )
    await session.commit()
    if format == "json":
        filename = "governance_recommendation_effectiveness_" f"{report.date_range_days}d.json"
        return Response(
            content=report.model_dump_json(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if format == "pdf":
        filename = "governance_recommendation_effectiveness_" f"{report.date_range_days}d.pdf"
        body = (
            f"Generated: {report.generated_at.isoformat()}\n"
            f"Range: {report.date_range_days} days\n"
            f"Reviewed: {report.summary.reviewed}\n"
            f"Acceptance: {report.summary.acceptance_rate.value}\n"
            f"Dismissal: {report.summary.dismissal_rate.value}\n"
            f"Conversion: {report.summary.conversion_rate.value}\n"
            f"Resolution: {report.summary.resolution_rate.value}\n"
            f"False positive: {report.summary.false_positive_rate.value}\n"
            + "\nWarnings\n"
            + "\n".join(f"- {item}" for item in report.warnings)
        )
        return Response(
            content=generate_simple_pdf("Recommendation Effectiveness", body),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    filename = f"governance_recommendation_effectiveness_{report.date_range_days}d.csv"
    return Response(
        content=effectiveness_report_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/governance/recommendations/{recommendation_id}/feedback",
    response_model=DataResponse[GovernanceStructuredFeedbackRead],
)
async def post_governance_recommendation_structured_feedback(
    recommendation_id: UUID,
    payload: GovernanceStructuredFeedbackRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceStructuredFeedbackRead]:
    data = await submit_structured_recommendation_feedback(
        session,
        current_user,
        recommendation_id,
        payload,
    )
    await session.commit()
    return DataResponse(data=data)


@router.get(
    "/governance/recommendations/{recommendation_id}/lifecycle",
    response_model=DataResponse[list[GovernanceRecommendationLifecycleEventRead]],
)
async def get_governance_recommendation_lifecycle(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[list[GovernanceRecommendationLifecycleEventRead]]:
    data = await get_recommendation_lifecycle(session, current_user, recommendation_id)
    return DataResponse(data=data)


instrument_governance_routes(router)
