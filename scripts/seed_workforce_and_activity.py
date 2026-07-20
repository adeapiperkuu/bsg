#!/usr/bin/env python3
"""Seed Workforce tab + Operational Tower Recent Activity for EXISTING data.

Populates:
  - Skill Coverage Matrix  (skills, project_skill_requirements, annotator_skills)
  - Capability Gaps        (capability_gaps)
  - Workforce Recommendations (risk_alerts workforce_imbalance + mitigation_recommendations)
  - Operational Tower Recent Activity (notifications for PM users)

Does NOT create users, organisations, programs, projects, or teams.
Idempotent: safe to re-run.

Usage:
  backend\\.venv\\Scripts\\python.exe scripts\\seed_workforce_and_activity.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import ssl
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / "backend" / ".env")
load_dotenv(REPO_ROOT / ".env")

SKILL_CATALOG = [
    # name, category, domain, description, is_critical
    (
        "Computer Vision QA",
        "Quality",
        "computer_vision",
        "Quality assurance for computer-vision annotation output.",
        True,
    ),
    (
        "Content Review",
        "Operations",
        "content_review",
        "General content moderation and review.",
        False,
    ),
    (
        "Safety Policy Review",
        "Trust and Safety",
        "content_review",
        "Safety policy enforcement and escalation review.",
        True,
    ),
    (
        "SME Calibration",
        "Quality",
        "quality",
        "Subject-matter-expert calibration and adjudication.",
        False,
    ),
    (
        "Prompt Engineering",
        "AI Delivery",
        "llm",
        "Prompt design, evaluation, and iteration for LLM workflows.",
        True,
    ),
]

# skill_name -> required_proficiency, headcount, sme_count, priority
REQUIREMENTS = [
    ("Computer Vision QA", "advanced", 3, 1, "high"),
    ("Content Review", "intermediate", 4, 1, "medium"),
    ("Safety Policy Review", "advanced", 3, 2, "critical"),
    ("SME Calibration", "expert", 2, 1, "high"),
    ("Prompt Engineering", "advanced", 2, 1, "high"),
]

# Intentionally under-cover Safety Policy Review and Prompt Engineering
ANNOTATOR_SKILL_PATTERNS = [
    # (name_hash_mod, skill_name, proficiency) — assigned by annotator name hash
    (0, "Computer Vision QA", "expert"),
    (0, "Content Review", "advanced"),
    (1, "Computer Vision QA", "advanced"),
    (1, "Content Review", "intermediate"),
    (2, "Content Review", "intermediate"),
    (2, "SME Calibration", "expert"),
    (3, "Content Review", "advanced"),
    (3, "Prompt Engineering", "intermediate"),  # below required advanced
    (4, "Safety Policy Review", "intermediate"),  # below required advanced
    (4, "Content Review", "beginner"),
]

GAP_TEMPLATES = [
    {
        "skill": "Safety Policy Review",
        "gap_type": "skill_shortage",
        "severity": "critical",
        "title": "Critical shortage: Safety Policy Review",
        "detail": (
            "Required advanced headcount for Safety Policy Review is unmet. "
            "Only intermediate coverage is available on Kosovo Delivery."
        ),
    },
    {
        "skill": "Prompt Engineering",
        "gap_type": "sme_shortage",
        "severity": "high",
        "title": "SME shortage: Prompt Engineering",
        "detail": (
            "Project requires advanced Prompt Engineering SMEs; current certified "
            "SME count is below the required threshold."
        ),
    },
    {
        "skill": None,
        "gap_type": "utilization_overload",
        "severity": "high",
        "title": "Utilization overload on Kosovo Delivery",
        "detail": (
            "Average utilization exceeds the sustainable band. Rebalance workload "
            "before quality and throughput degrade further."
        ),
    },
]

ACTIVITY_TEMPLATES = [
    ("risk_alert", "Delivery risk raised on {project}", "Open delivery risk requires PM review."),
    ("quality_drift_detected", "Quality drift on {project}", "Gold-set accuracy dropped week-over-week."),
    ("skill_gap_detected", "Skill gap detected on {project}", "Safety Policy Review coverage is critically low."),
    ("milestone_at_risk", "Milestone at risk — {project}", "Confidence forecast slipped below the amber band."),
    ("calibration_required", "Calibration required — {project}", "SME calibration overdue for Content Review."),
    ("communication_pending", "Client communication pending — {project}", "Draft status update awaits approval."),
    ("sop_ambiguity_flagged", "SOP ambiguity flagged — {project}", "Policy language conflict found in review guide."),
]

PM_EMAILS = (
    "arbios.kastrati@bsg.dev",
    "pm@bsg.dev",
    "vesa.susuri@bsg.dev",
)


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


async def ensure_skills(conn: asyncpg.Connection, org_id) -> dict[str, object]:
    """Return {skill_name: skill_id} for the org, inserting missing rows."""
    existing = {
        r["name"]: r["id"]
        for r in await conn.fetch(
            "SELECT id, name FROM skills WHERE org_id = $1 AND deleted_at IS NULL",
            org_id,
        )
    }
    for name, category, domain, description, is_critical in SKILL_CATALOG:
        if name in existing:
            continue
        skill_id = uuid4()
        await conn.execute(
            """
            INSERT INTO skills (id, org_id, name, category, domain, description, is_critical)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            skill_id,
            org_id,
            name,
            category,
            domain,
            description,
            is_critical,
        )
        existing[name] = skill_id
    return existing


