from datetime import UTC, datetime
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
from app.schemas.domain import (
    CommunicationApprove,
    CommunicationDraftCreate,
    CommunicationDraftEdit,
    CommunicationRead,
    CommunicationReject,
    CommunicationReview,
)
from app.services.communications import (
    approve,
    create_draft,
    edit_draft,
    generate_comms_draft_body,
    get_visible_communication,
    move_to_review,
    reject,
    send,
)
from app.services.evidence import EvidenceInput
from app.services.quality import generate_quality_summary
from app.services.scoping import get_visible_project

router = APIRouter(tags=["communications"])

_MutatorDep = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN))


@router.get("/projects/{project_id}/communications", response_model=ListResponse[CommunicationRead])
async def list_communications(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> ListResponse[CommunicationRead]:
    project = await get_visible_project(session, project_id, current_user)
    query = select(ClientCommunication).where(ClientCommunication.project_id == project.id)
    if current_user.role == AppRole.CLIENT:
        query = query.where(ClientCommunication.status == CommunicationStatus.SENT)
    rows = list(
        (
            await session.execute(
                query.order_by(
                    ClientCommunication.created_at.desc(),
                    ClientCommunication.id.desc(),
                ).limit(50)
            )
        ).scalars()
    )
    evidence_by_communication = await _evidence_links_by_communication_id(
        session,
        [row.id for row in rows],
        include_provenance=current_user.role != AppRole.CLIENT,
    )
    return ListResponse(
        data=[
            _communication_read_with_links(
                row,
                evidence_by_communication.get(row.id, []),
                include_provenance=current_user.role != AppRole.CLIENT,
            )
            for row in rows
        ],
        pagination=Pagination(limit=50),
    )


@router.post("/projects/{project_id}/communications/draft", response_model=DataResponse[CommunicationRead])
async def draft_communication(
    project_id: UUID,
    payload: CommunicationDraftCreate,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    from app.agents.client_intelligence.contracts import EvidenceVisibility
    from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack
    from app.services.evidence import ERROR_EVIDENCE_PROVENANCE_UNMATCHED

    project = await get_visible_project(session, project_id, current_user)

    # Fail closed: new CI drafts require a governed pack fingerprint.
    pack = await build_client_evidence_pack(
        session,
        current_user,
        project.id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    if not pack.source_fingerprint or len(pack.source_fingerprint) != 64:
        raise ApiError(
            409,
            "EVIDENCE_FINGERPRINT_REQUIRED",
            "Client Intelligence draft requires a governed evidence source fingerprint.",
        )

    latest_throughput = (
        await session.execute(
            select(ThroughputSnapshot)
            .where(ThroughputSnapshot.project_id == project.id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_throughput is None:
        raise ApiError(
            409,
            "EVIDENCE_REQUIRED",
            "Communication draft requires at least one evidence row.",
        )

    pack_by_key = {
        (ref.source_table, ref.source_row_id): ref for ref in pack.evidence
    }

    def _from_pack_ref(
        source_table: str,
        source_row_id: UUID,
    ) -> EvidenceInput:
        ref = pack_by_key.get((source_table, source_row_id))
        if ref is None:
            raise ApiError(
                409,
                ERROR_EVIDENCE_PROVENANCE_UNMATCHED,
                (
                    "Communication evidence must match an exact governed "
                    "ClientEvidencePack reference."
                ),
                {
                    "source_table": source_table,
                    "source_row_id": str(source_row_id),
                },
            )
        if not ref.claim_keys:
            raise ApiError(
                409,
                "EVIDENCE_CLAIM_KEYS_REQUIRED",
                "Governed evidence references used for communications require claim keys.",
                {
                    "source_table": source_table,
                    "source_row_id": str(source_row_id),
                },
            )
        return EvidenceInput(
            source_table=ref.source_table,
            source_row_id=ref.source_row_id,
            description=ref.description,
            visibility=ref.visibility.value,
            observed_at=ref.observed_at,
            claim_keys=tuple(ref.claim_keys),
            pack_source_fingerprint=pack.source_fingerprint,
        )

    evidence: list[EvidenceInput] = [
        _from_pack_ref("throughput_snapshots", latest_throughput.id)
    ]

    quality_snaps: list[QualitySnapshot] = []
    drift_alerts: list[RiskAlert] = []
    quality_summary = None

    if payload.comm_type == CommunicationType.WEEKLY_SUMMARY:
        now = datetime.now(UTC)
        iso_year, iso_week, _ = now.isocalendar()
        quality_summary = await generate_quality_summary(
            session, project, iso_year, iso_week, current_user
        )
        # Do not invent synthetic summary-row identities. Link real
        # Quality/Delivery source rows that support the narrative instead.
        quality_snaps = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(QualitySnapshot.project_id == project.id)
                    .order_by(
                        QualitySnapshot.iso_year.desc(),
                        QualitySnapshot.iso_week.desc(),
                    )
                    .limit(10)
                )
            ).scalars()
        )
        seen_teams: set[UUID] = set()
        deduped_snaps: list[QualitySnapshot] = []
        for snap in quality_snaps:
            if snap.team_id not in seen_teams:
                seen_teams.add(snap.team_id)
                deduped_snaps.append(snap)
                evidence.append(_from_pack_ref("quality_snapshots", snap.id))
        quality_snaps = deduped_snaps

        drift_alerts = list(
            (
                await session.execute(
                    select(RiskAlert)
                    .where(
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
            evidence.append(_from_pack_ref("risk_alerts", alert.id))

    body = await generate_comms_draft_body(
        project,
        latest_throughput,
        payload.comm_type,
        quality_summary=quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
    )
    try:
        communication = await create_draft(
            session,
            project,
            payload.subject,
            body,
            payload.comm_type,
            evidence,
            evidence_source_fingerprint=pack.source_fingerprint,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(communication)
    return DataResponse(
        data=await _communication_read(session, communication, current_user)
    )


@router.get("/communications/{communication_id}", response_model=DataResponse[CommunicationRead])
async def get_communication(
    communication_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    return DataResponse(data=await _communication_read(session, communication, current_user))


@router.patch(
    "/communications/{communication_id}/draft",
    response_model=DataResponse[CommunicationRead],
)
async def edit_communication_draft(
    communication_id: UUID,
    payload: CommunicationDraftEdit,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await edit_draft(session, communication, payload, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication, current_user))


@router.patch("/communications/{communication_id}/review", response_model=DataResponse[CommunicationRead])
async def review_communication(
    communication_id: UUID,
    payload: CommunicationReview,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await move_to_review(session, communication, payload, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication, current_user))


@router.post("/communications/{communication_id}/approve", response_model=DataResponse[CommunicationRead])
async def approve_communication(
    communication_id: UUID,
    payload: CommunicationApprove,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await approve(session, communication, payload, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication, current_user))


@router.post("/communications/{communication_id}/reject", response_model=DataResponse[CommunicationRead])
async def reject_communication(
    communication_id: UUID,
    payload: CommunicationReject,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await reject(session, communication, payload, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication, current_user))


@router.post("/communications/{communication_id}/send", response_model=DataResponse[CommunicationRead])
async def send_communication(
    communication_id: UUID,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await send(session, communication, current_user)
    await session.commit()
    await session.refresh(communication)
    return DataResponse(data=await _communication_read(session, communication, current_user))


async def _evidence_links_by_communication_id(
    session: SessionDep,
    communication_ids: list[UUID],
    *,
    include_provenance: bool,
) -> dict[UUID, list[EvidenceLinkRead]]:
    if not communication_ids:
        return {}
    links = list(
        (
            await session.execute(
                select(CommunicationEvidenceLink)
                .where(CommunicationEvidenceLink.communication_id.in_(communication_ids))
                .order_by(
                    CommunicationEvidenceLink.communication_id.asc(),
                    CommunicationEvidenceLink.created_at.asc(),
                    CommunicationEvidenceLink.id.asc(),
                )
            )
        ).scalars()
    )
    grouped: dict[UUID, list[EvidenceLinkRead]] = {comm_id: [] for comm_id in communication_ids}
    for link in links:
        claim_keys = list(getattr(link, "claim_keys", None) or [])
        visibility = getattr(link, "visibility", None)
        observed_at = getattr(link, "observed_at", None)
        pack_fp = getattr(link, "pack_source_fingerprint", None)
        complete = bool(
            visibility
            and observed_at is not None
            and pack_fp
            and claim_keys
        )
        if include_provenance:
            grouped.setdefault(link.communication_id, []).append(
                EvidenceLinkRead(
                    id=link.id,
                    source_table=link.source_table,
                    source_row_id=link.source_row_id,
                    description=link.description,
                    created_at=getattr(link, "created_at", None),
                    visibility=visibility,
                    observed_at=observed_at,
                    claim_keys=claim_keys,
                    pack_source_fingerprint=pack_fp,
                    evidence_provenance_complete=complete,
                )
            )
        else:
            # Client-safe projection: no fingerprints, claim keys, or visibility.
            grouped.setdefault(link.communication_id, []).append(
                EvidenceLinkRead(
                    id=link.id,
                    source_table=link.source_table,
                    source_row_id=link.source_row_id,
                    description=link.description,
                    created_at=getattr(link, "created_at", None),
                )
            )
    return grouped


def _communication_provenance_state(
    communication: ClientCommunication,
    evidence_links: list[EvidenceLinkRead],
    *,
    include_provenance: bool,
) -> tuple[str | None, bool | None, str | None]:
    if not include_provenance:
        return None, None, None
    fingerprint = getattr(communication, "evidence_source_fingerprint", None)
    links_complete = bool(evidence_links) and all(
        link.evidence_provenance_complete for link in evidence_links
    )
    complete = bool(fingerprint) and links_complete
    if complete:
        return fingerprint, True, None
    if fingerprint is None:
        return None, False, "LEGACY_EVIDENCE_FINGERPRINT_MISSING"
    return fingerprint, False, "LEGACY_EVIDENCE_PROVENANCE_INCOMPLETE"


def _communication_read_with_links(
    communication: ClientCommunication,
    evidence_links: list[EvidenceLinkRead],
    *,
    include_provenance: bool,
) -> CommunicationRead:
    data = CommunicationRead.model_validate(communication)
    data.evidence_links = evidence_links
    fingerprint, complete, state = _communication_provenance_state(
        communication,
        evidence_links,
        include_provenance=include_provenance,
    )
    data.evidence_source_fingerprint = fingerprint
    data.evidence_provenance_complete = complete
    data.evidence_provenance_state = state
    if not include_provenance:
        data.evidence_source_fingerprint = None
        data.evidence_provenance_complete = None
        data.evidence_provenance_state = None
    return data


async def _communication_read(
    session: SessionDep,
    communication: ClientCommunication,
    current_user: UserDep | None = None,
) -> CommunicationRead:
    include_provenance = True
    if current_user is not None and current_user.role == AppRole.CLIENT:
        include_provenance = False
    grouped = await _evidence_links_by_communication_id(
        session,
        [communication.id],
        include_provenance=include_provenance,
    )
    return _communication_read_with_links(
        communication,
        grouped.get(communication.id, []),
        include_provenance=include_provenance,
    )
