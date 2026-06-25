from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeLesson, SopDocument


async def keyword_search(
    session: AsyncSession,
    org_id,
    query: str,
    *,
    limit: int = 20,
) -> list[dict]:
    """Simple keyword search over lessons and SOPs. Returns [] when no matches."""
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

    sops = list(
        (
            await session.execute(
                select(SopDocument)
                .where(
                    SopDocument.org_id == org_id,
                    SopDocument.is_active.is_(True),
                    or_(
                        SopDocument.title.ilike(term),
                        SopDocument.content_text.ilike(term),
                    ),
                )
                .order_by(SopDocument.effective_date.desc())
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
    for sop in sops:
        results.append(
            {
                "type": "sop",
                "id": str(sop.id),
                "title": sop.title,
                "version": sop.version,
                "snippet": sop.content_text[:200],
                "tags": sop.tags or [],
            }
        )
    return results[:limit]
