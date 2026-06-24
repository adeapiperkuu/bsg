"""DB-backed dashboard aggregation for the Delivery Performance Agent."""

from dataclasses import dataclass
from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.milestones import select_current_milestone
from app.agents.delivery.services.scoring_service import build_dashboard_response
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    Bottleneck,
    DeliveryConfidenceScore,
    Milestone,
    Project,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
)
from app.services.scoping import get_visible_project, scoped_project_query

THROUGHPUT_HISTORY_LIMIT = 30

# Single authoritative filter for active risk/bottleneck statuses.
OPEN_STATUSES = [AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]


@dataclass(frozen=True, slots=True)
class ProjectScoringInputs:
    """ORM-backed delivery inputs for one scoring run."""

    project: Project
    milestones: list[Milestone]
    raw_data: dict[str, Any]
    open_risk_alerts: list[RiskAlert]
    bottlenecks: list[Bottleneck]
    latest_confidence_by_milestone: dict[UUID, DeliveryConfidenceScore]

    @property
    def current_milestone(self) -> Milestone | None:
        """Return the ORM milestone entity matching the active scoring milestone."""
        current_id = self.raw_data.get("current_milestone_id")
        if current_id is None:
            return None
        for milestone in self.milestones:
            if milestone.id == current_id:
                return milestone
        return None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _project_payload(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "org_id": project.org_id,
        "name": project.name,
        "description": project.description,
        "vertical": project.vertical,
        "status": _enum_value(project.status),
        "start_date": project.start_date,
        "target_end_date": project.target_end_date,
        "actual_end_date": project.actual_end_date,
        "daily_target_units": project.daily_target_units,
    }


def _milestone_payload(milestone: Milestone) -> dict[str, Any]:
    return {
        "id": milestone.id,
        "project_id": milestone.project_id,
        "name": milestone.name,
        "description": milestone.description,
        "planned_date": milestone.planned_date,
        "actual_date": milestone.actual_date,
        "status": _enum_value(milestone.status),
    }


