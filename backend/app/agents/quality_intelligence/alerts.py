from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.drift import DriftResult
from app.agents.quality_intelligence.rework_metrics import compute_rework_impact
from app.agents.quality_intelligence.signals import mirror_quality_risk_signal
from app.agents.quality_intelligence.root_cause import RootCauseResult
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    Notification,
    NotificationType,
    QualitySnapshot,
    RiskAlert,
    RiskTier,
    User,
)


async def create_drift_risk_alert(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    drift: DriftResult,
    *,
    root_cause: RootCauseResult | None = None,
) -> RiskAlert | None:
    if not drift.has_drift:
        return None

    # Idempotency: dedup by source_table + source_row_id (the snapshot that triggered this alert).
    existing = (
        await session.execute(
            select(RiskAlert).where(
                RiskAlert.project_id == snapshot.project_id,
                RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                RiskAlert.deleted_at.is_(None),
                RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                RiskAlert.source_table == "quality_snapshots",
                RiskAlert.source_row_id == snapshot.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    title = f"Quality drift — team {snapshot.team_id} W{snapshot.iso_week}"
    detail_parts = [drift.detail or "Quality threshold breach detected"]
    if root_cause and root_cause.primary_driver:
        detail_parts.append(f"Primary driver: {root_cause.primary_driver}")

    contributing = dict(drift.contributing_causes or {})
    if root_cause:
        contributing["primary_driver"] = root_cause.primary_driver or "undetermined"
        contributing["confidence"] = root_cause.confidence

    contributing["quality_risk_payload"] = {
        "signal_type": "quality_risk",
        "severity": drift.severity.value,
        "rework_rate_pct": str(snapshot.rework_rate_pct) if snapshot.rework_rate_pct is not None else None,
        "hold_recommended": drift.severity in {RiskTier.HIGH, RiskTier.CRITICAL},
        "affected_team_id": str(snapshot.team_id),
        "iso_week": snapshot.iso_week,
        "iso_year": snapshot.iso_year,
    }

    rework_impact = await compute_rework_impact(
        session,
        snapshot.project_id,
        iso_year=snapshot.iso_year,
        iso_week=snapshot.iso_week,
    )
    contributing["quality_risk_payload"].update(
        {
            "rework_volume_units": rework_impact["rework_volume_units"],
            "rework_time_estimate_days": rework_impact["rework_time_estimate_days"],
            "affected_batch_ids": rework_impact["affected_batch_ids"],
        }
    )

    alert = RiskAlert(
        project_id=snapshot.project_id,
        org_id=snapshot.org_id,
        alert_type=AlertType.QUALITY_DRIFT,
        risk_tier=drift.severity,
        title=title,
        detail=" | ".join(detail_parts),
        contributing_causes=contributing,
        status=AlertStatus.OPEN,
        source_table="quality_snapshots",
        source_row_id=snapshot.id,
    )
    session.add(alert)
    await session.flush()

    payload = contributing.get("quality_risk_payload")
    if payload:
        await mirror_quality_risk_signal(
            session,
            project_id=snapshot.project_id,
            org_id=snapshot.org_id,
            alert_id=alert.id,
            quality_risk_payload=payload,
        )

    return alert


async def notify_quality_drift(
    session: AsyncSession,
    org_id: UUID,
    risk_alert: RiskAlert,
    snapshot: QualitySnapshot,
) -> list[Notification]:
    existing = (
        await session.execute(
            select(Notification).where(
                Notification.org_id == org_id,
                Notification.notification_type == NotificationType.QUALITY_DRIFT_DETECTED,
                Notification.source_table == "risk_alerts",
                Notification.source_row_id == risk_alert.id,
            )
        )
    ).scalars()
    if list(existing):
        return []

    dm_users = (
        await session.execute(
            select(User).where(
                User.org_id == org_id,
                User.role == AppRole.DELIVERY_MANAGER,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
    ).scalars()

    notifications: list[Notification] = []
    for user in dm_users:
        note = Notification(
            user_id=user.id,
            org_id=org_id,
            notification_type=NotificationType.QUALITY_DRIFT_DETECTED,
            title=risk_alert.title,
            body=risk_alert.detail,
            source_table="risk_alerts",
            source_row_id=risk_alert.id,
        )
        session.add(note)
        notifications.append(note)

    await session.flush()
    return notifications
