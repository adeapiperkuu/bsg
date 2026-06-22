"""
Apply supabase/seed.sql to the database configured in .env (DATABASE_URL).

Usage (from repo root or supabase/):
  python apply_seed.py
  python apply_seed.py --file seed.sql

Requires: asyncpg (install via backend venv: pip install -e "../backend[dev]")
"""
from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import asyncpg
except ImportError:
    print(
        "asyncpg is not installed.\n"
        "Run from the backend venv:\n"
        "  cd backend\n"
        "  pip install -e \".[dev]\"\n"
        "  ..\\backend\\.venv\\Scripts\\python.exe ..\\supabase\\apply_seed.py",
        file=sys.stderr,
    )
    raise SystemExit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_SEED = SCRIPT_DIR / "seed.sql"


def load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_path in (SCRIPT_DIR / ".env", REPO_ROOT / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_database_url(override: str | None = None) -> str:
    if override:
        return override

    values = load_env_values()
    env_value = os.getenv("DATABASE_URL") or values.get("DATABASE_URL")
    if env_value:
        warn_on_database_mismatch(env_value, values.get("SUPABASE_URL"))
        return env_value

    raise SystemExit(
        "DATABASE_URL not found. Set it in bsg/.env or pass --database-url."
    )


def warn_on_database_mismatch(database_url: str, supabase_url: str | None) -> None:
    host = urlparse(normalize_database_url(database_url)).hostname or ""
    if not supabase_url or "supabase.co" not in supabase_url:
        return
    if host in {"localhost", "127.0.0.1"}:
        print(
            "Warning: DATABASE_URL points to localhost, but SUPABASE_URL is a hosted "
            "Supabase project.\n"
            "Update DATABASE_URL in bsg/.env to the hosted connection string from:\n"
            "  Supabase Dashboard -> Project Settings -> Database -> Connection string\n",
            file=sys.stderr,
        )


def normalize_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def supabase_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def connection_kwargs(database_url: str) -> dict:
    normalized = normalize_database_url(database_url)
    parsed = urlparse(normalized)
    host = parsed.hostname or ""

    kwargs: dict = {"dsn": normalized}
    if host.endswith("supabase.co") or "pooler.supabase.com" in host:
        kwargs["ssl"] = supabase_ssl_context()
    return kwargs


def iter_statements(sql: str):
    lines: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if stripped in {"BEGIN;", "COMMIT;"}:
            continue
        lines.append(line)
        if stripped.endswith(";"):
            yield "\n".join(lines)
            lines = []

    if lines:
        raise ValueError("seed.sql appears truncated: last SQL statement is incomplete.")


async def apply_seed(seed_path: Path, database_url: str) -> None:
    if not seed_path.exists():
        raise SystemExit(f"Seed file not found: {seed_path}")

    sql = seed_path.read_text(encoding="utf-8")
    statements = list(iter_statements(sql))
    if not statements:
        raise SystemExit(f"No SQL statements found in {seed_path}")

    print("Connecting to database...")
    try:
        conn = await asyncpg.connect(**connection_kwargs(database_url))
    except asyncpg.InvalidPasswordError as exc:
        host = urlparse(normalize_database_url(database_url)).hostname or "unknown"
        raise SystemExit(
            f"Database login failed for {host}.\n"
            "Your DATABASE_URL username/password do not match the database.\n"
            "For hosted Supabase, copy the URI from:\n"
            "  Project Settings -> Database -> Connection string\n"
            "and set DATABASE_URL in bsg/.env, for example:\n"
            "  postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres"
        ) from exc
    except OSError as exc:
        host = urlparse(normalize_database_url(database_url)).hostname or "unknown"
        if host.startswith("db.") and host.endswith(".supabase.co"):
            raise SystemExit(
                f"Could not reach direct database host '{host}'.\n"
                "On many networks (especially Windows without IPv6), the direct host "
                "db.[project].supabase.co does not resolve.\n"
                "Use the Session pooler URI from Supabase Dashboard instead:\n"
                "  Project Settings -> Database -> Connection string -> Session pooler\n"
                "Example format:\n"
                "  postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres\n"
                "Set that value as DATABASE_URL in bsg/.env, then run apply_seed.py again."
            ) from exc
        raise SystemExit(
            f"Could not reach database host '{host}' ({exc}).\n"
            "Check DATABASE_URL in bsg/.env and your network connection."
        ) from exc

    try:
        exists = await conn.fetchval("SELECT to_regclass('public.organisations') IS NOT NULL")
        if not exists:
            raise SystemExit(
                "Table public.organisations does not exist.\n"
                "Apply the migration first in Supabase SQL Editor:\n"
                "  supabase/migrations/20260622090000_initial_backend_schema.sql"
            )

        print(f"Applying {len(statements)} statements from {seed_path.name}...")
        async with conn.transaction():
            for index, statement in enumerate(statements, start=1):
                await conn.execute(statement)
                if index == 1 or index % 10 == 0 or index == len(statements):
                    print(f"  {index}/{len(statements)} statements executed")

        org_count = await conn.fetchval("SELECT COUNT(*) FROM organisations")
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        print(f"Done. organisations={org_count}, users={user_count}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply supabase/seed.sql to DATABASE_URL")
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_SEED,
        help="Path to seed SQL file (default: supabase/seed.sql)",
    )
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL for this run",
    )
    args = parser.parse_args()

    database_url = load_database_url(args.database_url)
    asyncio.run(apply_seed(args.file.resolve(), database_url))


if __name__ == "__main__":
    main()