async def ensure_requirements(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    skills: dict[str, object],
) -> int:
    inserted = 0
    for skill_name, level, headcount, sme_count, priority in REQUIREMENTS:
        skill_id = skills.get(skill_name)
        if skill_id is None:
            continue
        exists = await conn.fetchval(
            """
            SELECT 1 FROM project_skill_requirements
            WHERE project_id = $1 AND skill_id = $2 AND deleted_at IS NULL
            """,
            project["id"],
            skill_id,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO project_skill_requirements
              (org_id, project_id, skill_id, required_proficiency_level,
               required_headcount, required_sme_count, priority)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            project["org_id"],
            project["id"],
            skill_id,
            level,
            headcount,
            sme_count,
            priority,
        )
        inserted += 1
    return inserted


async def ensure_annotator_skills(
    conn: asyncpg.Connection,
    annotators: list[asyncpg.Record],
    skills: dict[str, object],
) -> int:
    inserted = 0
    rows: list[tuple] = []
    for annotator in annotators:
        bucket = abs(hash(annotator["full_name"])) % 5
        for mod, skill_name, level in ANNOTATOR_SKILL_PATTERNS:
            if mod != bucket:
                continue
            skill_id = skills.get(skill_name)
            if skill_id is None:
                continue
            rows.append(
                (
                    annotator["org_id"],
                    annotator["id"],
                    skill_id,
                    level,
                )
            )

    for org_id, annotator_id, skill_id, level in rows:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM annotator_skills
            WHERE annotator_id = $1 AND skill_id = $2 AND deleted_at IS NULL
            """,
            annotator_id,
            skill_id,
        )
        if exists:
            continue
        await conn.execute(
            """
            INSERT INTO annotator_skills (org_id, annotator_id, skill_id, proficiency_level)
            VALUES ($1, $2, $3, $4)
            """,
            org_id,
            annotator_id,
            skill_id,
            level,
        )
        inserted += 1
    return inserted


async def ensure_capability_gaps(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    team_id,
    skills: dict[str, object],
) -> list[asyncpg.Record]:
    """Insert open high/critical gaps; return all open high/critical gaps for project."""
    for tmpl in GAP_TEMPLATES:
        skill_id = skills.get(tmpl["skill"]) if tmpl["skill"] else None
        # Deduped by unique index on (project, gap_type, team, skill) for open/ack
        exists = await conn.fetchval(
            """
            SELECT 1 FROM capability_gaps
            WHERE project_id = $1
              AND gap_type = $2
              AND COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid)
                  = COALESCE($3::uuid, '00000000-0000-0000-0000-000000000000'::uuid)
              AND COALESCE(skill_id, '00000000-0000-0000-0000-000000000000'::uuid)
                  = COALESCE($4::uuid, '00000000-0000-0000-0000-000000000000'::uuid)
              AND deleted_at IS NULL
              AND status IN ('open', 'acknowledged')
            """,
            project["id"],
            tmpl["gap_type"],
            team_id,
            skill_id,
        )
        if exists:
            continue
        evidence = {
            "source": "seed_workforce_and_activity",
            "skill": tmpl["skill"],
            "required_vs_available": "shortfall",
        }
        await conn.execute(
            """
            INSERT INTO capability_gaps
              (org_id, project_id, team_id, skill_id, gap_type, severity,
               title, detail, evidence, status, detected_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, 'open', $10)
            """,
            project["org_id"],
            project["id"],
            team_id,
            skill_id,
            tmpl["gap_type"],
            tmpl["severity"],
            tmpl["title"],
            tmpl["detail"],
            json.dumps(evidence),
            datetime.now(timezone.utc) - timedelta(hours=random.randint(2, 72)),
        )

    return list(
        await conn.fetch(
            """
            SELECT id, title, detail, severity, gap_type
            FROM capability_gaps
            WHERE project_id = $1
              AND deleted_at IS NULL
              AND status IN ('open', 'acknowledged')
              AND severity IN ('high', 'critical')
            """,
            project["id"],
        )
    )


def _gap_to_risk_tier(severity: str) -> str:
    return "critical" if severity == "critical" else "high"


def _gap_to_rec_severity(severity: str) -> str:
    return "high" if severity in {"high", "critical"} else "medium"


async def ensure_workforce_recommendations(
    conn: asyncpg.Connection,
    project: asyncpg.Record,
    gaps: list[asyncpg.Record],
) -> tuple[int, int]:
    risks_created = 0
    recs_created = 0
    for gap in gaps:
        risk = await conn.fetchrow(
            """
            SELECT id FROM risk_alerts
            WHERE project_id = $1
              AND alert_type = 'workforce_imbalance'::alert_type
              AND title = $2
              AND deleted_at IS NULL
              AND status = 'open'::alert_status
            LIMIT 1
            """,
            project["id"],
            gap["title"],
        )
        if risk is None:
            risk_id = uuid4()
            await conn.execute(
                """
                INSERT INTO risk_alerts
                  (id, project_id, org_id, alert_type, risk_tier, title, detail,
                   status, contributing_causes, source_table, source_row_id)
                VALUES (
                  $1, $2, $3, 'workforce_imbalance'::alert_type, $4::risk_tier,
                  $5, $6, 'open'::alert_status, $7::jsonb, 'capability_gaps', $8
                )
                """,
                risk_id,
                project["id"],
                project["org_id"],
                _gap_to_risk_tier(gap["severity"]),
                gap["title"],
                gap["detail"],
                json.dumps({"workforce_imbalance": 1.0}),
                gap["id"],
            )
            risks_created += 1
        else:
            risk_id = risk["id"]

        rec_exists = await conn.fetchval(
            """
            SELECT 1 FROM mitigation_recommendations
            WHERE project_id = $1
              AND source_risk_id = $2
              AND deleted_at IS NULL
            """,
            project["id"],
            risk_id,
        )
        if rec_exists:
            continue
        title = "Rebalance workforce allocation"
        description = (
            "Shift annotator capacity across teams to remove imbalance and restore "
            f"sustainable throughput. Linked risk: {gap['detail']}"
        )
        await conn.execute(
            """
            INSERT INTO mitigation_recommendations
              (project_id, org_id, title, description, severity, confidence_score,
               status, source_risk_id)
            VALUES (
              $1, $2, $3, $4, $5::recommendation_severity, $6,
              'pending'::recommendation_status, $7
            )
            """,
            project["id"],
            project["org_id"],
            title,
            description,
            _gap_to_rec_severity(gap["severity"]),
            Decimal("0.750"),
            risk_id,
        )
        recs_created += 1
    return risks_created, recs_created


async def ensure_tower_activity(
    conn: asyncpg.Connection,
    users: list[asyncpg.Record],
    projects: list[asyncpg.Record],
) -> int:
    """Seed varied notifications for PM users so Tower Recent Activity is populated."""
    if not users or not projects:
        return 0

    # Prefer active BSG projects for titles; fall back to any.
    bsg_projects = [p for p in projects if p["org_slug"] == "bsg" and p["status"] == "active"]
    pool = bsg_projects or [p for p in projects if p["status"] == "active"] or projects

    inserted = 0
    now = datetime.now(timezone.utc)
    for user in users:
        for i, (ntype, title_tmpl, body_tmpl) in enumerate(ACTIVITY_TEMPLATES):
            project = pool[i % len(pool)]
            title = title_tmpl.format(project=project["name"])
            exists = await conn.fetchval(
                "SELECT 1 FROM notifications WHERE user_id = $1 AND title = $2",
                user["id"],
                title,
            )
            if exists:
                continue
            created_at = now - timedelta(hours=i * 3 + 1, minutes=i * 7)
            await conn.execute(
                """
                INSERT INTO notifications
                  (user_id, org_id, notification_type, title, body,
                   source_table, source_row_id, is_read, created_at, sent_at)
                VALUES (
                  $1, $2, $3::notification_type, $4, $5,
                  'projects', $6, $7, $8, $8
                )
                """,
                user["id"],
                user["org_id"],
                ntype,
                title,
                body_tmpl.format(project=project["name"]),
                project["id"],
                i % 3 == 0,  # mix of read/unread
                created_at,
            )
            inserted += 1
    return inserted


async def main() -> None:
    url = database_url()
    kwargs: dict = {"dsn": url}
    if "supabase" in url or "pooler.supabase.com" in url:
        kwargs["ssl"] = ssl_context()

    conn = await asyncpg.connect(**kwargs)
    totals = {
        "orgs_skilled": 0,
        "requirements": 0,
        "annotator_skills": 0,
        "capability_gaps_projects": 0,
        "workforce_risks": 0,
        "workforce_recs": 0,
        "notifications": 0,
        "projects": 0,
    }

    try:
        projects = await conn.fetch(
            """
            SELECT p.id, p.org_id, p.name, p.status, o.slug AS org_slug, o.name AS org_name
            FROM projects p
            JOIN organisations o ON o.id = p.org_id
            WHERE p.deleted_at IS NULL AND o.deleted_at IS NULL
            ORDER BY o.slug, p.name
            """
        )
        users = await conn.fetch(
            """
            SELECT id, email, org_id FROM users
            WHERE deleted_at IS NULL AND email = ANY($1::text[])
            """,
            list(PM_EMAILS),
        )

        print(
            f"Seeding workforce + activity for {len(projects)} projects "
            f"({len(users)} PM users)...",
            flush=True,
        )

        skills_by_org: dict[object, dict[str, object]] = {}

        for project in projects:
            totals["projects"] += 1
            org_id = project["org_id"]
            if org_id not in skills_by_org:
                skills_by_org[org_id] = await ensure_skills(conn, org_id)
                totals["orgs_skilled"] += 1
            skills = skills_by_org[org_id]

            team = await conn.fetchrow(
                """
                SELECT id, org_id, name FROM teams
                WHERE project_id = $1 AND deleted_at IS NULL
                ORDER BY created_at
                LIMIT 1
                """,
                project["id"],
            )
            if team is None:
                print(f"  skip {project['org_slug']:24} {project['name']}: no team", flush=True)
                continue

            totals["requirements"] += await ensure_requirements(conn, project, skills)

            annotators = await conn.fetch(
                """
                SELECT id, org_id, full_name FROM annotators
                WHERE team_id = $1 AND deleted_at IS NULL
                """,
                team["id"],
            )
            totals["annotator_skills"] += await ensure_annotator_skills(
                conn, list(annotators), skills
            )

            gaps = await ensure_capability_gaps(conn, project, team["id"], skills)
            totals["capability_gaps_projects"] += 1 if gaps else 0

            risks, recs = await ensure_workforce_recommendations(conn, project, gaps)
            totals["workforce_risks"] += risks
            totals["workforce_recs"] += recs

            print(
                f"  ok  {project['org_slug']:24} {project['name']} "
                f"(annotators={len(annotators)}, gaps={len(gaps)}, "
                f"+risks={risks}, +recs={recs})",
                flush=True,
            )

        totals["notifications"] = await ensure_tower_activity(
            conn, list(users), list(projects)
        )

        print("\nSeed complete (no users/orgs/projects created):")
        for key, value in totals.items():
            print(f"  {key}: {value}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
