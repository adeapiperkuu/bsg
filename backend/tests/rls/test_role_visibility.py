"""Table-driven RLS visibility tests (DEVELOPMENT_PLAN.md Workstream C, closes F4).

Turns the static findings behind Workstream A (F1/F1a: client-role policies
didn't join `project_assignments`) and Workstream B (F2: `audit_logs` had no
policies at all) into a permanent regression suite that actually opens a
connection *as* each role and checks the row set Postgres returns, instead of
inspecting compiled SQL text (see the old `test_tenant_isolation.py`) or
`pg_policies` existence.

Run with: `pytest --run-live-rls tests/rls` (skipped by default -- see
tests/rls/conftest.py for why).

Covers all 13 tables F1 touched (projects, milestones, client_communications,
throughput_snapshots, teams, quality_snapshots, quality_error_entries,
risk_alerts, bottlenecks, both evidence-link tables, agent_queries,
delivery_confidence_scores) plus audit_logs (F2).

Extending this coverage surfaced a new finding (F10 / BUG-007, fixed
2026-07-14): `communication_evidence_links` and `agent_query_evidence_links`
had SELECT policies for every role but **no INSERT policy at all**, in any
migration -- the same failure mode as F2 (`audit_logs`). Fixed by
`supabase/migrations/20260714100000_evidence_links_insert_rls.sql`;
`test_comm_evidence_links_insert_allowed_for_own_org` and its
`agent_query_evidence_links` counterpart below now confirm INSERT succeeds
for a matching org and is denied cross-org, matching the pattern already
used for `audit_logs`.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from tests.rls.conftest import Seed, as_user


async def _visible_ids(conn: AsyncSession, table: str) -> set:
    result: Result = await conn.execute(text(f"SELECT id FROM {table}"))
    return {row[0] for row in result.all()}


async def test_assigned_client_sees_only_their_assigned_project(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, "projects") == {data.project_a1}


async def test_unassigned_client_sees_no_projects_even_in_their_own_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_unassigned)
    assert await _visible_ids(conn, "projects") == set()


async def test_client_in_org_b_cannot_see_org_a_projects(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.client_b)
    assert await _visible_ids(conn, "projects") == {data.project_b1}


async def test_delivery_manager_sees_whole_org_but_not_other_org(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    visible = await _visible_ids(conn, "projects")
    assert visible == {data.project_a1, data.project_a2}
    assert data.project_b1 not in visible


async def test_leadership_and_super_admin_see_across_orgs(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    expected = {data.project_a1, data.project_a2, data.project_b1}
    for user_id in (data.bsg_leadership, data.super_admin):
        await as_user(conn, user_id)
        assert expected <= await _visible_ids(conn, "projects")


async def test_client_milestone_visibility_follows_project_assignment(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, "milestones") == {data.milestone_a1}

    await as_user(conn, data.client_unassigned)
    assert await _visible_ids(conn, "milestones") == set()


async def test_client_communications_hides_drafts_and_unassigned_projects(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded

    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, "client_communications") == {data.comm_a1_sent}

    await as_user(conn, data.client_unassigned)
    assert await _visible_ids(conn, "client_communications") == set()

    await as_user(conn, data.client_b)
    assert await _visible_ids(conn, "client_communications") == {data.comm_b1_sent}


async def test_delivery_manager_sees_drafts_and_sent_for_own_org_only(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    visible = await _visible_ids(conn, "client_communications")
    assert visible == {data.comm_a1_sent, data.comm_a1_draft}
    assert data.comm_b1_sent not in visible


async def test_leadership_and_super_admin_see_all_communications_across_orgs(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    expected = {data.comm_a1_sent, data.comm_a1_draft, data.comm_b1_sent}
    for user_id in (data.bsg_leadership, data.super_admin):
        await as_user(conn, user_id)
        assert expected <= await _visible_ids(conn, "client_communications")


async def test_audit_logs_has_no_client_read_access(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, "audit_logs") == set()


async def test_audit_logs_dm_sees_own_org_only(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    visible = await _visible_ids(conn, "audit_logs")
    assert data.audit_a in visible
    assert data.audit_b not in visible


async def test_audit_logs_leadership_and_super_admin_see_across_orgs(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    for user_id in (data.bsg_leadership, data.super_admin):
        await as_user(conn, user_id)
        visible = await _visible_ids(conn, "audit_logs")
        assert {data.audit_a, data.audit_b} <= visible


async def test_audit_logs_insert_allowed_for_own_org(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO audit_logs (org_id, project_id, event_type, payload) "
                "VALUES (:org_id, :project_id, 'rls_test_insert_own_org', '{}'::jsonb)"
            ),
            {"org_id": data.org_a, "project_id": data.project_a1},
        )


async def test_audit_logs_insert_denied_for_other_org(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO audit_logs (org_id, project_id, event_type, payload) "
                    "VALUES (:org_id, :project_id, 'rls_test_insert_wrong_org', '{}'::jsonb)"
                ),
                {"org_id": data.org_b, "project_id": data.project_b1},
            )


def _draft_insert_sql() -> str:
    return (
        "INSERT INTO client_communications "
        "(project_id, org_id, comm_type, subject, body_draft, status, drafted_by_agent) "
        "VALUES (:project_id, :org_id, 'weekly_summary', 'RLS test draft', 'draft body', 'draft', 'rls-test')"
    )


async def test_delivery_manager_can_insert_draft_communication_for_own_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    """Regression test for the resolved F3 decision (DEVELOPMENT_PLAN.md
    Workstream D): delivery_manager inserts client_communications rows
    directly under comms_dm_all -- there is no service_role-only write path."""
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    async with conn.begin_nested():
        await conn.execute(
            text(_draft_insert_sql()),
            {"project_id": data.project_a1, "org_id": data.org_a},
        )


async def test_delivery_manager_cannot_insert_draft_communication_for_other_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(_draft_insert_sql()),
                {"project_id": data.project_b1, "org_id": data.org_b},
            )


async def test_client_cannot_insert_draft_communication(seeded: tuple[AsyncSession, Seed]) -> None:
    """`client` has no INSERT policy on client_communications at all (only
    comms_client_select, a SELECT policy) -- default-deny applies regardless
    of org, unlike the delivery_manager case above."""
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(_draft_insert_sql()),
                {"project_id": data.project_a1, "org_id": data.org_a},
            )


# Tables sharing the exact same policy shape as milestones: client sees only
# rows on their assigned project, delivery_manager sees their whole org,
# leadership/super_admin see across orgs. (table_name, attr for the org-A/
# project-A1 row, attr for the org-B/project-B1 row).
SIMPLE_ORG_PROJECT_SCOPED_TABLES = [
    ("throughput_snapshots", "throughput_a1", "throughput_b1"),
    ("teams", "team_a1", "team_b1"),
    ("quality_snapshots", "quality_a1", "quality_b1"),
    ("quality_error_entries", "quality_error_a1", "quality_error_b1"),
    ("risk_alerts", "risk_alert_a1", "risk_alert_b1"),
    ("bottlenecks", "bottleneck_a1", "bottleneck_b1"),
    ("delivery_confidence_scores", "confidence_a1", "confidence_b1"),
]


@pytest.mark.parametrize("table, id_a1_attr, id_b1_attr", SIMPLE_ORG_PROJECT_SCOPED_TABLES)
async def test_assigned_client_sees_only_their_project_row(
    seeded: tuple[AsyncSession, Seed], table: str, id_a1_attr: str, id_b1_attr: str
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, table) == {getattr(data, id_a1_attr)}


@pytest.mark.parametrize("table, id_a1_attr, id_b1_attr", SIMPLE_ORG_PROJECT_SCOPED_TABLES)
async def test_unassigned_client_sees_no_rows(
    seeded: tuple[AsyncSession, Seed], table: str, id_a1_attr: str, id_b1_attr: str
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_unassigned)
    assert await _visible_ids(conn, table) == set()


@pytest.mark.parametrize("table, id_a1_attr, id_b1_attr", SIMPLE_ORG_PROJECT_SCOPED_TABLES)
async def test_delivery_manager_sees_own_org_row_not_other_org(
    seeded: tuple[AsyncSession, Seed], table: str, id_a1_attr: str, id_b1_attr: str
) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    visible = await _visible_ids(conn, table)
    assert getattr(data, id_a1_attr) in visible
    assert getattr(data, id_b1_attr) not in visible


@pytest.mark.parametrize("table, id_a1_attr, id_b1_attr", SIMPLE_ORG_PROJECT_SCOPED_TABLES)
async def test_leadership_and_super_admin_see_both_orgs_rows(
    seeded: tuple[AsyncSession, Seed], table: str, id_a1_attr: str, id_b1_attr: str
) -> None:
    conn, data = seeded
    expected = {getattr(data, id_a1_attr), getattr(data, id_b1_attr)}
    for user_id in (data.bsg_leadership, data.super_admin):
        await as_user(conn, user_id)
        assert expected <= await _visible_ids(conn, table)


async def test_agent_queries_client_sees_only_their_own_queries(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    """agent_queries is scoped by user_id, not just org/project -- a client
    must not see another user's query even in their own org and project."""
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    visible = await _visible_ids(conn, "agent_queries")
    assert visible == {data.agent_query_client_assigned, data.agent_query_client_assigned_cross_project}
    assert data.agent_query_dm_a not in visible


