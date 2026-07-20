"""Phase 15.2 operational signal stubs for Delivery root-cause inputs.

These loaders return None until timesheets, absenteeism, review queues,
capacity history, and related sources are ingested. The root-cause engine
treats None as data_unavailable and never invents values.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class OperationalSignal:
    """Optional Phase 15.2 severity input (0-100)."""

    value: Decimal
    source: str
    evidence: dict[str, object]


class OperationalSignalProvider(Protocol):
    async def get_timesheet_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...

    async def get_absenteeism_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...

    async def get_review_queue_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...

    async def get_backlog_queue_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...

    async def get_capacity_snapshot_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...

    async def get_dependency_delay_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...

    async def get_scope_volatility_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None: ...


class StubOperationalSignalProvider:
    """No-op provider until Phase 15.2 operational ingestion lands."""

    async def get_timesheet_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None

    async def get_absenteeism_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None

    async def get_review_queue_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None

    async def get_backlog_queue_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None

    async def get_capacity_snapshot_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None

    async def get_dependency_delay_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None

    async def get_scope_volatility_signal(
        self, session: AsyncSession, *, project_id: UUID
    ) -> OperationalSignal | None:
        return None


DEFAULT_OPERATIONAL_SIGNAL_PROVIDER: OperationalSignalProvider = StubOperationalSignalProvider()
