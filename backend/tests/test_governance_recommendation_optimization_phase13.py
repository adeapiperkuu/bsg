"""Phase 13 — controlled recommendation optimization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.governance.services.effectiveness_metrics import is_resolved
from app.agents.governance.services.learning_rules_engine import (
    ALLOWED_RULE_EFFECTS,
    RecommendationCandidateView,
    apply_learning_rule,
    compare_rankings,
    validate_rule_payload,
)
from app.agents.governance.services.optimization_service import (
    OPTIMIZATION_ROLES,
    _metric_snapshot,
    assert_can_manage_optimization,
)
from app.db.models import (
    AppRole,
    GovernanceAIRecommendationStatus,
    GovernanceFalsePositiveStatus,
    GovernanceRecommendationAcceptanceStatus,
)


def _candidate(**overrides):
    base = {
        "id": str(uuid4()),
        "title": "Rec",
        "confidence": 0.7,
        "priority": "high",
        "trigger_type": "dependency_overdue",
        "fingerprint": "fp-1",
        "evidence_count": 2,
        "ranking_score": 70.0,
    }
    base.update(overrides)
    return RecommendationCandidateView(**base)


def _rec(**overrides):
    base = {
        "id": uuid4(),
        "confidence": 0.8,
        "status": GovernanceAIRecommendationStatus.ACTIVE,
        "acceptance_status": GovernanceRecommendationAcceptanceStatus.NOT_ACCEPTED,
        "accepted_at": None,
        "dismissed_at": None,
        "converted_action_id": None,
        "converted_escalation_id": None,
        "resolved_at": None,
        "reopened_at": None,
        "false_positive_status": None,
        "quality_score": 72.0,
        "recurrence_after_acceptance_count": 0,
        "recurrence_after_dismissal_count": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_allowed_rule_effects_are_bounded():
    assert "ranking" in ALLOWED_RULE_EFFECTS
    assert "auto_accept" not in ALLOWED_RULE_EFFECTS
    assert "create_escalation" not in ALLOWED_RULE_EFFECTS


def test_validate_rule_payload_rejects_forbidden_keys():
    errors = validate_rule_payload("ranking", {"auto_accept": True, "boost": 1})
    assert any("forbidden" in e for e in errors)
    assert validate_rule_payload("ranking", {"boost": 1.5}) == []


def test_validate_rule_payload_rejects_unknown_rule_type():
    errors = validate_rule_payload("auto_escalate", {})
    assert errors


def test_apply_ranking_and_confidence_adjustment_do_not_overwrite_original():
    candidates = [_candidate(id="a", ranking_score=50), _candidate(id="b", ranking_score=40)]
    ranked = apply_learning_rule(
        candidates,
        rule_type="ranking",
        rule_payload={"boost": 5, "priority_weights": {"high": 10}},
    )
    assert ranked.applied_effects == ["ranking"]
    assert ranked.candidates[0].ranking_score >= ranked.candidates[1].ranking_score

    adjusted = apply_learning_rule(
        candidates,
        rule_type="confidence_adjustment",
        rule_payload={"delta": 0.1},
    )
    assert adjusted.candidates[0].confidence == 0.7
    assert adjusted.candidates[0].metadata["original_confidence"] == 0.7
    assert adjusted.candidates[0].metadata["adjusted_confidence"] == pytest.approx(0.8)


def test_duplicate_suppression_and_evidence_requirements():
    candidates = [
        _candidate(id="1", fingerprint="same", evidence_count=0),
        _candidate(id="2", fingerprint="same", evidence_count=3),
        _candidate(id="3", fingerprint="other", evidence_count=0),
    ]
    dup = apply_learning_rule(
        candidates, rule_type="duplicate_suppression", rule_payload={}
    )
    assert dup.applied_effects == ["duplicate_suppression"]
    assert sum(1 for c in dup.candidates if c.suppress) == 1

    evidence = apply_learning_rule(
        candidates, rule_type="evidence_requirements", rule_payload={"min_evidence": 1}
    )
    assert evidence.applied_effects == ["evidence_requirements"]
    demoted = [c for c in evidence.candidates if c.metadata.get("evidence_requirement_failed")]
    assert len(demoted) == 2


def test_compare_rankings_reports_changes_without_production_side_effects():
    baseline = [_candidate(id="a"), _candidate(id="b"), _candidate(id="c")]
    optimized = [_candidate(id="c"), _candidate(id="a"), _candidate(id="b")]
    comparison = compare_rankings(baseline, optimized)
    assert comparison["rank_changes"] >= 1
    assert comparison["baseline_count"] == 3


def test_metric_snapshot_keeps_acceptance_conversion_resolution_separate():
    rows = [
        _rec(accepted_at=datetime.now(UTC)),
        _rec(
            accepted_at=datetime.now(UTC),
            converted_action_id=uuid4(),
        ),
        _rec(
            accepted_at=datetime.now(UTC),
            converted_action_id=uuid4(),
            resolved_at=datetime.now(UTC),
        ),
        _rec(
            dismissed_at=datetime.now(UTC),
            false_positive_status=GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE,
        ),
    ]
    snap = _metric_snapshot(rows)
    assert snap["accepted"] == 3
    assert snap["converted"] == 2
    assert snap["resolved"] == 1
    assert snap["false_positives"] == 1
    assert is_resolved(rows[2])
    assert not is_resolved(rows[1])


def test_optimization_roles_exclude_clients_and_delivery_managers():
    assert AppRole.BSG_LEADERSHIP in OPTIMIZATION_ROLES
    assert AppRole.SUPER_ADMIN in OPTIMIZATION_ROLES
    assert AppRole.CLIENT not in OPTIMIZATION_ROLES
    assert AppRole.DELIVERY_MANAGER not in OPTIMIZATION_ROLES

    with pytest.raises(HTTPException) as exc:
        assert_can_manage_optimization(
            SimpleNamespace(role=AppRole.CLIENT, org_id=uuid4(), id=uuid4())
        )
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        assert_can_manage_optimization(
            SimpleNamespace(role=AppRole.DELIVERY_MANAGER, org_id=uuid4(), id=uuid4())
        )
    assert exc.value.status_code == 403


def test_forbidden_effects_are_rejected_by_engine():
    result = apply_learning_rule(
        [_candidate()],
        rule_type="auto_accept",
        rule_payload={},
    )
    assert result.applied_effects == []
    assert "auto_accept" in result.rejected_effects


def test_lifecycle_resolved_requires_not_reopened():
    now = datetime.now(UTC)
    resolved = _rec(resolved_at=now, reopened_at=None)
    reopened = _rec(resolved_at=now, reopened_at=now + timedelta(hours=1))
    assert is_resolved(resolved)
    assert not is_resolved(reopened)
