"""OKA client placeholder tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.quality_intelligence.oka_client import OKA_TIMEOUT_SECONDS, OKAClient


@pytest.mark.asyncio
async def test_retrieve_lessons_empty_without_base_url() -> None:
    with patch("app.agents.quality_intelligence.oka_client.get_settings") as mock_settings:
        mock_settings.return_value.oka_base_url = None
        lessons = await OKAClient().retrieve_lessons(task_type="calibration", error_category="ERR-01")
    assert lessons == []


@pytest.mark.asyncio
async def test_write_lesson_false_without_base_url() -> None:
    with patch("app.agents.quality_intelligence.oka_client.get_settings") as mock_settings:
        mock_settings.return_value.oka_base_url = None
        result = await OKAClient().write_lesson(event_id="x", summary="test", source_table="risk_alerts")
    assert result is None


# --- PHASE 2B: OKA prod-hardening (capped timeout, non-blocking failure) --------


def test_oka_timeout_capped_at_three_seconds() -> None:
    """The httpx timeout for OKA calls must be capped low (was 30s) since OKA
    is a best-effort side call on the agent-query hot path — a slow/hanging
    OKA request must never dominate an already latency-sensitive NL query."""
    assert OKA_TIMEOUT_SECONDS <= 3.0


@pytest.mark.asyncio
async def test_retrieve_lessons_uses_capped_httpx_timeout() -> None:
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = []

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch("app.agents.quality_intelligence.oka_client.get_settings") as mock_settings,
        patch("app.agents.quality_intelligence.oka_client.httpx.AsyncClient", return_value=fake_client) as mock_ctor,
    ):
        mock_settings.return_value.oka_base_url = "https://oka.example.com"
        await OKAClient().retrieve_lessons(org_id="org-1", error_category="quality")

    assert mock_ctor.call_args.kwargs["timeout"] == OKA_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_retrieve_lessons_failure_is_non_blocking() -> None:
    """An OKA outage/timeout must degrade to an empty list, never raise —
    the caller (query_handler.py) treats [] as OKA_UNAVAILABLE, not an error."""
    with (
        patch("app.agents.quality_intelligence.oka_client.get_settings") as mock_settings,
        patch(
            "app.agents.quality_intelligence.oka_client.httpx.AsyncClient",
            side_effect=TimeoutError("OKA unreachable"),
        ),
    ):
        mock_settings.return_value.oka_base_url = "https://oka.example.com"
        lessons = await OKAClient().retrieve_lessons(org_id="org-1", error_category="quality")

    assert lessons == []
