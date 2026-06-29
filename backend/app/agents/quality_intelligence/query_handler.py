from __future__ import annotations

import json
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.retrieval import keyword_search
from app.agents.quality_intelligence.citations import append_evidence_index, strip_ungrounded_citations
from app.agents.quality_intelligence.drift import evaluate_drift
from app.agents.quality_intelligence.oka_client import OKAClient
from app.agents.quality_intelligence.prompts import QUALITY_SYSTEM_PROMPT, build_user_prompt
from app.agents.quality_intelligence.rework_metrics import compute_rework_impact
from app.agents.quality_intelligence.root_cause import analyze_root_cause
from app.agents.quality_intelligence.what_if import analyze_what_if, what_if_to_read
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AlertStatus,
    AlertType,
    KnowledgeLesson,
    Milestone,
    QualityErrorEntry,
    QualitySnapshot,
    RiskAlert,
)
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput, require_evidence
from app.services.llm.client import LLMClient
from app.services.quality_scoping import filter_context_for_role, filter_response_for_role
from app.services.scoping import get_visible_project


def classify_intent(query_text: str) -> str:
    lower = query_text.lower()
    if any(w in lower for w in ("what if", "if we", "scenario", "would happen")):
        return "what_if"
    if any(w in lower for w in ("schedule", "milestone", "slippage", "rework volume", "how many units", "days impact")):
        return "impact"
    if any(w in lower for w in ("resolved", "how was", "how did we", "last time", "historical", "lesson")):
        return "historical"
    if any(w in lower for w in ("why", "driving", "root cause", "drop", "increasing")):
        return "diagnostic"
    if any(w in lower for w in ("focus", "fix", "recommend", "action", "should i")):
        return "action"
    return "status"


async def classify_intent_llm(query_text: str) -> str | None:
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_intent_routing:
        return None
    try:
        llm = LLMClient()
        raw = await llm.generate_structured(
            system=(
                "Classify the user query into exactly one intent: "
                "status, diagnostic, action, impact, historical, what_if. "
                "Return JSON: {\"intent\": \"...\"}"
            ),
            user=query_text,
            context="",
            json_mode=True,
        )
        payload = json.loads(raw)
        intent = str(payload.get("intent", "")).strip().lower()
        if intent in {"status", "diagnostic", "action", "impact", "historical", "what_if"}:
            return intent
    except Exception:
        return None
    return None


async def gather_quality_evidence(
    session: AsyncSession,
    project_id: UUID,
) -> tuple[list[EvidenceInput], str]:
    snapshots = list(
        (
            await session.execute(
                select(QualitySnapshot)
                .where(QualitySnapshot.project_id == project_id)
                .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                .limit(6)
            )
        ).scalars()
    )
    evidence: list[EvidenceInput] = []
    context_parts: list[str] = []

    for snap in snapshots:
        evidence.append(
            EvidenceInput(
                source_table="quality_snapshots",
                source_row_id=snap.id,
                description=f"W{snap.iso_week} quality snapshot",
            )
        )
        entries = (
            await session.execute(
                select(QualityErrorEntry).where(QualityErrorEntry.quality_snapshot_id == snap.id)
            )
        ).scalars()
        context_parts.append(
            json.dumps(
                {
                    "snapshot": {
                        "id": str(snap.id),
                        "iso_week": snap.iso_week,
                        "gold_set_accuracy_pct": str(snap.gold_set_accuracy_pct),
                        "iaa": str(snap.iaa_krippendorff_alpha),
                        "rework_rate_pct": str(snap.rework_rate_pct),
                        "has_drift_alert": snap.has_drift_alert,
                        "root_cause": snap.root_cause,
                    },
                    "errors": [
                        {"category": e.error_category, "share_pct": str(e.share_pct)}
                        for e in entries
                    ],
                },
                default=str,
            )
        )

    alerts = list(
        (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project_id,
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .limit(5)
            )
        ).scalars()
    )
    for alert in alerts:
        evidence.append(
            EvidenceInput(
                source_table="risk_alerts",
                source_row_id=alert.id,
                description=alert.title,
            )
        )
        context_parts.append(json.dumps({"risk_alert": {"id": str(alert.id), "title": alert.title, "detail": alert.detail}}))

    return evidence, "\n".join(context_parts)


