from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification, NotificationType


async def create_notification(
    session: AsyncSession,
    *,
    user_id,
    org_id,
    notification_type: NotificationType,
    title: str,
    body: str,
    source_table: str | None = None,
    source_row_id=None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        org_id=org_id,
        notification_type=notification_type,
        title=title,
        body=body,
        source_table=source_table,
        source_row_id=source_row_id,
    )
    session.add(notification)
    await session.flush()
    return notification
