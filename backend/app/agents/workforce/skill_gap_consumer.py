"""Consume skill_gap inter-agent signals for Workforce & Capability."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.signals import mark_signal_consumed, mark_signal_failed
from app.db.models import (
    AppRole,
    InterAgentSignal,
    Notification,
    NotificationType,
    SignalType,
    User,
)

logger = logging.getLogger(__name__)

TARGET_AGENT = "workforce_agent"


async def consume_skill_gap_signal(session: AsyncSession, signal: InterAgentSignal) -> None:
    payload: dict[str, Any] = signal.payload or {}
    if not signal.org_id:
        await mark_signal_failed(session, signal, "Missing org_id on skill_gap signal")
        return

    reviewer_ids = payload.get("reviewer_ids") or []
    urgency = payload.get("urgency", "this_week")
    error_category = payload.get("error_category") or "quality"
    body = (
        f"Skill gap detected from Quality Intelligence: {len(reviewer_ids)} reviewer(s) "
        f"need {payload.get('recommendation', 'calibration')} for {error_category}. "
        f"Urgency: {urgency}."
    )

    existing = (
        await session.execute(
            select(Notification).where(
                Notification.org_id == signal.org_id,
                Notification.notification_type == NotificationType.SKILL_GAP_DETECTED,
                Notification.source_table == "inter_agent_signals",
                Notification.source_row_id == signal.id,
            )
        )
    ).scalars()
    if not list(existing):
        dm_users = (
            await session.execute(
                select(User).where(
                    User.org_id == signal.org_id,
                    User.role == AppRole.DELIVERY_MANAGER,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        ).scalars()
        for user in dm_users:
            session.add(
                Notification(
                    user_id=user.id,
                    org_id=signal.org_id,
                    notification_type=NotificationType.SKILL_GAP_DETECTED,
                    title="Workforce skill gap from quality drift",
                    body=body,
                    source_table="inter_agent_signals",
                    source_row_id=signal.id,
                )
            )

    await mark_signal_consumed(session, signal)
    logger.info("Consumed skill_gap signal id=%s reviewers=%s", signal.id, len(reviewer_ids))


async def consume_pending_skill_gap_signals(session: AsyncSession) -> int:
    from app.agents.quality_intelligence.signals import fetch_pending_signals

    signals = await fetch_pending_signals(session, target_agent=TARGET_AGENT, signal_type=SignalType.SKILL_GAP)
    count = 0
    for signal in signals:
        try:
            await consume_skill_gap_signal(session, signal)
            count += 1
        except Exception as exc:
            logger.exception("Failed to consume skill_gap signal %s", signal.id)
            await mark_signal_failed(session, signal, str(exc))
    if count:
        await session.commit()
    return count
