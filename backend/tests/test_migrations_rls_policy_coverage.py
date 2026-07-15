"""Guards against two confirmed bug classes in DEVELOPMENT_PLAN.md Workstreams
B and H:

1. A migration enabling RLS on a table without ever adding a CREATE POLICY
   for it. Postgres default-denies every operation on such a table, which
   silently breaks any code that writes to it through a non-superuser,
   RLS-bound connection.
2. A policy checking `current_setting('app.role', ...)` -- a Postgres
   session variable this codebase never sets anywhere (every real policy
   resolves the caller's role via `public.auth_user_role()`, which looks up
   `public.current_user_id()` in `public.users`). A policy using `app.role`
   can never be satisfied by any real request; see BUG-008
   (quality_error_categories / quality_scan_runs), found because this class
   of bug wasn't otherwise being checked for anywhere.

This is a pure text scan over the migration files -- no database required.

NOTE (Workstream H, 2026-07-14): earlier versions of the two regexes below
didn't account for schema-qualified table names (`public.foo` vs. `foo`),
which meant every migration using `public.foo` syntax was invisible to this
lint entirely -- neither "enabled" nor "policied", so a table in that
category with zero policies would have passed silently. Confirmed via the
live database: 80 tables have `rowsecurity=true` but this lint's original
regex only ever found ~68. Fixed by making the `public.` prefix optional.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

ENABLE_RLS_RE = re.compile(
    r"ALTER TABLE\s+(?:IF EXISTS\s+)?(?:public\.)?(\w+)\s+ENABLE ROW LEVEL SECURITY", re.IGNORECASE
)
CREATE_POLICY_RE = re.compile(r"CREATE POLICY\s+\w+\s+ON\s+(?:public\.)?(\w+)", re.IGNORECASE)
# Captures policy name + everything up to the next top-level `;`, so each
# occurrence's body can be checked independently of other policies.
CREATE_POLICY_BODY_RE = re.compile(r"CREATE POLICY\s+(\w+)\s+ON\s+(?:public\.)?\w+.*?;", re.IGNORECASE | re.DOTALL)
DROP_POLICY_RE = re.compile(r"DROP POLICY\s+(?:IF EXISTS\s+)?(\w+)\s+ON", re.IGNORECASE)
DEAD_SESSION_VAR_RE = re.compile(r"current_setting\(\s*'app\.role'", re.IGNORECASE)


def _scan_migrations() -> tuple[dict[str, str], set[str]]:
    enabled: dict[str, str] = {}
    policied: set[str] = set()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for match in ENABLE_RLS_RE.finditer(text):
            enabled[match.group(1)] = path.name
        for match in CREATE_POLICY_RE.finditer(text):
            policied.add(match.group(1))
    return enabled, policied


def test_every_rls_enabled_table_has_at_least_one_policy() -> None:
    enabled, policied = _scan_migrations()
    missing = sorted(set(enabled) - policied)
    assert not missing, (
        "These tables run ALTER TABLE ... ENABLE ROW LEVEL SECURITY but have no "
        "CREATE POLICY anywhere in supabase/migrations/, which means every "
        "operation against them is default-denied for any non-superuser "
        "connection: "
        + ", ".join(f"{table} (enabled in {source})" for table, source in ((t, enabled[t]) for t in missing))
    )


def test_migrations_directory_is_not_empty() -> None:
    # Guards against the check above passing vacuously if the path is ever wrong.
    assert list(MIGRATIONS_DIR.glob("*.sql")), f"No migration files found under {MIGRATIONS_DIR}"


def test_no_policy_uses_the_dead_app_role_session_variable() -> None:
    """Drop/recreate-aware: a policy fixed by a later migration (DROP + CREATE
    under the same name, e.g. BUG-008's fix) must not keep failing this check
    forever just because the original, now-superseded migration file --
    which this repo's convention says to never edit after it's applied --
    still contains the old, broken text. Only currently-live policies count."""
    live_bodies: dict[str, str] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for match in DROP_POLICY_RE.finditer(text):
            live_bodies.pop(match.group(1), None)
        for match in CREATE_POLICY_BODY_RE.finditer(text):
            live_bodies[match.group(1)] = match.group(0)

    offending = sorted(name for name, body in live_bodies.items() if DEAD_SESSION_VAR_RE.search(body))
    assert not offending, (
        "These currently-live policies reference current_setting('app.role', ...), "
        "a Postgres session variable this codebase never sets anywhere -- they can "
        "never be satisfied by a real request (see BUG-008). Use "
        "public.auth_user_role() instead, matching every other policy: "
        + ", ".join(offending)
    )
