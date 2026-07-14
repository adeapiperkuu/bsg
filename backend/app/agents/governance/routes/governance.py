import csv
import io
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.agents.governance.analytics.sla import dependency_overdue_days, effective_action_status
from app.agents.governance.schemas.governance import (
    ConvertRecommendationToActionRequest,
    ConvertRecommendationToEscalationRequest,
    EscalationSuggestionScanHistoryRead,
    EscalationSuggestionScanRequest,
    EscalationSuggestionScanResult,
    EscalationSuggestionSnoozeRequest,
    GovernanceActionCreate,
    GovernanceActionListRead,
    GovernanceActionRead,
    GovernanceActionUpdate,
    GovernanceAIRecommendationDismissRequest,
    GovernanceAIRecommendationFeedbackRead,
    GovernanceAIRecommendationFeedbackRequest,
    GovernanceAIRecommendationGenerateRequest,
    GovernanceAIRecommendationGenerationResult,
    GovernanceAIRecommendationListRead,
    GovernanceAIRecommendationRead,
    GovernanceAnalyticsDetailRead,
    GovernanceAnalyticsRead,
    GovernanceAnalyticsSummaryRead,
    GovernanceBootstrapRead,
    GovernanceEffectivenessCalibrationRead,
    GovernanceEffectivenessCategoryStatRead,
    GovernanceEffectivenessDrilldownRead,
    GovernanceEffectivenessFalsePositiveRead,
    GovernanceEffectivenessFunnelRead,
    GovernanceEffectivenessQualityRead,
    GovernanceEffectivenessRecurrenceRead,
    GovernanceEffectivenessReportRead,
    GovernanceEffectivenessSummaryRead,
    GovernanceEffectivenessTimingRead,
    GovernanceEffectivenessTrendsRead,
    GovernanceEscalationCreate,
    GovernanceEscalationListRead,
    GovernanceEscalationRead,
    GovernanceEscalationUpdate,
    GovernanceLearningRuleApproveRequest,
    GovernanceLearningRuleRead,
    GovernanceLearningRuleRollbackRequest,
    GovernanceMonitoringRead,
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
    GovernanceRecommendationConversionRead,
    GovernanceRecommendationLifecycleActionRead,
    GovernanceRecommendationReopenRequest,
    GovernanceRecommendationResolveRequest,
    GovernanceRecordEvidenceLinkRead,
    GovernanceRegisterRowRead,
    GovernanceRecommendationLifecycleEventRead,
    GovernanceSourceRecommendationRead,
    GovernanceStructuredFeedbackRead,
    GovernanceStructuredFeedbackRequest,
    GovernanceWeeklySummaryCreate,
    GovernanceWeeklySummaryGenerateRequest,
    GovernanceWeeklySummaryRead,
    GovernanceWeeklySummaryUpdate,
    ProjectCharterGenerateRequest,
    ProjectCharterRead,
    ProjectCharterUpdate,
    CharterKnowledgeLinkRead,
    CharterPublicationActionRequest,
    CharterPublicationEventRead,
    CharterPublicationStatusRead,
    CharterPublicationVersionRead,
    ProjectDependencyCreate,
    ProjectDependencyListRead,
    ProjectDependencyRead,
    ProjectDependencyUpdate,
    ProjectScopeStateRead,
    ProjectScopeStateUpdate,
    PromoteRiskAlertRequest,
)
from app.agents.governance.services.analytics_service import (
    get_governance_analytics,
    get_governance_analytics_detail,
    get_governance_analytics_summary,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.charter_export import (
    CharterExportDocument,
    generate_charter_docx,
    generate_charter_pdf,
)
from app.agents.governance.services.charter_service import (
    approve_project_charter,
    archive_project_charter,
    build_project_charter_read,
    generate_project_charter,
    get_project_charter_or_404,
    list_project_charters,
    update_project_charter_draft,
)
from app.agents.governance.services.governance_charter_publish_service import (
    PUBLISH_ROLES,
    get_charter_knowledge_link,
    get_publication_versions,
    get_publish_status,
    list_charter_publication_timeline,
    maybe_auto_publish_after_approval,
    publish_charter,
    republish_charter,
    retry_publication,
    unpublish_charter,
)
from app.agents.governance.services.dashboard_service import get_governance_bootstrap
from app.agents.governance.services.delivery_integration import promote_risk_alert_to_escalation
from app.agents.governance.services.governance_service import (
    approve_weekly_summary,
    create_action,
    create_dependency,
    create_escalation,
    create_weekly_summary,
    enriched_action_read,
    enriched_dependency_read,
    enriched_escalation_read,
    get_action_or_404,
    get_dependency_or_404,
    get_escalation_or_404,
    get_latest_weekly_summary,
    get_scope_state_for_project,
    get_weekly_summary_by_id,
    list_governance_actions_page,
    list_governance_dependencies_page,
    list_governance_escalations_page,
    list_governance_scope_states_page,
    list_weekly_summaries,
    map_action_list_row,
    map_dependency_list_row,
    map_escalation_list_row,
    resolve_dependency,
    soft_delete_action,
    soft_delete_dependency,
    soft_delete_escalation,
    update_action,
    update_dependency,
    update_escalation,
    update_scope_state,
    update_weekly_summary_draft,
)
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
from app.agents.governance.services.monitoring_service import get_governance_monitoring
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
from app.agents.governance.services.recommendation_service import (
    _to_read,
    can_generate_ai_recommendations,
    convert_governance_recommendation_to_action,
    convert_governance_recommendation_to_escalation,
    dismiss_governance_ai_recommendation,
    generate_governance_ai_recommendations,
    get_governance_ai_recommendation,
    list_governance_ai_recommendation_conversions,
    list_governance_ai_recommendations,
    submit_governance_ai_recommendation_feedback,
)
from app.agents.governance.services.register_service import list_governance_register_page
from app.agents.governance.services.summary_service import (
    build_weekly_summary_read,
    generate_weekly_governance_summary,
)
from app.agents.governance.timing import instrument_governance_routes
from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, GovernanceRecommendationEvaluationPeriod, Project
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.services.pdf_export import generate_simple_pdf

router = APIRouter(tags=["governance"])

READ_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN, AppRole.CLIENT)
WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)
CHARTER_PUBLISH_ROLES = tuple(PUBLISH_ROLES)
AI_RECOMMENDATION_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
MONITORING_ROLES = (AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


def _pagination(total: int, limit: int, offset: int, item_count: int) -> Pagination:
    return Pagination(
        limit=limit,
        offset=offset,
        total=total,
        items=item_count,
        has_more=offset + item_count < total,
    )


@router.get("/governance/bootstrap", response_model=DataResponse[GovernanceBootstrapRead])
async def governance_bootstrap(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceBootstrapRead]:
    return DataResponse(data=await get_governance_bootstrap(session, current_user))


@router.get("/governance/register", response_model=ListResponse[GovernanceRegisterRowRead])
async def list_governance_register(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID | None = None,
    status: str | None = None,
    search: str | None = None,
) -> ListResponse[GovernanceRegisterRowRead]:
    page = await list_governance_register_page(
        session,
        current_user,
        limit=limit,
        offset=offset,
        project_id=project_id,
        status=status,
        search=search,
    )
    data = page.items
    return ListResponse(
        data=data,
        pagination=_pagination(page.total, page.limit, page.offset, len(data)),
    )


@router.get("/governance/analytics/summary", response_model=DataResponse[GovernanceAnalyticsSummaryRead])
async def governance_analytics_summary(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsSummaryRead]:
    return DataResponse(
        data=await get_governance_analytics_summary(
            session,
            current_user,
            days=days,
            project_id=project_id,
            vertical=vertical,
        )
    )


@router.get("/governance/analytics/detail", response_model=DataResponse[GovernanceAnalyticsDetailRead])
async def governance_analytics_detail(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsDetailRead]:
    return DataResponse(
        data=await get_governance_analytics_detail(
            session,
            current_user,
            days=days,
            project_id=project_id,
            vertical=vertical,
        )
    )


@router.get("/governance/analytics", response_model=DataResponse[GovernanceAnalyticsRead])
async def governance_analytics(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceAnalyticsRead]:
    # TODO(deprecate): Monolithic analytics payload. The live /governance UI uses
    # GET /governance/analytics/summary + GET /governance/analytics/detail instead.
    # Keep this route for backward compatibility until external callers are confirmed gone.
    return DataResponse(
        data=await get_governance_analytics(
            session,
            current_user,
            days=days,
            project_id=project_id,
            vertical=vertical,
        )
    )


@router.get("/governance/monitoring", response_model=DataResponse[GovernanceMonitoringRead])
async def governance_monitoring(
    session: SessionDep,
    window_hours: int = 24,
    current_user: CurrentUser = Depends(require_role(*MONITORING_ROLES)),
) -> DataResponse[GovernanceMonitoringRead]:
    return DataResponse(
        data=await get_governance_monitoring(
            session,
            current_user,
            window_hours=window_hours,
        )
    )


def _analytics_csv(data: GovernanceAnalyticsRead) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "project", "metric", "value", "evidence"])
    if data.insights_kpis is not None:
        kpis = data.insights_kpis
        writer.writerow(
            [
                "insights_kpis",
                "",
                "portfolio_governance_score",
                kpis.portfolio_governance_score,
                "",
            ]
        )
        writer.writerow(
            [
                "insights_kpis",
                "",
                "recommendation_acceptance_rate_pct",
                kpis.recommendation_acceptance_rate_pct,
                "",
            ]
        )
        writer.writerow(
            [
                "insights_kpis",
                "",
                "recommendation_dismissal_rate_pct",
                kpis.recommendation_dismissal_rate_pct,
                "",
            ]
        )
        writer.writerow(
            ["insights_kpis", "", "escalations_created", kpis.escalations_created, ""]
        )
        writer.writerow(
            ["insights_kpis", "", "recommendations_created", kpis.recommendations_created, ""]
        )
        writer.writerow(["insights_kpis", "", "projects_at_risk", kpis.projects_at_risk, ""])
    for project in data.portfolio_risk_ranking:
        writer.writerow(
            [
                "portfolio_risk_ranking",
                project.project_name,
                "governance_health_score",
                project.score,
                "; ".join(item.label for item in project.evidence),
            ]
        )
    for risk in data.top_governance_risks:
        writer.writerow(
            [
                "top_governance_risks",
                risk.project_name or "",
                risk.label,
                risk.count,
                risk.detail or "",
            ]
        )
    for blocker in data.top_recurring_blockers:
        writer.writerow(
            [
                "top_recurring_blockers",
                blocker.project_name or "",
                blocker.label,
                blocker.count,
                blocker.detail or "",
            ]
        )
    for failure in data.top_recurring_mitigation_failures:
        writer.writerow(
            [
                "top_recurring_mitigation_failures",
                failure.project_name or "",
                failure.label,
                failure.count,
                failure.detail or "",
            ]
        )
    for department in data.most_affected_departments:
        writer.writerow(
            [
                "most_affected_departments",
                "",
                department.label,
                department.count,
                department.detail or "",
            ]
        )
    for cell in data.risk_heatmap:
        writer.writerow(
            [
                "risk_heatmap",
                cell.vertical,
                cell.risk_level,
                cell.project_count,
                f"avg_score={cell.avg_score}",
            ]
        )
    for recommendation in data.recommendations:
        writer.writerow(
            [
                "recommendation",
                recommendation.project_name or "",
                recommendation.title,
                recommendation.detail,
                "; ".join(item.label for item in recommendation.evidence),
            ]
        )
    return output.getvalue()


