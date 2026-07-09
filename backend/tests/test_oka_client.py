"""OKA client placeholder tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.quality_intelligence.oka_client import OKAClient


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
