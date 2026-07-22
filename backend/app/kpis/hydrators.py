"""Scope-aware input hydrators for KPI evaluation from source snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GovernanceAction,
    GovernanceEscalation,
    Project,
    QualitySnapshot,
    ThroughputSnapshot,
    WorkforceUtilizationSnapshot,
)


async def hydrate_kpi_inputs(
    session: AsyncSession,
    *,
    kpi_key: str,
    org_id: UUID | None,
    project_id: UUID | None,
    as_of: datetime | None = None,
    existing_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load calculator inputs from source facts when not already supplied."""
    inputs = dict(existing_inputs or {})
    if as_of is None:
        as_of = datetime.now(UTC)

    if kpi_key.startswith("delivery.") and project_id is not None:
        await _hydrate_delivery(session, project_id=project_id, as_of=as_of, inputs=inputs)
    elif kpi_key.startswith("quality.") and project_id is not None:
        await _hydrate_quality(session, project_id=project_id, as_of=as_of, inputs=inputs)
    elif kpi_key == "workforce.avg_utilization" and org_id is not None:
        await _hydrate_workforce(session, org_id=org_id, as_of=as_of, inputs=inputs)
    elif kpi_key.startswith("governance.") and org_id is not None:
        await _hydrate_governance(session, org_id=org_id, as_of=as_of, inputs=inputs)
    elif kpi_key.startswith("tower.") and org_id is not None:
        await _hydrate_tower(session, org_id=org_id, as_of=as_of, inputs=inputs)
    elif kpi_key.startswith("client.") and project_id is not None:
        inputs.setdefault("has_evidence", True)
        inputs.setdefault("has_score", "has_score" in inputs)
    return inputs


async def resolve_department_key(
    session: AsyncSession,
    project_id: UUID | None,
) -> str | None:
    if project_id is None:
        return None
    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    return None if project is None else project.vertical


async def _hydrate_delivery(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of: datetime,
    inputs: dict[str, Any],
) -> None:
    if "rolling_7day_units" not in inputs or "daily_target_units" not in inputs:
        project = (
            await session.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
        if project is not None and "daily_target_units" not in inputs:
            inputs["daily_target_units"] = project.daily_target_units
        snaps = list(
            (
                await session.execute(
                    select(ThroughputSnapshot)
                    .where(
                        ThroughputSnapshot.project_id == project_id,
                        ThroughputSnapshot.snapshot_date <= as_of.date(),
                    )
                    .order_by(ThroughputSnapshot.snapshot_date.desc())
                    .limit(14)
                )
            ).scalars()
        )
        if snaps and "rolling_7day_units" not in inputs:
            inputs["rolling_7day_units"] = snaps[0].rolling_7day_units
        if snaps and "rolling_windows" not in inputs:
            windows = [s.rolling_7day_units for s in reversed(snaps[:7])]
            inputs["rolling_windows"] = windows
    if "confidence_score_pct" not in inputs and "rolling_7day_units" in inputs:
        # Leave confidence to the calculator; risk/traffic light may receive it later.
        pass


async def _hydrate_quality(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of: datetime,
    inputs: dict[str, Any],
) -> None:
    snaps = list(
        (
            await session.execute(
                select(QualitySnapshot)
                .where(
                    QualitySnapshot.project_id == project_id,
                    QualitySnapshot.created_at <= as_of,
                )
                .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            )
        ).scalars()
    )
    latest_by_team: dict[UUID, QualitySnapshot] = {}
    for snap in snaps:
        if snap.team_id not in latest_by_team:
            latest_by_team[snap.team_id] = snap
    latest = list(latest_by_team.values())
    inputs.setdefault(
        "gold_set_accuracy_pct_values",
        [s.gold_set_accuracy_pct for s in latest],
    )
    inputs.setdefault(
        "iaa_krippendorff_alpha_values",
        [s.iaa_krippendorff_alpha for s in latest],
    )
    inputs.setdefault(
        "rework_rate_pct_values",
        [s.rework_rate_pct for s in latest],
    )
    inputs.setdefault(
        "has_drift_alert_flags",
        [bool(s.has_drift_alert) for s in latest],
    )


async def _hydrate_workforce(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of: datetime,
    inputs: dict[str, Any],
) -> None:
    snaps = list(
        (
            await session.execute(
                select(WorkforceUtilizationSnapshot)
                .where(
                    WorkforceUtilizationSnapshot.org_id == org_id,
                    WorkforceUtilizationSnapshot.created_at <= as_of,
                )
                .order_by(
                    WorkforceUtilizationSnapshot.iso_year.desc(),
                    WorkforceUtilizationSnapshot.iso_week.desc(),
                )
            )
        ).scalars()
    )
    latest_by_team: dict[UUID, WorkforceUtilizationSnapshot] = {}
    for snap in snaps:
        if snap.team_id not in latest_by_team:
            latest_by_team[snap.team_id] = snap
    inputs.setdefault(
        "utilization_pct_values",
        [s.utilization_pct for s in latest_by_team.values()],
    )


async def _hydrate_governance(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of: datetime,
    inputs: dict[str, Any],
) -> None:
    actions = list(
        (
            await session.execute(
                select(GovernanceAction).where(
                    GovernanceAction.org_id == org_id,
                    GovernanceAction.deleted_at.is_(None),
                    GovernanceAction.created_at <= as_of,
                )
            )
        ).scalars()
    )
    escalations = list(
        (
            await session.execute(
                select(GovernanceEscalation).where(
                    GovernanceEscalation.org_id == org_id,
                    GovernanceEscalation.deleted_at.is_(None),
                    GovernanceEscalation.created_at <= as_of,
                )
            )
        ).scalars()
    )
    inputs.setdefault("actions", actions)
    inputs.setdefault("escalations", escalations)
    inputs.setdefault("today", as_of.date())


async def _hydrate_tower(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of: datetime,
    inputs: dict[str, Any],
) -> None:
    # Tower composites prefer already-computed project values when provided.
    if "confidence_pct_values" not in inputs:
        projects = list(
            (
                await session.execute(
                    select(Project).where(
                        Project.org_id == org_id,
                        Project.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        # Without delivery confidence scores in hydrator scope, leave empty for no_data.
        inputs.setdefault("confidence_pct_values", [])
        inputs.setdefault("project_count", len(projects))
    if "gold_set_accuracy_pct_values" not in inputs:
        snaps = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(
                        QualitySnapshot.org_id == org_id,
                        QualitySnapshot.created_at <= as_of,
                    )
                    .order_by(QualitySnapshot.created_at.desc())
                    .limit(200)
                )
            ).scalars()
        )
        values = [
            None if s.gold_set_accuracy_pct is None else float(s.gold_set_accuracy_pct)
            for s in snaps
        ]
        inputs.setdefault("gold_set_accuracy_pct_values", values)
