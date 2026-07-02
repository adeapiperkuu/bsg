"""AI-assisted weekly governance summary generation with evidence grounding."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.dashboard_service import get_portfolio_data
from app.agents.governance.analytics.sla import (
    dependency_overdue_days,
    effective_action_status,
)
from app.agents.governance.services.governance_service import (
    load_project_names,
    scoped_actions_query,
    scoped_dependencies_query,
    scoped_escalations_query,
    scoped_scope_states_query,
)
from app.agents.governance.services.knowledge_link_service import (
    list_approved_governance_document_refs,
)
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceEvidenceLink,
    GovernanceEvidenceSourceType,
    GovernanceScopeStatus,
    GovernanceSummaryStatus,
    GovernanceWeeklySummary,
)
from app.services.llm.client import LLMClient

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "weekly_summary.md"
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
INSUFFICIENT_EVIDENCE_MESSAGE = (
    "Not enough governance evidence is available to generate a weekly summary."
)

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


@dataclass(frozen=True, slots=True)
class SummaryEvidenceItem:
    source_type: GovernanceEvidenceSourceType
    source_id: UUID
    evidence_ref: str
    label: str
    category: str
    project_name: str | None
    detail: str


def monday_of_week(ref: date | None = None) -> date:
    today = ref or datetime.now(timezone.utc).date()
    return today - timedelta(days=today.weekday())


def has_sufficient_evidence(items: list[SummaryEvidenceItem]) -> bool:
    return len(items) > 0


def _load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _evidence_ref(source_type: GovernanceEvidenceSourceType, source_id: UUID) -> str:
    return f"{source_type.value}:{source_id}"


def _rank_projects_attention(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}

    def bump(project: str | None, points: int, reason: str) -> None:
        if not project:
            return
        entry = scores.setdefault(project, {"project": project, "score": 0, "reasons": []})
        entry["score"] += points
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    for dep in context.get("dependencies", []):
        if dep.get("status") == GovernanceDependencyStatus.BLOCKING.value:
            bump(dep.get("project_name"), 5, "blocking dependency")
        elif dep.get("overdue_days", 0) > 0:
            bump(dep.get("project_name"), 3, "overdue dependency")

    for esc in context.get("escalations", []):
        severity = esc.get("severity")
        if severity == GovernanceEscalationSeverity.CRITICAL.value:
            bump(esc.get("project_name"), 6, "critical escalation")
        elif severity == GovernanceEscalationSeverity.HIGH.value:
            bump(esc.get("project_name"), 4, "high escalation")
        elif esc.get("status") in {s.value for s in OPEN_ESCALATION_STATUSES}:
            bump(esc.get("project_name"), 2, "open escalation")

    for action in context.get("actions", []):
        if action.get("status") == GovernanceActionStatus.OVERDUE.value:
            bump(action.get("project_name"), 3, "overdue action")

    for scope in context.get("scope_states", []):
        if scope.get("scope_status") == GovernanceScopeStatus.PENDING_REVISION.value:
            bump(scope.get("project_name"), 4, "pending scope revision")

    for signal in context.get("delivery_signals", []):
        if signal.get("traffic_light") == "red":
            bump(signal.get("project_name"), 5, "critical delivery health")
        elif signal.get("traffic_light") == "yellow":
            bump(signal.get("project_name"), 2, "at-risk delivery health")

    ranked = sorted(scores.values(), key=lambda row: (-row["score"], row["project"]))
    return ranked[:10]


async def collect_weekly_summary_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    summary_week: date,
) -> tuple[list[SummaryEvidenceItem], dict[str, Any]]:
    dependencies = await scoped_dependencies_query(session, current_user)
    actions = await scoped_actions_query(session, current_user)
    escalations = await scoped_escalations_query(session, current_user)
    scope_states = await scoped_scope_states_query(session, current_user)

    project_ids = {
        *(d.project_id for d in dependencies),
        *(a.project_id for a in actions),
        *(e.project_id for e in escalations),
        *(s.project_id for s in scope_states),
    }
    project_names = await load_project_names(session, project_ids)

    evidence: list[SummaryEvidenceItem] = []
    context: dict[str, Any] = {
        "summary_week": summary_week.isoformat(),
        "dependencies": [],
        "actions": [],
        "escalations": [],
        "scope_states": [],
        "delivery_signals": [],
        "knowledge_documents": [],
    }

    for dep in dependencies:
        overdue = dependency_overdue_days(dep)
        if dep.status not in OPEN_DEPENDENCY_STATUSES and overdue <= 0:
            continue
        pname = project_names.get(dep.project_id)
        ref = _evidence_ref(GovernanceEvidenceSourceType.DEPENDENCY, dep.id)
        detail = f"status={dep.status.value}, due={dep.due_date}, overdue_days={overdue}"
        evidence.append(
            SummaryEvidenceItem(
                source_type=GovernanceEvidenceSourceType.DEPENDENCY,
                source_id=dep.id,
                evidence_ref=ref,
                label=dep.title,
                category="dependency",
                project_name=pname,
                detail=detail,
            )
        )
        context["dependencies"].append(
            {
                "evidence_ref": ref,
                "title": dep.title,
                "project_name": pname,
                "dependency_type": dep.dependency_type.value,
                "status": dep.status.value,
                "owner_id": str(dep.owner_id) if dep.owner_id else None,
                "due_date": dep.due_date.isoformat() if dep.due_date else None,
                "overdue_days": overdue,
            }
        )

    for action in actions:
        status = effective_action_status(action)
        if status not in OPEN_ACTION_STATUSES:
            continue
        pname = project_names.get(action.project_id)
        ref = _evidence_ref(GovernanceEvidenceSourceType.ACTION, action.id)
        detail = f"status={status.value}, due={action.due_date}"
        evidence.append(
            SummaryEvidenceItem(
                source_type=GovernanceEvidenceSourceType.ACTION,
                source_id=action.id,
                evidence_ref=ref,
                label=action.title,
                category="action",
                project_name=pname,
                detail=detail,
            )
        )
        context["actions"].append(
            {
                "evidence_ref": ref,
                "title": action.title,
                "project_name": pname,
                "status": status.value,
                "due_date": action.due_date.isoformat() if action.due_date else None,
            }
        )

    for esc in escalations:
        if esc.status not in OPEN_ESCALATION_STATUSES:
            continue
        pname = project_names.get(esc.project_id)
        ref = _evidence_ref(GovernanceEvidenceSourceType.ESCALATION, esc.id)
        detail = f"severity={esc.severity.value}, status={esc.status.value}"
        evidence.append(
            SummaryEvidenceItem(
                source_type=GovernanceEvidenceSourceType.ESCALATION,
                source_id=esc.id,
                evidence_ref=ref,
                label=esc.title,
                category="escalation",
                project_name=pname,
                detail=detail,
            )
        )
        context["escalations"].append(
            {
                "evidence_ref": ref,
                "title": esc.title,
                "project_name": pname,
                "severity": esc.severity.value,
                "status": esc.status.value,
                "description": esc.description,
            }
        )

    for scope in scope_states:
        if scope.scope_status == GovernanceScopeStatus.APPROVED:
            continue
        pname = project_names.get(scope.project_id)
        ref = _evidence_ref(GovernanceEvidenceSourceType.SCOPE_STATE, scope.id)
        detail = f"scope_status={scope.scope_status.value}, version={scope.version_label}"
        evidence.append(
            SummaryEvidenceItem(
                source_type=GovernanceEvidenceSourceType.SCOPE_STATE,
                source_id=scope.id,
                evidence_ref=ref,
                label=f"Scope — {pname or scope.project_id}",
                category="scope",
                project_name=pname,
                detail=detail,
            )
        )
        context["scope_states"].append(
            {
                "evidence_ref": ref,
                "project_name": pname,
                "scope_status": scope.scope_status.value,
                "version_label": scope.version_label,
                "notes": scope.notes,
            }
        )

    portfolio = await get_portfolio_data(session=session, current_user=current_user)
    for entry in portfolio.get("projects", []):
        project_id = entry.get("project_id")
        dashboard = entry.get("dashboard") or {}
        pname = None
        overview = dashboard.get("overview") or {}
        project_meta = overview.get("project") or {}
        if isinstance(project_meta, dict):
            pname = project_meta.get("name")
        if not pname and project_id:
            pname = project_names.get(UUID(str(project_id)))

        traffic = dashboard.get("traffic_light")
        confidence = dashboard.get("confidence")
        at_risk_milestones = [
            ms
            for ms in dashboard.get("milestones", [])
            if isinstance(ms, dict) and ms.get("status") == "at_risk"
        ]

        include_delivery = (
            traffic in {"yellow", "red"} or at_risk_milestones or dashboard.get("risks")
        )
        if not include_delivery:
            continue

        for risk in dashboard.get("risks", []):
            if not isinstance(risk, dict) or not risk.get("id"):
                continue
            risk_id = UUID(str(risk["id"]))
            ref = _evidence_ref(GovernanceEvidenceSourceType.DELIVERY_SIGNAL, risk_id)
            title = risk.get("title") or risk.get("alert_type") or "Delivery risk alert"
            detail = f"risk_tier={risk.get('risk_tier')}, alert_type={risk.get('alert_type')}"
            evidence.append(
                SummaryEvidenceItem(
                    source_type=GovernanceEvidenceSourceType.DELIVERY_SIGNAL,
                    source_id=risk_id,
                    evidence_ref=ref,
                    label=title,
                    category="delivery_risk",
                    project_name=pname,
                    detail=detail,
                )
            )
            context["delivery_signals"].append(
                {
                    "evidence_ref": ref,
                    "signal_type": "risk_alert",
                    "project_name": pname,
                    "title": title,
                    "risk_tier": risk.get("risk_tier"),
                    "detail": risk.get("detail"),
                }
            )

        for ms in at_risk_milestones:
            if not ms.get("id"):
                continue
            ms_id = UUID(str(ms["id"]))
            ref = _evidence_ref(GovernanceEvidenceSourceType.DELIVERY_SIGNAL, ms_id)
            title = ms.get("name") or "At-risk milestone"
            detail = f"status={ms.get('status')}, planned_date={ms.get('planned_date')}"
            evidence.append(
                SummaryEvidenceItem(
                    source_type=GovernanceEvidenceSourceType.DELIVERY_SIGNAL,
                    source_id=ms_id,
                    evidence_ref=ref,
                    label=title,
                    category="milestone_risk",
                    project_name=pname,
                    detail=detail,
                )
            )
            context["delivery_signals"].append(
                {
                    "evidence_ref": ref,
                    "signal_type": "milestone",
                    "project_name": pname,
                    "name": title,
                    "status": ms.get("status"),
                    "planned_date": ms.get("planned_date"),
                }
            )

        if traffic in {"yellow", "red"} and project_id:
            pid = UUID(str(project_id))
            ref = _evidence_ref(GovernanceEvidenceSourceType.DELIVERY_SIGNAL, pid)
            label = f"Delivery health ({traffic})"
            detail = f"confidence={confidence}, traffic_light={traffic}"
            if not any(
                item.source_id == pid and item.category == "project_health" for item in evidence
            ):
                evidence.append(
                    SummaryEvidenceItem(
                        source_type=GovernanceEvidenceSourceType.DELIVERY_SIGNAL,
                        source_id=pid,
                        evidence_ref=ref,
                        label=label,
                        category="project_health",
                        project_name=pname,
                        detail=detail,
                    )
                )
                context["delivery_signals"].append(
                    {
                        "evidence_ref": ref,
                        "signal_type": "project_health",
                        "project_name": pname,
                        "traffic_light": traffic,
                        "confidence": confidence,
                    }
                )

    knowledge_docs = await list_approved_governance_document_refs(session, current_user)
    for doc in knowledge_docs:
        ref = _evidence_ref(GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT, doc.document_id)
        evidence.append(
            SummaryEvidenceItem(
                source_type=GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT,
                source_id=doc.document_id,
                evidence_ref=ref,
                label=doc.title,
                category=doc.source_type,
                project_name=doc.project,
                detail=f"version={doc.version}, visibility={doc.visibility}",
            )
        )
        context["knowledge_documents"].append(
            {
                "evidence_ref": ref,
                "title": doc.title,
                "project": doc.project,
                "source_type": doc.source_type,
                "version": doc.version,
            }
        )

    context["projects_attention"] = _rank_projects_attention(context)
    return evidence, context


def build_template_summary(context: dict[str, Any], evidence: list[SummaryEvidenceItem]) -> str:
    """Deterministic fallback summary built only from structured context."""
    lines = [
        "## 1. Executive Overview",
        (
            f"Governance summary for week of {context.get('summary_week')}. "
            f"{len(context.get('dependencies', []))} active dependencies, "
            f"{len(context.get('actions', []))} open actions, "
            f"{len(context.get('escalations', []))} open escalations."
        ),
        "",
        "## 2. Key Governance Risks",
    ]
    if context.get("dependencies") or context.get("escalations") or context.get("scope_states"):
        for dep in context.get("dependencies", []):
            if dep.get("status") == "blocking" or dep.get("overdue_days", 0) > 0:
                lines.append(
                    f"- [{dep['evidence_ref']}] {dep['title']} ({dep.get('project_name')})"
                )
        for esc in context.get("escalations", []):
            if esc.get("severity") in {"critical", "high"}:
                lines.append(
                    f"- [{esc['evidence_ref']}] {esc['title']} ({esc.get('project_name')})"
                )
        for scope in context.get("scope_states", []):
            lines.append(
                f"- [{scope['evidence_ref']}] Scope {scope.get('scope_status')} - "
                f"{scope.get('project_name')}"
            )
    else:
        lines.append("No items in this category for the reporting week.")

    lines.extend(["", "## 3. Delivery Impact"])
    if context.get("delivery_signals"):
        for signal in context["delivery_signals"]:
            lines.append(
                f"- [{signal['evidence_ref']}] {signal.get('project_name')}: "
                f"{signal.get('signal_type')} - "
                f"{signal.get('title') or signal.get('name') or signal.get('traffic_light')}"
            )
    else:
        lines.append("No items in this category for the reporting week.")

    lines.extend(["", "## 4. Recommended Governance Actions"])
    recommendations: list[str] = []
    for dep in context.get("dependencies", []):
        if dep.get("status") == "blocking":
            recommendations.append(
                f"- Escalate blocking dependency [{dep['evidence_ref']}]: {dep['title']}"
            )
    for action in context.get("actions", []):
        if action.get("status") == "overdue":
            recommendations.append(
                f"- Complete overdue action [{action['evidence_ref']}]: {action['title']}"
            )
    for scope in context.get("scope_states", []):
        if scope.get("scope_status") == "pending_revision":
            recommendations.append(
                f"- Schedule scope review [{scope['evidence_ref']}] for {scope.get('project_name')}"
            )
    lines.extend(recommendations or ["No items in this category for the reporting week."])

    lines.extend(["", "## 5. Projects Requiring Attention"])
    attention = context.get("projects_attention") or []
    if attention:
        for row in attention:
            lines.append(f"- {row['project']} (score {row['score']}): {', '.join(row['reasons'])}")
    else:
        lines.append("No items in this category for the reporting week.")

    lines.extend(["", "## 6. Evidence Section"])
    for item in evidence:
        lines.append(
            f"- [{item.evidence_ref}] {item.category}: {item.label} - "
            f"{item.project_name or 'Portfolio'} - {item.detail}"
        )

    return "\n".join(lines)


async def _call_llm_summary(context: dict[str, Any]) -> str | None:
    settings = get_settings()
    if not (settings.llm_api_key or settings.openai_api_key):
        return None

    template = _load_prompt_template()
    context_json = json.dumps(context, default=str, indent=2)
    prompt = template.replace("{{GOVERNANCE_CONTEXT_JSON}}", context_json)

    try:
        client = LLMClient()
        response = await asyncio.wait_for(
            client.generate(prompt),
            timeout=DEFAULT_LLM_TIMEOUT_SECONDS,
        )
    except Exception:
        return None

    text = response.strip()
    return text or None


async def generate_weekly_governance_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    summary_week: date | None = None,
) -> GovernanceWeeklySummary:
    from app.agents.governance.services.governance_service import assert_can_write_governance

    assert_can_write_governance(current_user)
    week = summary_week or monday_of_week()

    evidence_items, context = await collect_weekly_summary_evidence(
        session, current_user, summary_week=week
    )
    if not has_sufficient_evidence(evidence_items):
        raise ApiError(422, "INSUFFICIENT_EVIDENCE", INSUFFICIENT_EVIDENCE_MESSAGE)

    summary_text = await _call_llm_summary(context)
    if not summary_text:
        summary_text = build_template_summary(context, evidence_items)

    org_id = current_user.org_id
    summary = GovernanceWeeklySummary(
        org_id=org_id,
        summary_week=week,
        summary_text=summary_text,
        status=GovernanceSummaryStatus.DRAFT,
        generated_by_ai=True,
    )
    session.add(summary)
    await session.flush()

    for item in evidence_items:
        session.add(
            GovernanceEvidenceLink(
                org_id=org_id,
                summary_id=summary.id,
                source_type=item.source_type,
                source_id=item.source_id,
            )
        )

    await session.commit()
    await session.refresh(summary)
    return summary


async def enrich_evidence_links(
    session: AsyncSession,
    links: list[GovernanceEvidenceLink],
    *,
    evidence_items_cache: dict[str, SummaryEvidenceItem] | None = None,
) -> list[dict[str, Any]]:
    """Resolve human-readable labels for evidence links."""
    from app.db.models import (
        DeliveryConfidenceScore,
        GovernanceAction,
        GovernanceEscalation,
        KnowledgeDocument,
        Milestone,
        Project,
        ProjectDependency,
        ProjectScopeState,
        RiskAlert,
    )

    enriched: list[dict[str, Any]] = []
    for link in links:
        label = str(link.source_id)
        detail = link.source_type.value
        project_name: str | None = None

        if link.source_type == GovernanceEvidenceSourceType.DEPENDENCY:
            row = (
                await session.execute(
                    select(ProjectDependency).where(ProjectDependency.id == link.source_id)
                )
            ).scalar_one_or_none()
            if row:
                label = row.title
                detail = f"{row.status.value}, due {row.due_date}"
                project_name = (
                    await session.execute(select(Project.name).where(Project.id == row.project_id))
                ).scalar_one_or_none()
        elif link.source_type == GovernanceEvidenceSourceType.ACTION:
            row = (
                await session.execute(
                    select(GovernanceAction).where(GovernanceAction.id == link.source_id)
                )
            ).scalar_one_or_none()
            if row:
                label = row.title
                detail = f"{row.status.value}, due {row.due_date}"
        elif link.source_type == GovernanceEvidenceSourceType.ESCALATION:
            row = (
                await session.execute(
                    select(GovernanceEscalation).where(GovernanceEscalation.id == link.source_id)
                )
            ).scalar_one_or_none()
            if row:
                label = row.title
                detail = f"{row.severity.value}, {row.status.value}"
        elif link.source_type == GovernanceEvidenceSourceType.SCOPE_STATE:
            row = (
                await session.execute(
                    select(ProjectScopeState).where(ProjectScopeState.id == link.source_id)
                )
            ).scalar_one_or_none()
            if row:
                label = f"Scope {row.scope_status.value}"
                detail = row.version_label
        elif link.source_type == GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT:
            row = (
                await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == link.source_id)
                )
            ).scalar_one_or_none()
            if row:
                label = row.title
                detail = f"{row.source_type.value} v{row.version}"
        elif link.source_type == GovernanceEvidenceSourceType.DELIVERY_SIGNAL:
            risk = (
                await session.execute(select(RiskAlert).where(RiskAlert.id == link.source_id))
            ).scalar_one_or_none()
            if risk:
                label = risk.title
                detail = f"risk_tier={risk.risk_tier.value}"
            else:
                milestone = (
                    await session.execute(select(Milestone).where(Milestone.id == link.source_id))
                ).scalar_one_or_none()
                if milestone:
                    label = milestone.name
                    detail = f"milestone {milestone.status.value}"
                else:
                    confidence = (
                        await session.execute(
                            select(DeliveryConfidenceScore).where(
                                DeliveryConfidenceScore.id == link.source_id
                            )
                        )
                    ).scalar_one_or_none()
                    if confidence:
                        label = "Delivery confidence"
                        detail = (
                            f"score_pct={confidence.score_pct}, "
                            f"status={confidence.status.value}"
                        )
                    else:
                        project = (
                            await session.execute(
                                select(Project).where(Project.id == link.source_id)
                            )
                        ).scalar_one_or_none()
                        if project:
                            label = f"Project - {project.name}"
                            detail = f"status={project.status.value}, vertical={project.vertical}"

        enriched.append(
            {
                "id": link.id,
                "org_id": link.org_id,
                "summary_id": link.summary_id,
                "charter_id": link.charter_id,
                "source_type": link.source_type.value,
                "source_id": link.source_id,
                "created_at": link.created_at,
                "label": label,
                "detail": detail,
                "project_name": project_name,
            }
        )
    return enriched


async def build_weekly_summary_read(
    session: AsyncSession,
    summary: GovernanceWeeklySummary,
):
    from app.agents.governance.schemas.governance import (
        GovernanceEvidenceLinkRead,
        GovernanceWeeklySummaryRead,
    )
    from app.agents.governance.services.governance_service import load_user_names

    evidence_rows = (
        (
            await session.execute(
                select(GovernanceEvidenceLink).where(
                    GovernanceEvidenceLink.summary_id == summary.id
                )
            )
        )
        .scalars()
        .all()
    )
    enriched = await enrich_evidence_links(session, list(evidence_rows))
    approved_by_name = None
    if summary.approved_by:
        names = await load_user_names(session, {summary.approved_by})
        approved_by_name = names.get(summary.approved_by)

    return GovernanceWeeklySummaryRead.model_validate(
        summary, from_attributes=True
    ).model_copy(
        update={
            "evidence_links": [
                GovernanceEvidenceLinkRead.model_validate(row) for row in enriched
            ],
            "approved_by_name": approved_by_name,
        }
    )
