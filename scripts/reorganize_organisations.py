"""Reorganize orgs: remove Northwind, one org per project + BSG for internal."""

from __future__ import annotations

import asyncio
import os
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / "backend" / ".env")
load_dotenv(REPO_ROOT / ".env")

# Programs treated as BSG-internal stay under BSG; all others get a dedicated org.
INTERNAL_PROGRAMS = {
    "AI Driven Operational Intelligence",
    "Intelligent Systems",
    "Leadership AI",
    "BOE - Operational Excellence",
}


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = slug.replace("&", " and ")
    slug = slug.replace(".", " ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "org"


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


async def ensure_org(conn: asyncpg.Connection, *, name: str, slug: str, vertical: str, region: str) -> str:
    row = await conn.fetchrow(
        """
        SELECT id FROM organisations
        WHERE deleted_at IS NULL AND (slug = $1 OR lower(name) = lower($2))
        LIMIT 1
        """,
        slug,
        name,
    )
    if row:
        await conn.execute(
            """
            UPDATE organisations
            SET name = $2, slug = $3, vertical = $4, region = $5,
                is_active = TRUE, deleted_at = NULL, updated_at = now()
            WHERE id = $1
            """,
            row["id"],
            name,
            slug,
            vertical,
            region,
        )
        return str(row["id"])

    # Revive soft-deleted match on slug if present.
    dead = await conn.fetchrow(
        "SELECT id FROM organisations WHERE slug = $1 LIMIT 1",
        slug,
    )
    if dead:
        await conn.execute(
            """
            UPDATE organisations
            SET name = $2, vertical = $3, region = $4,
                is_active = TRUE, deleted_at = NULL, updated_at = now()
            WHERE id = $1
            """,
            dead["id"],
            name,
            vertical,
            region,
        )
        return str(dead["id"])

    org_id = await conn.fetchval(
        """
        INSERT INTO organisations (name, slug, vertical, region, is_active)
        VALUES ($1, $2, $3, $4, TRUE)
        RETURNING id
        """,
        name,
        slug,
        vertical,
        region,
    )
    return str(org_id)


async def ensure_bsg(conn: asyncpg.Connection) -> str:
    """Prefer renaming existing bsg-platform → BSG to keep FKs stable."""
    existing = await conn.fetchrow(
        """
        SELECT id FROM organisations
        WHERE deleted_at IS NULL AND slug IN ('bsg', 'bsg-platform')
        ORDER BY CASE WHEN slug = 'bsg' THEN 0 ELSE 1 END
        LIMIT 1
        """
    )
    if existing:
        await conn.execute(
            """
            UPDATE organisations
            SET name = 'BSG', slug = 'bsg', vertical = 'platform', region = 'global',
                is_active = TRUE, deleted_at = NULL, updated_at = now()
            WHERE id = $1
            """,
            existing["id"],
        )
        return str(existing["id"])
    return await ensure_org(
        conn,
        name="BSG",
        slug="bsg",
        vertical="platform",
        region="global",
    )


async def reassign_tree(conn: asyncpg.Connection, program_id: str, org_id: str) -> None:
    await conn.execute(
        "UPDATE programs SET org_id = $1::uuid, updated_at = now() WHERE id = $2::uuid",
        org_id,
        program_id,
    )
    project_ids = [
        str(r["id"])
        for r in await conn.fetch(
            "SELECT id FROM projects WHERE program_id = $1::uuid AND deleted_at IS NULL",
            program_id,
        )
    ]
    if not project_ids:
        return

    await conn.execute(
        "UPDATE projects SET org_id = $1::uuid, updated_at = now() WHERE program_id = $2::uuid",
        org_id,
        program_id,
    )
    # Keep dependent org-scoped rows aligned for the scopes under this program.
    for table in (
        "project_assignments",
        "teams",
        "milestones",
        "throughput_snapshots",
        "team_throughput_snapshots",
        "utilization_snapshots",
        "annotators",
        "risk_alerts",
        "bottlenecks",
        "delivery_confidence_scores",
        "quality_snapshots",
        "client_communications",
    ):
        exists = await conn.fetchval(
            "SELECT to_regclass('public.' || $1) IS NOT NULL",
            table,
        )
        if not exists:
            continue
        # Only update rows that reference these project ids when the column exists.
        cols = {
            r["column_name"]
            for r in await conn.fetch(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                """,
                table,
            )
        }
        if "org_id" not in cols:
            continue
        if "project_id" in cols:
            await conn.execute(
                f"""
                UPDATE {table}
                SET org_id = $1::uuid
                WHERE project_id = ANY($2::uuid[])
                """,
                org_id,
                project_ids,
            )


async def main() -> None:
    url = database_url()
    kwargs: dict = {"dsn": url}
    if "supabase" in url or "pooler.supabase.com" in url:
        kwargs["ssl"] = ssl_context()

    conn = await asyncpg.connect(**kwargs)
    try:
        async with conn.transaction():
            bsg_id = await ensure_bsg(conn)
            print(f"BSG org id={bsg_id}")

            await conn.execute(
                """
                UPDATE organisations
                SET deleted_at = now(), is_active = FALSE, updated_at = now()
                WHERE deleted_at IS NULL
                  AND slug = 'northwind-analytics'
                """
            )
            print("Soft-deleted Northwind Analytics")

            programs = await conn.fetch(
                """
                SELECT id, name, org_id, description
                FROM programs
                WHERE deleted_at IS NULL
                ORDER BY name
                """
            )
            print(f"Programs: {len(programs)}")

            for program in programs:
                name = program["name"]
                if name in INTERNAL_PROGRAMS:
                    org_id = bsg_id
                    label = "BSG (internal)"
                else:
                    # One organisation per client/product project.
                    vertical_row = await conn.fetchrow(
                        """
                        SELECT vertical FROM projects
                        WHERE program_id = $1::uuid AND deleted_at IS NULL
                        ORDER BY created_at LIMIT 1
                        """,
                        program["id"],
                    )
                    vertical = vertical_row["vertical"] if vertical_row else "other"
                    org_id = await ensure_org(
                        conn,
                        name=name,
                        slug=slugify(name),
                        vertical=vertical,
                        region="europe",
                    )
                    label = name

                await reassign_tree(conn, str(program["id"]), org_id)
                print(f"  {name} -> {label}")

            # Move staff to BSG; TTL client users to TTL org.
            ttl_org = await conn.fetchrow(
                """
                SELECT id FROM organisations
                WHERE deleted_at IS NULL
                  AND (slug = 'ttl-tax-tech-lab' OR slug = 'ttl' OR lower(name) LIKE 'ttl%')
                ORDER BY CASE WHEN slug = 'ttl-tax-tech-lab' THEN 0 WHEN slug = 'ttl' THEN 1 ELSE 2 END
                LIMIT 1
                """
            )
            ttl_id = str(ttl_org["id"]) if ttl_org else None

            users = await conn.fetch(
                "SELECT id, email, role FROM users WHERE deleted_at IS NULL"
            )
            for user in users:
                email = user["email"].lower()
                if email in {"ttl@bsg.dev", "client@bsg.dev"} and ttl_id:
                    target = ttl_id
                else:
                    target = bsg_id
                await conn.execute(
                    "UPDATE users SET org_id = $1::uuid, updated_at = now() WHERE id = $2",
                    target,
                    user["id"],
                )

            # Soft-delete leftover bare ttl slug if renamed org exists.
            ttl_named = await conn.fetchrow(
                """
                SELECT id FROM organisations
                WHERE deleted_at IS NULL AND slug = 'ttl-tax-tech-lab'
                """
            )
            if ttl_named:
                await conn.execute(
                    """
                    UPDATE organisations
                    SET deleted_at = now(), is_active = FALSE, updated_at = now()
                    WHERE deleted_at IS NULL AND slug = 'ttl' AND id <> $1
                    """,
                    ttl_named["id"],
                )

            active = await conn.fetch(
                """
                SELECT name, slug, vertical, region
                FROM organisations
                WHERE deleted_at IS NULL
                ORDER BY name
                """
            )
            print("\nActive organisations:")
            for org in active:
                print(f"  - {org['name']} ({org['slug']})")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
