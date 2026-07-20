"""Placeholder Operational Knowledge Agent client.

When OKA_BASE_URL is unset, all methods return empty/false gracefully.
When set, attempts HTTP calls; failures degrade to local no-op.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# OKA is a best-effort, non-blocking side call on the agent-query hot path
# (query_handler.py) — a slow or hanging OKA request must never be allowed to
# dominate an already latency-sensitive NL query. 3s is generous for a
# same-network lookup/write while bounding worst case impact when
# OKA_BASE_URL points at a degraded or unreachable service (PHASE 2B
# prod-hardening; inert/no-op in dev where OKA_BASE_URL is unset).
OKA_TIMEOUT_SECONDS = 3.0


class OKAClient:
    async def retrieve_lessons(
        self,
        *,
        org_id: str | None = None,
        task_type: str = "",
        error_category: str = "",
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        if not settings.oka_base_url:
            return []

        query = " ".join(p for p in (task_type, error_category) if p).strip() or "quality"
        try:
            async with httpx.AsyncClient(timeout=OKA_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{settings.oka_base_url.rstrip('/')}/lessons/search",
                    params={"q": query, "org_id": org_id},
                )
            if response.status_code >= 400:
                logger.warning("OKA retrieve_lessons failed status=%s", response.status_code)
                return []
            payload = response.json()
            return payload if isinstance(payload, list) else payload.get("data", [])
        except Exception:
            logger.exception("OKA retrieve_lessons unavailable")
            return []

    async def write_lesson(
        self,
        *,
        event_id: str,
        summary: str,
        source_table: str,
        org_id: str | None = None,
    ) -> dict[str, Any] | None:
        settings = get_settings()
        if not settings.oka_base_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=OKA_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.oka_base_url.rstrip('/')}/lessons",
                    json={
                        "title": f"Quality event {event_id}",
                        "body": summary,
                        "source_table": source_table,
                        "org_id": org_id,
                    },
                )
            if response.status_code >= 400:
                logger.warning("OKA write_lesson failed status=%s", response.status_code)
                return None
            return response.json()
        except Exception:
            logger.exception("OKA write_lesson unavailable")
            return None
