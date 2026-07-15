from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class GoldenQACase:
    id: str
    question: str
    required_concepts: tuple[str, ...]
    expected_source_ids: tuple[str, ...]
    expected_citation_ids: tuple[str, ...]
    min_confidence: float = 0.6
    client_safe: bool = False


@dataclass(frozen=True)
class GoldenQAResult:
    case_id: str
    passed: bool
    concept_coverage: float
    source_accuracy: float
    citation_accuracy: float
    confidence_score: float
    client_safe_violation: bool
    average_retrieval_rank: float | None
    answer_quality: float = 0.0
    confidence_accuracy: float = 0.0


GOLDEN_QA_CASES: tuple[GoldenQACase, ...] = (
    GoldenQACase(
        id="sop_escalation_internal",
        question="What is the escalation path for a blocked delivery milestone?",
        required_concepts=("delivery manager", "project governance", "next action"),
        expected_source_ids=("sop-escalation",),
        expected_citation_ids=("sop-escalation#1",),
    ),
    GoldenQACase(
        id="client_safe_status",
        question="What can we tell the client about the weekly readiness status?",
        required_concepts=("client-safe", "approved", "no restricted details"),
        expected_source_ids=("client-status-guide",),
        expected_citation_ids=("client-status-guide#2",),
        min_confidence=0.7,
        client_safe=True,
    ),
    GoldenQACase(
        id="freshness_expiry",
        question="Which SOP version should be used when an older version is expired?",
        required_concepts=("current approved version", "expiry date", "superseded"),
        expected_source_ids=("version-policy",),
        expected_citation_ids=("version-policy#1",),
    ),
    GoldenQACase(
        id="lesson_writeback",
        question="Where should delivery lessons learned be recorded after a project incident?",
        required_concepts=("lesson learned", "histories folder", "approved source"),
        expected_source_ids=("lesson-capture-guide",),
        expected_citation_ids=("lesson-capture-guide#1",),
        min_confidence=0.65,
    ),
    GoldenQACase(
        id="restricted_visibility",
        question="Can a client-safe answer include leadership-only escalation contacts?",
        required_concepts=("client-safe", "restricted", "omit internal contacts"),
        expected_source_ids=("client-safe-policy",),
        expected_citation_ids=("client-safe-policy#1",),
        min_confidence=0.75,
        client_safe=True,
    ),
    GoldenQACase(
        id="retrieval_ranking",
        question="Which document should rank first for onboarding checklist questions?",
        required_concepts=("onboarding", "checklist", "guide"),
        expected_source_ids=("onboarding-guide",),
        expected_citation_ids=("onboarding-guide#1",),
        min_confidence=0.6,
    ),
    GoldenQACase(
        id="duplicate_sop_awareness",
        question="How should near-duplicate SOP copies be handled before merging?",
        required_concepts=("compare", "review", "never merge automatically"),
        expected_source_ids=("duplicate-policy",),
        expected_citation_ids=("duplicate-policy#1",),
        min_confidence=0.65,
    ),
    GoldenQACase(
        id="gap_resolution_review",
        question="What should happen when the same knowledge gap is triggered repeatedly?",
        required_concepts=("suggest documents", "human review", "do not auto-resolve"),
        expected_source_ids=("gap-policy",),
        expected_citation_ids=("gap-policy#1",),
        min_confidence=0.65,
    ),
)


def _coverage(expected: tuple[str, ...], actual: set[str]) -> float:
    if not expected:
        return 1.0
    return sum(1 for item in expected if item.lower() in actual) / len(expected)


def evaluate_golden_answer(case: GoldenQACase, answer: dict[str, Any]) -> GoldenQAResult:
    concepts = {str(item).lower() for item in answer.get("concepts", [])}
    source_ids = {str(item) for item in answer.get("source_ids", [])}
    citation_ids = {str(item) for item in answer.get("citation_ids", [])}
    retrieval_ranks = [float(rank) for rank in answer.get("retrieval_ranks", []) if rank is not None]
    confidence_score = float(answer.get("confidence_score", 0.0) or 0.0)
    client_safe_violation = bool(answer.get("client_safe_violation", False))
    expected_confidence = float(answer.get("expected_confidence", case.min_confidence) or case.min_confidence)

    concept_coverage = _coverage(case.required_concepts, concepts)
    source_accuracy = _coverage(case.expected_source_ids, source_ids)
    citation_accuracy = _coverage(case.expected_citation_ids, citation_ids)
    average_retrieval_rank = mean(retrieval_ranks) if retrieval_ranks else None
    answer_quality = round((concept_coverage + source_accuracy + citation_accuracy) / 3.0, 4)
    confidence_accuracy = 1.0 - min(1.0, abs(confidence_score - expected_confidence))
    passed = (
        concept_coverage >= 0.8
        and source_accuracy >= 1.0
        and citation_accuracy >= 1.0
        and confidence_score >= case.min_confidence
        and not (case.client_safe and client_safe_violation)
    )
    return GoldenQAResult(
        case_id=case.id,
        passed=passed,
        concept_coverage=concept_coverage,
        source_accuracy=source_accuracy,
        citation_accuracy=citation_accuracy,
        confidence_score=confidence_score,
        client_safe_violation=client_safe_violation,
        average_retrieval_rank=average_retrieval_rank,
        answer_quality=answer_quality,
        confidence_accuracy=round(confidence_accuracy, 4),
    )


