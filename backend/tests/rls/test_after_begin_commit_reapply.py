"""Phase 1A regression test (docs/PERF_IMPLEMENTATION_PLAN.md): proves RLS
context is reapplied after a REAL, top-level `session.commit()` -- not just
within the first transaction of a session -- using the actual production
mechanism (`app/db/rls.py:_reapply_rls_on_begin`, a SQLAlchemy `after_begin`
listener wired onto the app's real `AsyncSessionLocal` sessions).

This closes a gap the rest of this package doesn't cover: every other test
here (see `conftest.py`) seeds data and asserts within ONE transaction that
is always rolled back at the end, so it never exercises what happens to RLS
enforcement *after* a mid-request commit -- exactly what routes like
`PATCH /me/notifications` do (`session.commit()` then `session.refresh(...)`,
see `app/api/routes/me.py`). Under the old NullPool-per-request model this
gap didn't matter much (a fresh connection came with fresh state to reapply
to on the next real request); under the new persistent transaction-pooler
pool, a connection genuinely outlives a commit within the SAME request, so a
regression here would silently drop back to the raw `postgres` (BYPASSRLS)
role for any query issued after a mid-request commit -- a real cross-org
data leak. Manually verified once at the HTTP layer during Phase 1A
implementation (login as PM, `PATCH /me/notifications/{id}`, then re-GET a
different org's project -> still 404); this test pins that behaviour down at
the DB layer, opt-in via `pytest --run-live-rls` like the rest of this
package.

Unlike sibling tests, this one performs a REAL top-level commit (that's the
scenario under test), so it seeds a small, self-contained fixture directly
(not the shared `Seed`/`seed()` in conftest.py, to keep the blast radius of
"data that must be cleaned up after a real commit" as small as possible) and
explicitly deletes everything it inserted in a `finally` block, restoring the
bypassing `postgres` role first so the cleanup itself is never subject to the
RLS policies under test.
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.rls import set_rls_context
from app.db.session import session_scope


async def test_rls_reapplied_after_commit_blocks_cross_org_read() -> None:
    org_a, org_b = uuid4(), uuid4()
    project_a, project_b = uuid4(), uuid4()
    dm_a = uuid4()

    async with session_scope() as session:  # type: AsyncSession
        # Capture the connection's actual baseline role (Supabase's pooler auth
        # user, whatever it's literally named) up front, before any SET ROLE, so
        # cleanup can restore exactly this -- no hardcoded role-name assumption.
        baseline_role = (await session.execute(text("SELECT current_user"))).scalar_one()
        try:
            # ---- Seed as the bypassing role captured above (default connection role). ----
            await session.execute(
                text(
                    "INSERT INTO organisations (id, name, slug, vertical, region) VALUES "
                    "(:id, :name, :slug, 'life_sciences', 'eu')"
                ),
                [
                    {"id": org_a, "name": "after_begin Test Org A", "slug": f"after-begin-a-{org_a.hex[:8]}"},
                    {"id": org_b, "name": "after_begin Test Org B", "slug": f"after-begin-b-{org_b.hex[:8]}"},
                ],
            )
            await session.execute(
                text(
                    "INSERT INTO users (id, org_id, email, full_name, role, is_active) VALUES "
                    "(:id, :org_id, :email, 'DM A', 'delivery_manager', true)"
                ),
                {"id": dm_a, "org_id": org_a, "email": f"{dm_a}@after-begin-test.example"},
            )
            from datetime import date

            today = date(2026, 1, 1)
            await session.execute(
                text(
                    "INSERT INTO projects (id, org_id, name, vertical, status, start_date, target_end_date) VALUES "
                    "(:id, :org_id, :name, 'life_sciences', 'active', :start_date, :target_end_date)"
                ),
                [
                    {"id": project_a, "org_id": org_a, "name": "Project A", "start_date": today, "target_end_date": today},
                    {"id": project_b, "org_id": org_b, "name": "Project B", "start_date": today, "target_end_date": today},
                ],
            )

            # ---- Apply RLS context for DM A (org_a) via the REAL production function. ----
            await set_rls_context(session, json.dumps({"sub": str(dm_a)}))

            # ---- Pre-commit: DM A sees only org_a's project. ----
            pre = await session.execute(text("SELECT id FROM projects WHERE id IN (:a, :b)"), {"a": project_a, "b": project_b})
            assert {row[0] for row in pre.all()} == {project_a}, (
                "Sanity check failed before commit: DM A should see only project_a, not project_b."
            )

            # ---- The scenario under test: a REAL top-level commit mid-session, ----
            # ---- exactly like `PATCH /me/notifications` (app/api/routes/me.py). ----
            await session.commit()

            # ---- Post-commit: a new transaction opens on the next statement. ----
            # `_reapply_rls_on_begin` (app/db/rls.py) must reapply DM A's claims
            # here via the `after_begin` hook -- if it didn't, this session would
            # silently be back on the bypassing `postgres` role and see BOTH
            # projects, which would be a live cross-org data leak under connection
            # reuse (the whole point of this test).
            post = await session.execute(text("SELECT id FROM projects WHERE id IN (:a, :b)"), {"a": project_a, "b": project_b})
            assert {row[0] for row in post.all()} == {project_a}, (
                "RLS was NOT reapplied after commit(): DM A saw project_b (another org's project) "
                "or lost visibility into project_a. This is the exact regression "
                "_reapply_rls_on_begin exists to prevent."
            )
        finally:
            # ---- Cleanup: regain BYPASSRLS before deleting, then commit the cleanup. ----
            # `set_config('role', ..., true)` is transaction-scoped (is_local=true),
            # identical to `SET LOCAL ROLE` (see app/db/rls.py's own use of this
            # equivalence) -- never a plain non-local `SET`/`RESET ROLE`, so this
            # can't leak the baseline role onto the pooled connection past this
            # transaction. Used instead of `SET LOCAL ROLE <name>` directly because
            # Postgres's `SET` family of commands doesn't accept bind parameters.
            await session.execute(
                text("select set_config('role', :role, true)"), {"role": baseline_role}
            )
            await session.execute(text("DELETE FROM projects WHERE id IN (:a, :b)"), {"a": project_a, "b": project_b})
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": dm_a})
            await session.execute(text("DELETE FROM organisations WHERE id IN (:a, :b)"), {"a": org_a, "b": org_b})
            await session.commit()
