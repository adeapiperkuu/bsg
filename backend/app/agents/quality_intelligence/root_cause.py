from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.drift import (
    GUIDELINE_AMBIGUITY_CATEGORIES,
    MIN_EVALUATED_ITEMS,
    count_recent_annotators,
    fetch_error_entries,
    fetch_prior_snapshot,
)
from app.db.optional_tables import query_optional_table
from app.db.models import (
    Annotator,
    GoldSetEvaluationLog,
    GoldSetMetadata,
    IaaMeasurementRecord,
    QualitySnapshot,
    ReviewerScorecard,
    SopVersionHistory,
    ThroughputSnapshot,
)


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


async def _hypothesis_eval_log_reviewers(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    *,
    accuracy_threshold: float = 85.0,
    min_items: int = 50,
) -> dict[str, Any] | None:
    """Reviewer-level attribution from item-level gold-set evaluation logs."""
    logs = list(
        (
            await session.execute(
                select(GoldSetEvaluationLog).where(
                    GoldSetEvaluationLog.project_id == snapshot.project_id,
                )
            )
        ).scalars()
    )
    if not logs:
        return None

    team_annotators = {
        a.id
        for a in (
            await session.execute(select(Annotator).where(Annotator.team_id == snapshot.team_id))
        ).scalars()
    }

    by_annotator: dict[UUID, list[float]] = {}
    for log in logs:
        if log.annotator_id not in team_annotators or log.score is None:
            continue
        by_annotator.setdefault(log.annotator_id, []).append(float(log.score))

    low_reviewers = [
        aid for aid, scores in by_annotator.items()
        if len(scores) >= min_items and (sum(scores) / len(scores)) < accuracy_threshold
    ]
    if not low_reviewers:
        return None

    avg_acc = sum(sum(by_annotator[aid]) / len(by_annotator[aid]) for aid in low_reviewers) / len(low_reviewers)
    return {
        "factor": "onboarding_gap",
        "contribution_pct": min(90.0, 50.0 + len(low_reviewers) * 10.0),
        "evidence": [
            f"gold_set_evaluation_logs: {len(low_reviewers)} reviewer(s) below {accuracy_threshold}% "
            f"over {min_items}+ items (avg {avg_acc:.1f}%)"
        ],
    }


async def _hypothesis_onboarding_scorecards(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    threshold: float = 85.0,
) -> dict[str, Any] | None:
    scorecards = list(
        (
            await session.execute(
                select(ReviewerScorecard).where(
                    ReviewerScorecard.project_id == snapshot.project_id,
                    ReviewerScorecard.iso_year == snapshot.iso_year,
                    ReviewerScorecard.iso_week == snapshot.iso_week,
                    ReviewerScorecard.items_evaluated >= 50,
                )
            )
        ).scalars()
    )
    if not scorecards:
        return None

    team_annotators = {
        a.id
        for a in (
            await session.execute(select(Annotator).where(Annotator.team_id == snapshot.team_id))
        ).scalars()
    }
    low = [
        s for s in scorecards
        if s.annotator_id in team_annotators
        and s.accuracy_pct is not None
        and float(s.accuracy_pct) < threshold
    ]
    if not low:
        return None

    return {
        "factor": "onboarding_gap",
        "contribution_pct": min(85.0, 45.0 + len(low) * 12.0),
        "evidence": [
            f"reviewer_scorecards:{s.id} accuracy {s.accuracy_pct}%"
            for s in low[:3]
        ],
    }


