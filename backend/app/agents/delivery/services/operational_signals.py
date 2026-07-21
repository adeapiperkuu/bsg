"""Phase 15.2 operational signal providers for Delivery root-cause inputs.

Ingested timesheets, absenteeism, review/backlog queues, capacity, and team
availability become deterministic severity signals. AI must not invent values
from these sources; the root-cause engine alone consumes the provider outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.operational_signals import (
    absenteeism_severity,
    backlog_queue_severity,
    capacity_shortage_severity,
    combine_max,
    review_queue_severity,
    team_availability_severity,
    timesheet_underfill_severity,
)
from app.agents.delivery.analytics.root_cause import quantize_pct
from app.db.models import (
    DeliveryAbsenteeismSnapshot,
    DeliveryBacklogQueueSnapshot,
    DeliveryCapacitySnapshot,
    DeliveryReviewQueueSnapshot,
    DeliveryTeamAvailabilitySnapshot,
    DeliveryTimesheetEntry,
)


@dataclass(frozen=True, slots=True)
class OperationalSignal:
    """Optional Phase 15.2 severity input (0-100)."""

    value: Decimal
    source: str
    evidence: dict[str, object]


class OperationalSignalProvider(Protocol):
    async def get_timesheet_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...

    async def get_absenteeism_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...

    async def get_review_queue_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...

    async def get_backlog_queue_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...

    async def get_capacity_snapshot_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...

    async def get_dependency_delay_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...

    async def get_scope_volatility_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None: ...


class StubOperationalSignalProvider:
    """No-op provider retained for tests that inject empty operational context."""

    async def get_timesheet_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None

    async def get_absenteeism_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None

    async def get_review_queue_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None

    async def get_backlog_queue_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None

    async def get_capacity_snapshot_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None

    async def get_dependency_delay_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None

    async def get_scope_volatility_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        return None


class DbOperationalSignalProvider:
    """Derive root-cause severity signals from ingested operational tables."""

    async def get_timesheet_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        target = as_of or date.today()
        rows = (
            (
                await session.execute(
                    select(DeliveryTimesheetEntry).where(
                        DeliveryTimesheetEntry.project_id == project_id,
                        DeliveryTimesheetEntry.snapshot_date == target,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            # Fall back to latest date on/before as_of.
            latest_date = (
                await session.execute(
                    select(DeliveryTimesheetEntry.snapshot_date)
                    .where(
                        DeliveryTimesheetEntry.project_id == project_id,
                        DeliveryTimesheetEntry.snapshot_date <= target,
                    )
                    .order_by(DeliveryTimesheetEntry.snapshot_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest_date is None:
                return None
            rows = (
                (
                    await session.execute(
                        select(DeliveryTimesheetEntry).where(
                            DeliveryTimesheetEntry.project_id == project_id,
                            DeliveryTimesheetEntry.snapshot_date == latest_date,
                        )
                    )
                )
                .scalars()
                .all()
            )
        severities: list[Decimal] = []
        evidence_rows: list[dict[str, object]] = []
        for row in rows:
            severity = timesheet_underfill_severity(
                hours_logged=row.hours_logged,
                expected_hours=row.expected_hours,
            )
            if severity is None:
                continue
            severities.append(severity)
            evidence_rows.append(
                {
                    "team_id": str(row.team_id),
                    "hours_logged": float(row.hours_logged),
                    "expected_hours": float(row.expected_hours) if row.expected_hours else None,
                    "severity": float(severity),
                }
            )
        if not severities:
            return None
        value = quantize_pct(sum(severities, Decimal("0")) / Decimal(len(severities)))
        return OperationalSignal(
            value=value,
            source="delivery_timesheet_entries",
            evidence={"teams": evidence_rows, "snapshot_date": str(rows[0].snapshot_date)},
        )

    async def get_absenteeism_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        row = await _latest_project_row(
            session,
            DeliveryAbsenteeismSnapshot,
            project_id=project_id,
            as_of=as_of or date.today(),
        )
        if row is None:
            return None
        value = absenteeism_severity(absence_rate_pct=row.absence_rate_pct)
        return OperationalSignal(
            value=value,
            source="delivery_absenteeism_snapshots",
            evidence={
                "absence_rate_pct": float(row.absence_rate_pct),
                "absent_fte": float(row.absent_fte),
                "planned_fte": float(row.planned_fte),
                "snapshot_date": str(row.snapshot_date),
            },
        )

    async def get_review_queue_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        row = await _latest_project_row(
            session,
            DeliveryReviewQueueSnapshot,
            project_id=project_id,
            as_of=as_of or date.today(),
        )
        if row is None:
            return None
        value = review_queue_severity(
            pending_count=row.pending_count,
            avg_turnaround_hours=row.avg_turnaround_hours,
            sla_breach_count=row.sla_breach_count,
        )
        return OperationalSignal(
            value=value,
            source="delivery_review_queue_snapshots",
            evidence={
                "pending_count": row.pending_count,
                "avg_turnaround_hours": float(row.avg_turnaround_hours),
                "sla_breach_count": row.sla_breach_count,
                "snapshot_date": str(row.snapshot_date),
            },
        )

    async def get_backlog_queue_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        row = await _latest_project_row(
            session,
            DeliveryBacklogQueueSnapshot,
            project_id=project_id,
            as_of=as_of or date.today(),
        )
        if row is None:
            return None
        value = backlog_queue_severity(
            item_count=row.item_count,
            aging_item_count=row.aging_item_count,
            oldest_item_age_days=row.oldest_item_age_days,
        )
        return OperationalSignal(
            value=value,
            source="delivery_backlog_queue_snapshots",
            evidence={
                "item_count": row.item_count,
                "aging_item_count": row.aging_item_count,
                "oldest_item_age_days": row.oldest_item_age_days,
                "snapshot_date": str(row.snapshot_date),
            },
        )

    async def get_capacity_snapshot_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        target = as_of or date.today()
        capacity = await _latest_project_row(
            session,
            DeliveryCapacitySnapshot,
            project_id=project_id,
            as_of=target,
        )
        capacity_sev: Decimal | None = None
        evidence: dict[str, object] = {}
        if capacity is not None:
            capacity_sev = capacity_shortage_severity(
                planned_capacity_hours=capacity.planned_capacity_hours,
                available_capacity_hours=capacity.available_capacity_hours,
            )
            evidence["capacity"] = {
                "planned_capacity_hours": float(capacity.planned_capacity_hours),
                "available_capacity_hours": float(capacity.available_capacity_hours),
                "snapshot_date": str(capacity.snapshot_date),
            }

        avail_date = (
            capacity.snapshot_date
            if capacity is not None
            else (
                await session.execute(
                    select(DeliveryTeamAvailabilitySnapshot.snapshot_date)
                    .where(
                        DeliveryTeamAvailabilitySnapshot.project_id == project_id,
                        DeliveryTeamAvailabilitySnapshot.snapshot_date <= target,
                    )
                    .order_by(DeliveryTeamAvailabilitySnapshot.snapshot_date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        )
        avail_sev: Decimal | None = None
        if avail_date is not None:
            avail_rows = (
                (
                    await session.execute(
                        select(DeliveryTeamAvailabilitySnapshot).where(
                            DeliveryTeamAvailabilitySnapshot.project_id == project_id,
                            DeliveryTeamAvailabilitySnapshot.snapshot_date == avail_date,
                        )
                    )
                )
                .scalars()
                .all()
            )
            team_severities: list[Decimal] = []
            for row in avail_rows:
                sev = team_availability_severity(
                    available_headcount=row.available_headcount,
                    planned_headcount=row.planned_headcount,
                )
                if sev is not None:
                    team_severities.append(sev)
            if team_severities:
                avail_sev = quantize_pct(
                    sum(team_severities, Decimal("0")) / Decimal(len(team_severities))
                )
                evidence["team_availability"] = {
                    "team_count": len(avail_rows),
                    "avg_unavailability_pct": float(avail_sev),
                    "snapshot_date": str(avail_date),
                }

        value = combine_max(capacity_sev, avail_sev)
        if value is None:
            return None
        return OperationalSignal(
            value=value,
            source="delivery_capacity_snapshots+team_availability",
            evidence=evidence,
        )

    async def get_dependency_delay_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        # Reserved for a future dependency-graph source; not ingested in 15.2.
        return None

    async def get_scope_volatility_signal(
        self, session: AsyncSession, *, project_id: UUID, as_of: date | None = None
    ) -> OperationalSignal | None:
        # Reserved for scope-change events; not ingested in 15.2.
        return None


async def _latest_project_row(
    session: AsyncSession,
    model: type,
    *,
    project_id: UUID,
    as_of: date,
):
    return (
        await session.execute(
            select(model)
            .where(
                model.project_id == project_id,
                model.snapshot_date <= as_of,
            )
            .order_by(model.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


DEFAULT_OPERATIONAL_SIGNAL_PROVIDER: OperationalSignalProvider = DbOperationalSignalProvider()
