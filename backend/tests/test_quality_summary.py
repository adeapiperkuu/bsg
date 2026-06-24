"""Tests for generate_quality_summary() and the §8.4 JSON shape."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from types import SimpleNamespace

from app.core.security import CurrentUser
from app.db.models import AlertStatus, AlertType, AppRole, RiskTier
from app.schemas.domain import QualitySummaryRead


def _make_project(org_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name="Test Project",
    )


def _make_snapshot(project_id, team_id=None, **kwargs):
    snap = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        team_id=team_id or uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        gold_set_accuracy_pct=Decimal("96.5"),
        iaa_krippendorff_alpha=Decimal("0.91"),
        rework_rate_pct=Decimal("3.2"),
        evaluated_item_count=55,
        has_drift_alert=False,
        confidence_level="high",
    )
    for k, v in kwargs.items():
        setattr(snap, k, v)
    return snap


def _make_user(role=AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email="test@example.com",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_summary_structure() -> None:
    """generate_quality_summary returns the §8.4 JSON shape for DM role."""
    from app.services.quality import generate_quality_summary

    project = _make_project()
    snap = _make_snapshot(project_id=project.id)

    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1

        class _R:
            def scalars(self):
                if call_count == 1:
                    return iter([snap])
                if call_count == 2:
                    return iter([])
                return iter([])

        return _R()

    class _FakeSession:
        execute = AsyncMock(side_effect=_execute)

    user = _make_user(AppRole.DELIVERY_MANAGER)
    summary = await generate_quality_summary(_FakeSession(), project, 2026, 25, user)

    assert isinstance(summary, QualitySummaryRead)
    assert summary.report_type == "quality_summary"
    assert summary.period == "W25"
    assert summary.project_id == project.id
    assert summary.overall_status in {"on_track", "at_risk", "critical"}
    assert summary.confidence in {"high", "medium", "low"}
    assert isinstance(summary.drift_events_this_period, list)


@pytest.mark.asyncio
async def test_client_role_gets_narrative_only() -> None:
    """CLIENT role should not receive raw metric values."""
    from app.services.quality import generate_quality_summary

    project = _make_project()
    snap = _make_snapshot(project_id=project.id)

    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1

        class _R:
            def scalars(self):
                if call_count == 1:
                    return iter([snap])
                return iter([])

        return _R()

    class _FakeSession:
        execute = AsyncMock(side_effect=_execute)

    user = _make_user(AppRole.CLIENT)
    summary = await generate_quality_summary(_FakeSession(), project, 2026, 25, user)

    assert summary.gold_set_accuracy_blended is None
    assert summary.rework_rate is None
    assert summary.iaa_score is None
    assert summary.drift_events_this_period == []
    assert summary.client_narrative is not None


@pytest.mark.asyncio
async def test_summary_overall_status_critical() -> None:
    """overall_status is critical when a CRITICAL drift alert is open."""
    from app.services.quality import generate_quality_summary

    project = _make_project()

    alert = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        risk_tier=RiskTier.CRITICAL,
        status=AlertStatus.OPEN,
        source_row_id=uuid4(),
        title="Quality drift W25",
    )

    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1

        class _R:
            def scalars(self):
                if call_count == 1:
                    return iter([])
                if call_count == 2:
                    return iter([alert])
                return iter([])

        return _R()

    class _FakeSession:
        execute = AsyncMock(side_effect=_execute)

    user = _make_user(AppRole.DELIVERY_MANAGER)
    summary = await generate_quality_summary(_FakeSession(), project, 2026, 25, user)
    assert summary.overall_status == "critical"
