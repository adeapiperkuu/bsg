"""Manually run the UTC-day Governance register summary refresh."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.governance.services.project_governance_summary_service import (  # noqa: E402
    refresh_stale_governance_summary_counts,
)
from app.agents.governance.services.register_service import (  # noqa: E402
    invalidate_register_list_cache,
)
from app.db.session import session_scope  # noqa: E402


async def main() -> None:
    async with session_scope() as session:
        try:
            result = await refresh_stale_governance_summary_counts(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    removed = sum(invalidate_register_list_cache(org_id=org_id) for org_id in result.org_ids)
    print(
        "Governance register summary refresh complete: "
        f"business_date={result.business_date} rows_refreshed={result.rows_refreshed} "
        f"org_count={len(result.org_ids)} execute_count={result.execute_count} "
        f"refresh_ms={result.duration_ms} register_cache_removed={removed} timezone=UTC"
    )


if __name__ == "__main__":
    asyncio.run(main())
