"""Verify Governance schema state needed by the current application code.

This script inspects the live database schema. It does not apply migrations and
never prints DATABASE_URL or credentials.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_MIGRATIONS = [
    "20260626160000_governance_charter_phase5",
    "20260630120000_governance_phase8_hardening",
    "20260713120000_governance_ai_recommendations_phase6",
    "20260713130000_governance_ai_recommendation_conversions_phase7",
    "20260713140000_governance_record_evidence_links_phase8",
    "20260713170000_governance_recommendation_effectiveness_phase12",
    "20260713180000_governance_recommendation_optimization_phase13",
    "20260713190000_governance_charter_knowledge_phase14",
    "20260715100000_governance_background_jobs_phase_f",
]

REQUIRED_TABLES = [
    "project_charters",
    "governance_evidence_links",
    "governance_charter_publication_events",
    "governance_charter_publication_audits",
    "governance_ai_recommendations",
    "governance_ai_recommendation_feedback",
    "governance_ai_recommendation_conversions",
    "governance_jobs",
    "governance_job_events",
]

REQUIRED_COLUMNS = {
    "project_charters": [
        "id",
        "org_id",
        "project_id",
        "version",
        "status",
        "generated_text",
        "visibility",
        "approved_by",
        "approved_at",
        "knowledge_document_id",
        "knowledge_version_id",
        "publication_status",
        "published_at",
        "published_by",
        "publication_error",
        "publication_attempt_count",
        "last_publication_attempt_at",
    ],
    "governance_evidence_links": ["id", "org_id", "summary_id", "charter_id", "source_type", "source_id"],
    "governance_jobs": [
        "id",
        "org_id",
        "project_id",
        "job_type",
        "status",
        "requested_by",
        "idempotency_key",
        "request_payload",
        "result_record_type",
        "result_record_id",
        "result_data",
        "heartbeat_at",
        "worker_id",
        "cancel_requested_at",
        "queue_wait_ms",
        "processing_ms",
    ],
    "governance_job_events": ["id", "org_id", "project_id", "job_id", "event_type", "created_at"],
}

EXPECTED_INDEXES = [
    "project_charters_project_id_idx",
    "project_charters_org_project_status_created_idx",
    "project_charters_publication_status_idx",
    "project_charters_knowledge_document_idx",
    "project_charters_published_knowledge_version_uidx",
    "governance_evidence_links_charter_idx",
    "governance_jobs_active_idempotency_uidx",
    "governance_jobs_queue_idx",
    "governance_jobs_org_requested_idx",
    "governance_job_events_job_created_idx",
]


def _database_url() -> str | None:
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT / "backend/.env", override=True)
    value = os.environ.get("DATABASE_URL")
    if value and value.startswith("postgresql+asyncpg://"):
        return value.replace("postgresql+asyncpg://", "postgresql://", 1)
    return value


async def _applied_migrations(conn: asyncpg.Connection) -> set[str] | None:
    migration_table = await conn.fetchval(
        """
        SELECT to_regclass('supabase_migrations.schema_migrations')::text
        """
    )
    if not migration_table:
        return None
    columns = {
        row["column_name"]
        for row in await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'supabase_migrations'
              AND table_name = 'schema_migrations'
            """
        )
    }
    if "version" not in columns:
        return set()
    rows = await conn.fetch("SELECT version::text AS version FROM supabase_migrations.schema_migrations")
    return {row["version"] for row in rows}


async def _existing_tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    return {row["table_name"] for row in rows}


async def _existing_columns(conn: asyncpg.Connection, table: str) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        """,
        table,
    )
    return {row["column_name"] for row in rows}


async def _existing_indexes(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
        """
    )
    return {row["indexname"] for row in rows}


async def main() -> int:
    database_url = _database_url()
    if not database_url:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        return 2

    failures: list[str] = []
    conn = await asyncpg.connect(database_url, statement_cache_size=0)
    try:
        print("Governance schema verification")
        print("Connection: configured (URL redacted)")

        applied = await _applied_migrations(conn)
        if applied is None:
            print("Applied migrations: unavailable (supabase_migrations.schema_migrations missing)")
        else:
            missing_migrations = [
                migration for migration in EXPECTED_MIGRATIONS if migration.split("_", 1)[0] not in applied
            ]
            print(f"Applied migrations table: present ({len(applied)} versions recorded)")
            if missing_migrations:
                failures.append(f"Missing recorded migration versions: {', '.join(missing_migrations)}")

        tables = await _existing_tables(conn)
        missing_tables = [table for table in REQUIRED_TABLES if table not in tables]
        if missing_tables:
            failures.append(f"Missing tables: {', '.join(missing_tables)}")
        else:
            print("Required governance tables: present")

        for table, expected_columns in REQUIRED_COLUMNS.items():
            existing = await _existing_columns(conn, table)
            missing = [column for column in expected_columns if column not in existing]
            if missing:
                failures.append(f"Missing columns on {table}: {', '.join(missing)}")
        if not any(item.startswith("Missing columns") for item in failures):
            print("Required governance columns: present")

        indexes = await _existing_indexes(conn)
        missing_indexes = [index for index in EXPECTED_INDEXES if index not in indexes]
        if missing_indexes:
            failures.append(f"Missing indexes: {', '.join(missing_indexes)}")
        else:
            print("Expected charter/job indexes: present")

        if failures:
            print("\nSchema verification failed:")
            for failure in failures:
                print(f"- {failure}")
            return 1

        print("Schema appears compatible with current Governance ORM models.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
