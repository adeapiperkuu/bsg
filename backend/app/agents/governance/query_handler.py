from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from time import perf_counter
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.services.governance_service import (
    assert_can_read_governance,
    can_read_internal_governance,
)
from app.agents.governance.services.knowledge_link_service import list_approved_governance_document_refs
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AlertStatus,
    AppRole,
    CapabilityGap,
    DeliveryConfidenceScore,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceCharterStatus,
    GovernanceSummaryStatus,
    GovernanceWeeklySummary,
    Milestone,
    MilestoneStatus,
    Project,
    ProjectCharter,
    ProjectDependency,
    ProjectScopeState,
    QualitySnapshot,
    RiskAlert,
    RiskTier,
    UtilizationSnapshot,
)
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput
from app.services.scoping import get_visible_project

PROJECT_GOVERNANCE_AGENT_NAME = "project_governance_agent"
INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I do not have enough approved governance evidence to answer this confidently."
)


@dataclass
class EvidenceItem:
    source_agent: str
    source_table: str
    source_row_id: UUID
    title: str
    detail: str
    project_id: UUID | None = None
    project_name: str | None = None
    severity: int = 1
    record_type: str = "record"

    def description(self, index: int) -> str:
        project = f" | Project: {self.project_name}" if self.project_name else ""
        return f"[{index}] {self.source_agent}: {self.title}{project}. {self.detail}"

    def related_record(self, index: int) -> dict[str, object]:
        return {
            "citation": index,
            "source_agent": self.source_agent,
            "source_table": self.source_table,
            "source_row_id": str(self.source_row_id),
            "record_type": self.record_type,
            "title": self.title,
            "detail": self.detail,
            "project_id": str(self.project_id) if self.project_id else None,
            "project_name": self.project_name,
        }


def _value(value: object) -> str:
    if isinstance(value, Decimal):
        return f"{float(value):.1f}".rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _org_stmt(stmt: Select, column, current_user: CurrentUser) -> Select:
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(column == current_user.org_id)
    return stmt


def _intent(query_text: str) -> str:
    text = query_text.lower()
    if any(word in text for word in ("depend", "block", "timeline", "milestone")):
        return "dependency_risk"
    if any(word in text for word in ("scope", "charter", "change", "revision")):
        return "scope_change"
    if any(word in text for word in ("escalat", "unresolved")):
        return "escalation_status"
    if any(word in text for word in ("action", "overdue", "due")):
        return "action_status"
    if any(word in text for word in ("leadership", "attention", "top", "risk", "posture", "call")):
        return "governance_risk"
    return "general_governance"


def _matches_intent(item: EvidenceItem, intent: str) -> bool:
    haystack = f"{item.source_table} {item.title} {item.detail} {item.source_agent}".lower()
    if intent == "dependency_risk":
        return any(token in haystack for token in ("dependency", "milestone", "delivery", "blocking"))
    if intent == "scope_change":
        return any(token in haystack for token in ("scope", "charter", "revision"))
    if intent == "escalation_status":
        return "escalation" in haystack
    if intent == "action_status":
        return "action" in haystack or "overdue" in haystack
    if intent == "governance_risk":
        return item.severity >= 3
    return True


def _project_names(projects: list[Project]) -> dict[UUID, str]:
    return {project.id: project.name for project in projects}


async def _visible_projects(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID | None,
) -> list[Project]:
    if project_id:
        return [await get_visible_project(session, project_id, current_user)]
    stmt = select(Project).where(Project.deleted_at.is_(None))
    stmt = _org_stmt(stmt, Project.org_id, current_user)
    return list((await session.execute(stmt.order_by(Project.name.asc()))).scalars())


