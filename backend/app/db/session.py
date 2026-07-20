import asyncio
import logging
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.rls import register_rls_event_listeners

settings = get_settings()
logger = logging.getLogger(__name__)

# Supabase session-mode (port 5432) caps total clients (~15 project-wide).
# Keep app concurrency well under that so uvicorn --reload + browser bursts
# cannot trigger EMAXCONNSESSION. This gate is SKIPPED entirely on the
# transaction pooler (port 6543, the default -- see _uses_session_pooler /
# session_scope below): PgBouncer transaction mode fans many client
# connections out over few server connections, so it doesn't need (and
# shouldn't get) this protection.
_SESSION_MODE_MAX_CONCURRENT = 4
_session_semaphore: asyncio.Semaphore | None = None

# Phase 1A (docs/PERF_IMPLEMENTATION_PLAN.md): persistent client-side pool
# sizing for the transaction pooler (port 6543). Supabase's transaction
# pooler tolerates far more client connections than the session pooler, so a
# real pool here is safe; keep it modest relative to the pooler's server-side
# capacity and revisit in Phase 3 if burst testing shows it should change.
_TRANSACTION_POOLER_POOL_SIZE = 10
_TRANSACTION_POOLER_MAX_OVERFLOW = 10
_TRANSACTION_POOLER_POOL_RECYCLE_SECONDS = 1800


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
        # PgBouncer transaction mode hands out its (few) real Postgres server
        # connections to whichever client transaction needs one, so the SAME
        # client-side connection object can be multiplexed across different
        # backend connections/roles/settings between transactions. asyncpg's
        # and SQLAlchemy's prepared-statement caches must stay OFF (unique
        # name per prepare() call) so a client-side connection reused across
        # requests never executes a stale cached statement prepared against a
        # backend connection it no longer holds. This is what makes it safe
        # to hold a real, persistent pool of these connections client-side
        # (see _engine_kwargs) instead of opening a fresh one per request.
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
        # Phase 1A: a real, persistent client-side pool. Previously this was
        # NullPool, which opened and immediately discarded a brand-new
        # connection (and a fresh TLS handshake to the remote AWS eu-west-1
        # Supabase Postgres) on every single request -- a measured ~1s fixed
        # tax per authenticated request with zero reuse benefit, even on
        # back-to-back repeat calls (docs/perf-baseline.md). PgBouncer
        # transaction mode is exactly what makes a persistent pool safe here:
        # each checked-out connection's asyncpg-level statement cache is
        # already disabled above, so there is no stale-prepared-statement
        # risk from reuse. `pool_pre_ping` costs one extra round trip per
        # checkout but guards against a connection PgBouncer/Supabase closed
        # server-side while idle; `pool_recycle` proactively retires
        # connections before that becomes likely.
        kwargs["pool_size"] = _TRANSACTION_POOLER_POOL_SIZE
        kwargs["max_overflow"] = _TRANSACTION_POOLER_MAX_OVERFLOW
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = _TRANSACTION_POOLER_POOL_RECYCLE_SECONDS
        return kwargs

    # Session pooler (port 5432, fallback only -- see .env): do NOT hold a
    # large idle QueuePool — those clients count against Supabase's ~15
    # session cap even when the app is idle, and uvicorn --reload can briefly
    # double them. NullPool + a concurrency gate keeps peak clients bounded.
    # This branch is no longer the default; DATABASE_URL should point at the
    # transaction pooler (port 6543, handled above) unless you have a
    # specific reason to fall back (e.g. a feature that turns out to need a
    # session-scoped `SET`/advisory lock across statements, which PgBouncer
    # transaction mode cannot support).
    logger.warning(
        "DATABASE_URL uses the Supabase SESSION pooler (port 5432), the Phase 1A "
        "fallback path -- not the default. This re-enables the ~1s-per-request "
        "connection-open tax the transaction pooler (port 6543) exists to avoid. "
        "Capping concurrent DB sessions at %s to stay under Supabase's ~15-client cap.",
        _SESSION_MODE_MAX_CONCURRENT,
    )
    kwargs["poolclass"] = NullPool
    return kwargs


class _AppSyncSession(Session):
    """Dedicated sync `Session` subclass (rather than the bare `Session`) so
    the RLS `after_begin` hook registered below is scoped precisely to
    sessions created by this app's `AsyncSessionLocal`, and can't fire for
    some unrelated sync `Session` (e.g. a future script/test) that happens to
    exist in the same process."""


engine = create_async_engine(
    settings.async_database_url,
    **_engine_kwargs(settings.async_database_url),
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, sync_session_class=_AppSyncSession)

# Phase 1A: reapply RLS context (app/db/rls.py) at the start of every
# transaction this app's sessions open, not just the first -- required now
# that connections/sessions are reused across transactions (mid-request
# commits, pooled physical connections) rather than torn down per request.
register_rls_event_listeners(_AppSyncSession)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Open a DB session, gated when using Supabase session-mode pooler
    (no-op gate on the default transaction-pooler path -- see
    _uses_session_pooler)."""
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
