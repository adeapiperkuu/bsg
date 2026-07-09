"""UC-05 what-if analysis tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.query_handler import classify_intent
from app.agents.quality_intelligence.what_if import WhatIfEngine, analyze_what_if


def test_classify_what_if_intent() -> None:
    assert classify_intent("What if we schedule calibration?") == "what_if"


def test_parse_scenario_calibration() -> None:
    assert WhatIfEngine.parse_scenario("What if we run calibration?") == "schedule_calibration"


@pytest.mark.asyncio
async def test_analyze_what_if_no_precedent() -> None:
    project = SimpleNamespace(id=uuid4(), org_id=uuid4(), name="Pilot")
    with (
        patch(
            "app.agents.quality_intelligence.what_if.OKAClient.retrieve_lessons",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.quality_intelligence.what_if.keyword_search",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.quality_intelligence.what_if.get_settings",
            return_value=SimpleNamespace(llm_api_key=None),
        ),
    ):
        mock_session = AsyncMock()

        class _Result:
            def scalars(self):
                return iter([])

        mock_session.execute = AsyncMock(return_value=_Result())
        result = await analyze_what_if(mock_session, project, "What if we do calibration?")

    assert result.no_precedent is True
    assert result.scenario == "schedule_calibration"
