"""UC-04 SOP ambiguity tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.sop_ambiguity import (
    confirm_sop_ambiguity_resolution,
    detect_distributed_iaa_drop,
)
from app.agents.quality_intelligence.sop_workflow import SopAmbiguityFlag
from app.db.models import AlertStatus, QualitySopLink, RiskAlert, RiskTier


@pytest.mark.asyncio
async def test_detect_distributed_iaa_drop_true() -> None:
    snap = SimpleNamespace(project_id=uuid4(), org_id=uuid4(), iso_year=2026, iso_week=25)
    with patch(
        "app.agents.quality_intelligence.sop_ambiguity.detect_sop_ambiguity",
        AsyncMock(
            return_value=SopAmbiguityFlag(detected=True, affected_reviewers=4, detail="IAA drop")
        ),
    ):
        assert await detect_distributed_iaa_drop(AsyncMock(), snap) is True


@pytest.mark.asyncio
async def test_detect_distributed_iaa_drop_false() -> None:
    snap = SimpleNamespace(project_id=uuid4(), org_id=uuid4(), iso_year=2026, iso_week=25)
    with patch(
        "app.agents.quality_intelligence.sop_ambiguity.detect_sop_ambiguity",
        AsyncMock(return_value=SopAmbiguityFlag(detected=False)),
    ):
        assert await detect_distributed_iaa_drop(AsyncMock(), snap) is False


@pytest.mark.asyncio
async def test_confirm_sop_ambiguity_resolution_creates_link_and_resolves_alert() -> None:
    project = SimpleNamespace(id=uuid4(), org_id=uuid4())
    alert_id = uuid4()
    sop_version_id = uuid4()
    confirmed_by = uuid4()

    alert = RiskAlert(
        id=alert_id,
        project_id=project.id,
        org_id=project.org_id,
        alert_type="quality_drift",
        risk_tier=RiskTier.MEDIUM,
        title="SOP ambiguity",
        detail="test",
        status=AlertStatus.OPEN,
    )
    sop_version = SimpleNamespace(id=sop_version_id, org_id=project.org_id)
    call_count = 0

    async def _fake_execute(stmt):
        nonlocal call_count
        call_count += 1

        class _Result:
            def __init__(self, scalar=None):
                self._scalar = scalar

            def scalar_one_or_none(self):
                return self._scalar

        if call_count == 1:
            return _Result(alert)
        if call_count == 2:
            return _Result(sop_version)
        return _Result(None)

    class _FakeSession:
        execute = AsyncMock(side_effect=_fake_execute)
        added: list = []

        def add(self, obj):
            self.added.append(obj)

        flush = AsyncMock()

    session = _FakeSession()
    link = await confirm_sop_ambiguity_resolution(
        session,
        project,
        alert_id=alert_id,
        sop_version_id=sop_version_id,
        confirmed_by=confirmed_by,
    )

    assert isinstance(link, QualitySopLink)
    assert alert.status == AlertStatus.RESOLVED
    assert alert.resolved_at is not None
    assert isinstance(alert.resolved_at, datetime)
    assert any(isinstance(o, QualitySopLink) for o in session.added)
