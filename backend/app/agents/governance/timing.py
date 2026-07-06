from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec, TypeVar

from fastapi.routing import APIRoute
from starlette.responses import Response

from app.core.security import CurrentUser
from app.schemas.common import DataResponse, ListResponse

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_active_timer: ContextVar[GovernanceEndpointTimer | None] = ContextVar(
    "governance_endpoint_timer",
    default=None,
)


class GovernanceEndpointTimer:
    """Per-request governance endpoint latency tracker."""

    def __init__(self, endpoint: str, current_user: CurrentUser | None) -> None:
        self.endpoint = endpoint
        self.org_id = str(current_user.org_id) if current_user and current_user.org_id else None
        self.role = current_user.role.value if current_user else "unknown"
        self.row_count = 0
        self.db_ms = 0.0
        self._started = perf_counter()
        self._db_depth = 0

    def add_db_ms(self, elapsed_ms: float) -> None:
        self.db_ms += elapsed_ms

    @property
    def serialization_ms(self) -> float:
        total_ms = (perf_counter() - self._started) * 1000
        return max(round(total_ms - self.db_ms, 1), 0.0)

    @property
    def total_ms(self) -> float:
        return round((perf_counter() - self._started) * 1000, 1)

    def finish(self, *, row_count: int | None = None) -> None:
        if row_count is not None:
            self.row_count = row_count
        logger.info(
            "governance_endpoint_timing",
            extra={
                "endpoint": self.endpoint,
                "org_id": self.org_id,
                "role": self.role,
                "row_count": self.row_count,
                "db_ms": round(self.db_ms, 1),
                "serialization_ms": self.serialization_ms,
                "total_ms": self.total_ms,
            },
        )


def get_governance_timer() -> GovernanceEndpointTimer | None:
    return _active_timer.get()


def _set_governance_timer(timer: GovernanceEndpointTimer | None) -> Token:
    return _active_timer.set(timer)


def _reset_governance_timer(token: Token) -> None:
    _active_timer.reset(token)


@asynccontextmanager
async def governance_db_section() -> AsyncIterator[None]:
    timer = get_governance_timer()
    if timer is None:
        yield
        return

    timer._db_depth += 1
    if timer._db_depth > 1:
        try:
            yield
        finally:
            timer._db_depth -= 1
        return

    started = perf_counter()
    try:
        yield
    finally:
        timer.add_db_ms((perf_counter() - started) * 1000)
        timer._db_depth -= 1


def governance_db_timed(
    func: Callable[P, Any],
) -> Callable[P, Any]:
    """Mark an async governance service function as DB-timed when a request timer is active."""

    if not callable(func):
        raise TypeError("governance_db_timed expects a callable")

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        async with governance_db_section():
            return await func(*args, **kwargs)

    return wrapper


def _find_current_user(args: tuple[Any, ...], kwargs: dict[str, Any]) -> CurrentUser | None:
    user = kwargs.get("current_user")
    if isinstance(user, CurrentUser):
        return user
    for arg in args:
        if isinstance(arg, CurrentUser):
            return arg
    return None


def row_count_from_result(result: Any) -> int:
    if isinstance(result, ListResponse):
        return len(result.data)
    if isinstance(result, DataResponse):
        data = result.data
        if isinstance(data, list):
            return len(data)
        return 0 if data is None else 1
    if isinstance(result, Response):
        return 0
    return 0


def instrument_governance_endpoint(endpoint: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        if not callable(func):
            return func

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            timer = GovernanceEndpointTimer(endpoint, _find_current_user(args, kwargs))
            token = _set_governance_timer(timer)
            try:
                result = await func(*args, **kwargs)
                timer.finish(row_count=row_count_from_result(result))
                return result
            except Exception:
                timer.finish()
                raise
            finally:
                _reset_governance_timer(token)

        return async_wrapper  # type: ignore[return-value]

    return decorator


def instrument_governance_routes(router: Any) -> None:
    """Wrap all governance APIRoute handlers with endpoint timing instrumentation."""
    for route in router.routes:
        if not isinstance(route, APIRoute) or route.endpoint is None:
            continue
        methods = ",".join(sorted(route.methods or []))
        endpoint_name = f"{methods} {route.path}"
        route.endpoint = instrument_governance_endpoint(endpoint_name)(route.endpoint)
