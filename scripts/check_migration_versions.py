"""Validate Supabase migration filenames and guard the known duplicate baseline.

Supabase migration versions are the leading 14-digit timestamp in each SQL
filename. Historical duplicate versions cannot be renamed safely until the
live migration history is reconciled, because renaming an already-applied
migration can make deployment tooling treat it as new. This check therefore:

* rejects malformed filenames;
* rejects any new duplicate version;
* reports the known historical duplicates as migration debt; and
* automatically stops warning when a known duplicate is resolved.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
MIGRATION_NAME = re.compile(r"^(?P<version>\d{14})_(?P<name>[a-z0-9_]+)\.sql$")

# Do not add versions here casually. Each entry records pre-existing migration
# history that must be reconciled with the live Supabase schema before rename.
KNOWN_DUPLICATE_VERSIONS = frozenset(
    {
        "20260624100000",
        "20260624120000",
        "20260624130000",
        "20260625140000",
        "20260626100000",
        "20260710120000",
        "20260714100000",
        "20260715100000",
    }
)


def main() -> int:
    if not MIGRATIONS_DIR.is_dir():
        print(f"Migration directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    malformed: list[str] = []
    by_version: dict[str, list[str]] = defaultdict(list)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            malformed.append(path.name)
            continue
        by_version[match.group("version")].append(path.name)

    duplicates = {
        version: names for version, names in by_version.items() if len(names) > 1
    }
    unexpected = sorted(set(duplicates) - KNOWN_DUPLICATE_VERSIONS)

    if malformed:
        print("Malformed migration filenames:", file=sys.stderr)
        for name in malformed:
            print(f"  - {name}", file=sys.stderr)
    if unexpected:
        print("New duplicate migration versions:", file=sys.stderr)
        for version in unexpected:
            print(f"  - {version}: {', '.join(duplicates[version])}", file=sys.stderr)

    known_present = sorted(set(duplicates) & KNOWN_DUPLICATE_VERSIONS)
    if known_present:
        print(
            "Known duplicate migration versions remain; reconcile them with "
            "the live migration history before renaming:"
        )
        for version in known_present:
            print(f"  - {version}: {', '.join(duplicates[version])}")

    resolved = sorted(KNOWN_DUPLICATE_VERSIONS - set(duplicates))
    if resolved:
        print(
            "Resolved versions still listed in KNOWN_DUPLICATE_VERSIONS; "
            f"remove from baseline: {', '.join(resolved)}",
            file=sys.stderr,
        )
        return 1

    if malformed or unexpected:
        return 1

    print(
        f"Validated {sum(len(names) for names in by_version.values())} migration files; "
        f"{len(known_present)} known duplicate version groups remain."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
