import ssl
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _engine_connect_args(database_url: str) -> dict:
    host = urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://")).hostname or ""
    if not (host.endswith("supabase.co") or "pooler.supabase.com" in host):
        return {}

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return {"ssl": ctx}


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_engine_connect_args(settings.database_url),
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
