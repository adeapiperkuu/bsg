import json
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.agents.governance.schemas.governance import (
    GovernanceLearningRuleApproveRequest,
    GovernanceLearningRuleRead,
    GovernanceLearningRuleRollbackRequest,
    GovernanceOptimizationCompareRead,
    GovernanceOptimizationDriftRead,
    GovernanceOptimizationFilters,
    GovernanceOptimizationReportRead,
    GovernanceOptimizationShadowRead,
    GovernanceOptimizationStrategyRead,
    GovernanceOptimizationSummaryRead,
    GovernanceRecommendationCancelResolutionRequest,
    GovernanceRecommendationChangeConversionTargetRequest,
    GovernanceRecommendationConvertRequest,
    GovernanceRecommendationLifecycleActionRead,
    GovernanceRecommendationReopenRequest,
    GovernanceRecommendationResolveRequest,
)
from app.agents.governance.services.optimization_service import (
    approve_learning_rule,
    cancel_recommendation_resolution,
    change_conversion_target,
    compare_strategy_versions,
    convert_recommendation_lifecycle,
    generate_evaluation_report,
    get_optimization_drift,
    get_optimization_summary,
    list_evaluation_reports,
    list_learning_rules,
    list_shadow_evaluations,
    list_strategy_versions,
    optimization_report_csv,
    reopen_recommendation,
    resolve_recommendation,
    rollback_learning_rule,
    run_shadow_evaluation,
)
from app.agents.governance.timing import instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, GovernanceRecommendationEvaluationPeriod
from app.schemas.common import DataResponse
from app.services.pdf_export import generate_simple_pdf

router = APIRouter(tags=["governance"])

WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)
MONITORING_ROLES = (AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


def _optimization_filters(
    days: int = 30,
    project_id: UUID | None = None,
    vertical: str | None = None,
    trigger_type: str | None = None,
    strategy_version: str | None = None,
    learning_rule_id: UUID | None = None,
    quality_band: str | None = None,
    confidence_band: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> GovernanceOptimizationFilters:
    return GovernanceOptimizationFilters(
        days=days,
        project_id=project_id,
        vertical=vertical,
        trigger_type=trigger_type,
        strategy_version=strategy_version,
        learning_rule_id=learning_rule_id,
        quality_band=quality_band,
        confidence_band=confidence_band,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/governance/recommendations/optimization/summary",
    response_model=DataResponse[GovernanceOptimizationSummaryRead],
)
async def get_recommendation_optimization_summary(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    days: int = Query(default=30, ge=1, le=365),
    project_id: UUID | None = None,
    vertical: str | None = None,
    trigger_type: str | None = None,
    strategy_version: str | None = None,
    learning_rule_id: UUID | None = None,
    quality_band: str | None = None,
    confidence_band: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> DataResponse[GovernanceOptimizationSummaryRead]:
    data = await get_optimization_summary(
        session,
        current_user,
        _optimization_filters(
            days=days,
            project_id=project_id,
            vertical=vertical,
            trigger_type=trigger_type,
            strategy_version=strategy_version,
            learning_rule_id=learning_rule_id,
            quality_band=quality_band,
            confidence_band=confidence_band,
            status=status,
            date_from=date_from,
            date_to=date_to,
        ),
    )
    return DataResponse(data=data)


@router.get(
    "/governance/recommendations/optimization/drift",
    response_model=DataResponse[GovernanceOptimizationDriftRead],
)
async def get_recommendation_optimization_drift(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    days: int = Query(default=30, ge=1, le=365),
    project_id: UUID | None = None,
    vertical: str | None = None,
    strategy_version: str | None = None,
) -> DataResponse[GovernanceOptimizationDriftRead]:
    data = await get_optimization_drift(
        session,
        current_user,
        _optimization_filters(
            days=days,
            project_id=project_id,
            vertical=vertical,
            strategy_version=strategy_version,
        ),
        persist=True,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/recommendations/optimization/strategies",
    response_model=DataResponse[list[GovernanceOptimizationStrategyRead]],
)
async def get_recommendation_optimization_strategies(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
) -> DataResponse[list[GovernanceOptimizationStrategyRead]]:
    data = await list_strategy_versions(session, current_user)
    return DataResponse(data=data)


@router.get(
    "/governance/recommendations/optimization/compare",
    response_model=DataResponse[GovernanceOptimizationCompareRead],
)
async def get_recommendation_optimization_compare(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    strategy_a: str = Query(...),
    strategy_b: str = Query(...),
    days: int = Query(default=30, ge=1, le=365),
) -> DataResponse[GovernanceOptimizationCompareRead]:
    data = await compare_strategy_versions(
        session,
        current_user,
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        days=days,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/recommendations/optimization/shadow",
    response_model=DataResponse[list[GovernanceOptimizationShadowRead]],
)
async def get_recommendation_optimization_shadow(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
) -> DataResponse[list[GovernanceOptimizationShadowRead]]:
    data = await list_shadow_evaluations(session, current_user, limit=limit)
    return DataResponse(data=data)


@router.get(
    "/governance/recommendations/optimization/reports",
    response_model=DataResponse[list[GovernanceOptimizationReportRead]],
)
async def get_recommendation_optimization_reports(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
) -> DataResponse[list[GovernanceOptimizationReportRead]]:
    data = await list_evaluation_reports(session, current_user, limit=limit)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/optimization/reports",
    response_model=DataResponse[GovernanceOptimizationReportRead],
)
async def post_recommendation_optimization_report(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    period: str = Query(default="weekly"),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceOptimizationReportRead]:
    try:
        period_enum = GovernanceRecommendationEvaluationPeriod(period)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="period must be weekly, monthly, or quarterly"
        ) from exc
    data = await generate_evaluation_report(session, current_user, period=period_enum)
    return DataResponse(data=data)


@router.get("/governance/recommendations/optimization/reports/{report_id}/export")
async def export_recommendation_optimization_report(
    report_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    format: str = Query(default="csv", pattern="^(json|csv|pdf)$"),
) -> Response:
    reports = await list_evaluation_reports(session, current_user, limit=200)
    report = next((r for r in reports if r.id == report_id), None)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if format == "json":
        filename = f"governance_optimization_report_{report_id}.json"
        return Response(
            content=json.dumps(report.model_dump(mode="json"), indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if format == "pdf":
        filename = f"governance_optimization_report_{report_id}.pdf"
        lines = [
            f"Period: {report.period}",
            f"Range: {report.period_start} - {report.period_end}",
            f"Strategy: {report.strategy_version or 'n/a'}",
            "",
            "KPI summary and drift alerts are included in the JSON/CSV exports.",
        ]
        for alert in ((report.report_payload or {}).get("drift") or {}).get("alerts") or []:
            lines.append(f"- {alert.get('message')}")
        return Response(
            content=generate_simple_pdf(
                title="Governance Recommendation Optimization Report",
                body="\n".join(lines),
            ),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    filename = f"governance_optimization_report_{report_id}.csv"
    return Response(
        content=optimization_report_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/governance/recommendations/learning-rules",
    response_model=DataResponse[list[GovernanceLearningRuleRead]],
)
async def get_recommendation_learning_rules(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
) -> DataResponse[list[GovernanceLearningRuleRead]]:
    data = await list_learning_rules(session, current_user)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/{recommendation_id}/convert",
    response_model=DataResponse[GovernanceRecommendationLifecycleActionRead],
)
async def post_recommendation_convert(
    recommendation_id: UUID,
    payload: GovernanceRecommendationConvertRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationLifecycleActionRead]:
    data = await convert_recommendation_lifecycle(session, current_user, recommendation_id, payload)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/{recommendation_id}/resolve",
    response_model=DataResponse[GovernanceRecommendationLifecycleActionRead],
)
async def post_recommendation_resolve(
    recommendation_id: UUID,
    payload: GovernanceRecommendationResolveRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationLifecycleActionRead]:
    data = await resolve_recommendation(session, current_user, recommendation_id, payload)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/{recommendation_id}/reopen",
    response_model=DataResponse[GovernanceRecommendationLifecycleActionRead],
)
async def post_recommendation_reopen(
    recommendation_id: UUID,
    payload: GovernanceRecommendationReopenRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationLifecycleActionRead]:
    data = await reopen_recommendation(session, current_user, recommendation_id, payload)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/{recommendation_id}/cancel-resolution",
    response_model=DataResponse[GovernanceRecommendationLifecycleActionRead],
)
async def post_recommendation_cancel_resolution(
    recommendation_id: UUID,
    payload: GovernanceRecommendationCancelResolutionRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationLifecycleActionRead]:
    data = await cancel_recommendation_resolution(session, current_user, recommendation_id, payload)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/{recommendation_id}/change-conversion-target",
    response_model=DataResponse[GovernanceRecommendationLifecycleActionRead],
)
async def post_recommendation_change_conversion_target(
    recommendation_id: UUID,
    payload: GovernanceRecommendationChangeConversionTargetRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationLifecycleActionRead]:
    data = await change_conversion_target(session, current_user, recommendation_id, payload)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/learning-rules/{rule_id}/approve",
    response_model=DataResponse[GovernanceLearningRuleRead],
)
async def post_learning_rule_approve(
    rule_id: UUID,
    payload: GovernanceLearningRuleApproveRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceLearningRuleRead]:
    data = await approve_learning_rule(session, current_user, rule_id, activate=payload.activate)
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/learning-rules/{rule_id}/rollback",
    response_model=DataResponse[GovernanceLearningRuleRead],
)
async def post_learning_rule_rollback(
    rule_id: UUID,
    payload: GovernanceLearningRuleRollbackRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceLearningRuleRead]:
    data = await rollback_learning_rule(
        session, current_user, rule_id, disable_only=payload.disable_only
    )
    return DataResponse(data=data)


@router.post(
    "/governance/recommendations/learning-rules/{rule_id}/shadow",
    response_model=DataResponse[GovernanceOptimizationShadowRead],
)
async def post_learning_rule_shadow(
    rule_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceOptimizationShadowRead]:
    data = await run_shadow_evaluation(session, current_user, rule_id)
    return DataResponse(data=data)


instrument_governance_routes(router)
