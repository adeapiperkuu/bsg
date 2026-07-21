"""Phase 15.4 — AI daily operational briefing assembly."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.ai.summary_service import generate_daily_summary
from app.agents.delivery.analytics.operational_briefing import build_operational_briefing
from app.agents.delivery.configuration import (
    DEFAULT_DELIVERY_SCORING_THRESHOLDS,
    load_delivery_scoring_thresholds,
)
from app.agents.delivery.services.dashboard_service import get_dashboard_data
from app.agents.delivery.services.delivery_knowledge_evidence_service import (
    retrieve_delivery_knowledge_evidence_for_dashboard,
)
from app.agents.delivery.services.delivery_root_cause_service import get_project_root_causes
from app.agents.delivery.services.pm_daily_action_service import list_daily_actions
from app.core.security import CurrentUser
from app.db.models import AppRole, DeliveryConfidenceScore, ThroughputSnapshot

logger = logging.getLogger(__name__)


async def build_project_operational_briefing(
    session: AsyncSession,
    *,
    project_id: UUID,
    current_user: CurrentUser,
    as_of: date | None = None,
    with_ai: bool = True,
    dashboard_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build grounded operational briefing for one project.

    Deterministic sections always present. Optional AI narrative is fail-open.
    Clients receive a high-level briefing without root-cause factor detail or PM actions.
    """
    target = as_of or date.today()
    client_mode = current_user.role == AppRole.CLIENT

    dashboard = dashboard_data or await get_dashboard_data(
        session=session,
        project_id=project_id,
        current_user=current_user,
        as_of_date=target,
    )

    root_payload = await get_project_root_causes(
        session,
        project_id=project_id,
        as_of=target,
        current_user=current_user,
    )
    root_summary = None if client_mode else root_payload.get("root_cause_summary")

    pm_actions: list[dict[str, Any]] = []
    if not client_mode:
        actions_payload = await list_daily_actions(
            session,
            project_id=project_id,
            plan_date=target,
            include_history=False,
        )
        pm_actions = list(actions_payload.get("todays_focus") or [])

    previous_confidence = await _previous_confidence_score(
        session, project_id=project_id, as_of=target
    )
    latest_throughput, previous_throughput = await _throughput_pair(
        session, project_id=project_id
    )

    org_id = _project_org_id(dashboard)
    thresholds = (
        await load_delivery_scoring_thresholds(session, org_id)
        if org_id is not None
        else DEFAULT_DELIVERY_SCORING_THRESHOLDS
    )

    overview = dashboard.get("overview") or {}
    project = overview.get("project") or {}
    if latest_throughput is None:
        latest_throughput = overview.get("latest_throughput")

    briefing = build_operational_briefing(
        as_of_date=target,
        traffic_light=str(dashboard.get("traffic_light") or "yellow"),
        confidence=float(dashboard.get("confidence") or 0),
        previous_confidence=previous_confidence,
        has_sufficient_data=bool(overview.get("has_sufficient_data", True)),
        latest_throughput=latest_throughput,
        previous_throughput=previous_throughput,
        daily_target_units=project.get("daily_target_units"),
        milestones=list(dashboard.get("milestones") or []),
        risks=list(dashboard.get("risks") or []),
        bottlenecks=list(dashboard.get("bottlenecks") or []),
        root_cause_summary=root_summary if isinstance(root_summary, dict) else None,
        pm_actions=[] if client_mode else pm_actions,
        milestone_warning_window_days=int(thresholds.risk.milestone_warning_window_days),
    )

    if client_mode:
        briefing["recommended_pm_actions"] = []
        briefing["root_cause_summary"] = None
        # Keep high-level drivers only (no factor keys / explanations with ops detail).
        movement = briefing.get("confidence_movement") or {}
        movement["drivers"] = []
        briefing["confidence_movement"] = movement
        briefing["knowledge_evidence"] = []
    else:
        knowledge = await retrieve_delivery_knowledge_evidence_for_dashboard(
            session,
            current_user,
            project_id=project_id,
            dashboard=dashboard,
            root_cause_summary=root_summary if isinstance(root_summary, dict) else None,
        )
        briefing["knowledge_evidence"] = list(knowledge.get("citations") or [])

    if with_ai and not client_mode:
        ai_context = {
            **dashboard,
            "root_cause_summary": root_summary,
            "operational_briefing": {
                "overnight_changes": briefing["overnight_changes"],
                "confidence_movement": briefing["confidence_movement"],
                "new_risks": briefing["new_risks"],
                "top_priorities": briefing["top_priorities"],
                "milestones_due_soon": briefing["milestones_due_soon"],
                "recommended_pm_actions": briefing["recommended_pm_actions"],
                "knowledge_evidence": briefing.get("knowledge_evidence") or [],
            },
            "pm_actions": pm_actions[:5],
            "knowledge_evidence": briefing.get("knowledge_evidence") or [],
        }
        try:
            narrative = await generate_daily_summary(ai_context)
        except Exception:
            logger.exception(
                "event=operational_briefing_ai_failed project_id=%s", project_id
            )
            narrative = None
        if narrative:
            briefing["narrative"] = narrative
            briefing["ai_generated"] = True

    return briefing


async def attach_operational_briefing_to_dashboard(
    session: AsyncSession,
    *,
    project_id: UUID,
    current_user: CurrentUser,
    dashboard_data: dict[str, Any],
    with_ai: bool = True,
) -> dict[str, Any]:
    """Mutate dashboard payload with operational_briefing + daily_summary narrative."""
    briefing = await build_project_operational_briefing(
        session,
        project_id=project_id,
        current_user=current_user,
        with_ai=with_ai,
        dashboard_data=dashboard_data,
    )
    dashboard_data["operational_briefing"] = briefing
    dashboard_data["daily_summary"] = briefing.get("narrative")
    return dashboard_data


async def _previous_confidence_score(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of: date,
) -> float | None:
    """Second-most-recent stored confidence on or before as_of (for movement delta)."""
    rows = (
        (
            await session.execute(
                select(DeliveryConfidenceScore.score_pct)
                .where(DeliveryConfidenceScore.project_id == project_id)
                .order_by(DeliveryConfidenceScore.created_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    _ = as_of
    if len(rows) < 2:
        return None
    return float(rows[1])


async def _throughput_pair(
    session: AsyncSession,
    *,
    project_id: UUID,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    rows = (
        (
            await session.execute(
                select(ThroughputSnapshot)
                .where(ThroughputSnapshot.project_id == project_id)
                .order_by(ThroughputSnapshot.snapshot_date.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None, None

    def _payload(row: ThroughputSnapshot) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "snapshot_date": row.snapshot_date,
            "units_completed": row.units_completed,
            "units_forecast": row.units_forecast,
            "rolling_7day_units": row.rolling_7day_units,
        }

    latest = _payload(rows[0])
    previous = _payload(rows[1]) if len(rows) > 1 else None
    return latest, previous


def _project_org_id(dashboard: dict[str, Any]) -> UUID | None:
    overview = dashboard.get("overview") or {}
    project = overview.get("project") or {}
    org_id = project.get("org_id")
    if org_id is None:
        return None
    return org_id if isinstance(org_id, UUID) else UUID(str(org_id))
