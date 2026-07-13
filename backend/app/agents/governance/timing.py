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
        self.execute_count: int | None = None
        self.cache_hit: bool | None = None
        self.limit: int | None = None
        self.offset: int | None = None
        self.cache_eligible: bool | None = None
        self.cache_shape: str | None = None
        self.filtered: bool | None = None
        self.cache_scope: str | None = None
        self._started = perf_counter()
        self._db_depth = 0

    def add_db_ms(self, elapsed_ms: float) -> None:
        self.db_ms += elapsed_ms

    def record_meta(
        self,
        *,
        execute_count: int | None = None,
        cache_hit: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        cache_eligible: bool | None = None,
        cache_shape: str | None = None,
        filtered: bool | None = None,
        cache_scope: str | None = None,
    ) -> None:
        """Attach optional profiling fields without changing response payloads."""
        if execute_count is not None:
            self.execute_count = execute_count
        if cache_hit is not None:
            self.cache_hit = cache_hit
        if limit is not None:
            self.limit = limit
        if offset is not None:
            self.offset = offset
        if cache_eligible is not None:
            self.cache_eligible = cache_eligible
        if cache_shape is not None:
            self.cache_shape = cache_shape
        if filtered is not None:
            self.filtered = filtered
        if cache_scope is not None:
            self.cache_scope = cache_scope

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
        db_ms = round(self.db_ms, 1)
        serialization_ms = self.serialization_ms
        total_ms = self.total_ms
        extra: dict[str, object] = {
            "endpoint": self.endpoint,
            "org_id": self.org_id,
            "role": self.role,
            "row_count": self.row_count,
            "db_ms": db_ms,
            "serialization_ms": serialization_ms,
            "total_ms": total_ms,
        }
        parts = [
            "governance_endpoint_timing endpoint=%s role=%s org_id=%s row_count=%s "
            "total_ms=%s db_ms=%s serialization_ms=%s"
        ]
        args: list[object] = [
            self.endpoint,
            self.role,
            self.org_id,
            self.row_count,
            total_ms,
            db_ms,
            serialization_ms,
        ]
        if self.execute_count is not None:
            extra["execute_count"] = self.execute_count
            parts.append("execute_count=%s")
            args.append(self.execute_count)
        if self.cache_hit is not None:
            extra["cache_hit"] = self.cache_hit
            parts.append("cache_hit=%s")
            args.append(self.cache_hit)
        if self.limit is not None:
            extra["limit"] = self.limit
            parts.append("limit=%s")
            args.append(self.limit)
        if self.offset is not None:
            extra["offset"] = self.offset
            parts.append("offset=%s")
            args.append(self.offset)
        if self.cache_eligible is not None:
            extra["cache_eligible"] = self.cache_eligible
            parts.append("cache_eligible=%s")
            args.append(self.cache_eligible)
        if self.cache_shape is not None:
            extra["cache_shape"] = self.cache_shape
            parts.append("cache_shape=%s")
            args.append(self.cache_shape)
        if self.filtered is not None:
            extra["filtered"] = self.filtered
            parts.append("filtered=%s")
            args.append(self.filtered)
        if self.cache_scope is not None:
            extra["cache_scope"] = self.cache_scope
            parts.append("cache_scope=%s")
            args.append(self.cache_scope)
        logger.info(" ".join(parts), *args, extra=extra)


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
            limit = kwargs.get("limit")
            offset = kwargs.get("offset")
            if isinstance(limit, int) or isinstance(offset, int):
                timer.record_meta(
                    limit=limit if isinstance(limit, int) else None,
                    offset=offset if isinstance(offset, int) else None,
                )
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
