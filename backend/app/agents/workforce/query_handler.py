from __future__ import annotations

import json
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workforce.prompts import WORKFORCE_SYSTEM_PROMPT, WORKFORCE_USER_TEMPLATE
from app.agents.workforce.skill_matrix import build_skill_matrix
from app.agents.workforce.utilization import get_latest_utilization_by_team, utilization_status
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink, Notification, NotificationType, Team
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput, require_evidence
from app.services.llm.client import LLMClient


def classify_intent(query_text: str) -> str:
    lower = query_text.lower()
    if any(w in lower for w in ("gap", "missing", "skill")):
        return "skill_gap"
    if any(w in lower for w in ("utilization", "capacity", "hours", "overload")):
        return "utilization"
    if any(w in lower for w in ("sme", "expert", "allocate")):
        return "sme_allocation"
    return "status"


async def gather_workforce_evidence(
    session: AsyncSession,
    org_id,
) -> tuple[list[EvidenceInput], str]:
    evidence: list[EvidenceInput] = []
    context_parts: list[str] = []

    util_snaps = await get_latest_utilization_by_team(session, org_id)
    for snap in util_snaps:
        evidence.append(
            EvidenceInput(
                source_table="workforce_utilization_snapshots",
                source_row_id=snap.id,
                description=f"Utilization W{snap.iso_week}/{snap.iso_year}",
            )
        )
        context_parts.append(
            json.dumps(
                {
                    "utilization": {
                        "team_id": str(snap.team_id),
                        "utilization_pct": str(snap.utilization_pct),
                        "status": utilization_status(snap.utilization_pct),
                    }
                },
                default=str,
            )
        )

    matrix = await build_skill_matrix(session, org_id)
    context_parts.append(json.dumps({"skill_matrix": matrix}, default=str))

    skill_gap_notes = list(
        (
            await session.execute(
                select(Notification).where(
                    Notification.org_id == org_id,
                    Notification.notification_type == NotificationType.SKILL_GAP_DETECTED,
                )
                .order_by(Notification.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    for note in skill_gap_notes:
        evidence.append(
            EvidenceInput(
                source_table="notifications",
                source_row_id=note.id,
                description=note.title,
            )
        )

    return evidence, "\n".join(context_parts)


async def answer_workforce_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    auto_evidence, context = await gather_workforce_evidence(session, current_user.org_id)
    merged = {str(e.source_row_id): e for e in (evidence or [])}
    for item in auto_evidence:
        merged.setdefault(str(item.source_row_id), item)
    evidence_list = list(merged.values())
    require_evidence(evidence_list)

    intent = classify_intent(payload.query_text)
    util_snaps = await get_latest_utilization_by_team(session, current_user.org_id)
    matrix = await build_skill_matrix(session, current_user.org_id)
    analysis_summary = json.dumps(
        {
            "teams_tracked": len(util_snaps),
            "avg_utilization": (
                str(round(sum(float(s.utilization_pct or 0) for s in util_snaps) / len(util_snaps), 1))
                if util_snaps
                else None
            ),
            "skill_codes": list(matrix.keys()),
        },
        default=str,
    )

    user_prompt = WORKFORCE_USER_TEMPLATE.format(
        intent=intent,
        query_text=payload.query_text,
        analysis_summary=analysis_summary,
    )

    started = perf_counter()
    settings = get_settings()
    try:
        llm = LLMClient()
        answer_text = await llm.generate_structured(
            system=WORKFORCE_SYSTEM_PROMPT,
            user=user_prompt,
            context=context,
        )
    except Exception:
        answer_text = (
            f"Workforce status based on evidence: {analysis_summary}. "
            "LLM synthesis unavailable; showing pre-computed analysis only."
        )

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
