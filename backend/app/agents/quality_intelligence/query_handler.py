from __future__ import annotations

import json
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.retrieval import keyword_search
from app.agents.quality_intelligence.citations import append_evidence_index, strip_ungrounded_citations
from app.agents.quality_intelligence.drift import evaluate_drift, fetch_prior_snapshot
from app.agents.quality_intelligence.evidence_pack import build_evidence_pack
from app.agents.quality_intelligence.oka_client import OKAClient
from app.agents.quality_intelligence.prompts import QUALITY_SYNTHESIS_PROMPT, build_synthesis_user_prompt
from app.agents.quality_intelligence.reasoning import reason_root_cause
from app.agents.quality_intelligence.root_cause import extract_signals
from app.agents.quality_intelligence.rework_metrics import compute_rework_impact
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


def _wow_direction(current: object, prior: object) -> dict[str, object]:
    """Pre-computed, unambiguous week-over-week direction — computed here
    rather than left for the LLM to infer from prose, so a metric can never
    be mischaracterized as "dropping" when the numbers show otherwise."""
    if current is None or prior is None:
        return {"direction": "unknown", "delta": None, "reason": "prior week not available"}
    delta = float(current) - float(prior)
    if delta > 0.01:
        direction = "increased"
    elif delta < -0.01:
        direction = "decreased"
    else:
        direction = "unchanged"
    return {"direction": direction, "delta": round(delta, 3)}


