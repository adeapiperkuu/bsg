"""PM Daily Action Planner — generate, list, complete, history."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.pm_actions import (
    MODEL_VERSION,
    build_candidates_from_bottlenecks,
    build_candidates_from_milestones,
    build_candidates_from_mitigations,
    build_candidates_from_root_causes,
    rank_daily_actions,
)
from app.agents.delivery.ai.pm_action_rationale import generate_action_rationale
from app.agents.delivery.services.dashboard_service import (
    clear_delivery_portfolio_cache,
    load_project_scoring_inputs,
)
from app.agents.delivery.services.delivery_root_cause_service import (
    get_project_root_causes,
    recalculate_root_causes,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    DeliveryPmDailyAction,
    MitigationRecommendation,
    PmDailyActionSourceType,
    PmDailyActionStatus,
    PmDailyActionUrgency,
    Project,
    RecommendationStatus,
)

logger = logging.getLogger(__name__)

OPEN_BOTTLENECK = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)


async def generate_daily_actions(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    plan_date: date | None = None,
    with_ai_rationale: bool = False,
    limit: int = 8,
) -> list[DeliveryPmDailyAction]:
    """Build today's ranked focus list from root causes, bottlenecks, mitigations, milestones."""
    as_of = plan_date or date.today()
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise ValueError(f"Project {project_id} not found")

    # Ensure a same-day root-cause snapshot exists when possible.
    try:
        await recalculate_root_causes(
            session, project_id=project_id, org_id=org_id, snapshot_date=as_of
        )
    except Exception:
        logger.exception(
            "event=pm_daily_actions_root_cause_refresh_failed project_id=%s", project_id
        )

    root = await get_project_root_causes(
        session, project_id=project_id, as_of=as_of, history_days=1
    )
    factors = list((root.get("latest") or {}).get("factors") or [])

    inputs = await load_project_scoring_inputs(session, project, as_of_date=as_of)
    bottlenecks = [
        {
            "id": str(b.id),
            "title": b.title,
            "detail": b.detail,
            "severity": b.severity.value if hasattr(b.severity, "value") else str(b.severity),
            "source_key": getattr(b, "source_key", None),
        }
        for b in inputs.bottlenecks
    ]
    mitigations = await _pending_mitigations(session, project_id=project_id)
    overdue = _overdue_count(inputs.raw_data.get("milestones") or [], as_of)
    days_until = None
    current = inputs.raw_data.get("current_milestone_id")
    for milestone in inputs.raw_data.get("milestones") or []:
        if milestone.get("id") == current and milestone.get("planned_date"):
            planned = milestone["planned_date"]
            if not isinstance(planned, date):
                planned = date.fromisoformat(str(planned))
            days_until = (planned - as_of).days
            break

    candidates = []
    candidates.extend(build_candidates_from_root_causes(plan_date=as_of, factors=factors))
    candidates.extend(build_candidates_from_bottlenecks(plan_date=as_of, bottlenecks=bottlenecks))
    candidates.extend(build_candidates_from_mitigations(plan_date=as_of, mitigations=mitigations))
    candidates.extend(
        build_candidates_from_milestones(
            plan_date=as_of,
            overdue_count=overdue,
            days_until_milestone=days_until,
        )
    )
    ranked = rank_daily_actions(candidates, limit=limit)
    now = datetime.now(UTC)

    # Soft-delete open todos for this day that are no longer in the ranked set.
    keep_keys = {item.source_key for item in ranked}
    existing_todos = (
        (
            await session.execute(
                select(DeliveryPmDailyAction).where(
                    DeliveryPmDailyAction.project_id == project_id,
                    DeliveryPmDailyAction.plan_date == as_of,
                    DeliveryPmDailyAction.deleted_at.is_(None),
                    DeliveryPmDailyAction.status == PmDailyActionStatus.TODO,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing_todos:
        if row.source_key not in keep_keys:
            row.deleted_at = now

    persisted: list[DeliveryPmDailyAction] = []
    for index, candidate in enumerate(ranked, start=1):
        row = next((item for item in existing_todos if item.source_key == candidate.source_key), None)
        ai_text = None
        if with_ai_rationale:
            ai_text = await generate_action_rationale(
                {
                    "title": candidate.title,
                    "deterministic_rationale": candidate.deterministic_rationale,
                    "estimated_impact_points": float(candidate.estimated_impact_points),
                    "urgency": candidate.urgency,
                    "due_date": candidate.due_date.isoformat(),
                    "evidence_json": candidate.evidence_json,
                    "root_cause_factor": candidate.root_cause_factor,
                }
            )
        if row is None:
            row = DeliveryPmDailyAction(
                id=uuid4(),
                org_id=org_id,
                project_id=project_id,
                plan_date=as_of,
                rank=index,
                title=candidate.title,
                description=candidate.description,
                deterministic_rationale=candidate.deterministic_rationale,
                ai_rationale=ai_text,
                urgency=PmDailyActionUrgency(candidate.urgency),
                estimated_impact_points=candidate.estimated_impact_points,
                due_date=candidate.due_date,
                status=PmDailyActionStatus.TODO,
                source_type=PmDailyActionSourceType(candidate.source_type),
                source_key=candidate.source_key,
                root_cause_factor=candidate.root_cause_factor,
                mitigation_recommendation_id=(
                    UUID(candidate.mitigation_recommendation_id)
                    if candidate.mitigation_recommendation_id
                    else None
                ),
                evidence_json=candidate.evidence_json,
                model_version=MODEL_VERSION,
                generated_at=now,
            )
            session.add(row)
        else:
            row.rank = index
            row.title = candidate.title
            row.description = candidate.description
            row.deterministic_rationale = candidate.deterministic_rationale
            if ai_text:
                row.ai_rationale = ai_text
            row.urgency = PmDailyActionUrgency(candidate.urgency)
            row.estimated_impact_points = candidate.estimated_impact_points
            row.due_date = candidate.due_date
            row.root_cause_factor = candidate.root_cause_factor
            row.evidence_json = candidate.evidence_json
            row.generated_at = now
            row.model_version = MODEL_VERSION
            row.deleted_at = None
        persisted.append(row)

    await session.flush()
    clear_delivery_portfolio_cache(org_id=org_id)
    return sorted(persisted, key=lambda item: item.rank)


async def list_daily_actions(
    session: AsyncSession,
    *,
    project_id: UUID,
    plan_date: date | None = None,
    include_history: bool = False,
    history_days: int = 14,
) -> dict[str, Any]:
    target = plan_date or date.today()
    today_rows = (
        (
            await session.execute(
                select(DeliveryPmDailyAction)
                .where(
                    DeliveryPmDailyAction.project_id == project_id,
                    DeliveryPmDailyAction.plan_date == target,
                    DeliveryPmDailyAction.deleted_at.is_(None),
                )
                .order_by(DeliveryPmDailyAction.rank.asc(), DeliveryPmDailyAction.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    focus = [_action_payload(row) for row in today_rows if row.status == PmDailyActionStatus.TODO]
    history: list[dict[str, Any]] = []
    if include_history:
        since = target - timedelta(days=max(0, history_days - 1))
        hist_rows = (
            (
                await session.execute(
                    select(DeliveryPmDailyAction)
                    .where(
                        DeliveryPmDailyAction.project_id == project_id,
                        DeliveryPmDailyAction.plan_date >= since,
                        DeliveryPmDailyAction.plan_date <= target,
                        DeliveryPmDailyAction.deleted_at.is_(None),
                        DeliveryPmDailyAction.status.in_(
                            (
                                PmDailyActionStatus.DONE,
                                PmDailyActionStatus.SKIPPED,
                                PmDailyActionStatus.DEFERRED,
                            )
                        ),
                    )
                    .order_by(
                        DeliveryPmDailyAction.completed_at.desc().nullslast(),
                        DeliveryPmDailyAction.plan_date.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        history = [_action_payload(row) for row in hist_rows]

    return {
        "project_id": str(project_id),
        "plan_date": target.isoformat(),
        "todays_focus": focus,
        "all_today": [_action_payload(row) for row in today_rows],
        "history": history,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def complete_daily_action(
    session: AsyncSession,
    *,
    action_id: UUID,
    actor: CurrentUser,
    status: PmDailyActionStatus = PmDailyActionStatus.DONE,
    note: str | None = None,
) -> DeliveryPmDailyAction:
    if status not in {
        PmDailyActionStatus.DONE,
        PmDailyActionStatus.SKIPPED,
        PmDailyActionStatus.DEFERRED,
    }:
        raise ApiError(400, "INVALID_STATUS", "Completion status must be done, skipped, or deferred.")
    row = (
        await session.execute(
            select(DeliveryPmDailyAction).where(
                DeliveryPmDailyAction.id == action_id,
                DeliveryPmDailyAction.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Daily action was not found.")
    if actor.role == AppRole.DELIVERY_MANAGER and row.org_id != actor.org_id:
        raise ApiError(404, "NOT_FOUND", "Daily action was not found.")
    if row.status != PmDailyActionStatus.TODO:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Only todo actions can be completed.")
    row.status = status
    row.completed_at = datetime.now(UTC)
    row.completed_by = actor.id
    row.completion_note = note
    await session.flush()
    clear_delivery_portfolio_cache(org_id=row.org_id)
    return row


def action_to_payload(row: DeliveryPmDailyAction) -> dict[str, Any]:
    return _action_payload(row)

async def safe_generate_daily_actions_after_scoring(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    plan_date: date,
) -> None:
    try:
        await generate_daily_actions(
            session,
            project_id=project_id,
            org_id=org_id,
            plan_date=plan_date,
            with_ai_rationale=False,
        )
    except Exception:
        logger.exception(
            "event=pm_daily_actions_generate_failed project_id=%s plan_date=%s",
            project_id,
            plan_date.isoformat(),
        )


async def _pending_mitigations(
    session: AsyncSession, *, project_id: UUID
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(MitigationRecommendation)
                .where(
                    MitigationRecommendation.project_id == project_id,
                    MitigationRecommendation.deleted_at.is_(None),
                    MitigationRecommendation.status == RecommendationStatus.PENDING,
                )
                .order_by(MitigationRecommendation.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "description": row.description,
            "severity": row.severity.value if hasattr(row.severity, "value") else str(row.severity),
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        }
        for row in rows
    ]


def _overdue_count(milestones: list[dict[str, Any]], as_of: date) -> int:
    count = 0
    for milestone in milestones:
        status = str(milestone.get("status", ""))
        if status == "missed":
            count += 1
            continue
        planned = milestone.get("planned_date")
        if planned is None or status == "completed":
            continue
        planned_date = planned if isinstance(planned, date) else date.fromisoformat(str(planned))
        if planned_date < as_of:
            count += 1
    return count


def _action_payload(row: DeliveryPmDailyAction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "org_id": str(row.org_id),
        "plan_date": row.plan_date.isoformat(),
        "rank": row.rank,
        "title": row.title,
        "description": row.description,
        "deterministic_rationale": row.deterministic_rationale,
        "ai_rationale": row.ai_rationale,
        "urgency": row.urgency.value if hasattr(row.urgency, "value") else row.urgency,
        "estimated_impact_points": float(row.estimated_impact_points),
        "due_date": row.due_date.isoformat(),
        "status": row.status.value if hasattr(row.status, "value") else row.status,
        "source_type": row.source_type.value if hasattr(row.source_type, "value") else row.source_type,
        "source_key": row.source_key,
        "root_cause_factor": row.root_cause_factor,
        "mitigation_recommendation_id": (
            str(row.mitigation_recommendation_id) if row.mitigation_recommendation_id else None
        ),
        "evidence_json": row.evidence_json or {},
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "completed_by": str(row.completed_by) if row.completed_by else None,
        "completion_note": row.completion_note,
        "model_version": row.model_version,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }
