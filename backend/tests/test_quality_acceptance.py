"""Phase 1.5-E / 2.0-E acceptance gates: synthetic drift, RBAC, concurrent NL."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.drift import MIN_EVALUATED_ITEMS
from app.agents.quality_intelligence.query_handler import classify_intent
from app.db.models import AppRole, QualitySnapshot, RiskTier
from app.services.quality_scoping import filter_response_for_role
from app.services.quality_thresholds import (
    ThresholdConfig,
    classify_value_severity,
    classify_wow_change,
    max_tier,
)


def _snap(week: int, acc: str, rework: str = "3.0", *, items: int = 40) -> QualitySnapshot:
    return QualitySnapshot(
        project_id=uuid4(),
        team_id=uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=week,
        gold_set_accuracy_pct=Decimal(acc),
        rework_rate_pct=Decimal(rework),
        evaluated_item_count=items,
    )


def _configs() -> dict[str, ThresholdConfig]:
    return {
        "gold_set_accuracy": ThresholdConfig(
            metric_key="gold_set_accuracy",
            direction="higher_is_better",
            green_min=96.0,
            amber_min=94.0,
            red_min=92.0,
            wow_drop_amber=1.0,
            wow_drop_red=2.0,
            wow_drop_critical=4.0,
        ),
        "iaa_krippendorff_alpha": ThresholdConfig(
            metric_key="iaa_krippendorff_alpha",
            direction="higher_is_better",
            green_min=0.90,
            amber_min=0.85,
            red_min=0.80,
            wow_drop_amber=0.03,
            wow_drop_red=0.05,
            wow_drop_critical=0.08,
        ),
        "rework_rate": ThresholdConfig(
            metric_key="rework_rate",
            direction="lower_is_better",
            green_max=3.0,
            amber_max=4.0,
            red_max=6.0,
            wow_rise_amber=1.0,
            wow_rise_red=2.0,
            wow_rise_critical=4.0,
        ),
    }


def _synthetic_drift_detect(current: QualitySnapshot, prior: QualitySnapshot | None) -> bool:
    """Mirror evaluate_drift tier logic without DB (for §16.4 synthetic gate)."""
    if current.evaluated_item_count is not None and current.evaluated_item_count < MIN_EVALUATED_ITEMS:
        return False
    cfg = _configs()
    tiers: list[RiskTier] = []
    acc_cfg = cfg["gold_set_accuracy"]
    tiers.append(classify_value_severity(acc_cfg, current.gold_set_accuracy_pct))
    if prior and current.gold_set_accuracy_pct is not None and prior.gold_set_accuracy_pct is not None:
        tiers.append(classify_wow_change(acc_cfg, current.gold_set_accuracy_pct, prior.gold_set_accuracy_pct))
    rework_cfg = cfg["rework_rate"]
    tiers.append(classify_value_severity(rework_cfg, current.rework_rate_pct))
    if prior and current.rework_rate_pct is not None and prior.rework_rate_pct is not None:
        tiers.append(classify_wow_change(rework_cfg, current.rework_rate_pct, prior.rework_rate_pct))
    severity = max_tier(*tiers) if tiers else RiskTier.LOW
    return severity in {RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.CRITICAL}


SYNTHETIC_DRIFT_SCENARIOS = [
    ("wow_critical_drop", _snap(25, "91.0"), _snap(24, "96.0"), True),
    ("floor_breach", _snap(25, "90.5"), _snap(24, "91.0"), True),
    ("stable", _snap(25, "96.5"), _snap(24, "96.0"), False),
    ("small_improvement", _snap(25, "96.2"), _snap(24, "96.0"), False),
    ("wow_medium_drop", _snap(25, "94.5"), _snap(24, "96.0"), True),
    ("rework_spike", _snap(25, "95.0", "8.0"), _snap(24, "95.0", "3.0"), True),
    ("no_prior_floor", _snap(25, "91.0"), None, True),
    ("sample_too_small", _snap(25, "90.0", items=5), _snap(24, "96.0"), False),
    ("borderline_ok", _snap(25, "96.1"), _snap(24, "96.0"), False),
    ("borderline_drift", _snap(25, "94.0"), _snap(24, "96.0"), True),
]


@pytest.mark.parametrize("name,current,prior,expect_drift", SYNTHETIC_DRIFT_SCENARIOS)
def test_synthetic_drift_detection_gate(name: str, current: QualitySnapshot, prior: QualitySnapshot | None, expect_drift: bool) -> None:
    assert _synthetic_drift_detect(current, prior) == expect_drift, f"Scenario {name} failed"


def test_synthetic_drift_suite_meets_90_percent_gate() -> None:
    correct = sum(
        1
        for _name, current, prior, expect_drift in SYNTHETIC_DRIFT_SCENARIOS
        if _synthetic_drift_detect(current, prior) == expect_drift
    )
    rate = correct / len(SYNTHETIC_DRIFT_SCENARIOS)
    assert rate >= 0.9, f"Synthetic drift detection rate {rate:.0%} below 90% gate"


RBAC_CASES = [
    (AppRole.CLIENT, "Reviewer ID: abc-123 caused errors", True),
    (AppRole.CLIENT, "SOP version 4.2 ambiguous", False),
    (AppRole.DELIVERY_MANAGER, "Reviewer ID: abc-123 caused errors", False),
    (AppRole.BSG_LEADERSHIP, "Reviewer ID: abc-123 caused errors", False),
    (AppRole.SUPER_ADMIN, "Reviewer ID: abc-123 caused errors", False),
]


@pytest.mark.parametrize("role,text,should_strip", RBAC_CASES)
def test_rbac_persona_matrix(role: AppRole, text: str, should_strip: bool) -> None:
    filtered = filter_response_for_role(text, role)
    if should_strip:
        assert "abc-123" not in filtered
    else:
        assert filtered == text


def test_intent_classification_coverage() -> None:
    cases = {
        "why did accuracy drop": "diagnostic",
        "what should we focus on": "action",
        "what is the rework rate": "status",
        "how many units need rework": "impact",
        "how was W20 resolved": "historical",
        "what if we add reviewers": "what_if",
    }
    for query, expected in cases.items():
        assert classify_intent(query) == expected


@pytest.mark.asyncio
async def test_concurrent_nl_sessions_do_not_degrade() -> None:
    """Lightweight 20-session concurrency gate (no LLM — diagnostic path only)."""
    from app.agents.quality_intelligence.query_handler import answer_quality_query
    from app.schemas.domain import AgentQueryCreate
    from app.services.evidence import EvidenceInput

    project_id = uuid4()
    user = SimpleNamespace(id=uuid4(), org_id=uuid4(), role=AppRole.DELIVERY_MANAGER)
    payload = AgentQueryCreate(
        agent_name="quality_intelligence_agent",
        project_id=project_id,
        query_text="Why did accuracy drop this week?",
    )
    project = SimpleNamespace(id=project_id, org_id=user.org_id, name="P")

    async def _fake_gather(*_a, **_k):
        snap_id = uuid4()
        return [
            EvidenceInput(
                source_table="quality_snapshots",
                source_row_id=snap_id,
                description="snap",
            )
        ], "{}"

    with (
        patch("app.agents.quality_intelligence.query_handler.get_visible_project", AsyncMock(return_value=project)),
        patch("app.agents.quality_intelligence.query_handler.gather_quality_evidence", AsyncMock(side_effect=_fake_gather)),
        patch("app.agents.quality_intelligence.query_handler.classify_intent_llm", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.query_handler.OKAClient") as mock_oka_cls,
        patch(
            "app.agents.quality_intelligence.query_handler.analyze_root_cause",
            AsyncMock(
                return_value=SimpleNamespace(
                    primary_driver="onboarding_gap", confidence="medium", factors=[], blocked=False
                )
            ),
        ),
        patch("app.agents.quality_intelligence.query_handler.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm_api_key = None
        mock_settings.return_value.llm_model = "test-model"
        mock_oka_cls.return_value.retrieve_lessons = AsyncMock(return_value=[])

        async def _one():
            session = AsyncMock()
            session.add = lambda *a: None
            session.flush = AsyncMock()
            session.execute = AsyncMock(
                return_value=type("R", (), {"scalar_one_or_none": lambda self: None})()
            )
            return await answer_quality_query(session, user, payload)

        results = await asyncio.gather(*[_one() for _ in range(20)])
    assert len(results) == 20
    assert all(r.answer_text for r in results)
