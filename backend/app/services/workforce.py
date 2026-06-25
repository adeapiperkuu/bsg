from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workforce.skill_matrix import build_skill_matrix, find_skill_gaps
from app.agents.workforce.utilization import get_latest_utilization_by_team, utilization_status
from app.core.security import CurrentUser
from app.db.models import Annotator, Notification, NotificationType, Team, WorkforceSkill, WorkforceUtilizationSnapshot
from app.schemas.domain import (
    SkillGapSignal,
    SkillMatrixEntry,
    SmeAllocationRead,
    TeamUtilizationRead,
    WorkforceDashboardKpis,
    WorkforceDashboardRead,
)


async def get_skill_gap_signals(session: AsyncSession, org_id) -> list[SkillGapSignal]:
    rows = list(
        (
            await session.execute(
                select(Notification).where(
                    Notification.org_id == org_id,
                    Notification.notification_type == NotificationType.SKILL_GAP_DETECTED,
                )
                .order_by(Notification.created_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    return [
        SkillGapSignal(
            id=row.id,
            title=row.title,
            body=row.body,
            source_row_id=row.source_row_id,
            created_at=row.created_at,
            is_read=row.is_read,
        )
        for row in rows
    ]


async def get_workforce_dashboard(
    session: AsyncSession,
    current_user: CurrentUser,
) -> WorkforceDashboardRead:
    org_id = current_user.org_id
    util_snaps = await get_latest_utilization_by_team(session, org_id)
    teams = {
        t.id: t
        for t in (await session.execute(select(Team).where(Team.org_id == org_id, Team.deleted_at.is_(None)))).scalars()
    }

    team_utilization = [
        TeamUtilizationRead(
            team_id=snap.team_id,
            team_name=teams[snap.team_id].name if snap.team_id in teams else str(snap.team_id),
            iso_year=snap.iso_year,
            iso_week=snap.iso_week,
            target_hours=snap.target_hours,
            logged_hours=snap.logged_hours,
            utilization_pct=snap.utilization_pct,
            status=utilization_status(snap.utilization_pct),
        )
        for snap in util_snaps
    ]

    matrix = await build_skill_matrix(session, org_id)
    skill_matrix = [
        SkillMatrixEntry(skill_code=code, proficiency_counts=counts)
        for code, counts in sorted(matrix.items())
    ]

    sme_count = (
        await session.execute(
            select(Annotator).where(
                Annotator.org_id == org_id,
                Annotator.is_sme_certified.is_(True),
                Annotator.is_active.is_(True),
                Annotator.deleted_at.is_(None),
            )
        )
    ).scalars()
    sme_total = len(list(sme_count))

    skill_rows = list(
        (await session.execute(select(WorkforceSkill).where(WorkforceSkill.org_id == org_id))).scalars()
    )
    gaps = await find_skill_gaps(session, org_id, list(matrix.keys()))

    avg_util = None
    if util_snaps:
        avg_util = str(
            round(sum(float(s.utilization_pct or 0) for s in util_snaps) / len(util_snaps), 1)
        )

    return WorkforceDashboardRead(
        kpis=WorkforceDashboardKpis(
            teams_tracked=len(teams),
            avg_utilization_pct=avg_util,
            sme_certified_count=sme_total,
            skill_records=len(skill_rows),
            open_skill_gaps=len(gaps),
        ),
        team_utilization=team_utilization,
        skill_matrix=skill_matrix,
        skill_gap_signals=await get_skill_gap_signals(session, org_id),
    )


async def get_sme_allocation(session: AsyncSession, org_id) -> list[SmeAllocationRead]:
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    smes = list(
        (
            await session.execute(
                select(Annotator, Team)
                .join(Team, Annotator.team_id == Team.id)
                .where(
                    Annotator.org_id == org_id,
                    Annotator.is_sme_certified.is_(True),
                    Annotator.is_active.is_(True),
                    Annotator.deleted_at.is_(None),
                )
            )
        ).all()
    )

    results: list[SmeAllocationRead] = []
    for annotator, team in smes:
        skills = list(
            (
                await session.execute(
                    select(WorkforceSkill).where(WorkforceSkill.annotator_id == annotator.id)
                )
            ).scalars()
        )
        util = (
            await session.execute(
                select(WorkforceUtilizationSnapshot).where(
                    WorkforceUtilizationSnapshot.team_id == team.id,
                    WorkforceUtilizationSnapshot.iso_year == iso_year,
                    WorkforceUtilizationSnapshot.iso_week == iso_week,
                )
            )
        ).scalar_one_or_none()

        results.append(
            SmeAllocationRead(
                annotator_id=annotator.id,
                team_id=team.id,
                team_name=team.name,
                site=annotator.site.value,
                skills=[s.skill_code for s in skills],
                utilization_pct=util.utilization_pct if util else None,
            )
        )
    return results
