import logging
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import (
    AppRole,
    ClientCommunication,
    CommunicationEvidenceLink,
    CommunicationStatus,
)
from app.schemas.common import DataResponse, EvidenceLinkRead, ListResponse, Pagination
from app.schemas.domain import (
    CommunicationApprove,
    CommunicationContentUpdate,
    CommunicationDraftCreate,
    CommunicationListItem,
    CommunicationRead,
    CommunicationReview,
)
from app.services.communications import (
    COMMUNICATIONS_LIST_DEFAULT_LIMIT,
    COMMUNICATIONS_LIST_MAX_LIMIT,
    approve,
    create_communication_draft,
    get_visible_communication,
    list_client_sent_communications,
    list_org_communications,
    move_to_review,
    reject,
    sanitize_communication_read_for_client,
    send,
    update_communication_content,
)
from app.services.scoping import get_visible_project

logger = logging.getLogger(__name__)

router = APIRouter(tags=["communications"])

PM_LIST_ROLES = (AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)


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
    rows = (await session.execute(query.order_by(ClientCommunication.created_at.desc()))).scalars()
    data = [CommunicationRead.model_validate(row) for row in rows]
    if current_user.role == AppRole.CLIENT:
        data = [sanitize_communication_read_for_client(item) for item in data]
    return ListResponse(data=data, pagination=Pagination(limit=50, items=len(data), total=len(data)))


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
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    auth_started = perf_counter()
    project = await get_visible_project(session, project_id, current_user)
    authorization_ms = (perf_counter() - auth_started) * 1000

    result = await create_communication_draft(
        session,
        project,
        subject=payload.subject,
        comm_type=payload.comm_type,
        instructions=payload.instructions,
        current_user=current_user,
        authorization_ms=authorization_ms,
    )
    data = await _communication_read(session, result.communication)
    # Ensure response reflects generation metadata even if ORM refresh races.
    data.generation_mode = result.generation_mode
    data.generation_warning = result.generation_warning

    t = result.timings
    logger.info(
        "communications_draft_timing route=POST /projects/{id}/communications/draft "
        "role=%s org_id=%s project_id=%s comm_type=%s generation_mode=%s "
        "evidence_link_count=%s authorization_ms=%.1f evidence_query_ms=%.1f "
        "quality_summary_ms=%.1f prompt_build_ms=%.1f llm_ms=%.1f persist_ms=%.1f total_ms=%.1f",
        current_user.role.value,
        current_user.org_id,
        project_id,
        payload.comm_type.value,
        result.generation_mode,
        result.evidence_link_count,
        t.authorization_ms,
        t.evidence_query_ms,
        t.quality_summary_ms,
        t.prompt_build_ms,
        t.llm_ms,
        t.persist_ms,
        t.total_ms,
    )
    return DataResponse(data=data)


@router.get("/communications/{communication_id}", response_model=DataResponse[CommunicationRead])
async def get_communication(
    communication_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[CommunicationRead]:
    communication = await get_visible_communication(session, communication_id, current_user)
    data = await _communication_read(session, communication, current_user=current_user)
    return DataResponse(data=data)


@router.patch("/communications/{communication_id}", response_model=DataResponse[CommunicationRead])
async def update_communication(
    communication_id: UUID,
    payload: CommunicationContentUpdate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
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
    return DataResponse(data=await _communication_read(session, communication))


@router.patch("/communications/{communication_id}/review", response_model=DataResponse[CommunicationRead])
async def review_communication(
    communication_id: UUID,
    payload: CommunicationReview,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CommunicationRead]:
    """Submit content for review (or re-save while already in_review)."""
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


async def _communication_read(
    session: SessionDep,
    communication: ClientCommunication,
    *,
    current_user=None,
) -> CommunicationRead:
    data = CommunicationRead.model_validate(communication)
    if current_user is not None and getattr(current_user, "role", None) == AppRole.CLIENT:
        # Clients do not receive internal evidence metadata or generation diagnostics.
        return sanitize_communication_read_for_client(data)

    links = (
        await session.execute(
            select(CommunicationEvidenceLink).where(CommunicationEvidenceLink.communication_id == communication.id)
        )
    ).scalars()
    data.evidence_links = [EvidenceLinkRead.model_validate(link) for link in links]
    return data
