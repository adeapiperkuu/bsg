from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import AppRole, Notification, NotificationType, User

GOVERNANCE_NOTIFICATION_ROLES = {
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
}


async def _governance_recipients(
    session: AsyncSession,
    *,
    org_id: UUID,
) -> list[User]:
    rows = (
        await session.execute(
            select(User).where(
                User.org_id == org_id,
                User.role.in_(GOVERNANCE_NOTIFICATION_ROLES),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
    ).scalars()
    return list(rows)


async def create_governance_notification(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    org_id: UUID,
    title: str,
    body: str,
    source_table: str,
    source_row_id: UUID,
    project_id: UUID | None = None,
) -> None:
    recipients = await _governance_recipients(session, org_id=org_id)
    notification_body = (
        f"{body}\n"
        "Priority: high\n"
        f"Project: {project_id or 'portfolio'}\n"
        f"Created by: {current_user.email}"
    )
    for user in recipients:
        exists = (
            await session.execute(
                select(Notification.id).where(
                    Notification.user_id == user.id,
                    Notification.notification_type == NotificationType.SYSTEM,
                    Notification.source_table == source_table,
                    Notification.source_row_id == source_row_id,
                )
            )
        ).scalar_one_or_none()
        if exists:
            continue
        session.add(
            Notification(
                user_id=user.id,
                org_id=org_id,
                notification_type=NotificationType.SYSTEM,
                title=title,
                body=notification_body,
                source_table=source_table,
                source_row_id=source_row_id,
            )
        )
