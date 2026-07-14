"""Phase 9: deterministic Governance escalation suggestion detection and lifecycle."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.analytics.sla import dependency_overdue_days, effective_action_status
from app.agents.governance.schemas.governance import (
    EscalationSuggestionScanResult,
    EscalationSuggestionSnoozeRequest,
    GovernanceAIRecommendationRead,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.governance_service import load_project_names
from app.agents.governance.services.notification_service import create_governance_notification
from app.agents.governance.services.recommendation_service import (
    _to_read,
    assert_can_generate_ai_recommendations,
    assert_can_view_ai_recommendations,
    can_generate_ai_recommendations,
)
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    DeliveryConfidenceScore,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationPriority,
    GovernanceAIRecommendationScope,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationSuggestionScan,
    GovernanceEscalationSourceType,
    GovernanceEscalationStatus,
    GovernanceEscalationTriggerType,
    GovernanceRecordEvidenceLink,
    GovernanceRecordEvidenceSourceType,
    GovernanceRecordTargetType,
    GovernanceScopeStatus,
    Milestone,
    MilestoneStatus,
    MitigationRecommendation,
    ProjectDependency,
    ProjectScopeState,
    QualitySnapshot,
    RecommendationStatus,
    RiskAlert,
    RiskTier,
    ScanStatus,
    Team,
    ThroughputSnapshot,
    CapabilityGap,
    CapabilityGapSeverity,
    CapabilityGapStatus,
    WorkforceUtilizationSnapshot,
)
from app.services.scoping import get_visible_project, scoped_project_query

logger = logging.getLogger(__name__)

OPEN_DEP_STATUSES = {GovernanceDependencyStatus.OPEN, GovernanceDependencyStatus.BLOCKING}
OPEN_ESC_STATUSES = {GovernanceEscalationStatus.OPEN, GovernanceEscalationStatus.IN_PROGRESS}
OPEN_ACTION_STATUSES = {
    GovernanceActionStatus.OPEN,
    GovernanceActionStatus.IN_PROGRESS,
    GovernanceActionStatus.OVERDUE,
}
OPEN_ALERT_STATUSES = {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}

_METRICS: dict[str, float] = {
    "scans_started": 0,
    "scans_completed": 0,
    "scans_failed": 0,
    "scan_duration_ms_total": 0,
    "projects_scanned": 0,
    "candidates_detected": 0,
    "suggestions_created": 0,
    "suggestions_reused": 0,
    "suggestions_suppressed_existing_escalation": 0,
    "suggestions_dismissed": 0,
    "suggestions_snoozed": 0,
    "suggestions_converted": 0,
    "llm_enrichment_requests": 0,
    "llm_enrichment_failures": 0,
    "query_executes_total": 0,
}
_ACTIVE_SCAN_KEYS: set[tuple[UUID, UUID | None]] = set()


def _inc(name: str, value: float = 1.0) -> None:
    _METRICS[name] = _METRICS.get(name, 0.0) + value


def get_escalation_suggestion_metrics() -> dict[str, float]:
    return dict(_METRICS)


def reset_escalation_suggestion_metrics() -> None:
    for key in list(_METRICS):
        _METRICS[key] = 0.0


def escalation_suggestions_enabled() -> bool:
    return bool(get_settings().governance_escalation_suggestions_enabled)


class GovernanceEscalationCandidate(BaseModel):
    trigger_type: GovernanceEscalationTriggerType
    project_id: UUID
    title: str
    summary: str
    severity_score: float
    suggested_severity: GovernanceEscalationSeverity
    primary_evidence_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    trigger_entity_type: str
    trigger_entity_id: UUID | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    priority: GovernanceAIRecommendationPriority = GovernanceAIRecommendationPriority.HIGH
    confidence: float = 0.85
    risk_categories: list[str] = Field(default_factory=list)
    signal_providers: list[str] = Field(default_factory=list)
    linked_milestone_id: UUID | None = None


class ProjectRiskSignal(BaseModel):
    category: str
    provider: str
    project_id: UUID
    evidence_id: str
    title: str
    summary: str
    score: float
    entity_type: str
    entity_id: UUID | None = None
    status: str | None = None
    severity: str | None = None
    milestone_id: UUID | None = None


def _fingerprint(
    *,
    org_id: UUID,
    project_id: UUID,
    trigger_type: GovernanceEscalationTriggerType,
    entity_id: UUID | None,
    evidence_key: str,
    threshold_bucket: str,
) -> str:
    raw = "|".join(
        [
            "esc_sug",
            str(org_id),
            str(project_id),
            trigger_type.value,
            str(entity_id or ""),
            evidence_key,
            threshold_bucket,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique_risk_signals(signals: list[ProjectRiskSignal]) -> list[ProjectRiskSignal]:
    seen: set[tuple[str, str]] = set()
    unique: list[ProjectRiskSignal] = []
    for signal in sorted(signals, key=lambda item: item.score, reverse=True):
        key = (signal.category, signal.evidence_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(signal)
    return unique


def _risk_categories(signals: list[ProjectRiskSignal]) -> list[str]:
    return sorted({signal.category for signal in signals})


def _signal_providers(signals: list[ProjectRiskSignal]) -> list[str]:
    return sorted({signal.provider for signal in signals})


def _milestone_risk_score(
    *,
    days_until_due: int,
    blockers: int,
    critical_actions: int,
    confidence_drop: float,
    critical_delivery_risks: int,
    dependency_severity: float,
    cross_agent_score: float = 0.0,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if days_until_due < 0:
        score += 30.0
        reasons.append("milestone overdue")
    elif days_until_due <= 7:
        score += 20.0
        reasons.append("milestone due within 7 days")
    elif days_until_due <= 14:
        score += 10.0
        reasons.append("milestone due within 14 days")
    if blockers:
        score += min(25.0, blockers * 8.0)
        reasons.append(f"{blockers} unresolved blocker(s)")
    if critical_actions:
        score += min(20.0, critical_actions * 10.0)
        reasons.append(f"{critical_actions} overdue critical action(s)")
    if confidence_drop > 0:
        score += min(20.0, confidence_drop)
        reasons.append(f"confidence declined {confidence_drop:.0f} point(s)")
    if critical_delivery_risks:
        score += min(25.0, critical_delivery_risks * 12.0)
        reasons.append(f"{critical_delivery_risks} critical/high delivery risk(s)")
    if dependency_severity > 0:
        score += min(15.0, dependency_severity)
        reasons.append("dependency severity contributing")
    if cross_agent_score > 0:
        score += min(20.0, cross_agent_score)
        reasons.append("cross-agent signals contributing")
    return min(100.0, score), reasons


def _combined_risk_qualifies(
    signals: list[ProjectRiskSignal],
    *,
    min_categories: int,
) -> tuple[bool, list[ProjectRiskSignal], list[str]]:
    unique = _unique_risk_signals(signals)
    categories = _risk_categories(unique)
    return len(categories) >= min_categories, unique, categories


def _evidence_ref(
    *,
    evidence_id: str,
    entity_type: str,
    entity_id: UUID | None,
    project_id: UUID,
    title: str,
    summary: str,
    status: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "project_id": str(project_id),
        "title": title,
        "summary": summary,
        "status": status,
        "severity": severity,
    }


def _priority_from_severity(
    severity: GovernanceEscalationSeverity,
) -> GovernanceAIRecommendationPriority:
    if severity == GovernanceEscalationSeverity.CRITICAL:
        return GovernanceAIRecommendationPriority.CRITICAL
    if severity == GovernanceEscalationSeverity.HIGH:
        return GovernanceAIRecommendationPriority.HIGH
    if severity == GovernanceEscalationSeverity.MEDIUM:
        return GovernanceAIRecommendationPriority.MEDIUM
    return GovernanceAIRecommendationPriority.LOW


async def _visible_project_ids(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None,
) -> list[UUID]:
    if project_id is not None:
        project = await get_visible_project(session, project_id, current_user)
        return [project.id]
    rows = (await session.execute(scoped_project_query(current_user))).scalars()
    return [row.id for row in rows]


async def _load_open_escalations(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_ids: list[UUID],
) -> list[GovernanceEscalation]:
    if not project_ids:
        return []
    rows = (
        await session.execute(
            select(GovernanceEscalation).where(
                GovernanceEscalation.org_id == org_id,
                GovernanceEscalation.project_id.in_(project_ids),
                GovernanceEscalation.deleted_at.is_(None),
                GovernanceEscalation.status.in_(OPEN_ESC_STATUSES),
            )
        )
    ).scalars()
    return list(rows)


async def _covered_dependency_ids(
    session: AsyncSession,
    *,
    org_id: UUID,
    escalation_ids: list[UUID],
) -> set[UUID]:
    if not escalation_ids:
        return set()
    rows = (
        await session.execute(
            select(GovernanceRecordEvidenceLink.source_id).where(
                GovernanceRecordEvidenceLink.org_id == org_id,
                GovernanceRecordEvidenceLink.target_type == GovernanceRecordTargetType.ESCALATION,
                GovernanceRecordEvidenceLink.target_id.in_(escalation_ids),
                GovernanceRecordEvidenceLink.source_type
                == GovernanceRecordEvidenceSourceType.DEPENDENCY,
                GovernanceRecordEvidenceLink.deleted_at.is_(None),
                GovernanceRecordEvidenceLink.source_id.is_not(None),
            )
        )
    ).scalars()
    return {row for row in rows if row is not None}


async def _load_quality_risk_signals(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_ids: list[UUID],
) -> list[ProjectRiskSignal]:
    if not project_ids:
        return []
    rows = list(
        (
            await session.execute(
                select(QualitySnapshot)
                .where(
                    QualitySnapshot.org_id == org_id,
                    QualitySnapshot.project_id.in_(project_ids),
                )
                .order_by(
                    QualitySnapshot.project_id.asc(),
                    QualitySnapshot.iso_year.desc(),
                    QualitySnapshot.iso_week.desc(),
                )
            )
        ).scalars()
    )
    signals: list[ProjectRiskSignal] = []
    per_project: dict[UUID, list[QualitySnapshot]] = {}
    for row in rows:
        per_project.setdefault(row.project_id, []).append(row)
    for pid, snapshots in per_project.items():
        for snap in snapshots[:3]:
            rework = float(snap.rework_rate_pct or 0)
            accuracy = float(snap.gold_set_accuracy_pct or 100)
            if snap.has_drift_alert:
                signals.append(
                    ProjectRiskSignal(
                        category="quality",
                        provider="quality",
                        project_id=pid,
                        evidence_id=f"quality_snapshot:{snap.id}:drift",
                        title="Quality drift alert",
                        summary=(snap.drift_alert_detail or "Quality drift alert is active.")[:500],
                        score=75.0,
                        entity_type="quality_snapshot",
                        entity_id=snap.id,
                        status="drift_alert",
                        severity="high",
                    )
                )
            if rework >= 20:
                signals.append(
                    ProjectRiskSignal(
                        category="quality",
                        provider="quality",
                        project_id=pid,
                        evidence_id=f"quality_snapshot:{snap.id}:rework",
                        title="High rework rate",
                        summary=f"Rework rate is {rework:.0f}%.",
                        score=min(90.0, 50.0 + rework),
                        entity_type="quality_snapshot",
                        entity_id=snap.id,
                        status="high_rework",
                        severity="high",
                    )
                )
            if accuracy <= 85:
                signals.append(
                    ProjectRiskSignal(
                        category="quality",
                        provider="quality",
                        project_id=pid,
                        evidence_id=f"quality_snapshot:{snap.id}:accuracy",
                        title="Declining quality trend",
                        summary=f"Gold accuracy is {accuracy:.0f}%.",
                        score=min(90.0, 100.0 - accuracy),
                        entity_type="quality_snapshot",
                        entity_id=snap.id,
                        status="low_accuracy",
                        severity="medium",
                    )
                )
    return signals


async def _load_workforce_risk_signals(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_ids: list[UUID],
) -> list[ProjectRiskSignal]:
    if not project_ids:
        return []
    gaps = list(
        (
            await session.execute(
                select(CapabilityGap).where(
                    CapabilityGap.org_id == org_id,
                    CapabilityGap.project_id.in_(project_ids),
                    CapabilityGap.deleted_at.is_(None),
                    CapabilityGap.status == CapabilityGapStatus.OPEN,
                    CapabilityGap.severity.in_(
                        {CapabilityGapSeverity.HIGH, CapabilityGapSeverity.CRITICAL}
                    ),
                )
            )
        ).scalars()
    )
    util_rows = list(
        (
            await session.execute(
                select(WorkforceUtilizationSnapshot, Team.project_id)
                .join(Team, WorkforceUtilizationSnapshot.team_id == Team.id)
                .where(
                    WorkforceUtilizationSnapshot.org_id == org_id,
                    Team.project_id.in_(project_ids),
                    Team.deleted_at.is_(None),
                )
            )
        ).all()
    )
    signals: list[ProjectRiskSignal] = []
    for gap in gaps:
        signals.append(
            ProjectRiskSignal(
                category="workforce",
                provider="workforce",
                project_id=gap.project_id,
                evidence_id=f"capability_gap:{gap.id}",
                title=gap.title,
                summary=gap.detail[:500],
                score=90.0
                if gap.severity == CapabilityGapSeverity.CRITICAL
                else 75.0,
                entity_type="capability_gap",
                entity_id=gap.id,
                status=gap.status.value,
                severity=gap.severity.value,
            )
        )
    # The utilization table is team-scoped; only include records when the row evidence
    # itself contains project-specific context in tests/fixtures through matching team gaps.
    for util, util_project_id in util_rows[:50]:
        pct = float(util.utilization_pct or 0)
        if pct < 110:
            continue
        signals.append(
            ProjectRiskSignal(
                category="workforce",
                provider="workforce",
                project_id=util_project_id,
                evidence_id=f"workforce_utilization:{util.id}",
                title="Overloaded workforce capacity",
                summary=f"Team utilization is {pct:.0f}%.",
                score=min(95.0, pct - 20.0),
                entity_type="workforce_utilization",
                entity_id=util.id,
                status="overloaded",
                severity="high",
            )
        )
    return [signal for signal in signals if signal.project_id in set(project_ids)]


async def _load_delivery_risk_signals(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_ids: list[UUID],
) -> list[ProjectRiskSignal]:
    if not project_ids:
        return []
    snapshots = list(
        (
            await session.execute(
                select(ThroughputSnapshot)
                .where(
                    ThroughputSnapshot.org_id == org_id,
                    ThroughputSnapshot.project_id.in_(project_ids),
                )
                .order_by(
                    ThroughputSnapshot.project_id.asc(),
                    ThroughputSnapshot.snapshot_date.desc(),
                )
            )
        ).scalars()
    )
    by_project: dict[UUID, list[ThroughputSnapshot]] = {}
    for row in snapshots:
        by_project.setdefault(row.project_id, []).append(row)
    signals: list[ProjectRiskSignal] = []
    for pid, rows in by_project.items():
        recent = rows[:3]
        if len(recent) < 3:
            continue
        latest = float(recent[0].rolling_7day_units or recent[0].units_completed or 0)
        oldest = float(recent[-1].rolling_7day_units or recent[-1].units_completed or 0)
        if oldest <= 0:
            continue
        decline = ((oldest - latest) / oldest) * 100
        if decline < 25:
            continue
        signals.append(
            ProjectRiskSignal(
                category="delivery",
                provider="delivery",
                project_id=pid,
                evidence_id=f"throughput:{recent[0].id}:decline",
                title="Throughput deterioration",
                summary=f"Rolling throughput declined {decline:.0f}% over recent snapshots.",
                score=min(90.0, 50.0 + decline),
                entity_type="throughput",
                entity_id=recent[0].id,
                status="declining",
                severity="high",
            )
        )
    return signals


async def _load_cross_agent_signals(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_ids: list[UUID],
) -> tuple[dict[UUID, list[ProjectRiskSignal]], dict[str, str], int]:
    if not project_ids or not get_settings().governance_escalation_suggestion_cross_agent_enabled:
        return {}, {}, 0
    failures: dict[str, str] = {}
    signals: list[ProjectRiskSignal] = []
    for name, loader in (
        ("quality", _load_quality_risk_signals),
        ("workforce", _load_workforce_risk_signals),
        ("delivery", _load_delivery_risk_signals),
    ):
        try:
            signals.extend(
                await loader(session, org_id=org_id, project_ids=project_ids)
            )
        except Exception as exc:
            failures[name] = exc.__class__.__name__
            logger.exception("Governance cross-agent provider failed: %s", name)
    grouped: dict[UUID, list[ProjectRiskSignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.project_id, []).append(signal)
    return grouped, failures, len(signals)


async def _existing_suggestion_by_fingerprint(
    session: AsyncSession,
    *,
    org_id: UUID,
    fingerprint: str,
) -> GovernanceAIRecommendation | None:
    return (
        await session.execute(
            select(GovernanceAIRecommendation).where(
                GovernanceAIRecommendation.org_id == org_id,
                GovernanceAIRecommendation.trigger_fingerprint == fingerprint,
                GovernanceAIRecommendation.deleted_at.is_(None),
                GovernanceAIRecommendation.auto_detected.is_(True),
            )
        )
    ).scalar_one_or_none()


def _escalation_covers_project_risk(
    escalations: list[GovernanceEscalation],
    *,
    project_id: UUID,
    title_tokens: list[str] | None = None,
) -> bool:
    tokens = [t.lower() for t in (title_tokens or []) if t]
    for esc in escalations:
        if esc.project_id != project_id:
            continue
        if not tokens:
            return True
        title = (esc.title or "").lower()
        if any(token in title for token in tokens):
            return True
    return False


async def detect_governance_escalation_candidates(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    org_id: UUID,
    project_id: UUID | None = None,
) -> tuple[list[GovernanceEscalationCandidate], int, int, dict[str, str], int]:
    """Deterministic detector.

    Returns (candidates, suppressed_count, query_executes, provider_failures, signals_evaluated).
    """
    settings = get_settings()
    today = date.today()
    executes = 0
    suppressed = 0
    candidates: list[GovernanceEscalationCandidate] = []
    risk_signals_by_project: dict[UUID, list[ProjectRiskSignal]] = {}

    project_ids = await _visible_project_ids(session, current_user, project_id=project_id)
    executes += 1
    max_projects = int(settings.governance_escalation_suggestion_max_projects_per_scan)
    if project_id is None and max_projects > 0:
        project_ids = project_ids[:max_projects]
    if not project_ids:
        return [], 0, executes, {}, 0

    names = await load_project_names(session, set(project_ids))
    executes += 1

    open_escalations = await _load_open_escalations(
        session, org_id=org_id, project_ids=project_ids
    )
    executes += 1
    covered_deps = await _covered_dependency_ids(
        session, org_id=org_id, escalation_ids=[e.id for e in open_escalations]
    )
    executes += 1
    delivery_risk_escalation_ids = {
        e.source_id
        for e in open_escalations
        if e.source_type == GovernanceEscalationSourceType.DELIVERY_RISK and e.source_id
    }

    # --- Dependencies (blocking / overdue) ---
    deps = list(
        (
            await session.execute(
                select(ProjectDependency).where(
                    ProjectDependency.org_id == org_id,
                    ProjectDependency.project_id.in_(project_ids),
                    ProjectDependency.deleted_at.is_(None),
                    ProjectDependency.status.in_(OPEN_DEP_STATUSES),
                )
            )
        ).scalars()
    )
    executes += 1

    blocking_by_project: dict[UUID, list[ProjectDependency]] = {}
    for dep in deps:
        blocking_by_project.setdefault(dep.project_id, []).append(dep)

    overdue_threshold = int(settings.governance_escalation_suggestion_overdue_days)
    blocking_count_threshold = int(settings.governance_escalation_suggestion_blocking_count)

    for dep in deps:
        if dep.status != GovernanceDependencyStatus.BLOCKING:
            continue
        overdue = dependency_overdue_days(dep, today=today) or 0
        if overdue < overdue_threshold:
            continue
        if dep.id in covered_deps:
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        if _escalation_covers_project_risk(
            open_escalations,
            project_id=dep.project_id,
            title_tokens=[dep.title],
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue

        project_name = names.get(dep.project_id) or "project"
        evidence_id = f"dependency:{dep.id}"
        evidence_key = f"{dep.id}:{overdue // overdue_threshold}"
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=dep.project_id,
            trigger_type=GovernanceEscalationTriggerType.OVERDUE_BLOCKING_DEPENDENCY,
            entity_id=dep.id,
            evidence_key=evidence_key,
            threshold_bucket=str(overdue_threshold),
        )
        severity = (
            GovernanceEscalationSeverity.CRITICAL
            if overdue >= overdue_threshold * 2
            else GovernanceEscalationSeverity.HIGH
        )
        title = f"Escalate overdue blocking dependency: {dep.title}"
        summary = (
            f"Dependency '{dep.title}' has been blocking {project_name} for {overdue} days, "
            f"is overdue, and has no active escalation. Consider creating a "
            f"{severity.value}-severity escalation for leadership review."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.OVERDUE_BLOCKING_DEPENDENCY,
                project_id=dep.project_id,
                title=title[:200],
                summary=summary,
                severity_score=min(100.0, 60.0 + overdue),
                suggested_severity=severity,
                primary_evidence_id=evidence_id,
                evidence_ids=[evidence_id],
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=evidence_id,
                        entity_type="dependency",
                        entity_id=dep.id,
                        project_id=dep.project_id,
                        title=dep.title,
                        summary=summary,
                        status=dep.status.value,
                        severity=severity.value,
                    )
                ],
                trigger_entity_type="dependency",
                trigger_entity_id=dep.id,
                facts={"overdue_days": overdue, "threshold": overdue_threshold},
                fingerprint=fingerprint,
                priority=_priority_from_severity(severity),
            )
        )
        risk_signals_by_project.setdefault(dep.project_id, []).append(
            ProjectRiskSignal(
                category="dependency",
                provider="governance",
                project_id=dep.project_id,
                evidence_id=evidence_id,
                title=dep.title,
                summary=summary,
                score=min(100.0, 60.0 + overdue),
                entity_type="dependency",
                entity_id=dep.id,
                status=dep.status.value,
                severity=severity.value,
            )
        )

        repeated_threshold = int(
            settings.governance_escalation_suggestion_repeated_overdue_count
        )
        existing = await _existing_suggestion_by_fingerprint(
            session, org_id=org_id, fingerprint=fingerprint
        )
        executes += 1
        detection_count = 1
        if existing is not None:
            snapshot = existing.source_snapshot or {}
            detection_count = int(snapshot.get("detection_count") or 1) + 1
        if detection_count >= repeated_threshold:
            repeated_fp = _fingerprint(
                org_id=org_id,
                project_id=dep.project_id,
                trigger_type=GovernanceEscalationTriggerType.REPEATED_OVERDUE_DEPENDENCY,
                entity_id=dep.id,
                evidence_key=str(dep.id),
                threshold_bucket=f"{repeated_threshold}:{overdue_threshold}",
            )
            repeated_summary = (
                f"Dependency '{dep.title}' has remained overdue across "
                f"{detection_count} deterministic scan(s). Review whether leadership "
                "intervention is now required."
            )
            candidates.append(
                GovernanceEscalationCandidate(
                    trigger_type=GovernanceEscalationTriggerType.REPEATED_OVERDUE_DEPENDENCY,
                    project_id=dep.project_id,
                    title=f"Escalate repeatedly overdue dependency: {dep.title}"[:200],
                    summary=repeated_summary,
                    severity_score=min(100.0, 65.0 + detection_count * 8 + overdue),
                    suggested_severity=GovernanceEscalationSeverity.HIGH,
                    primary_evidence_id=evidence_id,
                    evidence_ids=[evidence_id],
                    evidence_refs=[
                        _evidence_ref(
                            evidence_id=evidence_id,
                            entity_type="dependency",
                            entity_id=dep.id,
                            project_id=dep.project_id,
                            title=dep.title,
                            summary=repeated_summary,
                            status=dep.status.value,
                            severity="high",
                        )
                    ],
                    trigger_entity_type="dependency",
                    trigger_entity_id=dep.id,
                    facts={
                        "overdue_days": overdue,
                        "detection_count": detection_count,
                        "threshold": repeated_threshold,
                    },
                    fingerprint=repeated_fp,
                    risk_categories=["dependency"],
                    signal_providers=["governance"],
                )
            )

    for pid, project_deps in blocking_by_project.items():
        blockers = [d for d in project_deps if d.status == GovernanceDependencyStatus.BLOCKING]
        if len(blockers) < blocking_count_threshold:
            continue
        overdue_or_critical = any(
            (dependency_overdue_days(d, today=today) or 0) > 0 for d in blockers
        )
        if not overdue_or_critical:
            continue
        if _escalation_covers_project_risk(
            open_escalations, project_id=pid, title_tokens=["blocking", "dependencies"]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        project_name = names.get(pid) or "project"
        evidence_ids = [f"dependency:{d.id}" for d in blockers[:10]]
        evidence_key = ",".join(sorted(str(d.id) for d in blockers[:10]))
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=pid,
            trigger_type=GovernanceEscalationTriggerType.MULTIPLE_BLOCKING_DEPENDENCIES,
            entity_id=None,
            evidence_key=hashlib.sha256(evidence_key.encode()).hexdigest()[:16],
            threshold_bucket=str(blocking_count_threshold),
        )
        title = f"Escalate multiple blocking dependencies on {project_name}"
        summary = (
            f"{project_name} has {len(blockers)} unresolved blocking dependencies "
            f"(threshold {blocking_count_threshold}). At least one is overdue. "
            "Consider a project-level high-severity escalation."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.MULTIPLE_BLOCKING_DEPENDENCIES,
                project_id=pid,
                title=title[:200],
                summary=summary,
                severity_score=min(100.0, 50.0 + len(blockers) * 10),
                suggested_severity=GovernanceEscalationSeverity.HIGH,
                primary_evidence_id=evidence_ids[0],
                evidence_ids=evidence_ids,
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=f"dependency:{d.id}",
                        entity_type="dependency",
                        entity_id=d.id,
                        project_id=pid,
                        title=d.title,
                        summary=f"Blocking dependency; status={d.status.value}",
                        status=d.status.value,
                        severity="high",
                    )
                    for d in blockers[:10]
                ],
                trigger_entity_type="project",
                trigger_entity_id=pid,
                facts={"blocking_count": len(blockers), "threshold": blocking_count_threshold},
                fingerprint=fingerprint,
            )
        )
        risk_signals_by_project.setdefault(pid, []).append(
            ProjectRiskSignal(
                category="dependency",
                provider="governance",
                project_id=pid,
                evidence_id=evidence_ids[0],
                title="Multiple blocking dependencies",
                summary=summary,
                score=min(100.0, 50.0 + len(blockers) * 10),
                entity_type="dependency",
                entity_id=blockers[0].id,
                status="blocking",
                severity="high",
            )
        )

    # --- Critical delivery risks ---
    max_age = int(settings.governance_escalation_suggestion_signal_max_age_days)
    cutoff = datetime.now(UTC) - timedelta(days=max_age)
    alerts = list(
        (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.org_id == org_id,
                    RiskAlert.project_id.in_(project_ids),
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_(OPEN_ALERT_STATUSES),
                    RiskAlert.risk_tier.in_({RiskTier.CRITICAL, RiskTier.HIGH}),
                    RiskAlert.created_at >= cutoff,
                )
            )
        ).scalars()
    )
    executes += 1
    for alert in alerts:
        if alert.id in delivery_risk_escalation_ids:
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        if _escalation_covers_project_risk(
            open_escalations, project_id=alert.project_id, title_tokens=[alert.title]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        severity = (
            GovernanceEscalationSeverity.CRITICAL
            if alert.risk_tier == RiskTier.CRITICAL
            else GovernanceEscalationSeverity.HIGH
        )
        evidence_id = f"delivery_signal:{alert.id}"
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=alert.project_id,
            trigger_type=GovernanceEscalationTriggerType.CRITICAL_DELIVERY_RISK,
            entity_id=alert.id,
            evidence_key=alert.risk_tier.value,
            threshold_bucket="critical_or_high",
        )
        project_name = names.get(alert.project_id) or "project"
        summary = (
            f"Delivery risk '{alert.title}' on {project_name} is {alert.risk_tier.value} "
            f"and remains unresolved without an equivalent open escalation."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.CRITICAL_DELIVERY_RISK,
                project_id=alert.project_id,
                title=f"Escalate delivery risk: {alert.title}"[:200],
                summary=summary,
                severity_score=95.0 if severity == GovernanceEscalationSeverity.CRITICAL else 80.0,
                suggested_severity=severity,
                primary_evidence_id=evidence_id,
                evidence_ids=[evidence_id],
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=evidence_id,
                        entity_type="delivery_signal",
                        entity_id=alert.id,
                        project_id=alert.project_id,
                        title=alert.title,
                        summary=alert.detail[:500],
                        status=alert.status.value,
                        severity=alert.risk_tier.value,
                    )
                ],
                trigger_entity_type="risk_alert",
                trigger_entity_id=alert.id,
                facts={"risk_tier": alert.risk_tier.value},
                fingerprint=fingerprint,
                priority=_priority_from_severity(severity),
            )
        )
        risk_signals_by_project.setdefault(alert.project_id, []).append(
            ProjectRiskSignal(
                category="delivery",
                provider="delivery",
                project_id=alert.project_id,
                evidence_id=evidence_id,
                title=alert.title,
                summary=alert.detail[:500],
                score=95.0 if severity == GovernanceEscalationSeverity.CRITICAL else 80.0,
                entity_type="delivery_signal",
                entity_id=alert.id,
                status=alert.status.value,
                severity=alert.risk_tier.value,
                milestone_id=alert.milestone_id,
            )
        )

    # --- Declining delivery confidence ---
    periods = int(settings.governance_escalation_suggestion_confidence_periods)
    drop_threshold = float(settings.governance_escalation_suggestion_confidence_drop)
    conf_floor = float(settings.governance_escalation_suggestion_confidence_threshold)
    conf_rows = list(
        (
            await session.execute(
                select(DeliveryConfidenceScore)
                .where(
                    DeliveryConfidenceScore.org_id == org_id,
                    DeliveryConfidenceScore.project_id.in_(project_ids),
                )
                .order_by(
                    DeliveryConfidenceScore.project_id.asc(),
                    DeliveryConfidenceScore.created_at.desc(),
                )
            )
        ).scalars()
    )
    executes += 1
    by_project_conf: dict[UUID, list[DeliveryConfidenceScore]] = {}
    for row in conf_rows:
        by_project_conf.setdefault(row.project_id, []).append(row)

    for pid, scores in by_project_conf.items():
        recent = scores[:periods]
        if len(recent) < periods:
            continue
        # recent[0] is newest
        newest = float(recent[0].score_pct)
        oldest = float(recent[-1].score_pct)
        drop = oldest - newest
        if drop < drop_threshold or newest > conf_floor:
            continue
        if _escalation_covers_project_risk(
            open_escalations, project_id=pid, title_tokens=["confidence", "delivery"]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        project_name = names.get(pid) or "project"
        evidence_id = f"trend:confidence:{pid}"
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=pid,
            trigger_type=GovernanceEscalationTriggerType.DECLINING_DELIVERY_CONFIDENCE,
            entity_id=None,
            evidence_key=f"{oldest:.0f}->{newest:.0f}",
            threshold_bucket=f"{drop_threshold}:{conf_floor}",
        )
        summary = (
            f"Delivery confidence for {project_name} declined from {oldest:.0f}% to "
            f"{newest:.0f}% over the last {periods} reporting periods "
            f"(drop {drop:.0f} pts). Consider a high-severity escalation for review."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.DECLINING_DELIVERY_CONFIDENCE,
                project_id=pid,
                title=f"Escalate declining delivery confidence on {project_name}"[:200],
                summary=summary,
                severity_score=min(100.0, 55.0 + drop),
                suggested_severity=GovernanceEscalationSeverity.HIGH,
                primary_evidence_id=evidence_id,
                evidence_ids=[evidence_id],
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=evidence_id,
                        entity_type="trend",
                        entity_id=None,
                        project_id=pid,
                        title="Delivery confidence trend",
                        summary=summary,
                        status="declining",
                        severity="high",
                    )
                ],
                trigger_entity_type="project",
                trigger_entity_id=pid,
                facts={
                    "from_pct": oldest,
                    "to_pct": newest,
                    "drop_pct": drop,
                    "periods": periods,
                },
                fingerprint=fingerprint,
            )
        )
        risk_signals_by_project.setdefault(pid, []).append(
            ProjectRiskSignal(
                category="delivery",
                provider="delivery",
                project_id=pid,
                evidence_id=evidence_id,
                title="Delivery confidence trend",
                summary=summary,
                score=min(100.0, 55.0 + drop),
                entity_type="trend",
                entity_id=None,
                status="declining",
                severity="high",
            )
        )

    # --- Overdue critical-ish actions ---
    action_overdue_days = int(settings.governance_escalation_suggestion_action_overdue_days)
    actions = list(
        (
            await session.execute(
                select(GovernanceAction).where(
                    GovernanceAction.org_id == org_id,
                    GovernanceAction.project_id.in_(project_ids),
                    GovernanceAction.deleted_at.is_(None),
                    GovernanceAction.status.in_(OPEN_ACTION_STATUSES),
                    GovernanceAction.due_date.is_not(None),
                    GovernanceAction.due_date < today,
                )
            )
        ).scalars()
    )
    executes += 1
    for action in actions:
        overdue = (today - action.due_date).days if action.due_date else 0
        if overdue < action_overdue_days:
            continue
        title_l = (action.title or "").lower()
        desc_l = (action.description or "").lower()
        critical_keywords = ("escalat", "mitigation", "critical", "risk", "blocker")
        if not any(k in title_l or k in desc_l for k in critical_keywords):
            continue
        if _escalation_covers_project_risk(
            open_escalations, project_id=action.project_id, title_tokens=[action.title]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        evidence_id = f"action:{action.id}"
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=action.project_id,
            trigger_type=GovernanceEscalationTriggerType.OVERDUE_CRITICAL_ACTION,
            entity_id=action.id,
            evidence_key=f"{overdue // action_overdue_days}",
            threshold_bucket=str(action_overdue_days),
        )
        project_name = names.get(action.project_id) or "project"
        summary = (
            f"Governance action '{action.title}' on {project_name} is {overdue} days overdue "
            f"and appears related to risk mitigation or escalation response."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.OVERDUE_CRITICAL_ACTION,
                project_id=action.project_id,
                title=f"Escalate overdue governance action: {action.title}"[:200],
                summary=summary,
                severity_score=min(100.0, 50.0 + overdue),
                suggested_severity=GovernanceEscalationSeverity.HIGH,
                primary_evidence_id=evidence_id,
                evidence_ids=[evidence_id],
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=evidence_id,
                        entity_type="action",
                        entity_id=action.id,
                        project_id=action.project_id,
                        title=action.title,
                        summary=summary,
                        status=effective_action_status(action).value,
                        severity="high",
                    )
                ],
                trigger_entity_type="action",
                trigger_entity_id=action.id,
                facts={"overdue_days": overdue},
                fingerprint=fingerprint,
            )
        )
        risk_signals_by_project.setdefault(action.project_id, []).append(
            ProjectRiskSignal(
                category="action",
                provider="governance",
                project_id=action.project_id,
                evidence_id=evidence_id,
                title=action.title,
                summary=summary,
                score=min(100.0, 50.0 + overdue),
                entity_type="action",
                entity_id=action.id,
                status=effective_action_status(action).value,
                severity="high",
            )
        )

    # --- Unresolved scope risk ---
    scope_days = int(settings.governance_escalation_suggestion_scope_pending_days)
    scope_cutoff = datetime.now(UTC) - timedelta(days=scope_days)
    scopes = list(
        (
            await session.execute(
                select(ProjectScopeState).where(
                    ProjectScopeState.org_id == org_id,
                    ProjectScopeState.project_id.in_(project_ids),
                    ProjectScopeState.deleted_at.is_(None),
                    ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
                    ProjectScopeState.updated_at <= scope_cutoff,
                )
            )
        ).scalars()
    )
    executes += 1
    for scope in scopes:
        if _escalation_covers_project_risk(
            open_escalations, project_id=scope.project_id, title_tokens=["scope"]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        evidence_id = f"scope_state:{scope.id}"
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=scope.project_id,
            trigger_type=GovernanceEscalationTriggerType.UNRESOLVED_SCOPE_RISK,
            entity_id=scope.id,
            evidence_key=scope.version_label or "",
            threshold_bucket=str(scope_days),
        )
        project_name = names.get(scope.project_id) or "project"
        summary = (
            f"Scope for {project_name} has been pending revision "
            f"({scope.version_label}) beyond {scope_days} days without resolution."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.UNRESOLVED_SCOPE_RISK,
                project_id=scope.project_id,
                title=f"Escalate unresolved scope risk on {project_name}"[:200],
                summary=summary,
                severity_score=70.0,
                suggested_severity=GovernanceEscalationSeverity.HIGH,
                primary_evidence_id=evidence_id,
                evidence_ids=[evidence_id],
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=evidence_id,
                        entity_type="scope_state",
                        entity_id=scope.id,
                        project_id=scope.project_id,
                        title=scope.version_label or "Scope",
                        summary=summary,
                        status=scope.scope_status.value,
                        severity="high",
                    )
                ],
                trigger_entity_type="scope_state",
                trigger_entity_id=scope.id,
                facts={"pending_days_threshold": scope_days},
                fingerprint=fingerprint,
            )
        )
        risk_signals_by_project.setdefault(scope.project_id, []).append(
            ProjectRiskSignal(
                category="scope",
                provider="governance",
                project_id=scope.project_id,
                evidence_id=evidence_id,
                title=scope.version_label or "Scope",
                summary=summary,
                score=70.0,
                entity_type="scope_state",
                entity_id=scope.id,
                status=scope.scope_status.value,
                severity="high",
            )
        )

    # --- Repeated mitigation failures (best-effort if data exists) ---
    fail_count = int(settings.governance_escalation_suggestion_mitigation_failure_count)
    mitigations = list(
        (
            await session.execute(
                select(MitigationRecommendation).where(
                    MitigationRecommendation.org_id == org_id,
                    MitigationRecommendation.project_id.in_(project_ids),
                    MitigationRecommendation.deleted_at.is_(None),
                    MitigationRecommendation.status == RecommendationStatus.REJECTED,
                )
            )
        ).scalars()
    )
    executes += 1
    failed_by_project: dict[UUID, list[MitigationRecommendation]] = {}
    for item in mitigations:
        failed_by_project.setdefault(item.project_id, []).append(item)
    for pid, failed in failed_by_project.items():
        if len(failed) < fail_count:
            continue
        if _escalation_covers_project_risk(
            open_escalations, project_id=pid, title_tokens=["mitigation"]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        project_name = names.get(pid) or "project"
        evidence_ids = [f"action:{m.id}" for m in failed[:5]]
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=pid,
            trigger_type=GovernanceEscalationTriggerType.REPEATED_MITIGATION_FAILURE,
            entity_id=None,
            evidence_key=str(len(failed)),
            threshold_bucket=str(fail_count),
        )
        summary = (
            f"{project_name} has {len(failed)} failed mitigation recommendations "
            f"(threshold {fail_count}). Consider escalation for leadership review."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.REPEATED_MITIGATION_FAILURE,
                project_id=pid,
                title=f"Escalate repeated mitigation failures on {project_name}"[:200],
                summary=summary,
                severity_score=min(100.0, 60.0 + len(failed) * 5),
                suggested_severity=GovernanceEscalationSeverity.HIGH,
                primary_evidence_id=evidence_ids[0],
                evidence_ids=evidence_ids,
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=f"action:{m.id}",
                        entity_type="action",
                        entity_id=m.id,
                        project_id=pid,
                        title=m.title,
                        summary="Rejected mitigation recommendation",
                        status="rejected",
                        severity="high",
                    )
                    for m in failed[:5]
                ],
                trigger_entity_type="project",
                trigger_entity_id=pid,
                facts={"failed_count": len(failed)},
                fingerprint=fingerprint,
            )
        )
        risk_signals_by_project.setdefault(pid, []).append(
            ProjectRiskSignal(
                category="mitigation",
                provider="governance",
                project_id=pid,
                evidence_id=evidence_ids[0],
                title="Repeated mitigation failures",
                summary=summary,
                score=min(100.0, 60.0 + len(failed) * 5),
                entity_type="action",
                entity_id=failed[0].id,
                status="rejected",
                severity="high",
            )
        )

    cross_agent_signals, provider_failures, cross_agent_count = await _load_cross_agent_signals(
        session, org_id=org_id, project_ids=project_ids
    )
    executes += 3 if settings.governance_escalation_suggestion_cross_agent_enabled else 0
    for pid, signals in cross_agent_signals.items():
        risk_signals_by_project.setdefault(pid, []).extend(signals)

    # --- Milestone-at-risk ---
    milestone_due_days = int(settings.governance_escalation_suggestion_milestone_due_days)
    milestone_threshold = float(
        settings.governance_escalation_suggestion_milestone_risk_threshold
    )
    milestone_cutoff = today + timedelta(days=milestone_due_days)
    milestones = list(
        (
            await session.execute(
                select(Milestone).where(
                    Milestone.org_id == org_id,
                    Milestone.project_id.in_(project_ids),
                    Milestone.deleted_at.is_(None),
                    Milestone.status.in_(
                        {
                            MilestoneStatus.PENDING,
                            MilestoneStatus.ON_TRACK,
                            MilestoneStatus.AT_RISK,
                        }
                    ),
                    Milestone.planned_date <= milestone_cutoff,
                )
            )
        ).scalars()
    )
    executes += 1
    for milestone in milestones:
        signals = _unique_risk_signals(risk_signals_by_project.get(milestone.project_id, []))
        milestone_signals = [
            signal
            for signal in signals
            if signal.milestone_id in {None, milestone.id}
        ][:10]
        blockers = len([s for s in milestone_signals if s.category == "dependency"])
        crit_actions = len([s for s in milestone_signals if s.category == "action"])
        delivery_risks = len(
            [s for s in milestone_signals if s.category == "delivery" and s.severity in {"high", "critical"}]
        )
        cross_score = sum(
            float(getattr(settings, f"governance_escalation_suggestion_{s.provider}_weight", 0.0))
            for s in milestone_signals
            if s.provider in {"quality", "workforce", "delivery"}
        )
        confidence_signals = [s for s in milestone_signals if s.evidence_id.startswith("trend:confidence")]
        confidence_drop = 10.0 if confidence_signals else 0.0
        score, reasons = _milestone_risk_score(
            days_until_due=(milestone.planned_date - today).days,
            blockers=blockers,
            critical_actions=crit_actions,
            confidence_drop=confidence_drop,
            critical_delivery_risks=delivery_risks,
            dependency_severity=sum(8.0 for s in milestone_signals if s.category == "dependency"),
            cross_agent_score=cross_score,
        )
        if milestone.status == MilestoneStatus.AT_RISK:
            score += 20.0
            reasons.append("milestone already marked at risk")
        score = min(100.0, score)
        if score < milestone_threshold:
            continue
        if _escalation_covers_project_risk(
            open_escalations,
            project_id=milestone.project_id,
            title_tokens=[milestone.name, "milestone"],
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        project_name = names.get(milestone.project_id) or "project"
        evidence_refs = [
            _evidence_ref(
                evidence_id=f"milestone:{milestone.id}",
                entity_type="milestone",
                entity_id=milestone.id,
                project_id=milestone.project_id,
                title=milestone.name,
                summary=f"Milestone status={milestone.status.value}; due={milestone.planned_date}",
                status=milestone.status.value,
                severity="high",
            )
        ]
        for signal in milestone_signals[:9]:
            evidence_refs.append(
                _evidence_ref(
                    evidence_id=signal.evidence_id,
                    entity_type=signal.entity_type,
                    entity_id=signal.entity_id,
                    project_id=signal.project_id,
                    title=signal.title,
                    summary=signal.summary,
                    status=signal.status,
                    severity=signal.severity,
                )
            )
        evidence_ids = [item["evidence_id"] for item in evidence_refs]
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=milestone.project_id,
            trigger_type=GovernanceEscalationTriggerType.MILESTONE_AT_RISK,
            entity_id=milestone.id,
            evidence_key=hashlib.sha256(
                "|".join(sorted(evidence_ids)).encode("utf-8")
            ).hexdigest()[:16],
            threshold_bucket=str(int(milestone_threshold)),
        )
        summary = (
            f"Milestone '{milestone.name}' on {project_name} is escalation-worthy "
            f"with score {score:.0f}. Reasons: {', '.join(reasons[:5])}."
        )
        severity = (
            GovernanceEscalationSeverity.CRITICAL
            if score >= 90
            else GovernanceEscalationSeverity.HIGH
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.MILESTONE_AT_RISK,
                project_id=milestone.project_id,
                title=f"Review milestone at risk: {milestone.name}"[:200],
                summary=summary,
                severity_score=score,
                suggested_severity=severity,
                primary_evidence_id=evidence_ids[0],
                evidence_ids=evidence_ids,
                evidence_refs=evidence_refs,
                trigger_entity_type="milestone",
                trigger_entity_id=milestone.id,
                facts={
                    "score": score,
                    "risk_reasons": reasons,
                    "recommended_review_action": "Review milestone recovery options and escalation owner.",
                },
                fingerprint=fingerprint,
                priority=_priority_from_severity(severity),
                risk_categories=_risk_categories(milestone_signals),
                signal_providers=_signal_providers(milestone_signals),
                linked_milestone_id=milestone.id,
            )
        )

    # --- Combined governance risk ---
    min_categories = int(settings.governance_escalation_suggestion_combined_min_categories)
    for pid, signals in risk_signals_by_project.items():
        qualifies, unique_signals, categories = _combined_risk_qualifies(
            signals, min_categories=min_categories
        )
        if not qualifies:
            continue
        if _escalation_covers_project_risk(
            open_escalations, project_id=pid, title_tokens=["combined", "governance", "risk"]
        ):
            suppressed += 1
            _inc("suggestions_suppressed_existing_escalation")
            continue
        project_name = names.get(pid) or "project"
        selected = unique_signals[:10]
        evidence_ids = [s.evidence_id for s in selected]
        fingerprint = _fingerprint(
            org_id=org_id,
            project_id=pid,
            trigger_type=GovernanceEscalationTriggerType.COMBINED_GOVERNANCE_RISK,
            entity_id=None,
            evidence_key=hashlib.sha256(
                "|".join(f"{s.category}:{s.evidence_id}" for s in selected).encode("utf-8")
            ).hexdigest()[:16],
            threshold_bucket=str(min_categories),
        )
        score = min(100.0, 55.0 + len(categories) * 10 + sum(s.score for s in selected[:4]) / 10)
        summary = (
            f"{project_name} has {len(categories)} independent governance risk categories: "
            f"{', '.join(categories)}. Review whether leadership escalation is warranted."
        )
        candidates.append(
            GovernanceEscalationCandidate(
                trigger_type=GovernanceEscalationTriggerType.COMBINED_GOVERNANCE_RISK,
                project_id=pid,
                title=f"Review combined governance risk on {project_name}"[:200],
                summary=summary,
                severity_score=score,
                suggested_severity=GovernanceEscalationSeverity.CRITICAL
                if score >= 90
                else GovernanceEscalationSeverity.HIGH,
                primary_evidence_id=evidence_ids[0],
                evidence_ids=evidence_ids,
                evidence_refs=[
                    _evidence_ref(
                        evidence_id=signal.evidence_id,
                        entity_type=signal.entity_type,
                        entity_id=signal.entity_id,
                        project_id=pid,
                        title=signal.title,
                        summary=signal.summary,
                        status=signal.status,
                        severity=signal.severity,
                    )
                    for signal in selected
                ],
                trigger_entity_type="project",
                trigger_entity_id=pid,
                facts={
                    "risk_categories": categories,
                    "signal_providers": _signal_providers(selected),
                    "minimum_categories": min_categories,
                },
                fingerprint=fingerprint,
                risk_categories=categories,
                signal_providers=_signal_providers(selected),
            )
        )

    # Bound per project
    max_per = int(settings.governance_escalation_suggestion_max_per_project)
    candidates.sort(key=lambda c: c.severity_score, reverse=True)
    bounded: list[GovernanceEscalationCandidate] = []
    per_project: dict[UUID, int] = {}
    for candidate in candidates:
        count = per_project.get(candidate.project_id, 0)
        if count >= max_per:
            continue
        per_project[candidate.project_id] = count + 1
        bounded.append(candidate)

    _inc("candidates_detected", float(len(bounded)))
    _inc("query_executes_total", float(executes))
    return bounded, suppressed, executes, provider_failures, (
        sum(len(v) for v in risk_signals_by_project.values()) + cross_agent_count
    )


def _should_suppress_existing(
    existing: GovernanceAIRecommendation,
    *,
    now: datetime,
) -> Literal["reuse", "suppress", "create"]:
    if existing.status == GovernanceAIRecommendationStatus.ACTIVE:
        return "reuse"
    if existing.status == GovernanceAIRecommendationStatus.SNOOZED:
        if existing.snoozed_until and existing.snoozed_until > now:
            return "suppress"
        return "create"
    if existing.status == GovernanceAIRecommendationStatus.DISMISSED:
        return "suppress"
    if (
        existing.acceptance_status
        and str(existing.acceptance_status.value).endswith("escalation")
        and existing.converted_escalation_id is not None
    ):
        return "suppress"
    if existing.status in {
        GovernanceAIRecommendationStatus.STALE,
        GovernanceAIRecommendationStatus.SUPERSEDED,
    }:
        return "create"
    return "suppress"


async def _persist_candidate(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    org_id: UUID,
    candidate: GovernanceEscalationCandidate,
    enrichment: dict[str, str] | None,
) -> tuple[GovernanceAIRecommendation, Literal["created", "reused", "suppressed"]]:
    now = datetime.now(UTC)
    existing = await _existing_suggestion_by_fingerprint(
        session, org_id=org_id, fingerprint=candidate.fingerprint
    )
    if existing is not None:
        decision = _should_suppress_existing(existing, now=now)
        if decision == "reuse":
            snapshot = dict(existing.source_snapshot or {})
            count = int(snapshot.get("detection_count") or 1) + 1
            snapshot["detection_count"] = count
            snapshot["latest_detected_at"] = now.isoformat()
            snapshot["risk_categories"] = candidate.risk_categories
            snapshot["signal_providers"] = candidate.signal_providers
            if candidate.linked_milestone_id:
                snapshot["linked_milestone_id"] = str(candidate.linked_milestone_id)
            existing.source_snapshot = snapshot
            existing.detected_at = now
            existing.severity_score = candidate.severity_score
            _inc("suggestions_reused")
            return existing, "reused"
        if decision == "suppress":
            return existing, "suppressed"
        existing.status = GovernanceAIRecommendationStatus.SUPERSEDED

    title = (enrichment or {}).get("title") or candidate.title
    narrative = (enrichment or {}).get("narrative") or candidate.summary
    rationale = (enrichment or {}).get("rationale") or (
        f"Deterministic trigger {candidate.trigger_type.value} with facts "
        f"{json.dumps(candidate.facts, sort_keys=True)}."
    )
    evidence_hash = hashlib.sha256(
        "|".join(sorted(candidate.evidence_ids)).encode("utf-8")
    ).hexdigest()
    row = GovernanceAIRecommendation(
        org_id=org_id,
        project_id=candidate.project_id,
        scope=GovernanceAIRecommendationScope.PROJECT,
        recommendation_type=GovernanceAIRecommendationType.ESCALATION_REQUIRED,
        title=title[:500],
        narrative=narrative[:2500],
        rationale=rationale[:1500],
        priority=candidate.priority,
        confidence=candidate.confidence,
        status=GovernanceAIRecommendationStatus.ACTIVE,
        suggested_actions=[
            {
                "label": "Create escalation",
                "description": (
                    f"Create a {candidate.suggested_severity.value}-severity escalation "
                    "for leadership review."
                ),
                "action_type": "consider_escalation",
                "target_entity_type": candidate.trigger_entity_type,
                "target_entity_id": (
                    str(candidate.trigger_entity_id) if candidate.trigger_entity_id else None
                ),
            }
        ],
        evidence_refs=candidate.evidence_refs,
        evidence_hash=evidence_hash,
        fingerprint=candidate.fingerprint,
        trigger_fingerprint=candidate.fingerprint,
        source_snapshot={
            "auto_detected": True,
            "trigger_type": candidate.trigger_type.value,
            "facts": candidate.facts,
            "suggested_severity": candidate.suggested_severity.value,
            "evidence_ids": candidate.evidence_ids,
            "source_type": "rule_based" if enrichment is None else "hybrid",
            "detection_count": 1,
            "latest_detected_at": now.isoformat(),
            "risk_categories": candidate.risk_categories,
            "signal_providers": candidate.signal_providers,
            "linked_milestone_id": str(candidate.linked_milestone_id)
            if candidate.linked_milestone_id
            else None,
        },
        model_name=None,
        model_version=None,
        prompt_version="escalation-suggestion-v1",
        generation_request_id=uuid4(),
        generated_by_user_id=current_user.id,
        auto_detected=True,
        trigger_type=candidate.trigger_type,
        trigger_entity_type=candidate.trigger_entity_type,
        trigger_entity_id=candidate.trigger_entity_id,
        severity_score=candidate.severity_score,
        detected_at=now,
        generated_at=now,
    )
    session.add(row)
    await session.flush()
    _inc("suggestions_created")
    return row, "created"


async def _optional_llm_enrichment(
    candidate: GovernanceEscalationCandidate,
) -> dict[str, str] | None:
    settings = get_settings()
    if not settings.governance_escalation_suggestion_use_llm_enrichment:
        return None
    _inc("llm_enrichment_requests")
    try:
        # Detector remains source of truth; enrichment is optional and best-effort.
        # Intentionally no chain-of-thought; fallback to deterministic text on any failure.
        from app.services.llm.client import LLMClient

        client = LLMClient()
        prompt = (
            "The system has already determined that this condition meets the "
            "escalation-suggestion threshold. Using only the supplied evidence, write a "
            "concise explanation of why escalation should be considered and what should be "
            "reviewed. Do not invent owners, dates, milestones, or facts.\n\n"
            f"Title: {candidate.title}\nSummary: {candidate.summary}\n"
            f"Facts: {json.dumps(candidate.facts)}\n"
            f"Evidence: {json.dumps(candidate.evidence_refs)[:2000]}"
        )
        # Prefer structured dict response if available; otherwise skip.
        if not hasattr(client, "generate_text"):
            return None
        text = await client.generate_text(prompt)  # type: ignore[attr-defined]
        if not text or not isinstance(text, str):
            return None
        return {
            "narrative": text[:2500],
            "rationale": "LLM-enriched explanation grounded in detector evidence.",
        }
    except Exception:
        _inc("llm_enrichment_failures")
        logger.exception("Escalation suggestion LLM enrichment failed")
        return None


def _suggestion_read(
    row: GovernanceAIRecommendation,
    *,
    project_name: str | None,
    can_generate: bool,
) -> GovernanceAIRecommendationRead:
    read = _to_read(row, project_name=project_name, can_generate=can_generate)
    snapshot = row.source_snapshot or {}
    latest_raw = snapshot.get("latest_detected_at")
    latest_detected_at = row.detected_at
    if isinstance(latest_raw, str):
        try:
            latest_detected_at = datetime.fromisoformat(latest_raw)
        except ValueError:
            latest_detected_at = row.detected_at
    linked_milestone_id = None
    if snapshot.get("linked_milestone_id"):
        try:
            linked_milestone_id = UUID(str(snapshot["linked_milestone_id"]))
        except ValueError:
            linked_milestone_id = None
    return read.model_copy(
        update={
            "auto_detected": True,
            "trigger_type": row.trigger_type.value if row.trigger_type else None,
            "trigger_entity_type": row.trigger_entity_type,
            "trigger_entity_id": row.trigger_entity_id,
            "severity_score": float(row.severity_score)
            if row.severity_score is not None
            else None,
            "detected_at": row.detected_at,
            "snoozed_until": row.snoozed_until,
            "source_type": "rule_based",
            "is_ai_generated": False,
            "can_snooze": can_generate
            and row.status == GovernanceAIRecommendationStatus.ACTIVE,
            "linked_milestone_id": linked_milestone_id,
            "risk_categories": list(snapshot.get("risk_categories") or []),
            "signal_providers": list(snapshot.get("signal_providers") or []),
            "repeated_detection_count": int(snapshot.get("detection_count") or 1),
            "latest_detected_at": latest_detected_at,
        }
    )


async def scan_governance_escalation_suggestions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    force: bool = False,
    scan_type: Literal["manual", "scheduled"] = "manual",
) -> EscalationSuggestionScanResult:
    started = perf_counter()
    _inc("scans_started")
    assert_can_generate_ai_recommendations(current_user)
    if not escalation_suggestions_enabled():
        return EscalationSuggestionScanResult(enabled=False)
    if scan_type == "scheduled" and not get_settings().governance_escalation_suggestion_scheduled_enabled:
        return EscalationSuggestionScanResult(enabled=False)

    org_id = current_user.org_id
    if org_id is None and current_user.role.value != "super_admin":
        raise ApiError(400, "ORG_REQUIRED", "Organisation context is required.")

    await log_governance_event(
        session,
        current_user,
        event_type="escalation_suggestion_scan_requested",
        org_id=org_id or UUID(int=0),
        project_id=project_id,
        source_table="governance_ai_recommendations",
        source_id=None,
        metadata={"force": force, "project_id": str(project_id) if project_id else None},
    )

    try:
        # Resolve org for super-admin scoped to a project
        if org_id is None and project_id is not None:
            project = await get_visible_project(session, project_id, current_user)
            org_id = project.org_id
        if org_id is None:
            raise ApiError(
                400,
                "ORG_REQUIRED",
                "Organisation context is required for portfolio scan.",
            )
        scan_key = (org_id, project_id)
        if scan_key in _ACTIVE_SCAN_KEYS:
            raise ApiError(409, "SCAN_IN_PROGRESS", "An escalation suggestion scan is already running.")
        _ACTIVE_SCAN_KEYS.add(scan_key)

        scan_row = GovernanceEscalationSuggestionScan(
            org_id=org_id,
            project_id=project_id,
            scan_type=scan_type,
            status=ScanStatus.RUNNING,
            requested_by_user_id=current_user.id,
        )
        session.add(scan_row)
        await session.flush()

        candidates, suppressed, executes, provider_failures, signals_evaluated = await detect_governance_escalation_candidates(
            session,
            current_user,
            org_id=org_id,
            project_id=project_id,
        )
        created_rows: list[GovernanceAIRecommendation] = []
        reused = 0
        created = 0
        llm_used = False
        for candidate in candidates:
            if created >= int(get_settings().governance_escalation_suggestion_max_created_per_scan):
                break
            enrichment = await _optional_llm_enrichment(candidate)
            if enrichment:
                llm_used = True
                await log_governance_event(
                    session,
                    current_user,
                    event_type="escalation_suggestion_enriched",
                    org_id=org_id,
                    project_id=candidate.project_id,
                    source_table="governance_ai_recommendations",
                    source_id=None,
                    metadata={
                        "trigger_type": candidate.trigger_type.value,
                        "fingerprint_prefix": candidate.fingerprint[:12],
                    },
                )
            row, outcome = await _persist_candidate(
                session,
                current_user,
                org_id=org_id,
                candidate=candidate,
                enrichment=enrichment,
            )
            if outcome == "created":
                created += 1
                created_rows.append(row)
                await log_governance_event(
                    session,
                    current_user,
                    event_type="escalation_suggestion_detected",
                    org_id=org_id,
                    project_id=candidate.project_id,
                    source_table="governance_ai_recommendations",
                    source_id=row.id,
                    metadata={
                        "trigger_type": candidate.trigger_type.value,
                        "severity_score": candidate.severity_score,
                        "evidence_count": len(candidate.evidence_ids),
                        "fingerprint_prefix": candidate.fingerprint[:12],
                        "source_type": "hybrid" if enrichment else "rule_based",
                        "llm_enrichment_used": bool(enrichment),
                    },
                )
                if candidate.priority == GovernanceAIRecommendationPriority.CRITICAL:
                    await create_governance_notification(
                        session,
                        current_user,
                        org_id=org_id,
                        title="Critical escalation suggested",
                        body=row.title,
                        source_table="governance_ai_recommendations",
                        source_row_id=row.id,
                        project_id=candidate.project_id,
                    )
            elif outcome == "reused":
                reused += 1
                created_rows.append(row)
                await log_governance_event(
                    session,
                    current_user,
                    event_type="escalation_suggestion_reused",
                    org_id=org_id,
                    project_id=candidate.project_id,
                    source_table="governance_ai_recommendations",
                    source_id=row.id,
                    metadata={
                        "trigger_type": candidate.trigger_type.value,
                        "fingerprint_prefix": candidate.fingerprint[:12],
                    },
                )

        duration_ms = round((perf_counter() - started) * 1000, 1)
        scan_row.status = ScanStatus.COMPLETED
        scan_row.completed_at = datetime.now(UTC)
        scan_row.projects_checked = len({c.project_id for c in candidates}) or (
            1 if project_id else 0
        )
        scan_row.signals_evaluated = signals_evaluated
        scan_row.suggestions_created = created
        scan_row.suggestions_refreshed = reused
        scan_row.suggestions_skipped_by_cooldown = len(candidates) - created - reused
        scan_row.suggestions_suppressed_existing_escalation = suppressed
        scan_row.provider_failures = provider_failures
        scan_row.duration_ms = duration_ms
        scan_row.result_summary = {
            "candidates_detected": len(candidates),
            "llm_enrichment_used": llm_used,
            "query_executes": executes,
        }
        await session.commit()
        names = await load_project_names(
            session, {row.project_id for row in created_rows if row.project_id}
        )
        can_generate = can_generate_ai_recommendations(current_user)
        enriched = [
            _suggestion_read(
                row,
                project_name=names.get(row.project_id) if row.project_id else None,
                can_generate=can_generate,
            )
            for row in created_rows
        ]
        _inc("scans_completed")
        _inc("scan_duration_ms_total", duration_ms)
        project_count = len({c.project_id for c in candidates}) or (
            1 if project_id else 0
        )
        _inc("projects_scanned", float(project_count))
        return EscalationSuggestionScanResult(
            suggestions=enriched,
            candidates_detected=len(candidates),
            suggestions_created=created,
            suggestions_reused=reused,
            suggestions_suppressed_existing_escalation=suppressed,
            projects_scanned=project_count,
            duration_ms=duration_ms,
            query_executes=executes,
            llm_enrichment_used=llm_used,
            enabled=True,
            signals_evaluated=signals_evaluated,
            suggestions_skipped_by_cooldown=len(candidates) - created - reused,
            provider_failures=provider_failures,
            scan_id=scan_row.id,
        )
    except Exception:
        _inc("scans_failed")
        try:
            if "scan_row" in locals():
                scan_row.status = ScanStatus.FAILED
                scan_row.completed_at = datetime.now(UTC)
                scan_row.duration_ms = round((perf_counter() - started) * 1000, 1)
                scan_row.failure_reason = "scan_failed"
                await session.commit()
            else:
                await session.rollback()
        except Exception:
            await session.rollback()
        await session.rollback()
        raise
    finally:
        if "scan_key" in locals():
            _ACTIVE_SCAN_KEYS.discard(scan_key)


async def list_escalation_suggestions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    status: GovernanceAIRecommendationStatus | None = GovernanceAIRecommendationStatus.ACTIVE,
    trigger_type: GovernanceEscalationTriggerType | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[GovernanceAIRecommendationRead]:
    assert_can_view_ai_recommendations(current_user)
    stmt = select(GovernanceAIRecommendation).where(
        GovernanceAIRecommendation.deleted_at.is_(None),
        GovernanceAIRecommendation.auto_detected.is_(True),
        GovernanceAIRecommendation.recommendation_type
        == GovernanceAIRecommendationType.ESCALATION_REQUIRED,
    )
    if current_user.org_id is not None:
        stmt = stmt.where(GovernanceAIRecommendation.org_id == current_user.org_id)
    if project_id is not None:
        await get_visible_project(session, project_id, current_user)
        stmt = stmt.where(GovernanceAIRecommendation.project_id == project_id)
    if status is not None:
        stmt = stmt.where(GovernanceAIRecommendation.status == status)
    if trigger_type is not None:
        stmt = stmt.where(GovernanceAIRecommendation.trigger_type == trigger_type)
    stmt = (
        stmt.order_by(
            GovernanceAIRecommendation.severity_score.desc().nullslast(),
            GovernanceAIRecommendation.detected_at.desc().nullslast(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = list((await session.execute(stmt)).scalars())
    names = await load_project_names(session, {r.project_id for r in rows if r.project_id})
    can_generate = can_generate_ai_recommendations(current_user)
    reads: list[GovernanceAIRecommendationRead] = []
    for row in rows:
        reads.append(
            _suggestion_read(
            row,
            project_name=names.get(row.project_id) if row.project_id else None,
            can_generate=can_generate,
        )
        )
    return reads


async def list_escalation_suggestion_scans(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    limit: int = 10,
) -> list[GovernanceEscalationSuggestionScan]:
    assert_can_view_ai_recommendations(current_user)
    stmt = select(GovernanceEscalationSuggestionScan)
    if current_user.org_id is not None:
        stmt = stmt.where(GovernanceEscalationSuggestionScan.org_id == current_user.org_id)
    if project_id is not None:
        await get_visible_project(session, project_id, current_user)
        stmt = stmt.where(GovernanceEscalationSuggestionScan.project_id == project_id)
    stmt = stmt.order_by(GovernanceEscalationSuggestionScan.started_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def run_scheduled_escalation_suggestion_scan(
    session: AsyncSession,
    current_user: CurrentUser,
) -> EscalationSuggestionScanResult:
    return await scan_governance_escalation_suggestions(
        session,
        current_user,
        scan_type="scheduled",
        force=False,
    )


async def snooze_escalation_suggestion(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    request: EscalationSuggestionSnoozeRequest,
) -> GovernanceAIRecommendationRead:
    assert_can_generate_ai_recommendations(current_user)
    row = (
        await session.execute(
            select(GovernanceAIRecommendation).where(
                GovernanceAIRecommendation.id == recommendation_id,
                GovernanceAIRecommendation.deleted_at.is_(None),
                GovernanceAIRecommendation.auto_detected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Escalation suggestion not found.")
    if current_user.org_id and row.org_id != current_user.org_id:
        raise ApiError(404, "NOT_FOUND", "Escalation suggestion not found.")
    if row.project_id:
        await get_visible_project(session, row.project_id, current_user)

    settings = get_settings()
    if request.snoozed_until is not None:
        until = request.snoozed_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
    else:
        days = request.days or int(settings.governance_escalation_suggestion_snooze_days)
        until = datetime.now(UTC) + timedelta(days=days)

    row.status = GovernanceAIRecommendationStatus.SNOOZED
    row.snoozed_until = until
    row.snooze_reason = request.reason
    await log_governance_event(
        session,
        current_user,
        event_type="escalation_suggestion_snoozed",
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendations",
        source_id=row.id,
        metadata={
            "trigger_type": row.trigger_type.value if row.trigger_type else None,
            "snoozed_until": until.isoformat(),
            "fingerprint_prefix": (row.trigger_fingerprint or "")[:12],
        },
    )
    await session.commit()
    await session.refresh(row)
    _inc("suggestions_snoozed")
    names = await load_project_names(session, {row.project_id} if row.project_id else set())
    read = _to_read(
        row,
        project_name=names.get(row.project_id) if row.project_id else None,
        can_generate=True,
    )
    return read.model_copy(
        update={
            "auto_detected": True,
            "trigger_type": row.trigger_type.value if row.trigger_type else None,
            "snoozed_until": row.snoozed_until,
            "can_snooze": False,
            "source_type": "rule_based",
            "is_ai_generated": False,
        }
    )


async def mark_project_escalation_suggestions_stale(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    exclude_ids: set[UUID] | None = None,
) -> int:
    """Cheap post-write stale marking — does not run detection."""
    stmt = (
        update(GovernanceAIRecommendation)
        .where(
            GovernanceAIRecommendation.org_id == org_id,
            GovernanceAIRecommendation.project_id == project_id,
            GovernanceAIRecommendation.deleted_at.is_(None),
            GovernanceAIRecommendation.auto_detected.is_(True),
            GovernanceAIRecommendation.recommendation_type
            == GovernanceAIRecommendationType.ESCALATION_REQUIRED,
            GovernanceAIRecommendation.status == GovernanceAIRecommendationStatus.ACTIVE,
        )
        .values(status=GovernanceAIRecommendationStatus.STALE)
    )
    if exclude_ids:
        stmt = stmt.where(GovernanceAIRecommendation.id.notin_(exclude_ids))
    result = await session.execute(stmt)
    return int(result.rowcount or 0)
