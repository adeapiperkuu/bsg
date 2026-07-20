"""Controlled learning-rule application for recommendation optimization (Phase 13).

Allowed effects only: ranking, confidence_adjustment, duplicate_suppression,
cooldown, explanation_strategy, evidence_requirements.

Never creates escalations, accepts/dismisses recommendations, suppresses critical
triggers, or mutates governance records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_RULE_EFFECTS = frozenset(
    {
        "ranking",
        "confidence_adjustment",
        "duplicate_suppression",
        "cooldown",
        "explanation_strategy",
        "evidence_requirements",
    }
)

FORBIDDEN_RULE_KEYS = frozenset(
    {
        "auto_accept",
        "auto_dismiss",
        "auto_escalate",
        "create_escalation",
        "create_action",
        "suppress_critical",
        "mutate_governance",
        "overwrite_confidence",
    }
)


@dataclass(frozen=True)
class RecommendationCandidateView:
    id: str
    title: str
    confidence: float
    priority: str
    trigger_type: str | None
    fingerprint: str | None
    evidence_count: int
    ranking_score: float
    explanation_strategy: str = "default"
    suppress: bool = False
    cooldown_hours: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleApplicationResult:
    candidates: list[RecommendationCandidateView]
    applied_effects: list[str]
    rejected_effects: list[str]
    explanations: list[str]


def validate_rule_payload(rule_type: str, payload: dict[str, Any]) -> list[str]:
    """Return validation errors; empty list means safe to approve."""
    errors: list[str] = []
    if rule_type not in ALLOWED_RULE_EFFECTS:
        errors.append(f"rule_type '{rule_type}' is not an allowed effect")
    for key in payload:
        if key in FORBIDDEN_RULE_KEYS:
            errors.append(f"forbidden payload key '{key}'")
    if payload.get("suppress_critical") is True:
        errors.append("cannot suppress critical trigger types")
    if payload.get("overwrite_original_confidence") is True:
        errors.append("cannot overwrite original confidence")
    return errors


def apply_learning_rule(
    candidates: list[RecommendationCandidateView],
    *,
    rule_type: str,
    rule_payload: dict[str, Any],
    allowed_effects: list[str] | None = None,
) -> RuleApplicationResult:
    """Apply a single approved learning rule in-memory (shadow or active ranking)."""
    allowed = set(allowed_effects or ALLOWED_RULE_EFFECTS) & ALLOWED_RULE_EFFECTS
    applied: list[str] = []
    rejected: list[str] = []
    explanations: list[str] = []

    if rule_type not in allowed:
        return RuleApplicationResult(
            candidates=list(candidates),
            applied_effects=[],
            rejected_effects=[rule_type],
            explanations=[f"Effect '{rule_type}' is not permitted"],
        )

    errors = validate_rule_payload(rule_type, rule_payload)
    if errors:
        return RuleApplicationResult(
            candidates=list(candidates),
            applied_effects=[],
            rejected_effects=[rule_type],
            explanations=errors,
        )

    working = list(candidates)

    if rule_type == "ranking":
        boost = float(rule_payload.get("boost", 0.0))
        priority_weights = rule_payload.get("priority_weights") or {}
        trigger_boosts = rule_payload.get("trigger_boosts") or {}
        updated: list[RecommendationCandidateView] = []
        for item in working:
            score = item.ranking_score + boost
            score += float(priority_weights.get(item.priority, 0.0))
            if item.trigger_type:
                score += float(trigger_boosts.get(item.trigger_type, 0.0))
            updated.append(
                RecommendationCandidateView(
                    **{**item.__dict__, "ranking_score": score}
                )
            )
        working = sorted(updated, key=lambda c: c.ranking_score, reverse=True)
        applied.append("ranking")
        explanations.append(f"Applied ranking boost={boost}")

    elif rule_type == "confidence_adjustment":
        # Adjust display/ranking confidence only — never mutate stored original.
        delta = float(rule_payload.get("delta", 0.0))
        clamp_min = float(rule_payload.get("min", 0.0))
        clamp_max = float(rule_payload.get("max", 1.0))
        updated = []
        for item in working:
            adjusted = max(clamp_min, min(clamp_max, item.confidence + delta))
            meta = {**item.metadata, "adjusted_confidence": adjusted, "original_confidence": item.confidence}
            ranking = item.ranking_score + (adjusted - item.confidence)
            updated.append(
                RecommendationCandidateView(
                    **{**item.__dict__, "ranking_score": ranking, "metadata": meta}
                )
            )
        working = updated
        applied.append("confidence_adjustment")
        explanations.append(f"Adjusted ranking confidence by delta={delta}")

    elif rule_type == "duplicate_suppression":
        seen: set[str] = set()
        kept: list[RecommendationCandidateView] = []
        suppressed = 0
        for item in working:
            key = (item.fingerprint or item.title or item.id).strip().lower()
            if key in seen:
                suppressed += 1
                kept.append(RecommendationCandidateView(**{**item.__dict__, "suppress": True}))
            else:
                seen.add(key)
                kept.append(item)
        working = [c for c in kept if not c.suppress] + [c for c in kept if c.suppress]
        applied.append("duplicate_suppression")
        explanations.append(f"Marked {suppressed} duplicate candidates for suppression")

    elif rule_type == "cooldown":
        hours = float(rule_payload.get("hours", 24))
        trigger_types = set(rule_payload.get("trigger_types") or [])
        updated = []
        for item in working:
            if trigger_types and item.trigger_type not in trigger_types:
                updated.append(item)
                continue
            updated.append(
                RecommendationCandidateView(**{**item.__dict__, "cooldown_hours": hours})
            )
        working = updated
        applied.append("cooldown")
        explanations.append(f"Applied cooldown_hours={hours}")

    elif rule_type == "explanation_strategy":
        strategy = str(rule_payload.get("strategy", "evidence_first"))
        working = [
            RecommendationCandidateView(**{**c.__dict__, "explanation_strategy": strategy})
            for c in working
        ]
        applied.append("explanation_strategy")
        explanations.append(f"Selected explanation strategy '{strategy}'")

    elif rule_type == "evidence_requirements":
        min_evidence = int(rule_payload.get("min_evidence", 1))
        updated = []
        demoted = 0
        for item in working:
            if item.evidence_count < min_evidence:
                demoted += 1
                updated.append(
                    RecommendationCandidateView(
                        **{
                            **item.__dict__,
                            "ranking_score": item.ranking_score - 10.0,
                            "metadata": {
                                **item.metadata,
                                "evidence_requirement_failed": True,
                                "min_evidence": min_evidence,
                            },
                        }
                    )
                )
            else:
                updated.append(item)
        working = sorted(updated, key=lambda c: c.ranking_score, reverse=True)
        applied.append("evidence_requirements")
        explanations.append(f"Demoted {demoted} candidates below min_evidence={min_evidence}")

    else:
        rejected.append(rule_type)

    return RuleApplicationResult(
        candidates=working,
        applied_effects=applied,
        rejected_effects=rejected,
        explanations=explanations,
    )


def compare_rankings(
    baseline: list[RecommendationCandidateView],
    optimized: list[RecommendationCandidateView],
) -> dict[str, Any]:
    baseline_order = [c.id for c in baseline if not c.suppress]
    optimized_order = [c.id for c in optimized if not c.suppress]
    moved = 0
    for idx, rec_id in enumerate(baseline_order):
        if rec_id in optimized_order and optimized_order.index(rec_id) != idx:
            moved += 1
    return {
        "baseline_count": len(baseline_order),
        "optimized_count": len(optimized_order),
        "suppressed_count": sum(1 for c in optimized if c.suppress),
        "rank_changes": moved,
        "baseline_top_ids": baseline_order[:10],
        "optimized_top_ids": optimized_order[:10],
    }
