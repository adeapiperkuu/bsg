"""Lightweight delivery signals for governance analytics (no full portfolio payload)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.dashboard_service import (
    OPEN_STATUSES,
    _build_raw_data,
    _fetch_latest_quality_by_project,
    _fetch_throughput_by_project,
    _milestone_payload,
)
from app.agents.delivery.services.scoring_service import ScoringContext, compute_delivery_scores
from app.agents.governance.services.governance_service import can_read_internal_governance
from app.core.security import CurrentUser
from app.db.models import AppRole, Bottleneck, Milestone, MilestoneStatus, Project, RiskAlert


GOVERNANCE_THROUGHPUT_LIMIT = 7


def _governance_delivery_signal_payload(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Shape compatible with analytics _score_project_from_metrics(delivery_signal=...)."""
    context = ScoringContext.from_raw_data(raw_data)
    scores = compute_delivery_scores(context)
    return {
        "dashboard": {
            "confidence": float(scores.confidence),
            "traffic_light": scores.traffic_light,
            "overview": {
                "quality_snapshot": raw_data.get("quality_snapshot"),
                "calculated_risk": {
                    "score": float(scores.risk),
                    "tier": scores.risk_tier,
                },
                "has_sufficient_data": scores.has_sufficient_data,
            },
        }
    }


async def _filter_accessible_project_ids(
    session: AsyncSession,
    current_user: CurrentUser,
    project_ids: list[UUID],
) -> list[UUID]:
    if not project_ids:
        return []
    stmt = select(Project.id).where(Project.id.in_(project_ids))
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(Project.org_id == current_user.org_id)
    allowed = set((await session.execute(stmt)).scalars())
    return [project_id for project_id in project_ids if project_id in allowed]


async def _fetch_active_milestones_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    if not project_ids:
        return {}
    rows = await session.execute(
        select(Milestone).where(
            Milestone.project_id.in_(project_ids),
            Milestone.deleted_at.is_(None),
            Milestone.actual_date.is_(None),
            Milestone.status != MilestoneStatus.COMPLETED,
        )
    )
    grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for milestone in rows.scalars():
        grouped[milestone.project_id].append(_milestone_payload(milestone))
    for project_id in project_ids:
        grouped.setdefault(project_id, [])
    return grouped


async def _fetch_open_risk_tiers_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    if not project_ids:
        return {}
    rows = await session.execute(
        select(RiskAlert.project_id, RiskAlert.risk_tier).where(
            RiskAlert.project_id.in_(project_ids),
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_(OPEN_STATUSES),
        )
    )
    grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for project_id, risk_tier in rows.all():
        grouped[project_id].append(
            {"project_id": project_id, "risk_tier": str(getattr(risk_tier, "value", risk_tier))}
        )
    for project_id in project_ids:
        grouped.setdefault(project_id, [])
    return grouped


async def _fetch_open_bottleneck_stubs_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    """Return minimal bottleneck rows so scoring can count open bottlenecks."""
    if not project_ids:
        return {}
    rows = await session.execute(
        select(Bottleneck.project_id, func.count().label("open_count"))
        .where(
            Bottleneck.project_id.in_(project_ids),
            Bottleneck.deleted_at.is_(None),
            Bottleneck.status.in_(OPEN_STATUSES),
        )
        .group_by(Bottleneck.project_id)
    )
    grouped: dict[UUID, list[dict[str, Any]]] = {
        project_id: [] for project_id in project_ids
    }
    for row in rows.all():
        grouped[row.project_id] = [{"project_id": row.project_id}] * int(row.open_count or 0)
    return grouped


async def fetch_governance_delivery_signals(
    session: AsyncSession,
    current_user: CurrentUser,
    project_ids: list[UUID],
    *,
    projects_by_id: dict[UUID, Project] | None = None,
    as_of_date: date | None = None,
) -> dict[UUID, dict[str, Any]]:
    """Load only the delivery fields governance scoring needs, keyed by project_id."""
    if not project_ids or not can_read_internal_governance(current_user):
        return {}
    if current_user.role == AppRole.CLIENT:
        return {}

    effective_date = as_of_date or date.today()
    accessible_ids = await _filter_accessible_project_ids(session, current_user, project_ids)
    if not accessible_ids:
        return {}

    missing_ids = [
        project_id
        for project_id in accessible_ids
        if projects_by_id is None or project_id not in projects_by_id
    ]
    if missing_ids:
        rows = await session.execute(select(Project).where(Project.id.in_(missing_ids)))
        loaded = {project.id: project for project in rows.scalars()}
        projects_by_id = {**(projects_by_id or {}), **loaded}

    throughput, quality, milestones, risks, bottlenecks = await _gather_governance_signal_inputs(
        session,
        accessible_ids,
    )

    signals: dict[UUID, dict[str, Any]] = {}
    for project_id in accessible_ids:
        project = (projects_by_id or {}).get(project_id)
        if project is None:
            continue
        raw_data = _build_raw_data(
            project,
            as_of_date=effective_date,
            milestones=milestones.get(project_id, []),
            throughput_snapshots=throughput.get(project_id, []),
            risks=risks.get(project_id, []),
            bottlenecks=bottlenecks.get(project_id, []),
            quality_snapshot=quality.get(project_id),
        )
        signals[project_id] = _governance_delivery_signal_payload(raw_data)
    return signals


async def _gather_governance_signal_inputs(
    session: AsyncSession,
    project_ids: list[UUID],
) -> tuple[
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, dict[str, Any] | None],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
]:
    throughput = await _fetch_throughput_by_project(
        session,
        project_ids,
        limit=GOVERNANCE_THROUGHPUT_LIMIT,
    )
    quality = await _fetch_latest_quality_by_project(session, project_ids)
    milestones = await _fetch_active_milestones_by_project(session, project_ids)
    risks = await _fetch_open_risk_tiers_by_project(session, project_ids)
    bottlenecks = await _fetch_open_bottleneck_stubs_by_project(session, project_ids)
    return throughput, quality, milestones, risks, bottlenecks
