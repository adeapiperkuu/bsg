from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, Organisation
from app.schemas.domain import OrganisationCreate, OrganisationUpdate


async def get_organisation_or_404(session: AsyncSession, org_id: UUID) -> Organisation:
    org = (
        await session.execute(
            select(Organisation).where(Organisation.id == org_id, Organisation.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if org is None:
        raise ApiError(404, "NOT_FOUND", "Organisation was not found.")
    return org


async def create_organisation(session: AsyncSession, payload: OrganisationCreate) -> Organisation:
    org = Organisation(**payload.model_dump())
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def update_organisation(
    session: AsyncSession,
    org: Organisation,
    payload: OrganisationUpdate,
) -> Organisation:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(org, key, value)
    await session.commit()
    await session.refresh(org)
    return org


async def deactivate_organisation(session: AsyncSession, org: Organisation) -> Organisation:
    org.is_active = False
    org.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(org)
    return org


def assert_can_manage_organisations(actor: CurrentUser) -> None:
    if actor.role != AppRole.SUPER_ADMIN:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
