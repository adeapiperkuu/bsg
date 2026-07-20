from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.agents.governance.analytics.sla import effective_action_status
from app.agents.governance.schemas.governance import (
    GovernanceActionCreate,
    GovernanceActionListRead,
    GovernanceActionRead,
    GovernanceActionUpdate,
    GovernanceRecordEvidenceLinkRead,
    GovernanceSourceRecommendationRead,
)
from app.agents.governance.services.governance_service import (
    create_action,
    enriched_action_read,
    get_action_or_404,
    list_governance_actions_page,
    map_action_list_row,
    soft_delete_action,
    update_action,
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


@router.delete("/governance/actions/{action_id}", status_code=204)
async def delete_action(
    action_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_action(session, action_id, current_user)
    return Response(status_code=204)


instrument_governance_routes(router)
