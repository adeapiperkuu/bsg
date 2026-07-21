#!/usr/bin/env python3
"""Seed PM-view operational data for EXISTING projects only.

Does NOT create or modify users, organisations, programs, or projects.
Idempotent: safe to re-run.

Usage:
  backend\\.venv\\Scripts\\python.exe scripts\\seed_pm_view_data.py
"""

from __future__ import annotations

import asyncio
import os
import random
import ssl
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / "backend" / ".env")
load_dotenv(REPO_ROOT / ".env")

ANNOTATOR_NAMES = [
    "Aria Kola",
    "Besa Dauti",
    "Driton Krasniqi",
    "Elira Hoxha",
    "Fisnik Berisha",
]


def database_url() -> str:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    if ":6543/" in url:
        url = url.replace(":6543/", ":5432/")
    return url


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def seed_metric_configurations(conn: asyncpg.Connection) -> int:
    rows = [
        (
            "delivery_confidence",
            "Delivery Confidence",
            True,
            1,
            "Current schedule confidence for the active milestone.",
            None,
        ),
        (
            "throughput_rolling_7d",
            "7-Day Throughput",
            True,
            2,
            "Rolling seven-day completed unit volume.",
            None,
        ),
        (
            "gold_set_accuracy",
            "Gold-Set Accuracy",
            True,
            3,
            "Weekly quality accuracy against gold-set labels.",
            '{"green_min": 96.0, "amber_min": 94.0, "red_min": 92.0, "wow_drop_amber": 1.0, "wow_drop_red": 2.0, "wow_drop_critical": 4.0, "direction": "higher_is_better"}',
        ),
        (
            "rework_rate",
            "Rework Rate",
            True,
            4,
            "Weekly percentage of work requiring rework.",
            '{"green_max": 3.0, "amber_max": 4.0, "red_max": 6.0, "wow_rise_amber": 1.0, "wow_rise_red": 2.0, "wow_rise_critical": 4.0, "direction": "lower_is_better"}',
        ),
        (
            "iaa_krippendorff_alpha",
            "Inter-Annotator Agreement",
            False,
            5,
            "Krippendorff alpha agreement score.",
            '{"green_min": 0.90, "amber_min": 0.85, "red_min": 0.80, "wow_drop_amber": 0.03, "wow_drop_red": 0.05, "wow_drop_critical": 0.08, "direction": "higher_is_better"}',
        ),
    ]
    inserted = 0
    for key, label, visible, order, description, threshold in rows:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM metric_configurations
            WHERE metric_key = $1 AND org_id IS NULL AND deleted_at IS NULL
            """,
            key,
        )
        if exists:
            await conn.execute(
                """
                UPDATE metric_configurations
                SET display_label = $2,
                    is_client_visible = $3,
                    display_order = $4,
                    description = $5,
                    threshold_config = COALESCE($6::jsonb, threshold_config),
                    updated_at = now()
                WHERE metric_key = $1 AND org_id IS NULL AND deleted_at IS NULL
                """,
                key,
                label,
                visible,
                order,
                description,
                threshold,
            )
            continue
        await conn.execute(
            """
            INSERT INTO metric_configurations
              (metric_key, display_label, is_client_visible, display_order, description, threshold_config, org_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NULL)
            """,
            key,
            label,
            visible,
            order,
            description,
            threshold,
        )
        inserted += 1
    return inserted


async def ensure_milestones(conn: asyncpg.Connection, project: asyncpg.Record, today: date) -> list:
    specs = [
        ("M1 — Kickoff complete", today - timedelta(days=45), "completed"),
        ("M2 — Mid-sprint delivery", today + timedelta(days=14), "on_track"),
        ("M3 — Hardening gate", today + timedelta(days=45), "at_risk"),
        ("M4 — Client acceptance", today + timedelta(days=75), "pending"),
    ]
    created = []
    for name, planned, status in specs:
        existing = await conn.fetchrow(
            """
            SELECT id FROM milestones
            WHERE project_id = $1 AND name = $2 AND deleted_at IS NULL
            """,
            project["id"],
            name,
        )
        if existing:
            created.append(existing)
            continue
        row = await conn.fetchrow(
            """
            INSERT INTO milestones
              (project_id, org_id, name, description, planned_date, actual_date, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7::milestone_status)
            RETURNING id
            """,
            project["id"],
            project["org_id"],
            name,
            f"{project['name']} — {name}",
            planned,
            planned if status == "completed" else None,
            status,
        )
        created.append(row)
    return created


async def ensure_throughput(conn: asyncpg.Connection, project: asyncpg.Record, today: date, rng: random.Random) -> int:
    existing = await conn.fetchval(
        "SELECT COUNT(*) FROM throughput_snapshots WHERE project_id = $1",
        project["id"],
    )
    if existing and int(existing) >= 14:
        return 0

    base = 80 + (hash(str(project["id"])) % 40)
    rows = []
    for days_ago in range(20, -1, -1):
        snap = today - timedelta(days=days_ago)
        units = max(20, int(base + rng.randint(-15, 25) + (5 if project["status"] == "active" else -10)))
        rows.append(
            (
                project["id"],
                project["org_id"],
                snap,
                units,
                units + rng.randint(0, 20),
                units * 7,
            )
        )
    await conn.executemany(
        """
        INSERT INTO throughput_snapshots
          (project_id, org_id, snapshot_date, units_completed, units_forecast, rolling_7day_units)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (project_id, snapshot_date) DO NOTHING
        """,
        rows,
    )
    return len(rows)


async def ensure_confidence(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    milestones: list,
    today: date,
    rng: random.Random,
) -> int:
    if not milestones:
        return 0
    milestone_id = milestones[1]["id"] if len(milestones) > 1 else milestones[0]["id"]
    existing = await conn.fetchval(
        """
        SELECT COUNT(*) FROM delivery_confidence_scores
        WHERE project_id = $1 AND milestone_id = $2
        """,
        project["id"],
        milestone_id,
    )
    if existing and int(existing) >= 4:
        return 0

    rows = []
    for weeks_ago in range(4, -1, -1):
        created_at = datetime.now(timezone.utc) - timedelta(days=weeks_ago * 7)
        score = Decimal(str(round(72 + rng.uniform(0, 22) - (3 if project["status"] == "ramping" else 0), 2)))
        status = "on_track" if score >= 80 else "at_risk" if score >= 65 else "pending"
        rows.append(
            (
                project["id"],
                milestone_id,
                project["org_id"],
                score,
                today + timedelta(days=30 + int(100 - float(score))),
                status,
                "seed-v1",
                created_at,
            )
        )
    await conn.executemany(
        """
        INSERT INTO delivery_confidence_scores
          (project_id, milestone_id, org_id, score_pct, forecast_completion_date, status, model_version, created_at)
        VALUES ($1, $2, $3, $4, $5, $6::milestone_status, $7, $8)
        """,
        rows,
    )
    return len(rows)


async def ensure_annotators(conn: asyncpg.Connection, team: asyncpg.Record, rng: random.Random) -> int:
    inserted = 0
    # Stable subset per team
    names = ANNOTATOR_NAMES[: 3 + (hash(str(team["id"])) % 3)]
    for i, name in enumerate(names):
        exists = await conn.fetchval(
            """
            SELECT 1 FROM annotators
            WHERE team_id = $1 AND full_name = $2 AND deleted_at IS NULL
            """,
            team["id"],
            name,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO annotators (org_id, team_id, full_name, site, is_sme_certified, is_active)
            VALUES ($1, $2, $3, $4::delivery_site, $5, TRUE)
            """,
            team["org_id"],
            team["id"],
            name,
            team["site"],
            i == 0,
        )
        inserted += 1
    return inserted


