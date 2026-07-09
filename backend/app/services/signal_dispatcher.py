"""Dispatch pending inter-agent signals to target agent consumers."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.quality_signal_consumer import consume_pending_quality_risk_signals
from app.agents.workforce.skill_gap_consumer import consume_pending_skill_gap_signals

logger = logging.getLogger(__name__)


async def dispatch_pending_signals(session: AsyncSession) -> dict[str, int]:
    quality_count = await consume_pending_quality_risk_signals(session)
    workforce_count = await consume_pending_skill_gap_signals(session)
    totals = {"quality_risk": quality_count, "skill_gap": workforce_count}
    logger.info("Signal dispatch complete: %s", totals)
    return totals
