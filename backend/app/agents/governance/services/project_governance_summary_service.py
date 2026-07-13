"""Maintain precomputed per-project governance counts for the register tab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    ProjectDependency,
    ProjectGovernanceSummary,
    ProjectScopeState,
)

_org_summary_day_refreshed: dict[UUID, date] = {}


def _overdue_action_filter(today: date):
    return or_(
        GovernanceAction.status == GovernanceActionStatus.OVERDUE,
        and_(
            GovernanceAction.status != GovernanceActionStatus.COMPLETED,
            GovernanceAction.due_date.is_not(None),
            GovernanceAction.due_date < today,
        ),
    )


@dataclass(frozen=True)
class ProjectGovernanceCounts:
    open_dependencies_count: int
    blocked_dependencies_count: int
    blocking_overdue_dependencies_count: int
    open_actions_count: int
    overdue_actions_count: int
    open_escalations_count: int
    critical_escalations_count: int
    pending_scope_changes_count: int


def _open_dependency_filter():
    return ProjectDependency.status.in_(
        {
            GovernanceDependencyStatus.OPEN,
            GovernanceDependencyStatus.BLOCKING,
        }
    )


def _blocking_dependency_filter():
    return ProjectDependency.status == GovernanceDependencyStatus.BLOCKING


def _blocking_overdue_dependency_filter(today: date):
    return and_(
        ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
        ProjectDependency.due_date.is_not(None),
        ProjectDependency.due_date < today,
    )


def _open_action_filter(today: date):
    return or_(
        GovernanceAction.status.in_(
            {
                GovernanceActionStatus.OPEN,
                GovernanceActionStatus.IN_PROGRESS,
                GovernanceActionStatus.OVERDUE,
            }
        ),
        _overdue_action_filter(today),
    )


def _open_escalation_filter():
    return GovernanceEscalation.status.in_(
        {GovernanceEscalationStatus.OPEN, GovernanceEscalationStatus.IN_PROGRESS}
    )


def invalidate_org_summary_day_cache(org_id: UUID) -> None:
    """Drop the in-process 'refreshed today' marker after a write-path summary update."""
    _org_summary_day_refreshed.pop(org_id, None)


async def compute_project_governance_counts(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    today: date | None = None,
) -> ProjectGovernanceCounts:
    today = today or datetime.now(UTC).date()
    open_esc = _open_escalation_filter()
    dep_base = and_(
        ProjectDependency.org_id == org_id,
        ProjectDependency.project_id == project_id,
        ProjectDependency.deleted_at.is_(None),
    )
    action_base = and_(
        GovernanceAction.org_id == org_id,
        GovernanceAction.project_id == project_id,
        GovernanceAction.deleted_at.is_(None),
    )
    esc_base = and_(
        GovernanceEscalation.org_id == org_id,
        GovernanceEscalation.project_id == project_id,
        GovernanceEscalation.deleted_at.is_(None),
    )
    scope_base = and_(
        ProjectScopeState.org_id == org_id,
        ProjectScopeState.project_id == project_id,
        ProjectScopeState.deleted_at.is_(None),
        ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
    )

    row = (
        await session.execute(
            select(
                select(func.count().filter(_open_dependency_filter()))
                .where(dep_base)
                .scalar_subquery()
                .label("open_dependencies"),
                select(func.count().filter(_blocking_dependency_filter()))
                .where(dep_base)
                .scalar_subquery()
                .label("blocked"),
                select(func.count().filter(_blocking_overdue_dependency_filter(today)))
                .where(dep_base)
                .scalar_subquery()
                .label("blocking_overdue"),
                select(func.count().filter(_open_action_filter(today)))
                .where(action_base)
                .scalar_subquery()
                .label("open_actions"),
                select(func.count().filter(_overdue_action_filter(today)))
                .where(action_base)
                .scalar_subquery()
                .label("overdue_actions"),
                select(func.count().filter(open_esc))
                .where(esc_base)
                .scalar_subquery()
                .label("open_escalations"),
                select(
                    func.count().filter(
                        and_(
                            open_esc,
                            GovernanceEscalation.severity
                            == GovernanceEscalationSeverity.CRITICAL,
                        )
                    )
                )
                .where(esc_base)
                .scalar_subquery()
                .label("critical_escalations"),
                select(func.count()).where(scope_base).scalar_subquery().label("pending_scope"),
            )
        )
    ).one()

    return ProjectGovernanceCounts(
        open_dependencies_count=int(row.open_dependencies or 0),
        blocked_dependencies_count=int(row.blocked or 0),
        blocking_overdue_dependencies_count=int(row.blocking_overdue or 0),
        open_actions_count=int(row.open_actions or 0),
        overdue_actions_count=int(row.overdue_actions or 0),
        open_escalations_count=int(row.open_escalations or 0),
        critical_escalations_count=int(row.critical_escalations or 0),
        pending_scope_changes_count=int(row.pending_scope or 0),
    )


async def refresh_project_governance_summary(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    today: date | None = None,
) -> ProjectGovernanceSummary:
    today = today or datetime.now(UTC).date()
    counts = await compute_project_governance_counts(
        session, org_id, project_id, today=today
    )

    summary = (
        await session.execute(
            select(ProjectGovernanceSummary).where(
                ProjectGovernanceSummary.org_id == org_id,
                ProjectGovernanceSummary.project_id == project_id,
            )
        )
    ).scalar_one_or_none()

    if summary is None:
        summary = ProjectGovernanceSummary(
            org_id=org_id,
            project_id=project_id,
            open_dependencies_count=counts.open_dependencies_count,
            blocked_dependencies_count=counts.blocked_dependencies_count,
            blocking_overdue_dependencies_count=counts.blocking_overdue_dependencies_count,
            open_actions_count=counts.open_actions_count,
            overdue_actions_count=counts.overdue_actions_count,
            open_escalations_count=counts.open_escalations_count,
            critical_escalations_count=counts.critical_escalations_count,
            pending_scope_changes_count=counts.pending_scope_changes_count,
        )
        session.add(summary)
    else:
        summary.open_dependencies_count = counts.open_dependencies_count
        summary.blocked_dependencies_count = counts.blocked_dependencies_count
        summary.blocking_overdue_dependencies_count = counts.blocking_overdue_dependencies_count
        summary.open_actions_count = counts.open_actions_count
        summary.overdue_actions_count = counts.overdue_actions_count
        summary.open_escalations_count = counts.open_escalations_count
        summary.critical_escalations_count = counts.critical_escalations_count
        summary.pending_scope_changes_count = counts.pending_scope_changes_count

    invalidate_org_summary_day_cache(org_id)
    await session.flush()
    return summary


async def _fetch_org_time_sensitive_counts(
    session: AsyncSession,
    org_id: UUID,
    *,
    today: date,
) -> dict[UUID, tuple[int, int]]:
    """Return per-project (overdue_actions, blocking_overdue_deps) in one round trip."""
    overdue_sq = (
        select(
            GovernanceAction.project_id.label("project_id"),
            func.count().label("overdue_actions"),
        )
        .where(
            GovernanceAction.org_id == org_id,
            GovernanceAction.deleted_at.is_(None),
            _overdue_action_filter(today),
        )
        .group_by(GovernanceAction.project_id)
        .subquery("overdue_actions_by_project")
    )
    blocking_sq = (
        select(
            ProjectDependency.project_id.label("project_id"),
            func.count().label("blocking_overdue"),
        )
        .where(
            ProjectDependency.org_id == org_id,
            ProjectDependency.deleted_at.is_(None),
            _blocking_overdue_dependency_filter(today),
        )
        .group_by(ProjectDependency.project_id)
        .subquery("blocking_overdue_by_project")
    )
    rows = (
        await session.execute(
            select(
                func.coalesce(overdue_sq.c.project_id, blocking_sq.c.project_id).label(
                    "project_id"
                ),
                func.coalesce(overdue_sq.c.overdue_actions, 0).label("overdue_actions"),
                func.coalesce(blocking_sq.c.blocking_overdue, 0).label("blocking_overdue"),
            ).select_from(
                overdue_sq.outerjoin(
                    blocking_sq,
                    overdue_sq.c.project_id == blocking_sq.c.project_id,
                    full=True,
                )
            )
        )
    ).all()
    return {
        row.project_id: (int(row.overdue_actions), int(row.blocking_overdue)) for row in rows
    }


async def ensure_org_time_sensitive_summary_counts(
    session: AsyncSession,
    org_id: UUID | None,
    *,
    today: date | None = None,
) -> int:
    """Refresh date-dependent counts once per org per UTC day. Returns DB execute count."""
    if org_id is None:
        return 0

    today = today or datetime.now(UTC).date()
    if _org_summary_day_refreshed.get(org_id) == today:
        return 0

    has_stale = (
        await session.execute(
            select(1)
            .where(
                ProjectGovernanceSummary.org_id == org_id,
                func.date(ProjectGovernanceSummary.updated_at) < today,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    db_executes = 1

    if has_stale is None:
        _org_summary_day_refreshed[org_id] = today
        return db_executes

    stale_summaries = (
        await session.execute(
            select(ProjectGovernanceSummary).where(
                ProjectGovernanceSummary.org_id == org_id,
                func.date(ProjectGovernanceSummary.updated_at) < today,
            )
        )
    ).scalars().all()
    db_executes += 1

    counts_by_project = await _fetch_org_time_sensitive_counts(session, org_id, today=today)
    db_executes += 1
    now = datetime.now(UTC)

    for summary in stale_summaries:
        overdue_actions, blocking_overdue = counts_by_project.get(summary.project_id, (0, 0))
        summary.overdue_actions_count = overdue_actions
        summary.blocking_overdue_dependencies_count = blocking_overdue
        summary.updated_at = now

    await session.flush()
    _org_summary_day_refreshed[org_id] = today
    return db_executes
