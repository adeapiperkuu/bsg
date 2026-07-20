"""Fixture for DEVELOPMENT_PLAN.md Workstream C: real-Postgres RLS visibility tests.

Every other test in this repo runs against `FakeSession` (see
`backend/tests/conftest.py`) and never evaluates a single Postgres policy.
That's the gap Workstream A/B's fixes exposed: F1a and F2a were both *static*
findings because there was no way to prove a policy actually filters rows for
a given role.

This suite connects to the real database (the same `DATABASE_URL` the app
uses -- the shared Supabase project, already fully migrated per F2a) and
opens the app's normal `postgres` connection role, which has `BYPASSRLS`.
Bypass is deliberately used for *seeding* fixture rows (so setup can't be
blocked by the same policies under test), then the transaction switches to
`SET LOCAL ROLE authenticated` -- a role that does NOT bypass RLS -- for every
assertion, simulating a given user via `request.jwt.claims.sub` the same way
`app/db/rls.py:set_rls_context` does for real requests.

Nothing here is ever committed. The one outer transaction per test is rolled
back unconditionally in fixture teardown, `SET LOCAL ROLE` / `set_config(...,
true)` are both transaction-scoped and revert automatically, and per-probe
work runs inside a SAVEPOINT (`session.begin_nested()`) so an *expected*
policy-violation error doesn't abort the whole fixture.

These tests are opt-in (`pytest --run-live-rls`) rather than part of the
default `pytest` run: they're the only tests in this repo that touch a real
database, and running them by default would mean every plain `cd backend &&
pytest` silently reaches out to the team's shared, real-data Supabase project.
Wiring this into CI as a required, non-skippable check (Workstream C step 4)
is a separate decision -- it needs its own DB credentials/config -- and is
intentionally not done here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine, session_scope

# `pytest_addoption` lives in tests/conftest.py, not here: pytest's early
# conftest scan (which registers command-line options before collection)
# only descends into subdirectories named `test*`, so a nested conftest.py
# under tests/rls/ would silently fail to register the flag.


@dataclass
class Seed:
    """IDs for the fixture graph seeded by `seed()`. See its docstring for the shape."""

    org_a: UUID
    org_b: UUID
    project_a1: UUID  # org A, has an assignment (client_assigned is on this one)
    project_a2: UUID  # org A, no client assignment
    project_b1: UUID  # org B
    milestone_a1: UUID
    milestone_a2: UUID
    milestone_b1: UUID
    comm_a1_sent: UUID  # org A, project A1, status=sent
    comm_a1_draft: UUID  # org A, project A1, status=draft
    comm_b1_sent: UUID  # org B, project B1, status=sent
    comm_evidence_a1: UUID  # evidence link on comm_a1_sent
    audit_a: UUID
    audit_b: UUID
    team_a1: UUID  # org A, project A1
    team_b1: UUID  # org B, project B1
    throughput_a1: UUID
    throughput_b1: UUID
    quality_a1: UUID  # project A1, team A1
    quality_b1: UUID  # project B1, team B1
    quality_error_a1: UUID  # via quality_a1
    quality_error_b1: UUID  # via quality_b1
    risk_alert_a1: UUID
    risk_alert_b1: UUID
    bottleneck_a1: UUID
    bottleneck_b1: UUID
    agent_query_client_assigned: UUID  # client_assigned's own query, project A1
    agent_query_client_assigned_cross_project: UUID  # client_assigned's own, project_id=NULL
    agent_query_dm_a: UUID  # DM's own query, project A1 -- client must NOT see this
    agent_query_b: UUID  # client_b's own query, org B
    agent_query_evidence_client: UUID  # evidence link on agent_query_client_assigned
    confidence_a1: UUID  # project A1 / milestone A1
    confidence_b1: UUID  # project B1 / milestone B1
    client_assigned: UUID  # org A, assigned to project A1 only
    client_unassigned: UUID  # org A, no project assignment at all
    client_b: UUID  # org B
    delivery_manager_a: UUID  # org A
    bsg_leadership: UUID  # org A (role ignores org_id per policy)
    super_admin: UUID  # org A (role ignores org_id per policy)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_after_test() -> AsyncIterator[None]:
    """Phase 1A (docs/PERF_IMPLEMENTATION_PLAN.md): `app/db/session.py`'s
    async engine now holds a persistent connection pool (`pool_size=10`)
    instead of `NullPool`, and that engine/pool is a module-level singleton
    created once at import. `pytest-asyncio`'s default (function-scoped)
    event loop means every test in this package runs on its OWN fresh loop
    -- so a pooled asyncpg connection checked out and returned idle during
    test A's loop would, under the old NullPool, simply never exist by the
    time test B ran (NullPool closes every connection on checkin, all within
    the same loop that opened it). With a persistent pool that connection
    instead survives, idle, into test B's DIFFERENT loop; asyncpg's
    connection/transport objects are bound to the loop that created them, so
    any operation on it from test B's loop (or the pool later closing it
    against test A's now-closed loop) raises `RuntimeError: Event loop is
    closed` or `InterfaceError: another operation is in progress`. This is a
    test-infrastructure-only problem (uvicorn's single long-lived loop in
    production never hits it) but it makes this opt-in `--run-live-rls` suite
    flaky/broken once a real pool is in place.

    Fix: dispose the pool's connections here, in THIS test's teardown, while
    its own event loop -- the one that actually owns them -- is still alive
    and running. That guarantees no connection ever survives to be touched
    from a different test's loop. Runs after `rls_conn`'s own teardown
    (pytest tears fixtures down in reverse of setup order, and this fixture,
    being autouse, is set up before the test explicitly requests `rls_conn`),
    so the session's connection has already been checked back into the pool
    by the time this disposes it.
    """
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def rls_conn() -> AsyncIterator[AsyncSession]:
    """A live DB session, always rolled back. First use runs as the bypassing
    `postgres` role for seeding; call `switch_to_authenticated` once seeding
    is done to start enforcing RLS for the rest of the transaction."""
    async with session_scope() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def switch_to_authenticated(conn: AsyncSession) -> None:
    """Drop the bypassing `postgres` role for the rest of this transaction.

    Transaction-scoped (`SET LOCAL`), matching `set_rls_context`'s use of
    `set_config(..., true)` -- both revert automatically when the outer
    transaction rolls back, so this can never leak onto a pooled connection.
    """
    await conn.execute(text("SET LOCAL ROLE authenticated"))


async def as_user(conn: AsyncSession, user_id: UUID | None) -> None:
    """Simulate `set_rls_context` for `user_id` (or fully unauthenticated if None)."""
    claims = json.dumps({"sub": str(user_id)} if user_id is not None else {})
    await conn.execute(text("select set_config('request.jwt.claims', :claims, true)"), {"claims": claims})


async def seed(conn: AsyncSession) -> Seed:
    """Seed two orgs' worth of fixture data as the bypassing role.

    org_a: project_a1 (client_assigned has an active assignment here),
    project_a2 (no client assignment at all), one milestone per project, a
    sent + a draft client_communications row on project_a1, one audit_logs
    row, and users for every one of the four roles (client_assigned,
    client_unassigned, delivery_manager_a, bsg_leadership, super_admin).

    org_b: project_b1, one milestone, one sent client_communications row,
    one audit_logs row, and client_b (assigned to project_b1) -- enough to
    prove cross-org isolation, not a mirror of every org_a role.

    Also seeds one row per remaining F1 table (teams, throughput_snapshots,
    quality_snapshots + quality_error_entries, risk_alerts, bottlenecks,
    delivery_confidence_scores, both evidence-link tables) for org_a/project_a1
    and org_b/project_b1, plus four agent_queries rows exercising the
    user_id-scoped (not just org-scoped) client policy on that table.
    """
    org_a, org_b = uuid4(), uuid4()
    project_a1, project_a2, project_b1 = uuid4(), uuid4(), uuid4()
    milestone_a1, milestone_a2, milestone_b1 = uuid4(), uuid4(), uuid4()
    comm_a1_sent, comm_a1_draft, comm_b1_sent = uuid4(), uuid4(), uuid4()
    comm_evidence_a1 = uuid4()
    audit_a, audit_b = uuid4(), uuid4()
    team_a1, team_b1 = uuid4(), uuid4()
    throughput_a1, throughput_b1 = uuid4(), uuid4()
    quality_a1, quality_b1 = uuid4(), uuid4()
    quality_error_a1, quality_error_b1 = uuid4(), uuid4()
    risk_alert_a1, risk_alert_b1 = uuid4(), uuid4()
    bottleneck_a1, bottleneck_b1 = uuid4(), uuid4()
    agent_query_client_assigned = uuid4()
    agent_query_client_assigned_cross_project = uuid4()
    agent_query_dm_a = uuid4()
    agent_query_b = uuid4()
    agent_query_evidence_client = uuid4()
    confidence_a1, confidence_b1 = uuid4(), uuid4()
    client_assigned, client_unassigned, client_b = uuid4(), uuid4(), uuid4()
    delivery_manager_a, bsg_leadership, super_admin = uuid4(), uuid4(), uuid4()

    await conn.execute(
        text(
            "INSERT INTO organisations (id, name, slug, vertical, region) VALUES "
            "(:id, :name, :slug, 'life_sciences', 'eu')"
        ),
        [
            {"id": org_a, "name": "RLS Test Org A", "slug": f"rls-test-a-{org_a.hex[:8]}"},
            {"id": org_b, "name": "RLS Test Org B", "slug": f"rls-test-b-{org_b.hex[:8]}"},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO users (id, org_id, email, full_name, role, is_active) VALUES "
            "(:id, :org_id, :email, :full_name, :role, true)"
        ),
        [
            {
                "id": client_assigned,
                "org_id": org_a,
                "email": f"{client_assigned}@rls-test.example",
                "full_name": "Client Assigned",
                "role": "client",
            },
            {
                "id": client_unassigned,
                "org_id": org_a,
                "email": f"{client_unassigned}@rls-test.example",
                "full_name": "Client Unassigned",
                "role": "client",
            },
            {
                "id": client_b,
                "org_id": org_b,
                "email": f"{client_b}@rls-test.example",
                "full_name": "Client B",
                "role": "client",
            },
            {
                "id": delivery_manager_a,
                "org_id": org_a,
                "email": f"{delivery_manager_a}@rls-test.example",
                "full_name": "DM A",
                "role": "delivery_manager",
            },
            {
                "id": bsg_leadership,
                "org_id": org_a,
                "email": f"{bsg_leadership}@rls-test.example",
                "full_name": "Leadership",
                "role": "bsg_leadership",
            },
            {
                "id": super_admin,
                "org_id": org_a,
                "email": f"{super_admin}@rls-test.example",
                "full_name": "Super Admin",
                "role": "super_admin",
            },
        ],
    )

    today = date(2026, 1, 1)
    await conn.execute(
        text(
            "INSERT INTO projects (id, org_id, name, vertical, status, start_date, target_end_date) VALUES "
            "(:id, :org_id, :name, 'life_sciences', 'active', :start_date, :target_end_date)"
        ),
        [
            {"id": project_a1, "org_id": org_a, "name": "Project A1", "start_date": today, "target_end_date": today},
            {"id": project_a2, "org_id": org_a, "name": "Project A2", "start_date": today, "target_end_date": today},
            {"id": project_b1, "org_id": org_b, "name": "Project B1", "start_date": today, "target_end_date": today},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO project_assignments (id, user_id, project_id, org_id, is_active) "
            "VALUES (:id, :user_id, :project_id, :org_id, true)"
        ),
        [
            {"id": uuid4(), "user_id": client_assigned, "project_id": project_a1, "org_id": org_a},
            {"id": uuid4(), "user_id": client_b, "project_id": project_b1, "org_id": org_b},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO milestones (id, project_id, org_id, name, planned_date) "
            "VALUES (:id, :project_id, :org_id, :name, :planned_date)"
        ),
        [
            {"id": milestone_a1, "project_id": project_a1, "org_id": org_a, "name": "M A1", "planned_date": today},
            {"id": milestone_a2, "project_id": project_a2, "org_id": org_a, "name": "M A2", "planned_date": today},
            {"id": milestone_b1, "project_id": project_b1, "org_id": org_b, "name": "M B1", "planned_date": today},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO client_communications "
            "(id, project_id, org_id, comm_type, subject, body_draft, status, drafted_by_agent) "
            "VALUES (:id, :project_id, :org_id, 'weekly_summary', :subject, 'draft body', :status, 'rls-test')"
        ),
        [
            {
                "id": comm_a1_sent,
                "project_id": project_a1,
                "org_id": org_a,
                "subject": "A1 sent",
                "status": "sent",
            },
            {
                "id": comm_a1_draft,
                "project_id": project_a1,
                "org_id": org_a,
                "subject": "A1 draft",
                "status": "draft",
            },
            {
                "id": comm_b1_sent,
                "project_id": project_b1,
                "org_id": org_b,
                "subject": "B1 sent",
                "status": "sent",
            },
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO communication_evidence_links (id, communication_id, source_table, source_row_id, description) "
            "VALUES (:id, :communication_id, 'throughput_snapshots', :source_row_id, 'RLS test evidence')"
        ),
        {"id": comm_evidence_a1, "communication_id": comm_a1_sent, "source_row_id": uuid4()},
    )

    await conn.execute(
        text(
            "INSERT INTO audit_logs (id, org_id, project_id, event_type, payload) "
            "VALUES (:id, :org_id, :project_id, 'rls_test_event', '{}'::jsonb)"
        ),
        [
            {"id": audit_a, "org_id": org_a, "project_id": project_a1},
            {"id": audit_b, "org_id": org_b, "project_id": project_b1},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO teams (id, project_id, org_id, name, site, domain, is_active) "
            "VALUES (:id, :project_id, :org_id, :name, 'india', 'annotation', true)"
        ),
        [
            {"id": team_a1, "project_id": project_a1, "org_id": org_a, "name": "Team A1"},
            {"id": team_b1, "project_id": project_b1, "org_id": org_b, "name": "Team B1"},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO throughput_snapshots (id, project_id, org_id, snapshot_date, units_completed) "
            "VALUES (:id, :project_id, :org_id, :snapshot_date, 100)"
        ),
        [
            {"id": throughput_a1, "project_id": project_a1, "org_id": org_a, "snapshot_date": today},
            {"id": throughput_b1, "project_id": project_b1, "org_id": org_b, "snapshot_date": today},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO quality_snapshots (id, project_id, team_id, org_id, iso_year, iso_week) "
            "VALUES (:id, :project_id, :team_id, :org_id, 2026, 1)"
        ),
        [
            {"id": quality_a1, "project_id": project_a1, "team_id": team_a1, "org_id": org_a},
            {"id": quality_b1, "project_id": project_b1, "team_id": team_b1, "org_id": org_b},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO quality_error_entries (id, quality_snapshot_id, org_id, error_category, share_pct) "
            "VALUES (:id, :quality_snapshot_id, :org_id, 'mislabel', 5.0)"
        ),
        [
            {"id": quality_error_a1, "quality_snapshot_id": quality_a1, "org_id": org_a},
            {"id": quality_error_b1, "quality_snapshot_id": quality_b1, "org_id": org_b},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO risk_alerts (id, project_id, org_id, alert_type, risk_tier, title, detail) "
            "VALUES (:id, :project_id, :org_id, 'delivery_risk', 'medium', 'RLS test alert', 'detail')"
        ),
        [
            {"id": risk_alert_a1, "project_id": project_a1, "org_id": org_a},
            {"id": risk_alert_b1, "project_id": project_b1, "org_id": org_b},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO bottlenecks (id, project_id, org_id, title, detail) "
            "VALUES (:id, :project_id, :org_id, 'RLS test bottleneck', 'detail')"
        ),
        [
            {"id": bottleneck_a1, "project_id": project_a1, "org_id": org_a},
            {"id": bottleneck_b1, "project_id": project_b1, "org_id": org_b},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO delivery_confidence_scores (id, project_id, milestone_id, org_id, score_pct, status) "
            "VALUES (:id, :project_id, :milestone_id, :org_id, 90.0, 'on_track')"
        ),
        [
            {"id": confidence_a1, "project_id": project_a1, "milestone_id": milestone_a1, "org_id": org_a},
            {"id": confidence_b1, "project_id": project_b1, "milestone_id": milestone_b1, "org_id": org_b},
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO agent_queries (id, user_id, org_id, project_id, agent_name, query_text, answer_text) "
            "VALUES (:id, :user_id, :org_id, :project_id, 'delivery_agent', 'q', 'a')"
        ),
        [
            {
                "id": agent_query_client_assigned,
                "user_id": client_assigned,
                "org_id": org_a,
                "project_id": project_a1,
            },
            {
                "id": agent_query_client_assigned_cross_project,
                "user_id": client_assigned,
                "org_id": org_a,
                "project_id": None,
            },
            {
                "id": agent_query_dm_a,
                "user_id": delivery_manager_a,
                "org_id": org_a,
                "project_id": project_a1,
            },
            {
                "id": agent_query_b,
                "user_id": client_b,
                "org_id": org_b,
                "project_id": project_b1,
            },
        ],
    )

    await conn.execute(
        text(
            "INSERT INTO agent_query_evidence_links (id, agent_query_id, source_table, source_row_id, description) "
            "VALUES (:id, :agent_query_id, 'throughput_snapshots', :source_row_id, 'RLS test evidence')"
        ),
        {"id": agent_query_evidence_client, "agent_query_id": agent_query_client_assigned, "source_row_id": uuid4()},
    )

    return Seed(
        org_a=org_a,
        org_b=org_b,
        project_a1=project_a1,
        project_a2=project_a2,
        project_b1=project_b1,
        milestone_a1=milestone_a1,
        milestone_a2=milestone_a2,
        milestone_b1=milestone_b1,
        comm_a1_sent=comm_a1_sent,
        comm_a1_draft=comm_a1_draft,
        comm_b1_sent=comm_b1_sent,
        comm_evidence_a1=comm_evidence_a1,
        audit_a=audit_a,
        audit_b=audit_b,
        team_a1=team_a1,
        team_b1=team_b1,
        throughput_a1=throughput_a1,
        throughput_b1=throughput_b1,
        quality_a1=quality_a1,
        quality_b1=quality_b1,
        quality_error_a1=quality_error_a1,
        quality_error_b1=quality_error_b1,
        risk_alert_a1=risk_alert_a1,
        risk_alert_b1=risk_alert_b1,
        bottleneck_a1=bottleneck_a1,
        bottleneck_b1=bottleneck_b1,
        agent_query_client_assigned=agent_query_client_assigned,
        agent_query_client_assigned_cross_project=agent_query_client_assigned_cross_project,
        agent_query_dm_a=agent_query_dm_a,
        agent_query_b=agent_query_b,
        agent_query_evidence_client=agent_query_evidence_client,
        confidence_a1=confidence_a1,
        confidence_b1=confidence_b1,
        client_assigned=client_assigned,
        client_unassigned=client_unassigned,
        client_b=client_b,
        delivery_manager_a=delivery_manager_a,
        bsg_leadership=bsg_leadership,
        super_admin=super_admin,
    )


@pytest_asyncio.fixture
async def seeded(rls_conn: AsyncSession) -> tuple[AsyncSession, Seed]:
    """Seed fixture data (as the bypassing role), then drop to `authenticated`
    so every test using this fixture starts RLS-enforced."""
    data = await seed(rls_conn)
    await switch_to_authenticated(rls_conn)
    return rls_conn, data


@pytest_asyncio.fixture
async def seed_data(rls_conn: AsyncSession) -> Seed:
    """Seed fixture data only -- deliberately does NOT switch to `authenticated`.

    For tests that need to call the real `app/db/rls.py:set_rls_context`
    themselves and confirm *it* performs the role switch, rather than relying
    on this file's own `switch_to_authenticated` to have already done it."""
    return await seed(rls_conn)
