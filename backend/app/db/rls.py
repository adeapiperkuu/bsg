from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(session: AsyncSession, jwt: str) -> None:
    """Set Supabase-compatible per-request JWT claims for Postgres RLS policies.

    DEVELOPMENT_PLAN.md Workstream I / docs/18. Known Bugs.md BUG-001: the
    app's connection role (`postgres`) has BYPASSRLS, so every RLS policy in
    this schema has no effect on the running app without this. `SET LOCAL`
    is transaction-scoped, matching `set_config(..., true)`'s `is_local=true`
    -- both revert automatically at transaction end, which matters because
    this app pools and reuses physical connections (app/db/session.py,
    Supabase session-pooler mode) and a plain `SET ROLE` would leak across
    requests on a reused connection. `authenticated` already has the grants
    it needs (SELECT/INSERT/UPDATE/DELETE on every table, EXECUTE on all RLS
    helper functions) -- this is standard, unused Supabase provisioning, not
    a new grant.
    """
    await session.execute(text("select set_config('request.jwt.claims', :claims, true)"), {"claims": jwt})
    await session.execute(text("SET LOCAL ROLE authenticated"))


async def set_service_role_context(session: AsyncSession) -> None:
    """Explicit system-level RLS bypass for scheduled jobs with no per-user identity.

    DEVELOPMENT_PLAN.md Workstream I / docs/18. Known Bugs.md BUG-005: the two
    scheduled jobs (quality-scan cron, ingestion queue poll) have no JWT to
    derive a per-user identity from, and are meant to operate across every
    organisation. Today that's an accidental side effect of the app's shared
    connection role having BYPASSRLS; this makes the bypass explicit and
    auditable per-session instead, so it keeps working once BYPASSRLS is
    removed for ordinary request-scoped sessions. `SET LOCAL` is
    transaction-scoped, same as `set_rls_context`'s `set_config(..., true)`.
    """
    await session.execute(text("SET LOCAL ROLE service_role"))