async def test_agent_queries_delivery_manager_sees_whole_org(seeded: tuple[AsyncSession, Seed]) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    visible = await _visible_ids(conn, "agent_queries")
    assert visible == {
        data.agent_query_client_assigned,
        data.agent_query_client_assigned_cross_project,
        data.agent_query_dm_a,
    }
    assert data.agent_query_b not in visible


async def test_agent_queries_insert_requires_matching_user_and_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO agent_queries (user_id, org_id, project_id, agent_name, query_text, answer_text) "
                "VALUES (:user_id, :org_id, :project_id, 'delivery_agent', 'q', 'a')"
            ),
            {"user_id": data.client_assigned, "org_id": data.org_a, "project_id": data.project_a1},
        )

    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO agent_queries (user_id, org_id, project_id, agent_name, query_text, answer_text) "
                    "VALUES (:user_id, :org_id, :project_id, 'delivery_agent', 'q', 'a')"
                ),
                {"user_id": data.delivery_manager_a, "org_id": data.org_a, "project_id": data.project_a1},
            )


async def test_communication_evidence_links_visibility_follows_parent(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, "communication_evidence_links") == {data.comm_evidence_a1}

    await as_user(conn, data.client_unassigned)
    assert await _visible_ids(conn, "communication_evidence_links") == set()

    await as_user(conn, data.delivery_manager_a)
    assert data.comm_evidence_a1 in await _visible_ids(conn, "communication_evidence_links")


