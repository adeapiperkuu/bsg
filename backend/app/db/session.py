import ssl
from collections.abc import AsyncIterator
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


def _normalized_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _is_supabase_pooler(database_url: str) -> bool:
    host = urlparse(_normalized_url(database_url)).hostname or ""
    return host.endswith("supabase.co") or "pooler.supabase.com" in host


def _is_transaction_pooler(database_url: str) -> bool:
    return ":6543/" in database_url or ":6543?" in database_url


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

    # Session pooler (port 5432): app-side pool; prepared statements are supported.
    kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_size": 5,
            "max_overflow": 5,
            "pool_recycle": 300,
            "pool_timeout": 30,
        }
    )
    return kwargs


engine = create_async_engine(
    settings.async_database_url,
    **_engine_kwargs(settings.async_database_url),
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
