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

    projected, assumptions, confidence = WhatIfEngine.rule_projection(scenario, snapshots)

    oka = OKAClient()
    lessons = await oka.retrieve_lessons(org_id=str(project.org_id), task_type=scenario, error_category="")
    if not lessons:
        lessons = await keyword_search(session, project.org_id, query_text, limit=3)

    no_precedent = len(lessons) == 0
    if no_precedent:
        assumptions.append("No comparable OKA lessons found — projection is speculative")

    settings = get_settings()
    if settings.llm_api_key:
        try:
            llm = LLMClient()
            narrative = await llm.generate_structured(
                system=WHAT_IF_SYSTEM_PROMPT,
                user=f"What-if query: {query_text}",
                context=json.dumps(
                    {
                        "scenario": scenario,
                        "rule_projection": projected,
                        "assumptions": assumptions,
                        "lessons": lessons,
                        "snapshots": len(snapshots),
                    },
                    default=str,
                ),
            )
            projected = narrative
        except Exception:
            pass

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
