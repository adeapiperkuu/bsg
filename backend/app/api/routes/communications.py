from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    ClientCommunication,
    CommunicationEvidenceLink,
    CommunicationStatus,
    CommunicationType,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
)
from app.schemas.common import DataResponse, EvidenceLinkRead, ListResponse, Pagination
from app.schemas.domain import CommunicationApprove, CommunicationDraftCreate, CommunicationRead, CommunicationReview
from app.services.communications import (
    approve,
    create_draft,
    generate_comms_draft_body,
    get_visible_communication,
    move_to_review,
    reject,
    send,
)
from datetime import datetime, timezone

from app.services.quality import generate_quality_summary
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
    latest_throughput = (
        await session.execute(
            select(ThroughputSnapshot)
            .where(ThroughputSnapshot.project_id == project.id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_throughput is None:
        raise ApiError(409, "EVIDENCE_REQUIRED", "Communication draft requires at least one evidence row.")

    evidence: list[EvidenceInput] = [
        EvidenceInput(
            source_table="throughput_snapshots",
            source_row_id=latest_throughput.id,
            description="Latest throughput snapshot for communication grounding.",
        )
    ]

    quality_snaps: list[QualitySnapshot] = []
    drift_alerts: list[RiskAlert] = []
    quality_summary = None

    # For weekly summaries, attach sanitized §8.4 quality summary when available.
    if payload.comm_type == CommunicationType.WEEKLY_SUMMARY:
        now = datetime.now(timezone.utc)
        iso_year, iso_week, _ = now.isocalendar()
        quality_summary = await generate_quality_summary(
            session, project, iso_year, iso_week, current_user
        )
        evidence.append(
            EvidenceInput(
                source_table="quality_summaries",
                source_row_id=project.id,
                description=f"Sanitized quality summary W{iso_week}/{iso_year}.",
            )
        )

        quality_snaps = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(QualitySnapshot.project_id == project.id)
                    .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                    .limit(10)
                )
            ).scalars()
        )
        # Deduplicate: one row per team (latest week only).
        seen_teams: set[UUID] = set()
        deduped_snaps: list[QualitySnapshot] = []
        for snap in quality_snaps:
            if snap.team_id not in seen_teams:
                seen_teams.add(snap.team_id)
                deduped_snaps.append(snap)
                evidence.append(
                    EvidenceInput(
                        source_table="quality_snapshots",
                        source_row_id=snap.id,
                        description=f"Quality snapshot W{snap.iso_week}/{snap.iso_year} for team {snap.team_id}.",
                    )
                )
        quality_snaps = deduped_snaps

        drift_alerts = list(
            (
                await session.execute(
                    select(RiskAlert).where(
                        RiskAlert.project_id == project.id,
                        RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                        RiskAlert.deleted_at.is_(None),
                        RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                    )
                    .order_by(RiskAlert.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )
        for alert in drift_alerts:
            evidence.append(
                EvidenceInput(
                    source_table="risk_alerts",
                    source_row_id=alert.id,
                    description=f"Open quality drift alert: {alert.title}",
                )
            )

    body = await generate_comms_draft_body(
        project,
        latest_throughput,
        payload.comm_type,
        quality_summary=quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
    )
    communication = await create_draft(
        session,
        project,
        payload.subject,
        body,
        payload.comm_type,
        evidence,
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
