from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.drift import (
    GUIDELINE_AMBIGUITY_CATEGORIES,
    MIN_EVALUATED_ITEMS,
    count_recent_annotators,
    fetch_error_entries,
    fetch_prior_snapshot,
)
from app.db.models import QualitySnapshot


@dataclass(frozen=True)
class RootCauseResult:
    primary_driver: str | None
    factors: list[dict[str, Any]]
    confidence: str
    recommended_actions: list[dict[str, Any]]
    blocked: bool = False
    block_reason: str | None = None


def _dominant_error_category(entries) -> tuple[str | None, float]:
    if not entries:
        return None, 0.0
    top = max(entries, key=lambda e: float(e.share_pct))
    return top.error_category, float(top.share_pct)


async def analyze_root_cause(session: AsyncSession, snapshot: QualitySnapshot) -> RootCauseResult:
    if snapshot.evaluated_item_count is not None and snapshot.evaluated_item_count < MIN_EVALUATED_ITEMS:
        return RootCauseResult(
            primary_driver=None,
            factors=[],
            confidence="low",
            recommended_actions=[],
            blocked=True,
            block_reason=(
                f"Insufficient sample size for conclusive analysis. "
                f"{snapshot.evaluated_item_count} items evaluated; minimum is {MIN_EVALUATED_ITEMS}."
            ),
        )

    entries = await fetch_error_entries(session, snapshot.id)
    prior = await fetch_prior_snapshot(session, snapshot)
    factors: list[dict[str, Any]] = []

    new_annotators = await count_recent_annotators(session, snapshot.team_id)
    dominant_cat, dominant_share = _dominant_error_category(entries)

    if new_annotators > 0:
        contribution = min(70.0, 40.0 + new_annotators * 10.0)
        if dominant_share > 30:
            contribution = min(85.0, contribution + 15.0)
        factors.append(
            {
                "factor": "onboarding_gap",
                "contribution_pct": contribution,
                "evidence": [f"{new_annotators} annotator(s) onboarded within last 14 days on team"],
            }
        )

    ambiguity_share = sum(
        float(e.share_pct)
        for e in entries
        if e.error_category.lower() in {c.lower() for c in GUIDELINE_AMBIGUITY_CATEGORIES}
        or e.error_category in GUIDELINE_AMBIGUITY_CATEGORIES
    )
    iaa_dropped = (
        prior is not None
        and snapshot.iaa_krippendorff_alpha is not None
        and prior.iaa_krippendorff_alpha is not None
        and snapshot.iaa_krippendorff_alpha < prior.iaa_krippendorff_alpha
    )
    if ambiguity_share >= 20.0 and iaa_dropped:
        factors.append(
            {
                "factor": "sop_ambiguity",
                "contribution_pct": min(75.0, ambiguity_share + 20.0),
                "evidence": [
                    f"Guideline ambiguity errors at {ambiguity_share:.1f}% share",
                    "IAA dropped week-over-week across team",
                ],
            }
        )

    if not factors:
        factors.append(
            {
                "factor": "undetermined",
                "contribution_pct": 100.0,
                "evidence": ["No dominant onboarding or SOP ambiguity signal in available data"],
            }
        )

    factors.sort(key=lambda f: f["contribution_pct"], reverse=True)
    primary = factors[0]["factor"]
    top_contribution = factors[0]["contribution_pct"]

    if top_contribution > 50 and primary != "undetermined":
        confidence = "high"
    elif top_contribution >= 35:
        confidence = "medium"
    else:
        confidence = "low"

    actions = _build_recommendations(primary, dominant_cat, new_annotators, ambiguity_share)

    return RootCauseResult(
        primary_driver=primary,
        factors=factors,
        confidence=confidence,
        recommended_actions=actions,
    )


def _build_recommendations(
    primary: str,
    dominant_cat: str | None,
    new_annotators: int,
    ambiguity_share: float,
) -> list[dict[str, Any]]:
    if primary == "onboarding_gap":
        return [
            {
                "rank": 1,
                "action": f"Schedule calibration session for {new_annotators} recently onboarded annotator(s)",
                "target": "QA Lead",
                "expected_outcome": "Gold-set accuracy recovery within 1 week",
                "estimated_effort": "45–60 minutes",
                "priority": "immediate",
            },
            {
                "rank": 2,
                "action": f"Targeted review of {dominant_cat or 'dominant'} error category with worked examples",
                "target": "QA Lead",
                "expected_outcome": "Reduce dominant error share by 30%+",
                "estimated_effort": "2 hours",
                "priority": "this_week",
            },
        ]
    if primary == "sop_ambiguity":
        return [
            {
                "rank": 1,
                "action": "Flag SOP ambiguity for human review and draft clarification with examples",
                "target": "QA Lead",
                "expected_outcome": f"Reduce guideline ambiguity errors from {ambiguity_share:.1f}%",
                "estimated_effort": "4 hours",
                "priority": "immediate",
            },
            {
                "rank": 2,
                "action": "Run team-wide calibration on divergent annotation decisions",
                "target": "QA Lead",
                "expected_outcome": "IAA recovery above 0.85 within 2 weeks",
                "estimated_effort": "1 hour session",
                "priority": "this_week",
            },
        ]
    return [
        {
            "rank": 1,
            "action": "Manual QA review recommended — automated root-cause confidence is low",
            "target": "Delivery Manager",
            "expected_outcome": "Confirmed diagnosis before remediation",
            "estimated_effort": "1–2 hours",
            "priority": "this_week",
        }
    ]


def root_cause_to_json(result: RootCauseResult) -> dict[str, Any]:
    return {
        "primary_driver": result.primary_driver,
        "factors": result.factors,
        "confidence": result.confidence,
        "recommended_actions": result.recommended_actions,
        "blocked": result.blocked,
        "block_reason": result.block_reason,
    }
