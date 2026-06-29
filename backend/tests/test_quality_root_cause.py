"""Unit tests for quality root-cause reasoning."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.query_handler import classify_intent
from app.agents.quality_intelligence.root_cause import RootCauseResult, _build_recommendations


def test_classify_intent() -> None:
    assert classify_intent("Why is accuracy dropping?") == "diagnostic"
    assert classify_intent("What should I focus on today?") == "action"
    assert classify_intent("What is the quality status?") == "status"


def test_build_onboarding_recommendations() -> None:
    actions = _build_recommendations("onboarding_gap", "boundary precision", 3, 0.0)
    assert len(actions) >= 1
    assert actions[0]["priority"] == "immediate"
    assert "calibration" in actions[0]["action"].lower()


def test_build_sop_ambiguity_recommendations() -> None:
    actions = _build_recommendations("sop_ambiguity", "guideline_ambiguity", 0, 25.0)
    assert any("SOP" in a["action"] for a in actions)


def test_root_cause_result_blocked() -> None:
    result = RootCauseResult(
        primary_driver=None,
        factors=[],
        confidence="low",
        recommended_actions=[],
        blocked=True,
        block_reason="Insufficient sample size",
    )
    assert result.blocked is True
