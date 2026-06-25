"""UC-03 calibration tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.calibration import identify_calibration_candidates


@pytest.mark.asyncio
async def test_identify_candidates_below_threshold() -> None:
    project_id = uuid4()
    card = SimpleNamespace(
        annotator_id=uuid4(),
        accuracy_pct=Decimal("80.0"),
        items_evaluated=60,
        error_breakdown={"ERR-01": 40},
    )

    async def _fake_execute(_stmt):
        class _R:
            def scalars(self):
                return self

            def __iter__(self):
                return iter([card])

        return _R()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_fake_execute)

    with patch(
        "app.agents.quality_intelligence.calibration.load_thresholds",
        AsyncMock(return_value={"gold_set_accuracy": SimpleNamespace(amber_min=85.0)}),
    ):
        candidates = await identify_calibration_candidates(
            session, project_id, iso_year=2026, iso_week=25
        )

    assert len(candidates) == 1
    assert candidates[0].items_evaluated >= 50


@pytest.mark.asyncio
async def test_no_candidates_when_above_threshold() -> None:
    project_id = uuid4()
    card = SimpleNamespace(
        annotator_id=uuid4(),
        accuracy_pct=Decimal("96.0"),
        items_evaluated=60,
        error_breakdown=None,
    )

    async def _fake_execute(_stmt):
        class _R:
            def scalars(self):
                return self

            def __iter__(self):
                return iter([card])

        return _R()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_fake_execute)

    with patch(
        "app.agents.quality_intelligence.calibration.load_thresholds",
        AsyncMock(return_value={"gold_set_accuracy": SimpleNamespace(amber_min=85.0)}),
    ):
        candidates = await identify_calibration_candidates(
            session, project_id, iso_year=2026, iso_week=25
        )

    assert candidates == []
