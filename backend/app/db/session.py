import asyncio
import logging
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Supabase session-mode (port 5432) caps total clients (~15 project-wide).
# Keep app concurrency well under that so uvicorn --reload + browser bursts
# cannot trigger EMAXCONNSESSION.
_SESSION_MODE_MAX_CONCURRENT = 4
_session_semaphore: asyncio.Semaphore | None = None
DatabaseConnectionMode = Literal[
    "direct_postgres",
    "supabase_session_pooler",
    "supabase_transaction_pooler",
]


def _normalized_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _is_supabase_pooler(database_url: str) -> bool:
    host = urlparse(_normalized_url(database_url)).hostname or ""
    return host.endswith("supabase.co") or "pooler.supabase.com" in host


def _is_transaction_pooler(database_url: str) -> bool:
    return ":6543/" in database_url or ":6543?" in database_url


def classify_database_url(database_url: str) -> DatabaseConnectionMode:
    """Classify DB URLs without exposing credentials in logs."""
    if not _is_supabase_pooler(database_url):
        return "direct_postgres"
    if _is_transaction_pooler(database_url):
        return "supabase_transaction_pooler"
    return "supabase_session_pooler"


def _uses_session_pooler(database_url: str) -> bool:
    return classify_database_url(database_url) == "supabase_session_pooler"


def _get_session_semaphore() -> asyncio.Semaphore:
    global _session_semaphore
    if _session_semaphore is None:
        _session_semaphore = asyncio.Semaphore(_SESSION_MODE_MAX_CONCURRENT)
    return _session_semaphore


def _engine_connect_args(database_url: str) -> dict:
    mode = classify_database_url(database_url)
    if mode == "direct_postgres":
        return {}

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    connect_args: dict = {"ssl": ctx}

    if mode == "supabase_transaction_pooler":
        # PgBouncer transaction mode: disable asyncpg + SQLAlchemy prepared-statement caches.
        # Unique names per prepare() call so a pooled connection cannot collide with a
        # prepared statement left behind on a different PgBouncer backend.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"

    return connect_args


def _engine_kwargs(database_url: str) -> dict:
    kwargs: dict = {
        "connect_args": _engine_connect_args(database_url),
    }

    mode = classify_database_url(database_url)
    if mode == "direct_postgres":
        kwargs["pool_pre_ping"] = True
        return kwargs

    if mode == "supabase_transaction_pooler":
        # PgBouncer owns *server*-side pooling, but the client still has to establish its own
        # TCP + TLS + auth handshake to reach it — measured at ~1.5s against
        # aws-0-eu-west-1 from a dev machine. Under NullPool that handshake was paid on
        # every single request (a bare /me cost ~1.65s, essentially all of it connection
        # setup), so keep a small client-side pool and reuse the connections instead.
        #
        # The stale-prepared-statement hazard that motivated NullPool here is already
        # handled independently by _engine_connect_args above: asyncpg's statement cache is
        # disabled and every prepare() gets a unique name, so a reused connection cannot
        # collide with a prepared statement left behind on a different PgBouncer backend.
        #
        # Sized for the dashboard's fan-out: the Operational Tower alone issues 5 section
        # requests in parallel, each holding a connection for its whole request. At
        # pool_size=5 one dashboard load would saturate the pool and the sections would
        # serialize behind each other, undoing the split. Still bounded per worker by
        # pool_size + max_overflow, well under Supabase's caps even with --reload.
        # AsyncAdaptedQueuePool, not QueuePool: the sync pool cannot back an asyncio engine.
        kwargs["poolclass"] = AsyncAdaptedQueuePool
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 10
        # PgBouncer can close an idle client connection from its side; recycle before that
        # is likely and verify on checkout, so a dropped connection surfaces as a cheap
        # reconnect rather than a failed request.
        #
        # pre_ping is not free: measured at ~278ms per checkout from a dev machine against
        # eu-west-1 (a full extra round trip), i.e. ~506ms per request with it vs ~278ms
        # without — against ~1636ms under NullPool, so both are a large win. It stays on
        # because dropping it trades intermittent request failures for that 278ms, and
        # Supabase's client idle timeout here is unverified. Co-located with the database
        # the round trip is ~1ms and the cost is irrelevant.
        kwargs["pool_recycle"] = 900
        kwargs["pool_pre_ping"] = True
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