async def _build_impact_summary(session: AsyncSession, project_id: UUID) -> str:
    latest = (
        await session.execute(
            select(QualitySnapshot)
            .where(QualitySnapshot.project_id == project_id)
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    rework = await compute_rework_impact(session, project_id)
    milestones = list(
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project_id)
                .order_by(Milestone.planned_date.asc().nullslast())
                .limit(5)
            )
        ).scalars()
    )
    at_risk = [m for m in milestones if m.status.value in {"at_risk", "delayed"}]
    return json.dumps(
        {
            "rework_impact": rework,
            "milestones_at_risk": [
                {"id": str(m.id), "name": m.name, "status": m.status.value, "target_date": str(m.target_date)}
                for m in at_risk
            ],
            "latest_week": f"W{latest.iso_week}/{latest.iso_year}" if latest else None,
        },
        default=str,
    )


async def _build_historical_summary(
    session: AsyncSession,
    project_id: UUID,
    org_id: UUID,
    query_text: str,
) -> str:
    oka = OKAClient()
    lessons = await oka.retrieve_lessons(org_id=str(org_id), error_category="quality")
    if not lessons:
        lessons = await keyword_search(session, org_id, query_text, limit=5)

    db_lessons = list(
        (
            await session.execute(
                select(KnowledgeLesson)
                .where(KnowledgeLesson.org_id == org_id)
                .order_by(KnowledgeLesson.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )

    return json.dumps(
        {
            "oka_lessons": lessons,
            "knowledge_lessons": [
                {"id": str(lesson.id), "title": lesson.title, "body": lesson.body[:300]}
                for lesson in db_lessons
            ],
        },
        default=str,
    )


async def answer_quality_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    if not payload.project_id:
        raise ValueError("Quality queries require a project_id.")

    project = await get_visible_project(session, payload.project_id, current_user)
    auto_evidence, context = await gather_quality_evidence(session, project.id)
    merged = {str(e.source_row_id): e for e in (evidence or [])}
    for item in auto_evidence:
        merged.setdefault(str(item.source_row_id), item)
    evidence_list = list(merged.values())
    require_evidence(evidence_list)

    intent = await classify_intent_llm(payload.query_text) or classify_intent(payload.query_text)
    latest = (
        await session.execute(
            select(QualitySnapshot)
            .where(QualitySnapshot.project_id == project.id)
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    analysis_summary = "No quality snapshots available."
    if latest:
        drift = await evaluate_drift(session, latest)
        root_cause = await analyze_root_cause(session, latest)
        analysis_summary = json.dumps(
            {
                "drift": {"has_drift": drift.has_drift, "severity": drift.severity.value, "detail": drift.detail},
                "root_cause": {
                    "primary_driver": root_cause.primary_driver,
                    "confidence": root_cause.confidence,
                    "factors": root_cause.factors,
                    "actions": root_cause.recommended_actions,
                    "blocked": root_cause.blocked,
                    "block_reason": root_cause.block_reason,
                },
            },
            default=str,
        )

    if intent == "what_if":
        what_if = await analyze_what_if(session, project, payload.query_text)
        analysis_summary = json.dumps({"what_if": what_if_to_read(what_if).model_dump()}, default=str)
    elif intent == "impact":
        analysis_summary = await _build_impact_summary(session, project.id)
    elif intent == "historical":
        analysis_summary = await _build_historical_summary(
            session, project.id, project.org_id, payload.query_text
        )

    oka = OKAClient()
    oka_lessons = await oka.retrieve_lessons(org_id=str(project.org_id), error_category="quality")
    if oka_lessons:
        context = context + "\n" + json.dumps({"oka_lessons": oka_lessons}, default=str)
    else:
        context = context + "\n[OKA_UNAVAILABLE] No OKA lessons retrieved."

    scoped_context = filter_context_for_role(context, current_user.role)
    user_prompt = build_user_prompt(
        query_text=payload.query_text,
        intent=intent,
        analysis_summary=analysis_summary,
    )

    started = perf_counter()
    settings = get_settings()
    llm = LLMClient()
    try:
        answer_text = await llm.generate_structured(
            system=QUALITY_SYSTEM_PROMPT,
            user=user_prompt,
            context=scoped_context,
            json_mode=intent in {"impact", "historical"},
        )
    except Exception:
        answer_text = (
            f"Quality status based on evidence: {analysis_summary}. "
            "LLM synthesis unavailable; showing pre-computed analysis only."
        )

    answer_text = strip_ungrounded_citations(answer_text, evidence_list)
    answer_text = append_evidence_index(answer_text, evidence_list)
    answer_text = filter_response_for_role(answer_text, current_user.role)

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
