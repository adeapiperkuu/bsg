from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Annotator, WorkforceSkill


async def build_skill_matrix(session: AsyncSession, org_id) -> dict:
    """Aggregate skills by skill_code with annotator counts per proficiency level."""
    rows = list(
        (
            await session.execute(
                select(WorkforceSkill, Annotator)
                .join(Annotator, WorkforceSkill.annotator_id == Annotator.id)
                .where(
                    WorkforceSkill.org_id == org_id,
                    Annotator.is_active.is_(True),
                    Annotator.deleted_at.is_(None),
                )
            )
        ).all()
    )

    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for skill, _annotator in rows:
        matrix[skill.skill_code][skill.proficiency_level] += 1

    return {code: dict(levels) for code, levels in matrix.items()}


async def find_skill_gaps(session: AsyncSession, org_id, required_skills: list[str]) -> list[str]:
    matrix = await build_skill_matrix(session, org_id)
    gaps = []
    for skill in required_skills:
        levels = matrix.get(skill, {})
        experts = levels.get("expert", 0) + levels.get("advanced", 0)
        if experts == 0:
            gaps.append(skill)
    return gaps
