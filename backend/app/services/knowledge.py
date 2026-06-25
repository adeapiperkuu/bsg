from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge.retrieval import keyword_search
from app.core.security import CurrentUser
from app.db.models import KnowledgeLesson
from app.schemas.domain import KnowledgeLessonCreate, KnowledgeLessonRead, KnowledgeSearchResult


async def list_lessons(
    session: AsyncSession,
    org_id,
    *,
    limit: int = 50,
) -> list[KnowledgeLesson]:
    return list(
        (
            await session.execute(
                select(KnowledgeLesson)
                .where(KnowledgeLesson.org_id == org_id)
                .order_by(KnowledgeLesson.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def create_lesson(
    session: AsyncSession,
    org_id,
    payload: KnowledgeLessonCreate,
    created_by: UUID,
) -> KnowledgeLesson:
    lesson = KnowledgeLesson(
        org_id=org_id,
        title=payload.title,
        body=payload.body,
        tags=payload.tags,
        linked_quality_event_id=payload.linked_quality_event_id,
        linked_alert_id=payload.linked_alert_id,
        created_by=created_by,
    )
    session.add(lesson)
    await session.flush()
    return lesson


async def search_knowledge(
    session: AsyncSession,
    org_id,
    query: str,
) -> list[KnowledgeSearchResult]:
    hits = await keyword_search(session, org_id, query)
    return [KnowledgeSearchResult.model_validate(h) for h in hits]
