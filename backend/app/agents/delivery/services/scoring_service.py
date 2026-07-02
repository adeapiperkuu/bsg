"""Pure delivery scoring computation and event-driven orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.confidence import (
    ON_TRACK_THRESHOLD,
    ConfidenceStatus,
    calculate_confidence,
    classify_confidence_status,
    forecast_completion_date,
    has_sufficient_throughput_data,
)
from app.agents.delivery.analytics.milestones import resolve_milestone_status, select_current_milestone
from app.agents.delivery.analytics.risk import (
    WARNING_WINDOW_DAYS,
    build_contributing_causes,
    calculate_risk,
    classify_risk_tier,
)
from app.agents.delivery.analytics.status import calculate_status
from app.agents.delivery.analytics.throughput import (
    latest_rolling_units,
    rolling_windows_from_snapshots,
    throughput_decline_pct,
)
from app.agents.delivery.events.domain_events import (
    DeliveryScoredEvent,
    DeliveryScoresSnapshot,
    HandlerRunSummary,
    MilestoneStatusUpdate,
)
from app.agents.delivery.events.event_bus import HandlerExecutionResult, emit_event
from app.agents.delivery.events.handlers import (
    confidence_snapshot_from_row,
    register_delivery_handlers,
    risk_alert_snapshot_from_row,
)
from app.db.models import AlertType, Project


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """Normalized delivery inputs computed once per scoring or dashboard request."""

    as_of_date: date
    project: dict[str, Any]
    milestones: list[dict[str, Any]]
    throughput_snapshots: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    bottlenecks: list[dict[str, Any]]
    quality_snapshot: dict[str, Any] | None
    rolling_windows: list[int]
    latest_rolling_units: int | None
    throughput_decline_pct: Decimal
    is_throughput_declining: bool
    current_milestone: dict[str, Any] | None
    days_until_milestone: int | None
    open_bottleneck_count: int
    has_quality_drift: bool
    rework_rate_pct: Decimal | None

    @classmethod
    def from_raw_data(cls, raw_data: dict[str, Any]) -> ScoringContext:
        """Build a scoring context from aggregated delivery raw data."""
        snapshots = raw_data["throughput_snapshots"]
        milestones = raw_data["milestones"]
        as_of_date = raw_data["as_of_date"]
        quality_snapshot = raw_data.get("quality_snapshot")
        rolling_windows = rolling_windows_from_snapshots(snapshots)
        decline_pct = throughput_decline_pct(rolling_windows)
        current_milestone = select_current_milestone(milestones, as_of_date=as_of_date)
        rework_rate_pct = quality_snapshot.get("rework_rate_pct") if quality_snapshot else None

        return cls(
            as_of_date=as_of_date,
            project=raw_data["project"],
            milestones=milestones,
            throughput_snapshots=snapshots,
            risks=raw_data["risks"],
            bottlenecks=raw_data["bottlenecks"],
            quality_snapshot=quality_snapshot,
            rolling_windows=rolling_windows,
            latest_rolling_units=latest_rolling_units(snapshots),
            throughput_decline_pct=decline_pct,
            is_throughput_declining=decline_pct > Decimal("0.00"),
            current_milestone=dict(current_milestone) if current_milestone is not None else None,
            days_until_milestone=(
                (current_milestone["planned_date"] - as_of_date).days
                if current_milestone is not None
                else None
            ),
            open_bottleneck_count=len(raw_data["bottlenecks"]),
            has_quality_drift=bool(quality_snapshot and quality_snapshot.get("has_drift_alert")),
            rework_rate_pct=(
                Decimal(str(rework_rate_pct))
                if rework_rate_pct is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DeliveryScores:
    """Deterministic delivery analytics outputs for one project."""

    confidence: Decimal
    risk: Decimal
    traffic_light: str
    risk_tier: str
    contributing_causes: dict[str, float]
    confidence_status: ConfidenceStatus
    forecast_completion_date: date | None
    has_sufficient_data: bool = True


@dataclass(frozen=True, slots=True)
class DeliveryScoringRunResult:
    """Summary of a delivery scoring run including handler side effects."""

    project_id: UUID
    as_of_date: date
    scores: DeliveryScores
    milestones_updated: int
    confidence_score_id: UUID | None
    risk_alert_id: UUID | None
    milestone_alert_ids: tuple[UUID, ...]
    notifications_sent: int
    skipped_persistence: bool
    # "failed" means the pure scores were computed but a persistence/side-effect handler
    # raised — the throughput snapshot itself is unaffected, but confidence/risk/alerts
    # may be stale until the next successful scoring run. Never silently hidden from callers.
    scoring_status: Literal["ok", "failed"] = "ok"
    scoring_error: str | None = None


@dataclass(frozen=True, slots=True)
class _ScoringComputeResult:
    """Intermediate result of Phase 1 (load + compute). Contains no DB writes."""

    resolved_project: Project
    scores: DeliveryScores
    event: DeliveryScoredEvent


def compute_delivery_scores(context: ScoringContext) -> DeliveryScores:
    """Calculate confidence, risk, traffic light, and contributing causes once."""
    confidence = calculate_confidence(
        context.latest_rolling_units,
        context.project.get("daily_target_units"),
        context.rolling_windows,
    )
    risk = calculate_risk(
        confidence_score_pct=confidence,
        throughput_decline_pct=context.throughput_decline_pct,
        is_throughput_declining=context.is_throughput_declining,
        days_until_milestone=context.days_until_milestone,
        open_bottleneck_count=context.open_bottleneck_count,
        has_quality_drift=context.has_quality_drift,
        rework_rate_pct=context.rework_rate_pct,
        on_track_threshold=ON_TRACK_THRESHOLD,
        warning_window_days=WARNING_WINDOW_DAYS,
    )
    traffic_light = calculate_status(
        confidence=confidence,
        risk_score=risk,
        open_bottleneck_count=context.open_bottleneck_count,
        milestone_status=(
            context.current_milestone.get("status")
            if context.current_milestone is not None
            else None
        ),
        open_risk_tiers=[risk_item["risk_tier"] for risk_item in context.risks],
        yellow_confidence_threshold=ON_TRACK_THRESHOLD,
    )
    contributing_causes = build_contributing_causes(
        confidence_score_pct=confidence,
        throughput_decline_pct=context.throughput_decline_pct,
        is_throughput_declining=context.is_throughput_declining,
        days_until_milestone=context.days_until_milestone,
        open_bottleneck_count=context.open_bottleneck_count,
        has_quality_drift=context.has_quality_drift,
        rework_rate_pct=context.rework_rate_pct,
        on_track_threshold=ON_TRACK_THRESHOLD,
    )
    confidence_status = classify_confidence_status(confidence)
    forecast = _forecast_completion_date(context)
    return DeliveryScores(
        confidence=confidence,
        risk=risk,
        traffic_light=traffic_light,
        risk_tier=classify_risk_tier(risk),
        contributing_causes=contributing_causes,
        confidence_status=confidence_status,
        forecast_completion_date=forecast,
        has_sufficient_data=has_sufficient_throughput_data(context.latest_rolling_units),
    )


def compute_milestone_status_updates(
    milestones: list[dict[str, Any]],
    *,
    context: ScoringContext,
    scores: DeliveryScores,
) -> tuple[MilestoneStatusUpdate, ...]:
    """Pure milestone lifecycle transitions without mutating persistence state."""
    updates: list[MilestoneStatusUpdate] = []
    for milestone in milestones:
        previous_status = str(milestone["status"])
        resolved_status = resolve_milestone_status(
            current_status=previous_status,
            planned_date=milestone["planned_date"],
            actual_date=milestone.get("actual_date"),
            as_of_date=context.as_of_date,
            confidence_score_pct=scores.confidence,
        )
        if resolved_status == previous_status:
            continue
        updates.append(
            MilestoneStatusUpdate(
                milestone_id=milestone["id"],
                milestone_name=str(milestone["name"]),
                previous_status=previous_status,
                new_status=resolved_status,
            )
        )
    return tuple(updates)


def build_dashboard_response(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Prepare the final deterministic dashboard payload."""
    context = ScoringContext.from_raw_data(raw_data)
    scores = compute_delivery_scores(context)
    latest_snapshot = (
        context.throughput_snapshots[0] if context.throughput_snapshots else None
    )

    overview = {
        "project": context.project,
        "latest_throughput": latest_snapshot,
        "current_milestone": context.current_milestone,
        "open_risk_count": len(context.risks),
        "open_bottleneck_count": context.open_bottleneck_count,
        "calculated_risk": {
            "score": float(scores.risk),
            "tier": scores.risk_tier,
            "contributing_causes": scores.contributing_causes,
        },
        # False only when the project has zero throughput snapshots — callers must show
        # "Insufficient data" instead of treating the numeric confidence/traffic_light as
        # a real health signal (see has_sufficient_throughput_data).
        "has_sufficient_data": scores.has_sufficient_data,
    }

    return {
        "overview": overview,
        "milestones": context.milestones,
        "confidence": float(scores.confidence),
        "risks": context.risks,
        "bottlenecks": context.bottlenecks,
        "traffic_light": scores.traffic_light,
        "daily_summary": None,
    }


