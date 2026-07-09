from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.query_handler import PROJECT_GOVERNANCE_AGENT_NAME
from app.agents.governance.schemas.governance import GovernanceMonitoringRead
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AppRole
from app.db.models.audit_log import AuditLog


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


async def get_governance_monitoring(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    window_hours: int = 24,
) -> GovernanceMonitoringRead:
    effective_hours = min(max(window_hours, 1), 168)
    since = datetime.now(UTC) - timedelta(hours=effective_hours)

    audit_stmt = select(AuditLog).where(
        AuditLog.event_type.like("governance.%"),
        AuditLog.created_at >= since,
    )
    query_stmt = select(AgentQuery).where(
        AgentQuery.agent_name == PROJECT_GOVERNANCE_AGENT_NAME,
        AgentQuery.created_at >= since,
    )
    if current_user.role != AppRole.SUPER_ADMIN:
        audit_stmt = audit_stmt.where(AuditLog.org_id == current_user.org_id)
        query_stmt = query_stmt.where(AgentQuery.org_id == current_user.org_id)

    audit_rows = list((await session.execute(audit_stmt)).scalars())
    query_rows = list((await session.execute(query_stmt)).scalars())
    latencies = [row.latency_ms for row in query_rows if row.latency_ms is not None]
    empty_answers = sum(
        1
        for row in query_rows
        if not row.answer_text
        or "do not have enough approved governance evidence" in row.answer_text.lower()
    )
    event_counts = Counter(row.event_type for row in audit_rows)
    return GovernanceMonitoringRead(
        generated_at=datetime.now(UTC),
        window_hours=effective_hours,
        audit_events=len(audit_rows),
        chatbot_queries=len(query_rows),
        chatbot_latency_avg_ms=round(sum(latencies) / len(latencies)) if latencies else None,
        chatbot_latency_p95_ms=_percentile(latencies, 0.95),
        failed_or_empty_ai_answers=empty_answers,
        dashboard_exports=event_counts.get("governance.dashboard.exported", 0)
        + event_counts.get("governance.charter.exported", 0),
        recent_event_types=dict(event_counts.most_common(12)),
    )