async def _fetch_latest_snapshot(session: AsyncSession, project_id: UUID) -> QualitySnapshot | None:
    return (
        await session.execute(
            select(QualitySnapshot)
            .where(QualitySnapshot.project_id == project_id)
            .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _fallback_evidence_no_snapshot(
    session: AsyncSession, project_id: UUID
) -> tuple[list[EvidenceInput], dict[str, object]]:
    """No quality_snapshots exist yet for this project — surface open alerts only."""
    alerts = list(
        (
            await session.execute(
                select(RiskAlert)
                .where(
                    RiskAlert.project_id == project_id,
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .limit(5)
            )
        ).scalars()
    )
    evidence = [
        EvidenceInput(source_table="risk_alerts", source_row_id=alert.id, description=alert.title)
        for alert in alerts
    ]
    context: dict[str, object] = {
        "note": "No quality snapshots available for this project.",
        "open_alerts": [alert.title for alert in alerts],
    }
    return evidence, context


async def _build_impact_context(
    session: AsyncSession, project_id: UUID
) -> tuple[dict[str, object], list[EvidenceInput]]:
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
    evidence = [
        EvidenceInput(source_table="milestones", source_row_id=m.id, description=m.name) for m in at_risk
    ]
    context = {
        "impact": {
            "rework_impact": rework,
            "milestones_at_risk": [
                {"id": str(m.id), "name": m.name, "status": m.status.value, "target_date": str(m.target_date)}
                for m in at_risk
            ],
        }
    }
    return context, evidence


async def _build_historical_context(
    session: AsyncSession,
    project_id: UUID,
    org_id: UUID,
    query_text: str,
) -> tuple[dict[str, object], list[EvidenceInput]]:
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
    evidence = [
        EvidenceInput(source_table="knowledge_lessons", source_row_id=lesson.id, description=lesson.title)
        for lesson in db_lessons
    ]
    context = {
        "historical": {
            "oka_lessons": lessons,
            "knowledge_lessons": [
                {"id": str(lesson.id), "title": lesson.title, "body": lesson.body[:300]} for lesson in db_lessons
            ],
        }
    }
    return context, evidence


async def answer_quality_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    if not payload.project_id:
        raise ValueError("Quality queries require a project_id.")

    project = await get_visible_project(session, payload.project_id, current_user)
    intent = await classify_intent_llm(payload.query_text) or classify_intent(payload.query_text)
    latest = await _fetch_latest_snapshot(session, project.id)

    auto_evidence: list[EvidenceInput]
    context: dict[str, object]
    reasoning_json: dict[str, object] = {}

    if latest is None:
        auto_evidence, context = await _fallback_evidence_no_snapshot(session, project.id)
    else:
        # Pack is built once per query, role-scoped at the source (reviewer
        # detail is simply absent from the pack for CLIENT, not scrubbed
        # after the fact). See evidence_pack.py.
        pack = await build_evidence_pack(session, latest, role=current_user.role)
        signals = extract_signals(pack)
        drift = await evaluate_drift(session, latest)
        prior_snapshot = await fetch_prior_snapshot(session, latest)
        # This almost always reuses the trace already computed and persisted
        # by evaluate_snapshot() at ingest time (fingerprint-matched) rather
        # than issuing a fresh LLM call per NL question — see reasoning.py.
        root_cause = await reason_root_cause(session, latest, pack, signals)

        context = pack.to_prompt_json()
        auto_evidence = [
            EvidenceInput(source_table=item.source_table, source_row_id=item.source_row_id, description=item.summary)
            for item in pack.all_items()
        ]
        reasoning_json = {
            "drift": {
                "has_drift": drift.has_drift,
                "severity": drift.severity.value,
                "detail": drift.detail,
                # Pre-computed so the model can never assert "dropping" or
                # "improving" against what the numbers actually show.
                "gold_set_accuracy_wow": _wow_direction(
                    latest.gold_set_accuracy_pct,
                    prior_snapshot.gold_set_accuracy_pct if prior_snapshot else None,
                ),
                "rework_rate_wow": _wow_direction(
                    latest.rework_rate_pct,
                    prior_snapshot.rework_rate_pct if prior_snapshot else None,
                ),
                "iaa_wow": _wow_direction(
                    latest.iaa_krippendorff_alpha,
                    prior_snapshot.iaa_krippendorff_alpha if prior_snapshot else None,
                ),
            },
            "root_cause": {
                "primary_driver": root_cause.primary_driver,
                "confidence": root_cause.confidence,
                "factors": root_cause.factors,
                "actions": root_cause.recommended_actions,
                "novel_findings": root_cause.novel_findings,
                "blocked": root_cause.blocked,
                "block_reason": root_cause.block_reason,
                "engine": root_cause.engine,
            },
        }

        if intent == "what_if":
            what_if = await analyze_what_if(session, project, payload.query_text)
            reasoning_json["what_if"] = what_if_to_read(what_if).model_dump()
        elif intent == "impact":
            impact_context, impact_evidence = await _build_impact_context(session, project.id)
            context.update(impact_context)
            auto_evidence.extend(impact_evidence)
        elif intent == "historical":
            historical_context, historical_evidence = await _build_historical_context(
                session, project.id, project.org_id, payload.query_text
            )
            context.update(historical_context)
            auto_evidence.extend(historical_evidence)

    merged = {str(e.source_row_id): e for e in (evidence or [])}
    for item in auto_evidence:
        merged.setdefault(str(item.source_row_id), item)
    evidence_list = list(merged.values())
    require_evidence(evidence_list)

    # Unconditional top-level OKA lookup, matching pre-existing behavior —
    # independent of whatever intent-specific lessons were already gathered.
    oka = OKAClient()
    oka_lessons = await oka.retrieve_lessons(org_id=str(project.org_id), error_category="quality")
    if oka_lessons:
        context["oka_lessons"] = oka_lessons
    else:
        context["oka_status"] = "OKA_UNAVAILABLE — no lessons retrieved"

    context_json = json.dumps(context, default=str, indent=2)
    scoped_context = filter_context_for_role(context_json, current_user.role)
    user_prompt = build_synthesis_user_prompt(
        query_text=payload.query_text,
        intent=intent,
        validated_reasoning=json.dumps(reasoning_json, default=str),
    )

    started = perf_counter()
    settings = get_settings()
    llm = LLMClient()
    try:
        answer_text = await llm.generate_structured(
            system=QUALITY_SYNTHESIS_PROMPT,
            user=user_prompt,
            context=scoped_context,
            json_mode=intent in {"impact", "historical"},
        )
    except Exception:
        answer_text = (
            f"Quality status based on evidence: {json.dumps(reasoning_json, default=str)}. "
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