async def run_delivery_scoring(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of_date: date | None = None,
    project: Project | None = None,
) -> DeliveryScoringRunResult:
    """Orchestrate a delivery scoring run with safe transaction boundaries.

    Standalone calls (no active transaction):
      Phase 1 — load + compute in a committed read transaction.
      Phase 2 — emit event and persist handler side effects in a fresh transaction.

    Embedded calls (active transaction already open, e.g. from ingestion):
      Both phases run within the caller's transaction; the caller is responsible
      for the transaction boundary and fault isolation (e.g. a savepoint).
    """
    register_delivery_handlers()
    effective_date = as_of_date or date.today()

    if session.in_transaction():
        compute_result = await _compute_scoring_event(
            session, project_id=project_id, as_of_date=effective_date, project=project
        )
        handler_results = await emit_event(session, compute_result.event)
    else:
        # Phase 1: reads + pure computation only — no DB writes.
        async with session.begin():
            compute_result = await _compute_scoring_event(
                session, project_id=project_id, as_of_date=effective_date, project=project
            )
        # Phase 1 committed. The event is built from a stable, committed snapshot.

        # Phase 2: handler side effects in an isolated transaction.
        async with session.begin():
            handler_results = await emit_event(session, compute_result.event)

    return _build_run_result(compute_result, effective_date, handler_results)


