"""Lightweight delivery signals for governance analytics (no full portfolio payload)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.dashboard_service import (
    OPEN_STATUSES,
    _build_raw_data,
    _milestone_payload,
)
from app.agents.delivery.services.scoring_service import ScoringContext, compute_delivery_scores
from app.agents.governance.services.governance_service import can_read_internal_governance
from app.core.security import CurrentUser
from app.db.models import AppRole, Bottleneck, Milestone, MilestoneStatus, Project, RiskAlert

GOVERNANCE_THROUGHPUT_LIMIT = 7
_OPEN_STATUS_LITERALS = ", ".join(f"'{status.value}'" for status in OPEN_STATUSES)

GOVERNANCE_SIGNAL_BUNDLE_SQL = text(
    f"""
    SELECT kind, project_id, payload
    FROM (
        SELECT 'throughput'::text AS kind,
               tr.project_id,
               jsonb_build_object(
                   'id', tr.id,
                   'project_id', tr.project_id,
                   'snapshot_date', tr.snapshot_date,
                   'units_completed', tr.units_completed,
                   'units_forecast', tr.units_forecast,
                   'rolling_7day_units', tr.rolling_7day_units,
                   'created_at', tr.created_at,
                   'updated_at', tr.updated_at
               ) AS payload
        FROM (
            SELECT ts.*,
                   row_number() OVER (
                       PARTITION BY ts.project_id ORDER BY ts.snapshot_date DESC
                   ) AS rn
            FROM throughput_snapshots ts
            WHERE ts.project_id = ANY(:project_ids)
        ) tr
        WHERE tr.rn <= :throughput_limit

        UNION ALL

        SELECT 'quality'::text,
               qr.project_id,
               jsonb_build_object(
                   'has_drift_alert', qr.has_drift_alert,
                   'rework_rate_pct', qr.rework_rate_pct
               )
        FROM (
            SELECT q.project_id,
                   q.has_drift_alert,
                   q.rework_rate_pct,
                   row_number() OVER (
                       PARTITION BY q.project_id ORDER BY q.created_at DESC
                   ) AS rn
            FROM quality_snapshots q
            WHERE q.project_id = ANY(:project_ids)
        ) qr
        WHERE qr.rn = 1

        UNION ALL

        SELECT 'milestone'::text,
               m.project_id,
               jsonb_build_object(
                   'id', m.id,
                   'project_id', m.project_id,
                   'name', m.name,
                   'description', m.description,
                   'planned_date', m.planned_date,
                   'actual_date', m.actual_date,
                   'status', m.status
               )
        FROM milestones m
        WHERE m.project_id = ANY(:project_ids)
          AND m.deleted_at IS NULL
          AND m.actual_date IS NULL
          AND m.status != 'completed'

        UNION ALL

        SELECT 'risk'::text,
               r.project_id,
               jsonb_build_object(
                   'project_id', r.project_id,
                   'risk_tier', r.risk_tier
               )
        FROM risk_alerts r
        WHERE r.project_id = ANY(:project_ids)
          AND r.deleted_at IS NULL
          AND r.status IN ({_OPEN_STATUS_LITERALS})

        UNION ALL

        SELECT 'bottleneck'::text,
               b.project_id,
               jsonb_build_object('open_count', count(*)::int)
        FROM bottlenecks b
        WHERE b.project_id = ANY(:project_ids)
          AND b.deleted_at IS NULL
          AND b.status IN ({_OPEN_STATUS_LITERALS})
        GROUP BY b.project_id
    ) bundle
    """
).bindparams(
    bindparam("project_ids", type_=ARRAY(PG_UUID())),
    bindparam("throughput_limit"),
)


def _coerce_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return None


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    return None


def _normalize_throughput_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["snapshot_date"] = _coerce_date(payload.get("snapshot_date"))
    normalized["created_at"] = _coerce_datetime(payload.get("created_at"))
    normalized["updated_at"] = _coerce_datetime(payload.get("updated_at"))
    return normalized


def _normalize_milestone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["planned_date"] = _coerce_date(payload.get("planned_date"))
    normalized["actual_date"] = _coerce_date(payload.get("actual_date"))
    normalized["status"] = str(payload.get("status"))
    return normalized


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


def _parse_governance_signal_bundle_rows(
    rows: list[tuple[str, UUID, dict[str, Any]]],
    project_ids: list[UUID],
) -> tuple[
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, dict[str, Any] | None],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
]:
    throughput: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    quality: dict[UUID, dict[str, Any] | None] = {project_id: None for project_id in project_ids}
    milestones: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    risks: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    bottlenecks: dict[UUID, list[dict[str, Any]]] = {project_id: [] for project_id in project_ids}

    for kind, project_id, payload in rows:
        if kind == "throughput":
            throughput[project_id].append(_normalize_throughput_payload(dict(payload)))
        elif kind == "quality":
            quality[project_id] = dict(payload)
        elif kind == "milestone":
            milestones[project_id].append(_normalize_milestone_payload(dict(payload)))
        elif kind == "risk":
            risk_payload = dict(payload)
            risk_payload["risk_tier"] = str(risk_payload.get("risk_tier"))
            risks[project_id].append(risk_payload)
        elif kind == "bottleneck":
            open_count = int(payload.get("open_count") or 0)
            bottlenecks[project_id] = [{"project_id": project_id}] * open_count

    for project_id in project_ids:
        throughput.setdefault(project_id, [])
        milestones.setdefault(project_id, [])
        risks.setdefault(project_id, [])

    return throughput, quality, milestones, risks, bottlenecks


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
    if projects_by_id and all(project_id in projects_by_id for project_id in project_ids):
        accessible_ids = project_ids
    else:
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
    return build_governance_delivery_signals_from_inputs(
        current_user,
        accessible_ids,
        projects_by_id or {},
        throughput=throughput,
        quality=quality,
        milestones=milestones,
        risks=risks,
        bottlenecks=bottlenecks,
        as_of_date=effective_date,
    )


def build_governance_delivery_signals_from_inputs(
    current_user: CurrentUser,
    project_ids: list[UUID],
    projects_by_id: dict[UUID, Project],
    *,
    throughput: dict[UUID, list[dict[str, Any]]],
    quality: dict[UUID, dict[str, Any] | None],
    milestones: dict[UUID, list[dict[str, Any]]],
    risks: dict[UUID, list[dict[str, Any]]],
    bottlenecks: dict[UUID, list[dict[str, Any]]],
    as_of_date: date | None = None,
) -> dict[UUID, dict[str, Any]]:
    if not project_ids or not can_read_internal_governance(current_user):
        return {}
    if current_user.role == AppRole.CLIENT:
        return {}

    effective_date = as_of_date or date.today()
    signals: dict[UUID, dict[str, Any]] = {}
    for project_id in project_ids:
        project = projects_by_id.get(project_id)
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
    """Load all delivery scoring inputs in one DB round trip."""
    if not project_ids:
        return {}, {}, {}, {}, {}

    rows = (
        await session.execute(
            GOVERNANCE_SIGNAL_BUNDLE_SQL,
            {
                "project_ids": project_ids,
                "throughput_limit": GOVERNANCE_THROUGHPUT_LIMIT,
            },
        )
    ).all()
    return _parse_governance_signal_bundle_rows(rows, project_ids)
