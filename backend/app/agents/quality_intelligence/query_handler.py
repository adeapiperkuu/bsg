from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.retrieval import keyword_search
from app.agents.quality_intelligence.citations import append_evidence_index, strip_ungrounded_citations
from app.agents.quality_intelligence.drift import DriftResult, evaluate_drift, fetch_prior_snapshot
from app.agents.quality_intelligence.evidence_pack import EvidencePack, build_evidence_pack
from app.agents.quality_intelligence.oka_client import OKAClient
from app.agents.quality_intelligence.prompts import QUALITY_SYNTHESIS_PROMPT, build_synthesis_user_prompt
from app.agents.quality_intelligence.reasoning import reason_root_cause
from app.agents.quality_intelligence.root_cause import RootCauseResult, Signal, extract_signals
from app.agents.quality_intelligence.rework_metrics import compute_rework_impact
from app.agents.quality_intelligence.what_if import analyze_what_if, what_if_to_read
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AlertStatus,
    AlertType,
    KnowledgeLesson,
    Milestone,
    Project,
    QualitySnapshot,
    RiskAlert,
)
from app.schemas.common import EvidenceLinkRead
from app.schemas.domain import AgentQueryCreate, AgentQueryRead
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
    oka_lessons: list[dict[str, object]],
) -> tuple[dict[str, object], list[EvidenceInput]]:
    # oka_lessons is fetched exactly once per query by the caller (dedupe —
    # this used to make its own second, redundant OKA call with identical
    # arguments to the unconditional top-level lookup below).
    lessons: list[dict[str, object]] = oka_lessons
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


# ── Shared pipeline (streaming + non-streaming) ────────────────────────────────
#
# answer_quality_query (non-streaming) and stream_quality_query (SSE) share the
# exact same evidence-gathering, reasoning, context-assembly, and
# post-processing/persistence logic below — they diverge ONLY at the synthesis
# LLM call itself (generate_structured vs. stream_structured). This guarantees
# the streamed `done` payload is produced by the identical pipeline as the
# non-streaming response for the same query.
#
# The pipeline is split into two phases so a streaming caller can emit a
# "reasoning" status event immediately before the ~9s root-cause LLM call
# (which must run inside _gather_quality_evidence's caller, not inside it,
# so the status event can be yielded first):
#   1. _gather_quality_evidence  — DB reads + optional intent-classification
#      LLM call only. Fast. Returns whatever reason_root_cause needs.
#   2. reason_root_cause          — the ~9s reasoning LLM call itself (or a
#      no-op when there's no snapshot to reason about).
#   3. _finish_quality_context    — reasoning-dependent context assembly
#      (intent-specific extra context, evidence merge, prompt build).
#   4. <synthesis LLM call>       — generate_structured or stream_structured.
#   5. _finalize_quality_answer   — shared post-processing + persistence.


@dataclass
class _QualityEvidenceContext:
    """Result of the (fast) evidence-gathering phase — everything needed to
    either run the root-cause reasoning LLM call or, if no snapshot exists for
    this project yet, skip straight to the fallback evidence path."""

    project: Project
    intent: str
    oka_lessons: list[dict[str, object]]
    latest: QualitySnapshot | None
    pack: EvidencePack | None = None
    signals: list[Signal] | None = None
    drift: DriftResult | None = None
    prior_snapshot: QualitySnapshot | None = None
    fallback_auto_evidence: list[EvidenceInput] | None = None
    fallback_context: dict[str, object] | None = None

    @property
    def needs_reasoning(self) -> bool:
        return self.latest is not None


@dataclass
class _QualityPrepared:
    """Result of the reasoning-dependent context-assembly phase — everything
    needed to run the synthesis LLM call and, afterward, finalize/persist."""

    project: Project
    evidence_list: list[EvidenceInput]
    scoped_context: str
    user_prompt: str
    json_mode: bool
    reasoning_json: dict[str, object]
    started: float


async def _gather_quality_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
) -> _QualityEvidenceContext:
    """Evidence-gathering phase: DB reads plus the (optional) intent
    classification LLM call. Deliberately does NOT call reason_root_cause —
    callers run that separately so a streaming caller can emit a "reasoning"
    status event right before that ~9s call starts."""
    if not payload.project_id:
        raise ValueError("Quality queries require a project_id.")

    project = await get_visible_project(session, payload.project_id, current_user)
    # PHASE 2B prod-hardening (no-op in dev, where llm_intent_routing is off
    # and classify_intent_llm returns None before ever calling the LLM):
    # classify_intent_llm() doesn't touch `session`, so it's safe to run
    # concurrently with the first session-bound evidence fetch instead of
    # serially in front of it — avoids stacking an intent-classification LLM
    # round trip in front of DB evidence gathering when the flag is enabled.
    llm_intent, latest = await asyncio.gather(
        classify_intent_llm(payload.query_text),
        _fetch_latest_snapshot(session, project.id),
    )
    intent = llm_intent or classify_intent(payload.query_text)

    # Fetched exactly once per query (dedupe — this used to be called a
    # second time, with identical arguments, inside _build_historical_context
    # for intent=="historical" queries). Non-blocking / inert when
    # oka_base_url is unset (oka_client.py short-circuits to []).
    oka = OKAClient()
    oka_lessons = await oka.retrieve_lessons(org_id=str(project.org_id), error_category="quality")

    if latest is None:
        auto_evidence, fallback_context = await _fallback_evidence_no_snapshot(session, project.id)
        return _QualityEvidenceContext(
            project=project,
            intent=intent,
            oka_lessons=oka_lessons,
            latest=None,
            fallback_auto_evidence=auto_evidence,
            fallback_context=fallback_context,
        )

    # Pack is built once per query, role-scoped at the source (reviewer
    # detail is simply absent from the pack for CLIENT, not scrubbed
    # after the fact). See evidence_pack.py.
    pack = await build_evidence_pack(session, latest, role=current_user.role)
    signals = extract_signals(pack)
    drift = await evaluate_drift(session, latest)
    prior_snapshot = await fetch_prior_snapshot(session, latest)
    return _QualityEvidenceContext(
        project=project,
        intent=intent,
        oka_lessons=oka_lessons,
        latest=latest,
        pack=pack,
        signals=signals,
        drift=drift,
        prior_snapshot=prior_snapshot,
    )


