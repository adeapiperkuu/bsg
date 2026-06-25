from __future__ import annotations

import json
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.dependencies import list_project_dependencies
from app.agents.governance.prompts import GOVERNANCE_SYSTEM_PROMPT, GOVERNANCE_USER_TEMPLATE
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink, GovernanceAction, RiskAlert
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput, require_evidence
from app.services.llm.client import LLMClient
from app.services.scoping import get_visible_project


def classify_intent(query_text: str) -> str:
    lower = query_text.lower()
    if any(w in lower for w in ("depend", "block", "upstream", "downstream")):
        return "dependencies"
    if any(w in lower for w in ("escalat", "overdue", "governance", "action")):
        return "governance"
    return "status"


async def gather_governance_evidence(
    session: AsyncSession,
    project_id,
) -> tuple[list[EvidenceInput], str]:
    evidence: list[EvidenceInput] = []
    context_parts: list[str] = []

    deps = await list_project_dependencies(session, project_id)
    for dep in deps:
        evidence.append(
            EvidenceInput(
                source_table="project_dependencies",
                source_row_id=dep.id,
                description=f"Dependency {dep.dependency_type}",
            )
        )
        context_parts.append(
            json.dumps(
                {
                    "dependency": {
                        "type": dep.dependency_type,
                        "status": dep.status,
                        "from": str(dep.from_project_id),
                        "to": str(dep.to_project_id),
                    }
                },
                default=str,
            )
        )

    actions = list(
        (
            await session.execute(
                select(GovernanceAction)
                .where(GovernanceAction.project_id == project_id)
                .order_by(GovernanceAction.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    for action in actions:
        evidence.append(
            EvidenceInput(
                source_table="governance_actions",
                source_row_id=action.id,
                description=action.title,
            )
        )

    alerts = list(
        (
            await session.execute(
                select(RiskAlert)
                .where(RiskAlert.project_id == project_id, RiskAlert.deleted_at.is_(None))
                .order_by(RiskAlert.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    for alert in alerts:
        evidence.append(
            EvidenceInput(source_table="risk_alerts", source_row_id=alert.id, description=alert.title)
        )

    return evidence, "\n".join(context_parts)


async def answer_governance_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    if not payload.project_id:
        raise ValueError("Governance queries require a project_id.")

    project = await get_visible_project(session, payload.project_id, current_user)
    auto_evidence, context = await gather_governance_evidence(session, project.id)
    merged = {str(e.source_row_id): e for e in (evidence or [])}
    for item in auto_evidence:
        merged.setdefault(str(item.source_row_id), item)
    evidence_list = list(merged.values())
    require_evidence(evidence_list)

    intent = classify_intent(payload.query_text)
    deps = await list_project_dependencies(session, project.id)
    analysis_summary = json.dumps(
        {"open_dependencies": sum(1 for d in deps if d.status == "open"), "total_dependencies": len(deps)},
        default=str,
    )

    user_prompt = GOVERNANCE_USER_TEMPLATE.format(
        intent=intent,
        query_text=payload.query_text,
        analysis_summary=analysis_summary,
    )

    started = perf_counter()
    settings = get_settings()
    try:
        llm = LLMClient()
        answer_text = await llm.generate_structured(
            system=GOVERNANCE_SYSTEM_PROMPT,
            user=user_prompt,
            context=context,
        )
    except Exception:
        answer_text = (
            f"Governance status based on evidence: {analysis_summary}. "
            "LLM synthesis unavailable; showing pre-computed analysis only."
        )

    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=project.id,
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
