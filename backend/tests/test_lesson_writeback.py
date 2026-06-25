"""Lesson write-back on alert resolve."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.db.models import AlertStatus, AlertType


@pytest.mark.asyncio
async def test_resolve_writes_lesson() -> None:
    from app.services.quality import resolve_risk_alert

    alert = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        title="Drift",
        detail="Accuracy drop",
        alert_type=AlertType.QUALITY_DRIFT,
        status=AlertStatus.OPEN,
        resolved_at=None,
        resolved_by=None,
    )
    session = AsyncMock()
    session.flush = AsyncMock()

    with (
        patch("app.services.quality.write_quality_lesson", AsyncMock()) as mock_lesson,
        patch("app.services.quality.write_lesson_on_alert_resolve", AsyncMock()),
    ):
        resolved = await resolve_risk_alert(
            session, alert, resolved_by=uuid4(), resolution_summary="Fixed via calibration"
        )

    assert resolved.status == AlertStatus.RESOLVED
    mock_lesson.assert_called_once()
