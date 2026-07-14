"""Proves the *actual* production code path, not the test harness's hand-rolled
mirror of it: `app/db/rls.py:set_rls_context` is what every real authenticated
request calls (via `app/core/security.py`). Every other test in this package
calls `conftest.py`'s own `switch_to_authenticated`/`as_user` helpers, which
replicate what `set_rls_context` is supposed to do but never call the real
function. This file closes that gap for DEVELOPMENT_PLAN.md Workstream I: it
opens a session the same way a real request does (`session_scope()`, the
app's normal `postgres`/BYPASSRLS connection role) and calls the unmodified
`set_rls_context` directly, confirming its `SET LOCAL ROLE authenticated`
line actually switches enforcement on for that session -- not just that a
manually-issued `SET LOCAL ROLE authenticated` would.

Opt-in via `pytest --run-live-rls`, same as the rest of this package.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.rls import set_rls_context
from tests.rls.conftest import Seed


async def test_real_set_rls_context_enforces_client_project_scoping(
    rls_conn: AsyncSession, seed_data: Seed
) -> None:
    conn = rls_conn
    await set_rls_context(conn, json.dumps({"sub": str(seed_data.client_assigned)}))

    result = await conn.execute(text("SELECT id FROM projects"))
    visible = {row[0] for row in result.all()}
    assert visible == {seed_data.project_a1}


async def test_real_set_rls_context_blocks_unassigned_client(rls_conn: AsyncSession, seed_data: Seed) -> None:
    conn = rls_conn
    await set_rls_context(conn, json.dumps({"sub": str(seed_data.client_unassigned)}))

    result = await conn.execute(text("SELECT id FROM projects"))
    assert {row[0] for row in result.all()} == set()


async def test_real_set_rls_context_lets_delivery_manager_see_own_org(
    rls_conn: AsyncSession, seed_data: Seed
) -> None:
    conn = rls_conn
    await set_rls_context(conn, json.dumps({"sub": str(seed_data.delivery_manager_a)}))

    result = await conn.execute(text("SELECT id FROM projects"))
    visible = {row[0] for row in result.all()}
    assert visible == {seed_data.project_a1, seed_data.project_a2}
