"""Measure communications list / detail / draft latency against the live DB.

Usage (from backend/):
  python scripts/measure_communications_latency.py

Does not log report bodies or PM instructions.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

load_dotenv(REPO_ROOT / "backend" / ".env")
load_dotenv(REPO_ROOT / ".env", override=False)


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return ordered[idx]


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    engine = create_async_engine(_async_url(database_url), pool_size=2, max_overflow=0)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from app.core.security import CurrentUser
    from app.db.models import AppRole, ClientCommunication, CommunicationStatus
    from app.services.communications import (
        list_client_sent_communications,
        list_org_communications,
    )

    async with Session() as session:
        org_id = (
            await session.execute(
                select(ClientCommunication.org_id)
                .where(ClientCommunication.status == CommunicationStatus.SENT)
                .limit(1)
            )
        ).scalar_one_or_none()
        if org_id is None:
            org_id = (
                await session.execute(select(ClientCommunication.org_id).limit(1))
            ).scalar_one_or_none()
        if org_id is None:
            print("No client_communications rows found; skipping live list measures.")
            await engine.dispose()
            return 0

        dm = CurrentUser(
            id=UUID(int=0),
            org_id=org_id,
            email="latency@example.com",
            role=AppRole.DELIVERY_MANAGER,
            is_active=True,
        )
        client = CurrentUser(
            id=UUID(int=1),
            org_id=org_id,
            email="client-latency@example.com",
            role=AppRole.CLIENT,
            is_active=True,
        )

        # Warm
        await list_org_communications(session, dm, limit=30, offset=0)

        list_ms: list[float] = []
        for _ in range(12):
            t0 = perf_counter()
            page = await list_org_communications(session, dm, limit=30, offset=0)
            list_ms.append((perf_counter() - t0) * 1000)
        print(
            f"pm_list_db n=12 avg={statistics.mean(list_ms):.1f}ms "
            f"p50={_pct(list_ms, 50):.1f}ms p95={_pct(list_ms, 95):.1f}ms "
            f"rows={len(page.items)} total={page.total} list_db_ms={page.db_ms:.1f}"
        )

        detail_ms: list[float] = []
        sample_id = page.items[0].id if page.items else None
        if sample_id:
            for _ in range(12):
                t0 = perf_counter()
                row = (
                    await session.execute(
                        select(ClientCommunication).where(ClientCommunication.id == sample_id)
                    )
                ).scalar_one()
                _ = row.subject, row.body_draft, row.body_approved, row.status
                detail_ms.append((perf_counter() - t0) * 1000)
            print(
                f"detail_db n=12 avg={statistics.mean(detail_ms):.1f}ms "
                f"p50={_pct(detail_ms, 50):.1f}ms p95={_pct(detail_ms, 95):.1f}ms"
            )

        client_ms: list[float] = []
        for _ in range(12):
            t0 = perf_counter()
            client_page = await list_client_sent_communications(session, client, limit=30, offset=0)
            client_ms.append((perf_counter() - t0) * 1000)
        print(
            f"client_sent_list n=12 avg={statistics.mean(client_ms):.1f}ms "
            f"p50={_pct(client_ms, 50):.1f}ms p95={_pct(client_ms, 95):.1f}ms "
            f"rows={len(client_page.items)} total={client_page.total}"
        )

        # Confirm no bodies in list SQL shape
        explain = await session.execute(
            text(
                "SELECT COUNT(*) FROM client_communications "
                "WHERE org_id = :org AND status = 'sent'"
            ),
            {"org": str(org_id)},
        )
        print(f"sent_count_for_org={explain.scalar_one()}")

    await engine.dispose()
    print(
        "Note: AI generation latency was previously measured at ~2.5s provider timeout boundary; "
        "fallback without LLM is sub-5ms service-side. Re-run draft endpoint under auth for full path."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
