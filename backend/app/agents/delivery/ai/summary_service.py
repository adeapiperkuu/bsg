"""Optional AI summarization for Delivery Performance dashboard data."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.llm.client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "daily_summary.md"
DEFAULT_TIMEOUT_SECONDS = 5.0

_PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")


def _load_prompt_template() -> str:
    return _PROMPT_TEMPLATE


def _risk_summary_fields(risk: dict[str, Any]) -> dict[str, Any]:
    """Project a risk down to the fields the summary prompt actually uses."""
    return {
        "title": risk.get("title"),
        "risk_tier": risk.get("risk_tier"),
        "detail": risk.get("detail"),
    }


def _bottleneck_summary_fields(bottleneck: dict[str, Any]) -> dict[str, Any]:
    """Project a bottleneck down to the fields the summary prompt actually uses."""
    return {
        "title": bottleneck.get("title"),
        "status": bottleneck.get("status"),
        "detail": bottleneck.get("detail"),
    }


def _summary_context(dashboard_data: dict[str, Any]) -> dict[str, Any]:
    """Select structured dashboard facts for the LLM without recalculating metrics."""
    risks = dashboard_data.get("risks") or []
    bottlenecks = dashboard_data.get("bottlenecks") or []
    return {
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
    }


def build_daily_summary_prompt(dashboard_data: dict[str, Any]) -> str:
    """Build a grounded prompt from already-aggregated dashboard data."""
    template = _load_prompt_template()
    context_json = json.dumps(_summary_context(dashboard_data), default=str, indent=2)
    return template.replace("{{DASHBOARD_DATA_JSON}}", context_json)


async def generate_daily_summary(
    dashboard_data: dict[str, Any],
    *,
    llm_client: LLMClient | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """Generate an optional AI summary, returning None when AI is unavailable."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_model:
        return None

    try:
        client = llm_client or LLMClient()
        prompt = build_daily_summary_prompt(dashboard_data)
        response = await asyncio.wait_for(client.generate(prompt), timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("Daily summary generation failed: %s", exc, exc_info=True)
        return None

    summary = response.strip()
    return summary or None
