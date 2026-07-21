"""PHASE 2B prod-hardening tests for answer_quality_query() (query_handler.py).

NOTE: the primary Phase 2B deliverable — merging the root-cause reasoning LLM
call with the final-answer synthesis call into a single OpenAI round trip —
was implemented and measured live against the running dev server, then
REVERTED after live measurement showed it made agent-query p50 *worse*, not
better (see the Phase 2B report / reasoning.py's module docstring for the
before/after numbers and root cause). The two-call flow in query_handler.py
is therefore intentionally unchanged from before Phase 2B.

What Phase 2B did keep (tested here): OKA is fetched exactly once per query
and reused everywhere it's needed (previously called a second, redundant
time for "historical" intent queries), and intent-classification LLM calls
(when llm_intent_routing is enabled) run concurrently with the first
session-bound DB evidence fetch instead of serially in front of it.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.drift import DriftResult
from app.agents.quality_intelligence.evidence_pack import EvidenceItem, EvidencePack
from app.agents.quality_intelligence.root_cause import RootCauseResult
from app.db.models import AppRole, RiskTier
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput


def _pack(project_id, team_id) -> EvidencePack:
    snap_item = EvidenceItem(
        key="SNAP-2026W25",
        source_table="quality_snapshots",
        source_row_id=uuid4(),
        summary="W25 snapshot",
        data={},
    )
    return EvidencePack(
        project_id=project_id,
        team_id=team_id,
        role=AppRole.DELIVERY_MANAGER,
        snapshot_timeline=[snap_item],
        error_taxonomy_trend={},
        reviewer_scorecards=[],
        eval_log_rollup={},
        iaa_records=[],
        sop_timeline=[],
        gold_set_versions=[],
        throughput_timeline=[],
        onboarding_events=[],
        open_alerts=[],
        oka_lessons=[],
        key_index={"SNAP-2026W25": snap_item},
    )


def _make_snapshot(project_id):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        team_id=uuid4(),
        org_id=project_id,
        iso_year=2026,
        iso_week=25,
        evaluated_item_count=40,
        gold_set_accuracy_pct=91.0,
        rework_rate_pct=5.0,
        iaa_krippendorff_alpha=0.82,
        root_cause=None,
    )


class _EmptyScalarsResult:
    def scalars(self):
        return []


@pytest.mark.asyncio
async def test_historical_intent_calls_oka_exactly_once() -> None:
    """PHASE 2B OKA dedupe: before this change, a "historical" intent query
    called OKAClient.retrieve_lessons twice — once inside
    _build_historical_context and once more via the unconditional top-level
    lookup, with identical arguments. It must now be fetched exactly once
    per query and reused by both."""
    from app.agents.quality_intelligence.query_handler import answer_quality_query

    project_id = uuid4()
    user = SimpleNamespace(id=uuid4(), org_id=uuid4(), role=AppRole.DELIVERY_MANAGER)
    project = SimpleNamespace(id=project_id, org_id=user.org_id, name="P")
    snapshot = _make_snapshot(project_id)
    pack = _pack(project_id, snapshot.team_id)
    payload = AgentQueryCreate(
        agent_name="quality_intelligence_agent",
        project_id=project_id,
        query_text="How was the accuracy issue resolved last time?",
    )
    drift = DriftResult(has_drift=False, severity=RiskTier.LOW, detail=None)
    root_cause = RootCauseResult(
        primary_driver="undetermined", factors=[], confidence="low", recommended_actions=[], engine="deterministic",
    )

    session = AsyncMock()
    session.add = lambda *a: None
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=_EmptyScalarsResult())

    with (
        patch("app.agents.quality_intelligence.query_handler.get_visible_project", AsyncMock(return_value=project)),
        patch("app.agents.quality_intelligence.query_handler._fetch_latest_snapshot", AsyncMock(return_value=snapshot)),
        patch("app.agents.quality_intelligence.query_handler.build_evidence_pack", AsyncMock(return_value=pack)),
        patch("app.agents.quality_intelligence.query_handler.evaluate_drift", AsyncMock(return_value=drift)),
        patch("app.agents.quality_intelligence.query_handler.fetch_prior_snapshot", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.query_handler.classify_intent_llm", AsyncMock(return_value=None)),
        patch("app.agents.quality_intelligence.query_handler.reason_root_cause", AsyncMock(return_value=root_cause)),
        patch("app.agents.quality_intelligence.query_handler.OKAClient") as mock_oka_cls,
        patch(
            "app.services.llm.client.LLMClient.generate_structured",
            AsyncMock(return_value="Here is what happened last time."),
        ),
    ):
        mock_oka_cls.return_value.retrieve_lessons = AsyncMock(return_value=[{"title": "Lesson X"}])
        query = await answer_quality_query(session, user, payload)

    assert mock_oka_cls.return_value.retrieve_lessons.await_count == 1
    assert query.answer_text


@pytest.mark.asyncio
async def test_intent_llm_classification_overlaps_db_evidence_fetch() -> None:
    """PHASE 2B prod-hardening: when llm_intent_routing is enabled,
    classify_intent_llm() must run concurrently with the first session-bound
    evidence fetch (_fetch_latest_snapshot), not serially in front of it —
    classify_intent_llm never touches `session`, so there's no single-session
    concurrency hazard in overlapping the two. No-op for dev perf (the flag
    is off by default there) but prevents a serial regression in prod."""
    from app.agents.quality_intelligence.query_handler import answer_quality_query

    project_id = uuid4()
    user = SimpleNamespace(id=uuid4(), org_id=uuid4(), role=AppRole.DELIVERY_MANAGER)
    project = SimpleNamespace(id=project_id, org_id=user.org_id, name="P")
    payload = AgentQueryCreate(
        agent_name="quality_intelligence_agent",
        project_id=project_id,
        query_text="What is the quality status?",
    )

    delay = 0.15

    async def _slow_classify_intent_llm(_query_text: str) -> str | None:
        await asyncio.sleep(delay)
        return "status"

    async def _slow_fetch_latest_snapshot(_session, _project_id):
        await asyncio.sleep(delay)
        return None  # no-snapshot fallback path — simplest to mock end-to-end

    async def _fake_fallback_evidence(*_a, **_k):
        return [
            EvidenceInput(source_table="risk_alerts", source_row_id=uuid4(), description="alert"),
        ], {"note": "No quality snapshots available for this project."}

    session = AsyncMock()
    session.add = lambda *a: None
    session.flush = AsyncMock()

    with (
        patch("app.agents.quality_intelligence.query_handler.get_visible_project", AsyncMock(return_value=project)),
        patch("app.agents.quality_intelligence.query_handler.classify_intent_llm", _slow_classify_intent_llm),
        patch("app.agents.quality_intelligence.query_handler._fetch_latest_snapshot", _slow_fetch_latest_snapshot),
        patch(
            "app.agents.quality_intelligence.query_handler._fallback_evidence_no_snapshot",
            AsyncMock(side_effect=_fake_fallback_evidence),
        ),
        patch("app.agents.quality_intelligence.query_handler.OKAClient") as mock_oka_cls,
        patch(
            "app.services.llm.client.LLMClient.generate_structured",
            AsyncMock(return_value="Status answer."),
        ),
    ):
        mock_oka_cls.return_value.retrieve_lessons = AsyncMock(return_value=[])
        started = time.perf_counter()
        query = await answer_quality_query(session, user, payload)
        elapsed = time.perf_counter() - started

    # Serial would take ~2*delay; concurrent takes ~delay. Use 1.5*delay as a
    # generous cutoff to absorb scheduling jitter without weakening the
    # assertion that they overlapped rather than ran back-to-back.
    assert elapsed < delay * 1.5, f"expected concurrent overlap (~{delay}s), took {elapsed:.3f}s"
    assert query.answer_text
