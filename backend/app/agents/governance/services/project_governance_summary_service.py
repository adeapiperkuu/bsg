"""Maintain precomputed per-project governance counts for the register tab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from time import perf_counter
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
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

# PostgreSQL transaction-scoped advisory lock. Every worker uses the same key, so a daily refresh
# is serialized across processes without introducing distributed infrastructure.
GOVERNANCE_DAILY_SUMMARY_REFRESH_LOCK_KEY = 4_732_019_884_017


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


@dataclass(frozen=True)
class GovernanceDailySummaryRefreshResult:
    business_date: date
    rows_refreshed: int
    org_ids: tuple[UUID, ...]
    execute_count: int
    duration_ms: float


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
                            GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
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
    counts = await compute_project_governance_counts(session, org_id, project_id, today=today)

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


async def refresh_stale_governance_summary_counts(
    session: AsyncSession,
    *,
    today: date | None = None,
    refreshed_at: datetime | None = None,
) -> GovernanceDailySummaryRefreshResult:
    """Refresh all stale UTC-day counts in one locked PostgreSQL statement.

    The advisory transaction lock prevents duplicate cross-worker refresh work. The update is
    idempotent: after one successful execution, `updated_at` is within the target UTC day and a
    retry updates zero rows. The caller owns commit/rollback and post-commit cache invalidation.
    """
    business_date = today or datetime.now(UTC).date()
    now = refreshed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("refreshed_at must be timezone-aware")
    day_start = datetime.combine(business_date, time.min, tzinfo=UTC)

    summary = ProjectGovernanceSummary
    overdue_actions = (
        select(func.count(GovernanceAction.id))
        .where(
            GovernanceAction.org_id == summary.org_id,
            GovernanceAction.project_id == summary.project_id,
            GovernanceAction.deleted_at.is_(None),
            _overdue_action_filter(business_date),
        )
        .correlate(summary)
        .scalar_subquery()
    )
    blocking_overdue = (
        select(func.count(ProjectDependency.id))
        .where(
            ProjectDependency.org_id == summary.org_id,
            ProjectDependency.project_id == summary.project_id,
            ProjectDependency.deleted_at.is_(None),
            _blocking_overdue_dependency_filter(business_date),
        )
        .correlate(summary)
        .scalar_subquery()
    )

    lock_acquired = select(
        func.pg_try_advisory_xact_lock(GOVERNANCE_DAILY_SUMMARY_REFRESH_LOCK_KEY)
    ).scalar_subquery()
    stmt = (
        update(summary)
        .where(
            summary.updated_at < day_start,
            lock_acquired.is_(True),
        )
        .values(
            overdue_actions_count=overdue_actions,
            blocking_overdue_dependencies_count=blocking_overdue,
            updated_at=now,
        )
        .returning(summary.org_id, summary.project_id)
    )
    started = perf_counter()
    rows = (await session.execute(stmt)).all()
    duration_ms = round((perf_counter() - started) * 1000, 1)
    return GovernanceDailySummaryRefreshResult(
        business_date=business_date,
        rows_refreshed=len(rows),
        org_ids=tuple(sorted({row.org_id for row in rows}, key=str)),
        execute_count=1,
        duration_ms=duration_ms,
    )
