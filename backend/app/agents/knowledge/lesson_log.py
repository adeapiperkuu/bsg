from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeLesson, QualityLessonLink, RiskAlert


async def write_lesson_on_alert_resolve(
    session: AsyncSession,
    alert: RiskAlert,
    *,
    created_by,
    resolution_summary: str | None = None,
) -> KnowledgeLesson | None:
    """Create a lesson log entry when a quality alert is resolved (BR-08)."""
    existing = (
        await session.execute(
            select(KnowledgeLesson).where(KnowledgeLesson.linked_alert_id == alert.id)
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    body = resolution_summary or alert.detail
    lesson = KnowledgeLesson(
        org_id=alert.org_id,
        title=f"Quality resolution: {alert.title}",
        body=body,
        tags=["quality", alert.alert_type.value],
        linked_alert_id=alert.id,
        created_by=created_by,
    )
    session.add(lesson)
    await session.flush()

    session.add(
        QualityLessonLink(
            org_id=alert.org_id,
            risk_alert_id=alert.id,
            knowledge_lesson_id=lesson.id,
        )
    )
    await session.flush()
    return lesson
