"""Shared recommendation timeline adapters (append-only references)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceRecommendationLifecycleEvent,
    RecommendationTimelineEvent,
)
from app.schemas.common import Pagination
from app.schemas.time_series import (
    RecommendationSubjectSummaryRead,
    RecommendationTimelineEventRead,
)

logger = logging.getLogger(__name__)


async def append_recommendation_timeline(
    session: AsyncSession,
    *,
    org_id: UUID,
    domain: str,
    subject_table: str,
    subject_id: UUID,
    event_type: str,
    project_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    source_agent: str | None = None,
    recommendation_type: str | None = None,
    severity: str | None = None,
    confidence: Decimal | None = None,
    affected_kpi_keys: list[str] | None = None,
    status_snapshot: str | None = None,
    related_table: str | None = None,
    related_id: UUID | None = None,
    conversion_target: str | None = None,
    resolution_outcome: str | None = None,
    strategy_version: str | None = None,
    evidence_fingerprint: str | None = None,
    governance_lifecycle_event_id: UUID | None = None,
    audit_log_id: UUID | None = None,
    event_timestamp: datetime | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> RecommendationTimelineEvent:
    if idempotency_key:
        existing = (
            await session.execute(
                select(RecommendationTimelineEvent).where(
                    RecommendationTimelineEvent.domain == domain,
                    RecommendationTimelineEvent.subject_id == subject_id,
                    RecommendationTimelineEvent.event_type == event_type,
                    RecommendationTimelineEvent.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    row = RecommendationTimelineEvent(
        org_id=org_id,
        project_id=project_id,
        domain=domain,
        subject_table=subject_table,
        subject_id=subject_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        source_agent=source_agent,
        recommendation_type=recommendation_type,
        severity=severity,
        confidence=confidence,
        affected_kpi_keys=affected_kpi_keys or [],
        status_snapshot=status_snapshot,
        related_table=related_table,
        related_id=related_id,
        conversion_target=conversion_target,
        resolution_outcome=resolution_outcome,
        strategy_version=strategy_version,
        evidence_fingerprint=evidence_fingerprint,
        governance_lifecycle_event_id=governance_lifecycle_event_id,
        audit_log_id=audit_log_id,
        event_timestamp=event_timestamp or datetime.now(UTC),
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "event=recommendation_timeline_appended domain=%s subject_id=%s event_type=%s",
        domain,
        subject_id,
        event_type,
    )
    return row


async def append_from_governance_lifecycle(
    session: AsyncSession,
    lifecycle: GovernanceRecommendationLifecycleEvent,
    *,
    project_id: UUID | None = None,
    source_agent: str = "governance",
    recommendation_type: str | None = None,
    severity: str | None = None,
    status_snapshot: str | None = None,
    strategy_version: str | None = None,
) -> RecommendationTimelineEvent:
    return await append_recommendation_timeline(
        session,
        org_id=lifecycle.org_id,
        project_id=project_id,
        domain="governance_ai",
        subject_table="governance_ai_recommendations",
        subject_id=lifecycle.recommendation_id,
        event_type=lifecycle.event_type.value
        if hasattr(lifecycle.event_type, "value")
        else str(lifecycle.event_type),
        actor_user_id=lifecycle.actor_user_id,
        source_agent=source_agent,
        recommendation_type=recommendation_type,
        severity=severity,
        status_snapshot=status_snapshot,
        conversion_target=lifecycle.conversion_target,
        related_id=lifecycle.conversion_target_id,
        related_table=(
            "governance_actions"
            if lifecycle.conversion_target == "action"
            else "governance_escalations"
            if lifecycle.conversion_target == "escalation"
            else None
        ),
        strategy_version=strategy_version,
        governance_lifecycle_event_id=lifecycle.id,
        event_timestamp=lifecycle.created_at,
        payload=dict(lifecycle.event_metadata or {}),
        idempotency_key=f"gov-lifecycle:{lifecycle.id}",
    )


async def backfill_governance_lifecycle(
    session: AsyncSession,
    *,
    org_id: UUID | None = None,
    limit: int = 500,
) -> int:
    stmt = select(GovernanceRecommendationLifecycleEvent).order_by(
        GovernanceRecommendationLifecycleEvent.created_at.asc()
    )
    if org_id is not None:
        stmt = stmt.where(GovernanceRecommendationLifecycleEvent.org_id == org_id)
    rows = list((await session.execute(stmt.limit(limit))).scalars())
    count = 0
    for row in rows:
        await append_from_governance_lifecycle(session, row)
        count += 1
    return count


async def list_recommendation_subjects(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    domain: str | None = None,
    project_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RecommendationSubjectSummaryRead], Pagination]:
    if current_user.role == AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Clients cannot access recommendation timelines.")
    stmt = select(RecommendationTimelineEvent)
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(RecommendationTimelineEvent.org_id == current_user.org_id)
    if domain:
        stmt = stmt.where(RecommendationTimelineEvent.domain == domain)
    if project_id:
        stmt = stmt.where(RecommendationTimelineEvent.project_id == project_id)
    rows = list(
        (
            await session.execute(
                stmt.order_by(RecommendationTimelineEvent.event_timestamp.desc()).limit(1000)
            )
        ).scalars()
    )
    latest: dict[UUID, RecommendationTimelineEvent] = {}
    counts: dict[UUID, int] = {}
    for row in rows:
        counts[row.subject_id] = counts.get(row.subject_id, 0) + 1
        if row.subject_id not in latest:
            latest[row.subject_id] = row
    summaries = [
        RecommendationSubjectSummaryRead(
            domain=row.domain,
            subject_table=row.subject_table,
            subject_id=row.subject_id,
            project_id=row.project_id,
            source_agent=row.source_agent,
            recommendation_type=row.recommendation_type,
            severity=row.severity,
            status_snapshot=row.status_snapshot,
            last_event_type=row.event_type,
            last_event_at=row.event_timestamp,
            event_count=counts[row.subject_id],
        )
        for row in latest.values()
    ]
    page = summaries[offset : offset + limit]
    return page, Pagination(limit=limit, offset=offset, total=len(summaries))


async def list_recommendation_timeline(
    session: AsyncSession,
    current_user: CurrentUser,
    subject_id: UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[RecommendationTimelineEventRead], Pagination]:
    if current_user.role == AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Clients cannot access recommendation timelines.")
    stmt = select(RecommendationTimelineEvent).where(
        RecommendationTimelineEvent.subject_id == subject_id
    )
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(RecommendationTimelineEvent.org_id == current_user.org_id)
    rows = list(
        (
            await session.execute(
                stmt.order_by(RecommendationTimelineEvent.event_timestamp.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    total = (
        await session.execute(
            select(RecommendationTimelineEvent.id).where(
                RecommendationTimelineEvent.subject_id == subject_id,
                *(
                    [RecommendationTimelineEvent.org_id == current_user.org_id]
                    if current_user.role != AppRole.SUPER_ADMIN
                    else []
                ),
            )
        )
    ).all()
    return (
        [RecommendationTimelineEventRead.model_validate(row) for row in rows],
        Pagination(limit=limit, offset=offset, total=len(total)),
    )