async def ensure_quality(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    team: asyncpg.Record,
    today: date,
    rng: random.Random,
) -> tuple[int, int]:
    existing = await conn.fetchval(
        "SELECT COUNT(*) FROM quality_snapshots WHERE project_id = $1 AND team_id = $2",
        project["id"],
        team["id"],
    )
    if existing and int(existing) >= 4:
        return 0, 0

    snaps = 0
    errors = 0
    for weeks_ago in range(4, -1, -1):
        d = today - timedelta(weeks=weeks_ago)
        y, w, _ = d.isocalendar()
        accuracy = Decimal(
            str(
                round(
                    93
                    + rng.uniform(0, 5)
                    - (2 if weeks_ago == 0 and hash(str(project["id"])) % 3 == 0 else 0),
                    2,
                )
            )
        )
        iaa = Decimal(str(round(0.82 + rng.uniform(0, 0.12), 3)))
        rework = Decimal(str(round(1.5 + rng.uniform(0, 3.5), 2)))
        evaluated = 120 + rng.randint(0, 80)
        has_drift = accuracy < Decimal("94.5") and weeks_ago <= 1
        row = await conn.fetchrow(
            """
            INSERT INTO quality_snapshots
              (project_id, team_id, org_id, iso_week, iso_year,
               gold_set_accuracy_pct, iaa_krippendorff_alpha, rework_rate_pct,
               evaluated_item_count, has_drift_alert, drift_alert_detail)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (project_id, team_id, iso_year, iso_week) DO NOTHING
            RETURNING id
            """,
            project["id"],
            team["id"],
            project["org_id"],
            w,
            y,
            accuracy,
            iaa,
            rework,
            evaluated,
            has_drift,
            "Gold-set accuracy dropped vs prior week." if has_drift else None,
        )
        if not row:
            continue
        snaps += 1
        await conn.executemany(
            """
            INSERT INTO quality_error_entries
              (quality_snapshot_id, org_id, error_category, share_pct)
            VALUES ($1, $2, $3, $4)
            """,
            [
                (row["id"], project["org_id"], "labeling_error", Decimal("40")),
                (row["id"], project["org_id"], "guideline_gap", Decimal("35")),
                (row["id"], project["org_id"], "tooling", Decimal("25")),
            ],
        )
        errors += 3
    return snaps, errors


