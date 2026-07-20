from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

# Perf: `SET LOCAL ROLE authenticated` and `set_config('request.jwt.claims', ...,
# true)` were originally two separate round trips. Against the remote Supabase
# DB (AWS eu-west-1) each round trip alone costs ~170-190ms regardless of
# connection pooling (pooling removes connection-SETUP cost, not per-query
# network RTT -- confirmed empirically while verifying Phase 1A), so on every
# authenticated request this was a fixed, avoidable ~170-190ms tax. Postgres's
# `role` GUC is exactly what `SET ROLE`/`SET LOCAL ROLE` sets under the hood
# (`SHOW role` reflects it), so `set_config('role', 'authenticated', true)` is
# semantically identical to `SET LOCAL ROLE authenticated` -- same is_local=true
# transaction-scoped revert semantics -- and can be issued in the SAME
# `select set_config(...), set_config(...)` statement as the claims, for one
# round trip instead of two. Verified against the live DB: role reads back as
# `authenticated` within the transaction and reverts to the connection default
# in a subsequent transaction.
_SET_CLAIMS_AND_ROLE_SQL = text(
    "select set_config('request.jwt.claims', :claims, true), set_config('role', 'authenticated', true)"
)

# Phase 1A (docs/PERF_IMPLEMENTATION_PLAN.md): request-scoped JWT claims, kept
# in a contextvar so RLS context can be *reapplied automatically* to every
# transaction opened on this asyncio Task -- not just the first. This closes
# a gap that pooling makes much more likely to matter: `SET LOCAL ROLE` /
# `set_config(..., true)` are transaction-scoped and revert on `commit()`
# (see docstring below), so a handler that commits mid-request and then
# issues another query (e.g. `PATCH /me/notifications`: `session.commit()`
# followed by `session.refresh(notification)`) would otherwise run that
# later query with NO RLS context at all on the reused connection -- i.e. as
# the bypassing `postgres` role. Verified empirically against the real DB
# (see the smoke test used to validate this mechanism before it was wired
# in): without the `after_begin` hook below, a post-commit query on the same
# session/connection silently reverted from role `authenticated` back to
# `postgres`. With the hook, it does not.
#
# Each incoming ASGI request is handled in its own asyncio Task (uvicorn
# creates one per request), and a new Task's context is a snapshot taken at
# Task-creation time -- mutations a Task makes to a contextvar are invisible
# to sibling/future Tasks. So setting this per request-handling Task cannot
# leak claims from one request into another; it only makes those claims
# available to further transactions/sessions opened *within that same task*
# (including, deliberately, future concurrent per-loader sessions from a
# `asyncio.gather` -- child tasks inherit a copy of the parent's context).
_request_jwt_claims: ContextVar[str | None] = ContextVar("_request_jwt_claims", default=None)


async def set_rls_context(session: AsyncSession, jwt: str) -> None:
    """Set Supabase-compatible per-request JWT claims for Postgres RLS policies.

    DEVELOPMENT_PLAN.md Workstream I / docs/18. Known Bugs.md BUG-001: the
    app's connection role (`postgres`) has BYPASSRLS, so every RLS policy in
    this schema has no effect on the running app without this. `SET LOCAL`
    is transaction-scoped, matching `set_config(..., true)`'s `is_local=true`
    -- both revert automatically at transaction end, which matters because
    this app pools and reuses physical connections (app/db/session.py,
    Supabase transaction-pooler mode) and a plain `SET ROLE` would leak
    across requests on a reused connection. `authenticated` already has the
    grants it needs (SELECT/INSERT/UPDATE/DELETE on every table, EXECUTE on
    all RLS helper functions) -- this is standard, unused Supabase
    provisioning, not a new grant.

    Applies immediately to the current transaction (unchanged behaviour),
    AND records `jwt` in `_request_jwt_claims` so `_reapply_rls_on_begin`
    (registered via `register_rls_event_listeners`) can reapply the same
    claims automatically the next time this task opens a new transaction --
    e.g. after a mid-request `session.commit()`.
    """
    await session.execute(_SET_CLAIMS_AND_ROLE_SQL, {"claims": jwt})
    _request_jwt_claims.set(jwt)


def _reapply_rls_on_begin(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    """`SessionEvents.after_begin` hook: reapply this task's RLS claims (if
    any) at the start of EVERY transaction a session opens, not just the
    first -- see `_request_jwt_claims` above for why this matters.

    A no-op when nothing has called `set_rls_context` on this asyncio Task
    (unauthenticated requests, background jobs using `set_service_role_context`
    instead -- see its docstring), so this never overrides those paths.

    ORM session events are always synchronous, even for `AsyncSession` (this
    fires from within the greenlet the async extension spawns for whatever
    operation is triggering the new transaction), so per SQLAlchemy's own
    `after_begin` docs: use the sync `Connection` provided here, not the
    `Session`/`AsyncSession`, and do not `await` in this function.
    """
    claims = _request_jwt_claims.get()
    if claims is None:
        return
    connection.execute(_SET_CLAIMS_AND_ROLE_SQL, {"claims": claims})


def register_rls_event_listeners(sync_session_class: type[Session]) -> None:
    """Wire `_reapply_rls_on_begin` to fire on every `after_begin` for
    sessions created from `sync_session_class` -- the sync `Session` class
    backing this app's `AsyncSessionLocal` (see `app/db/session.py`, the
    only caller). Idempotent-ish in practice (called once at import time)."""
    event.listens_for(sync_session_class, "after_begin")(_reapply_rls_on_begin)
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