async def _collect_governance_items(
    session: AsyncSession,
    current_user: CurrentUser,
    project_ids: set[UUID],
    project_name_by_id: dict[UUID, str],
) -> list[EvidenceItem]:
    if not can_read_internal_governance(current_user):
        return []

    items: list[EvidenceItem] = []
    today = datetime.now(UTC).date()

    dep_stmt = select(ProjectDependency).where(ProjectDependency.deleted_at.is_(None))
    dep_stmt = _org_stmt(dep_stmt, ProjectDependency.org_id, current_user)
    if project_ids:
        dep_stmt = dep_stmt.where(ProjectDependency.project_id.in_(project_ids))
    deps = list((await session.execute(dep_stmt.order_by(ProjectDependency.due_date.asc()))).scalars())
    for dep in deps:
        overdue_days = (today - dep.due_date).days if dep.due_date and dep.due_date < today else 0
        is_blocking = dep.status.value == "blocking"
        if not is_blocking and overdue_days <= 0 and dep.status.value == "resolved":
            continue
        severity = 4 if is_blocking else 3 if overdue_days > 0 else 2
        detail = (
            f"Status {_value(dep.status)}, type {_value(dep.dependency_type)}, "
            f"due {_value(dep.due_date) if dep.due_date else 'not set'}"
        )
        if overdue_days > 0:
            detail += f", overdue by {overdue_days} day(s)"
        items.append(
            EvidenceItem(
                "Project Governance Agent",
                "project_dependencies",
                dep.id,
                dep.title,
                detail,
                dep.project_id,
                project_name_by_id.get(dep.project_id),
                severity,
                "dependency",
            )
        )

    esc_stmt = select(GovernanceEscalation).where(GovernanceEscalation.deleted_at.is_(None))
    esc_stmt = _org_stmt(esc_stmt, GovernanceEscalation.org_id, current_user)
    if project_ids:
        esc_stmt = esc_stmt.where(GovernanceEscalation.project_id.in_(project_ids))
    escalations = list(
        (await session.execute(esc_stmt.order_by(GovernanceEscalation.raised_at.desc()))).scalars()
    )
    for esc in escalations:
        if esc.status == GovernanceEscalationStatus.RESOLVED:
            continue
        severity = 5 if esc.severity == GovernanceEscalationSeverity.CRITICAL else 4 if esc.severity == GovernanceEscalationSeverity.HIGH else 3
        items.append(
            EvidenceItem(
                "Project Governance Agent",
                "governance_escalations",
                esc.id,
                esc.title,
                f"Severity {_value(esc.severity)}, status {_value(esc.status)}, raised {_value(esc.raised_at)}",
                esc.project_id,
                project_name_by_id.get(esc.project_id),
                severity,
                "escalation",
            )
        )

    action_stmt = select(GovernanceAction).where(GovernanceAction.deleted_at.is_(None))
    action_stmt = _org_stmt(action_stmt, GovernanceAction.org_id, current_user)
    if project_ids:
        action_stmt = action_stmt.where(GovernanceAction.project_id.in_(project_ids))
    actions = list((await session.execute(action_stmt.order_by(GovernanceAction.due_date.asc()))).scalars())
    for action in actions:
        if action.status == GovernanceActionStatus.COMPLETED:
            continue
        overdue = bool(action.due_date and action.due_date < today)
        if action.status != GovernanceActionStatus.OVERDUE and not overdue:
            continue
        items.append(
            EvidenceItem(
                "Project Governance Agent",
                "governance_actions",
                action.id,
                action.title,
                f"Status {_value(action.status)}, due {_value(action.due_date) if action.due_date else 'not set'}",
                action.project_id,
                project_name_by_id.get(action.project_id),
                3 if overdue else 2,
                "action",
            )
        )

    scope_stmt = select(ProjectScopeState).where(ProjectScopeState.deleted_at.is_(None))
    scope_stmt = _org_stmt(scope_stmt, ProjectScopeState.org_id, current_user)
    if project_ids:
        scope_stmt = scope_stmt.where(ProjectScopeState.project_id.in_(project_ids))
    scopes = list((await session.execute(scope_stmt)).scalars())
    for scope in scopes:
        if scope.scope_status.value != "pending_revision":
            continue
        items.append(
            EvidenceItem(
                "Project Governance Agent",
                "project_scope_states",
                scope.id,
                f"Pending scope revision {scope.version_label}",
                scope.notes or "Scope state is pending revision.",
                scope.project_id,
                project_name_by_id.get(scope.project_id),
                3,
                "scope_state",
            )
        )

    summary_stmt = select(GovernanceWeeklySummary).where(
        GovernanceWeeklySummary.status == GovernanceSummaryStatus.APPROVED
    )
    summary_stmt = _org_stmt(summary_stmt, GovernanceWeeklySummary.org_id, current_user)
    summaries = list(
        (await session.execute(summary_stmt.order_by(GovernanceWeeklySummary.summary_week.desc()).limit(3))).scalars()
    )
    for summary in summaries:
        items.append(
            EvidenceItem(
                "Project Governance Agent",
                "governance_weekly_summaries",
                summary.id,
                f"Weekly summary {summary.summary_week.isoformat()}",
                summary.summary_text[:280],
                None,
                None,
                2,
                "weekly_summary",
            )
        )

    charter_stmt = select(ProjectCharter).where(ProjectCharter.status == GovernanceCharterStatus.APPROVED)
    charter_stmt = _org_stmt(charter_stmt, ProjectCharter.org_id, current_user)
    if project_ids:
        charter_stmt = charter_stmt.where(ProjectCharter.project_id.in_(project_ids))
    charters = list((await session.execute(charter_stmt.order_by(ProjectCharter.updated_at.desc()).limit(8))).scalars())
    for charter in charters:
        items.append(
            EvidenceItem(
                "Project Governance Agent",
                "project_charters",
                charter.id,
                f"Project charter {charter.version}",
                charter.generated_text[:260],
                charter.project_id,
                project_name_by_id.get(charter.project_id),
                2,
                "charter",
            )
        )

    return items


