"""Project Governance structured evidence adapter for Client Intelligence.

Produces scope, charter metadata, and dependency/action/escalation aggregates.
Never loads charter generated_text, weekly summary_text, titles, or ownership IDs.
Does not import Governance analytics, scoring, prompts, or recommendation services.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import (
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    GovernanceActionFacts,
    GovernanceCharterFacts,
    GovernanceCountFacts,
    GovernanceDependencyFacts,
    GovernanceEscalationFacts,
    GovernanceEvidenceFacts,
    GovernanceScopeFacts,
    GovernanceSummaryFacts,
    ReportingPeriod,
    SourceAgent,
    VisibilityLimitation,
)
from app.db.models import (
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceCharterStatus,
    GovernanceDependencyStatus,
    GovernanceDependencyType,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    KnowledgeVisibility,
    ProjectCharter,
    ProjectDependency,
    ProjectScopeState,
)

_MAX_SCOPE_ROWS = 1
_MAX_CHARTER_METADATA = 50
_MAX_DEPENDENCIES = 100
_MAX_ACTIONS = 100
_MAX_ESCALATIONS = 100

_GENERIC_DESCRIPTION = "Project Governance aggregate evidence for an authorized project."

_HISTORICAL_LIMITATION = (
    "Governance status and soft-delete fields are primarily current-state records; "
    "a past as_of cannot fully reconstruct historical state."
)

_DQ_PRECEDENCE: dict[DataQualityState, int] = {
    DataQualityState.COMPLETE: 0,
    DataQualityState.PARTIAL: 1,
    DataQualityState.STALE: 2,
    DataQualityState.UNAVAILABLE: 3,
    DataQualityState.CONFLICTING: 4,
}

_SCOPE_CLAIM_KEYS = ["scope_status", "version_label", "scope_present"]
_CHARTER_CLAIM_KEYS = [
    "version",
    "status",
    "visibility",
    "approved_at",
    "approved_charter_present",
    "client_safe_charter_present",
]
_DEPENDENCY_AGG_CLAIM_KEYS = [
    "dependency_count",
    "open_dependency_count",
    "blocking_dependency_count",
    "overdue_dependency_count",
    "client_action_dependency_count",
]
_ACTION_AGG_CLAIM_KEYS = [
    "action_count",
    "open_action_count",
    "overdue_action_count",
]
_ESCALATION_AGG_CLAIM_KEYS = [
    "escalation_count",
    "open_escalation_count",
    "critical_escalation_count",
]

_OPEN_DEPENDENCY_STATUSES = {
    GovernanceDependencyStatus.OPEN,
    GovernanceDependencyStatus.BLOCKING,
}
_OPEN_ACTION_STATUSES = {
    GovernanceActionStatus.OPEN,
    GovernanceActionStatus.IN_PROGRESS,
}
_OPEN_ESCALATION_STATUSES = {
    GovernanceEscalationStatus.OPEN,
    GovernanceEscalationStatus.IN_PROGRESS,
}


@dataclass(frozen=True, slots=True)
class _ScopeRow:
    id: UUID
    scope_status: object
    version_label: str
    updated_at: datetime | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _CharterRow:
    id: UUID
    version: str
    status: object
    visibility: object
    approved_at: datetime | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _DependencyRow:
    id: UUID
    dependency_type: object
    status: object
    due_date: date | None
    resolved_at: datetime | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _ActionRow:
    id: UUID
    status: object
    due_date: date | None
    completed_at: datetime | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _EscalationRow:
    id: UUID
    severity: object
    status: object
    raised_at: datetime
    resolved_at: datetime | None
    source_type: object | None
    created_at: datetime | None


def _as_of_end_utc(as_of: date) -> datetime:
    return datetime.combine(as_of, time.max, tzinfo=UTC)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _evidence_visibility(client_safe: bool) -> EvidenceVisibility:
    return EvidenceVisibility.CLIENT_SAFE if client_safe else EvidenceVisibility.INTERNAL


def _issue(source: str, state: DataQualityState, detail: str) -> DataQualityIssue:
    return DataQualityIssue(source=source, state=state, detail=detail, observed_at=None)


def _set_source_issue(
    issues_by_source: dict[str, DataQualityIssue],
    source: str,
    state: DataQualityState,
    detail: str,
) -> None:
    """Keep one issue per source: CONFLICTING > UNAVAILABLE > PARTIAL > COMPLETE."""
    existing = issues_by_source.get(source)
    if existing is None or _DQ_PRECEDENCE[state] > _DQ_PRECEDENCE[existing.state]:
        issues_by_source[source] = _issue(source, state, detail)


def _finalize_issues(issues_by_source: dict[str, DataQualityIssue]) -> list[DataQualityIssue]:
    return [issues_by_source[key] for key in sorted(issues_by_source)]


def _trim_limit_plus_one(rows: list, max_rows: int) -> tuple[list, bool]:
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


def _status_enum(value: object, enum_cls: type) -> object:
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)


async def load_governance_evidence(
    session: AsyncSession,
    project_id: UUID,
    org_id: UUID,
    reporting_period: ReportingPeriod,
    *,
    visibility_mode: EvidenceVisibility,
) -> tuple[
    GovernanceEvidenceFacts,
    list[ClientEvidenceReference],
    list[DataQualityIssue],
    list[VisibilityLimitation],
    list[str],
]:
    """Load bounded Governance facts for an already-authorized project."""
    client_safe = visibility_mode == EvidenceVisibility.CLIENT_SAFE
    as_of = reporting_period.as_of
    as_of_end = _as_of_end_utc(as_of)
    today = datetime.now(UTC).date()

    evidence: list[ClientEvidenceReference] = []
    issues_by_source: dict[str, DataQualityIssue] = {}
    visibility_limitations: list[VisibilityLimitation] = []
    limitations: list[str] = []

    if as_of < today:
        limitations.append(_HISTORICAL_LIMITATION)

    scope, scope_limitations = await _build_scope(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(scope_limitations)

    charter, charter_vis, charter_limitations = await _build_charter(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    visibility_limitations.extend(charter_vis)
    limitations.extend(charter_limitations)

    dependencies, dependency_facts, dep_limitations = await _build_dependencies(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(dep_limitations)

    actions, action_facts, action_limitations = await _build_actions(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(action_limitations)

    escalations, escalation_facts, esc_limitations = await _build_escalations(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(esc_limitations)

    grouped = _build_grouped_counts(
        dependencies,
        actions,
        escalations,
        client_safe=client_safe,
    )
    summary = GovernanceSummaryFacts(
        dependency_count=len(dependencies),
        open_dependency_count=sum(
            1
            for row in dependencies
            if _status_enum(row.status, GovernanceDependencyStatus) in _OPEN_DEPENDENCY_STATUSES
        ),
        blocking_dependency_count=sum(
            1
            for row in dependencies
            if _status_enum(row.status, GovernanceDependencyStatus)
            == GovernanceDependencyStatus.BLOCKING
        ),
        overdue_dependency_count=sum(
            1
            for row in dependencies
            if row.due_date is not None
            and row.due_date < as_of
            and _status_enum(row.status, GovernanceDependencyStatus)
            != GovernanceDependencyStatus.RESOLVED
        ),
        client_action_dependency_count=sum(
            1
            for row in dependencies
            if _status_enum(row.dependency_type, GovernanceDependencyType)
            == GovernanceDependencyType.CLIENT_ACTION
        ),
        action_count=len(actions),
        open_action_count=sum(
            1
            for row in actions
            if _status_enum(row.status, GovernanceActionStatus) in _OPEN_ACTION_STATUSES
        ),
        overdue_action_count=sum(1 for row in actions if _action_is_overdue(row, as_of)),
        escalation_count=len(escalations),
        open_escalation_count=sum(
            1
            for row in escalations
            if _status_enum(row.status, GovernanceEscalationStatus) in _OPEN_ESCALATION_STATUSES
        ),
        critical_escalation_count=sum(
            1
            for row in escalations
            if _status_enum(row.severity, GovernanceEscalationSeverity)
            == GovernanceEscalationSeverity.CRITICAL
        ),
        scope_present=scope is not None,
        approved_charter_present=_is_approved_charter(charter) if charter else False,
        client_safe_charter_present=_is_client_safe_charter(charter) if charter else False,
        grouped_counts=grouped,
    )

    if client_safe:
        evidence = [item for item in evidence if item.visibility == EvidenceVisibility.CLIENT_SAFE]

    facts = GovernanceEvidenceFacts(
        scope=scope,
        charter=charter,
        summary=summary,
        dependencies=[] if client_safe else dependency_facts,
        actions=[] if client_safe else action_facts,
        escalations=[] if client_safe else escalation_facts,
        as_of=as_of,
    )
    return (
        facts,
        evidence,
        _finalize_issues(issues_by_source),
        visibility_limitations,
        limitations,
    )


def _is_approved_charter(charter: GovernanceCharterFacts) -> bool:
    return charter.status == GovernanceCharterStatus.APPROVED.value


def _is_client_safe_charter(charter: GovernanceCharterFacts) -> bool:
    return (
        charter.status == GovernanceCharterStatus.APPROVED.value
        and charter.visibility == KnowledgeVisibility.CLIENT_SAFE.value
        and charter.approved_at is not None
    )


def _action_is_overdue(row: _ActionRow, as_of: date) -> bool:
    status = _status_enum(row.status, GovernanceActionStatus)
    if status == GovernanceActionStatus.OVERDUE:
        return True
    return row.due_date is not None and row.due_date < as_of and status in _OPEN_ACTION_STATUSES


def _build_grouped_counts(
    dependencies: list[_DependencyRow],
    actions: list[_ActionRow],
    escalations: list[_EscalationRow],
    *,
    client_safe: bool,
) -> list[GovernanceCountFacts]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in dependencies:
        counts[("dependency", _enum_str(row.status))] += 1
        if not client_safe:
            counts[("dependency_type", _enum_str(row.dependency_type))] += 1
    for row in actions:
        counts[("action", _enum_str(row.status))] += 1
    for row in escalations:
        counts[("escalation", _enum_str(row.status))] += 1
        counts[("escalation_severity", _enum_str(row.severity))] += 1
    return [
        GovernanceCountFacts(category=category, status=status, count=count)
        for (category, status), count in sorted(counts.items(), key=lambda item: item[0])
    ]


async def _build_scope(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[GovernanceScopeFacts | None, list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)
    rows, truncated = await _load_scope_rows(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if truncated or len(rows) > 1:
        # limit-plus-one with MAX=1: truncated means another row exists.
        _set_source_issue(
            issues_by_source,
            "governance_scope",
            DataQualityState.CONFLICTING,
            "Multiple project scope-state rows exist at or before as_of.",
        )
        limitations.append(
            "Multiple scope-state rows were resolved to the latest deterministically."
        )

    if not rows:
        _set_source_issue(
            issues_by_source,
            "governance_scope",
            DataQualityState.UNAVAILABLE,
            "No project scope-state row found at or before as_of.",
        )
        return None, limitations

    row = rows[0]
    facts = GovernanceScopeFacts(
        scope_state_id=None if client_safe else row.id,
        scope_status=_enum_str(row.scope_status),
        version_label=row.version_label,
        observed_at=row.updated_at or row.created_at,
    )
    evidence.append(
        ClientEvidenceReference(
            source_agent=SourceAgent.PROJECT_GOVERNANCE,
            source_table="project_scope_states",
            source_row_id=row.id,
            description=_GENERIC_DESCRIPTION,
            visibility=visibility,
            observed_at=facts.observed_at,
            claim_keys=list(_SCOPE_CLAIM_KEYS),
        )
    )
    _set_source_issue(
        issues_by_source,
        "governance_scope",
        DataQualityState.COMPLETE,
        "Project scope-state metadata was loaded.",
    )
    return facts, limitations


async def _load_scope_rows(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_ScopeRow], bool]:
    result = await session.execute(
        select(
            ProjectScopeState.id,
            ProjectScopeState.scope_status,
            ProjectScopeState.version_label,
            ProjectScopeState.updated_at,
            ProjectScopeState.created_at,
        )
        .where(
            ProjectScopeState.project_id == project_id,
            ProjectScopeState.org_id == org_id,
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.created_at <= as_of_end,
        )
        .order_by(
            ProjectScopeState.updated_at.desc(),
            ProjectScopeState.created_at.desc(),
            ProjectScopeState.id.desc(),
        )
        .limit(_MAX_SCOPE_ROWS + 1)
    )
    rows = [
        _ScopeRow(
            id=row.id,
            scope_status=row.scope_status,
            version_label=row.version_label,
            updated_at=row.updated_at,
            created_at=row.created_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_SCOPE_ROWS)


async def _build_charter(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[GovernanceCharterFacts | None, list[VisibilityLimitation], list[str]]:
    limitations: list[str] = []
    visibility_limitations: list[VisibilityLimitation] = []
    visibility = _evidence_visibility(client_safe)

    if client_safe:
        return await _build_client_safe_charter(
            session,
            project_id=project_id,
            org_id=org_id,
            as_of_end=as_of_end,
            evidence=evidence,
            issues_by_source=issues_by_source,
            visibility_limitations=visibility_limitations,
            limitations=limitations,
        )

    return await _project_internal_charter(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        evidence=evidence,
        issues_by_source=issues_by_source,
        limitations=limitations,
        visibility=visibility,
    )


async def _build_client_safe_charter(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
    visibility_limitations: list[VisibilityLimitation],
    limitations: list[str],
) -> tuple[GovernanceCharterFacts | None, list[VisibilityLimitation], list[str]]:
    candidates, truncated = await _load_client_safe_approved_candidates(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if truncated:
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.PARTIAL,
            "Approved client-safe charter candidate query reached the configured row bound.",
        )
        limitations.append("Charter candidate discovery was truncated; results may be incomplete.")

    return _project_client_safe_charter(
        candidates,
        as_of_end=as_of_end,
        truncated=truncated,
        any_charter=await _any_charter_exists(
            session,
            project_id=project_id,
            org_id=org_id,
            as_of_end=as_of_end,
        ),
        evidence=evidence,
        issues_by_source=issues_by_source,
        visibility_limitations=visibility_limitations,
        limitations=limitations,
    )


def _project_client_safe_charter(
    candidates: list[_CharterRow],
    *,
    as_of_end: datetime,
    truncated: bool,
    any_charter: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
    visibility_limitations: list[VisibilityLimitation],
    limitations: list[str],
) -> tuple[GovernanceCharterFacts | None, list[VisibilityLimitation], list[str]]:
    missing_approved_at = [row for row in candidates if row.approved_at is None]
    future_approved = [
        row for row in candidates if row.approved_at is not None and row.approved_at > as_of_end
    ]
    valid = [
        row for row in candidates if row.approved_at is not None and row.approved_at <= as_of_end
    ]
    valid.sort(
        key=lambda row: (
            row.approved_at or datetime.min.replace(tzinfo=UTC),
            row.created_at or datetime.min.replace(tzinfo=UTC),
            str(row.id),
        ),
        reverse=True,
    )

    # Evaluate competing and malformed candidates before projecting COMPLETE.
    if len(valid) > 1:
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.CONFLICTING,
            "Multiple approved client-safe charters exist at or before as_of.",
        )
        limitations.append(
            "Multiple approved client-safe charters were resolved deterministically."
        )
    if missing_approved_at:
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.PARTIAL,
            "Approved client-safe charter is missing approved_at.",
        )
        limitations.append(
            "Another approved client-safe charter lacks approval metadata " "and was not projected."
            if valid
            else (
                "An approved client-safe charter cannot be exposed because "
                "approved_at is missing."
            )
        )
        if not valid:
            visibility_limitations.append(
                VisibilityLimitation(
                    source="governance_charter",
                    reason="missing_approved_at",
                    detail=(
                        "An APPROVED CLIENT_SAFE charter exists but lacks approved_at, "
                        "so it cannot be projected as client-safe evidence."
                    ),
                )
            )

    if valid:
        row = valid[0]
        facts = GovernanceCharterFacts(
            charter_id=row.id,
            version=row.version,
            status=_enum_str(row.status),
            visibility=_enum_str(row.visibility),
            approved_at=row.approved_at,
            observed_at=row.created_at,
        )
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="project_charters",
                source_row_id=row.id,
                description=_GENERIC_DESCRIPTION,
                visibility=EvidenceVisibility.CLIENT_SAFE,
                observed_at=row.approved_at or row.created_at,
                claim_keys=list(_CHARTER_CLAIM_KEYS),
            )
        )
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.COMPLETE,
            "Approved client-safe charter metadata was loaded.",
        )
        return facts, visibility_limitations, limitations

    if missing_approved_at:
        return None, visibility_limitations, limitations

    if truncated:
        # Do not claim absence of an approved client-safe charter when discovery was truncated.
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.PARTIAL,
            "Charter candidate discovery was truncated before approval state could be confirmed.",
        )
        return None, visibility_limitations, limitations

    if future_approved:
        visibility_limitations.append(
            VisibilityLimitation(
                source="governance_charter",
                reason="approved_after_as_of",
                detail=(
                    "An approved client-safe charter exists but was approved after as_of, "
                    "so it is not projected for the requested period."
                ),
            )
        )
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.COMPLETE,
            "Charter source queried; no charter approved at or before as_of.",
        )
        return None, visibility_limitations, limitations

    if any_charter:
        visibility_limitations.append(
            VisibilityLimitation(
                source="governance_charter",
                reason="not_client_safe",
                detail=(
                    "A project charter exists but is not an approved "
                    "client-safe charter at or before as_of."
                ),
            )
        )
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.COMPLETE,
            "Charter source queried; no approved client-safe charter projected.",
        )
        return None, visibility_limitations, limitations

    _set_source_issue(
        issues_by_source,
        "governance_charter",
        DataQualityState.UNAVAILABLE,
        "No project charter found at or before as_of.",
    )
    return None, visibility_limitations, limitations


async def _project_internal_charter(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
    limitations: list[str],
    visibility: EvidenceVisibility,
) -> tuple[GovernanceCharterFacts | None, list[VisibilityLimitation], list[str]]:
    latest = await _load_latest_internal_charter(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if latest is None:
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.UNAVAILABLE,
            "No project charter found at or before as_of.",
        )
        return None, [], limitations

    competing = await _load_competing_approved_charters(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if len(competing) > 1:
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.CONFLICTING,
            "Multiple simultaneously APPROVED charter versions exist at or before as_of.",
        )
        limitations.append(
            "Competing approved charter versions were detected; latest metadata was selected."
        )

    status = _status_enum(latest.status, GovernanceCharterStatus)
    if status == GovernanceCharterStatus.APPROVED and latest.approved_at is None:
        _set_source_issue(
            issues_by_source,
            "governance_charter",
            DataQualityState.PARTIAL,
            "Approved charter is missing approved_at.",
        )
        limitations.append("Selected APPROVED charter is missing approved_at.")

    facts = GovernanceCharterFacts(
        charter_id=latest.id,
        version=latest.version,
        status=_enum_str(latest.status),
        visibility=_enum_str(latest.visibility),
        approved_at=latest.approved_at,
        observed_at=latest.created_at,
    )
    evidence.append(
        ClientEvidenceReference(
            source_agent=SourceAgent.PROJECT_GOVERNANCE,
            source_table="project_charters",
            source_row_id=latest.id,
            description=_GENERIC_DESCRIPTION,
            visibility=visibility,
            observed_at=latest.created_at,
            claim_keys=list(_CHARTER_CLAIM_KEYS),
        )
    )
    _set_source_issue(
        issues_by_source,
        "governance_charter",
        DataQualityState.COMPLETE,
        "Project charter metadata was loaded.",
    )
    return facts, [], limitations


async def _any_charter_exists(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> bool:
    result = await session.execute(
        select(ProjectCharter.id)
        .where(
            ProjectCharter.project_id == project_id,
            ProjectCharter.org_id == org_id,
            ProjectCharter.created_at <= as_of_end,
        )
        .order_by(ProjectCharter.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _load_latest_internal_charter(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> _CharterRow | None:
    result = await session.execute(
        select(
            ProjectCharter.id,
            ProjectCharter.version,
            ProjectCharter.status,
            ProjectCharter.visibility,
            ProjectCharter.approved_at,
            ProjectCharter.created_at,
        )
        .where(
            ProjectCharter.project_id == project_id,
            ProjectCharter.org_id == org_id,
            ProjectCharter.created_at <= as_of_end,
        )
        .order_by(
            ProjectCharter.created_at.desc(),
            ProjectCharter.id.desc(),
        )
        .limit(1)
    )
    rows = result.all()
    if not rows:
        return None
    row = rows[0]
    return _CharterRow(
        id=row.id,
        version=row.version,
        status=row.status,
        visibility=row.visibility,
        approved_at=row.approved_at,
        created_at=row.created_at,
    )


async def _load_client_safe_approved_candidates(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_CharterRow], bool]:
    """APPROVED + CLIENT_SAFE metadata, including missing approved_at for validation."""
    result = await session.execute(
        select(
            ProjectCharter.id,
            ProjectCharter.version,
            ProjectCharter.status,
            ProjectCharter.visibility,
            ProjectCharter.approved_at,
            ProjectCharter.created_at,
        )
        .where(
            ProjectCharter.project_id == project_id,
            ProjectCharter.org_id == org_id,
            ProjectCharter.created_at <= as_of_end,
            ProjectCharter.status == GovernanceCharterStatus.APPROVED,
            ProjectCharter.visibility == KnowledgeVisibility.CLIENT_SAFE,
        )
        .order_by(
            ProjectCharter.approved_at.desc().nulls_last(),
            ProjectCharter.created_at.desc(),
            ProjectCharter.id.desc(),
        )
        .limit(_MAX_CHARTER_METADATA + 1)
    )
    rows = [
        _CharterRow(
            id=row.id,
            version=row.version,
            status=row.status,
            visibility=row.visibility,
            approved_at=row.approved_at,
            created_at=row.created_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_CHARTER_METADATA)


async def _load_competing_approved_charters(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> list[_CharterRow]:
    result = await session.execute(
        select(
            ProjectCharter.id,
            ProjectCharter.version,
            ProjectCharter.status,
            ProjectCharter.visibility,
            ProjectCharter.approved_at,
            ProjectCharter.created_at,
        )
        .where(
            ProjectCharter.project_id == project_id,
            ProjectCharter.org_id == org_id,
            ProjectCharter.created_at <= as_of_end,
            ProjectCharter.status == GovernanceCharterStatus.APPROVED,
        )
        .order_by(
            ProjectCharter.approved_at.desc().nulls_last(),
            ProjectCharter.created_at.desc(),
            ProjectCharter.id.desc(),
        )
        .limit(2)
    )
    return [
        _CharterRow(
            id=row.id,
            version=row.version,
            status=row.status,
            visibility=row.visibility,
            approved_at=row.approved_at,
            created_at=row.created_at,
        )
        for row in result.all()
    ]


async def _build_dependencies(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[list[_DependencyRow], list[GovernanceDependencyFacts], list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)
    rows, truncated = await _load_dependencies(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if truncated:
        limitations.append("Dependency query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "governance_dependencies",
            DataQualityState.PARTIAL,
            "Dependency query reached the configured row bound.",
        )

    facts: list[GovernanceDependencyFacts] = []
    for row in rows:
        facts.append(
            GovernanceDependencyFacts(
                dependency_id=row.id,
                dependency_type=_enum_str(row.dependency_type),
                status=_enum_str(row.status),
                due_date=row.due_date,
                resolved_at=row.resolved_at,
                observed_at=row.created_at,
            )
        )
        claim_keys = list(_DEPENDENCY_AGG_CLAIM_KEYS)
        if not client_safe:
            claim_keys.extend(
                [
                    "dependency_id",
                    "dependency_type",
                    "status",
                    "due_date",
                    "resolved_at",
                ]
            )
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="project_dependencies",
                source_row_id=row.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=row.created_at,
                claim_keys=claim_keys,
            )
        )

    _set_source_issue(
        issues_by_source,
        "governance_dependencies",
        DataQualityState.COMPLETE,
        f"Dependency query succeeded with {len(rows)} row(s).",
    )
    return rows, facts, limitations


async def _load_dependencies(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_DependencyRow], bool]:
    result = await session.execute(
        select(
            ProjectDependency.id,
            ProjectDependency.dependency_type,
            ProjectDependency.status,
            ProjectDependency.due_date,
            ProjectDependency.resolved_at,
            ProjectDependency.created_at,
        )
        .where(
            ProjectDependency.project_id == project_id,
            ProjectDependency.org_id == org_id,
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.created_at <= as_of_end,
        )
        .order_by(ProjectDependency.created_at.desc(), ProjectDependency.id.desc())
        .limit(_MAX_DEPENDENCIES + 1)
    )
    rows = [
        _DependencyRow(
            id=row.id,
            dependency_type=row.dependency_type,
            status=row.status,
            due_date=row.due_date,
            resolved_at=row.resolved_at,
            created_at=row.created_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_DEPENDENCIES)


async def _build_actions(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[list[_ActionRow], list[GovernanceActionFacts], list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)
    rows, truncated = await _load_actions(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if truncated:
        limitations.append("Governance action query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "governance_actions",
            DataQualityState.PARTIAL,
            "Governance action query reached the configured row bound.",
        )

    facts: list[GovernanceActionFacts] = []
    for row in rows:
        facts.append(
            GovernanceActionFacts(
                action_id=row.id,
                status=_enum_str(row.status),
                due_date=row.due_date,
                completed_at=row.completed_at,
                observed_at=row.created_at,
            )
        )
        claim_keys = list(_ACTION_AGG_CLAIM_KEYS)
        if not client_safe:
            claim_keys.extend(["action_id", "status", "due_date", "completed_at"])
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="governance_actions",
                source_row_id=row.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=row.created_at,
                claim_keys=claim_keys,
            )
        )

    _set_source_issue(
        issues_by_source,
        "governance_actions",
        DataQualityState.COMPLETE,
        f"Governance action query succeeded with {len(rows)} row(s).",
    )
    return rows, facts, limitations


async def _load_actions(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_ActionRow], bool]:
    result = await session.execute(
        select(
            GovernanceAction.id,
            GovernanceAction.status,
            GovernanceAction.due_date,
            GovernanceAction.completed_at,
            GovernanceAction.created_at,
        )
        .where(
            GovernanceAction.project_id == project_id,
            GovernanceAction.org_id == org_id,
            GovernanceAction.deleted_at.is_(None),
            GovernanceAction.created_at <= as_of_end,
        )
        .order_by(GovernanceAction.created_at.desc(), GovernanceAction.id.desc())
        .limit(_MAX_ACTIONS + 1)
    )
    rows = [
        _ActionRow(
            id=row.id,
            status=row.status,
            due_date=row.due_date,
            completed_at=row.completed_at,
            created_at=row.created_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_ACTIONS)


async def _build_escalations(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[list[_EscalationRow], list[GovernanceEscalationFacts], list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)
    rows, truncated = await _load_escalations(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if truncated:
        limitations.append("Governance escalation query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "governance_escalations",
            DataQualityState.PARTIAL,
            "Governance escalation query reached the configured row bound.",
        )

    facts: list[GovernanceEscalationFacts] = []
    for row in rows:
        facts.append(
            GovernanceEscalationFacts(
                escalation_id=row.id,
                severity=_enum_str(row.severity),
                status=_enum_str(row.status),
                raised_at=row.raised_at,
                resolved_at=row.resolved_at,
                source_type=_enum_str(row.source_type) if row.source_type is not None else None,
                observed_at=row.created_at,
            )
        )
        claim_keys = list(_ESCALATION_AGG_CLAIM_KEYS)
        if not client_safe:
            claim_keys.extend(
                [
                    "escalation_id",
                    "severity",
                    "status",
                    "raised_at",
                    "resolved_at",
                    "source_type",
                ]
            )
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.PROJECT_GOVERNANCE,
                source_table="governance_escalations",
                source_row_id=row.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=row.created_at,
                claim_keys=claim_keys,
            )
        )

    _set_source_issue(
        issues_by_source,
        "governance_escalations",
        DataQualityState.COMPLETE,
        f"Governance escalation query succeeded with {len(rows)} row(s).",
    )
    return rows, facts, limitations


async def _load_escalations(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_EscalationRow], bool]:
    result = await session.execute(
        select(
            GovernanceEscalation.id,
            GovernanceEscalation.severity,
            GovernanceEscalation.status,
            GovernanceEscalation.raised_at,
            GovernanceEscalation.resolved_at,
            GovernanceEscalation.source_type,
            GovernanceEscalation.created_at,
        )
        .where(
            GovernanceEscalation.project_id == project_id,
            GovernanceEscalation.org_id == org_id,
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.raised_at <= as_of_end,
            GovernanceEscalation.created_at <= as_of_end,
        )
        .order_by(
            GovernanceEscalation.raised_at.desc(),
            GovernanceEscalation.id.desc(),
        )
        .limit(_MAX_ESCALATIONS + 1)
    )
    rows = [
        _EscalationRow(
            id=row.id,
            severity=row.severity,
            status=row.status,
            raised_at=row.raised_at,
            resolved_at=row.resolved_at,
            source_type=row.source_type,
            created_at=row.created_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_ESCALATIONS)
