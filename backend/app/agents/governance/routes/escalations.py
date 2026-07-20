from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.agents.governance.schemas.governance import (
    GovernanceEscalationCreate,
    GovernanceEscalationListRead,
    GovernanceEscalationRead,
    GovernanceEscalationUpdate,
    GovernanceRecordEvidenceLinkRead,
    GovernanceSourceRecommendationRead,
    PromoteRiskAlertRequest,
    PublishClientEscalationSummaryRequest,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.delivery_integration import promote_risk_alert_to_escalation
from app.agents.governance.services.governance_service import (
    create_escalation,
    enriched_escalation_read,
    get_escalation_or_404,
    list_governance_escalations_page,
    map_escalation_list_row,
    publish_client_escalation_summary,
    soft_delete_escalation,
    update_escalation,
)
from app.agents.governance.timing import instrument_governance_routes
from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse, ListResponse, Pagination

router = APIRouter(tags=["governance"])

READ_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
    AppRole.CLIENT,
)
WRITE_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)
AI_RECOMMENDATION_ROLES = (
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
)


def _pagination(total: int, limit: int, offset: int, item_count: int) -> Pagination:
    return Pagination(
        limit=limit,
        offset=offset,
        total=total,
        items=item_count,
        has_more=offset + item_count < total,
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
    data = [
        map_escalation_list_row(row, for_client=current_user.role == AppRole.CLIENT)
        for row in page.items
    ]
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


@router.post(
    "/governance/escalations/{escalation_id}/publish-client-summary",
    response_model=DataResponse[GovernanceEscalationRead],
)
async def publish_escalation_client_summary(
    escalation_id: UUID,
    payload: PublishClientEscalationSummaryRequest,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> DataResponse[GovernanceEscalationRead]:
    escalation = await publish_client_escalation_summary(
        session,
        escalation_id,
        current_user,
        client_summary=payload.client_summary,
        client_visible=payload.client_visible,
    )
    return DataResponse(data=await enriched_escalation_read(session, escalation, current_user))


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


@router.delete("/governance/escalations/{escalation_id}", status_code=204)
async def delete_escalation(
    escalation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_escalation(session, escalation_id, current_user)
    return Response(status_code=204)


instrument_governance_routes(router)
