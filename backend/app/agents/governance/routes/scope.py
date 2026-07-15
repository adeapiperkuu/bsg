from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.agents.governance.schemas.governance import (
    ProjectScopeStateRead,
    ProjectScopeStateUpdate,
)
from app.agents.governance.services.governance_service import (
    get_scope_state_for_project,
    list_governance_scope_states_page,
    update_scope_state,
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


instrument_governance_routes(router)
