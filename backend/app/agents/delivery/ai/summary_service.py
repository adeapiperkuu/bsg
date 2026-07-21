"""Optional AI summarization for Delivery Performance operational briefings."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.llm.client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "daily_summary.md"
DEFAULT_TIMEOUT_SECONDS = 8.0

_PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")


def _risk_summary_fields(risk: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": risk.get("title"),
        "risk_tier": risk.get("risk_tier"),
        "detail": risk.get("detail"),
        "status": risk.get("status"),
        "created_at": risk.get("created_at"),
    }


def _bottleneck_summary_fields(bottleneck: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": bottleneck.get("title"),
        "status": bottleneck.get("status"),
        "severity": bottleneck.get("severity"),
        "detail": bottleneck.get("detail"),
        "created_at": bottleneck.get("created_at"),
    }


def _summary_context(dashboard_data: dict[str, Any]) -> dict[str, Any]:
    """Select structured dashboard facts for the LLM without recalculating metrics."""
    risks = dashboard_data.get("risks") or []
    bottlenecks = dashboard_data.get("bottlenecks") or []
    context: dict[str, Any] = {
        "overview": dashboard_data.get("overview"),
        "milestones": dashboard_data.get("milestones"),
        "confidence": dashboard_data.get("confidence"),
        "risks": [_risk_summary_fields(risk) for risk in risks if isinstance(risk, dict)],
        "bottlenecks": [
            _bottleneck_summary_fields(bottleneck)
            for bottleneck in bottlenecks
            if isinstance(bottleneck, dict)
        ],
        "traffic_light": dashboard_data.get("traffic_light"),
        "structured_summary": dashboard_data.get("structured_summary"),
    }
    # Phase 15.4: ground narratives in deterministic causes / briefing sections only.
    root_cause_summary = dashboard_data.get("root_cause_summary")
    if root_cause_summary is not None:
        context["root_cause_summary"] = root_cause_summary
    operational_briefing = dashboard_data.get("operational_briefing")
    if operational_briefing is not None:
        context["operational_briefing"] = operational_briefing
    pm_actions = dashboard_data.get("pm_actions")
    if pm_actions is not None:
        context["pm_actions"] = [
            {
                "rank": item.get("rank"),
                "title": item.get("title"),
                "urgency": item.get("urgency"),
                "estimated_impact_points": item.get("estimated_impact_points"),
                "due_date": item.get("due_date"),
                "deterministic_rationale": item.get("deterministic_rationale"),
                "root_cause_factor": item.get("root_cause_factor"),
            }
            for item in pm_actions
            if isinstance(item, dict)
        ][:5]
    knowledge_evidence = dashboard_data.get("knowledge_evidence")
    if knowledge_evidence is not None:
        context["knowledge_evidence"] = [
            {
                "title": item.get("title"),
                "source_type": item.get("source_type"),
                "section_title": item.get("section_title"),
                "excerpt": item.get("excerpt"),
                "relevance_score": item.get("relevance_score"),
            }
            for item in knowledge_evidence
            if isinstance(item, dict)
        ][:5]
    return context


def build_daily_summary_prompt(dashboard_data: dict[str, Any]) -> str:
    """Build a grounded prompt from already-aggregated dashboard / briefing data."""
    context_json = json.dumps(_summary_context(dashboard_data), default=str, indent=2)
    return _PROMPT_TEMPLATE.replace("{{DASHBOARD_DATA_JSON}}", context_json)


def _llm_configured(settings: Any) -> bool:
    return bool(
        (settings.openai_api_key or settings.llm_api_key)
        and (settings.openai_model or settings.llm_model)
    )


async def generate_daily_summary(
    dashboard_data: dict[str, Any],
    *,
    llm_client: LLMClient | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """Generate an optional AI briefing narrative, returning None when AI is unavailable."""
    settings = get_settings()
    if not _llm_configured(settings):
        return None

    try:
        client = llm_client or LLMClient()
        prompt = build_daily_summary_prompt(dashboard_data)
        response = await asyncio.wait_for(client.generate(prompt), timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("Daily summary generation failed: %s", exc, exc_info=True)
        return None

    summary = (response or "").strip()
    return summary or None