async def ensure_risks_and_bottlenecks(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    team: asyncpg.Record,
    milestones: list,
) -> tuple[int, int]:
    risks = 0
    bots = 0
    milestone_id = milestones[2]["id"] if len(milestones) > 2 else None
    risk_specs = [
        ("delivery_risk", "medium", "Schedule pressure on hardening gate", "Throughput trend may miss M3 without capacity uplift."),
        ("quality_drift", "high", "Quality drift on gold-set", "Recent gold-set accuracy dipped below amber threshold."),
        ("milestone_at_risk", "medium", "M3 at risk", "Hardening gate has open blockers."),
    ]
    for alert_type, tier, title, detail in risk_specs:
        full_title = f"[seed] {title}"
        exists = await conn.fetchval(
            """
            SELECT 1 FROM risk_alerts
            WHERE project_id = $1 AND title = $2 AND deleted_at IS NULL
            """,
            project["id"],
            full_title,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO risk_alerts
              (project_id, org_id, milestone_id, alert_type, risk_tier, title, detail, status, slippage_probability)
            VALUES ($1, $2, $3, $4::alert_type, $5::risk_tier, $6, $7, 'open'::alert_status, $8)
            """,
            project["id"],
            project["org_id"],
            milestone_id,
            alert_type,
            tier,
            full_title,
            detail,
            Decimal("0.35"),
        )
        risks += 1

    bot_title = "[seed] Review queue backlog"
    exists = await conn.fetchval(
        """
        SELECT 1 FROM bottlenecks
        WHERE project_id = $1 AND title = $2 AND deleted_at IS NULL
        """,
        project["id"],
        bot_title,
    )
    if not exists:
        await conn.execute(
            """
            INSERT INTO bottlenecks
              (project_id, org_id, team_id, title, detail, status)
            VALUES ($1, $2, $3, $4, $5, 'open'::alert_status)
            """,
            project["id"],
            project["org_id"],
            team["id"],
            bot_title,
            "QA review queue growing; redistribute reviewers across Kosovo Delivery.",
        )
        bots += 1
    return risks, bots


async def ensure_utilization(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    team: asyncpg.Record,
    today: date,
    rng: random.Random,
) -> int:
    existing = await conn.fetchval(
        """
        SELECT COUNT(*) FROM utilization_snapshots
        WHERE project_id = $1 AND team_id = $2 AND deleted_at IS NULL AND annotator_id IS NULL
        """,
        project["id"],
        team["id"],
    )
    if existing and int(existing) >= 4:
        return 0

    rows = []
    for weeks_ago in range(4, -1, -1):
        snap = week_start(today - timedelta(weeks=weeks_ago))
        available = Decimal("40")
        allocated = Decimal(str(round(28 + rng.uniform(0, 16), 2)))
        util = (allocated / available * 100).quantize(Decimal("0.01"))
        rows.append(
            (
                project["org_id"],
                project["id"],
                team["id"],
                snap,
                allocated,
                available,
                util,
            )
        )
    await conn.executemany(
        """
        INSERT INTO utilization_snapshots
          (org_id, project_id, team_id, snapshot_date, allocated_hours, available_hours, utilization_pct)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        rows,
    )
    return len(rows)


