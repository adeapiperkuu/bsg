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
        self.activity_row_count: int | None = None
        self.project_row_count: int | None = None
        self.summary_refresh_required: bool | None = None
        self.summary_refresh_performed: bool | None = None
        self.summary_refresh_ms: float | None = None
        self.summary_rows_refreshed: int | None = None
        self.register_row_count: int | None = None
        self.project_id: str | None = None
        self.authorization_ms: float | None = None
        self.response_bytes: int | None = None
        self.list_row_fetch_ms: float | None = None
        self.enrichment_ms: float | None = None
        self.detail_fetch_ms: float | None = None
        self.returned_row_count: int | None = None
        self.dependency_count: int | None = None
        self.action_count: int | None = None
        self.escalation_count: int | None = None
        self.risk_count: int | None = None
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
        activity_row_count: int | None = None,
        project_row_count: int | None = None,
        summary_refresh_required: bool | None = None,
        summary_refresh_performed: bool | None = None,
        summary_refresh_ms: float | None = None,
        summary_rows_refreshed: int | None = None,
        register_row_count: int | None = None,
        project_id: str | None = None,
        authorization_ms: float | None = None,
        response_bytes: int | None = None,
        list_row_fetch_ms: float | None = None,
        enrichment_ms: float | None = None,
        detail_fetch_ms: float | None = None,
        returned_row_count: int | None = None,
        dependency_count: int | None = None,
        action_count: int | None = None,
        escalation_count: int | None = None,
        risk_count: int | None = None,
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
        if activity_row_count is not None:
            self.activity_row_count = activity_row_count
        if project_row_count is not None:
            self.project_row_count = project_row_count
        if summary_refresh_required is not None:
            self.summary_refresh_required = summary_refresh_required
        if summary_refresh_performed is not None:
            self.summary_refresh_performed = summary_refresh_performed
        if summary_refresh_ms is not None:
            self.summary_refresh_ms = summary_refresh_ms
        if summary_rows_refreshed is not None:
            self.summary_rows_refreshed = summary_rows_refreshed
        if register_row_count is not None:
            self.register_row_count = register_row_count
        if project_id is not None:
            self.project_id = project_id
        if authorization_ms is not None:
            self.authorization_ms = authorization_ms
        if response_bytes is not None:
            self.response_bytes = response_bytes
        if list_row_fetch_ms is not None:
            self.list_row_fetch_ms = list_row_fetch_ms
        if enrichment_ms is not None:
            self.enrichment_ms = enrichment_ms
        if detail_fetch_ms is not None:
            self.detail_fetch_ms = detail_fetch_ms
        if returned_row_count is not None:
            self.returned_row_count = returned_row_count
        if dependency_count is not None:
            self.dependency_count = dependency_count
        if action_count is not None:
            self.action_count = action_count
        if escalation_count is not None:
            self.escalation_count = escalation_count
        if risk_count is not None:
            self.risk_count = risk_count

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
        if self.activity_row_count is not None:
            extra["activity_row_count"] = self.activity_row_count
            parts.append("activity_row_count=%s")
            args.append(self.activity_row_count)
        if self.project_row_count is not None:
            extra["project_row_count"] = self.project_row_count
            parts.append("project_row_count=%s")
            args.append(self.project_row_count)
        if self.summary_refresh_required is not None:
            extra["summary_refresh_required"] = self.summary_refresh_required
            parts.append("summary_refresh_required=%s")
            args.append(self.summary_refresh_required)
        if self.summary_refresh_performed is not None:
            extra["summary_refresh_performed"] = self.summary_refresh_performed
            parts.append("summary_refresh_performed=%s")
            args.append(self.summary_refresh_performed)
        if self.summary_refresh_ms is not None:
            extra["summary_refresh_ms"] = self.summary_refresh_ms
            parts.append("summary_refresh_ms=%s")
            args.append(self.summary_refresh_ms)
        if self.summary_rows_refreshed is not None:
            extra["summary_rows_refreshed"] = self.summary_rows_refreshed
            parts.append("summary_rows_refreshed=%s")
            args.append(self.summary_rows_refreshed)
        if self.register_row_count is not None:
            extra["register_row_count"] = self.register_row_count
            parts.append("register_row_count=%s")
            args.append(self.register_row_count)
        for field_name in (
            "project_id",
            "authorization_ms",
            "response_bytes",
            "list_row_fetch_ms",
            "enrichment_ms",
            "detail_fetch_ms",
            "returned_row_count",
            "dependency_count",
            "action_count",
            "escalation_count",
            "risk_count",
        ):
            value = getattr(self, field_name)
            if value is not None:
                extra[field_name] = value
                parts.append(f"{field_name}=%s")
                args.append(value)
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
