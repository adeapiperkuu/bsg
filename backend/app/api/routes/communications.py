from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, ClientCommunication, CommunicationEvidenceLink, CommunicationStatus, ThroughputSnapshot
from app.schemas.common import DataResponse, EvidenceLinkRead, ListResponse, Pagination
from app.schemas.domain import CommunicationApprove, CommunicationDraftCreate, CommunicationRead, CommunicationReview
from app.services.communications import approve, create_draft, get_visible_communication, move_to_review, reject, send
from app.services.evidence import EvidenceInput
from app.services.scoping import get_visible_project

router = APIRouter(tags=["communications"])


@router.get("/projects/{project_id}/communications", response_model=ListResponse[CommunicationRead])
async def list_communications(project_id: UUID, session: SessionDep, current_user: UserDep) -> ListResponse[CommunicationRead]:
    project = await get_visible_project(session, project_id, current_user)
    query = select(ClientCommunication).where(ClientCommunication.project_id == project.id)
    if current_user.role == AppRole.CLIENT:
        query = query.where(ClientCommunication.status == CommunicationStatus.SENT)
    rows = (await session.execute(query.order_by(ClientCommunication.created_at.desc()))).scalars()
    return ListResponse(data=[CommunicationRead.model_validate(row) for row in rows], pagination=Pagination(limit=50))


@router.post("/projects/{project_id}/communications/draft", response_model=DataResponse[CommunicationRead])
async def draft_communication(
    project_id: UUID,
    payload: CommunicationDraftCreate,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    project = await get_visible_project(session, project_id, current_user)
    latest_snapshot = (
        await session.execute(
            select(ThroughputSnapshot)
            .where(ThroughputSnapshot.project_id == project.id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_snapshot is None:
        raise ApiError(409, "EVIDENCE_REQUIRED", "Communication draft requires at least one evidence row.")
    body = (
        "Draft generation is ready for LLM integration. "
        "This placeholder is evidence-backed and must be reviewed before sending."
    )
    communication = await create_draft(
        session,
        project,
        payload.subject,
        body,
        payload.comm_type,
        [
            EvidenceInput(
                source_table="throughput_snapshots",
                source_row_id=latest_snapshot.id,
                description="Latest throughput snapshot for communication grounding.",
            )
        ],
    )
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication))


@router.get("/communications/{communication_id}", response_model=DataResponse[CommunicationRead])
async def get_communication(communication_id: UUID, session: SessionDep, current_user: UserDep) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    return DataResponse(data=await _communication_read(session, communication))


@router.patch("/communications/{communication_id}/review", response_model=DataResponse[CommunicationRead])
async def review_communication(
    communication_id: UUID,
    payload: CommunicationReview,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await move_to_review(session, communication, payload, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication))


@router.post("/communications/{communication_id}/approve", response_model=DataResponse[CommunicationRead])
async def approve_communication(
    communication_id: UUID,
    payload: CommunicationApprove,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await approve(session, communication, payload, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication))


@router.post("/communications/{communication_id}/reject", response_model=DataResponse[CommunicationRead])
async def reject_communication(
    communication_id: UUID,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await reject(session, communication)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication))


@router.post("/communications/{communication_id}/send", response_model=DataResponse[CommunicationRead])
async def send_communication(
    communication_id: UUID,
    session: SessionDep,
    current_user = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await send(session, communication)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication))


async def _communication_read(session: SessionDep, communication: ClientCommunication) -> CommunicationRead:
    data = CommunicationRead.model_validate(communication)
    links = (
        await session.execute(
            select(CommunicationEvidenceLink).where(CommunicationEvidenceLink.communication_id == communication.id)
        )
    ).scalars()
    data.evidence_links = [EvidenceLinkRead.model_validate(link) for link in links]
    return data
