from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, Organisation
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import OrganisationCreate, OrganisationRead, OrganisationUpdate
from app.services.organisations import (
    assert_can_manage_organisations,
    create_organisation,
    deactivate_organisation,
    get_organisation_or_404,
    update_organisation,
)

router = APIRouter(tags=["organisations"])


@router.get("/organisations", response_model=ListResponse[OrganisationRead])
async def list_organisations(
    session: SessionDep,
    _current_user: CurrentUser = Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[OrganisationRead]:
    rows = (
        await session.execute(
            select(Organisation).where(Organisation.deleted_at.is_(None)).order_by(Organisation.name)
        )
    ).scalars()
    return ListResponse(data=[OrganisationRead.model_validate(row) for row in rows], pagination=Pagination(limit=100))


@router.get("/organisations/{org_id}", response_model=DataResponse[OrganisationRead])
async def get_organisation(
    org_id: UUID,
    session: SessionDep,
    _current_user: CurrentUser = Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[OrganisationRead]:
    org = await get_organisation_or_404(session, org_id)
    return DataResponse(data=OrganisationRead.model_validate(org))


@router.post("/organisations", response_model=DataResponse[OrganisationRead])
async def create_organisation_route(
    payload: OrganisationCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[OrganisationRead]:
    assert_can_manage_organisations(current_user)
    org = await create_organisation(session, payload)
    return DataResponse(data=OrganisationRead.model_validate(org))


@router.patch("/organisations/{org_id}", response_model=DataResponse[OrganisationRead])
async def update_organisation_route(
    org_id: UUID,
    payload: OrganisationUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[OrganisationRead]:
    assert_can_manage_organisations(current_user)
    org = await get_organisation_or_404(session, org_id)
    org = await update_organisation(session, org, payload)
    return DataResponse(data=OrganisationRead.model_validate(org))


@router.delete("/organisations/{org_id}", status_code=204)
async def delete_organisation_route(
    org_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> Response:
    assert_can_manage_organisations(current_user)
    org = await get_organisation_or_404(session, org_id)
    await deactivate_organisation(session, org)
    return Response(status_code=204)
