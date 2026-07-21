"""Optional AI rationale for PM daily actions — grounded in deterministic evidence only."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.llm.client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "pm_action_rationale.md"
DEFAULT_TIMEOUT_SECONDS = 4.0

_PROMPT_TEMPLATE = (
    PROMPT_PATH.read_text(encoding="utf-8")
    if PROMPT_PATH.exists()
    else (
        "Rewrite the deterministic rationale into one short PM-facing sentence. "
        "Use only facts in the JSON. Do not invent causes, numbers, or actions.\n\n"
        "{{ACTION_JSON}}"
    )
)


def build_action_rationale_prompt(action: dict[str, Any]) -> str:
    payload = {
        "title": action.get("title"),
        "deterministic_rationale": action.get("deterministic_rationale"),
        "estimated_impact_points": action.get("estimated_impact_points"),
        "urgency": action.get("urgency"),
        "due_date": action.get("due_date"),
        "evidence_json": action.get("evidence_json"),
        "root_cause_factor": action.get("root_cause_factor"),
    }
    return _PROMPT_TEMPLATE.replace(
        "{{ACTION_JSON}}", json.dumps(payload, default=str, indent=2)
    )


async def generate_action_rationale(
    action: dict[str, Any],
    *,
    llm_client: LLMClient | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """Return optional AI prose grounded in deterministic action facts, or None."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_model:
        return None
    try:
        client = llm_client or LLMClient()
        prompt = build_action_rationale_prompt(action)
        response = await asyncio.wait_for(client.generate(prompt), timeout=timeout_seconds)
    except Exception as exc:
        logger.warning("PM action AI rationale failed: %s", exc, exc_info=True)
        return None
    text = (response or "").strip()
    return text or None
