"""Apply only the calibration_briefs migration."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "supabase/migrations/20260702100000_calibration_briefs.sql"


async def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    sql = MIGRATION.read_text(encoding="utf-8")
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(sql)
        exists = await conn.fetchval("SELECT to_regclass('public.calibration_briefs') IS NOT NULL")
        print(f"calibration_briefs exists: {exists}")
    except asyncpg.DuplicateTableError:
        print("calibration_briefs already exists")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