async def test_agent_query_evidence_links_visibility_follows_parent(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    assert await _visible_ids(conn, "agent_query_evidence_links") == {data.agent_query_evidence_client}

    await as_user(conn, data.client_unassigned)
    assert await _visible_ids(conn, "agent_query_evidence_links") == set()

    await as_user(conn, data.delivery_manager_a)
    assert data.agent_query_evidence_client in await _visible_ids(conn, "agent_query_evidence_links")


async def test_comm_evidence_links_insert_allowed_for_own_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    """Regression test for F10 / BUG-007 (fixed by
    supabase/migrations/20260714100000_evidence_links_insert_rls.sql):
    communication_evidence_links had SELECT policies for every role but no
    INSERT policy anywhere -- delivery_manager's own create_draft() request
    (backend/app/services/communications.py) would have started failing the
    moment BYPASSRLS was removed. Now fixed: INSERT succeeds when the parent
    client_communications row's org matches the caller's."""
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO communication_evidence_links "
                "(communication_id, source_table, source_row_id, description) "
                "VALUES (:communication_id, 'throughput_snapshots', :source_row_id, 'x')"
            ),
            {"communication_id": data.comm_a1_sent, "source_row_id": data.throughput_a1},
        )


async def test_comm_evidence_links_insert_denied_for_other_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO communication_evidence_links "
                    "(communication_id, source_table, source_row_id, description) "
                    "VALUES (:communication_id, 'throughput_snapshots', :source_row_id, 'x')"
                ),
                {"communication_id": data.comm_b1_sent, "source_row_id": data.throughput_b1},
            )


async def test_delivery_manager_can_enqueue_report_job_for_own_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    """A delivery manager authorized by the API must also pass report queue RLS."""
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    job_id = uuid4()
    event_id = uuid4()
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO report_jobs "
                "(id, org_id, job_type, idempotency_key, request_payload) "
                "VALUES (:id, :org_id, 'on_demand_generate', :key, '{}'::jsonb)"
            ),
            {"id": job_id, "org_id": data.org_a, "key": f"rls-briefing-{job_id}"},
        )
        await conn.execute(
            text(
                "INSERT INTO report_job_events "
                "(id, org_id, job_id, event_type, event_metadata) "
                "VALUES (:id, :org_id, :job_id, 'enqueued', '{}'::jsonb)"
            ),
            {"id": event_id, "org_id": data.org_a, "job_id": job_id},
        )


async def test_delivery_manager_cannot_enqueue_report_job_for_other_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.delivery_manager_a)
    job_id = uuid4()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO report_jobs "
                    "(id, org_id, job_type, idempotency_key, request_payload) "
                    "VALUES (:id, :org_id, 'on_demand_generate', :key, '{}'::jsonb)"
                ),
                {"id": job_id, "org_id": data.org_b, "key": f"rls-briefing-{job_id}"},
            )


async def test_agent_query_evidence_links_insert_allowed_for_own_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    """Same fix as above, for agent_query_evidence_links."""
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO agent_query_evidence_links "
                "(agent_query_id, source_table, source_row_id, description) "
                "VALUES (:agent_query_id, 'throughput_snapshots', :source_row_id, 'x')"
            ),
            {"agent_query_id": data.agent_query_client_assigned, "source_row_id": data.throughput_a1},
        )


async def test_agent_query_evidence_links_insert_denied_for_other_org(
    seeded: tuple[AsyncSession, Seed],
) -> None:
    conn, data = seeded
    await as_user(conn, data.client_assigned)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO agent_query_evidence_links "
                    "(agent_query_id, source_table, source_row_id, description) "
                    "VALUES (:agent_query_id, 'throughput_snapshots', :source_row_id, 'x')"
                ),
                {"agent_query_id": data.agent_query_b, "source_row_id": data.throughput_b1},
            )
