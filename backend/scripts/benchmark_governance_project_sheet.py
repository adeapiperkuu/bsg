"""Benchmark Phase E's composite project sheet against the previous request fan-out.

The backend runs locally without Docker and connects to the configured remote Supabase
database. Results are development measurements, not production latency claims.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import statistics
import sys
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.agents.governance.schemas.governance import ProjectScopeStateRead  # noqa: E402
from app.agents.governance.services.governance_service import (  # noqa: E402
    list_governance_actions_page,
    list_governance_dependencies_page,
    list_governance_escalations_page,
    list_governance_scope_states_page,
    map_action_list_row,
    map_dependency_list_row,
    map_escalation_list_row,
)
from app.agents.governance.services.project_sheet_service import (  # noqa: E402
    get_governance_project_sheet,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import (  # noqa: E402
    AppRole,
    Project,
    ProjectAssignment,
    RiskAlert,
    User,
)
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.scoping import get_visible_project  # noqa: E402

ORG_ID = UUID("0ac27787-896c-49e4-b90a-616c13a3694e")
INTERNAL_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
RUNS = 5
LIMIT = 6


@dataclass
class Sample:
    elapsed_ms: float
    http_requests: int
    executes: int
    response_bytes: int
    gzip_bytes: int
    serialization_ms: float


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _internal_user() -> CurrentUser:
    return CurrentUser(
        id=INTERNAL_USER_ID,
        org_id=ORG_ID,
        email="phase-e-internal@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def _internal_project() -> UUID:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(Project.id)
                .where(Project.org_id == ORG_ID, Project.deleted_at.is_(None))
                .order_by(Project.name)
                .limit(1)
            )
        ).scalar_one()


async def _assigned_client() -> tuple[CurrentUser, UUID] | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(User, ProjectAssignment.project_id)
                .join(ProjectAssignment, ProjectAssignment.user_id == User.id)
                .join(Project, Project.id == ProjectAssignment.project_id)
                .where(
                    User.role == AppRole.CLIENT,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    ProjectAssignment.is_active.is_(True),
                    ProjectAssignment.deleted_at.is_(None),
                    Project.deleted_at.is_(None),
                )
                .limit(1)
            )
        ).one_or_none()
    if row is None:
        return None
    user, project_id = row
    return (
        CurrentUser(
            id=user.id,
            org_id=user.org_id,
            email=user.email,
            role=AppRole.CLIENT,
            is_active=True,
        ),
        project_id,
    )


async def _old_internal(user: CurrentUser, project_id: UUID) -> Sample:
    started = perf_counter()
    fragments: dict[str, object] = {}
    executes = 0

    async with AsyncSessionLocal() as session:
        page = await list_governance_dependencies_page(
            session, user, limit=LIMIT, offset=0, project_id=project_id
        )
        fragments["dependencies"] = [
            map_dependency_list_row(row).model_dump() for row in page.items
        ]
        executes += page.db_executes
    async with AsyncSessionLocal() as session:
        page = await list_governance_actions_page(
            session, user, limit=LIMIT, offset=0, project_id=project_id
        )
        fragments["actions"] = [map_action_list_row(row).model_dump() for row in page.items]
        executes += page.db_executes
    async with AsyncSessionLocal() as session:
        page = await list_governance_escalations_page(
            session, user, limit=LIMIT, offset=0, project_id=project_id
        )
        fragments["escalations"] = [map_escalation_list_row(row).model_dump() for row in page.items]
        executes += page.db_executes
    async with AsyncSessionLocal() as session:
        page = await list_governance_scope_states_page(
            session, user, limit=1, offset=0, project_id=project_id
        )
        fragments["scope"] = [
            ProjectScopeStateRead.model_validate(row[0], from_attributes=True).model_dump()
            for row in page.items
        ]
        executes += page.db_executes
    async with AsyncSessionLocal() as session:
        project = await get_visible_project(session, project_id, user)
        risks = (
            (
                await session.execute(
                    select(RiskAlert)
                    .where(RiskAlert.project_id == project.id, RiskAlert.deleted_at.is_(None))
                    .order_by(RiskAlert.created_at.desc())
                    .limit(LIMIT)
                )
            )
            .scalars()
            .all()
        )
        fragments["delivery_risks"] = [risk.id for risk in risks]
        executes += 2

    serialization_started = perf_counter()
    payload = json.dumps(fragments, default=str, separators=(",", ":")).encode()
    serialization_ms = (perf_counter() - serialization_started) * 1000
    return Sample(
        elapsed_ms=(perf_counter() - started) * 1000,
        http_requests=5,
        executes=executes,
        response_bytes=len(payload),
        gzip_bytes=len(gzip.compress(payload)),
        serialization_ms=serialization_ms,
    )


async def _old_client(user: CurrentUser, project_id: UUID) -> Sample:
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        page = await list_governance_escalations_page(
            session, user, limit=LIMIT, offset=0, project_id=project_id
        )
        items = [map_escalation_list_row(row, for_client=True).model_dump() for row in page.items]
    serialization_started = perf_counter()
    payload = json.dumps(items, default=str, separators=(",", ":")).encode()
    serialization_ms = (perf_counter() - serialization_started) * 1000
    return Sample(
        elapsed_ms=(perf_counter() - started) * 1000,
        http_requests=1,
        executes=page.db_executes,
        response_bytes=len(payload),
        gzip_bytes=len(gzip.compress(payload)),
        serialization_ms=serialization_ms,
    )


async def _composite(user: CurrentUser, project_id: UUID) -> Sample:
    started = perf_counter()
    async with AsyncSessionLocal() as session:
        result = await get_governance_project_sheet(session, user, project_id=project_id)
    serialization_started = perf_counter()
    payload = result.model_dump_json().encode()
    serialization_ms = (perf_counter() - serialization_started) * 1000
    return Sample(
        elapsed_ms=(perf_counter() - started) * 1000,
        http_requests=1,
        executes=1,
        response_bytes=len(payload),
        gzip_bytes=len(gzip.compress(payload)),
        serialization_ms=serialization_ms,
    )


def _print(label: str, samples: list[Sample]) -> None:
    values = [sample.elapsed_ms for sample in samples]
    print(
        f"{label}: n={len(samples)} http={samples[0].http_requests} "
        f"executes={samples[0].executes} p50={statistics.median(values):.1f}ms "
        f"p95={_percentile(values, 0.95):.1f}ms "
        f"bytes={statistics.median(sample.response_bytes for sample in samples):.0f} "
        f"gzip_bytes={statistics.median(sample.gzip_bytes for sample in samples):.0f} "
        f"serialization={statistics.mean(sample.serialization_ms for sample in samples):.2f}ms"
    )


async def main() -> None:
    internal = _internal_user()
    project_id = await _internal_project()
    async with AsyncSessionLocal() as session:
        await session.execute(select(1))

    print("Local backend; remote Supabase database; warm connection pool; no Docker")
    _print("Internal before", [await _old_internal(internal, project_id) for _ in range(RUNS)])
    _print("Internal after", [await _composite(internal, project_id) for _ in range(RUNS)])

    client = await _assigned_client()
    if client is None:
        print("Client benchmark: unsupported (no active client assignment in configured dataset)")
        return
    client_user, client_project_id = client
    _print(
        "Client before",
        [await _old_client(client_user, client_project_id) for _ in range(RUNS)],
    )
    _print(
        "Client after",
        [await _composite(client_user, client_project_id) for _ in range(RUNS)],
    )


if __name__ == "__main__":
    asyncio.run(main())
