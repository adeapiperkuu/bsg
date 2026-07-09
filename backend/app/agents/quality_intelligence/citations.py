"""Citation validation for evidence-grounded quality NL responses (BR-02)."""

from __future__ import annotations

import re
from uuid import UUID

from app.agents.quality_intelligence.evidence_pack import EvidencePack
from app.agents.quality_intelligence.root_cause import Signal
from app.schemas.domain import LLMRootCause
from app.services.evidence import EvidenceInput

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

_PII_FIELD_PATTERN = re.compile(r"\b(annotator_id|reviewer_id|full_name)\b", re.IGNORECASE)

CONTRIBUTION_SUM_MIN = 90.0
CONTRIBUTION_SUM_MAX = 110.0
HIGH_CONFIDENCE_MIN_PRIMARY_PCT = 50.0


def allowed_evidence_ids(evidence: list[EvidenceInput]) -> set[str]:
    return {str(item.source_row_id) for item in evidence}


def strip_ungrounded_citations(answer_text: str, evidence: list[EvidenceInput]) -> str:
    """Remove UUID citations that are not in the evidence set."""
    allowed = allowed_evidence_ids(evidence)
    if not allowed:
        return answer_text

    def _replace(match: re.Match[str]) -> str:
        uid = match.group(0)
        return uid if uid in allowed else "[citation removed — not in evidence]"

    return _UUID_PATTERN.sub(_replace, answer_text)


def append_evidence_index(answer_text: str, evidence: list[EvidenceInput]) -> str:
    if not evidence:
        return answer_text
    lines = ["", "Evidence:"]
    for item in evidence[:12]:
        lines.append(f"- {item.source_table}:{item.source_row_id} — {item.description}")
    return answer_text + "\n".join(lines)


def validate_reasoning(
    llm_out: LLMRootCause,
    pack: EvidencePack,
    signals: list[Signal] | None = None,
) -> tuple[bool, LLMRootCause, list[str]]:
    """Validate an LLM-produced root-cause reasoning object against the
    evidence pack it was derived from (quality_reasoning_upgrade_plan.md §6).

    Returns (ok, cleaned_result, reasons). ok=False means the caller must fall
    back to the deterministic engine — a rejection is the guardrail working
    as intended, not an error to be surfaced to the user.
    """
    reasons: list[str] = []
    signal_by_hypothesis = {s.hypothesis: s for s in (signals or [])}

    # 0. The primary driver must correspond to a hypothesis the deterministic
    #    pre-pass actually observed, when it maps to one of the six known
    #    hypotheses at all (a genuinely novel_findings-derived primary_driver
    #    won't match any signal and is left alone). An LLM asserting, say,
    #    "workload_fatigue" as the primary cause when the pre-pass found no
    #    sustained spike — or worse, inverted the metric's meaning (treating
    #    below-average throughput as evidence of overwork) — is exactly the
    #    failure mode this pipeline exists to prevent.
    primary_signal = signal_by_hypothesis.get(llm_out.primary_driver)
    if primary_signal is not None and not primary_signal.observed:
        facts = "; ".join(primary_signal.facts) or "no supporting facts"
        return False, llm_out, [
            f"Primary driver '{llm_out.primary_driver}' contradicts the deterministic pre-pass "
            f"(observed=False: {facts})"
        ]

    # Non-primary factors that claim a large share of an unobserved
    # hypothesis aren't fatal (the primary driver carries the conclusion),
    # but are logged for the audit trail.
    for f in llm_out.factors:
        sig = signal_by_hypothesis.get(f.factor)
        if sig is not None and not sig.observed and f.contribution_pct > 15.0:
            reasons.append(
                f"Factor '{f.factor}' assigned {f.contribution_pct}% despite the pre-pass marking it not observed"
            )

    # 1. No raw PII anywhere in the structured output. Belt-and-suspenders —
    #    the evidence pack itself never contains reviewer names or annotator
    #    UUIDs, so this should never trigger, but we assert it (BR-03).
    raw_text = " ".join(
        [
            llm_out.primary_driver,
            *[f.factor for f in llm_out.factors],
            *[f.reasoning for f in llm_out.factors],
            *llm_out.competing_hypotheses_ruled_out,
            *llm_out.novel_findings,
            *[a.action for a in llm_out.recommended_actions],
            *[a.evidence_basis or "" for a in llm_out.recommended_actions],
            *llm_out.data_gaps,
        ]
    )
    if _PII_FIELD_PATTERN.search(raw_text):
        return False, llm_out, ["LLM output referenced a raw PII field name (annotator_id/reviewer_id/full_name)"]

    # 2. Every cited evidence_key must exist in the pack's key_index. Drop
    #    unknown keys from individual factors; reject outright if the primary
    #    driver's factor cited keys but none of them survive validation.
    cleaned_factors = []
    primary_factor_lost_all_citations = False
    for f in llm_out.factors:
        valid_keys = [k for k in f.evidence_keys if k in pack.key_index]
        if len(valid_keys) < len(f.evidence_keys):
            reasons.append(f"Dropped ungrounded evidence_keys for factor '{f.factor}'")
        if f.factor == llm_out.primary_driver and f.evidence_keys and not valid_keys:
            primary_factor_lost_all_citations = True
        cleaned_factors.append(f.model_copy(update={"evidence_keys": valid_keys}))

    if primary_factor_lost_all_citations:
        return False, llm_out, [*reasons, "Primary driver's factor cited no evidence present in the pack"]

    # 3. Recommended-action evidence_basis should reference something real
    #    (an evidence_key, an OKA lesson title, or a SOP version) when set.
    lesson_titles = {str(lesson.get("title", "")).lower() for lesson in pack.oka_lessons if lesson.get("title")}
    for action in llm_out.recommended_actions:
        if not action.evidence_basis:
            continue
        basis_lower = action.evidence_basis.lower()
        grounded = any(key.lower() in basis_lower for key in pack.key_index) or any(
            title in basis_lower for title in lesson_titles
        )
        if not grounded:
            reasons.append(f"Recommended action evidence_basis not traceable to pack: {action.evidence_basis!r}")

    # 4. Contribution percentages should sum to ~100. Renormalize rather than
    #    reject outright — a scaling error is not the same as a fabrication.
    total_pct = sum(f.contribution_pct for f in cleaned_factors)
    if cleaned_factors and not (CONTRIBUTION_SUM_MIN <= total_pct <= CONTRIBUTION_SUM_MAX):
        if total_pct <= 0:
            return False, llm_out, [*reasons, f"Contribution percentages summed to {total_pct} — cannot renormalize"]
        scale = 100.0 / total_pct
        cleaned_factors = [
            f.model_copy(update={"contribution_pct": round(f.contribution_pct * scale, 1)}) for f in cleaned_factors
        ]
        reasons.append(f"Renormalized contribution_pct (raw sum was {total_pct:.1f})")

    # 5. Confidence discipline (§7.5 / BR-04): "high" requires the primary
    #    factor to carry more than half the total weight.
    confidence = llm_out.confidence
    primary_pct = next((f.contribution_pct for f in cleaned_factors if f.factor == llm_out.primary_driver), 0.0)
    if confidence == "high" and primary_pct <= HIGH_CONFIDENCE_MIN_PRIMARY_PCT:
        confidence = "medium"
        reasons.append(
            f"Downgraded confidence high -> medium: primary factor only {primary_pct:.1f}% of total weight"
        )

    cleaned = llm_out.model_copy(update={"factors": cleaned_factors, "confidence": confidence})
    return True, cleaned, reasons