async def ensure_governance(conn: asyncpg.Connection, project: asyncpg.Record, today: date) -> dict[str, int]:
    counts = {"scope": 0, "deps": 0, "actions": 0, "escalations": 0}
    scope_exists = await conn.fetchval(
        "SELECT 1 FROM project_scope_states WHERE project_id = $1 AND deleted_at IS NULL",
        project["id"],
    )
    if not scope_exists:
        status = "approved" if project["status"] == "active" else "pending_revision"
        await conn.execute(
            """
            INSERT INTO project_scope_states
              (org_id, project_id, scope_status, version_label, notes)
            VALUES ($1, $2, $3::governance_scope_status, $4, $5)
            """,
            project["org_id"],
            project["id"],
            status,
            "v1",
            f"Seeded scope state for {project['name']}.",
        )
        counts["scope"] = 1

    dep_specs = [
        ("[seed] Client feedback window", "client_action", "blocking", today + timedelta(days=10)),
        ("[seed] Internal guideline refresh", "internal", "open", today + timedelta(days=21)),
    ]
    for title, dep_type, status, due in dep_specs:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM project_dependencies
            WHERE project_id = $1 AND title = $2 AND deleted_at IS NULL
            """,
            project["id"],
            title,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO project_dependencies
              (org_id, project_id, title, description, dependency_type, due_date, status)
            VALUES ($1, $2, $3, $4, $5::governance_dependency_type, $6, $7::governance_dependency_status)
            """,
            project["org_id"],
            project["id"],
            title,
            f"Dependency for {project['name']}.",
            dep_type,
            due,
            status,
        )
        counts["deps"] += 1

    action_title = "[seed] Close open blockers"
    if not await conn.fetchval(
        "SELECT 1 FROM governance_actions WHERE project_id=$1 AND title=$2 AND deleted_at IS NULL",
        project["id"],
        action_title,
    ):
        await conn.execute(
            """
            INSERT INTO governance_actions
              (org_id, project_id, title, description, due_date, status)
            VALUES ($1, $2, $3, $4, $5, 'open'::governance_action_status)
            """,
            project["org_id"],
            project["id"],
            action_title,
            "Resolve open delivery and quality blockers this sprint.",
            today + timedelta(days=7),
        )
        counts["actions"] = 1

    esc_title = "[seed] Capacity risk escalation"
    if project["status"] in {"active", "ramping"} and not await conn.fetchval(
        "SELECT 1 FROM governance_escalations WHERE project_id=$1 AND title=$2 AND deleted_at IS NULL",
        project["id"],
        esc_title,
    ):
        await conn.execute(
            """
            INSERT INTO governance_escalations
              (org_id, project_id, title, description, severity, status)
            VALUES ($1, $2, $3, $4, 'medium'::governance_escalation_severity, 'open'::governance_escalation_status)
            """,
            project["org_id"],
            project["id"],
            esc_title,
            "Escalating capacity shortfall before hardening gate.",
        )
        counts["escalations"] = 1

    return counts


