from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models.audit_log import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def governance_snapshot(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _jsonable(getattr(row, field, None)) for field in fields}


async def log_governance_event(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    event_type: str,
    org_id: UUID,
    project_id: UUID | None = None,
    source_table: str | None = None,
    source_id: UUID | None = None,
    previous_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        org_id=org_id,
        project_id=project_id,
        event_type=f"governance.{event_type}",
        payload={
            "actor_user_id": str(current_user.id),
            "actor_role": current_user.role.value,
            "source_table": source_table,
            "source_id": str(source_id) if source_id else None,
            "previous_values": _jsonable(previous_values or {}),
            "new_values": _jsonable(new_values or {}),
            "metadata": _jsonable(metadata or {}),
        },
    )
    session.add(entry)
    await session.flush()
    return entry
