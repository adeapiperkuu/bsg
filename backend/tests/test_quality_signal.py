"""Tests for quality_risk signal payload on drift alerts."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.alerts import create_drift_risk_alert
from app.agents.quality_intelligence.drift import DriftResult
from app.db.models import InterAgentSignal, QualitySnapshot, RiskAlert, RiskTier


def _make_snapshot(**kwargs) -> QualitySnapshot:
    defaults = dict(
        project_id=uuid4(),
        team_id=uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        gold_set_accuracy_pct=Decimal("91.0"),
        rework_rate_pct=Decimal("5.5"),
        evaluated_item_count=40,
    )
    defaults.update(kwargs)
    snap = QualitySnapshot(**defaults)
    snap.id = uuid4()
    return snap


@pytest.mark.asyncio
async def test_quality_risk_payload_on_new_alert() -> None:
    snap = _make_snapshot()
    drift = DriftResult(has_drift=True, severity=RiskTier.HIGH, detail="WoW drop exceeded threshold")
    added: list[RiskAlert] = []

    async def _fake_execute(stmt):
        class _Result:
            def scalar_one_or_none(self):
                return None
        return _Result()

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)

        def add(self, obj):
            added.append(obj)

        flush = AsyncMock()

    with patch(
        "app.agents.quality_intelligence.alerts.compute_rework_impact",
        AsyncMock(return_value={"rework_volume_units": 0, "rework_time_estimate_days": 0.0, "affected_batch_ids": []}),
    ):
        await create_drift_risk_alert(_FakeSession(), snap, drift)

    alerts = [a for a in added if isinstance(a, RiskAlert)]
    signals = [s for s in added if isinstance(s, InterAgentSignal)]
    assert len(alerts) == 1
    assert len(signals) == 1
    payload = alerts[0].contributing_causes.get("quality_risk_payload")
    assert payload is not None
    assert payload["signal_type"] == "quality_risk"
    assert payload["severity"] == "high"
    assert payload["rework_rate_pct"] == "5.5"
    assert payload["hold_recommended"] is True
    assert payload["affected_team_id"] == str(snap.team_id)
    assert payload["iso_week"] == 25
    assert payload["iso_year"] == 2026
    assert "rework_volume_units" in payload
    assert "rework_time_estimate_days" in payload
    assert "affected_batch_ids" in payload


@pytest.mark.asyncio
async def test_quality_risk_payload_includes_rework_metrics() -> None:
    snap = _make_snapshot()
    drift = DriftResult(has_drift=True, severity=RiskTier.HIGH, detail="WoW drop")
    added: list = []

    async def _fake_execute(stmt):
        class _Result:
            def scalar_one_or_none(self):
                return None
        return _Result()

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)

        def add(self, obj):
            added.append(obj)

        flush = AsyncMock()

    with patch(
        "app.agents.quality_intelligence.alerts.compute_rework_impact",
        AsyncMock(
            return_value={
                "rework_volume_units": 18,
                "rework_time_estimate_days": 2.3,
                "affected_batch_ids": ["item-1", "item-2"],
            }
        ),
    ):
        await create_drift_risk_alert(_FakeSession(), snap, drift)

    alerts = [a for a in added if isinstance(a, RiskAlert)]
    payload = alerts[0].contributing_causes["quality_risk_payload"]
    assert payload["rework_volume_units"] == 18
    assert payload["rework_time_estimate_days"] == 2.3
    assert payload["affected_batch_ids"] == ["item-1", "item-2"]


@pytest.mark.asyncio
async def test_quality_risk_hold_not_recommended_for_medium() -> None:
    snap = _make_snapshot()
    drift = DriftResult(has_drift=True, severity=RiskTier.MEDIUM, detail="Minor drift")
    added: list[RiskAlert] = []

    async def _fake_execute(stmt):
        class _Result:
            def scalar_one_or_none(self):
                return None
        return _Result()

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)

        def add(self, obj):
            added.append(obj)

        flush = AsyncMock()

    with patch(
        "app.agents.quality_intelligence.alerts.compute_rework_impact",
        AsyncMock(return_value={"rework_volume_units": 0, "rework_time_estimate_days": 0.0, "affected_batch_ids": []}),
    ):
        await create_drift_risk_alert(_FakeSession(), snap, drift)

    alerts = [a for a in added if isinstance(a, RiskAlert)]
    payload = alerts[0].contributing_causes["quality_risk_payload"]
    assert payload["hold_recommended"] is False
