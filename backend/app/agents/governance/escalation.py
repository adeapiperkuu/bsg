from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AlertStatus,
    AlertType,
    GovernanceAction,
    Project,
    RiskAlert,
    RiskTier,
)


def business_days_between(start: datetime, end: datetime) -> int:
    """Count weekdays between two datetimes (exclusive of end day)."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    current = start.date()
    end_date = end.date()
    days = 0
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


async def check_quality_escalations(session: AsyncSession) -> int:
    """Escalate quality drift alerts open > 5 business days to governance register."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=7)  # fallback window for alerts without precise biz-day tracking

    open_alerts = list(
        (
            await session.execute(
                select(RiskAlert, Project)
                .join(Project, RiskAlert.project_id == Project.id)
                .where(
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                    RiskAlert.created_at <= threshold,
                )
            )
        ).all()
    )

    created = 0
    for alert, project in open_alerts:
        biz_days = business_days_between(alert.created_at, now)
        if biz_days <= 5:
            continue

        existing_escalation = (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project.id,
                    RiskAlert.alert_type == AlertType.QUALITY_ESCALATION,
                    RiskAlert.source_table == "risk_alerts",
                    RiskAlert.source_row_id == alert.id,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
            )
        ).scalar_one_or_none()
        if existing_escalation:
            continue

        escalation_alert = RiskAlert(
            project_id=project.id,
            org_id=project.org_id,
            alert_type=AlertType.QUALITY_ESCALATION,
            risk_tier=RiskTier.HIGH,
            title=f"Quality escalation — unresolved drift ({biz_days} business days)",
            detail=(
                f"Quality drift alert '{alert.title}' has been open for {biz_days} business days. "
                "Governance action required."
            ),
            status=AlertStatus.OPEN,
            source_table="risk_alerts",
            source_row_id=alert.id,
            contributing_causes={"original_alert_id": str(alert.id), "business_days_open": biz_days},
        )
        session.add(escalation_alert)
        await session.flush()

        existing_action = (
            await session.execute(
                select(GovernanceAction).where(
                    GovernanceAction.project_id == project.id,
                    GovernanceAction.title.like(f"%{alert.id}%"),
                )
            )
        ).scalar_one_or_none()
        if not existing_action:
            session.add(
                GovernanceAction(
                    project_id=project.id,
                    org_id=project.org_id,
                    title=f"Resolve quality drift: {alert.title}",
                    due_date=date.today() + timedelta(days=3),
                    status="open",
                    priority="high",
                )
            )
        created += 1

    await session.flush()
    return created
