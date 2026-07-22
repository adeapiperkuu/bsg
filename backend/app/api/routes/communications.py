import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
    CommunicationContentUpdate,
    CommunicationDraftCreate,
    CommunicationDraftEdit,
    CommunicationListItem,
    CommunicationRead,
    CommunicationReject,
    CommunicationReview,
)
from app.services.communications import (
    COMMUNICATIONS_LIST_DEFAULT_LIMIT,
    COMMUNICATIONS_LIST_MAX_LIMIT,
    approve,
    create_draft,
    edit_draft,
    generate_comms_draft_body,
    get_visible_communication,
    list_client_sent_communications,
    list_org_communications,
    move_to_review,
    reject,
    send,
    update_communication_content,
)
from app.services.evidence import EvidenceInput
from app.services.quality import generate_quality_summary
from app.services.scoping import get_visible_project

logger = logging.getLogger(__name__)

router = APIRouter(tags=["communications"])

PM_LIST_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)

_MutatorDep = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN))


def _list_pagination(*, total: int, limit: int, offset: int, item_count: int) -> Pagination:
    return Pagination(
        limit=limit,
        offset=offset,
        total=total,
        items=item_count,
        has_more=offset + item_count < total,
    )


@router.get("/communications", response_model=ListResponse[CommunicationListItem])
async def list_org_scoped_communications(
    session: SessionDep,
    current_user=Depends(require_role(*PM_LIST_ROLES)),
    status: CommunicationStatus | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=COMMUNICATIONS_LIST_DEFAULT_LIMIT, ge=1, le=COMMUNICATIONS_LIST_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> ListResponse[CommunicationListItem]:
    """PM inbox: lightweight org-scoped communications list (no bodies).

    Clients must use project-scoped `/projects/{id}/communications` (sent only)
    or the client portal — they cannot call this endpoint.
    """
    started = perf_counter()
    page = await list_org_communications(
        session,
        current_user,
        status=status,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    serialization_started = perf_counter()
    payload = ListResponse(
        data=page.items,
        pagination=_list_pagination(
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            item_count=len(page.items),
        ),
    )
    serialization_ms = (perf_counter() - serialization_started) * 1000
    total_ms = (perf_counter() - started) * 1000
    logger.info(
        "communications_list_timing route=GET /communications role=%s org_id=%s "
        "status_filter=%s project_filter=%s row_count=%s db_ms=%.1f "
        "serialization_ms=%.1f total_ms=%.1f",
        current_user.role.value,
        current_user.org_id,
        status.value if status is not None else None,
        project_id,
        len(page.items),
        page.db_ms,
        serialization_ms,
        total_ms,
    )
    return payload


@router.get("/projects/{project_id}/communications", response_model=ListResponse[CommunicationRead])
async def list_communications(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    status: CommunicationStatus | None = Query(
        default=None,
        description="Ignored for clients; clients always receive sent-only rows.",
    ),
) -> ListResponse[CommunicationRead]:
    """Project-scoped communications list.

    Clients always receive `sent` only. A client-supplied status other than `sent`
    is rejected so drafts/approved-unsent cannot be requested.
    """
    project = await get_visible_project(session, project_id, current_user)
    query = select(ClientCommunication).where(ClientCommunication.project_id == project.id)
    if current_user.role == AppRole.CLIENT:
        if status is not None and status != CommunicationStatus.SENT:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "Clients can only list sent communications.",
            )
        query = query.where(ClientCommunication.status == CommunicationStatus.SENT)
    elif status is not None:
        query = query.where(ClientCommunication.status == status)
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
    include_provenance = current_user.role != AppRole.CLIENT
    evidence_by_communication = await _evidence_links_by_communication_id(
        session,
        [row.id for row in rows],
        include_provenance=include_provenance,
    )
    return ListResponse(
        data=[
            _communication_read_with_links(
                row,
                evidence_by_communication.get(row.id, []),
                include_provenance=include_provenance,
            )
            for row in rows
        ],
        pagination=Pagination(limit=50),
    )


@router.get("/client/communications", response_model=ListResponse[CommunicationListItem])
async def list_client_archive_communications(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.CLIENT)),
    limit: int = Query(default=COMMUNICATIONS_LIST_DEFAULT_LIMIT, ge=1, le=COMMUNICATIONS_LIST_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> ListResponse[CommunicationListItem]:
    """Client published archive: org-scoped sent communications only (no bodies)."""
    started = perf_counter()
    page = await list_client_sent_communications(
        session,
        current_user,
        limit=limit,
        offset=offset,
    )
    payload = ListResponse(
        data=page.items,
        pagination=_list_pagination(
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            item_count=len(page.items),
        ),
    )
    total_ms = (perf_counter() - started) * 1000
    logger.info(
        "client_communications_list_timing route=GET /client/communications role=%s org_id=%s "
        "row_count=%s db_ms=%.1f total_ms=%.1f",
        current_user.role.value,
        current_user.org_id,
        len(page.items),
        page.db_ms,
        total_ms,
    )
    return payload


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

    started = perf_counter()
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

    generated = await generate_comms_draft_body(
        project,
        latest_throughput,
        payload.comm_type,
        quality_summary=quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
        instructions=payload.instructions,
    )
    if isinstance(generated, tuple):
        body, generation_mode, generation_warning, llm_ms = generated
    else:
        body, generation_mode, generation_warning, llm_ms = generated, "ai", None, 0.0
    try:
        communication = await create_draft(
            session,
            project,
            payload.subject,
            body,
            payload.comm_type,
            evidence,
            evidence_source_fingerprint=pack.source_fingerprint,
            generation_mode=generation_mode,
            generation_warning=generation_warning,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(communication)
    data = await _communication_read(session, communication, current_user)
    # Ensure response reflects generation metadata even if ORM refresh races.
    data.generation_mode = generation_mode
    data.generation_warning = generation_warning
    logger.info(
        "communications_draft_timing route=POST /projects/{id}/communications/draft "
        "role=%s org_id=%s project_id=%s comm_type=%s generation_mode=%s "
        "evidence_link_count=%s llm_ms=%.1f total_ms=%.1f",
        current_user.role.value,
        current_user.org_id,
        project_id,
        payload.comm_type.value,
        generation_mode,
        len(evidence),
        llm_ms,
        (perf_counter() - started) * 1000,
    )
    return DataResponse(data=data)


@router.get("/communications/{communication_id}", response_model=DataResponse[CommunicationRead])
async def get_communication(
    communication_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    return DataResponse(data=await _communication_read(session, communication, current_user))


@router.patch("/communications/{communication_id}", response_model=DataResponse[CommunicationRead])
async def update_communication(
    communication_id: UUID,
    payload: CommunicationContentUpdate,
    session: SessionDep,
    current_user=_MutatorDep,
) -> DataResponse[CommunicationRead]:
    """Save subject/body edits without changing lifecycle status (draft | in_review)."""
    communication = await get_visible_communication(session, communication_id, current_user)
    communication = await update_communication_content(
        session,
        communication,
        subject=payload.subject,
        body=payload.body,
    )
    await session.commit()
    await session.refresh(communication)
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
    """Submit content for review (draft → in_review)."""
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
        # Clients do not receive internal integrity or generation diagnostics.
        data.evidence_source_fingerprint = None
        data.evidence_provenance_complete = None
        data.evidence_provenance_state = None
        data.generation_mode = None
        data.generation_warning = None
        if data.body_approved and data.body_approved.strip():
            data.body_draft = data.body_approved
    return data


async def _communication_read(
    session: SessionDep,
    communication: ClientCommunication,
    current_user: UserDep | None = None,
) -> CommunicationRead:
    include_provenance = True
    if current_user is not None and getattr(current_user, "role", None) == AppRole.CLIENT:
        include_provenance = False
    grouped = await _evidence_links_by_communication_id(
        session,
        [communication.id],
        include_provenance=include_provenance,
    )
    data = _communication_read_with_links(
        communication,
        grouped.get(communication.id, []),
        include_provenance=include_provenance,
    )
    if include_provenance:
        try:
            from app.reports.adapters import lookup_platform_report_id_for_communication

            data.platform_report_id = await lookup_platform_report_id_for_communication(
                session, communication.id
            )
        except Exception:
            data.platform_report_id = None
    else:
        data.platform_report_id = None
    return data
