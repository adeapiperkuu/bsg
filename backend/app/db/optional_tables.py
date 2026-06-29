"""Helpers for optional schema tables that may not be migrated yet."""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


def is_undefined_table_error(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", exc)
    name = type(orig).__name__.lower()
    text = str(orig).lower()
    return "undefinedtable" in name or "does not exist" in text


async def query_optional_table(
    session: AsyncSession,
    query: Callable[[], Awaitable[T]],
    default: T,
) -> T:
    """Run a read query, returning default when the backing table is not migrated."""
    try:
        async with session.begin_nested():
            return await query()
    except ProgrammingError as exc:
        if is_undefined_table_error(exc):
            return default
        raise
