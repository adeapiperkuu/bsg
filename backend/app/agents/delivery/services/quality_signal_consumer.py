"""Consume quality_risk inter-agent signals for Delivery Performance."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.signals import mark_signal_consumed, mark_signal_failed
from app.db.models import (
    AlertStatus,
    AppRole,
    InterAgentSignal,
    Notification,
    NotificationType,
    RiskAlert,
    SignalType,
    User,
)

logger = logging.getLogger(__name__)

TARGET_AGENT = "delivery_performance_agent"


async def consume_quality_risk_signal(
    session: AsyncSession,
    signal: InterAgentSignal,
) -> None:
    payload: dict[str, Any] = signal.payload or {}
    alert_id_raw = payload.get("alert_id")
    if not alert_id_raw:
        await mark_signal_failed(session, signal, "Missing alert_id in quality_risk payload")
        return

    try:
        alert_id = UUID(str(alert_id_raw))
    except (TypeError, ValueError):
        await mark_signal_failed(session, signal, "Invalid alert_id in quality_risk payload")
        return

    alert = (await session.execute(select(RiskAlert).where(RiskAlert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        await mark_signal_failed(session, signal, f"Risk alert {alert_id} not found")
        return

    causes = dict(alert.contributing_causes or {})
    causes["delivery_signal_consumed"] = {
        "signal_id": str(signal.id),
        "rework_volume_units": payload.get("rework_volume_units"),
        "rework_time_estimate_days": payload.get("rework_time_estimate_days"),
        "severity": payload.get("severity"),
        "hold_recommended": payload.get("hold_recommended"),
    }
    alert.contributing_causes = causes

    if signal.org_id:
        existing = (
            await session.execute(
                select(Notification).where(
                    Notification.org_id == signal.org_id,
                    Notification.notification_type == NotificationType.RISK_ALERT,
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
            detail = (
                f"Quality risk signal consumed: rework volume {payload.get('rework_volume_units', 0)} units, "
                f"estimated {payload.get('rework_time_estimate_days', 0)} days impact."
            )
            for user in dm_users:
                session.add(
                    Notification(
                        user_id=user.id,
                        org_id=signal.org_id,
                        notification_type=NotificationType.RISK_ALERT,
                        title="Delivery impact from quality drift",
                        body=detail,
                        source_table="inter_agent_signals",
                        source_row_id=signal.id,
                    )
                )

    if alert.status == AlertStatus.OPEN:
        alert.status = AlertStatus.ACKNOWLEDGED

    await mark_signal_consumed(session, signal)
    logger.info("Consumed quality_risk signal id=%s alert_id=%s", signal.id, alert_id)


async def consume_pending_quality_risk_signals(session: AsyncSession) -> int:
    from app.agents.quality_intelligence.signals import fetch_pending_signals

    signals = await fetch_pending_signals(session, target_agent=TARGET_AGENT, signal_type=SignalType.QUALITY_RISK)
    count = 0
    for signal in signals:
        try:
            await consume_quality_risk_signal(session, signal)
            count += 1
        except Exception as exc:
            logger.exception("Failed to consume quality_risk signal %s", signal.id)
            await mark_signal_failed(session, signal, str(exc))
    if count:
        await session.commit()
    return count