async def _collect_knowledge_items(
    session: AsyncSession,
    current_user: CurrentUser,
    project_names: set[str],
) -> list[EvidenceItem]:
    refs = await list_approved_governance_document_refs(session, current_user)
    items: list[EvidenceItem] = []
    for ref in refs[:10]:
        if project_names and ref.project and ref.project not in project_names:
            continue
        items.append(
            EvidenceItem(
                "Operational Knowledge Agent",
                "knowledge_documents",
                ref.document_id,
                ref.title,
                f"Approved {ref.source_type} document, version {ref.version}, visibility {ref.visibility}",
                None,
                ref.project,
                2,
                "knowledge_document",
            )
        )
    return items


async def _collect_delivery_items(
    session: AsyncSession,
    current_user: CurrentUser,
    project_ids: set[UUID],
    project_name_by_id: dict[UUID, str],
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if not can_read_internal_governance(current_user):
        return items
    alert_stmt = select(RiskAlert).where(RiskAlert.deleted_at.is_(None), RiskAlert.status != AlertStatus.RESOLVED)
    alert_stmt = _org_stmt(alert_stmt, RiskAlert.org_id, current_user)
    if project_ids:
        alert_stmt = alert_stmt.where(RiskAlert.project_id.in_(project_ids))
    alerts = list((await session.execute(alert_stmt.order_by(RiskAlert.created_at.desc()).limit(20))).scalars())
    for alert in alerts:
        if alert.alert_type.value not in {"delivery_risk", "milestone_at_risk"}:
            continue
        severity = 5 if alert.risk_tier == RiskTier.CRITICAL else 4 if alert.risk_tier == RiskTier.HIGH else 3
        items.append(
            EvidenceItem(
                "Delivery Performance Agent",
                "risk_alerts",
                alert.id,
                alert.title,
                f"{_value(alert.risk_tier)} delivery signal: {alert.detail[:220]}",
                alert.project_id,
                project_name_by_id.get(alert.project_id),
                severity,
                "delivery_signal",
            )
        )

    ms_stmt = select(Milestone).where(Milestone.deleted_at.is_(None), Milestone.status.in_([MilestoneStatus.AT_RISK, MilestoneStatus.MISSED]))
    ms_stmt = _org_stmt(ms_stmt, Milestone.org_id, current_user)
    if project_ids:
        ms_stmt = ms_stmt.where(Milestone.project_id.in_(project_ids))
    milestones = list((await session.execute(ms_stmt.order_by(Milestone.planned_date.asc()).limit(12))).scalars())
    for milestone in milestones:
        items.append(
            EvidenceItem(
                "Delivery Performance Agent",
                "milestones",
                milestone.id,
                milestone.name,
                f"Milestone status {_value(milestone.status)}, planned {_value(milestone.planned_date)}",
                milestone.project_id,
                project_name_by_id.get(milestone.project_id),
                4 if milestone.status == MilestoneStatus.MISSED else 3,
                "milestone",
            )
        )

    confidence_stmt = select(DeliveryConfidenceScore)
    confidence_stmt = _org_stmt(confidence_stmt, DeliveryConfidenceScore.org_id, current_user)
    if project_ids:
        confidence_stmt = confidence_stmt.where(DeliveryConfidenceScore.project_id.in_(project_ids))
    scores = list((await session.execute(confidence_stmt.order_by(DeliveryConfidenceScore.created_at.desc()).limit(20))).scalars())
    seen_projects: set[UUID] = set()
    for score in scores:
        if score.project_id in seen_projects or Decimal(score.score_pct) >= Decimal("70"):
            continue
        seen_projects.add(score.project_id)
        items.append(
            EvidenceItem(
                "Delivery Performance Agent",
                "delivery_confidence_scores",
                score.id,
                "Low delivery confidence",
                f"Delivery confidence {_value(score.score_pct)}%, status {_value(score.status)}",
                score.project_id,
                project_name_by_id.get(score.project_id),
                4 if Decimal(score.score_pct) < Decimal("50") else 3,
                "delivery_confidence",
            )
        )
    return items


async def _collect_quality_items(
    session: AsyncSession,
    current_user: CurrentUser,
    project_ids: set[UUID],
    project_name_by_id: dict[UUID, str],
) -> list[EvidenceItem]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = select(QualitySnapshot).where(QualitySnapshot.has_drift_alert.is_(True))
    stmt = _org_stmt(stmt, QualitySnapshot.org_id, current_user)
    if project_ids:
        stmt = stmt.where(QualitySnapshot.project_id.in_(project_ids))
    snapshots = list((await session.execute(stmt.order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc()).limit(15))).scalars())
    return [
        EvidenceItem(
            "Quality Intelligence Agent",
            "quality_snapshots",
            snap.id,
            "Quality drift alert",
            f"Week {snap.iso_year}-W{snap.iso_week}; accuracy {_value(snap.gold_set_accuracy_pct) if snap.gold_set_accuracy_pct is not None else 'n/a'}; {snap.drift_alert_detail or 'drift detected'}",
            snap.project_id,
            project_name_by_id.get(snap.project_id),
            3,
            "quality_signal",
        )
        for snap in snapshots
    ]


