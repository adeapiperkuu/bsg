"""UC-05: What-if scenario analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.retrieval import keyword_search
from app.agents.quality_intelligence.comms_prompts import WHAT_IF_SYSTEM_PROMPT
from app.agents.quality_intelligence.oka_client import OKAClient
from app.core.config import get_settings
from app.db.models import Project, QualitySnapshot
from app.schemas.domain import WhatIfQueryRead
from app.services.llm.client import LLMClient


@dataclass(frozen=True)
class WhatIfResult:
    scenario: str
    projected_outcome: str
    assumptions: list[str]
    comparable_lessons: list[dict[str, Any]]
    confidence: str
    no_precedent: bool = False


class WhatIfEngine:
    @staticmethod
    def parse_scenario(query_text: str) -> str:
        lower = query_text.lower()
        if "calibration" in lower:
            return "schedule_calibration"
        if "sop" in lower or "guideline" in lower:
            return "sop_clarification"
        if "rework" in lower:
            return "reduce_rework"
        if "reassign" in lower:
            return "reassignment"
        return "general_intervention"

    @staticmethod
    def rule_projection(scenario: str, snapshots: list[QualitySnapshot]) -> tuple[str, list[str], str]:
        assumptions = ["Projection based on historical quality snapshot patterns"]
        if scenario == "schedule_calibration":
            return (
                "Gold-set accuracy recovery expected within 1–2 weeks based on similar past events",
                assumptions,
                "medium",
            )
        if scenario == "sop_clarification":
            return (
                "Guideline ambiguity errors may reduce 20–40% within 2 weeks after SOP update",
                assumptions,
                "medium",
            )
        if scenario == "reduce_rework":
            return (
                "Targeted error-category review may reduce rework rate by 15–25%",
                [*assumptions, "Assumes rework drivers are category-specific"],
                "low",
            )
        if snapshots:
            accs = [float(s.gold_set_accuracy_pct) for s in snapshots if s.gold_set_accuracy_pct is not None]
            if accs and accs[0] < accs[-1]:
                return (
                    "Historical trend shows recovery after intervention; expect gradual improvement over 2–3 weeks",
                    assumptions,
                    "medium",
                )
        return (
            "Outcome depends on root cause; manual QA review recommended before action",
            [*assumptions, "No strong precedent match for this scenario variable"],
            "low",
        )


def _historical_recovery_patterns(snapshots: list[QualitySnapshot]) -> list[dict[str, Any]]:
    """Compute observed drop-then-recovery sequences from this project's own
    quality snapshot history (oldest to newest), instead of asking the LLM to
    reason over a bare snapshot count. A drop of >=1.0pp that later recovers
    to at least its pre-drop level is a real precedent for a what-if
    projection; one that never recovers within the window is equally
    informative evidence."""
    ordered = sorted(
        (s for s in snapshots if s.gold_set_accuracy_pct is not None),
        key=lambda s: (s.iso_year, s.iso_week),
    )
    patterns: list[dict[str, Any]] = []
    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        delta = float(cur.gold_set_accuracy_pct) - float(prev.gold_set_accuracy_pct)
        if delta > -1.0:
            continue
        drop_level = float(prev.gold_set_accuracy_pct)
        recovered_at = next(
            (s for s in ordered[i + 1 :] if float(s.gold_set_accuracy_pct) >= drop_level),
            None,
        )
        patterns.append(
            {
                "drop_from": f"{prev.gold_set_accuracy_pct}% (W{prev.iso_week})",
                "drop_to": f"{cur.gold_set_accuracy_pct}% (W{cur.iso_week})",
                "recovered_by": (
                    f"{recovered_at.gold_set_accuracy_pct}% (W{recovered_at.iso_week})" if recovered_at else None
                ),
                "weeks_to_recover": (recovered_at.iso_week - cur.iso_week) if recovered_at else None,
            }
        )
    return patterns


async def analyze_what_if(
    session: AsyncSession,
    project: Project,
    query_text: str,
) -> WhatIfResult:
    scenario = WhatIfEngine.parse_scenario(query_text)
    snapshots = list(
        (
            await session.execute(
                select(QualitySnapshot)
                .where(QualitySnapshot.project_id == project.id)
                .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                .limit(8)
            )
        ).scalars()
    )

    fallback_projected, fallback_assumptions, fallback_confidence = WhatIfEngine.rule_projection(
        scenario, snapshots
    )
    patterns = _historical_recovery_patterns(snapshots)

    oka = OKAClient()
    lessons = await oka.retrieve_lessons(org_id=str(project.org_id), task_type=scenario, error_category="")
    if not lessons:
        lessons = await keyword_search(session, project.org_id, query_text, limit=3)

    no_precedent = len(lessons) == 0 and not patterns
    projected, assumptions, confidence = fallback_projected, fallback_assumptions, fallback_confidence

    settings = get_settings()
    if settings.llm_api_key:
        try:
            llm = LLMClient()
            raw = await llm.generate_structured(
                system=WHAT_IF_SYSTEM_PROMPT,
                user=f"What-if query: {query_text}\nScenario: {scenario}",
                context=json.dumps(
                    {
                        "scenario": scenario,
                        "historical_recovery_patterns": patterns,
                        "comparable_lessons": lessons,
                        "recent_snapshot_count": len(snapshots),
                        "rule_based_projection_fallback": {
                            "projected_outcome": fallback_projected,
                            "assumptions": fallback_assumptions,
                            "confidence": fallback_confidence,
                        },
                    },
                    default=str,
                ),
                json_mode=True,
            )
            parsed = json.loads(raw)
            llm_projected = str(parsed.get("projected_outcome", "")).strip()
            llm_assumptions = parsed.get("assumptions")
            llm_confidence = str(parsed.get("confidence", "")).strip().lower()
            if (
                llm_projected
                and isinstance(llm_assumptions, list)
                and llm_assumptions
                and llm_confidence in {"high", "medium", "low"}
            ):
                projected = llm_projected
                assumptions = [str(a) for a in llm_assumptions]
                confidence = llm_confidence
        except Exception:
            pass

    if no_precedent and not any(
        "no comparable" in a.lower() or "no strong precedent" in a.lower() for a in assumptions
    ):
        assumptions = [*assumptions, "No comparable OKA lessons or historical recovery pattern found — projection is speculative"]

    return WhatIfResult(
        scenario=scenario,
        projected_outcome=projected,
        assumptions=assumptions,
        comparable_lessons=lessons,
        confidence=confidence,
        no_precedent=no_precedent,
    )


def what_if_to_read(result: WhatIfResult) -> WhatIfQueryRead:
    return WhatIfQueryRead(
        scenario=result.scenario,
        projected_outcome=result.projected_outcome,
        assumptions=result.assumptions,
        confidence=result.confidence,
        no_precedent=result.no_precedent,
        comparable_lessons=result.comparable_lessons,
    )
