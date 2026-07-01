from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.query_handler import (
    PROJECT_GOVERNANCE_AGENT_NAME,
    answer_governance_query,
)
from app.agents.quality_intelligence.query_handler import answer_quality_query
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput, require_evidence

SUPPORTED_AGENTS = {
    "delivery_performance_agent",
    "quality_intelligence_agent",
    "client_interaction_agent",
    "workforce_capability_agent",
    PROJECT_GOVERNANCE_AGENT_NAME,
}
GOVERNANCE_CHAT_CACHE_TTL = timedelta(minutes=3)


async def _cached_governance_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
) -> AgentQuery | None:
    since = datetime.now(UTC) - GOVERNANCE_CHAT_CACHE_TTL
    rows = list(
        (
            await session.execute(
                select(AgentQuery)
                .where(
                    AgentQuery.org_id == current_user.org_id,
                    AgentQuery.user_id == current_user.id,
                    AgentQuery.agent_name == PROJECT_GOVERNANCE_AGENT_NAME,
                    AgentQuery.project_id == payload.project_id,
                    AgentQuery.created_at >= since,
                )
                .order_by(AgentQuery.created_at.desc())
                .limit(8)
            )
        ).scalars()
    )
    normalized_question = payload.query_text.strip().lower()
    for row in rows:
        if row.query_text.strip().lower() == normalized_question and row.answer_text:
            return row
    return None


async def _copy_governance_cached_answer(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    cached: AgentQuery,
) -> AgentQuery:
    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=payload.project_id,
        agent_name=payload.agent_name,
        query_text=payload.query_text,
        answer_text=cached.answer_text,
        model_used=cached.model_used,
        latency_ms=0,
        retrieval_params={
            **(cached.retrieval_params or {}),
            "cache_hit": True,
            "cached_query_id": str(cached.id),
        },
    )
    session.add(query)
    await session.flush()
    cached_links = list(
        (
            await session.execute(
                select(AgentQueryEvidenceLink).where(
                    AgentQueryEvidenceLink.agent_query_id == cached.id
                )
            )
        ).scalars()
    )
    for item in cached_links:
        session.add(
            AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return query


async def answer_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput],
) -> AgentQuery:
    if payload.agent_name == "quality_intelligence_agent":
        return await answer_quality_query(session, current_user, payload, evidence)
    if payload.agent_name == PROJECT_GOVERNANCE_AGENT_NAME:
        cached = await _cached_governance_query(session, current_user, payload)
        if cached is not None:
            return await _copy_governance_cached_answer(session, current_user, payload, cached)
        return await answer_governance_query(session, current_user, payload, evidence)

    require_evidence(evidence)
    started = perf_counter()
    settings = get_settings()
    answer_text = "The LLM provider is not configured yet; this response is grounded in the attached evidence placeholders."
    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=payload.project_id,
        agent_name=payload.agent_name,
        query_text=payload.query_text,
        answer_text=answer_text,
        model_used=settings.llm_model,
        latency_ms=int((perf_counter() - started) * 1000),
    )
    session.add(query)
    await session.flush()
    for item in evidence:
        session.add(
            AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return query
