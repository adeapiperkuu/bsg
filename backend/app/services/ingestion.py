import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.throughput import sum_recent_units_completed
from app.agents.delivery.services.scoring_service import run_delivery_scoring
from app.db.models import Project, ThroughputSnapshot
from app.schemas.domain import ThroughputSnapshotCreate

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ThroughputIngestResult:
    """Result of persisting a throughput snapshot plus the scoring outcome.

    The snapshot write always succeeds independently of scoring — callers must surface
    `scoring_status`/`scoring_error` to the API response instead of hiding a scoring
    failure behind an unconditional "success".
    """

    snapshot: ThroughputSnapshot
    scoring_status: Literal["ok", "failed"]
    scoring_error: str | None


async def upsert_throughput_snapshot(
    session: AsyncSession,
    project: Project,
    payload: ThroughputSnapshotCreate,
) -> ThroughputIngestResult:
    existing = (
        await session.execute(
            select(ThroughputSnapshot).where(
                ThroughputSnapshot.project_id == project.id,
                ThroughputSnapshot.snapshot_date == payload.snapshot_date,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        snapshot = ThroughputSnapshot(
            project_id=project.id,
            org_id=project.org_id,
            snapshot_date=payload.snapshot_date,
            units_completed=payload.units_completed,
            units_forecast=payload.units_forecast,
            rolling_7day_units=None,
        )
        session.add(snapshot)
    else:
        existing.units_completed = payload.units_completed
        existing.units_forecast = payload.units_forecast
        existing.rolling_7day_units = None
        snapshot = existing

    # Flush before computing rolling so today's row is visible in the date window.
    await session.flush()
    snapshot.rolling_7day_units = await _compute_rolling_7day_units(
        session, project.id, payload.snapshot_date
    )
    await session.flush()

    # Scoring runs in a savepoint so a failure cannot corrupt the snapshot. A failure here
    # is never hidden from the caller: it is surfaced as scoring_status="failed" on the
    # ingest result so the API response (and therefore the dashboard) can reflect that
    # confidence/risk may be stale rather than silently reporting success.
    scoring_status: Literal["ok", "failed"] = "ok"
    scoring_error: str | None = None
    try:
        async with session.begin_nested():
            run_result = await run_delivery_scoring(
                session,
                project_id=project.id,
                as_of_date=payload.snapshot_date,
                project=project,
            )
        scoring_status = run_result.scoring_status
        scoring_error = run_result.scoring_error
        if scoring_status == "failed":
            logger.warning(
                "Delivery scoring completed with a failed handler for project %s on %s: %s",
                project.id,
                payload.snapshot_date,
                scoring_error,
            )
    except Exception as exc:
        scoring_status = "failed"
        scoring_error = f"scoring raised {type(exc).__name__}"
        logger.warning(
            "Delivery scoring failed for project %s on %s; snapshot preserved.",
            project.id,
            payload.snapshot_date,
            exc_info=True,
        )

    return ThroughputIngestResult(
        snapshot=snapshot,
        scoring_status=scoring_status,
        scoring_error=scoring_error,
    )


async def _compute_rolling_7day_units(
    session: AsyncSession,
    project_id: UUID,
    snapshot_date: date,
) -> int | None:
    """Sum units_completed for the 7-calendar-day window ending on snapshot_date."""
    cutoff = snapshot_date - timedelta(days=6)
    rows = (
        await session.execute(
            select(ThroughputSnapshot.units_completed)
            .where(
                ThroughputSnapshot.project_id == project_id,
                ThroughputSnapshot.snapshot_date >= cutoff,
                ThroughputSnapshot.snapshot_date <= snapshot_date,
            )
            .order_by(ThroughputSnapshot.snapshot_date.desc())
        )
    ).scalars()
    return sum_recent_units_completed(list(rows))
