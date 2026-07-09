from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_email(*, to: str, subject: str, html_body: str) -> bool:
    """Send email via Resend. No-op when EMAIL_API_KEY is not configured."""
    settings = get_settings()
    if not settings.email_api_key:
        logger.debug("Email skipped (no EMAIL_API_KEY): to=%s subject=%s", to, subject)
        return False

    from_address = settings.email_from_address or "noreply@operations-tower.local"
    payload = {
        "from": from_address,
        "to": [to],
        "subject": subject,
        "html": html_body,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.email_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False
