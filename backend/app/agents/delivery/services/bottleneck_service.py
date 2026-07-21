"""Persistence and lifecycle orchestration for deterministic Delivery bottlenecks."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.analytics.bottlenecks import (
    BottleneckAnalysisResult,
    BottleneckDetectionSignal,
    TeamThroughputObservation,
    analyze_team_bottlenecks,
)
from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.delivery.configuration import load_delivery_scoring_thresholds
from app.agents.delivery.services.scoring_service import (
    DeliveryScoringRunResult,
    run_delivery_scoring,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    Bottleneck,
    BottleneckSourceType,
    NotificationType,
    Project,
    RiskTier,
    Team,
    TeamThroughputSnapshot,
    User,
)
from app.services.notifications import create_notification

logger = logging.getLogger(__name__)

ACTIVE_BOTTLENECK_STATUSES = {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}
SEVERITY_RANK = {
    RiskTier.LOW: 0,
    RiskTier.MEDIUM: 1,
    RiskTier.HIGH: 2,
    RiskTier.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class BottleneckDetectionResult:
    analysis: BottleneckAnalysisResult
    created: int = 0
    updated: int = 0
    resolved: int = 0
    reopened: int = 0
    notifications_sent: int = 0
    scoring: DeliveryScoringRunResult | None = None

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.resolved or self.reopened)


async def detect_project_bottlenecks(
    session: AsyncSession,
    *,
    project: Project,
    as_of_date: date | None = None,
    trigger_scoring: bool = True,
    score_when_unchanged: bool = False,
) -> BottleneckDetectionResult:
    """Load bounded inputs once, analyze them, and persist lifecycle transitions."""
    started = perf_counter()
    effective_date = as_of_date or date.today()
    thresholds = await load_delivery_scoring_thresholds(session, project.org_id)

    # Serialize detector lifecycle changes per project across app processes. This
    # complements the source-key unique index and row locks for existing records.
    detector_lock_key = f"delivery-bottleneck:{project.org_id}:{project.id}"
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(detector_lock_key, 0)))
    )

    data_started = perf_counter()
    teams = list(
        (
            await session.execute(
                select(Team)
                .where(
                    Team.project_id == project.id,
                    Team.org_id == project.org_id,
                    Team.is_active.is_(True),
                    Team.deleted_at.is_(None),
                )
                .order_by(Team.id)
            )
        ).scalars()
    )
    cutoff = effective_date - timedelta(days=thresholds.bottleneck.maximum_history_days - 1)
    snapshot_rows = list(
        (
            await session.execute(
                select(TeamThroughputSnapshot)
                .where(
                    TeamThroughputSnapshot.org_id == project.org_id,
                    TeamThroughputSnapshot.project_id == project.id,
                    TeamThroughputSnapshot.snapshot_date >= cutoff,
                    TeamThroughputSnapshot.snapshot_date <= effective_date,
                )
                .order_by(
                    TeamThroughputSnapshot.snapshot_date,
                    TeamThroughputSnapshot.team_id,
                )
            )
        ).scalars()
    )
    existing_rows = list(
        (
            await session.execute(
                select(Bottleneck)
                .where(
                    Bottleneck.org_id == project.org_id,
                    Bottleneck.project_id == project.id,
                    Bottleneck.source_type == BottleneckSourceType.DETECTOR,
                    Bottleneck.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalars()
    )
    data_load_ms = (perf_counter() - data_started) * 1000

    analytics_started = perf_counter()
    analysis = analyze_team_bottlenecks(
        [
            TeamThroughputObservation(
                team_id=row.team_id,
                snapshot_date=row.snapshot_date,
                units_completed=row.units_completed,
                active_headcount=row.active_headcount,
            )
            for row in snapshot_rows
        ],
        organisation_id=project.org_id,
        project_id=project.id,
        expected_team_ids={team.id for team in teams},
        thresholds=thresholds.bottleneck,
        as_of_date=effective_date,
    )
    analytics_ms = (perf_counter() - analytics_started) * 1000

    persistence_started = perf_counter()
    now = datetime.now(UTC)
    audit = AuditLogger(session)
    existing_by_source = {
        row.source_key: row for row in existing_rows if row.source_key is not None
    }
    team_names = {team.id: team.name for team in teams}
    created = updated = resolved = reopened = 0
    notifications: list[tuple[str, Bottleneck]] = []

    for signal in analysis.signals:
        evidence = _signal_evidence(signal)
        evidence_hash = _evidence_hash(evidence)
        existing = existing_by_source.get(signal.source_key)
        if existing is None:
            bottleneck = Bottleneck(
                id=uuid4(),
                org_id=project.org_id,
                project_id=project.id,
                team_id=signal.team_id,
                title=f"Sustained throughput decline: {team_names.get(signal.team_id, 'team')}",
                detail=_signal_detail(signal),
                status=AlertStatus.OPEN,
                severity=RiskTier(signal.severity),
                source_type=BottleneckSourceType.DETECTOR,
                source_key=signal.source_key,
                detector_version=signal.detector_version,
                evidence_json=evidence,
                first_detected_at=now,
                last_detected_at=now,
                last_evidence_hash=evidence_hash,
                occurrence_count=1,
            )
            session.add(bottleneck)
            existing_by_source[signal.source_key] = bottleneck
            created += 1
            await _audit_bottleneck(
                audit,
                "delivery_bottleneck_detected",
                bottleneck,
                actor_id=None,
                old_status=None,
                old_severity=None,
            )
            if bottleneck.severity in {RiskTier.HIGH, RiskTier.CRITICAL}:
                notifications.append(("detected", bottleneck))
            continue

        if existing.status in ACTIVE_BOTTLENECK_STATUSES:
            old_severity = existing.severity
            evidence_changed = existing.last_evidence_hash != evidence_hash
            severity_changed = old_severity != RiskTier(signal.severity)
            existing.last_detected_at = now
            existing.recovery_started_at = None
            existing.evidence_json = evidence
            existing.last_evidence_hash = evidence_hash
            existing.detail = _signal_detail(signal)
            existing.severity = RiskTier(signal.severity)
            if evidence_changed or severity_changed:
                updated += 1
                await _audit_bottleneck(
                    audit,
                    "delivery_bottleneck_updated",
                    existing,
                    actor_id=None,
                    old_status=existing.status,
                    old_severity=old_severity,
                )
            if severity_changed and SEVERITY_RANK[existing.severity] > SEVERITY_RANK[old_severity]:
                notifications.append(("escalated", existing))
            continue

        if existing.status == AlertStatus.RESOLVED and _can_reopen(
            existing,
            signal,
            evidence_hash,
        ):
            old_severity = existing.severity
            existing.status = AlertStatus.OPEN
            existing.severity = RiskTier(signal.severity)
            existing.detail = _signal_detail(signal)
            existing.evidence_json = evidence
            existing.last_evidence_hash = evidence_hash
            existing.last_detected_at = now
            existing.first_detected_at = existing.first_detected_at or now
            existing.acknowledged_at = None
            existing.acknowledged_by = None
            existing.acknowledgement_note = None
            existing.resolved_at = None
            existing.resolved_by = None
            existing.resolution_reason = None
            existing.recovery_started_at = None
            existing.occurrence_count += 1
            reopened += 1
            await _audit_bottleneck(
                audit,
                "delivery_bottleneck_reopened",
                existing,
                actor_id=None,
                old_status=AlertStatus.RESOLVED,
                old_severity=old_severity,
            )
            notifications.append(("reopened", existing))

    recovered_ids = set(analysis.recovered_team_ids)
    recovery_start_date = effective_date - timedelta(days=thresholds.bottleneck.recovery_days - 1)
    for bottleneck in existing_rows:
        if (
            bottleneck.status not in ACTIVE_BOTTLENECK_STATUSES
            or bottleneck.team_id not in recovered_ids
        ):
            continue
        old_status = bottleneck.status
        old_severity = bottleneck.severity
        bottleneck.recovery_started_at = datetime.combine(
            recovery_start_date,
            time.min,
            tzinfo=UTC,
        )
        bottleneck.status = AlertStatus.RESOLVED
        bottleneck.resolved_at = now
        bottleneck.resolved_by = None
        bottleneck.resolution_reason = (
            f"Automatically resolved after {thresholds.bottleneck.recovery_days} "
            "consecutive valid recovery observations."
        )
        resolved += 1
        await _audit_bottleneck(
            audit,
            "delivery_bottleneck_auto_resolved",
            bottleneck,
            actor_id=None,
            old_status=old_status,
            old_severity=old_severity,
        )
        notifications.append(("resolved", bottleneck))

    await session.flush()
    persistence_ms = (perf_counter() - persistence_started) * 1000
    notifications_sent = await _send_transition_notifications(
        session,
        org_id=project.org_id,
        project_name=project.name,
        transitions=notifications,
    )

    scoring: DeliveryScoringRunResult | None = None
    scoring_started = perf_counter()
    changed = bool(created or updated or resolved or reopened)
    if trigger_scoring and (changed or score_when_unchanged):
        scoring = await run_delivery_scoring(
            session,
            project_id=project.id,
            project=project,
            as_of_date=effective_date,
            thresholds=thresholds,
        )
    scoring_ms = (perf_counter() - scoring_started) * 1000

    total_ms = (perf_counter() - started) * 1000
    logger.info(
        "event=delivery_bottleneck_detection_completed organisation_id=%s project_id=%s "
        "teams_evaluated=%s valid_days=%s signals_detected=%s created_count=%s "
        "updated_count=%s resolved_count=%s reopened_count=%s skipped_count=%s "
        "data_load_ms=%.2f analytics_ms=%.2f persistence_ms=%.2f scoring_ms=%.2f "
        "total_ms=%.2f",
        project.org_id,
        project.id,
        analysis.evaluated_teams,
        analysis.valid_observation_days,
        len(analysis.signals),
        created,
        updated,
        resolved,
        reopened,
        len(analysis.skipped_reasons),
        data_load_ms,
        analytics_ms,
        persistence_ms,
        scoring_ms,
        total_ms,
    )
    for skip in analysis.skipped_reasons:
        logger.info(
            "event=delivery_bottleneck_detection_skipped organisation_id=%s project_id=%s "
            "reason=%s team_id=%s",
            project.org_id,
            project.id,
            skip.reason,
            skip.team_id or "none",
        )

    return BottleneckDetectionResult(
        analysis=analysis,
        created=created,
        updated=updated,
        resolved=resolved,
        reopened=reopened,
        notifications_sent=notifications_sent,
        scoring=scoring,
    )


async def acknowledge_bottleneck(
    session: AsyncSession,
    *,
    bottleneck: Bottleneck,
    actor: CurrentUser,
    note: str | None,
) -> bool:
    """Acknowledge an active bottleneck without removing its scoring impact."""
    if bottleneck.status == AlertStatus.ACKNOWLEDGED:
        return False
    if bottleneck.status != AlertStatus.OPEN:
        raise ApiError(
            400,
            "INVALID_STATUS_TRANSITION",
            "Only open bottlenecks can be acknowledged.",
        )
    old_status = bottleneck.status
    bottleneck.status = AlertStatus.ACKNOWLEDGED
    bottleneck.acknowledged_at = datetime.now(UTC)
    bottleneck.acknowledged_by = actor.id
    bottleneck.acknowledgement_note = note
    await _audit_bottleneck(
        AuditLogger(session),
        "delivery_bottleneck_acknowledged",
        bottleneck,
        actor_id=actor.id,
        old_status=old_status,
        old_severity=bottleneck.severity,
    )
    await session.flush()
    return True


async def resolve_bottleneck(
    session: AsyncSession,
    *,
    project: Project,
    bottleneck: Bottleneck,
    actor: CurrentUser,
    reason: str,
    as_of_date: date | None = None,
) -> tuple[bool, DeliveryScoringRunResult | None]:
    """Manually resolve an active bottleneck and immediately refresh scoring."""
    if bottleneck.status == AlertStatus.RESOLVED:
        return False, None
    if bottleneck.status not in ACTIVE_BOTTLENECK_STATUSES:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Bottleneck cannot be resolved.")
    old_status = bottleneck.status
    bottleneck.status = AlertStatus.RESOLVED
    bottleneck.resolved_at = datetime.now(UTC)
    bottleneck.resolved_by = actor.id
    bottleneck.resolution_reason = reason
    bottleneck.recovery_started_at = None
    await _audit_bottleneck(
        AuditLogger(session),
        "delivery_bottleneck_resolved",
        bottleneck,
        actor_id=actor.id,
        old_status=old_status,
        old_severity=bottleneck.severity,
    )
    await session.flush()
    scoring = await run_delivery_scoring(
        session,
        project_id=project.id,
        project=project,
        as_of_date=as_of_date,
    )
    await _send_transition_notifications(
        session,
        org_id=project.org_id,
        project_name=project.name,
        transitions=[("resolved", bottleneck)],
    )
    return True, scoring


async def get_project_bottleneck(
    session: AsyncSession,
    *,
    project_id: UUID,
    bottleneck_id: UUID,
    for_update: bool = False,
) -> Bottleneck:
    query = select(Bottleneck).where(
        Bottleneck.id == bottleneck_id,
        Bottleneck.project_id == project_id,
        Bottleneck.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    bottleneck = (await session.execute(query)).scalar_one_or_none()
    if bottleneck is None:
        raise ApiError(404, "NOT_FOUND", "Bottleneck was not found.")
    return bottleneck


def _signal_evidence(signal: BottleneckDetectionSignal) -> dict[str, object]:
    return {
        "current_share": str(signal.current_share),
        "historical_share": str(signal.historical_share),
        "decline_pct": str(signal.decline_pct),
        "headcount_change_pct": (
            str(signal.headcount_change_pct) if signal.headcount_change_pct is not None else None
        ),
        "consecutive_days": signal.consecutive_days,
        "observation_window_days": signal.observation_window_days,
        "latest_observation_date": signal.latest_observation_date.isoformat(),
        "evidence": [point.model_dump(mode="json") for point in signal.evidence],
    }


def _evidence_hash(evidence: dict[str, object]) -> str:
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _signal_detail(signal: BottleneckDetectionSignal) -> str:
    return (
        f"Team throughput share averaged {signal.current_share}% versus a "
        f"{signal.historical_share}% historical baseline, a {signal.decline_pct}% "
        f"relative decline sustained for {signal.consecutive_days} valid observation days."
    )


def _can_reopen(
    bottleneck: Bottleneck,
    signal: BottleneckDetectionSignal,
    evidence_hash: str,
) -> bool:
    if bottleneck.resolved_at is None:
        return False
    return (
        signal.latest_observation_date > bottleneck.resolved_at.date()
        and evidence_hash != bottleneck.last_evidence_hash
    )


async def _audit_bottleneck(
    audit: AuditLogger,
    event_type: str,
    bottleneck: Bottleneck,
    *,
    actor_id: UUID | None,
    old_status: AlertStatus | None,
    old_severity: RiskTier | None,
) -> None:
    evidence = bottleneck.evidence_json or {}
    await audit.log(
        event_type=event_type,
        org_id=bottleneck.org_id,
        project_id=bottleneck.project_id,
        payload={
            "bottleneck_id": str(bottleneck.id),
            "team_id": str(bottleneck.team_id) if bottleneck.team_id else None,
            "actor_id": str(actor_id) if actor_id else None,
            "old_status": old_status.value if old_status else None,
            "new_status": bottleneck.status.value,
            "old_severity": old_severity.value if old_severity else None,
            "new_severity": bottleneck.severity.value,
            "source_key": bottleneck.source_key,
            "decline_pct": evidence.get("decline_pct"),
            "latest_observation_date": evidence.get("latest_observation_date"),
            "occurrence_count": bottleneck.occurrence_count,
        },
    )


async def _send_transition_notifications(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_name: str,
    transitions: list[tuple[str, Bottleneck]],
) -> int:
    if not transitions:
        return 0
    try:
        async with session.begin_nested():
            recipients = list(
                (
                    await session.execute(
                        select(User).where(
                            User.org_id == org_id,
                            User.is_active.is_(True),
                            User.deleted_at.is_(None),
                            User.role.in_([AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP]),
                        )
                    )
                ).scalars()
            )
            sent = 0
            for transition, bottleneck in transitions:
                for recipient in recipients:
                    await create_notification(
                        session,
                        user_id=recipient.id,
                        org_id=org_id,
                        notification_type=NotificationType.RISK_ALERT,
                        title=f"Delivery bottleneck {transition}: {project_name}",
                        body=(
                            f"A {bottleneck.severity.value} delivery bottleneck was "
                            f"{transition}. Review the internal Delivery workspace for details."
                        ),
                        source_table="bottlenecks",
                        source_row_id=bottleneck.id,
                    )
                    sent += 1
            return sent
    except Exception:
        logger.exception(
            "event=delivery_bottleneck_notification_failed organisation_id=%s",
            org_id,
        )
        return 0
