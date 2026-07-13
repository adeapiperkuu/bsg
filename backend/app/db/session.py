import asyncio
import logging
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Supabase session-mode (port 5432) caps total clients (~15 project-wide).
# Keep app concurrency well under that so uvicorn --reload + browser bursts
# cannot trigger EMAXCONNSESSION.
_SESSION_MODE_MAX_CONCURRENT = 4
_session_semaphore: asyncio.Semaphore | None = None


def _normalized_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _is_supabase_pooler(database_url: str) -> bool:
    host = urlparse(_normalized_url(database_url)).hostname or ""
    return host.endswith("supabase.co") or "pooler.supabase.com" in host


def _is_transaction_pooler(database_url: str) -> bool:
    return ":6543/" in database_url or ":6543?" in database_url


def _uses_session_pooler(database_url: str) -> bool:
    return _is_supabase_pooler(database_url) and not _is_transaction_pooler(database_url)


def _get_session_semaphore() -> asyncio.Semaphore:
    global _session_semaphore
    if _session_semaphore is None:
        _session_semaphore = asyncio.Semaphore(_SESSION_MODE_MAX_CONCURRENT)
    return _session_semaphore


def _engine_connect_args(database_url: str) -> dict:
    if not _is_supabase_pooler(database_url):
        return {}

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    connect_args: dict = {"ssl": ctx}

    if _is_transaction_pooler(database_url):
        # PgBouncer transaction mode: disable asyncpg + SQLAlchemy prepared-statement caches.
        # Unique names per prepare() call; NullPool ensures connections are not reused across requests.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"

    return connect_args


def _engine_kwargs(database_url: str) -> dict:
    kwargs: dict = {
        "connect_args": _engine_connect_args(database_url),
    }

    if not _is_supabase_pooler(database_url):
        kwargs["pool_pre_ping"] = True
        return kwargs

    if _is_transaction_pooler(database_url):
        # Let Supabase PgBouncer own pooling; avoid stale prepared statements on checkout.
        kwargs["poolclass"] = NullPool
        return kwargs

    # Session pooler (port 5432): do NOT hold a large idle QueuePool — those clients
    # count against Supabase's ~15 session cap even when the app is idle, and
    # uvicorn --reload can briefly double them. NullPool + a concurrency gate
    # keeps peak clients bounded; prefer port 6543 (transaction mode) for prod.
    logger.warning(
        "DATABASE_URL uses Supabase session pooler (port 5432). "
        "Prefer transaction pooler port 6543 to avoid EMAXCONNSESSION. "
        "Capping concurrent DB sessions at %s.",
        _SESSION_MODE_MAX_CONCURRENT,
    )
    kwargs["poolclass"] = NullPool
    return kwargs


engine = create_async_engine(
    settings.async_database_url,
    **_engine_kwargs(settings.async_database_url),
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Open a DB session, gated when using Supabase session-mode pooler."""
    gate = _get_session_semaphore() if _uses_session_pooler(settings.async_database_url) else None
    if gate is not None:
        await gate.acquire()
    try:
        async with AsyncSessionLocal() as session:
            yield session
    finally:
        if gate is not None:
            gate.release()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