def static_answer_fixtures() -> dict[str, dict[str, Any]]:
    return {
        "sop_escalation_internal": {
            "concepts": ["delivery manager", "project governance", "next action"],
            "source_ids": ["sop-escalation"],
            "citation_ids": ["sop-escalation#1"],
            "confidence_score": 0.86,
            "expected_confidence": 0.85,
            "retrieval_ranks": [1],
        },
        "client_safe_status": {
            "concepts": ["client-safe", "approved", "no restricted details"],
            "source_ids": ["client-status-guide"],
            "citation_ids": ["client-status-guide#2"],
            "confidence_score": 0.82,
            "expected_confidence": 0.8,
            "retrieval_ranks": [1, 2],
            "client_safe_violation": False,
        },
        "freshness_expiry": {
            "concepts": ["current approved version", "expiry date", "superseded"],
            "source_ids": ["version-policy"],
            "citation_ids": ["version-policy#1"],
            "confidence_score": 0.79,
            "expected_confidence": 0.78,
            "retrieval_ranks": [1],
        },
        "lesson_writeback": {
            "concepts": ["lesson learned", "histories folder", "approved source"],
            "source_ids": ["lesson-capture-guide"],
            "citation_ids": ["lesson-capture-guide#1"],
            "confidence_score": 0.77,
            "expected_confidence": 0.75,
            "retrieval_ranks": [1],
        },
        "restricted_visibility": {
            "concepts": ["client-safe", "restricted", "omit internal contacts"],
            "source_ids": ["client-safe-policy"],
            "citation_ids": ["client-safe-policy#1"],
            "confidence_score": 0.88,
            "expected_confidence": 0.85,
            "retrieval_ranks": [1],
            "client_safe_violation": False,
        },
        "retrieval_ranking": {
            "concepts": ["onboarding", "checklist", "guide"],
            "source_ids": ["onboarding-guide"],
            "citation_ids": ["onboarding-guide#1"],
            "confidence_score": 0.74,
            "expected_confidence": 0.72,
            "retrieval_ranks": [1],
        },
        "duplicate_sop_awareness": {
            "concepts": ["compare", "review", "never merge automatically"],
            "source_ids": ["duplicate-policy"],
            "citation_ids": ["duplicate-policy#1"],
            "confidence_score": 0.8,
            "expected_confidence": 0.78,
            "retrieval_ranks": [1],
        },
        "gap_resolution_review": {
            "concepts": ["suggest documents", "human review", "do not auto-resolve"],
            "source_ids": ["gap-policy"],
            "citation_ids": ["gap-policy#1"],
            "confidence_score": 0.81,
            "expected_confidence": 0.78,
            "retrieval_ranks": [1],
        },
    }


def run_static_golden_evaluation() -> dict[str, Any]:
    fixtures = static_answer_fixtures()
    results = [evaluate_golden_answer(case, fixtures.get(case.id, {})) for case in GOLDEN_QA_CASES]
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    client_safe_cases = [case for case in GOLDEN_QA_CASES if case.client_safe]
    client_safe_pass = sum(
        1
        for case, result in zip(GOLDEN_QA_CASES, results, strict=True)
        if case.client_safe and result.passed and not result.client_safe_violation
    )
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 1.0,
        "retrieval_accuracy": mean(result.source_accuracy for result in results) if results else 1.0,
        "source_accuracy": mean(result.source_accuracy for result in results) if results else 1.0,
        "citation_accuracy": mean(result.citation_accuracy for result in results) if results else 1.0,
        "answer_quality": mean(result.answer_quality for result in results) if results else 1.0,
        "answer_concept_coverage": mean(result.concept_coverage for result in results) if results else 1.0,
        "confidence_accuracy": mean(result.confidence_accuracy for result in results) if results else 1.0,
        "confidence_pass_rate": sum(
            1
            for case, result in zip(GOLDEN_QA_CASES, results, strict=True)
            if result.confidence_score >= case.min_confidence
        )
        / total
        if total
        else 1.0,
        "client_safe_compliance": (client_safe_pass / len(client_safe_cases)) if client_safe_cases else 1.0,
        "client_safe_violations": sum(1 for result in results if result.client_safe_violation),
        "average_retrieval_rank": mean(
            result.average_retrieval_rank for result in results if result.average_retrieval_rank is not None
        )
        if any(result.average_retrieval_rank is not None for result in results)
        else None,
        "results": [result.__dict__ for result in results],
    }


def build_evaluation_report(
    evaluation: dict[str, Any] | None = None,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = evaluation or run_static_golden_evaluation()
    regressions: list[str] = []
    if previous:
        for metric in (
            "pass_rate",
            "retrieval_accuracy",
            "citation_accuracy",
            "answer_quality",
            "confidence_accuracy",
            "client_safe_compliance",
        ):
            before = float(previous.get(metric, 1.0) or 1.0)
            after = float(current.get(metric, 1.0) or 1.0)
            if after + 1e-9 < before:
                regressions.append(f"{metric}: {before:.3f} → {after:.3f}")
    generated_at = datetime.now(UTC).isoformat()
    lines = [
        f"Knowledge golden evaluation report ({generated_at})",
        f"Cases: {current.get('passed', 0)}/{current.get('total', 0)} passed ({float(current.get('pass_rate', 0)):.1%})",
        f"Retrieval accuracy: {float(current.get('retrieval_accuracy', 0)):.1%}",
        f"Citation accuracy: {float(current.get('citation_accuracy', 0)):.1%}",
        f"Answer quality: {float(current.get('answer_quality', 0)):.1%}",
        f"Confidence accuracy: {float(current.get('confidence_accuracy', 0)):.1%}",
        f"Client-safe compliance: {float(current.get('client_safe_compliance', 0)):.1%}",
    ]
    if regressions:
        lines.append("Regressions: " + "; ".join(regressions))
    else:
        lines.append("Regressions: none")
    return {
        **current,
        "generated_at": generated_at,
        "regressions": regressions,
        "report_text": "\n".join(lines),
    }