async def _collect_workforce_items(
    session: AsyncSession,
    current_user: CurrentUser,
    project_ids: set[UUID],
    project_name_by_id: dict[UUID, str],
) -> list[EvidenceItem]:
    if not can_read_internal_governance(current_user):
        return []
    items: list[EvidenceItem] = []
    gap_stmt = select(CapabilityGap).where(CapabilityGap.deleted_at.is_(None), CapabilityGap.status != "resolved")
    gap_stmt = _org_stmt(gap_stmt, CapabilityGap.org_id, current_user)
    if project_ids:
        gap_stmt = gap_stmt.where(CapabilityGap.project_id.in_(project_ids))
    gaps = list((await session.execute(gap_stmt.order_by(CapabilityGap.detected_at.desc()).limit(15))).scalars())
    for gap in gaps:
        items.append(
            EvidenceItem(
                "Workforce & Capability Agent",
                "capability_gaps",
                gap.id,
                gap.title,
                f"Severity {_value(gap.severity)}, type {_value(gap.gap_type)}: {gap.detail[:220]}",
                gap.project_id,
                project_name_by_id.get(gap.project_id),
                4 if str(gap.severity) in {"high", "critical"} else 3,
                "capability_gap",
            )
        )

    util_stmt = select(UtilizationSnapshot).where(UtilizationSnapshot.deleted_at.is_(None))
    util_stmt = _org_stmt(util_stmt, UtilizationSnapshot.org_id, current_user)
    if project_ids:
        util_stmt = util_stmt.where(UtilizationSnapshot.project_id.in_(project_ids))
    util_rows = list((await session.execute(util_stmt.order_by(UtilizationSnapshot.snapshot_date.desc()).limit(20))).scalars())
    seen: set[UUID] = set()
    for util in util_rows:
        if util.project_id in seen:
            continue
        seen.add(util.project_id)
        if util.utilization_pct is None or Decimal(util.utilization_pct) < Decimal("90"):
            continue
        items.append(
            EvidenceItem(
                "Workforce & Capability Agent",
                "utilization_snapshots",
                util.id,
                "High utilization signal",
                f"Utilization {_value(util.utilization_pct)}% on {_value(util.snapshot_date)}",
                util.project_id,
                project_name_by_id.get(util.project_id),
                3,
                "utilization_signal",
            )
        )
    return items


