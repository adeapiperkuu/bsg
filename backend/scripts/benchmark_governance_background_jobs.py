"""Measure Phase F request acceptance separately from simulated worker processing.

This is a local architecture harness. It excludes HTTP transport and database latency and mocks the
external provider with a fixed delay, so results are not production latency claims.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from time import perf_counter
from uuid import UUID, uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.governance.routes import governance as routes  # noqa: E402
from app.agents.governance.schemas.governance import (  # noqa: E402
    GovernanceAIRecommendationGenerateRequest,
)
from app.agents.governance.services import job_service  # noqa: E402
from app.agents.governance.services.job_service import (  # noqa: E402
    JOB_AI_RECOMMENDATION,
    JobProduct,
    run_governance_job,
)
from app.core.security import CurrentUser  # noqa: E402
from app.db.models import AppRole, GovernanceJob, GovernanceJobStatus  # noqa: E402

RUNS = 20
PROVIDER_DELAY_SECONDS = 0.05
ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def print_result(label: str, values: list[float]) -> None:
    print(
        f"{label}: n={len(values)} p50={statistics.median(values):.3f}ms "
        f"p95={percentile(values, 0.95):.3f}ms"
    )


async def main() -> None:
    user = CurrentUser(
        id=USER_ID,
        org_id=ORG_ID,
        email="phase-f@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )
    queued = GovernanceJob(
        id=uuid4(),
        org_id=ORG_ID,
        project_id=None,
        job_type=JOB_AI_RECOMMENDATION,
        status=GovernanceJobStatus.QUEUED,
        requested_by=USER_ID,
        progress_stage="queued",
        progress_percent=0,
        attempt_count=0,
        max_attempts=3,
        idempotency_key=uuid4().hex,
        request_payload={},
    )

    async def enqueue(*_args, **_kwargs):
        return queued, False

    original_enqueue = routes.enqueue_governance_job
    routes.enqueue_governance_job = enqueue
    acceptance: list[float] = []
    try:
        for _ in range(RUNS):
            started = perf_counter()
            await routes.post_generate_governance_ai_recommendations(
                GovernanceAIRecommendationGenerateRequest(scope="project"),
                object(),
                user,
                None,
            )
            acceptance.append((perf_counter() - started) * 1000)
    finally:
        routes.enqueue_governance_job = original_enqueue

    async def progress(*_args):
        return True

    async def snapshot(_job_id):
        queued.status = GovernanceJobStatus.RUNNING
        return queued

    async def product(_job):
        await asyncio.sleep(PROVIDER_DELAY_SECONDS)
        return JobProduct("mock_result", uuid4(), {})

    async def success(*_args):
        return None

    original_progress = job_service._set_progress
    original_snapshot = job_service._load_job_snapshot
    original_product = job_service._execute_product
    original_success = job_service._finish_success
    job_service._set_progress = progress
    job_service._load_job_snapshot = snapshot
    job_service._execute_product = product
    job_service._finish_success = success
    processing: list[float] = []
    synchronous: list[float] = []
    try:
        for _ in range(RUNS):
            started = perf_counter()
            await run_governance_job(queued.id)
            processing.append((perf_counter() - started) * 1000)
        for _ in range(RUNS):
            started = perf_counter()
            await asyncio.sleep(PROVIDER_DELAY_SECONDS)
            synchronous.append((perf_counter() - started) * 1000)
    finally:
        job_service._set_progress = original_progress
        job_service._load_job_snapshot = original_snapshot
        job_service._execute_product = original_product
        job_service._finish_success = original_success

    print("Local in-process harness; DB/HTTP excluded; external provider delay mocked at 50ms")
    print_result("202 acceptance path", acceptance)
    print_result("Background processing", processing)
    print_result("Previous synchronous wait", synchronous)


if __name__ == "__main__":
    asyncio.run(main())