async def _compute_scoring_event(
    session: AsyncSession,
    *,
    project_id: UUID,
    as_of_date: date,
    project: Project | None,
) -> _ScoringComputeResult:
    """Load scoring inputs and build the delivery event. Pure reads and computation."""
    from app.agents.delivery.services.dashboard_service import load_project_scoring_inputs

    resolved_project = project or await _load_project(session, project_id)
    if resolved_project.id != project_id:
        raise ValueError("project_id does not match the provided project entity.")

    inputs = await load_project_scoring_inputs(
        session,
        resolved_project,
        as_of_date=as_of_date,
    )
    context = ScoringContext.from_raw_data(inputs.raw_data)
    scores = compute_delivery_scores(context)
    milestone_updates = compute_milestone_status_updates(
        inputs.raw_data["milestones"],
        context=context,
        scores=scores,
    )

    previous_confidence = None
    current_milestone = inputs.current_milestone  # ORM Milestone | None
    if current_milestone is not None:
        latest = inputs.latest_confidence_by_milestone.get(current_milestone.id)
        if latest is not None:
            previous_confidence = confidence_snapshot_from_row(latest)

    # open_risk_alerts is already filtered to OPEN/ACKNOWLEDGED by the DB query.
    previous_delivery_alert = next(
        (
            risk_alert_snapshot_from_row(alert)
            for alert in inputs.open_risk_alerts
            if alert.alert_type == AlertType.DELIVERY_RISK
        ),
        None,
    )

    event = DeliveryScoredEvent(
        project_id=resolved_project.id,
        org_id=resolved_project.org_id,
        project_name=resolved_project.name,
        as_of_date=as_of_date,
        occurred_at=datetime.now(timezone.utc),
        scores=_scores_snapshot(scores),
        current_milestone_id=current_milestone.id if current_milestone is not None else None,
        milestone_updates=milestone_updates,
        previous_confidence=previous_confidence,
        previous_delivery_alert=previous_delivery_alert,
        latest_confidence_by_milestone={
            milestone_id: confidence_snapshot_from_row(row)
            for milestone_id, row in inputs.latest_confidence_by_milestone.items()
        },
    )

    return _ScoringComputeResult(
        resolved_project=resolved_project,
        scores=scores,
        event=event,
    )


