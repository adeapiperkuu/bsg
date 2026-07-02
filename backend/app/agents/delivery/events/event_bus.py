"""Minimal async-safe event bus for delivery domain events."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

EventT = TypeVar("EventT")
EventHandler = Callable[[AsyncSession, Any], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class HandlerExecutionResult:
    """Execution outcome for one handler invocation."""

    handler: str
    success: bool
    result: Any | None
    error: str | None
    error_type: str | None = None


class EventBus:
    """In-process event bus dispatching handlers for a shared database session."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Register an async handler for a domain event type."""
        self._handlers[event_type].append(handler)

    async def emit(self, session: AsyncSession, event: Any) -> list[HandlerExecutionResult]:
        """Dispatch event to all subscribed handlers.

        Each handler runs inside its own SAVEPOINT so that a failure rolls back
        only that handler's writes and leaves the outer transaction intact.
        """
        handlers = self._handlers.get(type(event), [])
        results: list[HandlerExecutionResult] = []
        for handler in handlers:
            try:
                async with session.begin_nested():
                    result = await handler(session, event)
                results.append(
                    HandlerExecutionResult(
                        handler=handler.__name__,
                        success=True,
                        result=result,
                        error=None,
                    )
                )
            except Exception as exc:
                # Full exception (with traceback) goes to the server log only — never to the
                # API response, which only carries the sanitized handler name + exception type.
                logger.exception(
                    "Handler %s raised for event %s",
                    handler.__name__,
                    type(event).__name__,
                )
                results.append(
                    HandlerExecutionResult(
                        handler=handler.__name__,
                        success=False,
                        result=None,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                )
        return results


_delivery_event_bus = EventBus()


def get_delivery_event_bus() -> EventBus:
    """Return the process-wide delivery event bus."""
    return _delivery_event_bus


async def emit_event(session: AsyncSession, event: Any) -> list[HandlerExecutionResult]:
    """Emit a domain event on the delivery event bus."""
    return await get_delivery_event_bus().emit(session, event)