async def ensure_weekly_summaries(conn: asyncpg.Connection, org_ids: set, today: date) -> int:
    inserted = 0
    week = week_start(today)
    for org_id in org_ids:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM governance_weekly_summaries
            WHERE org_id = $1 AND summary_week = $2
            """,
            org_id,
            week,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO governance_weekly_summaries
              (org_id, summary_week, summary_text, status, generated_by_ai)
            VALUES ($1, $2, $3, 'draft'::governance_summary_status, TRUE)
            """,
            org_id,
            week,
            "Seeded weekly governance summary: delivery confidence stable, "
            "two open escalations, quality drift monitored on active scopes.",
        )
        inserted += 1
    return inserted


async def ensure_communications(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    pm_user_id: str | None,
) -> int:
    inserted = 0
    specs = [
        ("weekly_summary", "draft", f"[seed] Weekly update — {project['name']}"),
        ("executive_summary", "in_review", f"[seed] Executive brief — {project['name']}"),
        ("weekly_summary", "sent", f"[seed] Sent weekly — {project['name']}"),
    ]
    for comm_type, status, subject in specs:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM client_communications
            WHERE project_id = $1 AND subject = $2
            """,
            project["id"],
            subject,
        )
        if exists:
            continue
        now = datetime.now(timezone.utc)
        await conn.execute(
            """
            INSERT INTO client_communications
              (project_id, org_id, comm_type, subject, body_draft, body_approved, status,
               drafted_by_agent, reviewed_by, reviewed_at, approved_by, approved_at, sent_at,
               generation_mode)
            VALUES (
              $1, $2, $3::communication_type, $4, $5, $6, $7::communication_status,
              'delivery-agent', $8, $9, $10, $11, $12, 'template'
            )
            """,
            project["id"],
            project["org_id"],
            comm_type,
            subject,
            f"Draft status for {project['name']}: delivery on track with monitored risks.",
            f"Approved status for {project['name']}." if status in {"sent", "approved"} else None,
            status,
            pm_user_id if status in {"in_review", "sent"} else None,
            now if status in {"in_review", "sent"} else None,
            pm_user_id if status == "sent" else None,
            now if status == "sent" else None,
            now if status == "sent" else None,
        )
        inserted += 1
    return inserted


async def ensure_notifications(
    conn: asyncpg.Connection,
    user_id: str,
    org_id: str,
    project: asyncpg.Record,
) -> int:
    title = f"[seed] Attention needed — {project['name']}"
    exists = await conn.fetchval(
        "SELECT 1 FROM notifications WHERE user_id=$1 AND title=$2",
        user_id,
        title,
    )
    if exists:
        return 0
    await conn.execute(
        """
        INSERT INTO notifications
          (user_id, org_id, notification_type, title, body, source_table, source_row_id, is_read)
        VALUES ($1, $2, 'risk_alert'::notification_type, $3, $4, 'projects', $5, FALSE)
        """,
        user_id,
        org_id,
        title,
        "Open delivery/quality risks require PM review.",
        project["id"],
    )
    return 1


async def main() -> None:
    url = database_url()
    kwargs: dict = {"dsn": url}
    if "supabase" in url or "pooler.supabase.com" in url:
        kwargs["ssl"] = ssl_context()

    conn = await asyncpg.connect(**kwargs)
    today = date.today()
    totals = {
        "projects": 0,
        "milestones": 0,
        "throughput": 0,
        "confidence": 0,
        "annotators": 0,
        "quality_snaps": 0,
        "quality_errors": 0,
        "risks": 0,
        "bottlenecks": 0,
        "utilization": 0,
        "comms": 0,
        "notifications": 0,
        "weekly": 0,
        "scope": 0,
        "deps": 0,
        "actions": 0,
        "escalations": 0,
    }

    try:
        # metric configs first
        await seed_metric_configurations(conn)

        projects = await conn.fetch(
            """
            SELECT p.id, p.org_id, p.name, p.status, p.vertical, p.program_id,
                   pr.name AS program_name, o.slug AS org_slug
            FROM projects p
            JOIN organisations o ON o.id = p.org_id
            LEFT JOIN programs pr ON pr.id = p.program_id
            WHERE p.deleted_at IS NULL
              AND o.deleted_at IS NULL
            ORDER BY o.slug, pr.name NULLS LAST, p.name
            """
        )
        if not projects:
            raise SystemExit("No existing projects found. Nothing to seed.")

        pm = await conn.fetchrow(
            """
            SELECT id, org_id FROM users
            WHERE deleted_at IS NULL
              AND email IN ('arbios.kastrati@bsg.dev', 'pm@bsg.dev')
            ORDER BY CASE WHEN email = 'arbios.kastrati@bsg.dev' THEN 0 ELSE 1 END
            LIMIT 1
            """
        )
        pm_user_id = str(pm["id"]) if pm else None

        org_ids: set = set()
        print(f"Seeding PM view data for {len(projects)} existing projects...", flush=True)

        for project in projects:
            totals["projects"] += 1
            org_ids.add(project["org_id"])
            rng = random.Random(str(project["id"]))

            team = await conn.fetchrow(
                """
                SELECT id, org_id, site, name FROM teams
                WHERE project_id = $1 AND deleted_at IS NULL
                ORDER BY created_at
                LIMIT 1
                """,
                project["id"],
            )
            if team is None:
                print(f"  skip {project['name']}: no team")
                continue

            milestones = await ensure_milestones(conn, project, today)
            totals["milestones"] += len(milestones)

            totals["throughput"] += await ensure_throughput(conn, project, today, rng)
            totals["confidence"] += await ensure_confidence(conn, project, milestones, today, rng)
            totals["annotators"] += await ensure_annotators(conn, team, rng)

            snaps, errors = await ensure_quality(conn, project, team, today, rng)
            totals["quality_snaps"] += snaps
            totals["quality_errors"] += errors

            risks, bots = await ensure_risks_and_bottlenecks(conn, project, team, milestones)
            totals["risks"] += risks
            totals["bottlenecks"] += bots

            totals["utilization"] += await ensure_utilization(conn, project, team, today, rng)

            gov = await ensure_governance(conn, project, today)
            totals["scope"] += gov["scope"]
            totals["deps"] += gov["deps"]
            totals["actions"] += gov["actions"]
            totals["escalations"] += gov["escalations"]

            totals["comms"] += await ensure_communications(conn, project, pm_user_id)

            if pm_user_id and project["org_id"] == pm["org_id"] and project["status"] == "active":
                totals["notifications"] += await ensure_notifications(
                    conn, pm_user_id, str(project["org_id"]), project
                )

            print(f"  ok  {project['org_slug']:24} {project['name']}", flush=True)

        totals["weekly"] += await ensure_weekly_summaries(conn, org_ids, today)

        print("\nSeed complete (existing projects only; no users/orgs/projects created):")
        for key, value in totals.items():
            print(f"  {key}: {value}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
