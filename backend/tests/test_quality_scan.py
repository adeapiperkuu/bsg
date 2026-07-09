"""Tests for scan_all_projects() and alert idempotency via source_row_id."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.drift import DriftResult
from app.db.models import AppRole, QualitySnapshot, RiskTier
from app.services.quality import evaluate_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(**kwargs) -> QualitySnapshot:
    defaults = dict(
        project_id=uuid4(),
        team_id=uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        gold_set_accuracy_pct=Decimal("91.0"),
        iaa_krippendorff_alpha=Decimal("0.88"),
        rework_rate_pct=Decimal("3.5"),
        evaluated_item_count=40,
        has_drift_alert=False,
        drift_alert_detail=None,
        root_cause=None,
        confidence_level=None,
    )
    defaults.update(kwargs)
    snap = QualitySnapshot(**defaults)
    snap.id = uuid4()
    return snap


# ---------------------------------------------------------------------------
# Alert idempotency: source_row_id dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_dedup_by_source_row_id() -> None:
    """create_drift_risk_alert must return the existing alert on re-run."""
    from app.agents.quality_intelligence.alerts import create_drift_risk_alert

    snap = _make_snapshot()
    drift = DriftResult(has_drift=True, severity=RiskTier.HIGH, detail="WoW drop exceeded threshold")

    existing_alert_id = uuid4()

    class _MockAlert:
        id = existing_alert_id

    async def _fake_execute(stmt):
        class _Result:
            def scalar_one_or_none(self):
                return _MockAlert()
        return _Result()

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)
        add = lambda self, *a: None
        flush = AsyncMock()

    session = _FakeSession()
    result = await create_drift_risk_alert(session, snap, drift)
    assert result is not None
    assert result.id == existing_alert_id
    # session.add should NOT have been called (existing alert returned early)
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_new_alert_sets_source_fields() -> None:
    """create_drift_risk_alert sets source_table and source_row_id on a new alert."""
    from app.agents.quality_intelligence.alerts import create_drift_risk_alert
    from app.db.models import InterAgentSignal, RiskAlert

    snap = _make_snapshot()
    drift = DriftResult(has_drift=True, severity=RiskTier.MEDIUM, detail="3-week declining trend")

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

    session = _FakeSession()
    with patch(
        "app.agents.quality_intelligence.alerts.compute_rework_impact",
        AsyncMock(return_value={"rework_volume_units": 0, "rework_time_estimate_days": 0.0, "affected_batch_ids": []}),
    ):
        await create_drift_risk_alert(session, snap, drift)

    alerts = [a for a in added if isinstance(a, RiskAlert)]
    assert len(alerts) == 1
    alert: RiskAlert = alerts[0]
    assert alert.source_table == "quality_snapshots"
    assert alert.source_row_id == snap.id


# ---------------------------------------------------------------------------
# scan_all_projects: smoke / idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_all_projects_empty_db() -> None:
    """scan_all_projects returns a completed run with zero counts when no active projects."""
    from app.db.models import QualityScanRun, ScanStatus
    from app.services.quality import scan_all_projects

    added: list = []

    async def _fake_execute(stmt):
        class _Result:
            def scalars(self):
                return iter([])

            def all(self):
                return []

        return _Result()

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)

        def add(self, obj):
            added.append(obj)
            if isinstance(obj, QualityScanRun):
                obj.id = uuid4()

        flush = AsyncMock()

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    session = _FakeSession()
    run = await scan_all_projects(session)
    assert run.projects_scanned == 0
    assert run.snapshots_evaluated == 0
    assert run.alerts_created == 0
    assert run.data_gaps == 0
    assert run.status == ScanStatus.COMPLETED
