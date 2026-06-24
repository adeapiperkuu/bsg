from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

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
}


async def answer_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput],
) -> AgentQuery:
    if payload.agent_name == "quality_intelligence_agent":
        return await answer_quality_query(session, current_user, payload, evidence)

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
