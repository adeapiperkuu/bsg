from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.security import require_role
from app.db.models import AppRole, ClientCsatScore
from app.schemas.common import DataResponse
from app.schemas.domain import ClientCsatCreate
from app.services.scoping import get_visible_project

router = APIRouter(tags=["csat"])


@router.post("/projects/{project_id}/csat")
async def submit_csat(
    project_id: UUID,
    payload: ClientCsatCreate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.CLIENT)),
) -> DataResponse[dict[str, str]]:
    project = await get_visible_project(session, project_id, current_user)
    score = ClientCsatScore(
        project_id=project.id,
        org_id=project.org_id,
        submitted_by=current_user.id,
        **payload.model_dump(),
    )
    session.add(score)
    await session.commit()
    await session.refresh(score)
    return DataResponse(data={"id": str(score.id)})
