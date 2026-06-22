from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(session: AsyncSession, jwt: str) -> None:
    """Set Supabase-compatible per-request JWT claims for Postgres RLS policies."""
    await session.execute(text("select set_config('request.jwt.claims', :claims, true)"), {"claims": jwt})
