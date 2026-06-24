"""Delivery domain event handlers for persistence, alerts, and notifications."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.audit.audit_logger import AuditLogger
from app.agents.delivery.services.recommendation_service import sync_recommendations_for_project
from app.agents.delivery.events.domain_events import (
    ConfidenceSnapshot,
    DeliveryScoredEvent,
    DeliveryScoresSnapshot,
    HandlerRunSummary,
    MilestoneStatusUpdate,
    RiskAlertChangedEvent,
    RiskAlertSnapshot,
)
from app.agents.delivery.events.event_bus import get_delivery_event_bus
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    DeliveryConfidenceScore,
    Milestone,
    MilestoneStatus,
    Notification,
    NotificationType,
    RiskAlert,
    RiskTier,
    User,
)
from app.services.notifications import create_notification

MODEL_VERSION = "delivery_v1"
CONFIDENCE_CHANGE_THRESHOLD = Decimal("5.00")
RISK_INCREASE_THRESHOLD = Decimal("5.00")
ACTIVE_ALERT_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)
HIGH_RISK_TIERS = frozenset({RiskTier.HIGH, RiskTier.CRITICAL})
_handlers_registered = False


def register_delivery_handlers() -> None:
    """Subscribe delivery side-effect handlers to the process event bus."""
    global _handlers_registered
    if _handlers_registered:
        return
    bus = get_delivery_event_bus()
    bus.subscribe(DeliveryScoredEvent, handle_delivery_scored)
    _handlers_registered = True


async def handle_delivery_scored(
    session: AsyncSession,
    event: DeliveryScoredEvent,
) -> HandlerRunSummary:
    """Orchestrate idempotent delivery side effects for a scoring run."""
    audit = AuditLogger(session)
    milestones_updated = await MilestoneUpdateHandler(session, audit).handle(event)
    confidence_score_id = await ConfidenceScoreHandler(session, audit).handle(event)
    delivery_alert, milestone_alert_ids = await RiskAlertHandler(session, audit).handle(event)
    await sync_recommendations_for_project(
        session,
        project_id=event.project_id,
        org_id=event.org_id,
    )
    notifications_sent = await NotificationHandler(session).handle(
        event,
        confidence_score_id=confidence_score_id,
        delivery_alert_id=delivery_alert.id if delivery_alert is not None else None,
    )

    await audit.log(
        event_type="delivery_scored",
        org_id=event.org_id,
        project_id=event.project_id,
        payload={
            "as_of_date": event.as_of_date.isoformat(),
            "scores": _scores_payload(event.scores),
            "handler_summary": HandlerRunSummary(
                milestones_updated=milestones_updated,
                confidence_score_id=confidence_score_id,
                risk_alert_id=delivery_alert.id if delivery_alert is not None else None,
                milestone_alert_ids=milestone_alert_ids,
                notifications_sent=notifications_sent,
            ).to_dict(),
        },
    )
    await session.flush()
    return HandlerRunSummary(
        milestones_updated=milestones_updated,
        confidence_score_id=confidence_score_id,
        risk_alert_id=delivery_alert.id if delivery_alert is not None else None,
        milestone_alert_ids=milestone_alert_ids,
        notifications_sent=notifications_sent,
    )


class MilestoneUpdateHandler:
    """Persist milestone lifecycle transitions."""

    def __init__(self, session: AsyncSession, audit: AuditLogger) -> None:
        self._session = session
        self._audit = audit

    async def handle(self, event: DeliveryScoredEvent) -> int:
        if not event.milestone_updates:
            return 0

        milestone_ids = [update.milestone_id for update in event.milestone_updates]
        rows = await self._session.execute(
            select(Milestone).where(
                Milestone.id.in_(milestone_ids),
                Milestone.project_id == event.project_id,
                Milestone.deleted_at.is_(None),
            )
        )
        milestones_by_id = {milestone.id: milestone for milestone in rows.scalars()}
        updates = 0

        for update in event.milestone_updates:
            milestone = milestones_by_id.get(update.milestone_id)
            if milestone is None:
                continue
            next_status = MilestoneStatus(update.new_status)
            if milestone.status == next_status:
                continue
            milestone.status = next_status
            updates += 1

            await self._audit.log(
                event_type="milestone_updated",
                org_id=event.org_id,
                project_id=event.project_id,
                payload={
                    "milestone_id": str(update.milestone_id),
                    "milestone_name": update.milestone_name,
                    "previous_status": update.previous_status,
                    "new_status": update.new_status,
                    "as_of_date": event.as_of_date.isoformat(),
                },
            )

        if updates:
            await self._session.flush()
        return updates


class ConfidenceScoreHandler:
    """Upsert delivery confidence scores idempotently."""

    def __init__(self, session: AsyncSession, audit: AuditLogger) -> None:
        self._session = session
        self._audit = audit

    async def handle(self, event: DeliveryScoredEvent) -> UUID | None:
        if event.current_milestone_id is None:
            return None

        milestone_status = MilestoneStatus(event.scores.confidence_status)
        existing_for_date = await _fetch_confidence_for_milestone_on_date(
            self._session,
            project_id=event.project_id,
            milestone_id=event.current_milestone_id,
            as_of_date=event.as_of_date,
        )

        if existing_for_date is not None:
            if _confidence_score_unchanged(
                existing_for_date,
                score_pct=event.scores.confidence,
                status=milestone_status,
                forecast_completion_date=event.scores.forecast_completion_date,
            ):
                return existing_for_date.id

            existing_for_date.score_pct = event.scores.confidence
            existing_for_date.forecast_completion_date = event.scores.forecast_completion_date
            existing_for_date.status = milestone_status
            existing_for_date.model_version = MODEL_VERSION
            await self._session.flush()
            await self._audit.log(
                event_type="confidence_score_updated",
                org_id=event.org_id,
                project_id=event.project_id,
                payload=_confidence_audit_payload(existing_for_date),
            )
            return existing_for_date.id

        latest = event.latest_confidence_by_milestone.get(event.current_milestone_id)
        if latest is not None and _confidence_snapshot_unchanged(
            latest,
            score_pct=event.scores.confidence,
            status=event.scores.confidence_status,
            forecast_completion_date=event.scores.forecast_completion_date,
        ):
            return None

        confidence_score = DeliveryConfidenceScore(
            project_id=event.project_id,
            milestone_id=event.current_milestone_id,
            org_id=event.org_id,
            score_pct=event.scores.confidence,
            forecast_completion_date=event.scores.forecast_completion_date,
            status=milestone_status,
            model_version=MODEL_VERSION,
        )
        self._session.add(confidence_score)
        await self._session.flush()
        await self._audit.log(
            event_type="confidence_score_created",
            org_id=event.org_id,
            project_id=event.project_id,
            payload=_confidence_audit_payload(confidence_score),
        )
        return confidence_score.id


class RiskAlertHandler:
    """Upsert delivery and milestone risk alerts without duplicates."""

    def __init__(self, session: AsyncSession, audit: AuditLogger) -> None:
        self._session = session
        self._audit = audit

    async def handle(self, event: DeliveryScoredEvent) -> tuple[RiskAlert | None, tuple[UUID, ...]]:
        open_alerts = await _fetch_open_risk_alerts(self._session, event.project_id)
        delivery_alert = await self._upsert_delivery_risk_alert(event, open_alerts)
        milestone_alert_ids = await self._upsert_milestone_risk_alerts(event, open_alerts)
        return delivery_alert, milestone_alert_ids

    async def _upsert_delivery_risk_alert(
        self,
        event: DeliveryScoredEvent,
        open_alerts: list[RiskAlert],
    ) -> RiskAlert | None:
        existing = _find_open_project_risk_alert(open_alerts, alert_type=AlertType.DELIVERY_RISK)
        slippage_probability = (event.scores.risk / Decimal("100")).quantize(Decimal("0.001"))
        risk_tier = RiskTier(event.scores.risk_tier)
        title = f"Delivery slippage risk ({event.scores.risk_tier})"
        detail = (
            f"Calculated delivery slippage probability is {event.scores.risk}% "
            f"with traffic-light status {event.scores.traffic_light}."
        )

        if existing is not None:
            if _risk_alert_unchanged(
                existing,
                risk_tier=risk_tier,
                slippage_probability=slippage_probability,
                contributing_causes=event.scores.contributing_causes,
                title=title,
                detail=detail,
                milestone_id=event.current_milestone_id,
            ):
                return existing

            existing.risk_tier = risk_tier
            existing.slippage_probability = slippage_probability
            existing.contributing_causes = event.scores.contributing_causes
            existing.title = title
            existing.detail = detail
            existing.milestone_id = event.current_milestone_id
            await self._session.flush()
            await emit_risk_alert_changed_audit(
                self._audit,
                RiskAlertChangedEvent(
                    project_id=event.project_id,
                    org_id=event.org_id,
                    alert_id=existing.id,
                    alert_type=AlertType.DELIVERY_RISK.value,
                    risk_tier=risk_tier.value,
                    slippage_probability=slippage_probability,
                    milestone_id=event.current_milestone_id,
                    action="updated",
                    as_of_date=event.as_of_date,
                    occurred_at=event.occurred_at,
                    detail=detail,
                ),
            )
            return existing

        if event.scores.risk_tier == "low":
            return None

        risk_alert = RiskAlert(
            project_id=event.project_id,
            org_id=event.org_id,
            milestone_id=event.current_milestone_id,
            alert_type=AlertType.DELIVERY_RISK,
            risk_tier=risk_tier,
            title=title,
            detail=detail,
            slippage_probability=slippage_probability,
            contributing_causes=event.scores.contributing_causes,
            status=AlertStatus.OPEN,
        )
        self._session.add(risk_alert)
        await self._session.flush()
        await emit_risk_alert_changed_audit(
            self._audit,
            RiskAlertChangedEvent(
                project_id=event.project_id,
                org_id=event.org_id,
                alert_id=risk_alert.id,
                alert_type=AlertType.DELIVERY_RISK.value,
                risk_tier=risk_tier.value,
                slippage_probability=slippage_probability,
                milestone_id=event.current_milestone_id,
                action="created",
                as_of_date=event.as_of_date,
                occurred_at=event.occurred_at,
                detail=detail,
            ),
        )
        return risk_alert

    async def _upsert_milestone_risk_alerts(
        self,
        event: DeliveryScoredEvent,
        open_alerts: list[RiskAlert],
    ) -> tuple[UUID, ...]:
        milestone_rows = await self._session.execute(
            select(Milestone).where(
                Milestone.project_id == event.project_id,
                Milestone.deleted_at.is_(None),
                Milestone.status.in_([MilestoneStatus.AT_RISK, MilestoneStatus.MISSED]),
            )
        )
        milestones = list(milestone_rows.scalars())

        alert_ids: list[UUID] = []
        for milestone in milestones:
            if milestone.status not in {MilestoneStatus.AT_RISK, MilestoneStatus.MISSED}:
                continue

            risk_tier = (
                RiskTier.CRITICAL
                if milestone.status == MilestoneStatus.MISSED
                else RiskTier.HIGH
            )
            title = (
                f"Milestone missed: {milestone.name}"
                if milestone.status == MilestoneStatus.MISSED
                else f"Milestone at risk: {milestone.name}"
            )
            detail = (
                f"Milestone '{milestone.name}' is {milestone.status.value.replace('_', ' ')} "
                f"with planned date {milestone.planned_date.isoformat()}."
            )
            existing = _find_open_milestone_risk_alert(
                open_alerts,
                alert_type=AlertType.MILESTONE_AT_RISK,
                milestone_id=milestone.id,
            )
            if existing is not None:
                if existing.risk_tier == risk_tier and existing.title == title and existing.detail == detail:
                    alert_ids.append(existing.id)
                    continue

                existing.risk_tier = risk_tier
                existing.title = title
                existing.detail = detail
                await self._session.flush()
                await emit_risk_alert_changed_audit(
                    self._audit,
                    RiskAlertChangedEvent(
                        project_id=event.project_id,
                        org_id=event.org_id,
                        alert_id=existing.id,
                        alert_type=AlertType.MILESTONE_AT_RISK.value,
                        risk_tier=risk_tier.value,
                        slippage_probability=existing.slippage_probability,
                        milestone_id=milestone.id,
                        action="updated",
                        as_of_date=event.as_of_date,
                        occurred_at=event.occurred_at,
                        detail=detail,
                    ),
                )
                alert_ids.append(existing.id)
                continue

            alert = RiskAlert(
                project_id=event.project_id,
                org_id=event.org_id,
                milestone_id=milestone.id,
                alert_type=AlertType.MILESTONE_AT_RISK,
                risk_tier=risk_tier,
                title=title,
                detail=detail,
                slippage_probability=None,
                contributing_causes=None,
                status=AlertStatus.OPEN,
            )
            self._session.add(alert)
            await self._session.flush()
            open_alerts.append(alert)
            await emit_risk_alert_changed_audit(
                self._audit,
                RiskAlertChangedEvent(
                    project_id=event.project_id,
                    org_id=event.org_id,
                    alert_id=alert.id,
                    alert_type=AlertType.MILESTONE_AT_RISK.value,
                    risk_tier=risk_tier.value,
                    slippage_probability=None,
                    milestone_id=milestone.id,
                    action="created",
                    as_of_date=event.as_of_date,
                    occurred_at=event.occurred_at,
                    detail=detail,
                ),
            )
            alert_ids.append(alert.id)
        return tuple(alert_ids)


class NotificationHandler:
    """Dispatch delivery notifications when scoring thresholds are met."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        event: DeliveryScoredEvent,
        *,
        confidence_score_id: UUID | None,
        delivery_alert_id: UUID | None,
    ) -> int:
        recipients = await _fetch_notification_recipients(self._session, event.org_id)
        if not recipients:
            return 0

        notifications_sent = 0
        for update in event.milestone_updates:
            if update.new_status != MilestoneStatus.MISSED.value:
                continue
            if update.previous_status == MilestoneStatus.MISSED.value:
                continue
            notifications_sent += await _notify_recipients(
                self._session,
                recipients=recipients,
                org_id=event.org_id,
                notification_type=NotificationType.MILESTONE_AT_RISK,
                title=f"Milestone missed: {update.milestone_name}",
                body=(
                    f"{event.project_name} milestone '{update.milestone_name}' is now missed "
                    f"as of {event.as_of_date.isoformat()}."
                ),
                source_table="milestones",
                source_row_id=update.milestone_id,
            )

        if event.previous_confidence is not None:
            confidence_delta = abs(event.scores.confidence - event.previous_confidence.score_pct)
            if confidence_delta >= CONFIDENCE_CHANGE_THRESHOLD:
                source_row_id = confidence_score_id or event.previous_confidence.id
                notifications_sent += await _notify_recipients(
                    self._session,
                    recipients=recipients,
                    org_id=event.org_id,
                    notification_type=NotificationType.RISK_ALERT,
                    title=f"Delivery confidence changed: {event.project_name}",
                    body=(
                        f"Schedule confidence moved from {event.previous_confidence.score_pct}% "
                        f"to {event.scores.confidence}%."
                    ),
                    source_table="delivery_confidence_scores",
                    source_row_id=source_row_id,
                )

        previous_risk_pct = _risk_alert_probability_pct(event.previous_delivery_alert)
        current_risk_pct = event.scores.risk
        previous_tier = (
            RiskTier(event.previous_delivery_alert.risk_tier)
            if event.previous_delivery_alert is not None
            else None
        )
        current_tier = RiskTier(event.scores.risk_tier)
        risk_increased = (
            previous_risk_pct is not None
            and current_risk_pct >= previous_risk_pct + RISK_INCREASE_THRESHOLD
        )
        severity_increased = (
            previous_tier is not None
            and previous_tier not in HIGH_RISK_TIERS
            and current_tier in HIGH_RISK_TIERS
        )
        if (risk_increased or severity_increased) and delivery_alert_id is not None:
            notifications_sent += await _notify_recipients(
                self._session,
                recipients=recipients,
                org_id=event.org_id,
                notification_type=NotificationType.RISK_ALERT,
                title=f"Delivery risk increased: {event.project_name}",
                body=(
                    f"Delivery slippage probability is now {current_risk_pct}% "
                    f"({event.scores.risk_tier} tier)."
                ),
                source_table="risk_alerts",
                source_row_id=delivery_alert_id,
            )

        return notifications_sent