async def _hypothesis_sop_change(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> dict[str, Any] | None:
    window_start = date.today() - timedelta(days=14)
    recent = (
        await session.execute(
            select(SopVersionHistory)
            .where(
                SopVersionHistory.org_id == snapshot.org_id,
                SopVersionHistory.effective_date >= window_start,
            )
            .order_by(SopVersionHistory.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not recent:
        return None
    return {
        "factor": "sop_change",
        "contribution_pct": 60.0,
        "evidence": [
            f"sop_version_history:{recent.id} version {recent.version} effective {recent.effective_date}",
        ],
    }


async def _hypothesis_gold_set_version(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> dict[str, Any] | None:
    meta_rows = list(
        (
            await session.execute(
                select(GoldSetMetadata)
                .where(GoldSetMetadata.project_id == snapshot.project_id)
                .order_by(GoldSetMetadata.last_updated.desc())
                .limit(2)
            )
        ).scalars()
    )
    if len(meta_rows) < 2:
        return None
    if meta_rows[0].version != meta_rows[1].version:
        return {
            "factor": "gold_set_version_change",
            "contribution_pct": 55.0,
            "evidence": [
                f"gold_set_metadata:{meta_rows[0].id} version changed {meta_rows[1].version} → {meta_rows[0].version}",
            ],
        }
    return None


async def _hypothesis_workload_fatigue(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> dict[str, Any] | None:
    rows = list(
        (
            await session.execute(
                select(ThroughputSnapshot)
                .where(ThroughputSnapshot.project_id == snapshot.project_id)
                .order_by(ThroughputSnapshot.snapshot_date.desc())
                .limit(28)
            )
        ).scalars()
    )
    if len(rows) < 5:
        return None
    latest = rows[0].rolling_7day_units
    if latest is None:
        return None
    prior_vals = [r.rolling_7day_units for r in rows[1:5] if r.rolling_7day_units is not None]
    if not prior_vals:
        return None
    avg = sum(prior_vals) / len(prior_vals)
    if avg <= 0:
        return None
    if latest > avg * 1.1:
        return {
            "factor": "workload_fatigue",
            "contribution_pct": 50.0,
            "evidence": [
                f"throughput_snapshots:{rows[0].id} 7-day units {latest} vs 4-week avg {avg:.0f} (+10%)",
            ],
        }
    return None


async def _hypothesis_systemic_iaa(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> dict[str, Any] | None:
    records = list(
        (
            await session.execute(
                select(IaaMeasurementRecord).where(
                    IaaMeasurementRecord.project_id == snapshot.project_id,
                    IaaMeasurementRecord.iso_year == snapshot.iso_year,
                    IaaMeasurementRecord.iso_week == snapshot.iso_week,
                )
            )
        ).scalars()
    )
    low = [r for r in records if r.krippendorff_alpha is not None and float(r.krippendorff_alpha) < 0.80]
    if len(low) < 3:
        return None
    return {
        "factor": "systemic_sop_ambiguity",
        "contribution_pct": min(80.0, 40.0 + len(low) * 8.0),
        "evidence": [f"iaa_measurement_records:{r.id} α={r.krippendorff_alpha}" for r in low[:3]],
    }


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

    eval_factor = await query_optional_table(
        session,
        lambda: _hypothesis_eval_log_reviewers(session, snapshot),
        None,
    )
    if eval_factor:
        factors.append(eval_factor)
    else:
        scorecard_factor = await query_optional_table(
            session,
            lambda: _hypothesis_onboarding_scorecards(session, snapshot),
            None,
        )
        if scorecard_factor:
            factors.append(scorecard_factor)
        else:
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

    sop_change = await query_optional_table(
        session,
        lambda: _hypothesis_sop_change(session, snapshot),
        None,
    )
    if sop_change:
        factors.append(sop_change)

    gold_ver = await query_optional_table(
        session,
        lambda: _hypothesis_gold_set_version(session, snapshot),
        None,
    )
    if gold_ver:
        factors.append(gold_ver)

    workload = await _hypothesis_workload_fatigue(session, snapshot)
    if workload:
        factors.append(workload)

    systemic_iaa = await query_optional_table(
        session,
        lambda: _hypothesis_systemic_iaa(session, snapshot),
        None,
    )
    if systemic_iaa:
        factors.append(systemic_iaa)
    else:
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
                "evidence": ["No dominant signal in available data"],
            }
        )

    factors.sort(key=lambda f: f["contribution_pct"], reverse=True)
    primary = factors[0]["factor"]
    top_contribution = factors[0]["contribution_pct"]
    dominant_cat, _ = _dominant_error_category(entries)
    new_annotators = await count_recent_annotators(session, snapshot.team_id)
    ambiguity_share = sum(
        float(e.share_pct)
        for e in entries
        if e.error_category.lower() in {c.lower() for c in GUIDELINE_AMBIGUITY_CATEGORIES}
    )

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
    if primary in {"onboarding_gap", "workload_fatigue"}:
        return [
            {
                "rank": 1,
                "action": f"Schedule calibration session for {max(new_annotators, 1)} flagged reviewer(s)",
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
    if primary in {"sop_ambiguity", "sop_change", "systemic_sop_ambiguity"}:
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
    if primary == "gold_set_version_change":
        return [
            {
                "rank": 1,
                "action": "Review gold-set version change impact and re-baseline accuracy expectations",
                "target": "QA Lead",
                "expected_outcome": "Stabilised accuracy within 2 weeks post version change",
                "estimated_effort": "2 hours",
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
