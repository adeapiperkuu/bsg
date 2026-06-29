"""Inter-agent signal helpers for Quality Intelligence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InterAgentSignal, SignalStatus, SignalType


async def emit_inter_agent_signal(
    session: AsyncSession,
    *,
    signal_type: str,
    target_agent: str,
    payload: dict[str, Any],
    project_id: UUID | None = None,
    org_id: UUID | None = None,
    source_agent: str = "quality_intelligence_agent",
) -> InterAgentSignal:
    signal = InterAgentSignal(
        signal_type=signal_type,
        source_agent=source_agent,
        target_agent=target_agent,
        payload=payload,
        status=SignalStatus.PENDING,
        project_id=project_id,
        org_id=org_id,
    )
    session.add(signal)
    await session.flush()
    return signal


async def fetch_pending_signals(
    session: AsyncSession,
    *,
    target_agent: str,
    signal_type: str | None = None,
    limit: int = 100,
) -> list[InterAgentSignal]:
    query = (
        select(InterAgentSignal)
        .where(
            InterAgentSignal.target_agent == target_agent,
            InterAgentSignal.status == SignalStatus.PENDING,
        )
        .order_by(InterAgentSignal.created_at.asc())
        .limit(limit)
    )
    if signal_type is not None:
        query = query.where(InterAgentSignal.signal_type == signal_type)
    return list((await session.execute(query)).scalars())


async def mark_signal_consumed(session: AsyncSession, signal: InterAgentSignal) -> InterAgentSignal:
    signal.status = SignalStatus.CONSUMED
    payload = dict(signal.payload or {})
    payload.pop("_error", None)
    signal.payload = payload
    await session.flush()
    return signal


async def mark_signal_failed(
    session: AsyncSession,
    signal: InterAgentSignal,
    error: str,
) -> InterAgentSignal:
    signal.status = SignalStatus.FAILED
    payload = dict(signal.payload or {})
    payload["_error"] = error[:500]
    signal.payload = payload
    await session.flush()
    return signal


async def mirror_quality_risk_signal(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    alert_id: UUID,
    quality_risk_payload: dict[str, Any],
) -> InterAgentSignal:
    payload = {
        **quality_risk_payload,
        "project_id": str(project_id),
        "alert_id": str(alert_id),
    }
    return await emit_inter_agent_signal(
        session,
        signal_type=SignalType.QUALITY_RISK,
        target_agent="delivery_performance_agent",
        payload=payload,
        project_id=project_id,
        org_id=org_id,
    )
