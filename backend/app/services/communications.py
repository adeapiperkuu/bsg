from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser, can_read_all_orgs
from app.db.models import (
    AppRole,
    ClientCommunication,
    CommunicationEvidenceLink,
    CommunicationStatus,
    Project,
)
from app.schemas.domain import CommunicationApprove, CommunicationReview
from app.services.evidence import EvidenceInput, require_evidence


async def get_visible_communication(
    session: AsyncSession,
    communication_id: UUID,
    current_user: CurrentUser,
) -> ClientCommunication:
    query = select(ClientCommunication).where(ClientCommunication.id == communication_id)
    if current_user.role == AppRole.CLIENT:
        query = query.where(
            ClientCommunication.org_id == current_user.org_id,
            ClientCommunication.status == CommunicationStatus.SENT,
        )
    elif not can_read_all_orgs(current_user.role):
        query = query.where(ClientCommunication.org_id == current_user.org_id)

    communication = (await session.execute(query)).scalar_one_or_none()
    if communication is None:
        raise ApiError(404, "NOT_FOUND", "Communication was not found.")
    return communication


async def create_draft(
    session: AsyncSession,
    project: Project,
    subject: str,
    body_draft: str,
    comm_type: str,
    evidence: list[EvidenceInput],
) -> ClientCommunication:
    require_evidence(evidence)
    communication = ClientCommunication(
        project_id=project.id,
        org_id=project.org_id,
        comm_type=comm_type,
        subject=subject,
        body_draft=body_draft,
        status=CommunicationStatus.DRAFT,
        drafted_by_agent="client_interaction_agent",
    )
    session.add(communication)
    await session.flush()
    for item in evidence:
        session.add(
            CommunicationEvidenceLink(
                communication_id=communication.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return communication


async def move_to_review(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationReview,
    current_user: CurrentUser,
) -> ClientCommunication:
    if communication.status not in {CommunicationStatus.DRAFT, CommunicationStatus.IN_REVIEW}:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Communication cannot move to review from its current state.")
    communication.status = CommunicationStatus.IN_REVIEW
    communication.body_approved = payload.body_approved
    communication.reviewed_by = current_user.id
    communication.reviewed_at = datetime.now(timezone.utc)
    await session.flush()
    return communication


async def approve(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationApprove,
    current_user: CurrentUser,
) -> ClientCommunication:
    body_approved = payload.body_approved or communication.body_approved
    if not body_approved:
        raise ApiError(400, "VALIDATION_ERROR", "Approved body is required.")
    communication.body_approved = body_approved
    communication.status = CommunicationStatus.APPROVED
    communication.approved_by = current_user.id
    communication.approved_at = datetime.now(timezone.utc)
    await session.flush()
    return communication


async def reject(session: AsyncSession, communication: ClientCommunication) -> ClientCommunication:
    communication.status = CommunicationStatus.REJECTED
    await session.flush()
    return communication


async def send(session: AsyncSession, communication: ClientCommunication) -> ClientCommunication:
    if communication.status != CommunicationStatus.APPROVED or communication.approved_by is None:
        raise ApiError(
            409,
            "COMMUNICATION_APPROVAL_REQUIRED",
            "Communication must be approved before it can be sent.",
            {"communication_id": str(communication.id)},
        )
    communication.status = CommunicationStatus.SENT
    communication.sent_at = datetime.now(timezone.utc)
    await session.flush()
    return communication
