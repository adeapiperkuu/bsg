"""UC-04 SOP ambiguity tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.sop_ambiguity import detect_distributed_iaa_drop
from app.agents.quality_intelligence.sop_workflow import SopAmbiguityFlag


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
