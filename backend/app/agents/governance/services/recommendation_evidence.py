"""Evidence assembly for grounded Governance AI recommendations."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.analytics.sla import dependency_overdue_days, effective_action_status
from app.agents.governance.services.delivery_signals import fetch_governance_delivery_signals
from app.agents.governance.services.governance_service import (
    can_read_internal_governance,
    load_project_names,
    load_user_names,
)
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceAIRecommendationScope,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    Milestone,
    ProjectDependency,
    ProjectScopeState,
)
from app.services.scoping import get_visible_project, scoped_project_query

OPEN_DEPENDENCY_STATUSES = {
    GovernanceDependencyStatus.OPEN,
    GovernanceDependencyStatus.BLOCKING,
}
OPEN_ACTION_STATUSES = {
    GovernanceActionStatus.OPEN,
    GovernanceActionStatus.IN_PROGRESS,
    GovernanceActionStatus.OVERDUE,
}
OPEN_ESCALATION_STATUSES = {
    GovernanceEscalationStatus.OPEN,
    GovernanceEscalationStatus.IN_PROGRESS,
}

EvidenceEntityType = Literal[
    "project",
    "dependency",
    "escalation",
    "action",
    "scope_state",
    "delivery_signal",
    "trend",
    "governance_metric",
    "recent_activity",
]


class GovernanceRecommendationEvidence(BaseModel):
    evidence_id: str
    entity_type: EvidenceEntityType
    entity_id: UUID | None = None
    project_id: UUID | None = None
    title: str
    summary: str
    status: str | None = None
    severity: str | None = None
    owner_name: str | None = None
    due_date: date | None = None
    occurred_at: datetime | None = None
    visibility: Literal["internal", "client_safe"] = "internal"
    attributes: dict[str, Any] = Field(default_factory=dict)


class GovernanceRuleSignal(BaseModel):
    signal_type: str
    severity: str
    project_id: UUID | None = None
    project_name: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    candidate_message: str
    evidence_ids: list[str] = Field(default_factory=list)


class GovernanceRecommendationEvidenceBundle(BaseModel):
    scope: GovernanceAIRecommendationScope
    org_id: UUID | None
    project_id: UUID | None = None
    project_name: str | None = None
    evidence: list[GovernanceRecommendationEvidence] = Field(default_factory=list)
    signals: list[GovernanceRuleSignal] = Field(default_factory=list)
    evidence_hash: str
    owner_names: set[str] = Field(default_factory=set)
    project_names: set[str] = Field(default_factory=set)
    dates: set[str] = Field(default_factory=set)
    counts: dict[str, int] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


def _evidence_id(entity_type: str, entity_id: UUID | str | None, suffix: str = "") -> str:
    base = f"{entity_type}:{entity_id}" if entity_id is not None else f"{entity_type}:aggregate"
    return f"{base}:{suffix}" if suffix else base


def _truncate(text: str | None, limit: int = 400) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _risk_rank(item: GovernanceRecommendationEvidence) -> tuple[int, int, str]:
    severity_rank = {
        "critical": 0,
        "high": 1,
        "blocking": 1,
        "medium": 2,
        "low": 3,
        None: 4,
    }
    type_rank = {
        "escalation": 0,
        "dependency": 1,
        "action": 2,
        "delivery_signal": 3,
        "scope_state": 4,
        "trend": 5,
        "governance_metric": 6,
        "project": 7,
        "recent_activity": 8,
    }
    return (
        severity_rank.get(item.severity, 4),
        type_rank.get(item.entity_type, 9),
        item.title,
    )


def compute_evidence_hash(evidence: list[GovernanceRecommendationEvidence]) -> str:
    payload = [
        {
            "evidence_id": item.evidence_id,
            "entity_type": item.entity_type,
            "entity_id": str(item.entity_id) if item.entity_id else None,
            "project_id": str(item.project_id) if item.project_id else None,
            "title": item.title,
            "summary": item.summary,
            "status": item.status,
            "severity": item.severity,
            "owner_name": item.owner_name,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "attributes": item.attributes,
        }
        for item in sorted(evidence, key=lambda row: row.evidence_id)
    ]
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_rule_signals(
    evidence: list[GovernanceRecommendationEvidence],
    *,
    project_id: UUID | None,
    project_name: str | None,
) -> list[GovernanceRuleSignal]:
    """Deterministic candidate signals used as LLM input and fallback source."""
    by_project: dict[UUID | None, list[GovernanceRecommendationEvidence]] = {}
    for item in evidence:
        by_project.setdefault(item.project_id, []).append(item)

    signals: list[GovernanceRuleSignal] = []
    for pid, items in by_project.items():
        if project_id is not None and pid != project_id:
            continue
        blocking = [
            i
            for i in items
            if i.entity_type == "dependency" and i.status == GovernanceDependencyStatus.BLOCKING.value
        ]
        overdue_blocking = [i for i in blocking if (i.attributes or {}).get("overdue_days", 0)]
        critical_esc = [
            i
            for i in items
            if i.entity_type == "escalation"
            and i.severity == GovernanceEscalationSeverity.CRITICAL.value
            and i.status in {s.value for s in OPEN_ESCALATION_STATUSES}
        ]
        overdue_actions = [
            i
            for i in items
            if i.entity_type == "action"
            and (i.status == GovernanceActionStatus.OVERDUE.value or (i.attributes or {}).get("overdue"))
        ]
        pending_scope = [
            i
            for i in items
            if i.entity_type == "scope_state"
            and i.status == GovernanceScopeStatus.PENDING_REVISION.value
        ]
        delivery_risk = [
            i
            for i in items
            if i.entity_type == "delivery_signal"
            and (i.severity in {"high", "critical"} or (i.attributes or {}).get("traffic_light") in {"red", "yellow"})
        ]
        name = project_name if pid == project_id else (items[0].attributes.get("project_name") if items else None)
        name = name or (items[0].title if items else None)

        if critical_esc:
            signals.append(
                GovernanceRuleSignal(
                    signal_type="critical_escalations",
                    severity="critical",
                    project_id=pid,
                    project_name=name,
                    facts={"critical_count": len(critical_esc)},
                    candidate_message="Escalate critical governance decisions to leadership.",
                    evidence_ids=[i.evidence_id for i in critical_esc[:5]],
                )
            )
        elif blocking:
            signals.append(
                GovernanceRuleSignal(
                    signal_type="blocking_dependencies",
                    severity="high",
                    project_id=pid,
                    project_name=name,
                    facts={
                        "blocking_count": len(blocking),
                        "overdue_count": len(overdue_blocking),
                    },
                    candidate_message="Assign owners and resolve blocking dependencies.",
                    evidence_ids=[i.evidence_id for i in blocking[:5]],
                )
            )
        elif overdue_actions:
            signals.append(
                GovernanceRuleSignal(
                    signal_type="overdue_actions",
                    severity="high",
                    project_id=pid,
                    project_name=name,
                    facts={"overdue_count": len(overdue_actions)},
                    candidate_message="Close or re-own overdue governance actions.",
                    evidence_ids=[i.evidence_id for i in overdue_actions[:5]],
                )
            )
        elif pending_scope:
            signals.append(
                GovernanceRuleSignal(
                    signal_type="pending_scope",
                    severity="medium",
                    project_id=pid,
                    project_name=name,
                    facts={"pending_count": len(pending_scope)},
                    candidate_message="Review pending scope revision against delivery commitments.",
                    evidence_ids=[i.evidence_id for i in pending_scope[:5]],
                )
            )
        elif delivery_risk:
            signals.append(
                GovernanceRuleSignal(
                    signal_type="delivery_risk",
                    severity="high",
                    project_id=pid,
                    project_name=name,
                    facts={"signal_count": len(delivery_risk)},
                    candidate_message="Review delivery confidence and milestone risk signals.",
                    evidence_ids=[i.evidence_id for i in delivery_risk[:5]],
                )
            )
    return signals[:10]


async def build_governance_recommendation_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    org_id: UUID | None,
    project_id: UUID | None = None,
    scope: GovernanceAIRecommendationScope = GovernanceAIRecommendationScope.PROJECT,
) -> GovernanceRecommendationEvidenceBundle:
    settings = get_settings()
    max_items = max(5, min(settings.governance_ai_recommendation_max_evidence_items, 40))
    evidence: list[GovernanceRecommendationEvidence] = []
    project_name: str | None = None
    visible_project_ids: set[UUID] = set()

    if scope == GovernanceAIRecommendationScope.PROJECT:
        if project_id is None:
            raise ValueError("project_id is required for project-scoped recommendations")
        project = await get_visible_project(session, project_id, current_user)
        project_name = project.name
        visible_project_ids = {project.id}
        evidence.append(
            GovernanceRecommendationEvidence(
                evidence_id=_evidence_id("project", project.id),
                entity_type="project",
                entity_id=project.id,
                project_id=project.id,
                title=project.name,
                summary=(
                    f"Project status={project.status.value}; "
                    f"start={project.start_date.isoformat()}; "
                    f"target_end={project.target_end_date.isoformat()}"
                ),
                status=project.status.value,
                visibility="internal",
                attributes={
                    "project_name": project.name,
                    "vertical": project.vertical,
                },
            )
        )
    else:
        projects = list((await session.execute(scoped_project_query(current_user))).scalars())
        if org_id is not None:
            projects = [p for p in projects if p.org_id == org_id]
        visible_project_ids = {p.id for p in projects}
        for project in projects[:15]:
            evidence.append(
                GovernanceRecommendationEvidence(
                    evidence_id=_evidence_id("project", project.id),
                    entity_type="project",
                    entity_id=project.id,
                    project_id=project.id,
                    title=project.name,
                    summary=f"Project status={project.status.value}",
                    status=project.status.value,
                    visibility="internal",
                    attributes={"project_name": project.name},
                )
            )

    if not visible_project_ids:
        empty_hash = compute_evidence_hash([])
        return GovernanceRecommendationEvidenceBundle(
            scope=scope,
            org_id=org_id or current_user.org_id,
            project_id=project_id,
            project_name=project_name,
            evidence=[],
            signals=[],
            evidence_hash=empty_hash,
        )

    # Dependencies / actions / escalations / scope are internal-only.
    if can_read_internal_governance(current_user):
        dep_stmt = select(ProjectDependency).where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.project_id.in_(visible_project_ids),
            ProjectDependency.status.in_(tuple(OPEN_DEPENDENCY_STATUSES)),
        )
        if org_id is not None:
            dep_stmt = dep_stmt.where(ProjectDependency.org_id == org_id)
        dependencies = list((await session.execute(dep_stmt)).scalars())

        action_stmt = select(GovernanceAction).where(
            GovernanceAction.deleted_at.is_(None),
            GovernanceAction.project_id.in_(visible_project_ids),
            GovernanceAction.status.in_(tuple(OPEN_ACTION_STATUSES)),
        )
        if org_id is not None:
            action_stmt = action_stmt.where(GovernanceAction.org_id == org_id)
        actions = list((await session.execute(action_stmt)).scalars())

        esc_stmt = select(GovernanceEscalation).where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.project_id.in_(visible_project_ids),
            GovernanceEscalation.status.in_(tuple(OPEN_ESCALATION_STATUSES)),
        )
        if org_id is not None:
            esc_stmt = esc_stmt.where(GovernanceEscalation.org_id == org_id)
        escalations = list((await session.execute(esc_stmt)).scalars())

        scope_stmt = select(ProjectScopeState).where(
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.project_id.in_(visible_project_ids),
        )
        if org_id is not None:
            scope_stmt = scope_stmt.where(ProjectScopeState.org_id == org_id)
        scopes = list((await session.execute(scope_stmt)).scalars())

        owner_ids = {d.owner_id for d in dependencies if d.owner_id} | {
            a.owner_id for a in actions if a.owner_id
        }
        names = await load_user_names(session, owner_ids)
        project_names = await load_project_names(session, visible_project_ids)

        today = date.today()
        for dep in dependencies:
            overdue = dependency_overdue_days(dep, today=today)
            evidence.append(
                GovernanceRecommendationEvidence(
                    evidence_id=_evidence_id("dependency", dep.id),
                    entity_type="dependency",
                    entity_id=dep.id,
                    project_id=dep.project_id,
                    title=_truncate(dep.title, 160),
                    summary=_truncate(
                        f"{dep.dependency_type.value} dependency; status={dep.status.value}; "
                        f"owner={names.get(dep.owner_id) if dep.owner_id else 'unassigned'}; "
                        f"due={dep.due_date.isoformat() if dep.due_date else 'none'}; "
                        f"overdue_days={overdue}"
                    ),
                    status=dep.status.value,
                    severity="high" if dep.status == GovernanceDependencyStatus.BLOCKING else "medium",
                    owner_name=names.get(dep.owner_id) if dep.owner_id else None,
                    due_date=dep.due_date,
                    occurred_at=dep.updated_at,
                    visibility="internal",
                    attributes={
                        "project_name": project_names.get(dep.project_id),
                        "dependency_type": dep.dependency_type.value,
                        "overdue_days": overdue,
                    },
                )
            )

        for action in actions:
            status = effective_action_status(action, today=today)
            overdue = bool(
                action.due_date
                and action.due_date < today
                and status != GovernanceActionStatus.COMPLETED
            )
            evidence.append(
                GovernanceRecommendationEvidence(
                    evidence_id=_evidence_id("action", action.id),
                    entity_type="action",
                    entity_id=action.id,
                    project_id=action.project_id,
                    title=_truncate(action.title, 160),
                    summary=_truncate(
                        f"Action status={status.value}; "
                        f"owner={names.get(action.owner_id) if action.owner_id else 'unassigned'}; "
                        f"due={action.due_date.isoformat() if action.due_date else 'none'}"
                    ),
                    status=status.value,
                    severity="high" if overdue else "medium",
                    owner_name=names.get(action.owner_id) if action.owner_id else None,
                    due_date=action.due_date,
                    occurred_at=action.updated_at,
                    visibility="internal",
                    attributes={
                        "project_name": project_names.get(action.project_id),
                        "overdue": overdue,
                    },
                )
            )

        for esc in escalations:
            evidence.append(
                GovernanceRecommendationEvidence(
                    evidence_id=_evidence_id("escalation", esc.id),
                    entity_type="escalation",
                    entity_id=esc.id,
                    project_id=esc.project_id,
                    title=_truncate(esc.title, 160),
                    summary=_truncate(
                        f"Escalation severity={esc.severity.value}; status={esc.status.value}; "
                        f"raised_at={esc.raised_at.isoformat()}"
                    ),
                    status=esc.status.value,
                    severity=esc.severity.value,
                    occurred_at=esc.raised_at,
                    visibility="internal",
                    attributes={"project_name": project_names.get(esc.project_id)},
                )
            )

        for scope_row in scopes:
            if scope_row.scope_status == GovernanceScopeStatus.APPROVED:
                continue
            evidence.append(
                GovernanceRecommendationEvidence(
                    evidence_id=_evidence_id("scope_state", scope_row.id),
                    entity_type="scope_state",
                    entity_id=scope_row.id,
                    project_id=scope_row.project_id,
                    title=f"Scope {scope_row.version_label}",
                    summary=_truncate(
                        f"Scope status={scope_row.scope_status.value}; "
                        f"notes={scope_row.notes or 'none'}"
                    ),
                    status=scope_row.scope_status.value,
                    severity=(
                        "medium"
                        if scope_row.scope_status == GovernanceScopeStatus.PENDING_REVISION
                        else "low"
                    ),
                    occurred_at=scope_row.updated_at,
                    visibility="internal",
                    attributes={"project_name": project_names.get(scope_row.project_id)},
                )
            )

        # Delivery signals (internal only)
        signals_by_project = await fetch_governance_delivery_signals(
            session, current_user, project_ids=list(visible_project_ids)
        )
        for pid, signal in signals_by_project.items():
            dashboard = signal.get("dashboard") if isinstance(signal, dict) else None
            if not isinstance(dashboard, dict):
                continue
            traffic = dashboard.get("traffic_light")
            confidence = dashboard.get("confidence")
            if traffic is None and confidence is None:
                continue
            severity = "high" if traffic in {"red", "yellow"} else "low"
            evidence.append(
                GovernanceRecommendationEvidence(
                    evidence_id=_evidence_id("delivery_signal", pid, "latest"),
                    entity_type="delivery_signal",
                    entity_id=pid,
                    project_id=pid,
                    title="Latest delivery signal",
                    summary=_truncate(
                        f"traffic_light={traffic}; confidence={confidence}"
                    ),
                    status=str(traffic) if traffic else None,
                    severity=severity,
                    visibility="internal",
                    attributes={
                        "project_name": project_names.get(pid),
                        "traffic_light": traffic,
                        "confidence": confidence,
                    },
                )
            )

        # Milestone proximity for project scope
        if project_id is not None:
            milestones = list(
                (
                    await session.execute(
                        select(Milestone)
                        .where(
                            Milestone.project_id == project_id,
                            Milestone.deleted_at.is_(None),
                        )
                        .order_by(Milestone.planned_date.asc())
                        .limit(5)
                    )
                ).scalars()
            )
            for milestone in milestones:
                evidence.append(
                    GovernanceRecommendationEvidence(
                        evidence_id=_evidence_id("trend", milestone.id, "milestone"),
                        entity_type="trend",
                        entity_id=milestone.id,
                        project_id=project_id,
                        title=_truncate(milestone.name, 160),
                        summary=_truncate(
                            f"Milestone status={milestone.status.value}; "
                            f"target={milestone.planned_date.isoformat()}"
                        ),
                        status=milestone.status.value,
                        severity="medium",
                        due_date=milestone.planned_date,
                        visibility="internal",
                        attributes={"project_name": project_name},
                    )
                )

    # Bound and prioritize
    evidence = sorted(evidence, key=_risk_rank)[:max_items]
    signals = build_rule_signals(evidence, project_id=project_id, project_name=project_name)
    evidence_hash = compute_evidence_hash(evidence)

    owner_names = {item.owner_name for item in evidence if item.owner_name}
    project_names_set = {
        str(item.attributes.get("project_name"))
        for item in evidence
        if item.attributes.get("project_name")
    }
    if project_name:
        project_names_set.add(project_name)
    dates = set()
    for item in evidence:
        if item.due_date:
            dates.add(item.due_date.isoformat())
        if item.occurred_at:
            dates.add(item.occurred_at.date().isoformat())

    counts = {
        "evidence_items": len(evidence),
        "signals": len(signals),
        "blocking_dependencies": sum(
            1
            for i in evidence
            if i.entity_type == "dependency" and i.status == GovernanceDependencyStatus.BLOCKING.value
        ),
        "critical_escalations": sum(
            1
            for i in evidence
            if i.entity_type == "escalation" and i.severity == GovernanceEscalationSeverity.CRITICAL.value
        ),
        "overdue_actions": sum(
            1 for i in evidence if i.entity_type == "action" and (i.attributes or {}).get("overdue")
        ),
    }

    return GovernanceRecommendationEvidenceBundle(
        scope=scope,
        org_id=org_id or current_user.org_id,
        project_id=project_id,
        project_name=project_name,
        evidence=evidence,
        signals=signals,
        evidence_hash=evidence_hash,
        owner_names=owner_names,
        project_names=project_names_set,
        dates=dates,
        counts=counts,
    )


def evidence_bundle_to_prompt_json(bundle: GovernanceRecommendationEvidenceBundle) -> dict[str, Any]:
    return {
        "scope": bundle.scope.value,
        "project_id": str(bundle.project_id) if bundle.project_id else None,
        "project_name": bundle.project_name,
        "counts": bundle.counts,
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "entity_type": item.entity_type,
                "entity_id": str(item.entity_id) if item.entity_id else None,
                "project_id": str(item.project_id) if item.project_id else None,
                "title": item.title,
                "summary": item.summary,
                "status": item.status,
                "severity": item.severity,
                "owner_name": item.owner_name,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "attributes": {
                    k: v
                    for k, v in item.attributes.items()
                    if k in {"project_name", "dependency_type", "overdue_days", "traffic_light", "confidence", "overdue"}
                },
            }
            for item in bundle.evidence
        ],
    }


def source_snapshot_from_bundle(bundle: GovernanceRecommendationEvidenceBundle) -> dict[str, Any]:
    return {
        "evidence_ids": [item.evidence_id for item in bundle.evidence],
        "entity_types": sorted({item.entity_type for item in bundle.evidence}),
        "entity_ids": [
            str(item.entity_id) for item in bundle.evidence if item.entity_id is not None
        ],
        "evidence_hash": bundle.evidence_hash,
        "source_counts": bundle.counts,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
    }
