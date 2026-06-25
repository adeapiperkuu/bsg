from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.retrieval import keyword_search


@dataclass(frozen=True)
class WhatIfResult:
    scenario: str
    projected_outcome: str
    assumptions: list[str]
    comparable_lessons: list[dict[str, Any]]
    confidence: str


async def analyze_what_if(
    session: AsyncSession,
    org_id,
    query_text: str,
) -> WhatIfResult:
    """UC-05: rule-based what-if with historical lesson retrieval."""
    lower = query_text.lower()
    assumptions = ["Projection based on historical patterns in knowledge base"]

    if "calibration" in lower:
        scenario = "schedule_calibration"
        projected = "Gold-set accuracy recovery expected within 1–2 weeks based on similar past events"
        confidence = "medium"
    elif "sop" in lower or "guideline" in lower:
        scenario = "sop_clarification"
        projected = "Guideline ambiguity errors may reduce 20–40% within 2 weeks after SOP update"
        confidence = "medium"
    elif "rework" in lower:
        scenario = "reduce_rework"
        projected = "Targeted error-category review may reduce rework rate by 15–25%"
        confidence = "low"
    else:
        scenario = "general_intervention"
        projected = "Outcome depends on root cause; manual QA review recommended before action"
        confidence = "low"
        assumptions.append("No strong precedent match for this scenario variable")

    lessons = await keyword_search(session, org_id, query_text, limit=3)
    if not lessons:
        assumptions.append("No comparable historical lessons found — projection is speculative")

    return WhatIfResult(
        scenario=scenario,
        projected_outcome=projected,
        assumptions=assumptions,
        comparable_lessons=lessons,
        confidence=confidence,
    )