def _throughput_payload(snapshot: ThroughputSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "snapshot_date": snapshot.snapshot_date,
        "units_completed": snapshot.units_completed,
        "units_forecast": snapshot.units_forecast,
        "rolling_7day_units": snapshot.rolling_7day_units,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


def _risk_payload(risk: RiskAlert) -> dict[str, Any]:
    return {
        "id": risk.id,
        "project_id": risk.project_id,
        "milestone_id": risk.milestone_id,
        "alert_type": _enum_value(risk.alert_type),
        "risk_tier": _enum_value(risk.risk_tier),
        "title": risk.title,
        "detail": risk.detail,
        "slippage_probability": risk.slippage_probability,
        "contributing_causes": risk.contributing_causes,
        "status": _enum_value(risk.status),
        "created_at": risk.created_at,
        "updated_at": risk.updated_at,
    }


def _bottleneck_payload(bottleneck: Bottleneck) -> dict[str, Any]:
    return {
        "id": bottleneck.id,
        "project_id": bottleneck.project_id,
        "team_id": bottleneck.team_id,
        "title": bottleneck.title,
        "detail": bottleneck.detail,
        "status": _enum_value(bottleneck.status),
        "created_at": bottleneck.created_at,
        "updated_at": bottleneck.updated_at,
    }


def _quality_payload(snapshot: QualitySnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "has_drift_alert": snapshot.has_drift_alert,
        "rework_rate_pct": snapshot.rework_rate_pct,
    }


def _group_by_project_id(
    payloads: list[dict[str, Any]],
) -> dict[UUID, list[dict[str, Any]]]:
    grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        grouped[payload["project_id"]].append(payload)
    return grouped


def _build_raw_data(
    project: Project,
    *,
    as_of_date: date,
    milestones: list[dict[str, Any]],
    throughput_snapshots: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    bottlenecks: list[dict[str, Any]],
    quality_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the scoring input payload for one project."""
    return {
        "as_of_date": as_of_date,
        "project": _project_payload(project),
        "milestones": milestones,
        "throughput_snapshots": throughput_snapshots,
        "risks": risks,
        "bottlenecks": bottlenecks,
        "quality_snapshot": quality_snapshot,
    }


# ---------------------------------------------------------------------------
# Batch dict-based loaders (used by get_dashboard_data / get_portfolio_data)
# ---------------------------------------------------------------------------

async def _fetch_milestones_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    """Load milestones for many projects in one query."""
    if not project_ids:
        return {}

    rows = await session.execute(
        select(Milestone)
        .where(Milestone.project_id.in_(project_ids), Milestone.deleted_at.is_(None))
        .order_by(Milestone.project_id.asc(), Milestone.planned_date.asc())
    )
    return _group_by_project_id([_milestone_payload(row) for row in rows.scalars()])


async def _fetch_throughput_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
    *,
    limit: int = THROUGHPUT_HISTORY_LIMIT,
) -> dict[UUID, list[dict[str, Any]]]:
    """Load recent throughput snapshots for many projects in one query."""
    if not project_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=ThroughputSnapshot.project_id,
            order_by=ThroughputSnapshot.snapshot_date.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(ThroughputSnapshot.id.label("snapshot_id"), row_number)
        .where(ThroughputSnapshot.project_id.in_(project_ids))
        .subquery()
    )
    rows = await session.execute(
        select(ThroughputSnapshot)
        .join(ranked, ThroughputSnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.row_number <= limit)
        .order_by(
            ThroughputSnapshot.project_id.asc(),
            ThroughputSnapshot.snapshot_date.desc(),
        )
    )
    return _group_by_project_id([_throughput_payload(row) for row in rows.scalars()])


async def _fetch_open_risks_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    """Load open delivery risks for many projects in one query."""
    if not project_ids:
        return {}

    rows = await session.execute(
        select(RiskAlert)
        .where(
            RiskAlert.project_id.in_(project_ids),
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_(OPEN_STATUSES),
        )
        .order_by(RiskAlert.project_id.asc(), RiskAlert.created_at.desc())
    )
    return _group_by_project_id([_risk_payload(row) for row in rows.scalars()])


async def _fetch_open_bottlenecks_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    """Load open bottlenecks for many projects in one query."""
    if not project_ids:
        return {}

    rows = await session.execute(
        select(Bottleneck)
        .where(
            Bottleneck.project_id.in_(project_ids),
            Bottleneck.deleted_at.is_(None),
            Bottleneck.status.in_(OPEN_STATUSES),
        )
        .order_by(Bottleneck.project_id.asc(), Bottleneck.created_at.desc())
    )
    return _group_by_project_id([_bottleneck_payload(row) for row in rows.scalars()])


async def _fetch_latest_quality_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, dict[str, Any] | None]:
    """Load the latest quality snapshot per project in one query."""
    if not project_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=QualitySnapshot.project_id,
            order_by=QualitySnapshot.created_at.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(QualitySnapshot.id.label("snapshot_id"), row_number)
        .where(QualitySnapshot.project_id.in_(project_ids))
        .subquery()
    )
    rows = await session.execute(
        select(QualitySnapshot)
        .join(ranked, QualitySnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.row_number == 1)
    )
    latest: dict[UUID, dict[str, Any] | None] = {project_id: None for project_id in project_ids}
    for snapshot in rows.scalars():
        latest[snapshot.project_id] = _quality_payload(snapshot)
    return latest


async def _fetch_delivery_inputs_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[str, Any]:
    """Batch-load all delivery dashboard inputs grouped by project."""
    milestones, throughput, risks, bottlenecks, quality = await _gather_delivery_queries(
        session,
        project_ids,
    )
    return {
        "milestones": milestones,
        "throughput_snapshots": throughput,
        "risks": risks,
        "bottlenecks": bottlenecks,
        "quality_snapshots": quality,
    }


async def _gather_delivery_queries(
    session: AsyncSession,
    project_ids: list[UUID],
) -> tuple[
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, dict[str, Any] | None],
]:
    """Run the five delivery dashboard queries without N+1 fan-out."""
    milestones = await _fetch_milestones_by_project(session, project_ids)
    throughput = await _fetch_throughput_by_project(session, project_ids)
    risks = await _fetch_open_risks_by_project(session, project_ids)
    bottlenecks = await _fetch_open_bottlenecks_by_project(session, project_ids)
    quality = await _fetch_latest_quality_by_project(session, project_ids)
    return milestones, throughput, risks, bottlenecks, quality


# ---------------------------------------------------------------------------
# ORM loaders (used only by load_project_scoring_inputs / scoring path)
# ---------------------------------------------------------------------------

async def _fetch_orm_milestones(
    session: AsyncSession,
    project_id: UUID,
) -> list[Milestone]:
    rows = await session.execute(
        select(Milestone)
        .where(Milestone.project_id == project_id, Milestone.deleted_at.is_(None))
        .order_by(Milestone.planned_date.asc())
    )
    return list(rows.scalars())


async def _fetch_orm_open_risks(
    session: AsyncSession,
    project_id: UUID,
) -> list[RiskAlert]:
    rows = await session.execute(
        select(RiskAlert)
        .where(
            RiskAlert.project_id == project_id,
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_(OPEN_STATUSES),
        )
        .order_by(RiskAlert.created_at.desc())
    )
    return list(rows.scalars())


async def _fetch_orm_open_bottlenecks(
    session: AsyncSession,
    project_id: UUID,
) -> list[Bottleneck]:
    rows = await session.execute(
        select(Bottleneck)
        .where(
            Bottleneck.project_id == project_id,
            Bottleneck.deleted_at.is_(None),
            Bottleneck.status.in_(OPEN_STATUSES),
        )
        .order_by(Bottleneck.created_at.desc())
    )
    return list(rows.scalars())


async def _fetch_latest_confidence_by_milestone(
    session: AsyncSession,
    project_id: UUID,
) -> dict[UUID, DeliveryConfidenceScore]:
    """Load the latest confidence score row for each milestone in one query."""
    row_number = (
        func.row_number()
        .over(
            partition_by=DeliveryConfidenceScore.milestone_id,
            order_by=DeliveryConfidenceScore.created_at.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(DeliveryConfidenceScore.id.label("score_id"), row_number)
        .where(DeliveryConfidenceScore.project_id == project_id)
        .subquery()
    )
    rows = await session.execute(
        select(DeliveryConfidenceScore)
        .join(ranked, DeliveryConfidenceScore.id == ranked.c.score_id)
        .where(ranked.c.row_number == 1)
    )
    return {score.milestone_id: score for score in rows.scalars()}


# ---------------------------------------------------------------------------
# Scoring input loader (scoring path only — ORM + raw_data in one shot)
# ---------------------------------------------------------------------------

async def load_project_scoring_inputs(
    session: AsyncSession,
    project: Project,
    *,
    as_of_date: date | None = None,
) -> ProjectScoringInputs:
    """Load ORM entities and scoring raw_data for one project without duplicate queries."""
    effective_date = as_of_date or date.today()

    milestones = await _fetch_orm_milestones(session, project.id)
    throughput_map = await _fetch_throughput_by_project(session, [project.id])
    quality_map = await _fetch_latest_quality_by_project(session, [project.id])
    open_risk_alerts = await _fetch_orm_open_risks(session, project.id)
    bottlenecks = await _fetch_orm_open_bottlenecks(session, project.id)
    latest_confidence_by_milestone = await _fetch_latest_confidence_by_milestone(
        session, project.id
    )

    milestone_payloads = [_milestone_payload(m) for m in milestones]
    current_milestone = select_current_milestone(milestone_payloads, as_of_date=effective_date)

    raw_data = _build_raw_data(
        project,
        as_of_date=effective_date,
        milestones=milestone_payloads,
        throughput_snapshots=throughput_map.get(project.id, []),
        risks=[_risk_payload(alert) for alert in open_risk_alerts],
        bottlenecks=[_bottleneck_payload(b) for b in bottlenecks],
        quality_snapshot=quality_map.get(project.id),
    )
    raw_data["current_milestone_id"] = current_milestone["id"] if current_milestone is not None else None

    return ProjectScoringInputs(
        project=project,
        milestones=milestones,
        raw_data=raw_data,
        open_risk_alerts=open_risk_alerts,
        bottlenecks=bottlenecks,
        latest_confidence_by_milestone=latest_confidence_by_milestone,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_dashboard_data(
    *,
    session: AsyncSession,
    project_id: UUID,
    current_user: CurrentUser,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Fetch raw delivery data and return the computed dashboard payload."""
    project = await get_visible_project(session, project_id, current_user)
    effective_date = as_of_date or date.today()
    inputs = await _fetch_delivery_inputs_by_project(session, [project.id])
    raw_data = _build_raw_data(
        project,
        as_of_date=effective_date,
        milestones=inputs["milestones"].get(project.id, []),
        throughput_snapshots=inputs["throughput_snapshots"].get(project.id, []),
        risks=inputs["risks"].get(project.id, []),
        bottlenecks=inputs["bottlenecks"].get(project.id, []),
        quality_snapshot=inputs["quality_snapshots"].get(project.id),
    )
    return build_dashboard_response(raw_data)


async def get_portfolio_data(
    *,
    session: AsyncSession,
    current_user: CurrentUser,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Return delivery dashboard summaries for every visible project in one payload."""
    project_rows = (
        await session.execute(scoped_project_query(current_user).order_by(Project.name.asc()))
    ).scalars()
    projects = list(project_rows)
    if not projects:
        return {"projects": [], "milestones": []}

    effective_date = as_of_date or date.today()
    project_ids = [project.id for project in projects]
    inputs = await _fetch_delivery_inputs_by_project(session, project_ids)

    portfolio_projects: list[dict[str, Any]] = []
    all_milestones: list[dict[str, Any]] = []

    for project in projects:
        raw_data = _build_raw_data(
            project,
            as_of_date=effective_date,
            milestones=inputs["milestones"].get(project.id, []),
            throughput_snapshots=inputs["throughput_snapshots"].get(project.id, []),
            risks=inputs["risks"].get(project.id, []),
            bottlenecks=inputs["bottlenecks"].get(project.id, []),
            quality_snapshot=inputs["quality_snapshots"].get(project.id),
        )
        dashboard = build_dashboard_response(raw_data)
        portfolio_projects.append({"project_id": project.id, "dashboard": dashboard})
        all_milestones.extend(dashboard["milestones"])

    return {"projects": portfolio_projects, "milestones": all_milestones}
