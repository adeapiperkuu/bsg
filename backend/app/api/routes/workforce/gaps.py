from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import LimitQuery, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    CapabilityGapDetectionResponse,
    CapabilityGapRead,
    CapabilityGapUpdate,
    WorkforceRecommendationGenerateResponse,
)
from app.services.scoping import get_visible_project
from app.services.workforce_gaps import (
    detect_and_persist_capability_gaps,
    generate_workforce_recommendations,
    get_capability_gap_or_404,
    list_project_capability_gaps,
    soft_delete_capability_gap,
    update_capability_gap,
)

router = APIRouter()


@router.get("/projects/{project_id}/capability-gaps", response_model=ListResponse[CapabilityGapRead])
async def list_capability_gaps_route(
    project_id: UUID,
    session: SessionDep,
    limit: LimitQuery = 50,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
) -> ListResponse[CapabilityGapRead]:
    project = await get_visible_project(session, project_id, current_user)
    gaps = await list_project_capability_gaps(session, project, current_user)
    page = gaps[:limit]
    return ListResponse(
        data=page,
        pagination=Pagination(total=len(gaps), limit=limit, offset=0),
    )


@router.post(
    "/projects/{project_id}/capability-gaps/detect",
    response_model=DataResponse[CapabilityGapDetectionResponse],
)
async def detect_capability_gaps_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CapabilityGapDetectionResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await detect_and_persist_capability_gaps(session, project, current_user)
    await session.commit()
    return DataResponse(data=result)


@router.patch("/capability-gaps/{gap_id}", response_model=DataResponse[CapabilityGapRead])
async def update_capability_gap_route(
    gap_id: UUID,
    payload: CapabilityGapUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CapabilityGapRead]:
    gap = await get_capability_gap_or_404(session, gap_id, current_user, for_mutation=True)
    updated = await update_capability_gap(session, gap, payload, current_user)
    await session.commit()
    return DataResponse(data=updated)


@router.delete("/capability-gaps/{gap_id}", status_code=204)
async def delete_capability_gap_route(
    gap_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    gap = await get_capability_gap_or_404(session, gap_id, current_user, for_mutation=True)
    await soft_delete_capability_gap(session, gap)
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/projects/{project_id}/workforce-recommendations/generate",
    response_model=DataResponse[WorkforceRecommendationGenerateResponse],
)
async def generate_workforce_recommendations_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[WorkforceRecommendationGenerateResponse]:
    project = await get_visible_project(session, project_id, current_user)
    created_count, recommendations = await generate_workforce_recommendations(
        session,
        project,
        current_user,
    )
    await session.commit()
    return DataResponse(
        data=WorkforceRecommendationGenerateResponse(
            project_id=project.id,
            recommendations_created=created_count,
            recommendations=recommendations,
        ),
    )
