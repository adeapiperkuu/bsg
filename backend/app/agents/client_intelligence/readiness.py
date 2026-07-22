"""Deterministic Project Readiness Assessment engine (Phase 17.1).

Scores eight readiness categories from a validated ClientEvidencePack.
No LLM, no persistence, and no invented source facts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    DataQualityState,
    EvidenceVisibility,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    validate_client_evidence_pack,
)
from app.agents.client_intelligence.explainability import (
    ExplainabilityEvidenceRef,
    build_explainability,
)
from app.agents.client_intelligence.readiness_contracts import (
    LIMITATION_READINESS_CATEGORY_UNAVAILABLE,
    LIMITATION_READINESS_CONFIDENCE_LOW,
    LIMITATION_READINESS_EVIDENCE_INCOMPLETE,
    LIMITATION_READINESS_HARD_BLOCKER,
    ReadinessAssessment,
    ReadinessAvailability,
    ReadinessCategoryKey,
    ReadinessCategoryScore,
    ReadinessEvidencePeriod,
    ReadinessEvidenceRef,
    ReadinessFinding,
    ReadinessFindingSeverity,
    ReadinessStatus,
    readiness_status_for,
    readiness_status_label,
)
from app.db.models import AppRole

RULES_VERSION = "client_readiness_v1"
_CATEGORY_WEIGHT = Decimal("0.125")
_RELIABLE_QUALITY = frozenset({DataQualityState.COMPLETE, DataQualityState.PARTIAL})


class ReadinessIntegrityError(Exception):
    """Deterministic readiness integrity failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def assess_project_readiness(
    pack: ClientEvidencePack,
    *,
    assessed_at: datetime | None = None,
) -> ReadinessAssessment:
    """Build a readiness assessment from a validated evidence pack."""
    working = pack.model_copy(deep=True)
    _validate_pack_or_raise(working)

    assessed = assessed_at if assessed_at is not None else working.generated_at
    if assessed.tzinfo is None:
        raise ReadinessIntegrityError(
            "ASSESSED_AT_NAIVE",
            "assessed_at must be timezone-aware",
        )

    limitations: list[str] = []
    categories: list[ReadinessCategoryScore] = []
    findings: list[ReadinessFinding] = []
    all_evidence: list[ReadinessEvidenceRef] = []

    builders = (
        _score_resources,
        _score_planning,
        _score_risks,
        _score_dependencies,
        _score_documentation,
        _score_testing,
        _score_training,
        _score_governance,
    )
    for builder in builders:
        category, category_findings = builder(working)
        categories.append(category)
        findings.extend(category_findings)
        all_evidence.extend(category.evidence)
        limitations.extend(category.limitations)

    scored = [c for c in categories if c.score_pct is not None]
    if scored:
        weighted = sum(
            (c.score_pct or Decimal("0")) * c.weight for c in scored
        ) / sum(c.weight for c in scored)
        overall_score = weighted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        overall_score = None

    missing = _unique(
        [item for category in categories for item in category.missing_requirements]
    )
    blockers = _unique(
        [item for category in categories for item in category.blockers]
    )
    positives = _unique(
        [item for category in categories for item in category.positive_findings]
    )

    assessment_confidence = _assessment_confidence(categories, working)
    has_hard_blocker = bool(blockers)
    status = readiness_status_for(
        overall_score,
        has_hard_blocker=has_hard_blocker,
        assessment_confidence=assessment_confidence,
        scored_category_count=len(scored),
    )

    if missing:
        limitations.append(LIMITATION_READINESS_EVIDENCE_INCOMPLETE)
    if has_hard_blocker:
        limitations.append(LIMITATION_READINESS_HARD_BLOCKER)
    if assessment_confidence < Decimal("0.55"):
        limitations.append(LIMITATION_READINESS_CONFIDENCE_LOW)
    if any(
        c.availability == ReadinessAvailability.UNAVAILABLE for c in categories
    ):
        limitations.append(LIMITATION_READINESS_CATEGORY_UNAVAILABLE)

    availability = _overall_availability(categories, status)
    if status == ReadinessStatus.INSUFFICIENT_EVIDENCE and availability == (
        ReadinessAvailability.UNAVAILABLE
    ):
        overall_score = None

    explainability = build_explainability(
        why_generated=(
            f"Project readiness assessed across eight dimensions using governed "
            f"evidence; status={readiness_status_label(status)}."
        ),
        confidence_score=assessment_confidence,
        supporting_evidence=[
            ExplainabilityEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=list(ref.claim_keys),
                observed_at=ref.observed_at,
            )
            for ref in all_evidence[:20]
        ],
        assumptions=[
            "Category weights are equal unless a hard blocker overrides readiness.",
            "Missing critical evidence cannot produce a Ready status.",
            "Assessment confidence is separate from the readiness score.",
        ],
        affected_kpis=[
            "readiness_score_pct",
            "readiness_status",
            "go_live_decision",
        ],
        reasoning=(
            "Overall score is the weighted mean of scored categories. Hard blockers "
            "force Not Ready. Low evidence confidence yields Insufficient Evidence."
        ),
        model_version=RULES_VERSION,
        source_fingerprint=working.source_fingerprint,
        generated_at=assessed,
    )

    return ReadinessAssessment(
        org_id=working.project.org_id,
        project_id=working.project.project_id,
        as_of=working.reporting_period.as_of,
        assessed_at=assessed,
        availability=availability,
        overall_score_pct=overall_score,
        status=status,
        assessment_confidence=assessment_confidence,
        categories=categories,
        missing_requirements=missing,
        major_blockers=blockers,
        positive_findings=positives,
        findings=findings,
        evidence=_dedupe_evidence(all_evidence),
        limitations=_unique(limitations),
        source_fingerprint=working.source_fingerprint,
        rules_version=RULES_VERSION,
        explainability=explainability,
    )


