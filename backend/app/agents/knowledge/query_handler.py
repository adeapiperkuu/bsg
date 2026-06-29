from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.prompts import KNOWLEDGE_SYSTEM_PROMPT, KNOWLEDGE_USER_TEMPLATE
from app.agents.knowledge.retrieval import keyword_search
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink, KnowledgeLesson
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput, require_evidence
from app.services.llm.client import LLMClient


def classify_intent(query_text: str) -> str:
    lower = query_text.lower()
    if any(w in lower for w in ("sop", "guideline", "procedure")):
        return "sop"
    if any(w in lower for w in ("lesson", "resolved", "historical", "past")):
        return "lesson"
    return "search"


async def gather_knowledge_evidence(
    session: AsyncSession,
    org_id,
    query_text: str,
) -> tuple[list[EvidenceInput], str]:
    hits = await keyword_search(session, org_id, query_text)
    evidence: list[EvidenceInput] = []
    context_parts: list[str] = []

    for hit in hits:
        table = "knowledge_lessons" if hit["type"] == "lesson" else "sop_documents"
        evidence.append(
            EvidenceInput(
                source_table=table,
                source_row_id=UUID(hit["id"]),
                description=hit["title"],
            )
        )
        context_parts.append(json.dumps(hit, default=str))

    if not evidence:
        recent = list(
            (
                await session.execute(
                    select(KnowledgeLesson)
                    .where(KnowledgeLesson.org_id == org_id)
                    .order_by(KnowledgeLesson.created_at.desc())
                    .limit(3)
                )
            ).scalars()
        )
        for lesson in recent:
            evidence.append(
                EvidenceInput(
                    source_table="knowledge_lessons",
                    source_row_id=lesson.id,
                    description=lesson.title,
                )
            )
            context_parts.append(json.dumps({"type": "lesson", "title": lesson.title, "snippet": lesson.body[:150]}))

    return evidence, "\n".join(context_parts)


async def answer_knowledge_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    auto_evidence, context = await gather_knowledge_evidence(
        session, current_user.org_id, payload.query_text
    )
    merged = {str(e.source_row_id): e for e in (evidence or [])}
    for item in auto_evidence:
        merged.setdefault(str(item.source_row_id), item)
    evidence_list = list(merged.values())
    require_evidence(evidence_list)

    intent = classify_intent(payload.query_text)
    user_prompt = KNOWLEDGE_USER_TEMPLATE.format(
        intent=intent,
        query_text=payload.query_text,
        context=context or "No matching knowledge found.",
    )

    started = perf_counter()
    settings = get_settings()
    try:
        llm = LLMClient()
        answer_text = await llm.generate_structured(
            system=KNOWLEDGE_SYSTEM_PROMPT,
            user=user_prompt,
            context=context,
        )
    except Exception:
        if not context:
            answer_text = "Knowledge base retrieval returned no matches for this query."
        else:
            answer_text = f"Retrieved knowledge:\n{context}\n\nLLM synthesis unavailable."

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
    for item in evidence_list:
        session.add(
            AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return query
