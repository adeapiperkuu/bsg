"""Unit tests for quality drift detection logic."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.drift import (
    detect_three_week_declining_trend,
    prior_iso_week,
)
from app.db.models import QualitySnapshot, RiskTier
from app.services.quality_thresholds import (
    ThresholdConfig,
    classify_value_severity,
    classify_wow_change,
    max_tier,
)


def test_prior_iso_week() -> None:
    assert prior_iso_week(2026, 5) == (2026, 4)
    assert prior_iso_week(2026, 1) == (2025, 52)


def test_three_week_declining_trend() -> None:
    team_id = uuid4()
    project_id = uuid4()
    org_id = uuid4()

    def snap(week: int, acc: str) -> QualitySnapshot:
        return QualitySnapshot(
            project_id=project_id,
            team_id=team_id,
            org_id=org_id,
            iso_year=2026,
            iso_week=week,
            gold_set_accuracy_pct=Decimal(acc),
        )

    assert detect_three_week_declining_trend([snap(3, "92"), snap(2, "94"), snap(1, "96")]) is True
    assert detect_three_week_declining_trend([snap(3, "96"), snap(2, "94"), snap(1, "92")]) is False


def test_classify_accuracy_severity() -> None:
    cfg = ThresholdConfig(
        metric_key="gold_set_accuracy",
        direction="higher_is_better",
        green_min=96.0,
        amber_min=94.0,
        red_min=92.0,
    )
    assert classify_value_severity(cfg, Decimal("97")) == RiskTier.LOW
    assert classify_value_severity(cfg, Decimal("94.5")) == RiskTier.MEDIUM
    assert classify_value_severity(cfg, Decimal("93")) == RiskTier.HIGH
    assert classify_value_severity(cfg, Decimal("91")) == RiskTier.CRITICAL


def test_classify_wow_drop() -> None:
    cfg = ThresholdConfig(
        metric_key="gold_set_accuracy",
        direction="higher_is_better",
        wow_drop_amber=1.0,
        wow_drop_red=2.0,
        wow_drop_critical=4.0,
    )
    assert classify_wow_change(cfg, Decimal("95"), Decimal("96")) == RiskTier.MEDIUM
    assert classify_wow_change(cfg, Decimal("93"), Decimal("96")) == RiskTier.HIGH


def test_max_tier() -> None:
    assert max_tier(RiskTier.LOW, RiskTier.HIGH) == RiskTier.HIGH
