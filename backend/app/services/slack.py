from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_slack_message(*, text: str) -> bool:
    """Post a message to the configured Slack incoming webhook. No-op when unset."""
    settings = get_settings()
    webhook = settings.slack_webhook_url
    if not webhook:
        logger.debug("Slack skipped (no SLACK_WEBHOOK_URL)")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(webhook, json={"text": text})
            response.raise_for_status()
            return True
    except Exception:
        logger.exception("Failed to send Slack notification")
        return False
