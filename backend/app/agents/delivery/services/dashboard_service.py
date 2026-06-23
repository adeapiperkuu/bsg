"""DB-backed dashboard aggregation for the Delivery Performance Agent."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.scoring_service import build_dashboard_response
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    Bottleneck,
    Milestone,
    Project,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
)
from app.services.scoping import get_visible_project, scoped_project_query


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


async def _list_milestones(session: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Milestone)
        .where(Milestone.project_id == project_id, Milestone.deleted_at.is_(None))
        .order_by(Milestone.planned_date.asc())
    )
    return [_milestone_payload(row) for row in rows.scalars()]


async def _list_throughput(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(ThroughputSnapshot)
        .where(ThroughputSnapshot.project_id == project_id)
        .order_by(ThroughputSnapshot.snapshot_date.desc())
        .limit(limit)
    )
    return [_throughput_payload(row) for row in rows.scalars()]


async def _list_open_risks(session: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(RiskAlert)
        .where(
            RiskAlert.project_id == project_id,
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
        )
        .order_by(RiskAlert.created_at.desc())
    )
    return [_risk_payload(row) for row in rows.scalars()]


async def _list_open_bottlenecks(session: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Bottleneck)
        .where(
            Bottleneck.project_id == project_id,
            Bottleneck.deleted_at.is_(None),
            Bottleneck.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
        )
        .order_by(Bottleneck.created_at.desc())
    )
    return [_bottleneck_payload(row) for row in rows.scalars()]


async def _latest_quality_snapshot(
    session: AsyncSession,
    project_id: UUID,
) -> dict[str, Any] | None:
    row = await session.execute(
        select(QualitySnapshot)
        .where(QualitySnapshot.project_id == project_id)
        .order_by(QualitySnapshot.created_at.desc())
        .limit(1)
    )
    return _quality_payload(row.scalar_one_or_none())


async def get_dashboard_data(
    *,
    session: AsyncSession,
    project_id: UUID,
    current_user: CurrentUser,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Fetch raw delivery data and return the computed dashboard payload."""
    project = await get_visible_project(session, project_id, current_user)
    raw_data = {
        "as_of_date": as_of_date or date.today(),
        "project": _project_payload(project),
        "milestones": await _list_milestones(session, project.id),
        "throughput_snapshots": await _list_throughput(session, project.id),
        "risks": await _list_open_risks(session, project.id),
        "bottlenecks": await _list_open_bottlenecks(session, project.id),
        "quality_snapshot": await _latest_quality_snapshot(session, project.id),
    }
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
    portfolio_projects: list[dict[str, Any]] = []
    all_milestones: list[dict[str, Any]] = []

    for project in projects:
        raw_data = {
            "as_of_date": as_of_date or date.today(),
            "project": _project_payload(project),
            "milestones": await _list_milestones(session, project.id),
            "throughput_snapshots": await _list_throughput(session, project.id),
            "risks": await _list_open_risks(session, project.id),
            "bottlenecks": await _list_open_bottlenecks(session, project.id),
            "quality_snapshot": await _latest_quality_snapshot(session, project.id),
        }
        dashboard = build_dashboard_response(raw_data)
        portfolio_projects.append({"project_id": project.id, "dashboard": dashboard})
        all_milestones.extend(dashboard["milestones"])

    return {"projects": portfolio_projects, "milestones": all_milestones}
