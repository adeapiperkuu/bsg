"""AI-assisted project charter generation with governance evidence grounding."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.agents.governance.analytics.sla import dependency_overdue_days, effective_action_status
from app.agents.governance.services.governance_service import (
    assert_can_read_governance,
    assert_can_write_governance,
    load_project_names,
    load_user_names,
)
from app.agents.governance.services.knowledge_link_service import (
    list_approved_governance_document_refs,
)
from app.agents.governance.timing import governance_db_timed
from app.agents.governance.timing import get_governance_timer
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    DeliveryConfidenceScore,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceCharterStatus,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationStatus,
    GovernanceEvidenceLink,
    GovernanceEvidenceSourceType,
    GovernanceScopeStatus,
    GovernanceSummaryStatus,
    GovernanceWeeklySummary,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeVisibility,
    Milestone,
    Project,
    ProjectAssignment,
    ProjectCharter,
    ProjectDependency,
    ProjectScopeState,
    RiskAlert,
)
from app.services.llm.client import LLMClient
from app.services.scoping import get_visible_project

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "project_charter.md"
DEFAULT_LLM_TIMEOUT_SECONDS = 45.0
INSUFFICIENT_CHARTER_EVIDENCE_MESSAGE = (
    "Not enough approved governance information exists to generate a Project Charter."
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
GOVERNANCE_EVIDENCE_TYPES = {
    GovernanceEvidenceSourceType.DEPENDENCY,
    GovernanceEvidenceSourceType.ESCALATION,
    GovernanceEvidenceSourceType.ACTION,
    GovernanceEvidenceSourceType.SCOPE_STATE,
    GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT,
    GovernanceEvidenceSourceType.WEEKLY_SUMMARY,
}
UNAVAILABLE = "Information not available in approved governance sources."
EVIDENCE_APPENDIX_PATTERN = re.compile(
    r"(?:\n{2,}|\A)\s*#{0,6}\s*Evidence Appendix\b[\s\S]*\Z",
    re.IGNORECASE,
)
PROJECT_CHARTER_LIST_CACHE_TTL = timedelta(seconds=60)
PROJECT_CHARTER_FIRST_PAGE_CACHE_LIMITS = frozenset({5, 10})
PROJECT_CHARTER_DEFAULT_OFFSET = 0
PROJECT_CHARTER_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class CharterEvidenceItem:
    source_type: GovernanceEvidenceSourceType
    source_id: UUID
    evidence_ref: str
    label: str
    category: str
    project_name: str | None
    detail: str


@dataclass(frozen=True)
class ProjectCharterListPage:
    items: list
    limit: int
    offset: int
    has_more: bool
    db_executes: int
    cache_hit: bool = False
    list_row_fetch_ms: float = 0.0
    enrichment_ms: float = 0.0
    include_detail: bool = True


@dataclass(frozen=True)
class ProjectChartersPanelData:
    charters: list
    selected_charter: object | None
    limit: int
    offset: int
    has_more: bool
    db_executes: int
    cache_hit: bool = False
    list_row_fetch_ms: float = 0.0
    detail_fetch_ms: float = 0.0
    enrichment_ms: float = 0.0


_project_charter_list_cache: dict[
    tuple[UUID | None, str, UUID, UUID | None, int, int, bool],
    tuple[datetime, ProjectCharterListPage],
] = {}


def _bounded_charter_limit(limit: int) -> int:
    return max(1, min(limit, PROJECT_CHARTER_MAX_LIMIT))


def _project_charter_cache_org(current_user: CurrentUser) -> UUID | None:
    return None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id


def _project_charter_cache_key(
    current_user: CurrentUser,
    *,
    project_id: UUID | None,
    limit: int,
    offset: int,
    include_detail: bool,
) -> tuple[UUID | None, str, UUID, UUID | None, int, int, bool]:
    return (
        _project_charter_cache_org(current_user),
        current_user.role.value,
        current_user.id,
        project_id,
        limit,
        offset,
        include_detail,
    )


def _copy_charter_list_page(page: ProjectCharterListPage, *, cache_hit: bool) -> ProjectCharterListPage:
    return ProjectCharterListPage(
        items=[item.model_copy(deep=True) for item in page.items],
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        db_executes=0 if cache_hit else page.db_executes,
        cache_hit=cache_hit,
        list_row_fetch_ms=0.0 if cache_hit else page.list_row_fetch_ms,
        enrichment_ms=0.0 if cache_hit else page.enrichment_ms,
        include_detail=page.include_detail,
    )


def _is_project_charter_list_cacheable(*, limit: int, offset: int) -> bool:
    return offset == PROJECT_CHARTER_DEFAULT_OFFSET and limit in PROJECT_CHARTER_FIRST_PAGE_CACHE_LIMITS


def _project_charter_cache_shape(*, project_id: UUID | None, limit: int, offset: int) -> str:
    if offset != PROJECT_CHARTER_DEFAULT_OFFSET:
        return "uncached_offset"
    if limit not in PROJECT_CHARTER_FIRST_PAGE_CACHE_LIMITS:
        return "uncached_limit"
    return "project_filtered_first_page" if project_id else "first_page"


def invalidate_project_charter_list_cache(
    *,
    org_id: UUID | None = None,
    project_id: UUID | None = None,
) -> int:
    """Clear process-local charter list cache entries affected by a committed write."""
    if org_id is None:
        keys = list(_project_charter_list_cache)
    else:
        keys = [
            key
            for key in _project_charter_list_cache
            if key[0] in {org_id, None}
            and (project_id is None or key[3] is None or key[3] == project_id)
        ]
    for key in keys:
        _project_charter_list_cache.pop(key, None)
    return len(keys)


def _load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _evidence_ref(source_type: GovernanceEvidenceSourceType, source_id: UUID) -> str:
    return f"{source_type.value}:{source_id}"


def _truncate(text: str | None, limit: int = 900) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _section_or_unavailable(lines: list[str]) -> list[str]:
    return lines if lines else [UNAVAILABLE]


def sanitize_charter_text(text: str) -> str:
    return EVIDENCE_APPENDIX_PATTERN.sub("", text).rstrip()


def _add_evidence(
    evidence: list[CharterEvidenceItem],
    *,
    source_type: GovernanceEvidenceSourceType,
    source_id: UUID,
    label: str,
    category: str,
    project_name: str | None,
    detail: str,
) -> str:
    ref = _evidence_ref(source_type, source_id)
    evidence.append(
        CharterEvidenceItem(
            source_type=source_type,
            source_id=source_id,
            evidence_ref=ref,
            label=label,
            category=category,
            project_name=project_name,
            detail=detail,
        )
    )
    return ref


async def _load_project_assignments(
    session: AsyncSession,
    project_id: UUID,
) -> list[dict[str, str | None]]:
    rows = (
        await session.execute(
            select(ProjectAssignment).where(
                ProjectAssignment.project_id == project_id,
                ProjectAssignment.is_active.is_(True),
                ProjectAssignment.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if not rows:
        return []
    user_ids = {row.user_id for row in rows}
    names = await load_user_names(session, user_ids)
    return [{"user_id": str(user_id), "name": names.get(user_id)} for user_id in user_ids]


async def collect_project_charter_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID,
    version: str,
) -> tuple[list[CharterEvidenceItem], dict[str, Any]]:
    project = await get_visible_project(session, project_id, current_user)
    project_name = project.name
    evidence: list[CharterEvidenceItem] = []
    context: dict[str, Any] = {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "vertical": project.vertical,
            "status": project.status.value,
            "start_date": project.start_date.isoformat(),
            "target_end_date": project.target_end_date.isoformat(),
            "actual_end_date": (
                project.actual_end_date.isoformat() if project.actual_end_date else None
            ),
            "daily_target_units": project.daily_target_units,
        },
        "charter": {"version": version},
        "scope": None,
        "dependencies": [],
        "actions": [],
        "escalations": [],
        "weekly_summaries": [],
        "delivery_signals": [],
        "knowledge_documents": [],
        "stakeholders": await _load_project_assignments(session, project.id),
    }

    scope = (
        await session.execute(
            select(ProjectScopeState).where(
                ProjectScopeState.project_id == project.id,
                ProjectScopeState.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if scope:
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.SCOPE_STATE,
            source_id=scope.id,
            label=f"Scope {scope.version_label}",
            category="scope_state",
            project_name=project_name,
            detail=f"scope_status={scope.scope_status.value}, version={scope.version_label}",
        )
        context["scope"] = {
            "evidence_ref": ref,
            "scope_status": scope.scope_status.value,
            "version_label": scope.version_label,
            "notes": scope.notes,
        }

    dependencies = (
        (
            await session.execute(
                select(ProjectDependency)
                .where(
                    ProjectDependency.project_id == project.id,
                    ProjectDependency.deleted_at.is_(None),
                    ProjectDependency.status.in_(OPEN_DEPENDENCY_STATUSES),
                )
                .order_by(ProjectDependency.due_date.asc())
            )
        )
        .scalars()
        .all()
    )
    for dep in dependencies:
        overdue = dependency_overdue_days(dep)
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.DEPENDENCY,
            source_id=dep.id,
            label=dep.title,
            category="dependency",
            project_name=project_name,
            detail=f"status={dep.status.value}, due={dep.due_date}, overdue_days={overdue}",
        )
        context["dependencies"].append(
            {
                "evidence_ref": ref,
                "title": dep.title,
                "description": dep.description,
                "dependency_type": dep.dependency_type.value,
                "status": dep.status.value,
                "due_date": dep.due_date.isoformat() if dep.due_date else None,
                "overdue_days": overdue,
            }
        )

    actions = (
        (
            await session.execute(
                select(GovernanceAction)
                .where(
                    GovernanceAction.project_id == project.id,
                    GovernanceAction.deleted_at.is_(None),
                )
                .order_by(GovernanceAction.due_date.asc())
            )
        )
        .scalars()
        .all()
    )
    for action in actions:
        status = effective_action_status(action)
        if status not in OPEN_ACTION_STATUSES:
            continue
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.ACTION,
            source_id=action.id,
            label=action.title,
            category="action",
            project_name=project_name,
            detail=f"status={status.value}, due={action.due_date}",
        )
        context["actions"].append(
            {
                "evidence_ref": ref,
                "title": action.title,
                "description": action.description,
                "status": status.value,
                "due_date": action.due_date.isoformat() if action.due_date else None,
            }
        )

    escalations = (
        (
            await session.execute(
                select(GovernanceEscalation)
                .where(
                    GovernanceEscalation.project_id == project.id,
                    GovernanceEscalation.deleted_at.is_(None),
                    GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
                )
                .order_by(GovernanceEscalation.raised_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for esc in escalations:
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.ESCALATION,
            source_id=esc.id,
            label=esc.title,
            category="escalation",
            project_name=project_name,
            detail=f"severity={esc.severity.value}, status={esc.status.value}",
        )
        context["escalations"].append(
            {
                "evidence_ref": ref,
                "title": esc.title,
                "description": esc.description,
                "severity": esc.severity.value,
                "status": esc.status.value,
                "raised_at": esc.raised_at.isoformat(),
            }
        )

    summaries = (
        (
            await session.execute(
                select(GovernanceWeeklySummary)
                .where(
                    GovernanceWeeklySummary.org_id == project.org_id,
                    GovernanceWeeklySummary.status == GovernanceSummaryStatus.APPROVED,
                )
                .order_by(GovernanceWeeklySummary.summary_week.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    for summary in summaries:
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.WEEKLY_SUMMARY,
            source_id=summary.id,
            label=f"Weekly summary {summary.summary_week.isoformat()}",
            category="weekly_summary",
            project_name=None,
            detail=_truncate(summary.summary_text, 240) or "approved weekly summary",
        )
        context["weekly_summaries"].append(
            {
                "evidence_ref": ref,
                "summary_week": summary.summary_week.isoformat(),
                "summary_text": _truncate(summary.summary_text, 1200),
            }
        )

    milestones = (
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project.id, Milestone.deleted_at.is_(None))
                .order_by(Milestone.planned_date.asc())
            )
        )
        .scalars()
        .all()
    )
    for milestone in milestones:
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.DELIVERY_SIGNAL,
            source_id=milestone.id,
            label=milestone.name,
            category="milestone",
            project_name=project_name,
            detail=f"status={milestone.status.value}, planned_date={milestone.planned_date}",
        )
        context["delivery_signals"].append(
            {
                "evidence_ref": ref,
                "signal_type": "milestone",
                "name": milestone.name,
                "description": milestone.description,
                "planned_date": milestone.planned_date.isoformat(),
                "actual_date": milestone.actual_date.isoformat() if milestone.actual_date else None,
                "status": milestone.status.value,
            }
        )

    confidence_rows = (
        (
            await session.execute(
                select(DeliveryConfidenceScore)
                .where(DeliveryConfidenceScore.project_id == project.id)
                .order_by(DeliveryConfidenceScore.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    for score in confidence_rows:
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.DELIVERY_SIGNAL,
            source_id=score.id,
            label="Delivery confidence",
            category="delivery_confidence",
            project_name=project_name,
            detail=f"score_pct={score.score_pct}, status={score.status.value}",
        )
        context["delivery_signals"].append(
            {
                "evidence_ref": ref,
                "signal_type": "delivery_confidence",
                "score_pct": str(score.score_pct),
                "forecast_completion_date": (
                    score.forecast_completion_date.isoformat()
                    if score.forecast_completion_date
                    else None
                ),
                "status": score.status.value,
                "created_at": score.created_at.isoformat(),
            }
        )

    risk_alerts = (
        (
            await session.execute(
                select(RiskAlert)
                .where(
                    RiskAlert.project_id == project.id,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(RiskAlert.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    for risk in risk_alerts:
        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.DELIVERY_SIGNAL,
            source_id=risk.id,
            label=risk.title,
            category="delivery_risk",
            project_name=project_name,
            detail=f"risk_tier={risk.risk_tier.value}, alert_type={risk.alert_type.value}",
        )
        context["delivery_signals"].append(
            {
                "evidence_ref": ref,
                "signal_type": "risk_alert",
                "title": risk.title,
                "detail": risk.detail,
                "risk_tier": risk.risk_tier.value,
                "alert_type": risk.alert_type.value,
            }
        )

    knowledge_refs = await list_approved_governance_document_refs(session, current_user)
    # Prefer same-project charters and related docs; then department/org examples.
    project_matched = [
        doc
        for doc in knowledge_refs
        if doc.project is not None and doc.project.casefold() == project.name.casefold()
    ]
    charter_docs = [
        doc for doc in knowledge_refs if doc.source_type == "project_charter"
    ]
    department_matched = [
        doc
        for doc in knowledge_refs
        if doc not in project_matched
        and doc.department
        and doc.department.casefold() == project.vertical.casefold()
    ]
    ranked_refs: list = []
    for bucket in (project_matched, charter_docs, department_matched, knowledge_refs):
        for doc in bucket:
            if doc not in ranked_refs:
                ranked_refs.append(doc)
    knowledge_refs = ranked_refs[:12]
    for doc_ref in knowledge_refs:
        doc = (
            await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id == doc_ref.document_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            continue
        chunk_filters = [KnowledgeDocumentChunk.document_id == doc.id]
        if doc.active_version_id:
            chunk_filters.append(KnowledgeDocumentChunk.version_id == doc.active_version_id)
        chunks = (
            (
                await session.execute(
                    select(KnowledgeDocumentChunk)
                    .where(*chunk_filters)
                    .order_by(KnowledgeDocumentChunk.chunk_index.asc())
                    .limit(4)
                )
            )
            .scalars()
            .all()
        )
        excerpts = [_truncate(chunk.chunk_text, 800) for chunk in chunks]
        excerpts = [item for item in excerpts if item]
        if not excerpts and doc.extracted_text:
            excerpts = [_truncate(doc.extracted_text, 1200) or ""]

        ref = _add_evidence(
            evidence,
            source_type=GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT,
            source_id=doc.id,
            label=doc.title,
            category=doc.source_type.value,
            project_name=doc.project,
            detail=f"version={doc.version}, visibility={doc.visibility.value}",
        )
        context["knowledge_documents"].append(
            {
                "evidence_ref": ref,
                "title": doc.title,
                "source_type": doc.source_type.value,
                "project": doc.project,
                "department": doc.department,
                "version": doc.version,
                "visibility": doc.visibility.value,
                "excerpts": excerpts,
                "is_project_charter": doc.source_type.value == "project_charter",
                "is_same_project": (
                    doc.project is not None
                    and doc.project.casefold() == project.name.casefold()
                ),
            }
        )

    # Previously approved charters for this project (organizational memory).
    prior_charters = (
        (
            await session.execute(
                select(ProjectCharter)
                .where(
                    ProjectCharter.project_id == project.id,
                    ProjectCharter.status == GovernanceCharterStatus.APPROVED,
                )
                .order_by(ProjectCharter.approved_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    context["previous_approved_charters"] = [
        {
            "charter_id": str(row.id),
            "version": row.version,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "excerpt": _truncate(sanitize_charter_text(row.generated_text), 1500),
            "knowledge_document_id": (
                str(row.knowledge_document_id) if row.knowledge_document_id else None
            ),
        }
        for row in prior_charters
    ]

    return evidence, context


def has_sufficient_charter_evidence(items: list[CharterEvidenceItem]) -> bool:
    return any(item.source_type in GOVERNANCE_EVIDENCE_TYPES for item in items)


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in _section_or_unavailable(lines))


def build_template_charter(context: dict[str, Any], evidence: list[CharterEvidenceItem]) -> str:
    project = context["project"]
    scope = context.get("scope")
    version = context.get("charter", {}).get("version", "v1")

    summary_lines: list[str] = []
    if scope:
        summary_lines.append(
            f"{project['name']} has current scope status `{scope['scope_status']}` "
            f"on {scope['version_label']} [{scope['evidence_ref']}]."
        )
    if context.get("dependencies"):
        blocking = [d for d in context["dependencies"] if d.get("status") == "blocking"]
        summary_lines.append(
            f"{len(context['dependencies'])} open dependencies are tracked"
            f"{', including ' + str(len(blocking)) + ' blocking' if blocking else ''} "
            f"[{context['dependencies'][0]['evidence_ref']}]."
        )
    if context.get("escalations"):
        summary_lines.append(
            f"{len(context['escalations'])} open escalations are active "
            f"[{context['escalations'][0]['evidence_ref']}]."
        )
    if context.get("delivery_signals"):
        summary_lines.append(
            f"Delivery context is available from {len(context['delivery_signals'])} read-only "
            f"Delivery Performance signals [{context['delivery_signals'][0]['evidence_ref']}]."
        )

    business_lines = [
        (
            f"Approved source `{doc['title']}` is available for business context "
            f"[{doc['evidence_ref']}]."
        )
        for doc in context.get("knowledge_documents", [])
    ]
    milestone_lines = [
        f"{ms['name']} is `{ms['status']}` with planned date {ms['planned_date']} "
        f"[{ms['evidence_ref']}]."
        for ms in context.get("delivery_signals", [])
        if ms.get("signal_type") == "milestone"
    ]
    confidence_lines = [
        f"Delivery confidence is {sig['score_pct']}% with status `{sig['status']}` "
        f"[{sig['evidence_ref']}]."
        for sig in context.get("delivery_signals", [])
        if sig.get("signal_type") == "delivery_confidence"
    ]
    dependency_lines = [
        f"{dep['title']} is `{dep['status']}`"
        f"{' and ' + str(dep['overdue_days']) + ' days overdue' if dep['overdue_days'] else ''} "
        f"[{dep['evidence_ref']}]."
        for dep in context.get("dependencies", [])
    ]
    escalation_lines = [
        f"{esc['title']} is `{esc['severity']}` severity and `{esc['status']}` "
        f"[{esc['evidence_ref']}]."
        for esc in context.get("escalations", [])
    ]
    risk_lines = [
        f"{sig['title']} is a `{sig['risk_tier']}` delivery risk [{sig['evidence_ref']}]."
        for sig in context.get("delivery_signals", [])
        if sig.get("signal_type") == "risk_alert"
    ]
    action_lines = [
        f"{action['title']} is `{action['status']}`"
        f"{' due ' + action['due_date'] if action.get('due_date') else ''} "
        f"[{action['evidence_ref']}]."
        for action in context.get("actions", [])
    ]
    weekly_lines = [
        f"Approved weekly summary for {summary['summary_week']} is available "
        f"[{summary['evidence_ref']}]."
        for summary in context.get("weekly_summaries", [])
    ]

    lines = [
        "## Executive Summary",
        *_section_or_unavailable(summary_lines),
        "",
        "## Business Objectives",
        _bullet(business_lines),
        "",
        "## Scope",
        "### In Scope",
        _bullet(
            [
                scope["notes"] + f" [{scope['evidence_ref']}]"
                for scope in [scope]
                if scope and scope.get("notes")
            ]
        ),
        "",
        "### Out of Scope",
        UNAVAILABLE,
        "",
        "### Current Scope Status",
        (
            f"{scope['scope_status']} [{scope['evidence_ref']}]"
            if scope
            else UNAVAILABLE
        ),
        "",
        "### Version",
        (f"{scope['version_label']} [{scope['evidence_ref']}]" if scope else UNAVAILABLE),
        "",
        "## Deliverables",
        _bullet(business_lines[:5]),
        "",
        "## Timeline",
        _bullet(milestone_lines + confidence_lines),
        "",
        "## Governance Structure",
        _bullet(action_lines + weekly_lines),
        "",
        "## Dependencies",
        _bullet(dependency_lines),
        "",
        "## Risks & Escalations",
        _bullet(escalation_lines + risk_lines),
        "",
        "## Assumptions",
        _bullet(
            [
                (
                    "The current scope version remains the operating baseline "
                    f"[{scope['evidence_ref']}]."
                )
                for scope in [scope]
                if scope and scope.get("scope_status") == GovernanceScopeStatus.APPROVED.value
            ]
        ),
        "",
        "## Constraints",
        _bullet(
            [
                *[
                    f"Blocking dependency: {dep['title']} [{dep['evidence_ref']}]."
                    for dep in context.get("dependencies", [])
                    if dep.get("status") == GovernanceDependencyStatus.BLOCKING.value
                ],
                *risk_lines,
            ]
        ),
        "",
        "## Communication Plan",
        _bullet(weekly_lines),
        "",
        "## Approval Section",
        "- Generated by: AI Project Governance Agent",
        "- Reviewed by: (pending)",
        "- Approved by: (pending)",
        "- Approval date: (pending)",
        f"- Version: {version}",
    ]
    return "\n".join(lines)


async def _call_llm_charter(context: dict[str, Any]) -> str | None:
    settings = get_settings()
    if not (settings.llm_api_key or settings.openai_api_key):
        return None

    prompt = _load_prompt_template().replace(
        "{{CHARTER_CONTEXT_JSON}}",
        json.dumps(context, default=str, indent=2),
    )
    try:
        response = await asyncio.wait_for(
            LLMClient().generate(prompt),
            timeout=DEFAULT_LLM_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    text = response.strip()
    return text or None


def _grounding_ok(text: str, evidence: list[CharterEvidenceItem]) -> bool:
    known_refs = {item.evidence_ref for item in evidence}
    bracket_refs = set(re.findall(r"\[([a-z_]+:[0-9a-fA-F-]{32,36})\]", text))
    if not bracket_refs:
        return False
    return bracket_refs.issubset(known_refs)


async def _next_charter_version(
    session: AsyncSession,
    project_id: UUID,
) -> tuple[str, ProjectCharter | None]:
    rows = (
        (
            await session.execute(
                select(ProjectCharter)
                .where(ProjectCharter.project_id == project_id)
                .order_by(ProjectCharter.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    latest = rows[0] if rows else None
    highest = 0
    for row in rows:
        match = re.match(r"^v(\d+)$", row.version.strip().lower())
        if match:
            highest = max(highest, int(match.group(1)))
    return f"v{highest + 1}", latest


def _charter_access_stmt(current_user: CurrentUser, *, for_mutation: bool = False):
    stmt = select(ProjectCharter)
    if for_mutation:
        assert_can_write_governance(current_user)
        if current_user.role != AppRole.SUPER_ADMIN:
            stmt = stmt.where(ProjectCharter.org_id == current_user.org_id)
        return stmt

    assert_can_read_governance(current_user)
    if current_user.role == AppRole.SUPER_ADMIN:
        return stmt
    if current_user.role == AppRole.DELIVERY_MANAGER:
        return stmt.where(ProjectCharter.org_id == current_user.org_id)
    if current_user.role == AppRole.BSG_LEADERSHIP:
        return stmt.where(
            ProjectCharter.org_id == current_user.org_id,
            ProjectCharter.status == GovernanceCharterStatus.APPROVED,
        )
    return stmt.where(
        ProjectCharter.org_id == current_user.org_id,
        ProjectCharter.status == GovernanceCharterStatus.APPROVED,
        ProjectCharter.visibility == KnowledgeVisibility.CLIENT_SAFE,
        ProjectCharter.project_id.in_(
            select(ProjectAssignment.project_id).where(
                ProjectAssignment.user_id == current_user.id,
                ProjectAssignment.is_active.is_(True),
                ProjectAssignment.deleted_at.is_(None),
            )
        ),
    )


async def list_project_charters(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ProjectCharter]:
    stmt = _charter_access_stmt(current_user)
    if project_id:
        await get_visible_project(session, project_id, current_user)
        stmt = stmt.where(ProjectCharter.project_id == project_id)
    stmt = stmt.order_by(ProjectCharter.created_at.desc()).limit(_bounded_charter_limit(limit))
    if offset > 0:
        stmt = stmt.offset(offset)
    return list((await session.execute(stmt)).scalars())


async def list_project_charters_page(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    limit: int = 10,
    offset: int = 0,
    include_detail: bool = True,
) -> ProjectCharterListPage:
    limit = _bounded_charter_limit(limit)
    offset = max(0, offset)
    cacheable = _is_project_charter_list_cacheable(limit=limit, offset=offset)
    cache_shape = _project_charter_cache_shape(project_id=project_id, limit=limit, offset=offset)
    timer = get_governance_timer()
    cache_key = _project_charter_cache_key(
        current_user,
        project_id=project_id,
        limit=limit,
        offset=offset,
        include_detail=include_detail,
    )
    now = datetime.now(timezone.utc)

    if cacheable:
        cached = _project_charter_list_cache.get(cache_key)
        if cached and now - cached[0] < PROJECT_CHARTER_LIST_CACHE_TTL:
            if timer is not None:
                timer.record_meta(
                    execute_count=0,
                    cache_hit=True,
                    limit=limit,
                    offset=offset,
                    cache_eligible=True,
                    cache_shape=cache_shape,
                    filtered=project_id is not None,
                    cache_scope="user_access",
                    project_id=str(project_id) if project_id else None,
                    list_row_fetch_ms=0.0,
                    enrichment_ms=0.0,
                    returned_row_count=len(cached[1].items),
                )
            return _copy_charter_list_page(cached[1], cache_hit=True)
        if cached:
            _project_charter_list_cache.pop(cache_key, None)

    db_executes = 0
    stmt = _charter_access_stmt(current_user)
    known_project_names: dict[UUID, str] = {}
    if project_id:
        project = await get_visible_project(session, project_id, current_user)
        db_executes += 1
        known_project_names[project.id] = project.name
        stmt = stmt.where(ProjectCharter.project_id == project_id)
    if not include_detail:
        stmt = stmt.options(
            load_only(
                ProjectCharter.id,
                ProjectCharter.org_id,
                ProjectCharter.project_id,
                ProjectCharter.version,
                ProjectCharter.status,
                ProjectCharter.generated_by_ai,
                ProjectCharter.previous_version_id,
                ProjectCharter.knowledge_document_id,
                ProjectCharter.knowledge_version_id,
                ProjectCharter.visibility,
                ProjectCharter.approved_by,
                ProjectCharter.approved_at,
                ProjectCharter.publication_status,
                ProjectCharter.published_at,
                ProjectCharter.published_by,
                ProjectCharter.publication_error,
                ProjectCharter.publication_attempt_count,
                ProjectCharter.last_publication_attempt_at,
                ProjectCharter.created_at,
                ProjectCharter.updated_at,
            )
        )

    row_fetch_started = perf_counter()
    rows = list(
        (
            await session.execute(
                stmt.order_by(ProjectCharter.created_at.desc())
                .limit(limit + 1)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    list_row_fetch_ms = round((perf_counter() - row_fetch_started) * 1000, 1)
    db_executes += 1
    has_more = len(rows) > limit
    rows = rows[:limit]
    enrichment_started = perf_counter()
    if include_detail:
        reads, enrichment_executes = await _build_project_charters_read_batch(
            session,
            rows,
            known_project_names=known_project_names,
        )
    else:
        reads, enrichment_executes = await _build_project_charter_list_rows_read(
            session,
            rows,
            known_project_names=known_project_names,
        )
    enrichment_ms = round((perf_counter() - enrichment_started) * 1000, 1)
    db_executes += enrichment_executes

    page = ProjectCharterListPage(
        items=reads,
        limit=limit,
        offset=offset,
        has_more=has_more,
        db_executes=db_executes,
        cache_hit=False,
        list_row_fetch_ms=list_row_fetch_ms,
        enrichment_ms=enrichment_ms,
        include_detail=include_detail,
    )
    if cacheable:
        _project_charter_list_cache[cache_key] = (
            now,
            _copy_charter_list_page(page, cache_hit=False),
        )
    if timer is not None:
        timer.record_meta(
            execute_count=db_executes,
            cache_hit=False,
            limit=limit,
            offset=offset,
            cache_eligible=cacheable,
            cache_shape=cache_shape,
            filtered=project_id is not None,
            cache_scope="user_access",
            project_id=str(project_id) if project_id else None,
            list_row_fetch_ms=list_row_fetch_ms,
            enrichment_ms=enrichment_ms,
            returned_row_count=len(reads),
        )
    return page


def _pick_current_charter_id(charters: Sequence) -> UUID | None:
    approved = next(
        (charter for charter in charters if charter.status == GovernanceCharterStatus.APPROVED),
        None,
    )
    draft = next(
        (charter for charter in charters if charter.status == GovernanceCharterStatus.DRAFT),
        None,
    )
    selected = approved or draft or (charters[0] if charters else None)
    return selected.id if selected else None


async def get_project_charters_panel_data(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    selected_charter_id: UUID | None = None,
    limit: int = 5,
    offset: int = 0,
) -> ProjectChartersPanelData:
    started = perf_counter()
    page = await list_project_charters_page(
        session,
        current_user,
        project_id=project_id,
        limit=limit,
        offset=offset,
        include_detail=False,
    )
    list_row_fetch_ms = round((perf_counter() - started) * 1000, 1)
    target_id = selected_charter_id or _pick_current_charter_id(page.items)
    selected_read = None
    detail_fetch_ms = 0.0
    detail_executes = 0
    if target_id:
        detail_started = perf_counter()
        charter = await get_project_charter_or_404(session, target_id, current_user)
        selected_read, enrichment_executes = await build_project_charter_read_with_metrics(
            session, charter
        )
        detail_fetch_ms = round((perf_counter() - detail_started) * 1000, 1)
        detail_executes = 1 + enrichment_executes

    return ProjectChartersPanelData(
        charters=page.items,
        selected_charter=selected_read,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        db_executes=page.db_executes + detail_executes,
        cache_hit=page.cache_hit,
        list_row_fetch_ms=list_row_fetch_ms,
        detail_fetch_ms=detail_fetch_ms,
        enrichment_ms=page.enrichment_ms,
    )


async def get_project_charter_or_404(
    session: AsyncSession,
    charter_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> ProjectCharter:
    stmt = _charter_access_stmt(current_user, for_mutation=for_mutation).where(
        ProjectCharter.id == charter_id
    )
    charter = (await session.execute(stmt)).scalar_one_or_none()
    if charter is None:
        raise ApiError(
            404, "NOT_FOUND", "Project charter was not found.", {"charter_id": str(charter_id)}
        )
    if current_user.role == AppRole.CLIENT:
        await get_visible_project(session, charter.project_id, current_user)
    return charter


async def generate_project_charter(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID,
    visibility: KnowledgeVisibility = KnowledgeVisibility.INTERNAL_ONLY,
) -> ProjectCharter:
    assert_can_write_governance(current_user)
    project = await get_visible_project(session, project_id, current_user)
    version, previous = await _next_charter_version(session, project.id)
    evidence_items, context = await collect_project_charter_evidence(
        session,
        current_user,
        project_id=project.id,
        version=version,
    )
    if not has_sufficient_charter_evidence(evidence_items):
        raise ApiError(422, "INSUFFICIENT_EVIDENCE", INSUFFICIENT_CHARTER_EVIDENCE_MESSAGE)

    # End the evidence-read transaction before the external model call.
    await session.commit()
    generated_text = await _call_llm_charter(context)
    if not generated_text or not _grounding_ok(generated_text, evidence_items):
        generated_text = build_template_charter(context, evidence_items)
    generated_text = sanitize_charter_text(generated_text)

    charter = ProjectCharter(
        org_id=project.org_id,
        project_id=project.id,
        version=version,
        status=GovernanceCharterStatus.DRAFT,
        generated_text=generated_text,
        generated_by_ai=True,
        previous_version_id=previous.id if previous else None,
        visibility=visibility,
    )
    session.add(charter)
    await session.flush()

    for item in evidence_items:
        session.add(
            GovernanceEvidenceLink(
                org_id=project.org_id,
                charter_id=charter.id,
                source_type=item.source_type,
                source_id=item.source_id,
            )
        )

    await session.commit()
    invalidate_project_charter_list_cache(org_id=project.org_id, project_id=project.id)
    await session.refresh(charter)
    return charter


async def update_project_charter_draft(
    session: AsyncSession,
    charter_id: UUID,
    current_user: CurrentUser,
    *,
    generated_text: str,
    visibility: KnowledgeVisibility | None = None,
) -> ProjectCharter:
    charter = await get_project_charter_or_404(
        session, charter_id, current_user, for_mutation=True
    )
    if charter.status != GovernanceCharterStatus.DRAFT:
        raise ApiError(409, "CHARTER_NOT_EDITABLE", "Only draft charters can be edited.")
    charter.generated_text = sanitize_charter_text(generated_text)
    if visibility is not None:
        charter.visibility = visibility
    await session.commit()
    invalidate_project_charter_list_cache(org_id=charter.org_id, project_id=charter.project_id)
    await session.refresh(charter)
    return charter


async def approve_project_charter(
    session: AsyncSession,
    charter_id: UUID,
    current_user: CurrentUser,
) -> ProjectCharter:
    charter = await get_project_charter_or_404(
        session, charter_id, current_user, for_mutation=True
    )
    if charter.status != GovernanceCharterStatus.DRAFT:
        raise ApiError(409, "CHARTER_NOT_APPROVABLE", "Only draft charters can be approved.")
    charter.status = GovernanceCharterStatus.APPROVED
    charter.approved_by = current_user.id
    charter.approved_at = datetime.now(timezone.utc)
    try:
        from app.reports.adapters import ensure_shadow_instance_for_charter

        await ensure_shadow_instance_for_charter(session, charter)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "event=report_shadow_charter_failed charter_id=%s",
            charter.id,
        )
    await session.commit()
    invalidate_project_charter_list_cache(org_id=charter.org_id, project_id=charter.project_id)
    await session.refresh(charter)
    return charter


async def archive_project_charter(
    session: AsyncSession,
    charter_id: UUID,
    current_user: CurrentUser,
) -> ProjectCharter:
    charter = await get_project_charter_or_404(
        session, charter_id, current_user, for_mutation=True
    )
    if charter.status == GovernanceCharterStatus.ARCHIVED:
        return charter
    charter.status = GovernanceCharterStatus.ARCHIVED
    await session.commit()
    invalidate_project_charter_list_cache(org_id=charter.org_id, project_id=charter.project_id)
    await session.refresh(charter)
    return charter


async def _batch_enrich_charter_evidence_links(
    session: AsyncSession,
    links: Sequence[GovernanceEvidenceLink],
) -> tuple[list[dict[str, Any]], int]:
    from app.agents.governance.schemas.governance import (
        GovernanceEvidenceLinkRead,
    )

    source_ids_by_type: dict[GovernanceEvidenceSourceType, set[UUID]] = {}
    for link in links:
        source_ids_by_type.setdefault(link.source_type, set()).add(link.source_id)

    executes = 0
    dependencies: dict[UUID, ProjectDependency] = {}
    actions: dict[UUID, GovernanceAction] = {}
    escalations: dict[UUID, GovernanceEscalation] = {}
    scopes: dict[UUID, ProjectScopeState] = {}
    knowledge_docs: dict[UUID, KnowledgeDocument] = {}
    risks: dict[UUID, RiskAlert] = {}
    milestones: dict[UUID, Milestone] = {}
    confidence_scores: dict[UUID, DeliveryConfidenceScore] = {}
    delivery_projects: dict[UUID, Project] = {}

    dependency_ids = source_ids_by_type.get(GovernanceEvidenceSourceType.DEPENDENCY, set())
    if dependency_ids:
        dependencies = {
            row.id: row
            for row in (
                await session.execute(select(ProjectDependency).where(ProjectDependency.id.in_(dependency_ids)))
            )
            .scalars()
            .all()
        }
        executes += 1

    action_ids = source_ids_by_type.get(GovernanceEvidenceSourceType.ACTION, set())
    if action_ids:
        actions = {
            row.id: row
            for row in (
                await session.execute(select(GovernanceAction).where(GovernanceAction.id.in_(action_ids)))
            )
            .scalars()
            .all()
        }
        executes += 1

    escalation_ids = source_ids_by_type.get(GovernanceEvidenceSourceType.ESCALATION, set())
    if escalation_ids:
        escalations = {
            row.id: row
            for row in (
                await session.execute(
                    select(GovernanceEscalation).where(GovernanceEscalation.id.in_(escalation_ids))
                )
            )
            .scalars()
            .all()
        }
        executes += 1

    scope_ids = source_ids_by_type.get(GovernanceEvidenceSourceType.SCOPE_STATE, set())
    if scope_ids:
        scopes = {
            row.id: row
            for row in (
                await session.execute(select(ProjectScopeState).where(ProjectScopeState.id.in_(scope_ids)))
            )
            .scalars()
            .all()
        }
        executes += 1

    knowledge_ids = source_ids_by_type.get(GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT, set())
    if knowledge_ids:
        knowledge_docs = {
            row.id: row
            for row in (
                await session.execute(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(knowledge_ids)))
            )
            .scalars()
            .all()
        }
        executes += 1

    delivery_ids = source_ids_by_type.get(GovernanceEvidenceSourceType.DELIVERY_SIGNAL, set())
    if delivery_ids:
        risks = {
            row.id: row
            for row in (
                await session.execute(select(RiskAlert).where(RiskAlert.id.in_(delivery_ids)))
            )
            .scalars()
            .all()
        }
        milestones = {
            row.id: row
            for row in (
                await session.execute(select(Milestone).where(Milestone.id.in_(delivery_ids)))
            )
            .scalars()
            .all()
        }
        confidence_scores = {
            row.id: row
            for row in (
                await session.execute(
                    select(DeliveryConfidenceScore).where(DeliveryConfidenceScore.id.in_(delivery_ids))
                )
            )
            .scalars()
            .all()
        }
        delivery_projects = {
            row.id: row
            for row in (
                await session.execute(select(Project).where(Project.id.in_(delivery_ids)))
            )
            .scalars()
            .all()
        }
        executes += 4

    dependency_project_ids = {
        dependency.project_id for dependency in dependencies.values() if dependency.project_id
    }
    dependency_project_names = await load_project_names(session, dependency_project_ids)
    if dependency_project_ids:
        executes += 1

    enriched: list[dict[str, Any]] = []
    for link in links:
        label = str(link.source_id)
        detail = link.source_type.value
        project_name: str | None = None

        if link.source_type == GovernanceEvidenceSourceType.DEPENDENCY:
            row = dependencies.get(link.source_id)
            if row:
                label = row.title
                detail = f"{row.status.value}, due {row.due_date}"
                project_name = dependency_project_names.get(row.project_id)
        elif link.source_type == GovernanceEvidenceSourceType.ACTION:
            row = actions.get(link.source_id)
            if row:
                label = row.title
                detail = f"{row.status.value}, due {row.due_date}"
        elif link.source_type == GovernanceEvidenceSourceType.ESCALATION:
            row = escalations.get(link.source_id)
            if row:
                label = row.title
                detail = f"{row.severity.value}, {row.status.value}"
        elif link.source_type == GovernanceEvidenceSourceType.SCOPE_STATE:
            row = scopes.get(link.source_id)
            if row:
                label = f"Scope {row.scope_status.value}"
                detail = row.version_label
        elif link.source_type == GovernanceEvidenceSourceType.KNOWLEDGE_DOCUMENT:
            row = knowledge_docs.get(link.source_id)
            if row:
                label = row.title
                detail = f"{row.source_type.value} v{row.version}"
        elif link.source_type == GovernanceEvidenceSourceType.DELIVERY_SIGNAL:
            risk = risks.get(link.source_id)
            if risk:
                label = risk.title
                detail = f"risk_tier={risk.risk_tier.value}"
            elif milestone := milestones.get(link.source_id):
                label = milestone.name
                detail = f"milestone {milestone.status.value}"
            elif confidence := confidence_scores.get(link.source_id):
                label = "Delivery confidence"
                detail = f"score_pct={confidence.score_pct}, status={confidence.status.value}"
            elif project := delivery_projects.get(link.source_id):
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

    return ([GovernanceEvidenceLinkRead.model_validate(row) for row in enriched], executes)


async def _build_project_charter_list_rows_read(
    session: AsyncSession,
    rows: Sequence[ProjectCharter],
    *,
    known_project_names: dict[UUID, str] | None = None,
) -> tuple[list, int]:
    from app.agents.governance.schemas.governance import ProjectCharterRead
    from app.agents.governance.services.governance_charter_publish_service import knowledge_deep_link

    charters = list(rows)
    if not charters:
        return [], 0

    executes = 0
    name_ids = {
        uid
        for charter in charters
        for uid in (charter.approved_by, charter.published_by)
        if uid
    }
    names = await load_user_names(session, name_ids)
    if name_ids:
        executes += 1

    project_names = dict(known_project_names or {})
    missing_project_ids = {charter.project_id for charter in charters} - set(project_names)
    if missing_project_ids:
        project_names.update(await load_project_names(session, missing_project_ids))
        executes += 1

    reads = [
        ProjectCharterRead.model_validate(
            {
                "id": charter.id,
                "org_id": charter.org_id,
                "project_id": charter.project_id,
                "version": charter.version,
                "status": charter.status,
                "generated_text": "",
                "generated_by_ai": charter.generated_by_ai,
                "previous_version_id": charter.previous_version_id,
                "knowledge_document_id": charter.knowledge_document_id,
                "knowledge_version_id": charter.knowledge_version_id,
                "visibility": charter.visibility,
                "approved_by": charter.approved_by,
                "approved_at": charter.approved_at,
                "publication_status": charter.publication_status,
                "published_at": charter.published_at,
                "published_by": charter.published_by,
                "publication_error": charter.publication_error,
                "publication_attempt_count": charter.publication_attempt_count,
                "last_publication_attempt_at": charter.last_publication_attempt_at,
                "created_at": charter.created_at,
                "updated_at": charter.updated_at,
                "evidence_links": [],
                "approved_by_name": names.get(charter.approved_by) if charter.approved_by else None,
                "published_by_name": (
                    names.get(charter.published_by) if charter.published_by else None
                ),
                "project_name": project_names.get(charter.project_id),
                "knowledge_url": knowledge_deep_link(charter.knowledge_document_id),
            }
        )
        for charter in charters
    ]
    return reads, executes


async def _build_project_charters_read_batch(
    session: AsyncSession,
    rows: Sequence[ProjectCharter],
    *,
    known_project_names: dict[UUID, str] | None = None,
) -> tuple[list, int]:
    from app.agents.governance.schemas.governance import ProjectCharterRead
    from app.agents.governance.services.governance_charter_publish_service import knowledge_deep_link

    charters = list(rows)
    if not charters:
        return [], 0

    executes = 0
    charter_ids = {charter.id for charter in charters}
    evidence_rows = list(
        (
            await session.execute(
                select(GovernanceEvidenceLink).where(GovernanceEvidenceLink.charter_id.in_(charter_ids))
            )
        )
        .scalars()
        .all()
    )
    executes += 1
    enriched, evidence_executes = await _batch_enrich_charter_evidence_links(session, evidence_rows)
    executes += evidence_executes

    evidence_by_charter: dict[UUID, list] = {charter.id: [] for charter in charters}
    for link in enriched:
        if link.charter_id in evidence_by_charter:
            evidence_by_charter[link.charter_id].append(link)

    name_ids = {
        uid
        for charter in charters
        for uid in (charter.approved_by, charter.published_by)
        if uid
    }
    names = await load_user_names(session, name_ids)
    if name_ids:
        executes += 1

    project_names = dict(known_project_names or {})
    missing_project_ids = {charter.project_id for charter in charters} - set(project_names)
    if missing_project_ids:
        project_names.update(await load_project_names(session, missing_project_ids))
        executes += 1

    reads = [
        ProjectCharterRead.model_validate(charter, from_attributes=True).model_copy(
            update={
                "evidence_links": evidence_by_charter.get(charter.id, []),
                "generated_text": sanitize_charter_text(charter.generated_text),
                "approved_by_name": names.get(charter.approved_by) if charter.approved_by else None,
                "published_by_name": (
                    names.get(charter.published_by) if charter.published_by else None
                ),
                "project_name": project_names.get(charter.project_id),
                "knowledge_url": knowledge_deep_link(charter.knowledge_document_id),
            }
        )
        for charter in charters
    ]
    return reads, executes


async def build_project_charters_read(
    session: AsyncSession,
    rows: Sequence[ProjectCharter],
) -> list:
    reads, _ = await _build_project_charters_read_batch(session, rows)
    return reads


async def build_project_charter_read_with_metrics(
    session: AsyncSession,
    charter: ProjectCharter,
):
    reads, executes = await _build_project_charters_read_batch(session, [charter])
    return reads[0], executes


async def build_project_charter_read(
    session: AsyncSession,
    charter: ProjectCharter,
):
    read, _ = await build_project_charter_read_with_metrics(session, charter)
    return read


_CHARTER_DB_TIMED = (
    "list_project_charters",
    "list_project_charters_page",
    "get_project_charters_panel_data",
    "get_project_charter_or_404",
    "generate_project_charter",
    "update_project_charter_draft",
    "approve_project_charter",
    "archive_project_charter",
    "build_project_charters_read",
    "build_project_charter_read_with_metrics",
    "build_project_charter_read",
)
for _name in _CHARTER_DB_TIMED:
    globals()[_name] = governance_db_timed(globals()[_name])
