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


async def compute_project_governance_counts(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    today: date | None = None,
) -> ProjectGovernanceCounts:
    today = today or datetime.now(UTC).date()
    open_esc = _open_escalation_filter()

    dep_row = (
        await session.execute(
            select(
                func.count().filter(_open_dependency_filter()).label("open_dependencies"),
                func.count().filter(_blocking_dependency_filter()).label("blocked"),
                func.count()
                .filter(_blocking_overdue_dependency_filter(today))
                .label("blocking_overdue"),
            ).where(
                ProjectDependency.org_id == org_id,
                ProjectDependency.project_id == project_id,
                ProjectDependency.deleted_at.is_(None),
            )
        )
    ).one()

    action_row = (
        await session.execute(
            select(
                func.count().filter(_open_action_filter(today)).label("open_actions"),
                func.count().filter(_overdue_action_filter(today)).label("overdue_actions"),
            ).where(
                GovernanceAction.org_id == org_id,
                GovernanceAction.project_id == project_id,
                GovernanceAction.deleted_at.is_(None),
            )
        )
    ).one()

    esc_row = (
        await session.execute(
            select(
                func.count().filter(open_esc).label("open_escalations"),
                func.count()
                .filter(
                    and_(
                        open_esc,
                        GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
                    )
                )
                .label("critical_escalations"),
            ).where(
                GovernanceEscalation.org_id == org_id,
                GovernanceEscalation.project_id == project_id,
                GovernanceEscalation.deleted_at.is_(None),
            )
        )
    ).one()

    pending_scope = (
        await session.execute(
            select(func.count()).where(
                ProjectScopeState.org_id == org_id,
                ProjectScopeState.project_id == project_id,
                ProjectScopeState.deleted_at.is_(None),
                ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
            )
        )
    ).scalar_one()

    return ProjectGovernanceCounts(
        open_dependencies_count=int(dep_row.open_dependencies or 0),
        blocked_dependencies_count=int(dep_row.blocked or 0),
        blocking_overdue_dependencies_count=int(dep_row.blocking_overdue or 0),
        open_actions_count=int(action_row.open_actions or 0),
        overdue_actions_count=int(action_row.overdue_actions or 0),
        open_escalations_count=int(esc_row.open_escalations or 0),
        critical_escalations_count=int(esc_row.critical_escalations or 0),
        pending_scope_changes_count=int(pending_scope or 0),
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

    await session.flush()
    return summary


async def ensure_org_time_sensitive_summary_counts(
    session: AsyncSession,
    org_id: UUID,
    *,
    today: date | None = None,
) -> None:
    """Refresh date-dependent counts once per org per UTC day."""
    today = today or datetime.now(UTC).date()
    stale_summaries = (
        await session.execute(
            select(ProjectGovernanceSummary).where(
                ProjectGovernanceSummary.org_id == org_id,
                func.date(ProjectGovernanceSummary.updated_at) < today,
            )
        )
    ).scalars().all()
    if not stale_summaries:
        return

    overdue_rows = (
        await session.execute(
            select(GovernanceAction.project_id, func.count())
            .where(
                GovernanceAction.org_id == org_id,
                GovernanceAction.deleted_at.is_(None),
                _overdue_action_filter(today),
            )
            .group_by(GovernanceAction.project_id)
        )
    ).all()
    blocking_overdue_rows = (
        await session.execute(
            select(ProjectDependency.project_id, func.count())
            .where(
                ProjectDependency.org_id == org_id,
                ProjectDependency.deleted_at.is_(None),
                _blocking_overdue_dependency_filter(today),
            )
            .group_by(ProjectDependency.project_id)
        )
    ).all()

    overdue_by_project = {row[0]: int(row[1]) for row in overdue_rows}
    blocking_overdue_by_project = {row[0]: int(row[1]) for row in blocking_overdue_rows}
    now = datetime.now(UTC)

    for summary in stale_summaries:
        summary.overdue_actions_count = overdue_by_project.get(summary.project_id, 0)
        summary.blocking_overdue_dependencies_count = blocking_overdue_by_project.get(
            summary.project_id, 0
        )
        summary.updated_at = now

    await session.flush()