async def _finish_quality_context(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    ctx: _QualityEvidenceContext,
    root_cause: RootCauseResult | None,
    evidence: list[EvidenceInput] | None,
) -> _QualityPrepared:
    """Reasoning-dependent phase: builds reasoning_json, handles intent-
    specific extra context (what_if/impact/historical), merges evidence, and
    assembles the synthesis prompt. Raises ApiError (409 EVIDENCE_REQUIRED) if
    the merged evidence set ends up empty."""
    project = ctx.project
    intent = ctx.intent
    oka_lessons = ctx.oka_lessons
    reasoning_json: dict[str, object] = {}

    if ctx.latest is None:
        auto_evidence = list(ctx.fallback_auto_evidence or [])
        context: dict[str, object] = dict(ctx.fallback_context or {})
    else:
        assert ctx.pack is not None and ctx.drift is not None and root_cause is not None
        pack = ctx.pack
        drift = ctx.drift
        prior_snapshot = ctx.prior_snapshot

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
                    ctx.latest.gold_set_accuracy_pct,
                    prior_snapshot.gold_set_accuracy_pct if prior_snapshot else None,
                ),
                "rework_rate_wow": _wow_direction(
                    ctx.latest.rework_rate_pct,
                    prior_snapshot.rework_rate_pct if prior_snapshot else None,
                ),
                "iaa_wow": _wow_direction(
                    ctx.latest.iaa_krippendorff_alpha,
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
                session, project.id, project.org_id, payload.query_text, oka_lessons
            )
            context.update(historical_context)
            auto_evidence.extend(historical_evidence)

    merged = {str(e.source_row_id): e for e in (evidence or [])}
    for item in auto_evidence:
        merged.setdefault(str(item.source_row_id), item)
    evidence_list = list(merged.values())
    require_evidence(evidence_list)

    # Unconditional top-level context population, matching pre-existing
    # behavior — independent of whatever intent-specific lessons were already
    # gathered above. Reuses the single oka_lessons fetch from the top of
    # this function (PHASE 2B dedupe) rather than issuing a second identical
    # OKA call.
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

    return _QualityPrepared(
        project=project,
        evidence_list=evidence_list,
        scoped_context=scoped_context,
        user_prompt=user_prompt,
        json_mode=intent in {"impact", "historical"},
        reasoning_json=reasoning_json,
        started=perf_counter(),
    )


def _quality_fallback_answer_text(reasoning_json: dict[str, object]) -> str:
    return (
        f"Quality status based on evidence: {json.dumps(reasoning_json, default=str)}. "
        "LLM synthesis unavailable; showing pre-computed analysis only."
    )


