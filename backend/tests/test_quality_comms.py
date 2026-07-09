"""Tests for LLM-generated communication draft bodies."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.db.models import CommunicationType
from app.services.communications import COMMS_PLACEHOLDER_BODY, build_comms_context, generate_comms_draft_body


def _project() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name="Pilot Project")


def _throughput() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        snapshot_date=date(2026, 6, 20),
        units_completed=120,
        units_forecast=130,
        rolling_7day_units=840,
    )


def _quality_snap() -> SimpleNamespace:
    return SimpleNamespace(
        iso_year=2026,
        iso_week=25,
        gold_set_accuracy_pct=Decimal("95.5"),
        iaa_krippendorff_alpha=Decimal("0.91"),
        rework_rate_pct=Decimal("3.2"),
        has_drift_alert=False,
    )


@pytest.mark.asyncio
async def test_generate_comms_draft_body_fallback_without_api_key() -> None:
    with patch("app.services.communications.get_settings") as mock_settings:
        mock_settings.return_value.llm_api_key = None
        body = await generate_comms_draft_body(
            _project(),
            _throughput(),
            CommunicationType.WEEKLY_SUMMARY,
            quality_snaps=[_quality_snap()],
            drift_alerts=[],
        )
    assert body == COMMS_PLACEHOLDER_BODY


@pytest.mark.asyncio
async def test_generate_comms_draft_body_calls_llm() -> None:
    with (
        patch("app.services.communications.get_settings") as mock_settings,
        patch("app.services.communications.LLMClient") as mock_llm_cls,
    ):
        mock_settings.return_value.llm_api_key = "test-key"
        mock_llm = AsyncMock()
        mock_llm.generate_structured.return_value = "Weekly update: quality is on track."
        mock_llm_cls.return_value = mock_llm

        body = await generate_comms_draft_body(
            _project(), _throughput(), quality_summary=None, drift_alerts=[], comm_type=CommunicationType.WEEKLY_SUMMARY
        )

    assert body == "Weekly update: quality is on track."
    mock_llm.generate_structured.assert_called_once()


def test_build_comms_context_uses_sanitized_quality_summary() -> None:
    """BR-03: weekly comms context must use §8.4 summary, not raw reviewer/SOP identifiers."""
    from app.schemas.domain import QualitySummaryRead

    summary = QualitySummaryRead(
        period="W25",
        project_id=uuid4(),
        overall_status="on_track",
        gold_set_accuracy_blended="95.5",
        rework_rate="3.2",
        rework_rate_target="4.0",
        iaa_score="0.91",
        drift_events_this_period=[],
        client_narrative="Quality posture for week 25 is on track.",
        confidence="high",
    )
    ctx = build_comms_context(_throughput(), quality_summary=summary)
    assert "quality_summary" in ctx
    assert "reviewer" not in ctx.lower()
    assert "sop" not in ctx.lower()
    assert "95.5" in ctx


def test_build_comms_context_legacy_quality_snaps_still_supported() -> None:
    alert = SimpleNamespace(title="Drift", detail="Accuracy drop", risk_tier=SimpleNamespace(value="high"))

    ctx = build_comms_context(_throughput(), quality_snaps=[_quality_snap()], drift_alerts=[alert])
    assert "throughput" in ctx
    assert "quality_snapshot" in ctx
    assert "drift_alert" in ctx
