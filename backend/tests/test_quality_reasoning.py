"""Tests for the LLM reasoning pipeline (docs/agents/quality_reasoning_upgrade_plan.md).

Covers: evidence-pack anonymization, citation/confidence validation, the
deterministic/LLM/shadow engine selection in reason_root_cause, and the
fingerprint-based cache short-circuit that avoids redundant LLM calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.quality_intelligence.citations import validate_reasoning
from app.agents.quality_intelligence.evidence_pack import EvidenceItem, EvidencePack, build_evidence_pack
from app.agents.quality_intelligence.reasoning import _fingerprint_signals, reason_root_cause
from app.agents.quality_intelligence.root_cause import RootCauseResult, Signal, extract_signals
from app.db.models import AppRole
from app.schemas.domain import LLMFactor, LLMRootCause, RecommendedAction


def _empty_pack(**overrides) -> EvidencePack:
    defaults: dict = dict(
        project_id=uuid4(),
        team_id=uuid4(),
        role=AppRole.DELIVERY_MANAGER,
        snapshot_timeline=[],
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
        key_index={},
    )
    defaults.update(overrides)
    return EvidencePack(**defaults)


class _NestedCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return iter(self._rows)


class _FakeSession:
    """Minimal async-session stand-in supporting execute() and begin_nested(),
    used instead of AsyncMock because query_optional_table's `async with
    session.begin_nested()` needs a real async context manager."""

    def __init__(self, rows: list | None = None) -> None:
        self._rows = rows or []

    async def execute(self, *_a, **_k):
        return _FakeResult(self._rows)

    def begin_nested(self):
        return _NestedCtx()


# --- Evidence pack anonymization -------------------------------------------------


def test_evidence_item_prompt_dict_has_no_pii_fields():
    item = EvidenceItem(
        key="R1",
        source_table="reviewer_scorecards",
        source_row_id=uuid4(),
        summary="R1: 78% accuracy",
        data={"accuracy_pct": 78.0, "items_evaluated": 60},
    )
    prompt_dict = item.to_prompt_dict()
    assert "annotator_id" not in prompt_dict
    assert "full_name" not in prompt_dict
    assert prompt_dict["key"] == "R1"


@pytest.mark.asyncio
async def test_build_evidence_pack_excludes_reviewer_detail_for_client() -> None:
    snapshot = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        team_id=uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        evaluated_item_count=40,
    )
    session = _FakeSession(rows=[])

    with patch("app.agents.quality_intelligence.evidence_pack.OKAClient") as mock_oka:
        mock_oka.return_value.retrieve_lessons = AsyncMock(return_value=[])
        pack = await build_evidence_pack(session, snapshot, role=AppRole.CLIENT)

    assert pack.reviewer_scorecards == []
    assert pack.eval_log_rollup == {}
    assert pack.onboarding_events == []


@pytest.mark.asyncio
async def test_build_evidence_pack_includes_reviewer_detail_for_delivery_manager() -> None:
    snapshot = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        team_id=uuid4(),
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        evaluated_item_count=40,
    )
    session = _FakeSession(rows=[])

    with patch("app.agents.quality_intelligence.evidence_pack.OKAClient") as mock_oka:
        mock_oka.return_value.retrieve_lessons = AsyncMock(return_value=[])
        pack = await build_evidence_pack(session, snapshot, role=AppRole.DELIVERY_MANAGER)

    # No rows returned by the fake session, but the sections are not
    # unconditionally suppressed the way they are for CLIENT.
    assert pack.role == AppRole.DELIVERY_MANAGER


# --- Citation / confidence validation --------------------------------------------


def test_validate_reasoning_drops_ungrounded_keys_and_renormalizes() -> None:
    pack = _empty_pack(
        reviewer_scorecards=[
            EvidenceItem(key="R1", source_table="reviewer_scorecards", source_row_id=uuid4(), summary="R1", data={})
        ],
    )
    pack.key_index["R1"] = pack.reviewer_scorecards[0]

    llm_out = LLMRootCause(
        primary_driver="onboarding_gap",
        factors=[
            LLMFactor(factor="onboarding_gap", contribution_pct=70, evidence_keys=["R1", "GHOST"], reasoning="x"),
            LLMFactor(factor="sop_change", contribution_pct=50, evidence_keys=[], reasoning="y"),
        ],
        confidence="high",
        recommended_actions=[],
    )
    ok, cleaned, reasons = validate_reasoning(llm_out, pack)

    assert ok is True
    assert cleaned.factors[0].evidence_keys == ["R1"]
    assert 99.0 <= sum(f.contribution_pct for f in cleaned.factors) <= 101.0
    assert any("Renormalized" in r for r in reasons)


def test_validate_reasoning_rejects_when_primary_factor_loses_all_citations() -> None:
    pack = _empty_pack()
    llm_out = LLMRootCause(
        primary_driver="onboarding_gap",
        factors=[LLMFactor(factor="onboarding_gap", contribution_pct=100, evidence_keys=["GHOST"], reasoning="x")],
        confidence="high",
        recommended_actions=[],
    )
    ok, _cleaned, reasons = validate_reasoning(llm_out, pack)
    assert ok is False
    assert any("no evidence present" in r for r in reasons)


def test_validate_reasoning_downgrades_high_confidence_without_majority_factor() -> None:
    pack = _empty_pack(
        reviewer_scorecards=[
            EvidenceItem(key="R1", source_table="reviewer_scorecards", source_row_id=uuid4(), summary="R1", data={})
        ],
    )
    pack.key_index["R1"] = pack.reviewer_scorecards[0]
    llm_out = LLMRootCause(
        primary_driver="onboarding_gap",
        factors=[
            LLMFactor(factor="onboarding_gap", contribution_pct=40, evidence_keys=["R1"], reasoning="x"),
            LLMFactor(factor="sop_change", contribution_pct=60, evidence_keys=[], reasoning="y"),
        ],
        confidence="high",
        recommended_actions=[],
    )
    ok, cleaned, reasons = validate_reasoning(llm_out, pack)
    assert ok is True
    assert cleaned.confidence == "medium"
    assert any("Downgraded confidence" in r for r in reasons)


def test_validate_reasoning_rejects_primary_driver_contradicting_unobserved_signal() -> None:
    """Regression: the LLM claimed 'workload_fatigue' as primary driver (60%)
    using a 7-day throughput BELOW the recent average as "evidence" — the
    hypothesis is defined as sustained OVER-utilization, so a below-average
    reading is not just weak evidence, it's the wrong direction entirely. The
    deterministic pre-pass correctly marks this not observed; validation must
    reject a primary_driver that contradicts it rather than let the LLM
    override the pre-pass silently."""
    pack = _empty_pack()
    signals = [
        Signal(
            hypothesis="workload_fatigue",
            observed=False,
            strength="weak",
            facts=["7-day units 380 vs 4-week avg 391 — no sustained spike"],
            evidence_keys=["THROUGHPUT-2026-06-17"],
        ),
    ]
    llm_out = LLMRootCause(
        primary_driver="workload_fatigue",
        factors=[
            LLMFactor(
                factor="workload_fatigue",
                contribution_pct=60,
                evidence_keys=["THROUGHPUT-2026-06-17"],
                reasoning="Throughput below average suggests reviewer fatigue",
            ),
        ],
        confidence="low",
        recommended_actions=[],
    )
    ok, _cleaned, reasons = validate_reasoning(llm_out, pack, signals)
    assert ok is False
    assert any("contradicts the deterministic pre-pass" in r for r in reasons)


def test_validate_reasoning_accepts_primary_driver_matching_observed_signal() -> None:
    pack = _empty_pack(
        reviewer_scorecards=[
            EvidenceItem(key="R1", source_table="reviewer_scorecards", source_row_id=uuid4(), summary="R1", data={})
        ],
    )
    pack.key_index["R1"] = pack.reviewer_scorecards[0]
    signals = [
        Signal(
            hypothesis="onboarding_gap",
            observed=True,
            strength="strong",
            facts=["R1: 78% accuracy over 60 items"],
            evidence_keys=["R1"],
        ),
    ]
    llm_out = LLMRootCause(
        primary_driver="onboarding_gap",
        factors=[LLMFactor(factor="onboarding_gap", contribution_pct=100, evidence_keys=["R1"], reasoning="x")],
        confidence="medium",
        recommended_actions=[],
    )
    ok, cleaned, _reasons = validate_reasoning(llm_out, pack, signals)
    assert ok is True
    assert cleaned.primary_driver == "onboarding_gap"


def test_validate_reasoning_rejects_raw_pii_field_reference() -> None:
    pack = _empty_pack()
    llm_out = LLMRootCause(
        primary_driver="onboarding_gap",
        factors=[
            LLMFactor(
                factor="onboarding_gap",
                contribution_pct=100,
                evidence_keys=[],
                reasoning="annotator_id abc123 is the cause",
            )
        ],
        confidence="low",
        recommended_actions=[],
    )
    ok, _cleaned, reasons = validate_reasoning(llm_out, pack)
    assert ok is False
    assert any("PII" in r for r in reasons)


def test_recommended_action_evidence_basis_must_be_traceable() -> None:
    pack = _empty_pack(oka_lessons=[{"title": "Lesson 1487"}])
    llm_out = LLMRootCause(
        primary_driver="undetermined",
        factors=[LLMFactor(factor="undetermined", contribution_pct=100, evidence_keys=[], reasoning="x")],
        confidence="low",
        recommended_actions=[
            RecommendedAction(
                rank=1,
                action="Do something",
                target="QA Lead",
                expected_outcome="Better",
                estimated_effort="1h",
                evidence_basis="A completely unrelated made-up reference",
                priority="this_week",
            )
        ],
    )
    ok, _cleaned, reasons = validate_reasoning(llm_out, pack)
    assert ok is True  # not fatal, but flagged
    assert any("not traceable to pack" in r for r in reasons)


# --- reason_root_cause engine selection ------------------------------------------


def _snapshot_for(pack: EvidencePack, *, evaluated_item_count: int = 40, root_cause: dict | None = None):
    return SimpleNamespace(
        id=uuid4(),
        project_id=pack.project_id,
        team_id=pack.team_id,
        org_id=uuid4(),
        iso_year=2026,
        iso_week=25,
        evaluated_item_count=evaluated_item_count,
        root_cause=root_cause,
    )


@pytest.mark.asyncio
async def test_reason_root_cause_blocks_on_insufficient_sample() -> None:
    pack = _empty_pack()
    signals = extract_signals(pack)
    snapshot = _snapshot_for(pack, evaluated_item_count=10)

    result = await reason_root_cause(AsyncMock(), snapshot, pack, signals)
    assert result.blocked is True
    assert result.primary_driver is None


@pytest.mark.asyncio
async def test_reason_root_cause_uses_deterministic_when_flag_off() -> None:
    pack = _empty_pack()
    signals = extract_signals(pack)
    snapshot = _snapshot_for(pack)

    async def _fake_deterministic(_session, _snap):
        return RootCauseResult(primary_driver="undetermined", factors=[], confidence="low", recommended_actions=[])

    with (
        patch("app.agents.quality_intelligence.reasoning.get_settings") as mock_settings,
        patch(
            "app.agents.quality_intelligence.reasoning.analyze_root_cause_deterministic",
            AsyncMock(side_effect=_fake_deterministic),
        ),
    ):
        mock_settings.return_value.quality_llm_reasoning = False
        mock_settings.return_value.quality_llm_reasoning_shadow = False
        mock_settings.return_value.openai_api_key = None
        mock_settings.return_value.llm_api_key = None

        result = await reason_root_cause(AsyncMock(), snapshot, pack, signals)

    assert result.engine == "deterministic"
    assert result.reasoning_trace["_signal_fingerprint"] == _fingerprint_signals(signals)


@pytest.mark.asyncio
async def test_reason_root_cause_uses_llm_when_enabled_and_valid() -> None:
    gold_new = EvidenceItem(
        key="GOLDSET-v2",
        source_table="gold_set_metadata",
        source_row_id=uuid4(),
        summary="v2",
        data={"version": "v2", "last_updated": "2026-06-20"},
    )
    gold_old = EvidenceItem(
        key="GOLDSET-v1",
        source_table="gold_set_metadata",
        source_row_id=uuid4(),
        summary="v1",
        data={"version": "v1", "last_updated": "2026-05-01"},
    )
    pack = _empty_pack(gold_set_versions=[gold_new, gold_old])
    pack.key_index["GOLDSET-v2"] = gold_new
    pack.key_index["GOLDSET-v1"] = gold_old
    signals = extract_signals(pack)
    snapshot = _snapshot_for(pack)

    llm_json = json.dumps(
        {
            "primary_driver": "gold_set_version_change",
            "factors": [
                {
                    "factor": "gold_set_version_change",
                    "contribution_pct": 90,
                    "evidence_keys": ["GOLDSET-v2"],
                    "reasoning": "Version changed the same week accuracy dropped — not a reviewer issue (BR-10)",
                }
            ],
            "confidence": "high",
            "competing_hypotheses_ruled_out": ["onboarding_gap: no low-accuracy reviewers present"],
            "novel_findings": [],
            "recommended_actions": [
                {
                    "rank": 1,
                    "action": "Re-baseline accuracy expectations against the new gold set",
                    "target": "QA Lead",
                    "expected_outcome": "Stabilised accuracy within 2 weeks",
                    "estimated_effort": "2 hours",
                    "evidence_basis": "GOLDSET-v2",
                    "priority": "this_week",
                }
            ],
            "data_gaps": [],
        }
    )

    with (
        patch("app.agents.quality_intelligence.reasoning.get_settings") as mock_settings,
        patch("app.services.llm.client.LLMClient.generate_structured", AsyncMock(return_value=llm_json)),
    ):
        mock_settings.return_value.quality_llm_reasoning = True
        mock_settings.return_value.quality_llm_reasoning_shadow = False
        mock_settings.return_value.openai_api_key = "test-key"
        mock_settings.return_value.llm_api_key = None
        mock_settings.return_value.quality_reasoning_model = "gpt-test"
        mock_settings.return_value.openai_model = "gpt-test"
        mock_settings.return_value.llm_model = "gpt-test"

        result = await reason_root_cause(AsyncMock(), snapshot, pack, signals)

    # This is the §13 confounder case: a gold-set version change must win
    # over a naive reviewer-calibration read, and the recommended action
    # must not be a calibration session.
    assert result.engine == "llm"
    assert result.primary_driver == "gold_set_version_change"
    assert result.confidence == "high"
    assert "calibration" not in result.recommended_actions[0]["action"].lower()


@pytest.mark.asyncio
async def test_reason_root_cause_falls_back_when_llm_raises() -> None:
    pack = _empty_pack()
    signals = extract_signals(pack)
    snapshot = _snapshot_for(pack)

    async def _fake_deterministic(_session, _snap):
        return RootCauseResult(primary_driver="undetermined", factors=[], confidence="low", recommended_actions=[])

    with (
        patch("app.agents.quality_intelligence.reasoning.get_settings") as mock_settings,
        patch(
            "app.services.llm.client.LLMClient.generate_structured",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "app.agents.quality_intelligence.reasoning.analyze_root_cause_deterministic",
            AsyncMock(side_effect=_fake_deterministic),
        ),
    ):
        mock_settings.return_value.quality_llm_reasoning = True
        mock_settings.return_value.quality_llm_reasoning_shadow = False
        mock_settings.return_value.openai_api_key = "test-key"
        mock_settings.return_value.llm_api_key = None
        mock_settings.return_value.quality_reasoning_model = "gpt-test"
        mock_settings.return_value.openai_model = "gpt-test"
        mock_settings.return_value.llm_model = "gpt-test"

        result = await reason_root_cause(AsyncMock(), snapshot, pack, signals)

    assert result.engine == "deterministic_fallback"
    assert "fallback_reasons" in (result.reasoning_trace or {})


@pytest.mark.asyncio
async def test_reason_root_cause_returns_cached_result_when_fingerprint_matches() -> None:
    pack = _empty_pack()
    signals = extract_signals(pack)
    fingerprint = _fingerprint_signals(signals)

    cached_json = {
        "primary_driver": "onboarding_gap",
        "factors": [],
        "confidence": "medium",
        "recommended_actions": [],
        "blocked": False,
        "block_reason": None,
        "engine": "llm",
        "novel_findings": [],
        "reasoning_trace": {"_signal_fingerprint": fingerprint, "model_used": "gpt-test"},
    }
    snapshot = _snapshot_for(pack, root_cause=cached_json)

    with patch(
        "app.services.llm.client.LLMClient.generate_structured",
        AsyncMock(side_effect=AssertionError("must not call the LLM when the cache is fresh")),
    ):
        result = await reason_root_cause(AsyncMock(), snapshot, pack, signals)

    assert result.primary_driver == "onboarding_gap"
    assert result.engine == "llm"