async def _finalize_quality_answer(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    prepared: _QualityPrepared,
    answer_text: str,
) -> AgentQuery:
    """Shared post-processing + persistence for both the non-streaming and
    streaming synthesis paths — identical grounding/citation guarantees and
    identical AgentQuery / AgentQueryEvidenceLink rows either way."""
    answer_text = strip_ungrounded_citations(answer_text, prepared.evidence_list)
    answer_text = append_evidence_index(answer_text, prepared.evidence_list)
    answer_text = filter_response_for_role(answer_text, current_user.role)

    settings = get_settings()
    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=prepared.project.id,
        agent_name=payload.agent_name,
        query_text=payload.query_text,
        answer_text=answer_text,
        model_used=settings.llm_model,
        latency_ms=int((perf_counter() - prepared.started) * 1000),
    )
    session.add(query)
    await session.flush()
    for item in prepared.evidence_list:
        session.add(
            AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return query


async def answer_quality_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    ctx = await _gather_quality_evidence(session, current_user, payload)
    # NOTE (PHASE 2B): a single-call merge of this reasoning step with the
    # synthesis call below was implemented and measured live against the
    # running dev server, then reverted — see reasoning.py's module
    # docstring / the Phase 2B report for the before/after numbers. The
    # merge did not reduce p50 latency in practice (it measured *slower*)
    # because the combined prompt still pays for generating the full
    # answer text even on the (frequent, in this evidence pack) branch
    # where the root-cause half fails grounding validation and has to be
    # discarded — so the two-call flow below is intentionally kept as-is.
    root_cause = (
        await reason_root_cause(session, ctx.latest, ctx.pack, ctx.signals)  # type: ignore[arg-type]
        if ctx.needs_reasoning
        else None
    )
    prepared = await _finish_quality_context(session, current_user, payload, ctx, root_cause, evidence)

    llm = LLMClient()
    try:
        answer_text = await llm.generate_structured(
            system=QUALITY_SYNTHESIS_PROMPT,
            user=prepared.user_prompt,
            context=prepared.scoped_context,
            json_mode=prepared.json_mode,
        )
    except Exception:
        answer_text = _quality_fallback_answer_text(prepared.reasoning_json)

    return await _finalize_quality_answer(session, current_user, payload, prepared, answer_text)


# ── SSE streaming ──────────────────────────────────────────────────────────────


def _sse(data: dict[str, object]) -> str:
    """Format a dict as a single SSE line, matching this repo's other
    streaming endpoints (knowledge/ask/stream, delivery/chat/stream)."""
    return f"data: {json.dumps(data, default=str)}\n\n"


async def _quality_query_read_payload(session: AsyncSession, query: AgentQuery) -> dict[str, object]:
    """Build the exact same shape POST /agent-queries returns
    (routes/agents.py::_agent_query_read + _query_evidence) so the SSE `done`
    payload is identical in content to the non-streaming response."""
    data = AgentQueryRead.model_validate(query)
    params = query.retrieval_params or {}
    data.confidence_level = params.get("confidence_level") if isinstance(params.get("confidence_level"), str) else None
    data.insufficient_evidence = bool(params.get("insufficient_evidence", False))
    related_records = params.get("related_records")
    data.related_records = related_records if isinstance(related_records, list) else []
    source_agents = params.get("source_agents_used")
    data.source_agents_used = source_agents if isinstance(source_agents, list) else []

    links = list(
        (
            await session.execute(
                select(AgentQueryEvidenceLink).where(AgentQueryEvidenceLink.agent_query_id == query.id)
            )
        ).scalars()
    )
    data.evidence_links = [EvidenceLinkRead.model_validate(item) for item in links]
    return data.model_dump(mode="json")


async def stream_quality_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AsyncGenerator[str, None]:
    """SSE-streaming counterpart to answer_quality_query.

    Shares _gather_quality_evidence / _finish_quality_context /
    _finalize_quality_answer with the non-streaming path — the two diverge
    ONLY at the synthesis LLM call (generate_structured vs. stream_structured)
    — so the final `done` payload is produced by an identical pipeline (same
    evidence, same grounding/citation post-processing, same persistence) to
    what POST /agent-queries returns for the same query.

    Event shapes:
      data: {"type": "status", "phase": "gathering_evidence" | "reasoning" | "writing"}
      data: {"type": "delta", "text": "<token>"}
      data: {"type": "done", "data": <AgentQueryRead JSON>}
      data: {"type": "error", "code": "...", "message": "...", "retryable": bool}
    """
    yield _sse({"type": "status", "phase": "gathering_evidence"})
    try:
        ctx = await _gather_quality_evidence(session, current_user, payload)
    except ValueError as exc:
        yield _sse({"type": "error", "code": "VALIDATION_ERROR", "message": str(exc), "retryable": False})
        return
    except ApiError as exc:
        yield _sse({"type": "error", "code": exc.code, "message": exc.message, "retryable": False})
        return

    root_cause: RootCauseResult | None = None
    if ctx.needs_reasoning:
        yield _sse({"type": "status", "phase": "reasoning"})
        root_cause = await reason_root_cause(session, ctx.latest, ctx.pack, ctx.signals)  # type: ignore[arg-type]

    try:
        prepared = await _finish_quality_context(session, current_user, payload, ctx, root_cause, evidence)
    except ApiError as exc:
        yield _sse({"type": "error", "code": exc.code, "message": exc.message, "retryable": False})
        return

    yield _sse({"type": "status", "phase": "writing"})

    llm = LLMClient()
    accumulated_answer = ""
    final_answer_text = ""
    async for event in llm.stream_structured(
        system=QUALITY_SYNTHESIS_PROMPT,
        user=prepared.user_prompt,
        context=prepared.scoped_context,
        json_mode=prepared.json_mode,
    ):
        if event.get("type") == "delta":
            text = str(event.get("text") or "")
            if text:
                accumulated_answer += text
                yield _sse({"type": "delta", "text": text})
        elif event.get("type") == "done":
            final_answer_text = str(event.get("answer_text") or "")

    answer_text = (final_answer_text or accumulated_answer).strip()
    if not answer_text:
        answer_text = _quality_fallback_answer_text(prepared.reasoning_json)

    query = await _finalize_quality_answer(session, current_user, payload, prepared, answer_text)
    await session.flush()

    data = await _quality_query_read_payload(session, query)
    yield _sse({"type": "done", "data": data})
