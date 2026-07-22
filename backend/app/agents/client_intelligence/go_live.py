"""Go-Live readiness assessment engine (Phase 17.2)."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
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
from app.agents.client_intelligence.go_live_contracts import (
    GoLiveAssessment,
    GoLiveAvailability,
    GoLiveDecision,
    go_live_decision_label,
)
from app.agents.client_intelligence.readiness import (
    ReadinessIntegrityError,
    assess_project_readiness,
)
from app.agents.client_intelligence.readiness_contracts import (
    ReadinessStatus,
)
from app.db.models import AppRole

RULES_VERSION = "client_go_live_v1"


class GoLiveIntegrityError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def assess_go_live_readiness(
    pack: ClientEvidencePack,
    *,
    assessed_at: datetime | None = None,
) -> GoLiveAssessment:
    """Evaluate go-live posture from readiness + governed operational evidence."""
    working = pack.model_copy(deep=True)
    role = (
        AppRole.CLIENT
        if working.visibility_mode == EvidenceVisibility.CLIENT_SAFE
        else AppRole.DELIVERY_MANAGER
    )
    try:
        result = validate_client_evidence_pack(working, role=role)
    except EvidencePackIntegrityError as exc:
        raise GoLiveIntegrityError("EVIDENCE_PACK_INVALID", str(exc)) from exc
    if not result.is_valid:
        detail = "; ".join(issue.detail for issue in result.errors[:5]) or "invalid pack"
        raise GoLiveIntegrityError("EVIDENCE_PACK_INVALID", detail)

    try:
        readiness = assess_project_readiness(working, assessed_at=assessed_at)
    except ReadinessIntegrityError as exc:
        raise GoLiveIntegrityError(exc.code, exc.detail) from exc

    assessed = readiness.assessed_at
    outstanding_defects: list[str] = []
    open_blockers = list(readiness.major_blockers)
    required_approvals: list[str] = []
    dependency_gaps: list[str] = []
    rollout_notes: list[str] = []
    required_actions: list[str] = []
    reasons: list[str] = []

    # Outstanding defects / quality gaps
    for snap in working.quality.current_period:
        if snap.has_drift_alert:
            outstanding_defects.append("Open quality drift alert")
        if snap.rework_rate_pct is not None and snap.rework_rate_pct > Decimal("25"):
            outstanding_defects.append(
                f"Elevated rework rate ({snap.rework_rate_pct}%)"
            )
        if (
            snap.gold_set_accuracy_pct is not None
            and snap.gold_set_accuracy_pct < Decimal("80")
        ):
            outstanding_defects.append(
                f"Gold-set accuracy below threshold ({snap.gold_set_accuracy_pct}%)"
            )

    critical_risks = [
        risk
        for risk in working.delivery.open_risks
        if risk.risk_tier.lower() == "critical"
    ]
    for risk in critical_risks:
        open_blockers.append(f"Critical risk: {risk.title}")

    if working.governance.summary.blocking_dependency_count > 0:
        dependency_gaps.append(
            f"{working.governance.summary.blocking_dependency_count} blocking "
            "dependency(ies) remain open"
        )
        open_blockers.extend(dependency_gaps)

    if not working.governance.summary.approved_charter_present:
        required_approvals.append("Approved project charter")
    if working.governance.summary.critical_escalation_count > 0:
        required_approvals.append("Resolution of critical governance escalations")
        open_blockers.append("Critical governance escalations remain open")

    training = working.workforce.training
    if training.completion_pct is not None and training.completion_pct < Decimal("90"):
        required_actions.append("Complete mandatory training assignments")
    for item in readiness.missing_requirements[:8]:
        required_actions.append(f"Address missing requirement: {item}")

    at_risk_milestones = [
        m for m in working.delivery.milestones if m.status in {"at_risk", "missed"}
    ]
    if at_risk_milestones:
        rollout_notes.append(
            f"{len(at_risk_milestones)} milestone(s) are at risk or missed"
        )
        required_actions.append("Stabilize at-risk milestones before go-live")
    else:
        rollout_notes.append("No at-risk milestones in current evidence")

    if readiness.overall_score_pct is not None:
        reasons.append(
            f"Overall readiness score is {readiness.overall_score_pct}% "
            f"({readiness.status.value})"
        )
    else:
        reasons.append("Overall readiness score is unavailable")

    blocking_items = _unique([*open_blockers, *outstanding_defects, *dependency_gaps])
    required_actions = _unique(required_actions)
    required_approvals = _unique(required_approvals)

    decision = _decide(
        readiness_status=readiness.status,
        readiness_score=readiness.overall_score_pct,
        blocking_items=blocking_items,
        required_approvals=required_approvals,
        outstanding_defects=outstanding_defects,
    )
    if decision == GoLiveDecision.GO:
        reasons.append("No hard blockers, approvals complete, readiness supports go-live")
        required_actions = []
    elif decision == GoLiveDecision.GO_WITH_CONDITIONS:
        reasons.append("Go-live is possible only after listed conditions are met")
        if not required_actions:
            required_actions = ["Resolve remaining readiness gaps before distribution"]
    else:
        reasons.append("Hard blockers or insufficient readiness prevent go-live")

    confidence = min(
        readiness.assessment_confidence,
        Decimal("0.95") if decision != GoLiveDecision.NO_GO else readiness.assessment_confidence,
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    availability = GoLiveAvailability.AVAILABLE
    if readiness.availability.value in {"unavailable"}:
        availability = GoLiveAvailability.UNAVAILABLE
    elif readiness.availability.value in {"partial", "stale", "conflicting"}:
        availability = GoLiveAvailability.PARTIAL
    if working.overall_data_quality not in {
        DataQualityState.COMPLETE,
        DataQualityState.PARTIAL,
    }:
        availability = GoLiveAvailability.PARTIAL

    explainability = build_explainability(
        why_generated=(
            f"Go-live decision derived from readiness status, open blockers, "
            f"approvals, dependencies, and quality defects; decision="
            f"{go_live_decision_label(decision)}."
        ),
        confidence_score=confidence,
        supporting_evidence=[
            ExplainabilityEvidenceRef(
                source_agent=ref.source_agent,
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                visibility=ref.visibility,
                claim_keys=list(ref.claim_keys),
                observed_at=ref.observed_at,
            )
            for ref in readiness.evidence[:20]
        ],
        assumptions=[
            "Critical open risks and blocking dependencies are hard No-Go gates.",
            "Approved charter is required for an unconditional Go.",
            "Go with Conditions requires explicit required actions.",
        ],
        affected_kpis=[
            "go_live_decision",
            "readiness_score_pct",
            "open_blocker_count",
        ],
        reasoning="; ".join(reasons[:5]),
        model_version=RULES_VERSION,
        source_fingerprint=working.source_fingerprint,
        generated_at=assessed,
    )

    return GoLiveAssessment(
        org_id=working.project.org_id,
        project_id=working.project.project_id,
        as_of=working.reporting_period.as_of,
        assessed_at=assessed,
        availability=availability,
        decision=decision,
        confidence_score=confidence,
        reasons=_unique(reasons),
        blocking_items=blocking_items,
        required_actions=required_actions,
        outstanding_defects=_unique(outstanding_defects),
        open_blockers=_unique(open_blockers),
        required_approvals=required_approvals,
        dependency_gaps=_unique(dependency_gaps),
        rollout_readiness_notes=_unique(rollout_notes),
        evidence=list(readiness.evidence[:30]),
        limitations=list(readiness.limitations),
        source_fingerprint=working.source_fingerprint,
        rules_version=RULES_VERSION,
        explainability=explainability,
    )


def _decide(
    *,
    readiness_status: ReadinessStatus,
    readiness_score: Decimal | None,
    blocking_items: list[str],
    required_approvals: list[str],
    outstanding_defects: list[str],
) -> GoLiveDecision:
    if readiness_status == ReadinessStatus.INSUFFICIENT_EVIDENCE:
        return GoLiveDecision.NO_GO
    if blocking_items:
        # Soft defects alone may allow conditions; hard blockers force No Go.
        hard = [
            item
            for item in blocking_items
            if not item.startswith("Elevated rework")
            and not item.startswith("Gold-set")
            and item != "Open quality drift alert"
        ]
        if hard or readiness_status == ReadinessStatus.NOT_READY:
            return GoLiveDecision.NO_GO
    if (
        readiness_status == ReadinessStatus.READY
        and not required_approvals
        and not outstanding_defects
        and not blocking_items
    ):
        return GoLiveDecision.GO
    if readiness_score is not None and readiness_score >= Decimal("75"):
        if required_approvals or outstanding_defects or blocking_items:
            return GoLiveDecision.GO_WITH_CONDITIONS
        if readiness_status == ReadinessStatus.READY_WITH_MINOR_RISKS:
            return GoLiveDecision.GO_WITH_CONDITIONS
        return GoLiveDecision.GO
    if readiness_status == ReadinessStatus.CONDITIONALLY_READY:
        return GoLiveDecision.GO_WITH_CONDITIONS
    return GoLiveDecision.NO_GO


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
