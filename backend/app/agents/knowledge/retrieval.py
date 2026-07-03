from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeLesson


async def keyword_search(
    session: AsyncSession,
    org_id,
    query: str,
    *,
    limit: int = 20,
) -> list[dict]:
    """Simple keyword search over knowledge lessons. Returns [] when no matches."""
    if not query or not query.strip():
        return []

    term = f"%{query.strip().lower()}%"

    lessons = list(
        (
            await session.execute(
                select(KnowledgeLesson)
                .where(
                    KnowledgeLesson.org_id == org_id,
                    or_(
                        KnowledgeLesson.title.ilike(term),
                        KnowledgeLesson.body.ilike(term),
                    ),
                )
                .order_by(KnowledgeLesson.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )

    results: list[dict] = []
    for lesson in lessons:
        results.append(
            {
                "type": "lesson",
                "id": str(lesson.id),
                "title": lesson.title,
                "snippet": lesson.body[:200],
                "tags": lesson.tags or [],
            }
        )
    return results[:limit]
