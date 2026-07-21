"""
Backup all public-schema table data, then truncate those tables.

Usage (from repo root):
  python scripts/backup_and_clean_db.py
  python scripts/backup_and_clean_db.py --backup-only
  python scripts/backup_and_clean_db.py --clean-only --from backups/<stamp>

Never prints DATABASE_URL or credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    import asyncpg
except ImportError:
    print("asyncpg is required. pip install asyncpg", file=sys.stderr)
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = REPO_ROOT / "backups"

# Leave migration / extension bookkeeping alone if present.
SKIP_TABLES = {
    "schema_migrations",
    "supabase_migrations",
}


def load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_path in (
        REPO_ROOT / ".env",
        REPO_ROOT / "backend" / ".env",
        REPO_ROOT / "supabase" / ".env",
    ):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_database_url() -> str:
    values = load_env_values()
    url = os.getenv("DATABASE_URL") or values.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found in environment or .env files.")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def prefer_session_pooler(url: str) -> str:
    """Transaction pooler (:6543) is unreliable for long dumps; prefer :5432."""
    parsed = urlparse(url)
    if parsed.port == 6543 and "pooler.supabase.com" in (parsed.hostname or ""):
        return url.replace(":6543/", ":5432/")
    return url


def supabase_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def connection_kwargs(database_url: str) -> dict:
    parsed = urlparse(database_url)
    host = parsed.hostname or ""
    kwargs: dict = {"dsn": database_url}
    if host.endswith("supabase.co") or "pooler.supabase.com" in host:
        kwargs["ssl"] = supabase_ssl_context()
    return kwargs


def safe_host(database_url: str) -> str:
    return urlparse(database_url).hostname or "unknown"


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        raw = bytes(value)
        return r"'\x" + raw.hex() + "'"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
        return "'" + text.replace("'", "''") + "'::jsonb"
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


async def list_public_tables(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname <> ALL($1::text[])
        ORDER BY c.relname
        """,
        list(SKIP_TABLES),
    )
    return [row["table_name"] for row in rows]


async def table_columns(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT a.attname
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = $1
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        table,
    )
    return [row["attname"] for row in rows]


async def backup_database(conn: asyncpg.Connection, stamp_dir: Path) -> dict[str, int]:
    stamp_dir.mkdir(parents=True, exist_ok=True)
    tables = await list_public_tables(conn)
    counts: dict[str, int] = {}
    data_path = stamp_dir / "data.sql"
    meta_path = stamp_dir / "manifest.json"

    with data_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("-- BSG public-schema data backup\n")
        fh.write(f"-- created_at: {datetime.now(timezone.utc).isoformat()}\n")
        fh.write("-- restore: apply migrations first, then run this file\n")
        fh.write("BEGIN;\n")
        fh.write("SET session_replication_role = replica;\n\n")

        for table in tables:
            columns = await table_columns(conn, table)
            if not columns:
                counts[table] = 0
                continue
            col_sql = ", ".join(f'"{c}"' for c in columns)
            rows = await conn.fetch(f'SELECT {col_sql} FROM public."{table}"')
            counts[table] = len(rows)
            fh.write(f"-- {table}: {len(rows)} rows\n")
            if not rows:
                fh.write("\n")
                continue
            for row in rows:
                values = ", ".join(sql_literal(row[c]) for c in columns)
                fh.write(
                    f'INSERT INTO public."{table}" ({col_sql}) VALUES ({values});\n'
                )
            fh.write("\n")

        fh.write("SET session_replication_role = DEFAULT;\n")
        fh.write("COMMIT;\n")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": safe_host(conn._protocol.addr[0] if False else ""),  # filled below
        "table_count": len(tables),
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "data_file": data_path.name,
    }
    # Prefer hostname from env URL rather than poking internals.
    manifest["host"] = safe_host(os.environ.get("_BSG_BACKUP_URL", ""))
    meta_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return counts


async def clean_database(conn: asyncpg.Connection) -> list[str]:
    tables = await list_public_tables(conn)
    if not tables:
        return []
    # Single TRUNCATE ... CASCADE clears FKs safely.
    quoted = ", ".join(f'public."{t}"' for t in tables)
    await conn.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
    return tables


async def count_rows(conn: asyncpg.Connection, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = int(await conn.fetchval(f'SELECT COUNT(*) FROM public."{table}"'))
    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backup then clean public schema data.")
    parser.add_argument("--backup-only", action="store_true")
    parser.add_argument("--clean-only", action="store_true")
    parser.add_argument(
        "--from",
        dest="from_backup",
        help="Existing backup directory (required with --clean-only for safety check)",
    )
    args = parser.parse_args()
    if args.backup_only and args.clean_only:
        print("Choose only one of --backup-only / --clean-only", file=sys.stderr)
        return 2
    if args.clean_only and not args.from_backup:
        print("--clean-only requires --from <backup-dir>", file=sys.stderr)
        return 2

    database_url = prefer_session_pooler(load_database_url())
    # Stash for manifest host only (not printed).
    os.environ["_BSG_BACKUP_URL"] = database_url
    host = safe_host(database_url)
    # Redact any accidental password echo from exceptions.
    redacted = re.sub(r":([^:@/]+)@", ":***@", database_url)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamp_dir = Path(args.from_backup) if args.from_backup else BACKUP_ROOT / stamp
    if args.from_backup and not stamp_dir.is_absolute():
        stamp_dir = REPO_ROOT / stamp_dir

    print(f"Connecting to {host}...")
    try:
        conn = await asyncpg.connect(**connection_kwargs(database_url))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        msg = msg.replace(unquote(urlparse(database_url).password or ""), "***")
        print(f"Connection failed: {msg}", file=sys.stderr)
        print(f"(url host form: {redacted.split('@')[-1]})", file=sys.stderr)
        return 1

    try:
        tables = await list_public_tables(conn)
        print(f"Found {len(tables)} public tables.")

        if not args.clean_only:
            print(f"Writing backup to {stamp_dir.relative_to(REPO_ROOT)} ...")
            counts = await backup_database(conn, stamp_dir)
            total = sum(counts.values())
            non_empty = sum(1 for n in counts.values() if n > 0)
            data_file = stamp_dir / "data.sql"
            size_mb = data_file.stat().st_size / (1024 * 1024)
            print(f"Backup complete: {total} rows across {non_empty} non-empty tables ({size_mb:.2f} MiB).")
            if data_file.stat().st_size == 0:
                print("Backup file is empty; refusing to clean.", file=sys.stderr)
                return 1

        if args.backup_only:
            print("Backup-only mode: skipping clean.")
            return 0

        if args.clean_only:
            data_file = stamp_dir / "data.sql"
            if not data_file.exists() or data_file.stat().st_size == 0:
                print(f"Refusing to clean: missing/empty backup at {data_file}", file=sys.stderr)
                return 1

        print("Truncating all public tables (RESTART IDENTITY CASCADE)...")
        truncated = await clean_database(conn)
        after = await count_rows(conn, truncated)
        remaining = sum(after.values())
        print(f"Clean complete: truncated {len(truncated)} tables; remaining rows={remaining}.")
        if remaining != 0:
            leftovers = {k: v for k, v in after.items() if v}
            print(f"WARNING: some tables still have rows: {leftovers}", file=sys.stderr)
            return 1
        print(f"Backup kept at: {stamp_dir}")
        return 0
    finally:
        await conn.close()
        os.environ.pop("_BSG_BACKUP_URL", None)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
