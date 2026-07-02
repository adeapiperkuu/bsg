"""One-off helper to apply SQL migration files via asyncpg."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT / "supabase/migrations/20260625100000_workforce_skills.sql",
    REPO_ROOT / "supabase/migrations/20260625110000_project_dependencies.sql",
    REPO_ROOT / "supabase/migrations/20260625120000_knowledge_lessons.sql",
    REPO_ROOT / "supabase/migrations/20260625130000_quality_phase2_schema.sql",
    REPO_ROOT / "supabase/migrations/20260625140000_inter_agent_signals.sql",
    REPO_ROOT / "supabase/migrations/20260702100000_calibration_briefs.sql",
]


def split_sql_statements(sql: str) -> list[str]:
    lines: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line.split("--", 1)[0])
    body = "\n".join(lines)
    return [part.strip() for part in body.split(";") if part.strip()]


async def apply_file(conn: asyncpg.Connection, path: Path) -> None:
    print(f"Applying {path.name}...")
    sql = path.read_text(encoding="utf-8")
    for statement in split_sql_statements(sql):
        try:
            await conn.execute(statement)
        except asyncpg.DuplicateTableError:
            print(f"  skip (already exists): {statement[:60]}...")
        except asyncpg.DuplicateObjectError:
            print(f"  skip (already exists): {statement[:60]}...")
        except asyncpg.InvalidSchemaNameError as exc:
            if "already exists" in str(exc):
                print(f"  skip: {statement[:60]}...")
            else:
                raise
        except asyncpg.PostgresError as exc:
            if "already exists" in str(exc):
                print(f"  skip: {statement[:60]}...")
            else:
                raise


async def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    import os

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(database_url)
    try:
        for path in MIGRATIONS:
            if not path.exists():
                print(f"Missing migration: {path}", file=sys.stderr)
                return 1
            await apply_file(conn, path)
        row = await conn.fetchval(
            "SELECT to_regclass('public.reviewer_scorecards') IS NOT NULL"
        )
        print(f"reviewer_scorecards exists: {row}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
