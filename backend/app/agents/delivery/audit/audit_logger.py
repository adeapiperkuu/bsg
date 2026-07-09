"""Append-only audit logging for delivery domain events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog


class AuditLogger:
    """Persist immutable audit records for meaningful state transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        org_id: UUID,
        project_id: UUID | None = None,
    ) -> AuditLog:
        """Append a single audit log entry."""
        entry = AuditLog(
            org_id=org_id,
            project_id=project_id,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(entry)
        return entry
