from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.agents.governance.analytics.sla import dependency_overdue_days
from app.agents.governance.schemas.governance import (
    ProjectDependencyCreate,
    ProjectDependencyListRead,
    ProjectDependencyRead,
    ProjectDependencyUpdate,
)
from app.agents.governance.services.governance_service import (
    create_dependency,
    enriched_dependency_read,
    get_dependency_or_404,
    list_governance_dependencies_page,
    map_dependency_list_row,
    resolve_dependency,
    soft_delete_dependency,
    update_dependency,
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


def _pagination(total: int, limit: int, offset: int, item_count: int) -> Pagination:
    return Pagination(
        limit=limit,
        offset=offset,
        total=total,
        items=item_count,
        has_more=offset + item_count < total,
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


@router.delete("/dependencies/{dependency_id}", status_code=204)
async def delete_dependency(
    dependency_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(*WRITE_ROLES)),
) -> Response:
    await soft_delete_dependency(session, dependency_id, current_user)
    return Response(status_code=204)


instrument_governance_routes(router)
