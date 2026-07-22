"""Readiness recommendation engine with reusable explainability (Phase 17.3 / 19.3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.client_intelligence.contracts import ClientEvidencePack, ClientIntelligenceModel
from app.agents.client_intelligence.explainability import (
    AiExplainability,
    ExplainabilityEvidenceRef,
    build_explainability,
)
from app.agents.client_intelligence.go_live import (
    GoLiveIntegrityError,
    assess_go_live_readiness,
)
from app.agents.client_intelligence.go_live_contracts import GoLiveDecision
from app.agents.client_intelligence.readiness import (
    ReadinessIntegrityError,
    assess_project_readiness,
)
from app.agents.client_intelligence.readiness_contracts import (
    ReadinessAssessment,
    ReadinessCategoryKey,
    ReadinessEvidenceRef,
    ReadinessFindingSeverity,
    ReadinessStatus,
)

RULES_VERSION = "client_readiness_recommendations_v1"


class RecommendationPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationType(StrEnum):
    COMPLETE_UAT = "complete_uat"
    ASSIGN_SME = "assign_sme"
    RESOLVE_DEPENDENCY = "resolve_dependency"
    FINALIZE_DOCUMENTATION = "finalize_documentation"
    INCREASE_TESTING = "increase_testing"
    COMPLETE_TRAINING = "complete_training"
    RESOLVE_RISK = "resolve_risk"
    OBTAIN_APPROVAL = "obtain_approval"
    STABILIZE_MILESTONE = "stabilize_milestone"
    STRENGTHEN_GOVERNANCE = "strengthen_governance"


class ReadinessRecommendation(ClientIntelligenceModel):
    recommendation_id: str = Field(min_length=1)
    recommendation_type: RecommendationType
    title: str = Field(min_length=1)
    priority: RecommendationPriority
    expected_business_impact: str = Field(min_length=1)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    reasoning: str = Field(min_length=1)
    category: ReadinessCategoryKey | None = None
    evidence: list[ReadinessEvidenceRef] = Field(default_factory=list)
    explainability: AiExplainability


class ReadinessRecommendationSet(ClientIntelligenceModel):
    org_id: UUID
    project_id: UUID
    as_of: datetime | None = None
    assessed_at: datetime
    recommendations: list[ReadinessRecommendation] = Field(default_factory=list)
    source_fingerprint: str
    rules_version: str = RULES_VERSION
    limitations: list[str] = Field(default_factory=list)

    @field_validator("limitations")
    @classmethod
    def _canonicalize(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip() if isinstance(item, str) else ""
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    @field_validator("assessed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("assessed_at must be timezone-aware")
        return value


class RecommendationIntegrityError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def generate_readiness_recommendations(
    pack: ClientEvidencePack,
    *,
    assessed_at: datetime | None = None,
    readiness: ReadinessAssessment | None = None,
) -> ReadinessRecommendationSet:
    """Generate prioritized, explainable recommendations from readiness gaps."""
    working = pack.model_copy(deep=True)
    try:
        assessment = readiness or assess_project_readiness(
            working, assessed_at=assessed_at
        )
        go_live = assess_go_live_readiness(working, assessed_at=assessed_at)
    except (ReadinessIntegrityError, GoLiveIntegrityError) as exc:
        raise RecommendationIntegrityError(exc.code, exc.detail) from exc

    recommendations: list[ReadinessRecommendation] = []

    for finding in assessment.findings:
        if finding.severity == ReadinessFindingSeverity.POSITIVE:
            continue
        mapped = _map_finding(finding.reason_code, finding.category)
        if mapped is None:
            continue
        rec_type, title, impact = mapped
        priority = (
            RecommendationPriority.CRITICAL
            if finding.severity == ReadinessFindingSeverity.BLOCKER
            else RecommendationPriority.HIGH
            if finding.severity == ReadinessFindingSeverity.MAJOR
            else RecommendationPriority.MEDIUM
        )
        confidence = _confidence_for(assessment, finding.evidence)
        recommendations.append(
            _build_recommendation(
                recommendation_id=f"rec.{finding.finding_id}",
                recommendation_type=rec_type,
                title=title,
                priority=priority,
                expected_business_impact=impact,
                confidence=confidence,
                reasoning=finding.summary,
                category=finding.category,
                evidence=finding.evidence,
                source_fingerprint=assessment.source_fingerprint,
                generated_at=assessment.assessed_at,
                affected_kpis=["readiness_score_pct", finding.category.value],
            )
        )

    for missing in assessment.missing_requirements:
        mapped = _map_missing(missing)
        if mapped is None:
            continue
        rec_type, title, category, impact = mapped
        if any(r.recommendation_type == rec_type for r in recommendations):
            continue
        recommendations.append(
            _build_recommendation(
                recommendation_id=f"rec.missing.{rec_type.value}",
                recommendation_type=rec_type,
                title=title,
                priority=RecommendationPriority.HIGH,
                expected_business_impact=impact,
                confidence=max(Decimal("0.45"), assessment.assessment_confidence),
                reasoning=f"Missing requirement detected: {missing}",
                category=category,
                evidence=list(assessment.evidence[:5]),
                source_fingerprint=assessment.source_fingerprint,
                generated_at=assessment.assessed_at,
                affected_kpis=["readiness_score_pct", category.value],
            )
        )

    if go_live.decision in {GoLiveDecision.NO_GO, GoLiveDecision.GO_WITH_CONDITIONS}:
        for action in go_live.required_actions[:5]:
            if "training" in action.lower():
                rec_type = RecommendationType.COMPLETE_TRAINING
                category = ReadinessCategoryKey.TRAINING
            elif "milestone" in action.lower():
                rec_type = RecommendationType.STABILIZE_MILESTONE
                category = ReadinessCategoryKey.PLANNING
            elif "documentation" in action.lower() or "sop" in action.lower():
                rec_type = RecommendationType.FINALIZE_DOCUMENTATION
                category = ReadinessCategoryKey.DOCUMENTATION
            else:
                continue
            if any(r.recommendation_type == rec_type for r in recommendations):
                continue
            recommendations.append(
                _build_recommendation(
                    recommendation_id=f"rec.golive.{rec_type.value}",
                    recommendation_type=rec_type,
                    title=action,
                    priority=(
                        RecommendationPriority.CRITICAL
                        if go_live.decision == GoLiveDecision.NO_GO
                        else RecommendationPriority.HIGH
                    ),
                    expected_business_impact=(
                        "Clears a go-live condition and reduces launch risk"
                    ),
                    confidence=go_live.confidence_score,
                    reasoning=action,
                    category=category,
                    evidence=list(go_live.evidence[:5]),
                    source_fingerprint=go_live.source_fingerprint,
                    generated_at=go_live.assessed_at,
                    affected_kpis=["go_live_decision", "readiness_score_pct"],
                )
            )

    if (
        assessment.status
        in {
            ReadinessStatus.CONDITIONALLY_READY,
            ReadinessStatus.READY_WITH_MINOR_RISKS,
            ReadinessStatus.NOT_READY,
        }
        and not any(
            r.recommendation_type == RecommendationType.INCREASE_TESTING
            for r in recommendations
        )
    ):
        testing = next(
            (c for c in assessment.categories if c.category == ReadinessCategoryKey.TESTING),
            None,
        )
        if testing and (
            testing.score_pct is None or testing.score_pct < Decimal("80")
        ):
            recommendations.append(
                _build_recommendation(
                    recommendation_id="rec.increase_testing",
                    recommendation_type=RecommendationType.INCREASE_TESTING,
                    title="Increase Testing",
                    priority=RecommendationPriority.HIGH,
                    expected_business_impact=(
                        "Improves quality preparedness and reduces post-launch defect risk"
                    ),
                    confidence=assessment.assessment_confidence,
                    reasoning="Testing readiness is below the preferred launch threshold",
                    category=ReadinessCategoryKey.TESTING,
                    evidence=list(testing.evidence[:5]),
                    source_fingerprint=assessment.source_fingerprint,
                    generated_at=assessment.assessed_at,
                    affected_kpis=["readiness_score_pct", "testing"],
                )
            )

    recommendations = _dedupe_and_sort(recommendations)
    return ReadinessRecommendationSet(
        org_id=assessment.org_id,
        project_id=assessment.project_id,
        assessed_at=assessment.assessed_at,
        recommendations=recommendations,
        source_fingerprint=assessment.source_fingerprint,
        rules_version=RULES_VERSION,
        limitations=list(assessment.limitations),
    )


def _build_recommendation(
    *,
    recommendation_id: str,
    recommendation_type: RecommendationType,
    title: str,
    priority: RecommendationPriority,
    expected_business_impact: str,
    confidence: Decimal,
    reasoning: str,
    category: ReadinessCategoryKey | None,
    evidence: list[ReadinessEvidenceRef],
    source_fingerprint: str,
    generated_at: datetime,
    affected_kpis: list[str],
) -> ReadinessRecommendation:
    explainability = build_explainability(
        why_generated=f"Generated from readiness gap: {reasoning}",
        confidence_score=confidence,
        supporting_evidence=[
            ExplainabilityEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=list(ref.claim_keys),
                summary=title,
                observed_at=ref.observed_at,
            )
            for ref in evidence[:10]
        ],
        assumptions=[
            "Recommendations are derived only from governed evidence gaps.",
            "Priority reflects blocker/major/minor severity from readiness findings.",
        ],
        affected_kpis=affected_kpis,
        reasoning=reasoning,
        model_version=RULES_VERSION,
        source_fingerprint=source_fingerprint,
        generated_at=generated_at,
    )
    return ReadinessRecommendation(
        recommendation_id=recommendation_id,
        recommendation_type=recommendation_type,
        title=title,
        priority=priority,
        expected_business_impact=expected_business_impact,
        confidence=confidence.quantize(Decimal("0.01")),
        reasoning=reasoning,
        category=category,
        evidence=list(evidence[:10]),
        explainability=explainability,
    )


def _map_finding(
    reason_code: str, category: ReadinessCategoryKey
) -> tuple[RecommendationType, str, str] | None:
    mapping: dict[str, tuple[RecommendationType, str, str]] = {
        "SME_COVERAGE_MISSING": (
            RecommendationType.ASSIGN_SME,
            "Assign SME",
            "Restores critical coverage and reduces delivery/readiness risk",
        ),
        "SKILL_COVERAGE_GAPS": (
            RecommendationType.ASSIGN_SME,
            "Assign SME",
            "Closes capability gaps that block readiness",
        ),
        "BLOCKING_DEPENDENCIES": (
            RecommendationType.RESOLVE_DEPENDENCY,
            "Resolve Dependency",
            "Removes launch blockers tied to external or internal dependencies",
        ),
        "DOCUMENTATION_MISSING": (
            RecommendationType.FINALIZE_DOCUMENTATION,
            "Finalize Documentation",
            "Ensures client-facing operating procedures and charter artifacts are ready",
        ),
        "TESTING_ACCURACY_LOW": (
            RecommendationType.INCREASE_TESTING,
            "Increase Testing",
            "Raises quality confidence before go-live",
        ),
        "TESTING_REWORK_HIGH": (
            RecommendationType.COMPLETE_UAT,
            "Complete UAT",
            "Reduces defect leakage and client-visible quality risk",
        ),
        "QUALITY_DRIFT_OPEN": (
            RecommendationType.INCREASE_TESTING,
            "Increase Testing",
            "Contains quality drift before launch",
        ),
        "TRAINING_INCOMPLETE": (
            RecommendationType.COMPLETE_TRAINING,
            "Complete Training",
            "Ensures workforce readiness for go-live operations",
        ),
        "TRAINING_PARTIAL": (
            RecommendationType.COMPLETE_TRAINING,
            "Complete Training",
            "Closes remaining mandatory training gaps",
        ),
        "CRITICAL_RISKS_OPEN": (
            RecommendationType.RESOLVE_RISK,
            "Resolve Risk",
            "Clears critical delivery risks that block go-live",
        ),
        "HIGH_RISKS_OPEN": (
            RecommendationType.RESOLVE_RISK,
            "Resolve Risk",
            "Reduces material delivery risk exposure",
        ),
        "CRITICAL_ESCALATIONS_OPEN": (
            RecommendationType.STRENGTHEN_GOVERNANCE,
            "Strengthen Governance",
            "Restores governance control required for launch approval",
        ),
        "OPEN_ESCALATIONS": (
            RecommendationType.STRENGTHEN_GOVERNANCE,
            "Strengthen Governance",
            "Improves governance posture ahead of go-live",
        ),
        "MILESTONES_AT_RISK": (
            RecommendationType.STABILIZE_MILESTONE,
            "Stabilize Milestone",
            "Protects timeline confidence and rollout readiness",
        ),
    }
    if reason_code in mapping:
        return mapping[reason_code]
    if category == ReadinessCategoryKey.DOCUMENTATION:
        return (
            RecommendationType.FINALIZE_DOCUMENTATION,
            "Finalize Documentation",
            "Improves documentation completeness for client readiness",
        )
    return None


def _map_missing(
    missing: str,
) -> tuple[RecommendationType, str, ReadinessCategoryKey, str] | None:
    lower = missing.lower()
    if "sme" in lower:
        return (
            RecommendationType.ASSIGN_SME,
            "Assign SME",
            ReadinessCategoryKey.RESOURCES,
            "Restores critical SME coverage",
        )
    if "training" in lower:
        return (
            RecommendationType.COMPLETE_TRAINING,
            "Complete Training",
            ReadinessCategoryKey.TRAINING,
            "Closes mandatory training gaps",
        )
    if "charter" in lower or "documentation" in lower or "sop" in lower:
        return (
            RecommendationType.FINALIZE_DOCUMENTATION,
            "Finalize Documentation",
            ReadinessCategoryKey.DOCUMENTATION,
            "Completes required documentation for go-live",
        )
    if "dependency" in lower:
        return (
            RecommendationType.RESOLVE_DEPENDENCY,
            "Resolve Dependency",
            ReadinessCategoryKey.DEPENDENCIES,
            "Removes dependency blockers",
        )
    if "gold-set" in lower or "quality" in lower or "testing" in lower:
        return (
            RecommendationType.INCREASE_TESTING,
            "Increase Testing",
            ReadinessCategoryKey.TESTING,
            "Improves testing preparedness",
        )
    if "approval" in lower or "governance" in lower:
        return (
            RecommendationType.OBTAIN_APPROVAL,
            "Obtain Approval",
            ReadinessCategoryKey.GOVERNANCE,
            "Secures required governance approval",
        )
    return None


def _confidence_for(
    assessment: ReadinessAssessment, evidence: list[ReadinessEvidenceRef]
) -> Decimal:
    base = assessment.assessment_confidence
    if evidence:
        base = min(Decimal("0.95"), base + Decimal("0.05"))
    return base.quantize(Decimal("0.01"))


_PRIORITY_ORDER = {
    RecommendationPriority.CRITICAL: 0,
    RecommendationPriority.HIGH: 1,
    RecommendationPriority.MEDIUM: 2,
    RecommendationPriority.LOW: 3,
}


def _dedupe_and_sort(
    recommendations: list[ReadinessRecommendation],
) -> list[ReadinessRecommendation]:
    seen: set[RecommendationType] = set()
    deduped: list[ReadinessRecommendation] = []
    for item in sorted(
        recommendations,
        key=lambda rec: (_PRIORITY_ORDER[rec.priority], -float(rec.confidence), rec.title),
    ):
        if item.recommendation_type in seen:
            continue
        seen.add(item.recommendation_type)
        deduped.append(item)
    return deduped