@router.get("/governance/analytics/export.csv")
async def export_governance_analytics_csv(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    data = await get_governance_analytics(
        session,
        current_user,
        days=days,
        project_id=project_id,
        vertical=vertical,
    )
    await log_governance_event(
        session,
        current_user,
        event_type="dashboard.exported",
        org_id=current_user.org_id,
        source_table="governance_analytics",
        metadata={
            "format": "csv",
            "days": data.date_range_days,
            "project_id": str(project_id) if project_id else None,
            "vertical": vertical,
        },
    )
    await session.commit()
    return Response(
        content=_analytics_csv(data),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="governance_analytics_{data.date_range_days}d.csv"'
            )
        },
    )


@router.get("/governance/analytics/export.pdf")
async def export_governance_analytics_pdf(
    session: SessionDep,
    days: int = 30,
    project_id: UUID | None = Query(default=None),
    vertical: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    data = await get_governance_analytics(
        session,
        current_user,
        days=days,
        project_id=project_id,
        vertical=vertical,
    )
    kpis = data.insights_kpis
    kpi_block = ""
    if kpis is not None:
        kpi_block = (
            "Insights KPIs\n"
            f"- Portfolio score: {kpis.portfolio_governance_score}\n"
            f"- Acceptance rate: {kpis.recommendation_acceptance_rate_pct}%\n"
            f"- Dismissal rate: {kpis.recommendation_dismissal_rate_pct}%\n"
            f"- Escalations created: {kpis.escalations_created}\n"
            f"- Recommendations created: {kpis.recommendations_created}\n"
            f"- Projects at risk: {kpis.projects_at_risk}\n\n"
        )
    body = (
        f"Generated: {data.generated_at.isoformat()}\n"
        f"Range: {data.date_range_days} days\n\n"
        f"{kpi_block}"
        "Portfolio Risk Ranking\n"
        + "\n".join(
            f"- {project.project_name}: score={project.score}, risk={project.risk_level}"
            for project in data.portfolio_risk_ranking[:10]
        )
        + "\n\nTop Governance Risks\n"
        + "\n".join(
            f"- {item.label}: count={item.count}"
            for item in data.top_governance_risks[:10]
        )
        + "\n\nTop Recurring Blockers\n"
        + "\n".join(
            f"- {item.label}: count={item.count}"
            for item in data.top_recurring_blockers[:10]
        )
        + "\n\nMost Affected Departments\n"
        + "\n".join(
            f"- {item.label}: count={item.count}"
            for item in data.most_affected_departments[:10]
        )
        + "\n\nRecommendations\n"
        + "\n".join(
            f"- {item.project_name or 'Portfolio'}: {item.title} ({item.priority})"
            for item in data.recommendations
        )
    )
    await log_governance_event(
        session,
        current_user,
        event_type="dashboard.exported",
        org_id=current_user.org_id,
        source_table="governance_analytics",
        metadata={
            "format": "pdf",
            "days": data.date_range_days,
            "project_id": str(project_id) if project_id else None,
            "vertical": vertical,
        },
    )
    await session.commit()
    return Response(
        content=generate_simple_pdf("Governance Analytics", body),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="governance_analytics_{data.date_range_days}d.pdf"'
            )
        },
    )


