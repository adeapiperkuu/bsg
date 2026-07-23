"""Client portal Ask Agent routes — grounded CLIENT_SAFE Q&A."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BeforeValidator, Field

from app.agents.client_intelligence.contracts import ClientIntelligenceModel
from app.agents.client_intelligence.query_contracts import (
    ClientIntelligenceQueryHistoryRead,
    ClientIntelligenceQueryRead,
)
from app.api.deps import SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole
from app.schemas.common import DataResponse
from app.services.client_intelligence import (
    QUERY_HISTORY_DEFAULT_LIMIT,
    QUERY_HISTORY_MAX_LIMIT,
    build_client_intelligence_query_history,
    create_client_intelligence_query,
)

router = APIRouter(tags=["client-ask"])

_ClientRoleDep = Annotated[
    CurrentUser,
    Depends(require_role(AppRole.CLIENT)),
]


def _strip_question(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class ClientAskQuestionCreate(ClientIntelligenceModel):
    project_id: UUID
    question: Annotated[
        str,
        BeforeValidator(_strip_question),
        Field(min_length=1, max_length=2000),
    ]


@router.post(
    "/client/ask/queries",
    response_model=DataResponse[ClientIntelligenceQueryRead],
)
async def create_client_ask_query(
    payload: ClientAskQuestionCreate,
    session: SessionDep,
    current_user: _ClientRoleDep,
) -> DataResponse[ClientIntelligenceQueryRead]:
    """Ask a grounded, CLIENT_SAFE question about an assigned project."""
    result = await create_client_intelligence_query(
        session,
        current_user,
        payload.project_id,
        question=payload.question,
    )
    await session.commit()
    return DataResponse(data=result)


@router.get(
    "/client/ask/queries",
    response_model=DataResponse[ClientIntelligenceQueryHistoryRead],
)
async def list_client_ask_queries(
    session: SessionDep,
    current_user: _ClientRoleDep,
    project_id: UUID = Query(...),
    limit: Annotated[
        int,
        Query(ge=1, le=QUERY_HISTORY_MAX_LIMIT),
    ] = QUERY_HISTORY_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DataResponse[ClientIntelligenceQueryHistoryRead]:
    """Return the caller's Ask Agent history for one assigned project."""
    history = await build_client_intelligence_query_history(
        session,
        current_user,
        project_id,
        limit=limit,
        offset=offset,
    )
    return DataResponse(data=history)
