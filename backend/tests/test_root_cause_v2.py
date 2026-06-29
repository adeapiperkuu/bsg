"""Root-cause engine v2 hypothesis tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.root_cause import analyze_root_cause


def _snapshot(**kwargs):
    defaults = dict(
        id=uuid4(),
        project_id=uuid4(),
        team_id=uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        evaluated_item_count=40,
        gold_set_accuracy_pct=Decimal("91.0"),
        iaa_krippendorff_alpha=Decimal("0.88"),
        rework_rate_pct=Decimal("4.0"),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_onboarding_from_scorecards_when_present() -> None:
    snap = _snapshot()
    scorecard = SimpleNamespace(
        id=uuid4(),
        annotator_id=uuid4(),
        accuracy_pct=Decimal("78.0"),
        items_evaluated=55,
    )

    async def _passthrough(_s, query, default):
        return await query()

    with (
        patch("app.agents.quality_intelligence.root_cause.fetch_error_entries", AsyncMock(return_value=[])),
        patch("app.agents.quality_intelligence.root_cause.fetch_prior_snapshot", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.root_cause.query_optional_table", side_effect=_passthrough),
        patch(
            "app.agents.quality_intelligence.root_cause._hypothesis_onboarding_scorecards",
            AsyncMock(
                return_value={
                    "factor": "onboarding_gap",
                    "contribution_pct": 70.0,
                    "evidence": ["reviewer_scorecards:test"],
                }
            ),
        ),
        patch("app.agents.quality_intelligence.root_cause._hypothesis_sop_change", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.root_cause._hypothesis_gold_set_version", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.root_cause._hypothesis_workload_fatigue", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.root_cause._hypothesis_systemic_iaa", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.root_cause._hypothesis_eval_log_reviewers", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.root_cause.count_recent_annotators", AsyncMock(return_value=0)),
    ):
        result = await analyze_root_cause(AsyncMock(), snap)

    assert result.primary_driver == "onboarding_gap"
    assert result.factors[0]["evidence"] == ["reviewer_scorecards:test"]


@pytest.mark.asyncio
async def test_blocked_when_sample_too_small() -> None:
    snap = _snapshot(evaluated_item_count=10)
    result = await analyze_root_cause(AsyncMock(), snap)
    assert result.blocked is True
    assert result.primary_driver is None
