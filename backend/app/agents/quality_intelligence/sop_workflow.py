from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.optional_tables import query_optional_table
from app.db.models import IaaMeasurementRecord, QualitySnapshot, SopVersionHistory


@dataclass(frozen=True)
class SopAmbiguityFlag:
    detected: bool
    detail: str | None = None
    sop_version: str | None = None
    affected_reviewers: int = 0


async def _load_iaa_records(session: AsyncSession, snapshot: QualitySnapshot) -> list[IaaMeasurementRecord]:
    return list(
        (
            await session.execute(
                select(IaaMeasurementRecord).where(
                    IaaMeasurementRecord.project_id == snapshot.project_id,
                    IaaMeasurementRecord.iso_year == snapshot.iso_year,
                    IaaMeasurementRecord.iso_week == snapshot.iso_week,
                )
            )
        ).scalars()
    )


async def _load_recent_sop_version(session: AsyncSession, snapshot: QualitySnapshot) -> SopVersionHistory | None:
    return (
        await session.execute(
            select(SopVersionHistory)
            .where(SopVersionHistory.org_id == snapshot.org_id)
            .order_by(SopVersionHistory.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def detect_sop_ambiguity(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> SopAmbiguityFlag:
    """UC-04: detect distributed IAA drop correlated with recent SOP changes."""
    iaa_records = await query_optional_table(
        session,
        lambda: _load_iaa_records(session, snapshot),
        [],
    )

    if len(iaa_records) < 3:
        return SopAmbiguityFlag(detected=False, detail="Insufficient IAA pair data")

    low_alpha = [r for r in iaa_records if r.krippendorff_alpha is not None and float(r.krippendorff_alpha) < 0.75]
    if len(low_alpha) < 3:
        return SopAmbiguityFlag(detected=False)

    recent_sop = await query_optional_table(
        session,
        lambda: _load_recent_sop_version(session, snapshot),
        None,
    )

    if recent_sop is None:
        return SopAmbiguityFlag(
            detected=True,
            detail="Distributed IAA drop across 3+ reviewer pairs without recent SOP version on file",
            affected_reviewers=len(low_alpha),
        )

    window_start = snapshot.created_at.date() - timedelta(days=14) if snapshot.created_at else None
    if window_start and recent_sop.effective_date >= window_start:
        return SopAmbiguityFlag(
            detected=True,
            detail="IAA drop correlates with recent SOP version change",
            sop_version=recent_sop.version,
            affected_reviewers=len(low_alpha),
        )

    return SopAmbiguityFlag(detected=True, detail="Distributed IAA drop detected", affected_reviewers=len(low_alpha))
