from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.services.governance_service import (
    invalidate_governance_read_caches_after_commit,
)
from app.agents.governance.services.notification_service import create_governance_notification
from app.agents.governance.services.project_governance_summary_service import (
    refresh_project_governance_summary,
)
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationSourceType,
    GovernanceEscalationStatus,
    Project,
    RiskAlert,
    RiskTier,
    User,
)

logger = logging.getLogger(__name__)

_RISK_TIER_TO_SEVERITY: dict[RiskTier, GovernanceEscalationSeverity] = {
    RiskTier.LOW: GovernanceEscalationSeverity.LOW,
    RiskTier.MEDIUM: GovernanceEscalationSeverity.MEDIUM,
    RiskTier.HIGH: GovernanceEscalationSeverity.HIGH,
    RiskTier.CRITICAL: GovernanceEscalationSeverity.CRITICAL,
}


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


def _should_auto_escalate(alert: RiskAlert, *, now: datetime) -> tuple[bool, int]:
    """Return (should_escalate, business_days_open). Critical escalates immediately."""
    biz_days = business_days_between(alert.created_at, now)
    if alert.risk_tier == RiskTier.CRITICAL:
        return True, biz_days
    return biz_days > 5, biz_days


async def _system_actor_for_org(session: AsyncSession, org_id) -> CurrentUser | None:
    user = (
        await session.execute(
            select(User)
            .where(
                User.org_id == org_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.role.in_(
                    {
                        AppRole.DELIVERY_MANAGER,
                        AppRole.BSG_LEADERSHIP,
                        AppRole.SUPER_ADMIN,
                    }
                ),
            )
            .order_by(User.role.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if user is None:
        return None
    return CurrentUser(
        id=user.id,
        org_id=org_id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )


async def check_quality_escalations(session: AsyncSession) -> int:
    """Promote unresolved quality drift into the governance escalation register (BR-06).

    Critical drift escalates immediately. Otherwise escalate after >5 business days.
    Creates `governance_escalations` (source_type=quality_risk) + a follow-up action.
    Never auto-publishes to clients (`client_visible` stays false).
    """
    settings = get_settings()
    if not settings.governance_quality_auto_escalation_enabled:
        return 0

    now = datetime.now(timezone.utc)

    open_alerts = list(
        (
            await session.execute(
                select(RiskAlert, Project)
                .join(Project, RiskAlert.project_id == Project.id)
                .where(
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
            )
        ).all()
    )

    created = 0
    touched_orgs: set = set()
    for alert, project in open_alerts:
        should_escalate, biz_days = _should_auto_escalate(alert, now=now)
        if not should_escalate:
            continue

        existing = (
            await session.execute(
                select(GovernanceEscalation).where(
                    GovernanceEscalation.org_id == project.org_id,
                    GovernanceEscalation.source_type
                    == GovernanceEscalationSourceType.QUALITY_RISK,
                    GovernanceEscalation.source_id == alert.id,
                    GovernanceEscalation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        severity = _RISK_TIER_TO_SEVERITY.get(alert.risk_tier, GovernanceEscalationSeverity.HIGH)
        title = (
            f"Quality escalation — unresolved drift ({biz_days} business days)"
            if alert.risk_tier != RiskTier.CRITICAL
            else "Quality escalation — critical drift"
        )
        description = (
            f"Quality drift alert '{alert.title}' has been open for {biz_days} business days. "
            "Governance action required."
            if alert.risk_tier != RiskTier.CRITICAL
            else (
                f"Critical quality drift alert '{alert.title}' requires immediate governance "
                "attention."
            )
        )

        actor = await _system_actor_for_org(session, project.org_id)
        escalation = GovernanceEscalation(
            org_id=project.org_id,
            project_id=project.id,
            title=title,
            description=description,
            severity=severity,
            status=GovernanceEscalationStatus.OPEN,
            raised_by=actor.id if actor else None,
            source_type=GovernanceEscalationSourceType.QUALITY_RISK,
            source_id=alert.id,
            client_visible=False,
        )
        session.add(escalation)
        await session.flush()

        action_fingerprint = str(alert.id)
        existing_action = (
            await session.execute(
                select(GovernanceAction).where(
                    GovernanceAction.project_id == project.id,
                    GovernanceAction.title.like(f"%{action_fingerprint}%"),
                    GovernanceAction.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_action is None:
            session.add(
                GovernanceAction(
                    project_id=project.id,
                    org_id=project.org_id,
                    title=f"Resolve quality drift: {alert.title} [{action_fingerprint}]",
                    description=description,
                    due_date=date.today() + timedelta(days=3),
                    status=GovernanceActionStatus.OPEN,
                    created_by=actor.id if actor else None,
                )
            )

        if actor is not None and severity == GovernanceEscalationSeverity.CRITICAL:
            await create_governance_notification(
                session,
                actor,
                org_id=escalation.org_id,
                project_id=escalation.project_id,
                title="Critical quality escalation created",
                body=escalation.title,
                source_table="governance_escalations",
                source_row_id=escalation.id,
            )

        await refresh_project_governance_summary(session, escalation.org_id, escalation.project_id)
        touched_orgs.add(escalation.org_id)
        created += 1

    if created:
        await session.commit()
        for org_id in touched_orgs:
            invalidate_governance_read_caches_after_commit(org_id=org_id)
        logger.info("Quality auto-escalation created %s governance escalation(s)", created)
    else:
        await session.flush()

    return created