def _build_answer(question: str, intent: str, items: list[EvidenceItem]) -> tuple[str, str, bool]:
    if not items:
        return INSUFFICIENT_EVIDENCE_MESSAGE, "low", True

    top = sorted(items, key=lambda item: item.severity, reverse=True)[:8]
    confidence = "high" if len(top) >= 4 else "medium"
    lines = [
        f"Answering from approved governance evidence for intent `{intent}`.",
        "",
        "Key findings:",
    ]
    for index, item in enumerate(top, start=1):
        project = f" ({item.project_name})" if item.project_name else ""
        lines.append(f"- {item.title}{project}: {item.detail} [{index}]")

    if intent in {"dependency_risk", "governance_risk"}:
        lines.extend(
            [
                "",
                "Recommended governance focus:",
                "- Prioritize blocking dependencies, unresolved high-severity escalations, and overdue owner actions with named owners.",
                "- Use the cited delivery, quality, and workforce signals as context only; their source agents remain the owners of those scores.",
            ]
        )
    elif intent == "scope_change":
        lines.extend(["", "Recommended governance focus:", "- Review pending scope revisions and confirm whether the latest approved charter still matches current delivery commitments."])
    elif intent == "action_status":
        lines.extend(["", "Recommended governance focus:", "- Confirm overdue action owners, due dates, and closure criteria in the next governance call."])
    elif intent == "escalation_status":
        lines.extend(["", "Recommended governance focus:", "- Confirm escalation owner, decision needed, and target resolution date for each unresolved item."])

    return "\n".join(lines), confidence, False


async def answer_governance_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
    evidence: list[EvidenceInput] | None = None,
) -> AgentQuery:
    assert_can_read_governance(current_user)
    if current_user.role == AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Ask Governance Agent is internal-only for this phase.")

    started = perf_counter()
    visible_projects = await _visible_projects(session, current_user, payload.project_id)
    project_ids = {project.id for project in visible_projects}
    project_name_by_id = _project_names(visible_projects)
    project_names = set(project_name_by_id.values())
    intent = _intent(payload.query_text)

    all_items = (
        await _collect_governance_items(session, current_user, project_ids, project_name_by_id)
        + await _collect_knowledge_items(session, current_user, project_names)
        + await _collect_delivery_items(session, current_user, project_ids, project_name_by_id)
        + await _collect_quality_items(session, current_user, project_ids, project_name_by_id)
        + await _collect_workforce_items(session, current_user, project_ids, project_name_by_id)
    )
    relevant = [item for item in all_items if _matches_intent(item, intent)]
    if not relevant and intent != "general_governance":
        relevant = sorted(all_items, key=lambda item: item.severity, reverse=True)[:6]
    ranked = sorted(relevant, key=lambda item: item.severity, reverse=True)[:12]
    answer_text, confidence, insufficient = _build_answer(payload.query_text, intent, ranked)
    cited = ranked[:8]
    source_agents = sorted({item.source_agent for item in cited})
    retrieval_params = {
        "intent": intent,
        "filters": payload.filters or {},
        "confidence_level": confidence,
        "insufficient_evidence": insufficient,
        "source_agents_used": source_agents,
        "related_records": [item.related_record(index) for index, item in enumerate(cited, start=1)],
    }

    settings = get_settings()
    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=payload.project_id,
        agent_name=PROJECT_GOVERNANCE_AGENT_NAME,
        query_text=payload.query_text,
        answer_text=answer_text,
        model_used=settings.llm_model,
        latency_ms=int((perf_counter() - started) * 1000),
        retrieval_params=retrieval_params,
    )
    session.add(query)
    await session.flush()

    seen: set[tuple[str, UUID]] = set()
    for index, item in enumerate(cited, start=1):
        key = (item.source_table, item.source_row_id)
        if key in seen:
            continue
        seen.add(key)
        session.add(
            AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description(index),
            )
        )
    return query