def _build_run_result(
    compute_result: _ScoringComputeResult,
    effective_date: date,
    handler_results: list[HandlerExecutionResult],
) -> DeliveryScoringRunResult:
    summary = next(
        (
            r.result
            for r in handler_results
            if r.success and isinstance(r.result, HandlerRunSummary)
        ),
        HandlerRunSummary(),
    )
    failed = next((r for r in handler_results if not r.success), None)
    scoring_status: Literal["ok", "failed"] = "failed" if failed is not None else "ok"
    # Sanitized: handler name + exception type only, never the raw exception message
    # (which may include internal identifiers or query fragments). Full detail is in the logs.
    scoring_error = f"{failed.handler} raised {failed.error_type}" if failed is not None else None

    return DeliveryScoringRunResult(
        project_id=compute_result.resolved_project.id,
        as_of_date=effective_date,
        scores=compute_result.scores,
        milestones_updated=summary.milestones_updated,
        confidence_score_id=summary.confidence_score_id,
        risk_alert_id=summary.risk_alert_id,
        milestone_alert_ids=summary.milestone_alert_ids,
        notifications_sent=summary.notifications_sent,
        skipped_persistence=_run_was_fully_idempotent(summary),
        scoring_status=scoring_status,
        scoring_error=scoring_error,
    )


async def _load_project(session: AsyncSession, project_id: UUID) -> Project:
    """Load a single project row for scoring orchestration."""
    project = (
        await session.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if project is None:
        raise ValueError(f"Project {project_id} was not found.")
    return project


def _forecast_completion_date(context: ScoringContext) -> date | None:
    """Estimate forecast completion when enough throughput context exists."""
    if context.latest_rolling_units is None or context.latest_rolling_units <= 0:
        return None
    if context.current_milestone is None:
        return None

    days_until_planned = (
        context.current_milestone["planned_date"] - context.as_of_date
    ).days
    if days_until_planned <= 0:
        return context.current_milestone["planned_date"]

    daily_target = context.project.get("daily_target_units")
    if daily_target is None or daily_target <= 0:
        return None

    remaining_units = days_until_planned * int(daily_target)
    return forecast_completion_date(
        as_of_date=context.as_of_date,
        remaining_units=remaining_units,
        rolling_7day_units=context.latest_rolling_units,
    )


def _scores_snapshot(scores: DeliveryScores) -> DeliveryScoresSnapshot:
    return DeliveryScoresSnapshot(
        confidence=scores.confidence,
        risk=scores.risk,
        traffic_light=scores.traffic_light,
        risk_tier=scores.risk_tier,
        contributing_causes=scores.contributing_causes,
        confidence_status=scores.confidence_status,
        forecast_completion_date=scores.forecast_completion_date,
        has_sufficient_data=scores.has_sufficient_data,
    )


def _run_was_fully_idempotent(summary: HandlerRunSummary) -> bool:
    return (
        summary.milestones_updated == 0
        and summary.confidence_score_id is None
        and summary.risk_alert_id is None
        and not summary.milestone_alert_ids
        and summary.notifications_sent == 0
    )
