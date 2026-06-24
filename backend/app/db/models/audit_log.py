"""Append-only audit log for delivery and platform state transitions."""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, CreatedAt, UuidPrimaryKey


class AuditLog(Base, UuidPrimaryKey, CreatedAt):
    """Immutable audit record for domain events and state changes."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("audit_logs_org_id_idx", "org_id"),
        Index("audit_logs_project_id_idx", "project_id"),
        Index("audit_logs_event_type_idx", "event_type"),
        Index("audit_logs_created_at_idx", "created_at"),
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organisations.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
