"""Delivery Performance Agent integration for Project Governance."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationSourceType,
    GovernanceEscalationStatus,
    RiskAlert,
    RiskTier,
)
from app.services.scoping import get_visible_project

_RISK_TIER_TO_SEVERITY: dict[RiskTier, GovernanceEscalationSeverity] = {
    RiskTier.LOW: GovernanceEscalationSeverity.LOW,
    RiskTier.MEDIUM: GovernanceEscalationSeverity.MEDIUM,
    RiskTier.HIGH: GovernanceEscalationSeverity.HIGH,
    RiskTier.CRITICAL: GovernanceEscalationSeverity.CRITICAL,
}


async def promote_risk_alert_to_escalation(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    risk_alert_id: UUID,
) -> GovernanceEscalation:
    from app.agents.governance.services.governance_service import assert_can_write_governance

    assert_can_write_governance(current_user)

    alert = (
        await session.execute(
            select(RiskAlert).where(
                RiskAlert.id == risk_alert_id,
                RiskAlert.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if alert is None:
        raise ApiError(404, "NOT_FOUND", "Risk alert was not found.", {"risk_alert_id": str(risk_alert_id)})

    if alert.org_id != current_user.org_id and current_user.role != AppRole.SUPER_ADMIN:
        raise ApiError(404, "NOT_FOUND", "Risk alert was not found.", {"risk_alert_id": str(risk_alert_id)})

    await get_visible_project(session, alert.project_id, current_user)

    existing = (
        await session.execute(
            select(GovernanceEscalation).where(
                GovernanceEscalation.org_id == alert.org_id,
                GovernanceEscalation.source_type == GovernanceEscalationSourceType.DELIVERY_RISK,
                GovernanceEscalation.source_id == alert.id,
                GovernanceEscalation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    if alert.status not in {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}:
        raise ApiError(
            409,
            "RISK_ALERT_NOT_PROMOTABLE",
            "Only open or acknowledged delivery risks can be promoted.",
        )

    severity = _RISK_TIER_TO_SEVERITY.get(alert.risk_tier, GovernanceEscalationSeverity.MEDIUM)
    escalation = GovernanceEscalation(
        org_id=alert.org_id,
        project_id=alert.project_id,
        title=alert.title,
        description=alert.detail,
        severity=severity,
        status=GovernanceEscalationStatus.OPEN,
        raised_by=current_user.id,
        source_type=GovernanceEscalationSourceType.DELIVERY_RISK,
        source_id=alert.id,
    )
    session.add(escalation)
    await session.commit()
    await session.refresh(escalation)
    return escalation