@router.get(
    "/projects/{project_id}/dependencies",
    response_model=ListResponse[ProjectDependencyListRead],
)
async def list_project_dependencies(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[ProjectDependencyListRead]:
    page = await list_governance_dependencies_page(
        session,
        current_user,
        limit=100,
        offset=0,
        project_id=project_id,
    )
    data = [map_dependency_list_row(row) for row in page.items]
    return ListResponse(
        data=data,
        pagination=_pagination(page.total, page.limit, page.offset, len(data)),
    )


@router.get("/governance/dependencies", response_model=ListResponse[ProjectDependencyListRead])
async def list_governance_dependencies(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    dependency_type: str | None = None,
    owner_id: UUID | None = None,
    assigned_to: UUID | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ListResponse[ProjectDependencyListRead]:
    page = await list_governance_dependencies_page(
        session,
        current_user,
        limit=limit,
        offset=offset,
        project_id=project_id,
        status=status,
        severity=severity,
        dependency_type=dependency_type,
        owner_id=owner_id,
        assigned_to=assigned_to,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    data = [map_dependency_list_row(row) for row in page.items]
    return ListResponse(
        data=data,
        pagination=_pagination(page.total, page.limit, page.offset, len(data)),
    )


@router.get("/dependencies/{dependency_id}", response_model=DataResponse[ProjectDependencyRead])
async def get_dependency(
    dependency_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await get_dependency_or_404(session, dependency_id, current_user)
    return DataResponse(data=await enriched_dependency_read(session, dep))


@router.post(
    "/projects/{project_id}/dependencies", response_model=DataResponse[ProjectDependencyRead]
)
async def create_project_dependency(
    project_id: UUID,
    payload: ProjectDependencyCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await create_dependency(
        session,
        project_id,
        current_user,
        title=payload.title,
        description=payload.description,
        dependency_type=payload.dependency_type,
        owner_id=payload.owner_id,
        due_date=payload.due_date,
        status=payload.status,
    )
    return DataResponse(
        data=ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={"overdue_days": dependency_overdue_days(dep)}
        )
    )


@router.patch("/dependencies/{dependency_id}", response_model=DataResponse[ProjectDependencyRead])
async def patch_dependency(
    dependency_id: UUID,
    payload: ProjectDependencyUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await update_dependency(
        session,
        dependency_id,
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    return DataResponse(
        data=ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={"overdue_days": dependency_overdue_days(dep)}
        )
    )


@router.post(
    "/dependencies/{dependency_id}/resolve", response_model=DataResponse[ProjectDependencyRead]
)
async def resolve_project_dependency(
    dependency_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectDependencyRead]:
    dep = await resolve_dependency(session, dependency_id, current_user)
    return DataResponse(
        data=ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={"overdue_days": 0}
        )
    )


@router.get("/governance/escalations", response_model=ListResponse[GovernanceEscalationListRead])
async def list_escalations(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    dependency_type: str | None = None,
    owner_id: UUID | None = None,
    assigned_to: UUID | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ListResponse[GovernanceEscalationListRead]:
    page = await list_governance_escalations_page(
        session,
        current_user,
        limit=limit,
        offset=offset,
        project_id=project_id,
        status=status,
        severity=severity,
        dependency_type=dependency_type,
        owner_id=owner_id,
        assigned_to=assigned_to,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    data = [map_escalation_list_row(row) for row in page.items]
    return ListResponse(
        data=data,
        pagination=_pagination(page.total, page.limit, page.offset, len(data)),
    )


@router.get(
    "/governance/escalations/{escalation_id}",
    response_model=DataResponse[GovernanceEscalationRead],
)
async def get_escalation(
    escalation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await get_escalation_or_404(session, escalation_id, current_user)
    return DataResponse(data=await enriched_escalation_read(session, escalation, current_user))


@router.get(
    "/governance/escalations/{escalation_id}/evidence",
    response_model=ListResponse[GovernanceRecordEvidenceLinkRead],
)
async def get_escalation_evidence(
    escalation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> ListResponse[GovernanceRecordEvidenceLinkRead]:
    from app.agents.governance.services.record_provenance_service import list_record_evidence_links
    from app.db.models import GovernanceRecordTargetType

    escalation = await get_escalation_or_404(session, escalation_id, current_user)
    items = await list_record_evidence_links(
        session,
        current_user,
        target_type=GovernanceRecordTargetType.ESCALATION,
        target_id=escalation.id,
        org_id=escalation.org_id,
    )
    return ListResponse(data=items)


@router.get(
    "/governance/escalations/{escalation_id}/source-recommendation",
    response_model=DataResponse[GovernanceSourceRecommendationRead | None],
)
async def get_escalation_source_recommendation(
    escalation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceSourceRecommendationRead | None]:
    from app.agents.governance.services.record_provenance_service import (
        get_source_recommendation_summary,
    )
    from app.db.models import GovernanceRecordTargetType

    escalation = await get_escalation_or_404(session, escalation_id, current_user)
    data = await get_source_recommendation_summary(
        session,
        current_user,
        target_type=GovernanceRecordTargetType.ESCALATION,
        target_id=escalation.id,
        org_id=escalation.org_id,
    )
    return DataResponse(data=data)


@router.post("/governance/escalations", response_model=DataResponse[GovernanceEscalationRead])
async def create_governance_escalation(
    payload: GovernanceEscalationCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await create_escalation(
        session,
        current_user,
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        status=payload.status,
        assigned_to=payload.assigned_to,
        source_type=payload.source_type,
        source_id=payload.source_id,
    )
    return DataResponse(
        data=GovernanceEscalationRead.model_validate(escalation, from_attributes=True)
    )


@router.patch(
    "/governance/escalations/{escalation_id}", response_model=DataResponse[GovernanceEscalationRead]
)
async def patch_escalation(
    escalation_id: UUID,
    payload: GovernanceEscalationUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await update_escalation(
        session,
        escalation_id,
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    return DataResponse(
        data=GovernanceEscalationRead.model_validate(escalation, from_attributes=True)
    )


@router.get("/governance/actions", response_model=ListResponse[GovernanceActionListRead])
async def list_governance_actions(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    dependency_type: str | None = None,
    owner_id: UUID | None = None,
    assigned_to: UUID | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ListResponse[GovernanceActionListRead]:
    page = await list_governance_actions_page(
        session,
        current_user,
        limit=limit,
        offset=offset,
        project_id=project_id,
        status=status,
        severity=severity,
        dependency_type=dependency_type,
        owner_id=owner_id,
        assigned_to=assigned_to,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    data = [map_action_list_row(row) for row in page.items]
    return ListResponse(
        data=data,
        pagination=_pagination(page.total, page.limit, page.offset, len(data)),
    )


@router.get(
    "/governance/actions/{action_id}",
    response_model=DataResponse[GovernanceActionRead],
)
async def get_action(
    action_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceActionRead]:
    action = await get_action_or_404(session, action_id, current_user)
    return DataResponse(data=await enriched_action_read(session, action, current_user))


@router.get(
    "/governance/actions/{action_id}/evidence",
    response_model=ListResponse[GovernanceRecordEvidenceLinkRead],
)
async def get_action_evidence(
    action_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> ListResponse[GovernanceRecordEvidenceLinkRead]:
    from app.agents.governance.services.record_provenance_service import list_record_evidence_links
    from app.db.models import GovernanceRecordTargetType

    action = await get_action_or_404(session, action_id, current_user)
    items = await list_record_evidence_links(
        session,
        current_user,
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=action.id,
        org_id=action.org_id,
    )
    return ListResponse(data=items)


@router.get(
    "/governance/actions/{action_id}/source-recommendation",
    response_model=DataResponse[GovernanceSourceRecommendationRead | None],
)
async def get_action_source_recommendation(
    action_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceSourceRecommendationRead | None]:
    from app.agents.governance.services.record_provenance_service import (
        get_source_recommendation_summary,
    )
    from app.db.models import GovernanceRecordTargetType

    action = await get_action_or_404(session, action_id, current_user)
    data = await get_source_recommendation_summary(
        session,
        current_user,
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=action.id,
        org_id=action.org_id,
    )
    return DataResponse(data=data)


@router.post("/governance/actions", response_model=DataResponse[GovernanceActionRead])
async def create_governance_action(
    payload: GovernanceActionCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceActionRead]:
    action = await create_action(
        session,
        current_user,
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        owner_id=payload.owner_id,
        due_date=payload.due_date,
        status=payload.status,
        linked_knowledge_document_id=payload.linked_knowledge_document_id,
    )
    return DataResponse(
        data=GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
            update={"status": effective_action_status(action)}
        )
    )


@router.patch("/governance/actions/{action_id}", response_model=DataResponse[GovernanceActionRead])
async def patch_governance_action(
    action_id: UUID,
    payload: GovernanceActionUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceActionRead]:
    action = await update_action(
        session,
        action_id,
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    return DataResponse(
        data=GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
            update={"status": effective_action_status(action)}
        )
    )


@router.get("/projects/{project_id}/scope", response_model=DataResponse[ProjectScopeStateRead])
async def get_project_scope(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[ProjectScopeStateRead]:
    scope = await get_scope_state_for_project(session, project_id, current_user)
    return DataResponse(data=ProjectScopeStateRead.model_validate(scope, from_attributes=True))


@router.get("/governance/scope-states", response_model=ListResponse[ProjectScopeStateRead])
async def list_governance_scope_states(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    dependency_type: str | None = None,
    owner_id: UUID | None = None,
    assigned_to: UUID | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ListResponse[ProjectScopeStateRead]:
    page = await list_governance_scope_states_page(
        session,
        current_user,
        limit=limit,
        offset=offset,
        project_id=project_id,
        status=status,
        severity=severity,
        dependency_type=dependency_type,
        owner_id=owner_id,
        assigned_to=assigned_to,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    scopes = page.items
    data = [ProjectScopeStateRead.model_validate(scope, from_attributes=True) for scope in scopes]
    return ListResponse(
        data=data,
        pagination=_pagination(page.total, page.limit, page.offset, len(data)),
    )


@router.patch("/projects/{project_id}/scope", response_model=DataResponse[ProjectScopeStateRead])
async def patch_project_scope(
    project_id: UUID,
    payload: ProjectScopeStateUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectScopeStateRead]:
    scope = await update_scope_state(
        session,
        project_id,
        current_user,
        scope_status=payload.scope_status,
        version_label=payload.version_label,
        notes=payload.notes,
        linked_charter_document_id=payload.linked_charter_document_id,
    )
    return DataResponse(data=ProjectScopeStateRead.model_validate(scope, from_attributes=True))


@router.get(
    "/governance/project-charters",
    response_model=ListResponse[ProjectCharterRead],
)
async def list_governance_project_charters(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    project_id: UUID | None = None,
    limit: int = 50,
) -> ListResponse[ProjectCharterRead]:
    rows = await list_project_charters(
        session,
        current_user,
        project_id=project_id,
        limit=limit,
    )
    reads = [await build_project_charter_read(session, row) for row in rows]
    return ListResponse(data=reads, pagination=Pagination(limit=limit))


@router.get(
    "/governance/project-charters/{charter_id}",
    response_model=DataResponse[ProjectCharterRead],
)
async def get_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await get_project_charter_or_404(session, charter_id, current_user)
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/generate",
    response_model=DataResponse[ProjectCharterRead],
)
async def generate_governance_project_charter(
    payload: ProjectCharterGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await generate_project_charter(
        session,
        current_user,
        project_id=payload.project_id,
        visibility=payload.visibility,
    )
    await log_governance_event(
        session,
        current_user,
        event_type="charter.generated",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={
            "version": charter.version,
            "status": charter.status.value,
            "generated_by_ai": charter.generated_by_ai,
            "visibility": charter.visibility.value,
        },
    )
    await session.commit()
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.patch(
    "/governance/project-charters/{charter_id}",
    response_model=DataResponse[ProjectCharterRead],
)
async def patch_governance_project_charter(
    charter_id: UUID,
    payload: ProjectCharterUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await update_project_charter_draft(
        session,
        charter_id,
        current_user,
        generated_text=payload.generated_text,
        visibility=payload.visibility,
    )
    await log_governance_event(
        session,
        current_user,
        event_type="charter.updated",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={"version": charter.version, "status": charter.status.value},
    )
    await session.commit()
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/approve",
    response_model=DataResponse[ProjectCharterRead],
)
async def approve_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await approve_project_charter(session, charter_id, current_user)
    await log_governance_event(
        session,
        current_user,
        event_type="charter.approved",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={"version": charter.version, "status": charter.status.value},
    )
    await session.commit()
    # Auto-publish is best-effort; approval is already committed and never rolled back.
    charter = await maybe_auto_publish_after_approval(session, current_user, charter)
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/publish",
    response_model=DataResponse[ProjectCharterRead],
)
async def publish_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await publish_charter(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/republish",
    response_model=DataResponse[ProjectCharterRead],
)
async def republish_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await republish_charter(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/retry-publication",
    response_model=DataResponse[ProjectCharterRead],
)
async def retry_governance_project_charter_publication(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await retry_publication(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.post(
    "/governance/project-charters/{charter_id}/unpublish",
    response_model=DataResponse[ProjectCharterRead],
)
async def unpublish_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    payload: CharterPublicationActionRequest | None = None,
    current_user: CurrentUser = Depends(require_role(*CHARTER_PUBLISH_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[ProjectCharterRead]:
    charter = await unpublish_charter(
        session,
        current_user,
        charter_id,
        reason=payload.reason if payload else None,
    )
    return DataResponse(data=await build_project_charter_read(session, charter))


@router.get(
    "/governance/project-charters/{charter_id}/publication-status",
    response_model=DataResponse[CharterPublicationStatusRead],
)
async def get_governance_project_charter_publication_status(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[CharterPublicationStatusRead]:
    status = await get_publish_status(session, current_user, charter_id)
    return DataResponse(data=CharterPublicationStatusRead.model_validate(status))


@router.get(
    "/governance/project-charters/{charter_id}/knowledge",
    response_model=DataResponse[CharterKnowledgeLinkRead],
)
async def get_governance_project_charter_knowledge(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[CharterKnowledgeLinkRead]:
    link = await get_charter_knowledge_link(session, current_user, charter_id)
    return DataResponse(data=CharterKnowledgeLinkRead.model_validate(link))


@router.get(
    "/governance/project-charters/{charter_id}/versions",
    response_model=ListResponse[CharterPublicationVersionRead],
)
async def get_governance_project_charter_versions(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[CharterPublicationVersionRead]:
    versions = await get_publication_versions(session, current_user, charter_id)
    reads = [CharterPublicationVersionRead.model_validate(row) for row in versions]
    return ListResponse(data=reads, pagination=Pagination(limit=len(reads), items=len(reads)))


@router.get(
    "/governance/project-charters/{charter_id}/publication-timeline",
    response_model=ListResponse[CharterPublicationEventRead],
)
async def get_governance_project_charter_publication_timeline(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> ListResponse[CharterPublicationEventRead]:
    events = await list_charter_publication_timeline(session, current_user, charter_id)
    reads = [
        CharterPublicationEventRead.model_validate(event, from_attributes=True)
        for event in events
    ]
    return ListResponse(data=reads, pagination=Pagination(limit=len(reads), items=len(reads)))


@router.post(
    "/governance/project-charters/{charter_id}/archive",
    response_model=DataResponse[ProjectCharterRead],
)
async def archive_governance_project_charter(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[ProjectCharterRead]:
    charter = await archive_project_charter(session, charter_id, current_user)
    await log_governance_event(
        session,
        current_user,
        event_type="charter.archived",
        org_id=charter.org_id,
        project_id=charter.project_id,
        source_table="project_charters",
        source_id=charter.id,
        new_values={"version": charter.version, "status": charter.status.value},
    )
    await session.commit()
    return DataResponse(data=await build_project_charter_read(session, charter))


def _safe_charter_filename(project_name: str, version: str, extension: str) -> str:
    safe_project = "".join(ch if ch.isalnum() else "_" for ch in project_name).strip("_")
    safe_project = safe_project or "project"
    safe_version = "".join(ch if ch.isalnum() else "_" for ch in version).strip("_")
    return f"{safe_project}_charter_{safe_version}.{extension}"


async def _charter_export_payload(
    session: SessionDep,
    charter_id: UUID,
    current_user: CurrentUser,
) -> tuple[ProjectCharterRead, CharterExportDocument]:
    charter = await get_project_charter_or_404(session, charter_id, current_user)
    read = await build_project_charter_read(session, charter)
    project = (
        await session.execute(select(Project).where(Project.id == charter.project_id))
    ).scalar_one_or_none()
    project_name = project.name if project else read.project_name or "Project"
    title = f"{project_name} Project Charter {read.version}"
    metadata = [
        ("Project", project_name),
        ("Version", read.version),
        ("Status", read.status.value.replace("_", " ").title()),
        ("Generated", read.created_at.strftime("%b %d, %Y")),
        ("Visibility", read.visibility.value.replace("_", " ").title()),
    ]
    if read.generated_by_ai:
        metadata.append(("Generated By", "AI"))
    metadata.extend(
        [
            ("Approved", read.approved_at.strftime("%b %d, %Y") if read.approved_at else "Pending"),
            ("Approved By", read.approved_by_name or "Pending"),
        ]
    )
    return read, CharterExportDocument(
        title=title,
        metadata=metadata,
        markdown=read.generated_text,
    )


@router.get("/governance/project-charters/{charter_id}/export.pdf")
async def export_governance_project_charter_pdf(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    read, document = await _charter_export_payload(session, charter_id, current_user)
    filename = _safe_charter_filename(read.project_name or "project", read.version, "pdf")
    await log_governance_event(
        session,
        current_user,
        event_type="charter.exported",
        org_id=read.org_id,
        project_id=read.project_id,
        source_table="project_charters",
        source_id=read.id,
        metadata={"format": "pdf", "version": read.version},
    )
    await session.commit()
    return Response(
        content=generate_charter_pdf(document),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/governance/project-charters/{charter_id}/export.docx")
async def export_governance_project_charter_docx(
    charter_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> Response:
    read, document = await _charter_export_payload(session, charter_id, current_user)
    filename = _safe_charter_filename(read.project_name or "project", read.version, "docx")
    await log_governance_event(
        session,
        current_user,
        event_type="charter.exported",
        org_id=read.org_id,
        project_id=read.project_id,
        source_table="project_charters",
        source_id=read.id,
        metadata={"format": "docx", "version": read.version},
    )
    await session.commit()
    return Response(
        content=generate_charter_docx(document),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/governance/weekly-summary", response_model=DataResponse[GovernanceWeeklySummaryRead | None]
)
async def get_weekly_summary(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead | None]:
    summary = await get_latest_weekly_summary(session, current_user)
    if summary is None:
        return DataResponse(data=None)
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.get(
    "/governance/weekly-summaries",
    response_model=ListResponse[GovernanceWeeklySummaryRead],
)
async def list_governance_weekly_summaries(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
    pagination: Pagination = Depends(),
) -> ListResponse[GovernanceWeeklySummaryRead]:
    rows = await list_weekly_summaries(session, current_user, limit=pagination.limit)
    reads = [await build_weekly_summary_read(session, row) for row in rows]
    return ListResponse(data=reads, meta={"total": len(reads)})


@router.get(
    "/governance/weekly-summary/{summary_id}",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def get_governance_weekly_summary_by_id(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await get_weekly_summary_by_id(session, summary_id, current_user)
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post(
    "/governance/weekly-summary/generate",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def generate_governance_weekly_summary(
    payload: GovernanceWeeklySummaryGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await generate_weekly_governance_summary(
        session,
        current_user,
        summary_week=payload.summary_week,
    )
    await log_governance_event(
        session,
        current_user,
        event_type="weekly_summary.generated",
        org_id=summary.org_id,
        source_table="governance_weekly_summaries",
        source_id=summary.id,
        new_values={
            "summary_week": summary.summary_week.isoformat(),
            "status": summary.status.value,
            "generated_by_ai": summary.generated_by_ai,
        },
    )
    await session.commit()
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.patch(
    "/governance/weekly-summary/{summary_id}",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def patch_governance_weekly_summary(
    summary_id: UUID,
    payload: GovernanceWeeklySummaryUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await update_weekly_summary_draft(
        session,
        summary_id,
        current_user,
        summary_text=payload.summary_text,
    )
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post(
    "/governance/weekly-summary/{summary_id}/approve",
    response_model=DataResponse[GovernanceWeeklySummaryRead],
)
async def approve_governance_weekly_summary(
    summary_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await approve_weekly_summary(session, summary_id, current_user)
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.post(
    "/governance/escalations/promote-from-risk-alert",
    response_model=DataResponse[GovernanceEscalationRead],
)
async def promote_escalation_from_risk_alert(
    payload: PromoteRiskAlertRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await promote_risk_alert_to_escalation(
        session,
        current_user,
        risk_alert_id=payload.risk_alert_id,
    )
    await log_governance_event(
        session,
        current_user,
        event_type="escalation.promoted_from_delivery_risk",
        org_id=escalation.org_id,
        project_id=escalation.project_id,
        source_table="governance_escalations",
        source_id=escalation.id,
        new_values={
            "title": escalation.title,
            "severity": escalation.severity.value,
            "status": escalation.status.value,
            "source_type": escalation.source_type.value if escalation.source_type else None,
            "source_id": str(escalation.source_id) if escalation.source_id else None,
        },
    )
    await session.commit()
    return DataResponse(
        data=GovernanceEscalationRead.model_validate(escalation, from_attributes=True)
    )


@router.delete("/dependencies/{dependency_id}", status_code=204)
async def delete_dependency(
    dependency_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_dependency(session, dependency_id, current_user)
    return Response(status_code=204)


@router.delete("/governance/escalations/{escalation_id}", status_code=204)
async def delete_escalation(
    escalation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_escalation(session, escalation_id, current_user)
    return Response(status_code=204)


@router.delete("/governance/actions/{action_id}", status_code=204)
async def delete_action(
    action_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_action(session, action_id, current_user)
    return Response(status_code=204)


@router.post("/governance/weekly-summary", response_model=DataResponse[GovernanceWeeklySummaryRead])
async def post_weekly_summary(
    payload: GovernanceWeeklySummaryCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceWeeklySummaryRead]:
    summary = await create_weekly_summary(
        session,
        current_user,
        summary_week=payload.summary_week,
        summary_text=payload.summary_text,
        evidence_links=payload.evidence_links,
    )
    return DataResponse(data=await build_weekly_summary_read(session, summary))


@router.get(
    "/governance/ai-recommendations",
    response_model=DataResponse[GovernanceAIRecommendationListRead],
)
async def get_governance_ai_recommendations(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    project_id: UUID | None = Query(default=None),
    scope: str = Query(default="project"),
    status: str | None = Query(default="active"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DataResponse[GovernanceAIRecommendationListRead]:
    from app.db.models import (
        GovernanceAIRecommendationScope,
        GovernanceAIRecommendationStatus,
    )

    scope_enum = GovernanceAIRecommendationScope(scope)
    status_enum = GovernanceAIRecommendationStatus(status) if status else None
    data = await list_governance_ai_recommendations(
        session,
        current_user,
        project_id=project_id,
        scope=scope_enum,
        status=status_enum,
        limit=limit,
        offset=offset,
        include_rule_based=False,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/ai-recommendations/{recommendation_id}",
    response_model=DataResponse[GovernanceAIRecommendationRead],
)
async def get_one_governance_ai_recommendation(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[GovernanceAIRecommendationRead]:
    from app.agents.governance.services.governance_service import load_project_names

    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    names = await load_project_names(session, {row.project_id} if row.project_id else set())
    return DataResponse(
        data=_to_read(
            row,
            project_name=names.get(row.project_id) if row.project_id else None,
            can_generate=can_generate_ai_recommendations(current_user),
        )
    )


@router.post(
    "/governance/ai-recommendations/generate",
    response_model=DataResponse[GovernanceAIRecommendationGenerationResult],
)
async def post_generate_governance_ai_recommendations(
    payload: GovernanceAIRecommendationGenerateRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationGenerationResult]:
    result = await generate_governance_ai_recommendations(
        session,
        current_user,
        project_id=payload.project_id,
        scope=payload.scope,
        force=payload.force,
    )
    return DataResponse(data=result)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/regenerate",
    response_model=DataResponse[GovernanceAIRecommendationGenerationResult],
)
async def post_regenerate_governance_ai_recommendation(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationGenerationResult]:
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    result = await generate_governance_ai_recommendations(
        session,
        current_user,
        project_id=row.project_id,
        scope=row.scope,
        force=True,
    )
    return DataResponse(data=result)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/dismiss",
    response_model=DataResponse[GovernanceAIRecommendationRead],
)
async def post_dismiss_governance_ai_recommendation(
    recommendation_id: UUID,
    payload: GovernanceAIRecommendationDismissRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationRead]:
    data = await dismiss_governance_ai_recommendation(
        session,
        current_user,
        recommendation_id,
        reason=payload.reason,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/feedback",
    response_model=DataResponse[GovernanceAIRecommendationFeedbackRead],
)
async def post_governance_ai_recommendation_feedback(
    recommendation_id: UUID,
    payload: GovernanceAIRecommendationFeedbackRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationFeedbackRead]:
    data = await submit_governance_ai_recommendation_feedback(
        session,
        current_user,
        recommendation_id,
        helpful=payload.helpful,
        reason=payload.reason,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/convert/action",
    response_model=DataResponse[GovernanceRecommendationConversionRead],
)
async def post_convert_governance_ai_recommendation_to_action(
    recommendation_id: UUID,
    payload: ConvertRecommendationToActionRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationConversionRead]:
    data = await convert_governance_recommendation_to_action(
        session,
        current_user,
        recommendation_id,
        payload,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/convert/escalation",
    response_model=DataResponse[GovernanceRecommendationConversionRead],
)
async def post_convert_governance_ai_recommendation_to_escalation(
    recommendation_id: UUID,
    payload: ConvertRecommendationToEscalationRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceRecommendationConversionRead]:
    data = await convert_governance_recommendation_to_escalation(
        session,
        current_user,
        recommendation_id,
        payload,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/ai-recommendations/{recommendation_id}/conversions",
    response_model=DataResponse[list[GovernanceRecommendationConversionRead]],
)
async def get_governance_ai_recommendation_conversions(
    recommendation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
) -> DataResponse[list[GovernanceRecommendationConversionRead]]:
    data = await list_governance_ai_recommendation_conversions(
        session,
        current_user,
        recommendation_id,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/escalation-suggestions/scan",
    response_model=DataResponse[EscalationSuggestionScanResult],
)
async def post_scan_escalation_suggestions(
    payload: EscalationSuggestionScanRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[EscalationSuggestionScanResult]:
    from app.agents.governance.services.escalation_suggestion_service import (
        scan_governance_escalation_suggestions,
    )

    data = await scan_governance_escalation_suggestions(
        session,
        current_user,
        project_id=payload.project_id,
        force=payload.force,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/escalation-suggestions",
    response_model=DataResponse[list[GovernanceAIRecommendationRead]],
)
async def get_escalation_suggestions(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default="active"),
    trigger_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DataResponse[list[GovernanceAIRecommendationRead]]:
    from app.agents.governance.services.escalation_suggestion_service import (
        list_escalation_suggestions,
    )
    from app.db.models import (
        GovernanceAIRecommendationStatus,
        GovernanceEscalationTriggerType,
    )

    status_enum = GovernanceAIRecommendationStatus(status) if status else None
    trigger_enum = GovernanceEscalationTriggerType(trigger_type) if trigger_type else None
    data = await list_escalation_suggestions(
        session,
        current_user,
        project_id=project_id,
        status=status_enum,
        trigger_type=trigger_enum,
        limit=limit,
        offset=offset,
    )
    return DataResponse(data=data)


@router.get(
    "/governance/escalation-suggestions/scans",
    response_model=DataResponse[list[EscalationSuggestionScanHistoryRead]],
)
async def get_escalation_suggestion_scans(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> DataResponse[list[EscalationSuggestionScanHistoryRead]]:
    from app.agents.governance.services.escalation_suggestion_service import (
        list_escalation_suggestion_scans,
    )

    rows = await list_escalation_suggestion_scans(
        session,
        current_user,
        project_id=project_id,
        limit=limit,
    )
    return DataResponse(
        data=[EscalationSuggestionScanHistoryRead.model_validate(row) for row in rows]
    )


@router.post(
    "/governance/escalation-suggestions/{suggestion_id}/snooze",
    response_model=DataResponse[GovernanceAIRecommendationRead],
)
async def post_snooze_escalation_suggestion(
    suggestion_id: UUID,
    payload: EscalationSuggestionSnoozeRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationRead]:
    from app.agents.governance.services.escalation_suggestion_service import (
        snooze_escalation_suggestion,
    )

    data = await snooze_escalation_suggestion(
        session,
        current_user,
        suggestion_id,
        payload,
    )
    return DataResponse(data=data)


@router.post(
    "/governance/ai-recommendations/{recommendation_id}/snooze",
    response_model=DataResponse[GovernanceAIRecommendationRead],
)
async def post_snooze_ai_recommendation(
    recommendation_id: UUID,
    payload: EscalationSuggestionSnoozeRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*AI_RECOMMENDATION_ROLES)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[GovernanceAIRecommendationRead]:
    from app.agents.governance.services.escalation_suggestion_service import (
        snooze_escalation_suggestion,
    )

    data = await snooze_escalation_suggestion(
        session,
        current_user,
        recommendation_id,
        payload,
    )
    return DataResponse(data=data)


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
        _effectiveness_filters(days=days, project_id=project_id, vertical=vertical, trigger_type=trigger_type),
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
        return Response(
            content=report.model_dump_json(),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="governance_recommendation_effectiveness_{report.date_range_days}d.json"'
                )
            },
        )
    if format == "pdf":
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
            headers={
                "Content-Disposition": (
                    f'attachment; filename="governance_recommendation_effectiveness_{report.date_range_days}d.pdf"'
                )
            },
        )
    return Response(
        content=effectiveness_report_csv(report),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="governance_recommendation_effectiveness_{report.date_range_days}d.csv"'
            )
        },
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


# ---------------------------------------------------------------------------
# Phase 13 — Controlled Recommendation Optimization
# ---------------------------------------------------------------------------


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
        raise HTTPException(status_code=400, detail="period must be weekly, monthly, or quarterly") from exc
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
        import json

        return Response(
            content=json.dumps(report.model_dump(mode="json"), indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="governance_optimization_report_{report_id}.json"'
            },
        )
    if format == "pdf":
        lines = [
            f"Period: {report.period}",
            f"Range: {report.period_start} – {report.period_end}",
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
            headers={
                "Content-Disposition": f'attachment; filename="governance_optimization_report_{report_id}.pdf"'
            },
        )
    return Response(
        content=optimization_report_csv(report),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="governance_optimization_report_{report_id}.csv"'
        },
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
    data = await convert_recommendation_lifecycle(
        session, current_user, recommendation_id, payload
    )
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
    data = await cancel_recommendation_resolution(
        session, current_user, recommendation_id, payload
    )
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
    data = await approve_learning_rule(
        session, current_user, rule_id, activate=payload.activate
    )
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