async def emit_risk_alert_changed_audit(
    audit: AuditLogger,
    event: RiskAlertChangedEvent,
) -> None:
    """Record a risk alert change in the append-only audit log."""
    await audit.log(
        event_type="risk_alert_changed",
        org_id=event.org_id,
        project_id=event.project_id,
        payload={
            "alert_id": str(event.alert_id),
            "alert_type": event.alert_type,
            "risk_tier": event.risk_tier,
            "slippage_probability": (
                str(event.slippage_probability) if event.slippage_probability is not None else None
            ),
            "milestone_id": str(event.milestone_id) if event.milestone_id else None,
            "action": event.action,
            "as_of_date": event.as_of_date.isoformat(),
            "detail": event.detail,
        },
    )


async def _fetch_open_risk_alerts(session: AsyncSession, project_id: UUID) -> list[RiskAlert]:
    rows = await session.execute(
        select(RiskAlert).where(
            RiskAlert.project_id == project_id,
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
        )
    )
    return list(rows.scalars())


async def _fetch_confidence_for_milestone_on_date(
    session: AsyncSession,
    *,
    project_id: UUID,
    milestone_id: UUID,
    as_of_date: date,
) -> DeliveryConfidenceScore | None:
    row = await session.execute(
        select(DeliveryConfidenceScore)
        .where(
            DeliveryConfidenceScore.project_id == project_id,
            DeliveryConfidenceScore.milestone_id == milestone_id,
            func.date(DeliveryConfidenceScore.created_at) == as_of_date,
        )
        .order_by(DeliveryConfidenceScore.created_at.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


def _find_open_project_risk_alert(
    open_risk_alerts: list[RiskAlert],
    *,
    alert_type: AlertType,
) -> RiskAlert | None:
    for alert in open_risk_alerts:
        if alert.alert_type != alert_type:
            continue
        if alert.status not in ACTIVE_ALERT_STATUSES:
            continue
        return alert
    return None


def _find_open_milestone_risk_alert(
    open_risk_alerts: list[RiskAlert],
    *,
    alert_type: AlertType,
    milestone_id: UUID,
) -> RiskAlert | None:
    for alert in open_risk_alerts:
        if alert.alert_type != alert_type:
            continue
        if alert.status not in ACTIVE_ALERT_STATUSES:
            continue
        if alert.milestone_id == milestone_id:
            return alert
    return None


def _confidence_score_unchanged(
    latest: DeliveryConfidenceScore,
    *,
    score_pct: Decimal,
    status: MilestoneStatus,
    forecast_completion_date: date | None,
) -> bool:
    return (
        latest.score_pct == score_pct
        and latest.status == status
        and latest.forecast_completion_date == forecast_completion_date
        and latest.model_version == MODEL_VERSION
    )


def _confidence_snapshot_unchanged(
    latest: ConfidenceSnapshot,
    *,
    score_pct: Decimal,
    status: str,
    forecast_completion_date: date | None,
) -> bool:
    return (
        latest.score_pct == score_pct
        and latest.status == status
        and latest.forecast_completion_date == forecast_completion_date
        and latest.model_version == MODEL_VERSION
    )


def _risk_alert_unchanged(
    alert: RiskAlert,
    *,
    risk_tier: RiskTier,
    slippage_probability: Decimal,
    contributing_causes: dict[str, float] | None,
    title: str,
    detail: str,
    milestone_id: UUID | None,
) -> bool:
    normalized_causes = contributing_causes or {}
    alert_causes = alert.contributing_causes or {}
    return (
        alert.risk_tier == risk_tier
        and alert.slippage_probability == slippage_probability
        and alert_causes == normalized_causes
        and alert.title == title
        and alert.detail == detail
        and alert.milestone_id == milestone_id
    )


def _risk_alert_probability_pct(alert: RiskAlertSnapshot | None) -> Decimal | None:
    if alert is None or alert.slippage_probability is None:
        return None
    return (alert.slippage_probability * Decimal("100")).quantize(Decimal("0.01"))


async def _fetch_notification_recipients(session: AsyncSession, org_id: UUID) -> list[User]:
    rows = await session.execute(
        select(User).where(
            User.org_id == org_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            User.role.in_([AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP]),
        )
    )
    return list(rows.scalars())


async def _notify_recipients(
    session: AsyncSession,
    *,
    recipients: list[User],
    org_id: UUID,
    notification_type: NotificationType,
    title: str,
    body: str,
    source_table: str,
    source_row_id: UUID,
) -> int:
    if not recipients:
        return 0

    existing_keys = await _fetch_existing_notification_keys(
        session,
        user_ids=[recipient.id for recipient in recipients],
        notification_type=notification_type,
        source_table=source_table,
        source_row_id=source_row_id,
    )

    created = 0
    for recipient in recipients:
        key = (recipient.id, notification_type, source_table, source_row_id)
        if key in existing_keys:
            continue
        await create_notification(
            session,
            user_id=recipient.id,
            org_id=org_id,
            notification_type=notification_type,
            title=title,
            body=body,
            source_table=source_table,
            source_row_id=source_row_id,
        )
        created += 1
    return created


async def _fetch_existing_notification_keys(
    session: AsyncSession,
    *,
    user_ids: list[UUID],
    notification_type: NotificationType,
    source_table: str,
    source_row_id: UUID,
) -> set[tuple[UUID, NotificationType, str, UUID]]:
    if not user_ids:
        return set()

    rows = await session.execute(
        select(
            Notification.user_id,
            Notification.notification_type,
            Notification.source_table,
            Notification.source_row_id,
        ).where(
            Notification.user_id.in_(user_ids),
            Notification.notification_type == notification_type,
            Notification.source_table == source_table,
            Notification.source_row_id == source_row_id,
        )
    )
    return {
        (user_id, notif_type, table, row_id)
        for user_id, notif_type, table, row_id in rows.all()
    }


def _confidence_audit_payload(score: DeliveryConfidenceScore) -> dict[str, Any]:
    return {
        "id": str(score.id),
        "milestone_id": str(score.milestone_id),
        "score_pct": str(score.score_pct),
        "status": score.status.value,
        "forecast_completion_date": (
            score.forecast_completion_date.isoformat()
            if score.forecast_completion_date is not None
            else None
        ),
        "model_version": score.model_version,
    }


def _scores_payload(scores: DeliveryScoresSnapshot) -> dict[str, Any]:
    return {
        "confidence": str(scores.confidence),
        "risk": str(scores.risk),
        "traffic_light": scores.traffic_light,
        "risk_tier": scores.risk_tier,
        "confidence_status": scores.confidence_status,
        "forecast_completion_date": (
            scores.forecast_completion_date.isoformat()
            if scores.forecast_completion_date is not None
            else None
        ),
        "contributing_causes": scores.contributing_causes,
    }


def confidence_snapshot_from_row(row: DeliveryConfidenceScore) -> ConfidenceSnapshot:
    return ConfidenceSnapshot(
        id=row.id,
        milestone_id=row.milestone_id,
        score_pct=row.score_pct,
        status=row.status.value,
        forecast_completion_date=row.forecast_completion_date,
        model_version=row.model_version,
    )


def risk_alert_snapshot_from_row(row: RiskAlert) -> RiskAlertSnapshot:
    return RiskAlertSnapshot(
        id=row.id,
        alert_type=row.alert_type.value,
        risk_tier=row.risk_tier.value,
        slippage_probability=row.slippage_probability,
        milestone_id=row.milestone_id,
    )
