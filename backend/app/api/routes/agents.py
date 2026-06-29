from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.exceptions import ApiError
from app.db.models import AgentQuery, AgentQueryEvidenceLink, QualitySnapshot, ThroughputSnapshot
from app.schemas.common import DataResponse, EvidenceLinkRead, ListResponse, Pagination
from app.schemas.domain import AgentQueryCreate, AgentQueryRead
from app.services.agent_queries import SUPPORTED_AGENTS, answer_query
from app.services.evidence import EvidenceInput
from app.services.scoping import get_visible_project
from app.services.workforce_agent import WORKFORCE_AGENT_NAME, answer_workforce_query

router = APIRouter(tags=["agent queries"])


@router.post("/agent-queries", response_model=DataResponse[AgentQueryRead])
async def create_agent_query(
    payload: AgentQueryCreate, session: SessionDep, current_user: UserDep
) -> DataResponse[AgentQueryRead]:
    if payload.agent_name not in SUPPORTED_AGENTS:
        raise ApiError(400, "VALIDATION_ERROR", "Agent is not supported in MVP.")

    if payload.agent_name == WORKFORCE_AGENT_NAME:
        query = await answer_workforce_query(session, current_user, payload)
        await session.commit()
        await session.refresh(query)
        data = AgentQueryRead.model_validate(query)
        data.evidence_links = [
            EvidenceLinkRead(**item.__dict__) for item in await _query_evidence(session, query.id)
        ]
        return DataResponse(data=data)

    evidence: list[EvidenceInput] = []
    if payload.project_id:
        project = await get_visible_project(session, payload.project_id, current_user)
        if payload.agent_name == "quality_intelligence_agent":
            snapshot = (
                await session.execute(
                    select(QualitySnapshot)
                    .where(QualitySnapshot.project_id == project.id)
                    .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if snapshot:
                evidence.append(
                    EvidenceInput(
                        source_table="quality_snapshots",
                        source_row_id=snapshot.id,
                        description="Latest quality snapshot for the selected project.",
                    )
                )
        else:
            snapshot = (
                await session.execute(
                    select(ThroughputSnapshot)
                    .where(ThroughputSnapshot.project_id == project.id)
                    .order_by(ThroughputSnapshot.snapshot_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if snapshot:
                evidence.append(
                    EvidenceInput(
                        source_table="throughput_snapshots",
                        source_row_id=snapshot.id,
                        description="Latest throughput snapshot for the selected project.",
                    )
                )
    query = await answer_query(session, current_user, payload, evidence)
    await session.commit()
    await session.refresh(query)
    data = AgentQueryRead.model_validate(query)
    data.evidence_links = [EvidenceLinkRead(**item.__dict__) for item in await _query_evidence(session, query.id)]
    return DataResponse(data=data)


@router.get("/agent-queries", response_model=ListResponse[AgentQueryRead])
async def list_agent_queries(
    session: SessionDep, current_user: UserDep, limit: LimitQuery = 50
) -> ListResponse[AgentQueryRead]:
    query = select(AgentQuery).order_by(AgentQuery.created_at.desc()).limit(limit)
    if current_user.role.value == "client":
        query = query.where(AgentQuery.user_id == current_user.id)
    elif current_user.role.value == "delivery_manager":
        query = query.where(AgentQuery.org_id == current_user.org_id)
    rows = (await session.execute(query)).scalars()
    return ListResponse(data=[AgentQueryRead.model_validate(row) for row in rows], pagination=Pagination(limit=limit))


@router.get("/agent-queries/{query_id}", response_model=DataResponse[AgentQueryRead])
async def get_agent_query(
    query_id: UUID, session: SessionDep, current_user: UserDep
) -> DataResponse[AgentQueryRead]:
    query = select(AgentQuery).where(AgentQuery.id == query_id)
    if current_user.role.value == "client":
        query = query.where(AgentQuery.user_id == current_user.id)
    elif current_user.role.value == "delivery_manager":
        query = query.where(AgentQuery.org_id == current_user.org_id)
    row = (await session.execute(query)).scalar_one_or_none()
    # Double-check access for maximum compatibility with previous logic
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Agent query was not found.")
    # If using a superuser/admin role, allow access to any row (consistent with previous permissions)
    return_row = row
    # Defensive check for old logic if higher priv user tries to fetch not theirs (should be unreachable, but for parity)
    if current_user.role.value == "client" and row.user_id != current_user.id:
        raise ApiError(404, "NOT_FOUND", "Agent query was not found.")
    if current_user.role.value == "delivery_manager" and row.org_id != current_user.org_id:
        raise ApiError(404, "NOT_FOUND", "Agent query was not found.")
    data = AgentQueryRead.model_validate(row)
    data.evidence_links = [EvidenceLinkRead(**item.__dict__) for item in await _query_evidence(session, row.id)]
    return DataResponse(data=data)


async def _query_evidence(session: SessionDep, query_id: UUID) -> list[AgentQueryEvidenceLink]:
    return list(
        (await session.execute(select(AgentQueryEvidenceLink).where(AgentQueryEvidenceLink.agent_query_id == query_id))).scalars()
    )
