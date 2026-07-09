"""LLM reasoning core for root-cause analysis (quality_reasoning_upgrade_plan.md §3).

reason_root_cause() is the single entry point for computing a snapshot's root
cause: it gates on sample size (BR-05), short-circuits on an unchanged
evidence fingerprint (cost control), and otherwise either calls the LLM
reasoning engine (validated by citations.validate_reasoning) or falls back to
the deterministic waterfall in root_cause.py — never both silently. Shadow
mode runs the LLM engine for divergence logging without affecting the
response, when the main flag is off.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.citations import validate_reasoning
from app.agents.quality_intelligence.drift import MIN_EVALUATED_ITEMS
from app.agents.quality_intelligence.evidence_pack import EvidencePack
from app.agents.quality_intelligence.prompts import QUALITY_REASONING_PROMPT, build_reasoning_user_prompt
from app.agents.quality_intelligence.root_cause import RootCauseResult, Signal, analyze_root_cause_deterministic
from app.core.config import get_settings
from app.db.models import QualitySnapshot
from app.schemas.domain import LLMRootCause
from app.services.llm.client import LLMClient

logger = logging.getLogger(__name__)


def _fingerprint_signals(signals: list[Signal]) -> str:
    """Fingerprint the deterministic feature-extraction pass. Comparing this
    against the last-stored fingerprint tells us whether the evidence that
    matters to root-cause analysis has changed since the last computation —
    the cache key for avoiding redundant LLM calls (plan §9/§10)."""
    payload = [
        {
            "hypothesis": s.hypothesis,
            "observed": s.observed,
            "strength": s.strength,
            "facts": s.facts,
            "evidence_keys": sorted(s.evidence_keys),
        }
        for s in signals
    ]
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _root_cause_from_cache(cached: dict) -> RootCauseResult | None:
    if not isinstance(cached, dict):
        return None
    try:
        return RootCauseResult(
            primary_driver=cached.get("primary_driver"),
            factors=cached.get("factors") or [],
            confidence=cached.get("confidence", "low"),
            recommended_actions=cached.get("recommended_actions") or [],
            blocked=cached.get("blocked", False),
            block_reason=cached.get("block_reason"),
            engine=cached.get("engine", "deterministic"),
            novel_findings=cached.get("novel_findings") or [],
            reasoning_trace=cached.get("reasoning_trace"),
        )
    except Exception:
        logger.exception("Failed to deserialize cached root_cause JSON")
        return None


def _cached_fingerprint(cached: dict | None) -> str | None:
    if not cached:
        return None
    trace = cached.get("reasoning_trace")
    if not isinstance(trace, dict):
        return None
    return trace.get("_signal_fingerprint")


def _with_fingerprint(result: RootCauseResult, fingerprint: str) -> RootCauseResult:
    trace = {**(result.reasoning_trace or {}), "_signal_fingerprint": fingerprint}
    return replace(result, reasoning_trace=trace)


def _llm_root_cause_to_result(
    llm_out: LLMRootCause,
    *,
    model_used: str,
    latency_ms: int,
    validation_reasons: list[str],
) -> RootCauseResult:
    return RootCauseResult(
        primary_driver=llm_out.primary_driver,
        factors=[f.model_dump() for f in llm_out.factors],
        confidence=llm_out.confidence,
        recommended_actions=[a.model_dump() for a in llm_out.recommended_actions],
        blocked=False,
        block_reason=None,
        engine="llm",
        novel_findings=llm_out.novel_findings,
        reasoning_trace={
            "competing_hypotheses_ruled_out": llm_out.competing_hypotheses_ruled_out,
            "data_gaps": llm_out.data_gaps,
            "model_used": model_used,
            "latency_ms": latency_ms,
            "validation_reasons": validation_reasons,
        },
    )


async def _run_llm_reasoning(
    pack: EvidencePack,
    signals: list[Signal],
    snapshot: QualitySnapshot,
) -> tuple[RootCauseResult | None, list[str]]:
    settings = get_settings()
    signals_json = json.dumps(
        [
            {
                "hypothesis": s.hypothesis,
                "observed": s.observed,
                "strength": s.strength,
                "facts": s.facts,
                "evidence_keys": s.evidence_keys,
            }
            for s in signals
        ],
        default=str,
    )
    sample_note = (
        f"Sample size: {snapshot.evaluated_item_count} evaluated items this week "
        f"(minimum for conclusive analysis is {MIN_EVALUATED_ITEMS})."
    )
    user_prompt = build_reasoning_user_prompt(signals_json=signals_json, sample_size_note=sample_note)
    context_json = json.dumps(pack.to_prompt_json(), default=str)

    started = perf_counter()
    model_used = settings.quality_reasoning_model or settings.openai_model or settings.llm_model or "gpt-4o-mini"
    try:
        llm = LLMClient()
        raw = await llm.generate_structured(
            system=QUALITY_REASONING_PROMPT,
            user=user_prompt,
            context=context_json,
            json_mode=True,
        )
        parsed = LLMRootCause.model_validate_json(raw)
    except Exception:
        logger.exception("quality_reasoning_llm_call_failed snapshot_id=%s", snapshot.id)
        return None, ["LLM reasoning call failed or returned invalid/unparseable JSON"]
    latency_ms = int((perf_counter() - started) * 1000)

    ok, cleaned, reasons = validate_reasoning(parsed, pack, signals)
    if not ok:
        logger.warning(
            "quality_reasoning_validation_rejected snapshot_id=%s reasons=%s", snapshot.id, reasons
        )
        return None, reasons

    result = _llm_root_cause_to_result(
        cleaned, model_used=model_used, latency_ms=latency_ms, validation_reasons=reasons
    )
    return result, reasons


async def reason_root_cause(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    pack: EvidencePack,
    signals: list[Signal],
    *,
    force_recompute: bool = False,
) -> RootCauseResult:
    # BR-05: the sample-size gate is enforced unconditionally, before any LLM
    # call — never ask the model for a conclusion on an insufficient sample.
    if snapshot.evaluated_item_count is not None and snapshot.evaluated_item_count < MIN_EVALUATED_ITEMS:
        return await analyze_root_cause_deterministic(session, snapshot)

    fingerprint = _fingerprint_signals(signals)
    cached_json = snapshot.root_cause if isinstance(snapshot.root_cause, dict) else None
    if not force_recompute and _cached_fingerprint(cached_json) == fingerprint:
        cached_result = _root_cause_from_cache(cached_json)
        if cached_result is not None:
            return cached_result

    settings = get_settings()
    has_api_key = bool(settings.openai_api_key or settings.llm_api_key)
    use_llm = bool(settings.quality_llm_reasoning and has_api_key)
    shadow = bool(settings.quality_llm_reasoning_shadow and has_api_key)

    if not use_llm and not shadow:
        result = await analyze_root_cause_deterministic(session, snapshot)
        return _with_fingerprint(result, fingerprint)

    llm_result, llm_reasons = await _run_llm_reasoning(pack, signals, snapshot)

    if use_llm:
        if llm_result is not None:
            return _with_fingerprint(llm_result, fingerprint)
        # Reasoning is enabled but the call failed or was rejected by
        # validation — fall back to the deterministic engine, tagged so the
        # audit trail shows this was a fallback rather than a fresh LLM read.
        fallback = await analyze_root_cause_deterministic(session, snapshot)
        fallback = replace(
            fallback,
            engine="deterministic_fallback",
            reasoning_trace={"fallback_reasons": llm_reasons},
        )
        return _with_fingerprint(fallback, fingerprint)

    # Shadow-only: the deterministic result remains authoritative for the
    # user; we just log where the LLM would have disagreed (plan §10), so
    # the flag can be flipped later with real divergence data in hand.
    deterministic = await analyze_root_cause_deterministic(session, snapshot)
    if llm_result is not None and llm_result.primary_driver != deterministic.primary_driver:
        logger.info(
            "quality_reasoning_shadow_divergence snapshot_id=%s deterministic=%s llm=%s llm_confidence=%s",
            snapshot.id,
            deterministic.primary_driver,
            llm_result.primary_driver,
            llm_result.confidence,
        )
    return _with_fingerprint(deterministic, fingerprint)
