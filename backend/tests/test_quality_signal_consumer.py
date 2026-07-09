"""Integration tests for inter-agent signal consumption lifecycle (Phase 1.5-A)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.delivery.services.quality_signal_consumer import consume_quality_risk_signal
from app.agents.quality_intelligence.signals import mark_signal_consumed
from app.agents.workforce.skill_gap_consumer import consume_skill_gap_signal
from app.db.models import (
    AlertStatus,
    AppRole,
    InterAgentSignal,
    NotificationType,
    RiskAlert,
    RiskTier,
    SignalStatus,
    SignalType,
)


@pytest.mark.asyncio
async def test_consume_quality_risk_signal_marks_consumed() -> None:
    alert_id = uuid4()
    signal_id = uuid4()
    org_id = uuid4()

    alert = RiskAlert(
        id=alert_id,
        project_id=uuid4(),
        org_id=org_id,
        alert_type="quality_drift",
        risk_tier=RiskTier.HIGH,
        title="Drift",
        detail="test",
        status=AlertStatus.OPEN,
        contributing_causes={},
    )
    signal = InterAgentSignal(
        id=signal_id,
        signal_type=SignalType.QUALITY_RISK,
        source_agent="quality_intelligence_agent",
        target_agent="delivery_performance_agent",
        payload={
            "alert_id": str(alert_id),
            "rework_volume_units": 12,
            "rework_time_estimate_days": 1.5,
            "severity": "high",
            "hold_recommended": True,
        },
        status=SignalStatus.PENDING,
        org_id=org_id,
    )

    dm_user = type("User", (), {"id": uuid4(), "org_id": org_id, "role": AppRole.DELIVERY_MANAGER})()

    call_count = 0

    async def _fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        class _Scalars:
            def __init__(self, items):
                self._items = items

            def __iter__(self):
                return iter(self._items)

        class _Result:
            def __init__(self, scalar=None, items=None):
                self._scalar = scalar
                self._items = items or []

            def scalar_one_or_none(self):
                return self._scalar

            def scalars(self):
                return _Scalars(self._items)

        if call_count == 1:
            return _Result(scalar=alert)
        if call_count == 2:
            return _Result(items=[])
        if call_count == 3:
            return _Result(items=[dm_user])
        return _Result()

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)
        added: list = []

        def add(self, obj):
            self.added.append(obj)

        flush = AsyncMock()

    session = _FakeSession()
    await consume_quality_risk_signal(session, signal)

    assert signal.status == SignalStatus.CONSUMED
    assert alert.status == AlertStatus.ACKNOWLEDGED
    assert alert.contributing_causes["delivery_signal_consumed"]["rework_volume_units"] == 12
    assert any(getattr(n, "notification_type", None) == NotificationType.RISK_ALERT for n in session.added)


@pytest.mark.asyncio
async def test_consume_skill_gap_signal_marks_consumed() -> None:
    signal_id = uuid4()
    org_id = uuid4()
    signal = InterAgentSignal(
        id=signal_id,
        signal_type=SignalType.SKILL_GAP,
        source_agent="quality_intelligence_agent",
        target_agent="workforce_agent",
        payload={
            "reviewer_ids": [str(uuid4())],
            "urgency": "this_week",
            "error_category": "ERR-02",
            "recommendation": "calibration",
        },
        status=SignalStatus.PENDING,
        org_id=org_id,
    )

    dm_user = type("User", (), {"id": uuid4(), "org_id": org_id, "role": AppRole.DELIVERY_MANAGER})()
    call_count = 0

    async def _fake_execute(stmt):
        nonlocal call_count
        call_count += 1

        class _Scalars:
            def __init__(self, items):
                self._items = items

            def __iter__(self):
                return iter(self._items)

        class _Result:
            def __init__(self, items=None):
                self._items = items or []

            def scalars(self):
                return _Scalars(self._items)

        if call_count == 1:
            return _Result(items=[])
        return _Result(items=[dm_user])

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)
        added: list = []

        def add(self, obj):
            self.added.append(obj)

        flush = AsyncMock()

    session = _FakeSession()
    await consume_skill_gap_signal(session, signal)
    assert signal.status == SignalStatus.CONSUMED
    assert any(getattr(n, "notification_type", None) == NotificationType.SKILL_GAP_DETECTED for n in session.added)


@pytest.mark.asyncio
async def test_mark_signal_consumed_clears_error() -> None:
    signal = InterAgentSignal(
        signal_type=SignalType.QUALITY_RISK,
        source_agent="quality_intelligence_agent",
        target_agent="delivery_performance_agent",
        payload={"_error": "old"},
        status=SignalStatus.PENDING,
    )

    class _FakeSession:
        flush = AsyncMock()

    await mark_signal_consumed(_FakeSession(), signal)
    assert signal.status == SignalStatus.CONSUMED
    assert "_error" not in signal.payload