def _validate_pack_or_raise(pack: ClientEvidencePack) -> None:
    role = (
        AppRole.CLIENT
        if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE
        else AppRole.DELIVERY_MANAGER
    )
    try:
        result = validate_client_evidence_pack(pack, role=role)
    except EvidencePackIntegrityError as exc:
        raise ReadinessIntegrityError("EVIDENCE_PACK_INVALID", str(exc)) from exc
    if not result.is_valid:
        detail = "; ".join(issue.detail for issue in result.errors[:5]) or "invalid pack"
        raise ReadinessIntegrityError("EVIDENCE_PACK_INVALID", detail)


def _score_resources(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    capacity = pack.workforce.capacity
    coverage = pack.workforce.skill_coverage
    evidence = _refs_for_tables(pack, {"utilization_snapshots", "capability_gaps", "teams"})
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"workforce_capacity", "skill_coverage", "utilization"})

    if capacity.active_worker_count is None and coverage.requirement_count == 0:
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.RESOURCES,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Aggregated workforce capacity evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("70")
    if capacity.active_worker_count is not None and capacity.active_worker_count > 0:
        score += Decimal("10")
        positives.append("Active workforce capacity is present")
    else:
        missing.append("Active worker capacity")
        score -= Decimal("15")

    if capacity.certified_sme_count is not None and capacity.certified_sme_count > 0:
        score += Decimal("8")
        positives.append("Certified SME coverage is present")
    else:
        missing.append("Certified SME coverage")
        findings.append(
            _finding(
                "resources.sme_gap",
                ReadinessCategoryKey.RESOURCES,
                ReadinessFindingSeverity.MAJOR,
                "Certified SME coverage is missing or zero",
                "SME_COVERAGE_MISSING",
                evidence,
            )
        )

    if coverage.gap_requirement_count > 0:
        score -= Decimal("12") * min(coverage.gap_requirement_count, 3)
        blockers.append("Critical skill coverage gaps remain open")
        findings.append(
            _finding(
                "resources.skill_gaps",
                ReadinessCategoryKey.RESOURCES,
                ReadinessFindingSeverity.BLOCKER,
                f"{coverage.gap_requirement_count} skill requirement gap(s) open",
                "SKILL_COVERAGE_GAPS",
                evidence,
            )
        )
    elif coverage.covered_requirement_count > 0:
        score += Decimal("7")
        positives.append("Skill requirements are covered")

    if capacity.utilization_pct is not None:
        util = capacity.utilization_pct
        if util > Decimal("95"):
            score -= Decimal("8")
            missing.append("Sustainable utilization headroom")
        elif Decimal("60") <= util <= Decimal("90"):
            score += Decimal("5")
            positives.append("Utilization is within a sustainable band")

    return _finalize_category(
        ReadinessCategoryKey.RESOURCES,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_planning(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    milestones = pack.delivery.milestones
    evidence = _refs_for_tables(pack, {"milestones", "project_charters", "project_scope_states"})
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"milestones", "project_charters", "project_scope"})

    if not milestones and pack.governance.charter is None:
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.PLANNING,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Milestone plan and project charter evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("65")
    if milestones:
        score += Decimal("15")
        positives.append("Milestone plan is present")
        at_risk = sum(1 for m in milestones if m.status in {"at_risk", "missed"})
        if at_risk:
            score -= Decimal("10") * min(at_risk, 3)
            findings.append(
                _finding(
                    "planning.milestones_at_risk",
                    ReadinessCategoryKey.PLANNING,
                    ReadinessFindingSeverity.MAJOR,
                    f"{at_risk} milestone(s) at risk or missed",
                    "MILESTONES_AT_RISK",
                    evidence,
                )
            )
    else:
        missing.append("Milestone plan")

    charter = pack.governance.charter
    if charter is not None and charter.status.lower() in {"approved", "published"}:
        score += Decimal("12")
        positives.append("Approved project charter is present")
    else:
        missing.append("Approved project charter")
        score -= Decimal("10")

    scope = pack.governance.scope
    if scope is not None and scope.scope_status.lower() in {"approved", "active", "baseline"}:
        score += Decimal("8")
        positives.append("Scope baseline is established")
    elif scope is None:
        missing.append("Scope baseline")

    return _finalize_category(
        ReadinessCategoryKey.PLANNING,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_risks(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    risks = pack.delivery.open_risks
    evidence = _refs_for_tables(pack, {"risk_alerts", "bottlenecks"})
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"risk_alerts", "bottlenecks", "risks"})

    if _source_unavailable(pack, {"risk_alerts", "risks"}):
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.RISKS,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Open risk evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("85")
    critical = [r for r in risks if r.risk_tier.lower() == "critical"]
    high = [r for r in risks if r.risk_tier.lower() == "high"]
    if not risks:
        positives.append("No open material risks")
        score = Decimal("95")
    if critical:
        score -= Decimal("25")
        blockers.append("Critical open risks remain unresolved")
        findings.append(
            _finding(
                "risks.critical_open",
                ReadinessCategoryKey.RISKS,
                ReadinessFindingSeverity.BLOCKER,
                f"{len(critical)} critical open risk(s)",
                "CRITICAL_RISKS_OPEN",
                evidence,
            )
        )
    if high:
        score -= Decimal("10") * min(len(high), 3)
        findings.append(
            _finding(
                "risks.high_open",
                ReadinessCategoryKey.RISKS,
                ReadinessFindingSeverity.MAJOR,
                f"{len(high)} high open risk(s)",
                "HIGH_RISKS_OPEN",
                evidence,
            )
        )
    if pack.delivery.open_bottlenecks:
        score -= Decimal("5") * min(len(pack.delivery.open_bottlenecks), 2)
        missing.append("Resolved delivery bottlenecks")

    return _finalize_category(
        ReadinessCategoryKey.RISKS,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_dependencies(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    summary = pack.governance.summary
    evidence = _refs_for_tables(pack, {"project_dependencies", "governance_dependencies"})
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"dependencies", "project_dependencies"})

    if summary.dependency_count == 0 and not pack.governance.dependencies:
        # Empty can mean healthy (no deps) or unavailable — treat as partial.
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.DEPENDENCIES,
                score_pct=Decimal("80.00"),
                availability=ReadinessAvailability.PARTIAL,
                weight=_CATEGORY_WEIGHT,
                positive_findings=["No open dependency records in current evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_EVIDENCE_INCOMPLETE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("90")
    if summary.blocking_dependency_count > 0:
        score -= Decimal("20") * min(summary.blocking_dependency_count, 3)
        blockers.append("Blocking dependencies remain open")
        findings.append(
            _finding(
                "dependencies.blocking",
                ReadinessCategoryKey.DEPENDENCIES,
                ReadinessFindingSeverity.BLOCKER,
                f"{summary.blocking_dependency_count} blocking dependency(ies)",
                "BLOCKING_DEPENDENCIES",
                evidence,
            )
        )
    if summary.overdue_dependency_count > 0:
        score -= Decimal("10") * min(summary.overdue_dependency_count, 3)
        missing.append("Resolved overdue dependencies")
    if summary.open_dependency_count == 0:
        positives.append("No open dependencies")
        score = max(score, Decimal("92"))

    return _finalize_category(
        ReadinessCategoryKey.DEPENDENCIES,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_documentation(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    knowledge = pack.knowledge
    evidence = _refs_for_tables(
        pack, {"knowledge_documents", "knowledge_document_versions"}
    )
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"knowledge_documents", "sop", "project_charter"})

    availability_by_type = {
        item.source_type: item for item in knowledge.source_availability
    }
    score = Decimal("60")
    scored_any = False
    for source_type, label in (
        ("sop", "SOP documentation"),
        ("project_charter", "Project charter documentation"),
        ("training_document", "Training documentation"),
    ):
        item = availability_by_type.get(source_type)
        if item is None:
            missing.append(label)
            continue
        scored_any = True
        if item.state == DataQualityState.COMPLETE and item.document_count > 0:
            score += Decimal("12")
            positives.append(f"{label} is available")
        elif item.document_count > 0:
            score += Decimal("6")
            missing.append(f"Complete {label.lower()}")
        else:
            missing.append(label)
            score -= Decimal("8")
            findings.append(
                _finding(
                    f"documentation.{source_type}_missing",
                    ReadinessCategoryKey.DOCUMENTATION,
                    ReadinessFindingSeverity.MAJOR,
                    f"{label} is missing",
                    "DOCUMENTATION_MISSING",
                    evidence,
                )
            )

    if not scored_any and not knowledge.documents:
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.DOCUMENTATION,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Approved knowledge documentation"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    return _finalize_category(
        ReadinessCategoryKey.DOCUMENTATION,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_testing(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    current = pack.quality.current_period
    evidence = _refs_for_tables(pack, {"quality_snapshots", "quality_drift_alerts"})
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"quality_snapshots", "quality"})

    if not current:
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.TESTING,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Quality / testing preparedness evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("70")
    accuracies = [
        snap.gold_set_accuracy_pct
        for snap in current
        if snap.gold_set_accuracy_pct is not None
    ]
    rework = [
        snap.rework_rate_pct for snap in current if snap.rework_rate_pct is not None
    ]
    evaluated = sum(snap.evaluated_item_count or 0 for snap in current)
    drift = any(snap.has_drift_alert for snap in current if snap.has_drift_alert)

    if accuracies:
        avg_acc = sum(accuracies) / Decimal(len(accuracies))
        if avg_acc >= Decimal("90"):
            score += Decimal("15")
            positives.append("Gold-set accuracy meets readiness threshold")
        elif avg_acc >= Decimal("80"):
            score += Decimal("5")
        else:
            score -= Decimal("15")
            missing.append("Gold-set accuracy at readiness threshold")
            findings.append(
                _finding(
                    "testing.accuracy_low",
                    ReadinessCategoryKey.TESTING,
                    ReadinessFindingSeverity.MAJOR,
                    "Gold-set accuracy below readiness threshold",
                    "TESTING_ACCURACY_LOW",
                    evidence,
                )
            )
    else:
        missing.append("Gold-set accuracy evidence")

    if rework:
        avg_rework = sum(rework) / Decimal(len(rework))
        if avg_rework <= Decimal("10"):
            score += Decimal("8")
            positives.append("Rework rate is within tolerance")
        elif avg_rework > Decimal("25"):
            score -= Decimal("12")
            blockers.append("Elevated rework indicates incomplete testing readiness")
            findings.append(
                _finding(
                    "testing.rework_high",
                    ReadinessCategoryKey.TESTING,
                    ReadinessFindingSeverity.BLOCKER,
                    "Rework rate exceeds go-live tolerance",
                    "TESTING_REWORK_HIGH",
                    evidence,
                )
            )

    if evaluated > 0:
        score += Decimal("5")
        positives.append("Evaluated quality sample is present")
    else:
        missing.append("Evaluated quality sample")

    if drift:
        score -= Decimal("10")
        findings.append(
            _finding(
                "testing.drift",
                ReadinessCategoryKey.TESTING,
                ReadinessFindingSeverity.MAJOR,
                "Quality drift alert is open",
                "QUALITY_DRIFT_OPEN",
                evidence,
            )
        )

    return _finalize_category(
        ReadinessCategoryKey.TESTING,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_training(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    training = pack.workforce.training
    evidence = _refs_for_tables(pack, {"training_records", "training_programs"})
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"training", "training_records"})

    if training.completion_pct is None and training.mandatory_program_count is None:
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.TRAINING,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Mandatory training completion evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("55")
    if training.completion_pct is not None:
        score = training.completion_pct
        if training.completion_pct >= Decimal("90"):
            positives.append("Mandatory training completion is on track")
        elif training.completion_pct < Decimal("50"):
            blockers.append("Mandatory training completion is below go-live threshold")
            findings.append(
                _finding(
                    "training.incomplete",
                    ReadinessCategoryKey.TRAINING,
                    ReadinessFindingSeverity.BLOCKER,
                    "Mandatory training completion below 50%",
                    "TRAINING_INCOMPLETE",
                    evidence,
                )
            )
        else:
            missing.append("Complete mandatory training assignments")
            findings.append(
                _finding(
                    "training.partial",
                    ReadinessCategoryKey.TRAINING,
                    ReadinessFindingSeverity.MAJOR,
                    "Mandatory training remains incomplete",
                    "TRAINING_PARTIAL",
                    evidence,
                )
            )

    if (training.expired_or_failed_assignment_count or 0) > 0:
        score -= Decimal("10")
        missing.append("Remediated expired or failed training")

    return _finalize_category(
        ReadinessCategoryKey.TRAINING,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _score_governance(
    pack: ClientEvidencePack,
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    summary = pack.governance.summary
    evidence = _refs_for_tables(
        pack,
        {
            "project_charters",
            "governance_actions",
            "governance_escalations",
            "project_scope_states",
        },
    )
    missing: list[str] = []
    blockers: list[str] = []
    positives: list[str] = []
    findings: list[ReadinessFinding] = []
    dq = _quality_for(pack, {"governance", "project_charters", "escalations"})

    has_signal = (
        summary.scope_present
        or summary.approved_charter_present
        or summary.action_count > 0
        or summary.escalation_count > 0
        or pack.governance.charter is not None
    )
    if not has_signal:
        return (
            ReadinessCategoryScore(
                category=ReadinessCategoryKey.GOVERNANCE,
                score_pct=None,
                availability=ReadinessAvailability.UNAVAILABLE,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=["Project governance evidence"],
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )

    score = Decimal("60")
    if summary.approved_charter_present:
        score += Decimal("20")
        positives.append("Approved charter is present")
    else:
        missing.append("Approved governance charter")
        score -= Decimal("10")

    if summary.scope_present:
        score += Decimal("10")
        positives.append("Governance scope is present")
    else:
        missing.append("Governance scope state")

    if summary.critical_escalation_count > 0:
        score -= Decimal("20")
        blockers.append("Critical governance escalations remain open")
        findings.append(
            _finding(
                "governance.critical_escalations",
                ReadinessCategoryKey.GOVERNANCE,
                ReadinessFindingSeverity.BLOCKER,
                f"{summary.critical_escalation_count} critical escalation(s) open",
                "CRITICAL_ESCALATIONS_OPEN",
                evidence,
            )
        )
    elif summary.open_escalation_count > 0:
        score -= Decimal("8")
        findings.append(
            _finding(
                "governance.open_escalations",
                ReadinessCategoryKey.GOVERNANCE,
                ReadinessFindingSeverity.MAJOR,
                f"{summary.open_escalation_count} open escalation(s)",
                "OPEN_ESCALATIONS",
                evidence,
            )
        )

    if summary.overdue_action_count > 0:
        score -= Decimal("8")
        missing.append("Completed overdue governance actions")

    return _finalize_category(
        ReadinessCategoryKey.GOVERNANCE,
        score,
        dq,
        evidence,
        missing,
        blockers,
        positives,
        findings,
    )


def _finalize_category(
    category: ReadinessCategoryKey,
    raw_score: Decimal,
    dq: DataQualityState,
    evidence: list[ReadinessEvidenceRef],
    missing: list[str],
    blockers: list[str],
    positives: list[str],
    findings: list[ReadinessFinding],
) -> tuple[ReadinessCategoryScore, list[ReadinessFinding]]:
    score = max(Decimal("0"), min(Decimal("100"), raw_score))
    score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if dq == DataQualityState.STALE:
        availability = ReadinessAvailability.STALE
    elif dq == DataQualityState.CONFLICTING:
        availability = ReadinessAvailability.CONFLICTING
        return (
            ReadinessCategoryScore(
                category=category,
                score_pct=None,
                availability=availability,
                weight=_CATEGORY_WEIGHT,
                missing_requirements=_unique(missing),
                blockers=_unique(blockers),
                positive_findings=_unique(positives),
                evidence=evidence,
                limitations=[LIMITATION_READINESS_CATEGORY_UNAVAILABLE],
                data_quality=dq,
            ),
            findings,
        )
    elif missing or dq == DataQualityState.PARTIAL:
        availability = ReadinessAvailability.PARTIAL
    else:
        availability = ReadinessAvailability.AVAILABLE
    return (
        ReadinessCategoryScore(
            category=category,
            score_pct=score,
            availability=availability,
            weight=_CATEGORY_WEIGHT,
            missing_requirements=_unique(missing),
            blockers=_unique(blockers),
            positive_findings=_unique(positives),
            evidence=evidence,
            limitations=[],
            data_quality=dq,
        ),
        findings,
    )


def _assessment_confidence(
    categories: list[ReadinessCategoryScore],
    pack: ClientEvidencePack,
) -> Decimal:
    scored = sum(
        1
        for c in categories
        if c.availability
        in {ReadinessAvailability.AVAILABLE, ReadinessAvailability.PARTIAL}
    )
    base = Decimal(scored) / Decimal("8")
    if pack.overall_data_quality == DataQualityState.COMPLETE:
        base += Decimal("0.10")
    elif pack.overall_data_quality in {
        DataQualityState.STALE,
        DataQualityState.CONFLICTING,
        DataQualityState.UNAVAILABLE,
    }:
        base -= Decimal("0.20")
    return max(Decimal("0"), min(Decimal("1"), base)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _overall_availability(
    categories: list[ReadinessCategoryScore],
    status: ReadinessStatus,
) -> ReadinessAvailability:
    states = {c.availability for c in categories}
    if status == ReadinessStatus.INSUFFICIENT_EVIDENCE and all(
        s == ReadinessAvailability.UNAVAILABLE for s in states
    ):
        return ReadinessAvailability.UNAVAILABLE
    if ReadinessAvailability.CONFLICTING in states:
        return ReadinessAvailability.CONFLICTING
    if ReadinessAvailability.STALE in states:
        return ReadinessAvailability.STALE
    if ReadinessAvailability.UNAVAILABLE in states or (
        ReadinessAvailability.PARTIAL in states
    ):
        return ReadinessAvailability.PARTIAL
    return ReadinessAvailability.AVAILABLE


def _quality_for(pack: ClientEvidencePack, sources: set[str]) -> DataQualityState:
    matches = [
        issue.state
        for issue in pack.data_quality
        if any(token in issue.source for token in sources)
    ]
    if not matches:
        return DataQualityState.PARTIAL
    priority = [
        DataQualityState.UNAVAILABLE,
        DataQualityState.CONFLICTING,
        DataQualityState.STALE,
        DataQualityState.PARTIAL,
        DataQualityState.COMPLETE,
    ]
    for state in priority:
        if state in matches:
            return state
    return DataQualityState.PARTIAL


def _source_unavailable(pack: ClientEvidencePack, sources: set[str]) -> bool:
    return any(
        issue.state == DataQualityState.UNAVAILABLE
        and any(token in issue.source for token in sources)
        for issue in pack.data_quality
    )


def _refs_for_tables(
    pack: ClientEvidencePack, tables: set[str]
) -> list[ReadinessEvidenceRef]:
    refs: list[ReadinessEvidenceRef] = []
    for ref in pack.evidence:
        if ref.source_table not in tables:
            continue
        refs.append(_to_readiness_ref(ref, pack.source_fingerprint))
    return _dedupe_evidence(refs)


def _to_readiness_ref(
    ref: ClientEvidenceReference, fingerprint: str
) -> ReadinessEvidenceRef:
    return ReadinessEvidenceRef(
        source_agent=ref.source_agent,
        source_table=ref.source_table,
        source_row_id=ref.source_row_id,
        visibility=ref.visibility,
        period=ReadinessEvidencePeriod.CURRENT,
        claim_keys=list(ref.claim_keys),
        source_fingerprint=fingerprint,
        observed_at=ref.observed_at,
    )


def _finding(
    finding_id: str,
    category: ReadinessCategoryKey,
    severity: ReadinessFindingSeverity,
    summary: str,
    reason_code: str,
    evidence: list[ReadinessEvidenceRef],
) -> ReadinessFinding:
    return ReadinessFinding(
        finding_id=finding_id,
        category=category,
        severity=severity,
        summary=summary,
        reason_code=reason_code,
        evidence=list(evidence[:5]),
    )


def _dedupe_evidence(refs: list[ReadinessEvidenceRef]) -> list[ReadinessEvidenceRef]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ReadinessEvidenceRef] = []
    for ref in refs:
        key = (ref.source_agent.value, ref.source_table, str(ref.source_row_id))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _unique(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned
