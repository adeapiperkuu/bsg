from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Team, WorkforceUtilizationSnapshot


async def get_latest_utilization_by_team(
    session: AsyncSession,
    org_id,
    *,
    iso_year: int | None = None,
    iso_week: int | None = None,
) -> list[WorkforceUtilizationSnapshot]:
    if iso_year is None or iso_week is None:
        now = datetime.now(timezone.utc)
        iso_year, iso_week, _ = now.isocalendar()

    teams = list(
        (await session.execute(select(Team).where(Team.org_id == org_id, Team.deleted_at.is_(None)))).scalars()
    )
    results: list[WorkforceUtilizationSnapshot] = []
    for team in teams:
        snap = (
            await session.execute(
                select(WorkforceUtilizationSnapshot)
                .where(
                    WorkforceUtilizationSnapshot.team_id == team.id,
                    WorkforceUtilizationSnapshot.iso_year == iso_year,
                    WorkforceUtilizationSnapshot.iso_week == iso_week,
                )
            )
        ).scalar_one_or_none()
        if snap:
            results.append(snap)
    return results


def utilization_status(pct: Decimal | None) -> str:
    if pct is None:
        return "unknown"
    value = float(pct)
    if value >= 100:
        return "over_allocated"
    if value >= 85:
        return "high"
    if value >= 60:
        return "balanced"
    return "under_utilized"
