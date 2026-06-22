from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.security import require_role
from app.db.models import AppRole, Organisation
from app.schemas.common import ListResponse, Pagination
from app.schemas.domain import OrganisationRead

router = APIRouter(tags=["organisations"])


@router.get("/organisations", response_model=ListResponse[OrganisationRead])
async def list_organisations(
    session: SessionDep,
    _ = Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[OrganisationRead]:
    rows = (
        await session.execute(
            select(Organisation).where(Organisation.deleted_at.is_(None)).order_by(Organisation.name)
        )
    ).scalars()
    return ListResponse(data=[OrganisationRead.model_validate(row) for row in rows], pagination=Pagination(limit=100))
