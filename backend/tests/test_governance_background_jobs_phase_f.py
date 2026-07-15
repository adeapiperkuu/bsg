from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy.dialects import postgresql

from app.agents.governance.routes import governance as governance_routes
from app.agents.governance.schemas.governance import GovernanceAIRecommendationGenerateRequest
from app.agents.governance.services import job_service
from app.agents.governance.services.job_service import (
    JOB_AI_RECOMMENDATION,
    JOB_ANALYTICS_EXPORT,
    JOB_CHARTER,
    JOB_WEEKLY_SUMMARY,
    JobProduct,
    _claim_next_job,
    _execute_product,
    _finish_failure,
    build_job_idempotency_key,
    cancel_governance_job,
    enqueue_governance_job,
    get_governance_job,
    recover_stale_governance_jobs,
    run_governance_job,
    transition_job,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceJob, GovernanceJobStatus
from app.main import app

ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_ORG_ID = UUID("33333333-3333-3333-3333-333333333333")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("44444444-4444-4444-4444-444444444444")
PROJECT_ID = UUID("55555555-5555-5555-5555-555555555555")


def current_user(*, user_id: UUID = USER_ID, org_id: UUID = ORG_ID) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        org_id=org_id,
        email="manager@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


def make_job(
    status: GovernanceJobStatus = GovernanceJobStatus.QUEUED,
    *,
    job_type: str = JOB_WEEKLY_SUMMARY,
    requested_by: UUID = USER_ID,
    org_id: UUID = ORG_ID,
    payload: dict | None = None,
) -> GovernanceJob:
    return GovernanceJob(
        id=uuid4(),
        org_id=org_id,
        project_id=PROJECT_ID if job_type == JOB_CHARTER else None,
        job_type=job_type,
        status=status,
        requested_by=requested_by,
        requested_at=datetime.now(UTC) - timedelta(seconds=2),
        progress_stage=status.value,
        progress_percent=0,
        attempt_count=0,
        max_attempts=3,
        idempotency_key=uuid4().hex,
        request_payload=payload or {},
    )


class Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else [self.value]

    def __iter__(self):
        return iter(self.value if isinstance(self.value, list) else [self.value])


class FakeSession:
    def __init__(self, results: list[Result] | None = None):
        self.results = list(results or [])
        self.statements = []
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else Result()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1

    async def refresh(self, _value):
        return None


def iter_app_api_routes():
    stack = [(route, "") for route in app.routes]
    while stack:
        route, prefix = stack.pop()
        if isinstance(route, APIRoute):
            yield route, f"{prefix}{route.path}"
            continue

        original_router = getattr(route, "original_router", None)
        if original_router is None:
            continue
        include_context = getattr(route, "include_context", None)
        include_prefix = getattr(include_context, "prefix", "") if include_context else ""
        stack.extend((child, f"{prefix}{include_prefix}") for child in original_router.routes)


def test_long_running_routes_return_202() -> None:
    expected = {
        "/api/v1/governance/ai-recommendations/generate",
        "/api/v1/governance/ai-recommendations/{recommendation_id}/regenerate",
        "/api/v1/governance/weekly-summary/generate",
        "/api/v1/governance/project-charters/generate",
        "/api/v1/governance/analytics/exports",
        "/api/v1/governance/analytics/export.csv",
        "/api/v1/governance/analytics/export.pdf",
    }
    routes = {path: route.status_code for route, path in iter_app_api_routes() if path in expected}
    assert routes == {path: 202 for path in expected}


def test_escalation_suggestion_web_surface_is_removed() -> None:
    assert not any(
        path.startswith("/api/v1/governance/escalation-suggestions")
        for _route, path in iter_app_api_routes()
    )
    assert "escalation_suggestion_scan" not in job_service.SUPPORTED_JOB_TYPES


@pytest.mark.asyncio
async def test_start_request_enqueues_without_running_heavy_generation(monkeypatch) -> None:
    queued = make_job(job_type=JOB_AI_RECOMMENDATION)
    enqueue = AsyncMock(return_value=(queued, False))
    heavy = AsyncMock(side_effect=AssertionError("heavy work ran in request"))
    monkeypatch.setattr(governance_routes, "enqueue_governance_job", enqueue)
    monkeypatch.setattr(
        governance_routes, "generate_governance_ai_recommendations", heavy, raising=False
    )

    response = await governance_routes.post_generate_governance_ai_recommendations(
        GovernanceAIRecommendationGenerateRequest(project_id=None, scope="project", force=False),
        FakeSession(),
        current_user(),
        None,
    )
    assert response.data.job_id == queued.id
    assert enqueue.await_count == 1
    heavy.assert_not_awaited()


def test_idempotency_key_is_deterministic_and_database_enforced() -> None:
    first = build_job_idempotency_key(
        job_type=JOB_AI_RECOMMENDATION,
        org_id=ORG_ID,
        project_id=PROJECT_ID,
        requested_by=USER_ID,
        payload={"scope": "project", "force": False, "strategy_version": "v1"},
    )
    second = build_job_idempotency_key(
        job_type=JOB_AI_RECOMMENDATION,
        org_id=ORG_ID,
        project_id=PROJECT_ID,
        requested_by=USER_ID,
        payload={"strategy_version": "v1", "force": False, "scope": "project"},
    )
    assert first == second
    migration = (
        Path(__file__).parents[2]
        / "supabase/migrations/20260715100000_governance_background_jobs_phase_f.sql"
    ).read_text(encoding="utf-8")
    assert "governance_jobs_active_idempotency_uidx" in migration
    assert (
        "WHERE status IN ('queued', 'running', 'retry_scheduled', 'cancellation_requested')"
        in migration
    )


@pytest.mark.asyncio
async def test_duplicate_active_request_returns_existing_job_without_work() -> None:
    existing = make_job()
    session = FakeSession([Result(), Result(existing)])
    returned, deduplicated = await enqueue_governance_job(
        session,
        current_user(),
        job_type=JOB_WEEKLY_SUMMARY,
        org_id=ORG_ID,
        project_id=None,
        payload={"summary_week": "2026-07-13"},
    )
    assert returned is existing
    assert deduplicated is True
    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_claim_uses_skip_locked_and_increments_attempt_once(monkeypatch) -> None:
    monkeypatch.setattr(job_service, "_worker_id", lambda: "worker-a")
    queued = make_job()
    session = FakeSession([Result(queued)])
    claimed = await _claim_next_job(session)
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert claimed is queued
    assert queued.status == GovernanceJobStatus.RUNNING
    assert queued.attempt_count == 1
    # A competing worker receives no unlocked row and therefore cannot execute it.
    assert await _claim_next_job(FakeSession([Result(None)])) is None


def test_service_enforces_valid_transitions() -> None:
    job = make_job()
    transition_job(job, GovernanceJobStatus.RUNNING)
    with pytest.raises(ApiError) as exc:
        transition_job(job, GovernanceJobStatus.QUEUED)
    assert exc.value.code == "INVALID_JOB_TRANSITION"


def test_generation_services_end_read_transactions_before_external_ai() -> None:
    from app.agents.governance.services import (
        charter_service,
        recommendation_service,
        summary_service,
    )

    checks = (
        (summary_service.generate_weekly_governance_summary, "_call_llm_summary"),
        (charter_service.generate_project_charter, "_call_llm_charter"),
        (recommendation_service.generate_governance_ai_recommendations, "_call_llm("),
    )
    for function, external_boundary in checks:
        source = inspect.getsource(function)
        boundary = source.index(external_boundary)
        assert source.rfind("await session.commit()", 0, boundary) >= 0


@pytest.mark.asyncio
async def test_queued_cancellation_is_terminal_at_safe_stage(monkeypatch) -> None:
    job = make_job()
    session = FakeSession()

    async def fake_get(*_args):
        return job

    monkeypatch.setattr(job_service, "get_governance_job", fake_get)
    result = await cancel_governance_job(session, current_user(), job.id)
    assert result.status == GovernanceJobStatus.CANCELLED
    assert result.progress_stage == "cancelled"
    assert session.commit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (httpx.ReadTimeout("timeout"), GovernanceJobStatus.RETRY_SCHEDULED, "AI_TIMEOUT"),
        (
            OSError("storage unavailable"),
            GovernanceJobStatus.RETRY_SCHEDULED,
            "STORAGE_UNAVAILABLE",
        ),
        (
            ApiError(422, "INVALID_INPUT", "Invalid input."),
            GovernanceJobStatus.FAILED,
            "INVALID_INPUT",
        ),
    ],
)
async def test_transient_failures_retry_and_permanent_failures_stop(
    monkeypatch, error, expected_status, expected_code
) -> None:
    job = make_job(GovernanceJobStatus.RUNNING)
    job.attempt_count = 1
    session = FakeSession([Result(job)])
    monkeypatch.setattr(job_service, "AsyncSessionLocal", lambda: session)
    await _finish_failure(job.id, error, perf_counter_value := 0.0)
    assert perf_counter_value == 0.0
    assert job.status == expected_status
    assert job.error_code == expected_code
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_result_returns_before_job_is_marked_success(monkeypatch) -> None:
    product_committed = False
    job = make_job(GovernanceJobStatus.RUNNING)

    async def progress(*_args):
        return True

    async def snapshot(_job_id):
        return job

    async def execute(_job):
        nonlocal product_committed
        product_committed = True
        return JobProduct("test", uuid4(), {})

    async def success(_job_id, _product, _started):
        assert product_committed is True

    monkeypatch.setattr(job_service, "_set_progress", progress)
    monkeypatch.setattr(job_service, "_load_job_snapshot", snapshot)
    monkeypatch.setattr(job_service, "_execute_product", execute)
    monkeypatch.setattr(job_service, "_finish_success", success)
    await run_governance_job(job.id)


@pytest.mark.asyncio
async def test_stale_running_job_is_recovered(monkeypatch) -> None:
    stale = make_job(GovernanceJobStatus.RUNNING)
    stale.attempt_count = 1
    stale.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
    session = FakeSession([Result([stale])])
    monkeypatch.setattr(job_service, "AsyncSessionLocal", lambda: session)
    assert await recover_stale_governance_jobs() == 1
    assert stale.status == GovernanceJobStatus.RETRY_SCHEDULED
    assert stale.error_code == "WORKER_INTERRUPTED"


@pytest.mark.asyncio
async def test_job_uuid_does_not_bypass_requester_or_tenant_visibility() -> None:
    session = FakeSession([Result(None)])
    with pytest.raises(ApiError) as exc:
        await get_governance_job(
            session, current_user(user_id=OTHER_USER_ID, org_id=OTHER_ORG_ID), uuid4()
        )
    assert exc.value.status_code == 404
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "governance_jobs.requested_by" in sql
    assert "governance_jobs.org_id" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_type", "payload", "record_type"),
    [
        (
            JOB_AI_RECOMMENDATION,
            {"scope": "project", "project_id": str(PROJECT_ID)},
            "governance_ai_recommendation",
        ),
        (
            JOB_WEEKLY_SUMMARY,
            {"summary_week": date(2026, 7, 13).isoformat()},
            "governance_weekly_summary",
        ),
        (
            JOB_CHARTER,
            {"project_id": str(PROJECT_ID), "visibility": "internal_only"},
            "project_charter",
        ),
        (JOB_ANALYTICS_EXPORT, {"days": 30, "format": "csv"}, "governance_analytics_export"),
    ],
)
async def test_supported_job_handlers_persist_review_first_products(
    monkeypatch, job_type, payload, record_type
) -> None:
    from app.agents.governance.services import (
        charter_service,
        job_export_service,
        recommendation_service,
        summary_service,
    )

    session = FakeSession()
    monkeypatch.setattr(job_service, "AsyncSessionLocal", lambda: session)

    async def requester(*_args):
        return current_user()

    async def recommendation(*_args, **_kwargs):
        return SimpleNamespace(
            recommendations=[SimpleNamespace(id=uuid4())],
            candidates_persisted=1,
            projects_attempted=1,
            projects_with_recommendations=1,
            fallback_used=False,
        )

    async def summary(*_args, **_kwargs):
        return SimpleNamespace(
            id=uuid4(), summary_week=date(2026, 7, 13), status=SimpleNamespace(value="draft")
        )

    async def charter(*_args, **_kwargs):
        return SimpleNamespace(id=uuid4(), project_id=PROJECT_ID, version="v1")

    async def export(*_args, **_kwargs):
        return JobProduct("governance_analytics_export", None, {"download_url": "/download"})

    monkeypatch.setattr(job_service, "_load_requester", requester)
    monkeypatch.setattr(
        recommendation_service, "generate_governance_ai_recommendations", recommendation
    )
    monkeypatch.setattr(summary_service, "generate_weekly_governance_summary", summary)
    monkeypatch.setattr(charter_service, "generate_project_charter", charter)
    monkeypatch.setattr(job_export_service, "generate_governance_analytics_export", export)

    product = await _execute_product(make_job(job_type=job_type, payload=payload))
    assert product.record_type == record_type
    # All generated records remain drafts/suggestions; handlers perform no approval/conversion.
    assert "approved" not in product.data
    assert "converted" not in product.data
