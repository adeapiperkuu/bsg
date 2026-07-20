"""Strip program name prefixes from scope/sprint names (idempotent)."""

from __future__ import annotations

import asyncio
import os
import ssl
from pathlib import Path

from dotenv import load_dotenv

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / "backend" / ".env")
load_dotenv(REPO_ROOT / ".env")


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


async def main() -> None:
    url = database_url()
    kwargs: dict = {"dsn": url}
    if "supabase" in url or "pooler.supabase.com" in url:
        kwargs["ssl"] = ssl_context()

    conn = await asyncpg.connect(**kwargs)
    try:
        rows = await conn.fetch(
            """
            SELECT p.id, p.name AS scope_name, pr.name AS program_name
            FROM projects p
            JOIN programs pr ON pr.id = p.program_id
            WHERE p.deleted_at IS NULL
              AND p.program_id IS NOT NULL
              AND p.name LIKE pr.name || ' · %'
            """
        )
        updated = 0
        for row in rows:
            new_name = row["scope_name"][len(row["program_name"]) + 3 :]
            await conn.execute(
                "UPDATE projects SET name = $1, updated_at = now() WHERE id = $2",
                new_name,
                row["id"],
            )
            updated += 1
        print(f"Renamed {updated} scopes to sprint-only names.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
