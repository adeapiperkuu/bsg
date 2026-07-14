from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from time import perf_counter
from types import SimpleNamespace
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, and_, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.analytics.sla import (
    calculate_sla_adherence_pct,
    dependency_overdue_days,
    effective_action_status,
)
from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsDetailRead,
    GovernanceAnalyticsRead,
    GovernanceAnalyticsSummaryRead,
    GovernanceChartPointRead,
    GovernanceEvidenceRead,
    GovernanceHealthProjectRead,
    GovernanceInsightRead,
    GovernanceInsightsKpisRead,
    GovernanceNamedCountRead,
    GovernanceRecommendationRead,
    GovernanceRiskHeatmapCellRead,
)
from app.agents.governance.services.dashboard_service import (
    _overdue_action_filter,
)
from app.agents.governance.services.delivery_signals import (
    GOVERNANCE_THROUGHPUT_LIMIT,
    _parse_governance_signal_bundle_rows,
    build_governance_delivery_signals_from_inputs,
    fetch_governance_delivery_signals,
    governance_signal_bundle_select_sql,
)
from app.agents.governance.services.governance_service import (
    _apply_org_filter,
    assert_can_read_governance,
    can_read_internal_governance,
)
from app.agents.governance.timing import get_governance_timer, governance_db_timed
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceEscalationTriggerType,
    GovernanceRecommendationAcceptanceStatus,
    GovernanceScopeStatus,
    Project,
    ProjectDependency,
    ProjectScopeState,
    ProjectStatus,
)
from app.db.session import session_scope
from app.services.scoping import scoped_project_query

logger = logging.getLogger(__name__)

T = TypeVar("T")

RANGE_DAY_OPTIONS = {7, 30, 90, 365}
SUMMARY_RANKING_LIMIT = 8
OPEN_ESCALATION_STATUSES = {
    GovernanceEscalationStatus.OPEN,
    GovernanceEscalationStatus.IN_PROGRESS,
}
ANALYTICS_CACHE_TTL = timedelta(minutes=3)
AnalyticsCacheKey = tuple[UUID | None, str, UUID, int, str | None, str | None]
_analytics_cache: dict[
    AnalyticsCacheKey,
    tuple[datetime, GovernanceAnalyticsRead],
] = {}
_analytics_summary_cache: dict[
    AnalyticsCacheKey,
    tuple[datetime, GovernanceAnalyticsSummaryRead],
] = {}
_analytics_detail_cache: dict[
    AnalyticsCacheKey,
    tuple[datetime, GovernanceAnalyticsDetailRead],
] = {}

ACCEPTED_RECOMMENDATION_STATUSES = {
    GovernanceRecommendationAcceptanceStatus.PARTIALLY_ACCEPTED,
    GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION,
    GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ESCALATION,
}
AT_RISK_LEVELS = {"high_risk", "critical"}
INSIGHTS_TOP_LIMIT = 8


@dataclass(frozen=True)
class AnalyticsCacheInvalidationResult:
    summary_removed: int = 0
    detail_removed: int = 0


def _analytics_cache_key(
    current_user: CurrentUser,
    days: int,
    *,
    project_id: UUID | None = None,
    vertical: str | None = None,
) -> AnalyticsCacheKey:
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id
    normalized_vertical = vertical.strip().lower() if vertical and vertical.strip() else None
    return (
        org_id,
        current_user.role.value,
        current_user.id,
        days,
        str(project_id) if project_id else None,
        normalized_vertical,
    )


def _clear_analytics_cache_by_org(
    cache: dict[AnalyticsCacheKey, tuple[datetime, T]],
    *,
    org_id: UUID | None,
) -> int:
    if org_id is None:
        keys_to_remove = list(cache)
    else:
        keys_to_remove = [key for key in cache if key[0] in {org_id, None}]
    for key in keys_to_remove:
        cache.pop(key, None)
    return len(keys_to_remove)


def clear_governance_analytics_summary_cache(*, org_id: UUID | None) -> int:
    """Clear cached summary reads affected by a committed governance write."""
    return _clear_analytics_cache_by_org(_analytics_summary_cache, org_id=org_id)


def clear_governance_analytics_detail_cache(*, org_id: UUID | None) -> int:
    """Clear cached detail reads affected by a committed governance write."""
    return _clear_analytics_cache_by_org(_analytics_detail_cache, org_id=org_id)


def clear_governance_analytics_caches(
    *,
    org_id: UUID | None,
) -> AnalyticsCacheInvalidationResult:
    """Clear summary/detail analytics caches without touching the database.

    Concrete org writes also clear the super-admin aggregate scope (`org_id=None`).
    If no org is available, clear every summary/detail entry to avoid stale reads.
    """
    return AnalyticsCacheInvalidationResult(
        summary_removed=clear_governance_analytics_summary_cache(org_id=org_id),
        detail_removed=clear_governance_analytics_detail_cache(org_id=org_id),
    )


def _clamp_range(days: int) -> int:
    if days in RANGE_DAY_OPTIONS:
        return days
    return 30


def _empty_charts() -> dict[str, list[GovernanceChartPointRead]]:
    return {
        "dependencies_by_type": [],
        "escalations_by_severity": [],
        "actions_by_status": [],
        "health_distribution": [],
        "most_active_projects": [],
        "recommendation_outcomes": [],
        "affected_departments": [],
    }


def _normalize_vertical_filter(vertical: str | None) -> str | None:
    if vertical is None:
        return None
    cleaned = vertical.strip()
    return cleaned or None


def _filter_projects(
    projects: list[Project],
    *,
    project_id: UUID | None = None,
    vertical: str | None = None,
) -> list[Project]:
    normalized_vertical = _normalize_vertical_filter(vertical)
    filtered = projects
    if project_id is not None:
        filtered = [project for project in filtered if project.id == project_id]
    if normalized_vertical is not None:
        needle = normalized_vertical.casefold()
        filtered = [
            project
            for project in filtered
            if (project.vertical or "").casefold() == needle
        ]
    return filtered


def _project_activity_count(project: GovernanceHealthProjectRead) -> int:
    return (
        project.open_dependencies
        + project.open_escalations
        + project.overdue_actions
        + project.pending_scope_revisions
        + project.blocking_dependencies
    )


def _portfolio_governance_score(project_health: list[GovernanceHealthProjectRead]) -> float:
    if not project_health:
        return 100.0
    return round(mean([project.score for project in project_health]), 1)


def _recommendation_is_accepted(row: GovernanceAIRecommendation) -> bool:
    if row.accepted_at is not None:
        return True
    return row.acceptance_status in ACCEPTED_RECOMMENDATION_STATUSES


def _recommendation_is_dismissed(row: GovernanceAIRecommendation) -> bool:
    if row.dismissed_at is not None:
        return True
    return row.status == GovernanceAIRecommendationStatus.DISMISSED


def _recommendation_is_escalation_suggestion(row: GovernanceAIRecommendation) -> bool:
    if row.auto_detected:
        return True
    return (
        row.recommendation_type == GovernanceAIRecommendationType.ESCALATION_REQUIRED
        and row.trigger_type is not None
    )


def _rate_pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 1)


async def _with_analytics_session(
    fn: Callable[[AsyncSession], Awaitable[T]],
    *,
    semaphore: asyncio.Semaphore,
) -> T:
    """Run a read-only analytics query on an independent session (safe for asyncio.gather)."""
    async with semaphore:
        async with session_scope() as session:
            return await fn(session)


async def _fetch_visible_projects(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[Project]:
    return list(
        (
            await session.execute(scoped_project_query(current_user).order_by(Project.name.asc()))
        ).scalars()
    )


async def _fetch_delivery_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    projects: list[Project] | None = None,
) -> dict[UUID, dict]:
    if not projects:
        return {}
    return await fetch_governance_delivery_signals(
        session,
        current_user,
        [project.id for project in projects],
        projects_by_id={project.id: project for project in projects},
    )


def _trend_window_start(*, today: date, days: int) -> datetime:
    start = today - timedelta(days=days - 1)
    return datetime.combine(start, datetime.min.time(), tzinfo=UTC)


def _risk_level(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "healthy"
    if score >= 60:
        return "moderate_risk"
    if score >= 40:
        return "high_risk"
    return "critical"


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _dt(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC)


def _evidence(
    source_type: str,
    label: str,
    *,
    source_id: UUID | None = None,
    detail: str | None = None,
    project_id: UUID | None = None,
    project_name: str | None = None,
) -> GovernanceEvidenceRead:
    return GovernanceEvidenceRead(
        source_type=source_type,
        source_id=str(source_id) if source_id else None,
        label=label,
        detail=detail,
        project_id=project_id,
        project_name=project_name,
    )


def _chart_points(counter: Counter[str], labels: list[tuple[str, str]]) -> list[GovernanceChartPointRead]:
    return [
        GovernanceChartPointRead(label=label, value=float(counter.get(key, 0)))
        for key, label in labels
    ]


@dataclass(frozen=True)
class _ProjectMetrics:
    open_dependencies: int = 0
    blocking_dependencies: int = 0
    open_escalations: int = 0
    critical_escalations: int = 0
    overdue_actions: int = 0
    pending_scope_revisions: int = 0


async def _fetch_dependency_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, tuple[int, int]]:
    if not can_read_internal_governance(current_user):
        return {}
    stmt = (
        select(
            ProjectDependency.project_id,
            func.count()
            .filter(ProjectDependency.status != GovernanceDependencyStatus.RESOLVED)
            .label("open"),
            func.count()
            .filter(ProjectDependency.status == GovernanceDependencyStatus.BLOCKING)
            .label("blocking"),
        )
        .where(ProjectDependency.deleted_at.is_(None))
        .group_by(ProjectDependency.project_id)
    )
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {
        row.project_id: (int(row.open or 0), int(row.blocking or 0))
        for row in rows
    }


async def _fetch_escalation_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, tuple[int, int]]:
    stmt = (
        select(
            GovernanceEscalation.project_id,
            func.count().label("open"),
            func.count()
            .filter(GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL)
            .label("critical"),
        )
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
        )
        .group_by(GovernanceEscalation.project_id)
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {
        row.project_id: (int(row.open or 0), int(row.critical or 0))
        for row in rows
    }


async def _fetch_overdue_action_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> dict[UUID, int]:
    if not can_read_internal_governance(current_user):
        return {}
    stmt = (
        select(
            GovernanceAction.project_id,
            func.count().label("overdue"),
        )
        .where(GovernanceAction.deleted_at.is_(None))
        .where(_overdue_action_filter(today))
        .group_by(GovernanceAction.project_id)
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {row.project_id: int(row.overdue or 0) for row in rows}


async def _fetch_pending_scope_counts_by_project(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, int]:
    if not can_read_internal_governance(current_user):
        return {}
    stmt = (
        select(
            ProjectScopeState.project_id,
            func.count().label("pending"),
        )
        .where(
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
        )
        .group_by(ProjectScopeState.project_id)
    )
    stmt = _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)
    rows = (await session.execute(stmt)).all()
    return {row.project_id: int(row.pending or 0) for row in rows}


def _merge_project_metrics(
    project_id: UUID,
    *,
    dependency_counts: dict[UUID, tuple[int, int]],
    escalation_counts: dict[UUID, tuple[int, int]],
    overdue_actions: dict[UUID, int],
    pending_scopes: dict[UUID, int],
) -> _ProjectMetrics:
    dep_open, dep_blocking = dependency_counts.get(project_id, (0, 0))
    esc_open, esc_critical = escalation_counts.get(project_id, (0, 0))
    return _ProjectMetrics(
        open_dependencies=dep_open,
        blocking_dependencies=dep_blocking,
        open_escalations=esc_open,
        critical_escalations=esc_critical,
        overdue_actions=overdue_actions.get(project_id, 0),
        pending_scope_revisions=pending_scopes.get(project_id, 0),
    )


async def _fetch_enum_counter(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    model,
    enum_column,
    org_column,
) -> Counter[str]:
    stmt = (
        select(enum_column, func.count().label("count"))
        .where(model.deleted_at.is_(None))
        .group_by(enum_column)
    )
    stmt = _apply_org_filter(stmt, org_column, current_user)
    rows = (await session.execute(stmt)).all()
    return Counter({_enum_value(row[0]): int(row.count or 0) for row in rows})


async def _fetch_action_status_counter(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> Counter[str]:
    if not can_read_internal_governance(current_user):
        return Counter()
    stmt = (
        select(
            func.count()
            .filter(GovernanceAction.status == GovernanceActionStatus.COMPLETED)
            .label("completed"),
            func.count()
            .filter(
                and_(
                    GovernanceAction.status == GovernanceActionStatus.IN_PROGRESS,
                    ~_overdue_action_filter(today),
                )
            )
            .label("in_progress"),
            func.count()
            .filter(
                and_(
                    GovernanceAction.status == GovernanceActionStatus.OPEN,
                    ~_overdue_action_filter(today),
                )
            )
            .label("open"),
            func.count().filter(_overdue_action_filter(today)).label("overdue"),
        )
        .select_from(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None))
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    row = (await session.execute(stmt)).one()
    return Counter(
        {
            "completed": int(row.completed or 0),
            "in_progress": int(row.in_progress or 0),
            "open": int(row.open or 0),
            "overdue": int(row.overdue or 0),
        }
    )


async def _fetch_window_escalations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[GovernanceEscalation]:
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(GovernanceEscalation).where(
        GovernanceEscalation.deleted_at.is_(None),
        or_(
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
            GovernanceEscalation.resolved_at >= window_start,
            GovernanceEscalation.raised_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_window_actions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[GovernanceAction]:
    if not can_read_internal_governance(current_user):
        return []
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(GovernanceAction).where(
        GovernanceAction.deleted_at.is_(None),
        or_(
            GovernanceAction.status != GovernanceActionStatus.COMPLETED,
            GovernanceAction.completed_at >= window_start,
            GovernanceAction.created_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_blocking_dependencies(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[ProjectDependency]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = (
        select(ProjectDependency)
        .where(
            ProjectDependency.deleted_at.is_(None),
            ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
        )
        .order_by(ProjectDependency.created_at.desc())
    )
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_critical_escalations(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceEscalation]:
    stmt = (
        select(GovernanceEscalation)
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
            GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
        )
        .order_by(GovernanceEscalation.raised_at.desc())
    )
    stmt = _apply_org_filter(stmt, GovernanceEscalation.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_overdue_actions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> list[GovernanceAction]:
    if not can_read_internal_governance(current_user):
        return []
    stmt = (
        select(GovernanceAction)
        .where(GovernanceAction.deleted_at.is_(None), _overdue_action_filter(today))
        .order_by(GovernanceAction.due_date.asc())
    )
    stmt = _apply_org_filter(stmt, GovernanceAction.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


def _derive_project_evidence(
    blocking_dependencies: list[ProjectDependency],
    critical_escalations: list[GovernanceEscalation],
    *,
    project_ids: list[UUID],
    project_names: dict[UUID, str],
) -> dict[UUID, list[GovernanceEvidenceRead]]:
    if not project_ids:
        return {}

    allowed = set(project_ids)
    evidence_by_project: dict[UUID, list[GovernanceEvidenceRead]] = defaultdict(list)

    for dep in blocking_dependencies:
        if dep.project_id not in allowed:
            continue
        if len(evidence_by_project[dep.project_id]) >= 3:
            continue
        evidence_by_project[dep.project_id].append(
            _evidence(
                "dependency",
                dep.title,
                source_id=dep.id,
                detail=f"status={_enum_value(dep.status)}, overdue_days={dependency_overdue_days(dep)}",
                project_id=dep.project_id,
                project_name=project_names.get(dep.project_id),
            )
        )

    for esc in critical_escalations:
        if esc.project_id not in allowed:
            continue
        if len(evidence_by_project[esc.project_id]) >= 3:
            continue
        evidence_by_project[esc.project_id].append(
            _evidence(
                "escalation",
                esc.title,
                source_id=esc.id,
                detail=f"severity={_enum_value(esc.severity)}, status={_enum_value(esc.status)}",
                project_id=esc.project_id,
                project_name=project_names.get(esc.project_id),
            )
        )

    return evidence_by_project


async def _fetch_project_evidence(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_ids: list[UUID],
    project_names: dict[UUID, str],
    blocking_dependencies: list[ProjectDependency] | None = None,
    critical_escalations: list[GovernanceEscalation] | None = None,
) -> dict[UUID, list[GovernanceEvidenceRead]]:
    if not project_ids or not can_read_internal_governance(current_user):
        return {}

    if blocking_dependencies is not None and critical_escalations is not None:
        return _derive_project_evidence(
            blocking_dependencies,
            critical_escalations,
            project_ids=project_ids,
            project_names=project_names,
        )

    async def _blocking_rows(db: AsyncSession) -> list[ProjectDependency]:
        blocking_stmt = (
            select(ProjectDependency)
            .where(
                ProjectDependency.deleted_at.is_(None),
                ProjectDependency.status == GovernanceDependencyStatus.BLOCKING,
                ProjectDependency.project_id.in_(project_ids),
            )
            .order_by(ProjectDependency.created_at.desc())
        )
        blocking_stmt = _apply_org_filter(blocking_stmt, ProjectDependency.org_id, current_user)
        return list((await db.execute(blocking_stmt)).scalars())

    async def _critical_rows(db: AsyncSession) -> list[GovernanceEscalation]:
        critical_stmt = (
            select(GovernanceEscalation)
            .where(
                GovernanceEscalation.deleted_at.is_(None),
                GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
                GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL,
                GovernanceEscalation.project_id.in_(project_ids),
            )
            .order_by(GovernanceEscalation.raised_at.desc())
        )
        critical_stmt = _apply_org_filter(critical_stmt, GovernanceEscalation.org_id, current_user)
        return list((await db.execute(critical_stmt)).scalars())

    blocking = await _blocking_rows(session)
    critical = await _critical_rows(session)

    evidence_by_project: dict[UUID, list[GovernanceEvidenceRead]] = defaultdict(list)
    for dep in blocking:
        if len(evidence_by_project[dep.project_id]) >= 3:
            continue
        evidence_by_project[dep.project_id].append(
            _evidence(
                "dependency",
                dep.title,
                source_id=dep.id,
                detail=f"status={_enum_value(dep.status)}, overdue_days={dependency_overdue_days(dep)}",
                project_id=dep.project_id,
                project_name=project_names.get(dep.project_id),
            )
        )
    for esc in critical:
        if len(evidence_by_project[esc.project_id]) >= 3:
            continue
        evidence_by_project[esc.project_id].append(
            _evidence(
                "escalation",
                esc.title,
                source_id=esc.id,
                detail=f"severity={_enum_value(esc.severity)}, status={_enum_value(esc.status)}",
                project_id=esc.project_id,
                project_name=project_names.get(esc.project_id),
            )
        )
    return evidence_by_project


async def _fetch_recent_activity(
    session: AsyncSession,
    current_user: CurrentUser,
    project_names: dict[UUID, str],
) -> list[GovernanceEvidenceRead]:
    rows: list[tuple[datetime, GovernanceEvidenceRead]] = []

    if can_read_internal_governance(current_user):
        dep_stmt = (
            select(ProjectDependency)
            .where(ProjectDependency.deleted_at.is_(None), ProjectDependency.created_at.is_not(None))
            .order_by(ProjectDependency.created_at.desc())
            .limit(8)
        )
        dep_stmt = _apply_org_filter(dep_stmt, ProjectDependency.org_id, current_user)
        for dep in (await session.execute(dep_stmt)).scalars():
            rows.append(
                (
                    dep.created_at,
                    _evidence(
                        "dependency",
                        dep.title,
                        source_id=dep.id,
                        detail=f"status={_enum_value(dep.status)}",
                        project_id=dep.project_id,
                        project_name=project_names.get(dep.project_id),
                    ),
                )
            )

        action_stmt = (
            select(GovernanceAction)
            .where(GovernanceAction.deleted_at.is_(None), GovernanceAction.created_at.is_not(None))
            .order_by(GovernanceAction.created_at.desc())
            .limit(8)
        )
        action_stmt = _apply_org_filter(action_stmt, GovernanceAction.org_id, current_user)
        for action in (await session.execute(action_stmt)).scalars():
            rows.append(
                (
                    action.created_at,
                    _evidence(
                        "action",
                        action.title,
                        source_id=action.id,
                        detail=f"status={effective_action_status(action).value}",
                        project_id=action.project_id,
                        project_name=project_names.get(action.project_id),
                    ),
                )
            )

    esc_stmt = (
        select(GovernanceEscalation)
        .where(GovernanceEscalation.deleted_at.is_(None), GovernanceEscalation.raised_at.is_not(None))
        .order_by(GovernanceEscalation.raised_at.desc())
        .limit(8)
    )
    esc_stmt = _apply_org_filter(esc_stmt, GovernanceEscalation.org_id, current_user)
    for esc in (await session.execute(esc_stmt)).scalars():
        rows.append(
            (
                esc.raised_at,
                _evidence(
                    "escalation",
                    esc.title,
                    source_id=esc.id,
                    detail=f"severity={_enum_value(esc.severity)}",
                    project_id=esc.project_id,
                    project_name=project_names.get(esc.project_id),
                ),
            )
        )

    return [item for _, item in sorted(rows, key=lambda row: row[0], reverse=True)[:8]]


def _delivery_penalty(confidence: float | None, traffic: str | None) -> int:
    if traffic == "red":
        return 14
    if traffic == "yellow":
        return 7
    if confidence is not None and confidence < 40:
        return 10
    if confidence is not None and confidence < 65:
        return 5
    return 0


def _score_project_from_metrics(
    project: Project,
    metrics: _ProjectMetrics,
    *,
    delivery_signal: dict | None,
    evidence: list[GovernanceEvidenceRead] | None = None,
) -> GovernanceHealthProjectRead:
    project_id = project.id
    delivery_dashboard = delivery_signal.get("dashboard") if delivery_signal else None
    delivery_confidence = (
        float(delivery_dashboard.get("confidence"))
        if delivery_dashboard and delivery_dashboard.get("confidence") is not None
        else None
    )
    delivery_traffic = delivery_dashboard.get("traffic_light") if delivery_dashboard else None
    quality_snapshot = None
    if delivery_dashboard:
        quality_snapshot = (delivery_dashboard.get("overview") or {}).get("quality_snapshot")
    quality_risk = "elevated" if quality_snapshot and quality_snapshot.get("has_drift_alert") else None

    non_critical_open = max(0, metrics.open_escalations - metrics.critical_escalations)
    penalty = (
        metrics.blocking_dependencies * 12
        + metrics.critical_escalations * 16
        + non_critical_open * 8
        + metrics.overdue_actions * 7
        + metrics.pending_scope_revisions * 9
        + _delivery_penalty(delivery_confidence, delivery_traffic)
        + (8 if quality_risk else 0)
    )
    score = max(0, min(100, 100 - penalty))
    priority = (
        metrics.critical_escalations * 30
        + metrics.blocking_dependencies * 20
        + metrics.overdue_actions * 10
        + metrics.pending_scope_revisions * 10
        + (15 if delivery_traffic == "red" else 7 if delivery_traffic == "yellow" else 0)
    )

    project_evidence = list(evidence or [])
    if delivery_dashboard and delivery_traffic in {"red", "yellow"}:
        project_evidence.append(
            _evidence(
                "delivery_signal",
                "Delivery confidence",
                detail=f"confidence={delivery_confidence}, traffic_light={delivery_traffic}",
                project_id=project_id,
                project_name=project.name,
            )
        )

    return GovernanceHealthProjectRead(
        project_id=project_id,
        project_name=project.name,
        score=score,
        risk_level=_risk_level(score),
        priority=priority,
        blocking_dependencies=metrics.blocking_dependencies,
        open_dependencies=metrics.open_dependencies,
        open_escalations=metrics.open_escalations,
        critical_escalations=metrics.critical_escalations,
        overdue_actions=metrics.overdue_actions,
        pending_scope_revisions=metrics.pending_scope_revisions,
        delivery_confidence=delivery_confidence,
        delivery_traffic_light=delivery_traffic,
        quality_risk=quality_risk,
        workforce_risk=None,
        trend="stable",
        vertical=project.vertical or None,
        evidence=project_evidence,
    )


def _build_insights(
    project_health: list[GovernanceHealthProjectRead],
    dependencies: list,
    escalations: list,
    actions: list[GovernanceAction],
) -> list[GovernanceInsightRead]:
    insights: list[GovernanceInsightRead] = []
    critical_projects = [project for project in project_health if project.risk_level == "critical"]
    high_risk_projects = [
        project for project in project_health if project.risk_level in {"critical", "high_risk"}
    ]
    blocking = [dep for dep in dependencies if dep.status == GovernanceDependencyStatus.BLOCKING]
    critical_escalations = [
        esc
        for esc in escalations
        if esc.status in OPEN_ESCALATION_STATUSES
        and esc.severity == GovernanceEscalationSeverity.CRITICAL
    ]
    overdue_actions = [action for action in actions if effective_action_status(action).value == "overdue"]

    if critical_projects:
        evidence = [
            _evidence(
                "governance_health",
                project.project_name,
                detail=f"score={project.score}, risk_level={project.risk_level}",
                project_id=project.project_id,
                project_name=project.project_name,
            )
            for project in critical_projects[:3]
        ]
        insights.append(
            GovernanceInsightRead(
                title=f"{len(critical_projects)} project(s) are in critical governance status",
                detail="Leadership attention is required because their health scores are below 40.",
                severity="critical",
                evidence=evidence,
            )
        )
    elif high_risk_projects:
        evidence = [
            _evidence(
                "governance_health",
                project.project_name,
                detail=f"score={project.score}, risk_level={project.risk_level}",
                project_id=project.project_id,
                project_name=project.project_name,
            )
            for project in high_risk_projects[:3]
        ]
        insights.append(
            GovernanceInsightRead(
                title=f"{len(high_risk_projects)} project(s) need governance attention",
                detail="These projects have high-risk or critical governance health scores.",
                severity="high",
                evidence=evidence,
            )
        )

    if blocking:
        dep_types = Counter(_enum_value(dep.dependency_type) for dep in blocking)
        top_type, count = dep_types.most_common(1)[0]
        insights.append(
            GovernanceInsightRead(
                title=f"{top_type.replace('_', ' ').title()} dependencies are the largest blocker group",
                detail=f"{count} blocking dependencies are currently classified as {top_type}.",
                severity="high",
                evidence=[
                    _evidence(
                        "dependency",
                        dep.title,
                        source_id=dep.id,
                        detail=f"type={_enum_value(dep.dependency_type)}, status={_enum_value(dep.status)}",
                        project_id=dep.project_id,
                    )
                    for dep in blocking
                    if _enum_value(dep.dependency_type) == top_type
                ][:3],
            )
        )

    if critical_escalations:
        insights.append(
            GovernanceInsightRead(
                title=f"{len(critical_escalations)} critical escalation(s) remain open",
                detail="Critical escalations are the strongest current governance health penalty.",
                severity="critical",
                evidence=[
                    _evidence(
                        "escalation",
                        esc.title,
                        source_id=esc.id,
                        detail=f"severity={_enum_value(esc.severity)}, status={_enum_value(esc.status)}",
                        project_id=esc.project_id,
                    )
                    for esc in critical_escalations[:3]
                ],
            )
        )

    if overdue_actions:
        insights.append(
            GovernanceInsightRead(
                title=f"{len(overdue_actions)} governance action(s) are overdue",
                detail="Overdue actions reduce SLA adherence and increase portfolio governance risk.",
                severity="medium",
                evidence=[
                    _evidence(
                        "action",
                        action.title,
                        source_id=action.id,
                        detail=f"due_date={action.due_date}, status={effective_action_status(action).value}",
                        project_id=action.project_id,
                    )
                    for action in overdue_actions[:3]
                ],
            )
        )

    return [insight for insight in insights if insight.evidence]


def _build_recommendations(
    ranking: list[GovernanceHealthProjectRead],
) -> list[GovernanceRecommendationRead]:
    recommendations: list[GovernanceRecommendationRead] = []
    for project in ranking[:5]:
        if project.critical_escalations:
            recommendations.append(
                GovernanceRecommendationRead(
                    title="Escalate critical governance decisions to leadership",
                    detail="Critical escalations are open and materially lowering governance health.",
                    priority="critical",
                    project_id=project.project_id,
                    project_name=project.project_name,
                    evidence=project.evidence[:3],
                )
            )
        elif project.blocking_dependencies:
            recommendations.append(
                GovernanceRecommendationRead(
                    title="Assign owners and decision dates to blocking dependencies",
                    detail="Blocking dependencies are the primary governance risk driver for this project.",
                    priority="high",
                    project_id=project.project_id,
                    project_name=project.project_name,
                    evidence=project.evidence[:3],
                )
            )
        elif project.pending_scope_revisions:
            recommendations.append(
                GovernanceRecommendationRead(
                    title="Review pending scope revision",
                    detail="Scope is pending revision and should be confirmed against current delivery commitments.",
                    priority="medium",
                    project_id=project.project_id,
                    project_name=project.project_name,
                    evidence=project.evidence[:3],
                )
            )
    return [item for item in recommendations if item.evidence]


def _count_escalations_created(
    escalations: list,
    *,
    today: date,
    days: int,
) -> int:
    start = today - timedelta(days=days - 1)
    count = 0
    for escalation in escalations:
        raised_at = _dt(getattr(escalation, "raised_at", None))
        if raised_at is not None and start <= raised_at.date() <= today:
            count += 1
    return count


def _build_insights_kpis(
    *,
    project_health: list[GovernanceHealthProjectRead],
    escalations_created: int,
    recommendations: list[GovernanceAIRecommendation],
    sla_adherence_pct: float,
) -> GovernanceInsightsKpisRead:
    created = len(recommendations)
    accepted = sum(1 for row in recommendations if _recommendation_is_accepted(row))
    dismissed = sum(1 for row in recommendations if _recommendation_is_dismissed(row))
    return GovernanceInsightsKpisRead(
        portfolio_governance_score=_portfolio_governance_score(project_health),
        projects_at_risk=sum(1 for row in project_health if row.risk_level in AT_RISK_LEVELS),
        recommendation_acceptance_rate_pct=_rate_pct(accepted, created),
        recommendation_dismissal_rate_pct=_rate_pct(dismissed, created),
        escalations_created=escalations_created,
        recommendations_created=created,
        sla_adherence_pct=round(sla_adherence_pct, 1),
    )


def _build_top_governance_risks(
    project_health: list[GovernanceHealthProjectRead],
    escalations: list,
) -> list[GovernanceNamedCountRead]:
    rows: list[GovernanceNamedCountRead] = []
    for project in sorted(
        [row for row in project_health if row.risk_level in AT_RISK_LEVELS],
        key=lambda row: (row.score, -row.priority),
    )[:INSIGHTS_TOP_LIMIT]:
        rows.append(
            GovernanceNamedCountRead(
                label=project.project_name,
                count=max(1, project.critical_escalations + project.blocking_dependencies),
                project_id=project.project_id,
                project_name=project.project_name,
                vertical=project.vertical,
                detail=f"score={project.score}, risk_level={project.risk_level}",
            )
        )
    critical_open = [
        esc
        for esc in escalations
        if esc.status in OPEN_ESCALATION_STATUSES
        and esc.severity == GovernanceEscalationSeverity.CRITICAL
    ]
    if critical_open and len(rows) < INSIGHTS_TOP_LIMIT:
        rows.append(
            GovernanceNamedCountRead(
                label="Open critical escalations",
                count=len(critical_open),
                detail="critical open escalations across filtered portfolio",
            )
        )
    return rows[:INSIGHTS_TOP_LIMIT]


def _build_top_recurring_blockers(dependencies: list) -> list[GovernanceNamedCountRead]:
    blocking = [dep for dep in dependencies if dep.status == GovernanceDependencyStatus.BLOCKING]
    by_type = Counter(_enum_value(dep.dependency_type) for dep in blocking)
    rows: list[GovernanceNamedCountRead] = []
    for dep_type, count in by_type.most_common(INSIGHTS_TOP_LIMIT):
        sample = next(
            (dep for dep in blocking if _enum_value(dep.dependency_type) == dep_type),
            None,
        )
        rows.append(
            GovernanceNamedCountRead(
                label=dep_type.replace("_", " ").title(),
                count=count,
                project_id=sample.project_id if sample else None,
                detail=f"blocking dependency type={dep_type}",
            )
        )
    return rows


def _build_top_mitigation_failures(
    recommendations: list[GovernanceAIRecommendation],
) -> list[GovernanceNamedCountRead]:
    failures = [
        row
        for row in recommendations
        if row.trigger_type == GovernanceEscalationTriggerType.REPEATED_MITIGATION_FAILURE
        or (
            row.recommendation_type == GovernanceAIRecommendationType.DEPENDENCY_MITIGATION
            and _recommendation_is_dismissed(row)
        )
    ]
    by_label = Counter(row.title for row in failures)
    rows: list[GovernanceNamedCountRead] = []
    for title, count in by_label.most_common(INSIGHTS_TOP_LIMIT):
        sample = next((row for row in failures if row.title == title), None)
        rows.append(
            GovernanceNamedCountRead(
                label=title,
                count=count,
                project_id=sample.project_id if sample else None,
                detail=(
                    f"trigger={_enum_value(sample.trigger_type)}"
                    if sample and sample.trigger_type
                    else "dismissed dependency mitigation"
                ),
            )
        )
    return rows


def _build_most_affected_projects(
    project_health: list[GovernanceHealthProjectRead],
) -> list[GovernanceNamedCountRead]:
    ranked = sorted(project_health, key=_project_activity_count, reverse=True)
    return [
        GovernanceNamedCountRead(
            label=project.project_name,
            count=_project_activity_count(project),
            project_id=project.project_id,
            project_name=project.project_name,
            vertical=project.vertical,
            detail=f"score={project.score}, priority={project.priority}",
        )
        for project in ranked[:INSIGHTS_TOP_LIMIT]
        if _project_activity_count(project) > 0
    ]


def _build_most_affected_departments(
    project_health: list[GovernanceHealthProjectRead],
) -> list[GovernanceNamedCountRead]:
    activity_by_vertical: Counter[str] = Counter()
    for project in project_health:
        vertical = project.vertical or "Unassigned"
        activity_by_vertical[vertical] += _project_activity_count(project)
    return [
        GovernanceNamedCountRead(
            label=vertical,
            count=count,
            vertical=vertical,
            detail="open governance activity across projects",
        )
        for vertical, count in activity_by_vertical.most_common(INSIGHTS_TOP_LIMIT)
        if count > 0
    ]


def _build_risk_heatmap(
    project_health: list[GovernanceHealthProjectRead],
) -> list[GovernanceRiskHeatmapCellRead]:
    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for project in project_health:
        vertical = project.vertical or "Unassigned"
        buckets[(vertical, project.risk_level)].append(project.score)
    cells = [
        GovernanceRiskHeatmapCellRead(
            vertical=vertical,
            risk_level=risk_level,
            project_count=len(scores),
            avg_score=round(mean(scores), 1),
        )
        for (vertical, risk_level), scores in buckets.items()
    ]
    return sorted(cells, key=lambda cell: (cell.vertical, cell.risk_level))


def _recommendation_outcome_charts(
    recommendations: list[GovernanceAIRecommendation],
) -> list[GovernanceChartPointRead]:
    accepted = sum(1 for row in recommendations if _recommendation_is_accepted(row))
    dismissed = sum(1 for row in recommendations if _recommendation_is_dismissed(row))
    active = sum(
        1
        for row in recommendations
        if not _recommendation_is_accepted(row) and not _recommendation_is_dismissed(row)
    )
    return [
        GovernanceChartPointRead(label="Accepted", value=float(accepted)),
        GovernanceChartPointRead(label="Dismissed", value=float(dismissed)),
        GovernanceChartPointRead(label="Open", value=float(active)),
    ]


def _affected_department_charts(
    project_health: list[GovernanceHealthProjectRead],
) -> list[GovernanceChartPointRead]:
    return [
        GovernanceChartPointRead(label=row.label, value=float(row.count))
        for row in _build_most_affected_departments(project_health)
    ]


async def _fetch_ai_recommendations_for_insights(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
    project_ids: set[UUID] | None = None,
) -> list[GovernanceAIRecommendation]:
    window_start = _trend_window_start(today=today, days=days)
    stmt = (
        select(GovernanceAIRecommendation)
        .where(
            GovernanceAIRecommendation.deleted_at.is_(None),
            GovernanceAIRecommendation.generated_at >= window_start,
        )
        .order_by(GovernanceAIRecommendation.generated_at.desc())
        .limit(2000)
    )
    stmt = _apply_org_filter(stmt, GovernanceAIRecommendation.org_id, current_user)
    if project_ids is not None:
        stmt = stmt.where(
            or_(
                GovernanceAIRecommendation.project_id.in_(project_ids),
                GovernanceAIRecommendation.project_id.is_(None),
            )
        )
    return list((await session.execute(stmt)).scalars())


def _filter_rows_by_project_ids(rows: list, project_ids: set[UUID]) -> list:
    return [row for row in rows if getattr(row, "project_id", None) in project_ids]


async def get_governance_analytics(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
    project_id: UUID | None = None,
    vertical: str | None = None,
) -> GovernanceAnalyticsRead:
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    normalized_vertical = _normalize_vertical_filter(vertical)
    cache_key = _analytics_cache_key(
        current_user,
        effective_days,
        project_id=project_id,
        vertical=normalized_vertical,
    )
    now = datetime.now(UTC)
    cached = _analytics_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
        return cached[1]

    total_started = perf_counter()
    today = now.date()

    projects = _filter_projects(
        await _fetch_visible_projects(session, current_user),
        project_id=project_id,
        vertical=normalized_vertical,
    )
    project_ids = {project.id for project in projects}
    project_names = {project.id: project.name for project in projects}

    counts_started = perf_counter()
    dependency_counts = await _fetch_dependency_counts_by_project(session, current_user)
    escalation_counts = await _fetch_escalation_counts_by_project(session, current_user)
    overdue_by_project = await _fetch_overdue_action_counts_by_project(
        session, current_user, today=today
    )
    pending_by_project = await _fetch_pending_scope_counts_by_project(session, current_user)
    counts_ms = round((perf_counter() - counts_started) * 1000, 1)

    portfolio_started = perf_counter()
    delivery_by_project = await _fetch_delivery_by_project(
        session, current_user, projects=projects
    )
    portfolio_ms = round((perf_counter() - portfolio_started) * 1000, 1)

    project_health: list[GovernanceHealthProjectRead] = []
    for project in projects:
        metrics = _merge_project_metrics(
            project.id,
            dependency_counts=dependency_counts,
            escalation_counts=escalation_counts,
            overdue_actions=overdue_by_project,
            pending_scopes=pending_by_project,
        )
        project_health.append(
            _score_project_from_metrics(
                project,
                metrics,
                delivery_signal=delivery_by_project.get(project.id),
            )
        )

    ranking = sorted(project_health, key=lambda row: (row.score, -row.priority, row.project_name))
    top_project_ids = [row.project_id for row in ranking[:10]]

    blocking_dependencies = _filter_rows_by_project_ids(
        await _fetch_blocking_dependencies(session, current_user),
        project_ids,
    ) if project_ids else []
    critical_escalations = _filter_rows_by_project_ids(
        await _fetch_critical_escalations(session, current_user),
        project_ids,
    ) if project_ids else []

    evidence_started = perf_counter()
    evidence_by_project = await _fetch_project_evidence(
        session,
        current_user,
        project_ids=top_project_ids,
        project_names=project_names,
        blocking_dependencies=blocking_dependencies,
        critical_escalations=critical_escalations,
    )
    evidence_ms = round((perf_counter() - evidence_started) * 1000, 1)

    if evidence_by_project:
        enriched: list[GovernanceHealthProjectRead] = []
        for row in project_health:
            fetched = evidence_by_project.get(row.project_id, [])
            if not fetched:
                enriched.append(row)
                continue
            delivery_evidence = [
                item for item in row.evidence if item.source_type == "delivery_signal"
            ]
            enriched.append(row.model_copy(update={"evidence": fetched + delivery_evidence}))
        project_health = enriched
        ranking = sorted(
            project_health, key=lambda row: (row.score, -row.priority, row.project_name)
        )

    window_metrics_started = perf_counter()
    window_escalations = await _fetch_window_escalations(
        session, current_user, today=today, days=effective_days
    )
    window_actions = await _fetch_window_actions(
        session, current_user, today=today, days=effective_days
    )
    if project_ids:
        window_escalations = _filter_rows_by_project_ids(window_escalations, project_ids)
        window_actions = _filter_rows_by_project_ids(window_actions, project_ids)

    ai_recommendations = await _fetch_ai_recommendations_for_insights(
        session,
        current_user,
        today=today,
        days=effective_days,
        project_ids=project_ids or None,
    )

    async def _fetch_chart_and_activity() -> tuple[
        Counter[str],
        Counter[str],
        Counter[str],
        list[GovernanceAction],
        list[GovernanceEvidenceRead],
    ]:
        dep_type_counter = await _fetch_enum_counter(
            session,
            current_user,
            model=ProjectDependency,
            enum_column=ProjectDependency.dependency_type,
            org_column=ProjectDependency.org_id,
        )
        esc_severity_counter = await _fetch_enum_counter(
            session,
            current_user,
            model=GovernanceEscalation,
            enum_column=GovernanceEscalation.severity,
            org_column=GovernanceEscalation.org_id,
        )
        action_status_counter = await _fetch_action_status_counter(session, current_user, today=today)
        overdue_actions = await _fetch_overdue_actions(session, current_user, today=today)
        recent_activity = await _fetch_recent_activity(session, current_user, project_names)
        if project_ids:
            overdue_actions = _filter_rows_by_project_ids(overdue_actions, project_ids)
            recent_activity = [
                item
                for item in recent_activity
                if item.project_id is None or item.project_id in project_ids
            ]
        return (
            dep_type_counter,
            esc_severity_counter,
            action_status_counter,
            overdue_actions,
            recent_activity,
        )

    (
        dep_type_counter,
        esc_severity_counter,
        action_status_counter,
        overdue_actions,
        recent_activity,
    ) = await _fetch_chart_and_activity()
    window_metrics_ms = round((perf_counter() - window_metrics_started) * 1000, 1)

    insights_kpis = _build_insights_kpis(
        project_health=project_health,
        escalations_created=_count_escalations_created(
            window_escalations,
            today=today,
            days=effective_days,
        ),
        recommendations=ai_recommendations,
        sla_adherence_pct=calculate_sla_adherence_pct(window_actions),
    )
    top_governance_risks = _build_top_governance_risks(project_health, critical_escalations)
    top_recurring_blockers = _build_top_recurring_blockers(blocking_dependencies)
    top_recurring_mitigation_failures = _build_top_mitigation_failures(ai_recommendations)
    most_affected_projects = _build_most_affected_projects(project_health)
    most_affected_departments = _build_most_affected_departments(project_health)
    risk_heatmap = _build_risk_heatmap(project_health)

    charts = {
        "dependencies_by_type": _chart_points(
            dep_type_counter,
            [
                ("client_action", "Client"),
                ("internal", "Internal"),
                ("external", "External"),
            ],
        ),
        "escalations_by_severity": _chart_points(
            esc_severity_counter,
            [
                ("low", "Low"),
                ("medium", "Medium"),
                ("high", "High"),
                ("critical", "Critical"),
            ],
        ),
        "actions_by_status": _chart_points(
            action_status_counter,
            [
                ("open", "Open"),
                ("in_progress", "In Progress"),
                ("completed", "Completed"),
                ("overdue", "Overdue"),
            ],
        ),
        "health_distribution": _chart_points(
            Counter(row.risk_level for row in project_health),
            [
                ("excellent", "Excellent"),
                ("healthy", "Healthy"),
                ("moderate_risk", "Moderate"),
                ("high_risk", "High Risk"),
                ("critical", "Critical"),
            ],
        ),
        "most_active_projects": [
            GovernanceChartPointRead(
                label=project.project_name,
                value=float(_project_activity_count(project)),
                secondary_value=float(project.score),
            )
            for project in sorted(project_health, key=lambda row: row.priority, reverse=True)[:8]
        ],
        "recommendation_outcomes": _recommendation_outcome_charts(ai_recommendations),
        "affected_departments": _affected_department_charts(project_health),
    }

    recommendations_started = perf_counter()
    insights = _build_insights(
        project_health,
        blocking_dependencies,
        critical_escalations,
        overdue_actions,
    )
    recommendations = _build_recommendations(ranking)
    recommendations_ms = round((perf_counter() - recommendations_started) * 1000, 1)

    analytics = GovernanceAnalyticsRead(
        generated_at=datetime.now(UTC),
        date_range_days=effective_days,
        project_health=project_health,
        portfolio_risk_ranking=ranking,
        insights=insights,
        recommendations=recommendations,
        charts=charts,
        recent_activity=recent_activity,
        export_sections=[
            "Charts",
            "Executive Insights",
            "Governance Health",
            "Evidence Appendix",
            "Insights KPIs",
        ],
        portfolio_governance_score=insights_kpis.portfolio_governance_score,
        insights_kpis=insights_kpis,
        top_governance_risks=top_governance_risks,
        top_recurring_blockers=top_recurring_blockers,
        top_recurring_mitigation_failures=top_recurring_mitigation_failures,
        most_affected_projects=most_affected_projects,
        most_affected_departments=most_affected_departments,
        risk_heatmap=risk_heatmap,
    )
    _analytics_cache[cache_key] = (now, analytics)

    total_ms = round((perf_counter() - total_started) * 1000, 1)
    wave_ms = round(max(counts_ms, portfolio_ms, window_metrics_ms, evidence_ms), 1)
    logger.info(
        "governance_analytics_timing org_id=%s role=%s days=%s total_ms=%s wave_ms=%s "
        "counts_ms=%s window_metrics_ms=%s portfolio_ms=%s evidence_ms=%s recommendations_ms=%s",
        str(current_user.org_id) if current_user.org_id else None,
        current_user.role.value,
        effective_days,
        total_ms,
        wave_ms,
        counts_ms,
        window_metrics_ms,
        portfolio_ms,
        evidence_ms,
        recommendations_ms,
        extra={
            "endpoint": "GET /governance/analytics",
            "org_id": str(current_user.org_id) if current_user.org_id else None,
            "role": current_user.role.value,
            "days": effective_days,
            "total_ms": total_ms,
            "wave_ms": wave_ms,
            "counts_ms": counts_ms,
            "window_metrics_ms": window_metrics_ms,
            "portfolio_ms": portfolio_ms,
            "evidence_ms": evidence_ms,
            "recommendations_ms": recommendations_ms,
        },
    )
    return analytics


def _summary_health_charts(
    project_health: list[GovernanceHealthProjectRead],
) -> dict[str, list[GovernanceChartPointRead]]:
    return {
        "health_distribution": _chart_points(
            Counter(row.risk_level for row in project_health),
            [
                ("excellent", "Excellent"),
                ("healthy", "Healthy"),
                ("moderate_risk", "Moderate"),
                ("high_risk", "High Risk"),
                ("critical", "Critical"),
            ],
        ),
    }


def _summary_project_metrics_stmt(current_user: CurrentUser, *, today: date) -> Select:
    dep_agg = (
        select(
            ProjectDependency.project_id.label("project_id"),
            func.count()
            .filter(ProjectDependency.status != GovernanceDependencyStatus.RESOLVED)
            .label("open"),
            func.count()
            .filter(ProjectDependency.status == GovernanceDependencyStatus.BLOCKING)
            .label("blocking"),
        )
        .where(ProjectDependency.deleted_at.is_(None))
        .group_by(ProjectDependency.project_id)
    )
    dep_agg = _apply_org_filter(dep_agg, ProjectDependency.org_id, current_user).subquery(
        "summary_dep_agg"
    )

    esc_agg = (
        select(
            GovernanceEscalation.project_id.label("project_id"),
            func.count().label("open"),
            func.count()
            .filter(GovernanceEscalation.severity == GovernanceEscalationSeverity.CRITICAL)
            .label("critical"),
        )
        .where(
            GovernanceEscalation.deleted_at.is_(None),
            GovernanceEscalation.status.in_(OPEN_ESCALATION_STATUSES),
        )
        .group_by(GovernanceEscalation.project_id)
    )
    esc_agg = _apply_org_filter(esc_agg, GovernanceEscalation.org_id, current_user).subquery(
        "summary_esc_agg"
    )

    overdue_agg = (
        select(
            GovernanceAction.project_id.label("project_id"),
            func.count().label("overdue"),
        )
        .where(GovernanceAction.deleted_at.is_(None))
        .where(_overdue_action_filter(today))
        .group_by(GovernanceAction.project_id)
    )
    overdue_agg = _apply_org_filter(overdue_agg, GovernanceAction.org_id, current_user).subquery(
        "summary_overdue_agg"
    )

    scope_agg = (
        select(
            ProjectScopeState.project_id.label("project_id"),
            func.count().label("pending"),
        )
        .where(
            ProjectScopeState.deleted_at.is_(None),
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
        )
        .group_by(ProjectScopeState.project_id)
    )
    scope_agg = _apply_org_filter(scope_agg, ProjectScopeState.org_id, current_user).subquery(
        "summary_scope_agg"
    )

    visible_project_ids = scoped_project_query(current_user).with_only_columns(Project.id)
    return (
        select(
            Project,
            func.coalesce(dep_agg.c.open, 0).label("dep_open"),
            func.coalesce(dep_agg.c.blocking, 0).label("dep_blocking"),
            func.coalesce(esc_agg.c.open, 0).label("esc_open"),
            func.coalesce(esc_agg.c.critical, 0).label("esc_critical"),
            func.coalesce(overdue_agg.c.overdue, 0).label("overdue_actions"),
            func.coalesce(scope_agg.c.pending, 0).label("pending_scopes"),
        )
        .outerjoin(dep_agg, dep_agg.c.project_id == Project.id)
        .outerjoin(esc_agg, esc_agg.c.project_id == Project.id)
        .outerjoin(overdue_agg, overdue_agg.c.project_id == Project.id)
        .outerjoin(scope_agg, scope_agg.c.project_id == Project.id)
        .where(Project.id.in_(visible_project_ids))
        .order_by(Project.name.asc())
    )


def _summary_include_delivery_signals(current_user: CurrentUser) -> bool:
    return can_read_internal_governance(current_user) and current_user.role != AppRole.CLIENT


def _summary_org_filter_sql(column: str) -> str:
    return f"(CAST(:is_super_admin AS boolean) OR {column} = :org_id)"


def _summary_unified_sql(*, include_signals: bool):
    """One-statement summary: visible projects + governance aggs (+ delivery signals)."""
    signal_cte = ""
    signal_select = "NULL::jsonb AS delivery_signals"
    signal_join = ""
    if include_signals:
        bundle_sql = governance_signal_bundle_select_sql(
            "{alias}.project_id IN (SELECT id FROM visible_projects)"
        )
        signal_cte = f"""
        , signal_bundle AS (
          {bundle_sql}
        )
        , signals_agg AS (
          SELECT
            project_id,
            coalesce(
              jsonb_agg(jsonb_build_object('kind', kind, 'payload', payload)),
              '[]'::jsonb
            ) AS signals
          FROM signal_bundle
          GROUP BY project_id
        )
        """
        signal_select = "coalesce(sa.signals, '[]'::jsonb) AS delivery_signals"
        signal_join = "LEFT JOIN signals_agg sa ON sa.project_id = vp.id"

    org_filter = _summary_org_filter_sql("org_id")
    sql = f"""
    WITH visible_projects AS (
      SELECT
        p.id,
        p.org_id,
        p.name,
        p.description,
        p.vertical,
        p.status,
        p.start_date,
        p.target_end_date,
        p.actual_end_date,
        p.daily_target_units
      FROM projects p
      WHERE p.deleted_at IS NULL
        AND (
          CAST(:is_super_admin AS boolean)
          OR (
            p.org_id = :org_id
            AND (
              NOT CAST(:is_client AS boolean)
              OR EXISTS (
                SELECT 1
                FROM project_assignments pa
                WHERE pa.project_id = p.id
                  AND pa.user_id = :user_id
                  AND pa.is_active IS TRUE
                  AND pa.deleted_at IS NULL
              )
            )
          )
        )
    ),
    summary_dep_agg AS (
      SELECT
        project_id,
        count(*) FILTER (WHERE status != 'resolved')::int AS open,
        count(*) FILTER (WHERE status = 'blocking')::int AS blocking
      FROM project_dependencies
      WHERE deleted_at IS NULL
        AND {org_filter}
      GROUP BY project_id
    ),
    summary_esc_agg AS (
      SELECT
        project_id,
        count(*)::int AS open,
        count(*) FILTER (WHERE severity = 'critical')::int AS critical
      FROM governance_escalations
      WHERE deleted_at IS NULL
        AND status IN ('open', 'in_progress')
        AND {org_filter}
      GROUP BY project_id
    ),
    summary_overdue_agg AS (
      SELECT
        project_id,
        count(*)::int AS overdue
      FROM governance_actions
      WHERE deleted_at IS NULL
        AND {org_filter}
        AND (
          status = 'overdue'
          OR (
            status != 'completed'
            AND due_date IS NOT NULL
            AND due_date < :today
          )
        )
      GROUP BY project_id
    ),
    summary_scope_agg AS (
      SELECT
        project_id,
        count(*)::int AS pending
      FROM project_scope_states
      WHERE deleted_at IS NULL
        AND scope_status = 'pending_revision'
        AND {org_filter}
      GROUP BY project_id
    )
    {signal_cte}
    SELECT
      vp.id,
      vp.org_id,
      vp.name,
      vp.description,
      vp.vertical,
      vp.status,
      vp.start_date,
      vp.target_end_date,
      vp.actual_end_date,
      vp.daily_target_units,
      coalesce(dep.open, 0)::int AS dep_open,
      coalesce(dep.blocking, 0)::int AS dep_blocking,
      coalesce(esc.open, 0)::int AS esc_open,
      coalesce(esc.critical, 0)::int AS esc_critical,
      coalesce(ov.overdue, 0)::int AS overdue_actions,
      coalesce(sc.pending, 0)::int AS pending_scopes,
      {signal_select}
    FROM visible_projects vp
    LEFT JOIN summary_dep_agg dep ON dep.project_id = vp.id
    LEFT JOIN summary_esc_agg esc ON esc.project_id = vp.id
    LEFT JOIN summary_overdue_agg ov ON ov.project_id = vp.id
    LEFT JOIN summary_scope_agg sc ON sc.project_id = vp.id
    {signal_join}
    ORDER BY vp.name ASC
    """
    stmt = text(sql).bindparams(
        bindparam("org_id", type_=PG_UUID()),
        bindparam("user_id", type_=PG_UUID()),
        bindparam("is_super_admin"),
        bindparam("is_client"),
        bindparam("today"),
    )
    if include_signals:
        stmt = stmt.bindparams(bindparam("throughput_limit"))
    return stmt


def _summary_unified_params(
    current_user: CurrentUser,
    *,
    today: date,
    include_signals: bool,
) -> dict:
    params: dict = {
        "org_id": current_user.org_id,
        "user_id": current_user.id,
        "is_super_admin": current_user.role == AppRole.SUPER_ADMIN,
        "is_client": current_user.role == AppRole.CLIENT,
        "today": today,
    }
    if include_signals:
        params["throughput_limit"] = GOVERNANCE_THROUGHPUT_LIMIT
    return params


def _project_from_summary_row(row: dict) -> Project:
    status = row["status"]
    if not isinstance(status, ProjectStatus):
        status = ProjectStatus(str(status))
    return Project(
        id=row["id"],
        org_id=row["org_id"],
        name=row["name"],
        description=row["description"],
        vertical=row["vertical"],
        status=status,
        start_date=row["start_date"],
        target_end_date=row["target_end_date"],
        actual_end_date=row["actual_end_date"],
        daily_target_units=row["daily_target_units"],
    )


def _signal_tuples_from_json(
    project_id: UUID,
    signals_json: object,
) -> list[tuple[str, UUID, dict]]:
    if not signals_json:
        return []
    items = signals_json
    if isinstance(items, str):
        items = json.loads(items)
    rows: list[tuple[str, UUID, dict]] = []
    for item in items:  # type: ignore[union-attr]
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        payload = item.get("payload")
        if not isinstance(kind, str) or not isinstance(payload, dict):
            continue
        rows.append((kind, project_id, payload))
    return rows


def _detail_bundle_sql(*, include_internal: bool, include_signals: bool):
    """Second analytics-detail execute: window KPIs, counters, evidence, and activity."""
    internal_predicate = "true" if include_internal else "false"
    signal_cte = ""
    signal_select = ""
    if include_signals:
        signal_project_predicate = "{alias}.project_id IN (SELECT id FROM visible_projects)"
        signal_cte = f""",
    signal_bundle AS (
      {governance_signal_bundle_select_sql(signal_project_predicate)}
    )"""
        signal_select = """
    UNION ALL
    SELECT 'delivery_signal'::text AS section,
           jsonb_build_object('kind', kind, 'project_id', project_id, 'payload', payload) AS payload
    FROM signal_bundle"""

    sql = f"""
    WITH visible_projects AS (
      SELECT p.id, p.org_id, p.name
      FROM projects p
      WHERE p.deleted_at IS NULL
        AND (
          :is_super_admin
          OR (
            p.org_id = :org_id
            AND (
              NOT :is_client
              OR EXISTS (
                SELECT 1
                FROM project_assignments pa
                WHERE pa.project_id = p.id
                  AND pa.user_id = :user_id
                  AND pa.is_active IS TRUE
                  AND pa.deleted_at IS NULL
              )
            )
          )
        )
    ){signal_cte},
    dep_base AS (
      SELECT d.*, vp.name AS project_name
      FROM project_dependencies d
      JOIN visible_projects vp ON vp.id = d.project_id
      WHERE {internal_predicate}
        AND d.deleted_at IS NULL
    ),
    esc_base AS (
      SELECT e.*, vp.name AS project_name
      FROM governance_escalations e
      JOIN visible_projects vp ON vp.id = e.project_id
      WHERE e.deleted_at IS NULL
    ),
    action_base AS (
      SELECT a.*, vp.name AS project_name
      FROM governance_actions a
      JOIN visible_projects vp ON vp.id = a.project_id
      WHERE {internal_predicate}
        AND a.deleted_at IS NULL
    ),
    window_escalation AS (
      SELECT *
      FROM esc_base
      WHERE status IN ('open', 'in_progress')
         OR resolved_at >= :window_start
         OR raised_at >= :window_start
    ),
    window_action AS (
      SELECT *
      FROM action_base
      WHERE status != 'completed'
         OR completed_at >= :window_start
         OR created_at >= :window_start
    ),
    recent_activity AS (
      SELECT created_at AS occurred_at,
             1 AS source_order,
             jsonb_build_object(
               'source_type', 'dependency',
               'occurred_at', created_at,
               'source_order', 1,
               'source_id', id,
               'label', title,
               'detail', concat('status=', status),
               'project_id', project_id,
               'project_name', project_name
             ) AS payload
      FROM (
        SELECT *
        FROM dep_base
        WHERE created_at IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 8
      ) recent_deps

      UNION ALL

      SELECT created_at AS occurred_at,
             2 AS source_order,
             jsonb_build_object(
               'source_type', 'action',
               'occurred_at', created_at,
               'source_order', 2,
               'source_id', id,
               'label', title,
               'detail', concat(
                 'status=',
                 CASE
                   WHEN status = 'completed' THEN 'completed'
                   WHEN status = 'overdue' THEN 'overdue'
                   WHEN due_date IS NOT NULL AND due_date < :today THEN 'overdue'
                   ELSE status::text
                 END
               ),
               'project_id', project_id,
               'project_name', project_name
             ) AS payload
      FROM (
        SELECT *
        FROM action_base
        WHERE created_at IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 8
      ) recent_actions

      UNION ALL

      SELECT raised_at AS occurred_at,
             3 AS source_order,
             jsonb_build_object(
               'source_type', 'escalation',
               'occurred_at', raised_at,
               'source_order', 3,
               'source_id', id,
               'label', title,
               'detail', concat('severity=', severity),
               'project_id', project_id,
               'project_name', project_name
             ) AS payload
      FROM (
        SELECT *
        FROM esc_base
        WHERE raised_at IS NOT NULL
        ORDER BY raised_at DESC
        LIMIT 8
      ) recent_escalations
    )
    SELECT 'window_escalation'::text AS section,
           jsonb_build_object(
             'id', id,
             'project_id', project_id,
             'title', title,
             'severity', severity,
             'status', status,
             'raised_at', raised_at,
             'resolved_at', resolved_at,
             'project_name', project_name
           ) AS payload
    FROM window_escalation

    UNION ALL
    SELECT 'window_action',
           jsonb_build_object(
             'id', id,
             'project_id', project_id,
             'title', title,
             'due_date', due_date,
             'status', status,
             'created_at', created_at,
             'completed_at', completed_at,
             'project_name', project_name
           )
    FROM window_action

    UNION ALL
    SELECT 'blocking_dependency',
           jsonb_build_object(
             'id', id,
             'project_id', project_id,
             'title', title,
             'dependency_type', dependency_type,
             'due_date', due_date,
             'status', status,
             'created_at', created_at,
             'resolved_at', resolved_at,
             'project_name', project_name
           )
    FROM dep_base
    WHERE status = 'blocking'

    UNION ALL
    SELECT 'critical_escalation',
           jsonb_build_object(
             'id', id,
             'project_id', project_id,
             'title', title,
             'severity', severity,
             'status', status,
             'raised_at', raised_at,
             'resolved_at', resolved_at,
             'project_name', project_name
           )
    FROM esc_base
    WHERE status IN ('open', 'in_progress')
      AND severity = 'critical'

    UNION ALL
    SELECT 'overdue_action',
           jsonb_build_object(
             'id', id,
             'project_id', project_id,
             'title', title,
             'due_date', due_date,
             'status', status,
             'created_at', created_at,
             'completed_at', completed_at,
             'project_name', project_name
           )
    FROM action_base
    WHERE status = 'overdue'
       OR (status != 'completed' AND due_date IS NOT NULL AND due_date < :today)

    UNION ALL
    SELECT 'counter_dependency_type',
           jsonb_build_object('label', dependency_type, 'value', count(*)::int)
    FROM dep_base
    GROUP BY dependency_type

    UNION ALL
    SELECT 'counter_escalation_severity',
           jsonb_build_object('label', severity, 'value', count(*)::int)
    FROM esc_base
    GROUP BY severity

    UNION ALL
    SELECT 'counter_action_status',
           jsonb_build_object(
             'label',
             'completed',
             'value',
             count(*) FILTER (WHERE status = 'completed')::int
           )
    FROM action_base

    UNION ALL
    SELECT 'counter_action_status',
           jsonb_build_object(
             'label',
             'in_progress',
             'value',
             count(*) FILTER (
               WHERE status = 'in_progress'
                 AND NOT (
                   status = 'overdue'
                   OR (
                     status != 'completed'
                     AND due_date IS NOT NULL
                     AND due_date < :today
                   )
                 )
             )::int
           )
    FROM action_base

    UNION ALL
    SELECT 'counter_action_status',
           jsonb_build_object(
             'label',
             'open',
             'value',
             count(*) FILTER (
               WHERE status = 'open'
                 AND NOT (
                   status = 'overdue'
                   OR (
                     status != 'completed'
                     AND due_date IS NOT NULL
                     AND due_date < :today
                   )
                 )
             )::int
           )
    FROM action_base

    UNION ALL
    SELECT 'counter_action_status',
           jsonb_build_object(
             'label',
             'overdue',
             'value',
             count(*) FILTER (
               WHERE status = 'overdue'
                  OR (status != 'completed' AND due_date IS NOT NULL AND due_date < :today)
             )::int
           )
    FROM action_base

    UNION ALL
    SELECT 'recent_activity',
           payload
    FROM recent_activity

    {signal_select}
    """
    stmt = text(sql).bindparams(
        bindparam("org_id", type_=PG_UUID()),
        bindparam("user_id", type_=PG_UUID()),
        bindparam("is_super_admin"),
        bindparam("is_client"),
        bindparam("today"),
        bindparam("window_start"),
    )
    if include_signals:
        stmt = stmt.bindparams(bindparam("throughput_limit"))
    return stmt


def _detail_bundle_params(
    current_user: CurrentUser,
    *,
    today: date,
    window_start: datetime,
    include_signals: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "org_id": current_user.org_id,
        "user_id": current_user.id,
        "is_super_admin": current_user.role == AppRole.SUPER_ADMIN,
        "is_client": current_user.role == AppRole.CLIENT,
        "today": today,
        "window_start": window_start,
    }
    if include_signals:
        params["throughput_limit"] = GOVERNANCE_THROUGHPUT_LIMIT
    return params


def _json_payload(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _parse_uuid(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_date_value(value: object) -> date | None:
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _parse_datetime_value(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _dependency_from_payload(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=_parse_uuid(payload.get("id")),
        project_id=_parse_uuid(payload.get("project_id")),
        title=str(payload.get("title") or ""),
        dependency_type=GovernanceDependencyStatus.OPEN.__class__(
            str(payload.get("dependency_type"))
        )
        if False
        else str(payload.get("dependency_type")),
        due_date=_parse_date_value(payload.get("due_date")),
        status=GovernanceDependencyStatus(str(payload.get("status"))),
        created_at=_parse_datetime_value(payload.get("created_at")),
        resolved_at=_parse_datetime_value(payload.get("resolved_at")),
    )


def _escalation_from_payload(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=_parse_uuid(payload.get("id")),
        project_id=_parse_uuid(payload.get("project_id")),
        title=str(payload.get("title") or ""),
        severity=GovernanceEscalationSeverity(str(payload.get("severity"))),
        status=GovernanceEscalationStatus(str(payload.get("status"))),
        raised_at=_parse_datetime_value(payload.get("raised_at")),
        resolved_at=_parse_datetime_value(payload.get("resolved_at")),
    )


def _action_from_payload(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=_parse_uuid(payload.get("id")),
        project_id=_parse_uuid(payload.get("project_id")),
        title=str(payload.get("title") or ""),
        due_date=_parse_date_value(payload.get("due_date")),
        status=GovernanceActionStatus(str(payload.get("status"))),
        created_at=_parse_datetime_value(payload.get("created_at")),
        completed_at=_parse_datetime_value(payload.get("completed_at")),
    )


@dataclass
class _DetailBundle:
    window_escalations: list[Any]
    window_actions: list[Any]
    blocking_dependencies: list[Any]
    critical_escalations: list[Any]
    overdue_actions: list[Any]
    dep_type_counter: Counter[str]
    esc_severity_counter: Counter[str]
    action_status_counter: Counter[str]
    recent_activity: list[GovernanceEvidenceRead]
    delivery_signal_tuples: list[tuple[str, UUID, dict]]


async def _fetch_detail_second_bundle(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
    include_signals: bool,
) -> _DetailBundle:
    result = await session.execute(
        _detail_bundle_sql(
            include_internal=can_read_internal_governance(current_user),
            include_signals=include_signals,
        ),
        _detail_bundle_params(
            current_user,
            today=today,
            window_start=_trend_window_start(today=today, days=days),
            include_signals=include_signals,
        ),
    )
    rows = result.mappings().all()
    window_escalations: list[Any] = []
    window_actions: list[Any] = []
    blocking_dependencies: list[Any] = []
    critical_escalations: list[Any] = []
    overdue_actions: list[Any] = []
    dep_type_counter: Counter[str] = Counter()
    esc_severity_counter: Counter[str] = Counter()
    action_status_counter: Counter[str] = Counter()
    recent_activity_rows: list[tuple[datetime, int, GovernanceEvidenceRead]] = []
    delivery_signal_tuples: list[tuple[str, UUID, dict]] = []

    for row in rows:
        section = str(row["section"])
        payload = _json_payload(row["payload"])
        if section == "window_escalation":
            window_escalations.append(_escalation_from_payload(payload))
        elif section == "window_action":
            window_actions.append(_action_from_payload(payload))
        elif section == "blocking_dependency":
            blocking_dependencies.append(_dependency_from_payload(payload))
        elif section == "critical_escalation":
            critical_escalations.append(_escalation_from_payload(payload))
        elif section == "overdue_action":
            overdue_actions.append(_action_from_payload(payload))
        elif section == "counter_dependency_type":
            dep_type_counter[str(payload.get("label"))] = int(payload.get("value") or 0)
        elif section == "counter_escalation_severity":
            esc_severity_counter[str(payload.get("label"))] = int(payload.get("value") or 0)
        elif section == "counter_action_status":
            action_status_counter[str(payload.get("label"))] = int(payload.get("value") or 0)
        elif section == "recent_activity":
            project_id = _parse_uuid(payload.get("project_id"))
            occurred_at = _parse_datetime_value(payload.get("occurred_at")) or datetime.min
            source_order = int(payload.get("source_order") or 99)
            recent_activity_rows.append(
                (
                    occurred_at,
                    source_order,
                    _evidence(
                        str(payload.get("source_type")),
                        str(payload.get("label") or ""),
                        source_id=_parse_uuid(payload.get("source_id")),
                        detail=(
                            str(payload.get("detail"))
                            if payload.get("detail") is not None
                            else None
                        ),
                        project_id=project_id,
                        project_name=(
                            str(payload.get("project_name"))
                            if payload.get("project_name") is not None
                            else None
                        ),
                    ),
                )
            )
        elif section == "delivery_signal":
            project_id = _parse_uuid(payload.get("project_id"))
            signal_payload = payload.get("payload")
            if project_id is not None and isinstance(signal_payload, dict):
                delivery_signal_tuples.append(
                    (str(payload.get("kind")), project_id, signal_payload)
                )

    blocking_dependencies.sort(key=lambda dep: dep.created_at or datetime.min, reverse=True)
    critical_escalations.sort(key=lambda esc: esc.raised_at or datetime.min, reverse=True)
    overdue_actions.sort(key=lambda action: action.due_date or date.max)
    recent_activity = [
        item
        for _, _, item in sorted(
            recent_activity_rows,
            key=lambda row: (row[0], -row[1]),
            reverse=True,
        )[:8]
    ]
    return _DetailBundle(
        window_escalations=window_escalations,
        window_actions=window_actions,
        blocking_dependencies=blocking_dependencies,
        critical_escalations=critical_escalations,
        overdue_actions=overdue_actions,
        dep_type_counter=dep_type_counter,
        esc_severity_counter=esc_severity_counter,
        action_status_counter=action_status_counter,
        recent_activity=recent_activity,
        delivery_signal_tuples=delivery_signal_tuples,
    )


async def _fetch_detail_project_bundle(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> tuple[
    list[Project],
    dict[UUID, tuple[int, int]],
    dict[UUID, tuple[int, int]],
    dict[UUID, int],
    dict[UUID, int],
]:
    result = await session.execute(
        _summary_unified_sql(include_signals=False),
        _summary_unified_params(current_user, today=today, include_signals=False),
    )
    rows = result.mappings().all()
    projects: list[Project] = []
    dependency_counts: dict[UUID, tuple[int, int]] = {}
    escalation_counts: dict[UUID, tuple[int, int]] = {}
    overdue_by_project: dict[UUID, int] = {}
    pending_by_project: dict[UUID, int] = {}
    internal = can_read_internal_governance(current_user)

    for row in rows:
        project = _project_from_summary_row(dict(row))
        projects.append(project)
        if internal:
            dependency_counts[project.id] = (
                int(row["dep_open"] or 0),
                int(row["dep_blocking"] or 0),
            )
            overdue_by_project[project.id] = int(row["overdue_actions"] or 0)
            pending_by_project[project.id] = int(row["pending_scopes"] or 0)
        escalation_counts[project.id] = (int(row["esc_open"] or 0), int(row["esc_critical"] or 0))

    return projects, dependency_counts, escalation_counts, overdue_by_project, pending_by_project


async def _fetch_summary_project_metrics(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> tuple[
    list[Project],
    dict[UUID, tuple[int, int]],
    dict[UUID, tuple[int, int]],
    dict[UUID, int],
    dict[UUID, int],
]:
    rows = (await session.execute(_summary_project_metrics_stmt(current_user, today=today))).all()
    projects: list[Project] = []
    dependency_counts: dict[UUID, tuple[int, int]] = {}
    escalation_counts: dict[UUID, tuple[int, int]] = {}
    overdue_by_project: dict[UUID, int] = {}
    pending_by_project: dict[UUID, int] = {}
    internal = can_read_internal_governance(current_user)

    for (
        project,
        dep_open,
        dep_blocking,
        esc_open,
        esc_critical,
        overdue_actions,
        pending_scopes,
    ) in rows:
        projects.append(project)
        if internal:
            dependency_counts[project.id] = (int(dep_open or 0), int(dep_blocking or 0))
            overdue_by_project[project.id] = int(overdue_actions or 0)
            pending_by_project[project.id] = int(pending_scopes or 0)
        escalation_counts[project.id] = (int(esc_open or 0), int(esc_critical or 0))

    return projects, dependency_counts, escalation_counts, overdue_by_project, pending_by_project


async def _fetch_summary_metric_bundle_two_query(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> tuple[
    list[Project],
    dict[UUID, tuple[int, int]],
    dict[UUID, tuple[int, int]],
    dict[UUID, int],
    dict[UUID, int],
    dict[UUID, dict],
    dict[str, float],
]:
    """Legacy two-execute path retained for equivalence tests only."""
    timings: dict[str, float] = {}

    metrics_started = perf_counter()
    (
        projects,
        dependency_counts,
        escalation_counts,
        overdue_by_project,
        pending_by_project,
    ) = await _fetch_summary_project_metrics(session, current_user, today=today)
    timings["project_metrics"] = round((perf_counter() - metrics_started) * 1000, 1)

    delivery_started = perf_counter()
    delivery_by_project = await _fetch_delivery_by_project(
        session,
        current_user,
        projects=projects,
    )
    timings["delivery_signals"] = round((perf_counter() - delivery_started) * 1000, 1)

    return (
        projects,
        dependency_counts,
        escalation_counts,
        overdue_by_project,
        pending_by_project,
        delivery_by_project,
        timings,
    )


async def _fetch_summary_metric_bundle(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
) -> tuple[
    list[Project],
    dict[UUID, tuple[int, int]],
    dict[UUID, tuple[int, int]],
    dict[UUID, int],
    dict[UUID, int],
    dict[UUID, dict],
    dict[str, float],
]:
    """Load visible projects, governance aggregates, and delivery signals in one execute."""
    timings: dict[str, float] = {}
    include_signals = _summary_include_delivery_signals(current_user)
    started = perf_counter()
    result = await session.execute(
        _summary_unified_sql(include_signals=include_signals),
        _summary_unified_params(current_user, today=today, include_signals=include_signals),
    )
    rows = result.mappings().all()
    timings["summary_unified"] = round((perf_counter() - started) * 1000, 1)

    projects: list[Project] = []
    dependency_counts: dict[UUID, tuple[int, int]] = {}
    escalation_counts: dict[UUID, tuple[int, int]] = {}
    overdue_by_project: dict[UUID, int] = {}
    pending_by_project: dict[UUID, int] = {}
    signal_tuples: list[tuple[str, UUID, dict]] = []
    internal = can_read_internal_governance(current_user)

    for row in rows:
        project = _project_from_summary_row(dict(row))
        projects.append(project)
        if internal:
            dependency_counts[project.id] = (
                int(row["dep_open"] or 0),
                int(row["dep_blocking"] or 0),
            )
            overdue_by_project[project.id] = int(row["overdue_actions"] or 0)
            pending_by_project[project.id] = int(row["pending_scopes"] or 0)
        escalation_counts[project.id] = (int(row["esc_open"] or 0), int(row["esc_critical"] or 0))
        if include_signals:
            signal_tuples.extend(_signal_tuples_from_json(project.id, row["delivery_signals"]))

    delivery_by_project: dict[UUID, dict] = {}
    if include_signals and projects:
        project_ids = [project.id for project in projects]
        throughput, quality, milestones, risks, bottlenecks = _parse_governance_signal_bundle_rows(
            signal_tuples,
            project_ids,
        )
        delivery_by_project = build_governance_delivery_signals_from_inputs(
            current_user,
            project_ids,
            {project.id: project for project in projects},
            throughput=throughput,
            quality=quality,
            milestones=milestones,
            risks=risks,
            bottlenecks=bottlenecks,
            as_of_date=today,
        )

    return (
        projects,
        dependency_counts,
        escalation_counts,
        overdue_by_project,
        pending_by_project,
        delivery_by_project,
        timings,
    )


async def get_governance_analytics_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
    project_id: UUID | None = None,
    vertical: str | None = None,
) -> GovernanceAnalyticsSummaryRead:
    """Fast executive header: top risk ranking without heavy analytics work."""
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    normalized_vertical = _normalize_vertical_filter(vertical)
    cache_key = _analytics_cache_key(
        current_user,
        effective_days,
        project_id=project_id,
        vertical=normalized_vertical,
    )
    now = datetime.now(UTC)
    timer = get_governance_timer()
    cached = _analytics_summary_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
        if timer is not None:
            timer.record_meta(execute_count=0, cache_hit=True)
        return cached[1]

    started = perf_counter()
    today = now.date()

    (
        projects,
        dependency_counts,
        escalation_counts,
        overdue_by_project,
        pending_by_project,
        delivery_by_project,
        query_timings,
    ) = await _fetch_summary_metric_bundle(
        session,
        current_user,
        today=today,
    )
    projects = _filter_projects(
        projects,
        project_id=project_id,
        vertical=normalized_vertical,
    )

    project_health: list[GovernanceHealthProjectRead] = []
    for project in projects:
        metrics = _merge_project_metrics(
            project.id,
            dependency_counts=dependency_counts,
            escalation_counts=escalation_counts,
            overdue_actions=overdue_by_project,
            pending_scopes=pending_by_project,
        )
        project_health.append(
            _score_project_from_metrics(
                project,
                metrics,
                delivery_signal=delivery_by_project.get(project.id),
            )
        )

    ranking = sorted(project_health, key=lambda row: (row.score, -row.priority, row.project_name))
    top_ranking = ranking[:SUMMARY_RANKING_LIMIT]
    top_health = top_ranking

    # Summary stays lean: portfolio score + at-risk count only. Rates live on detail.
    insights_kpis = GovernanceInsightsKpisRead(
        portfolio_governance_score=_portfolio_governance_score(project_health),
        projects_at_risk=sum(1 for row in project_health if row.risk_level in AT_RISK_LEVELS),
        recommendation_acceptance_rate_pct=0.0,
        recommendation_dismissal_rate_pct=0.0,
        escalations_created=0,
        recommendations_created=0,
        sla_adherence_pct=0.0,
    )

    summary = GovernanceAnalyticsSummaryRead(
        generated_at=now,
        date_range_days=effective_days,
        project_health=top_health,
        portfolio_risk_ranking=top_ranking,
        charts=_summary_health_charts(project_health),
        export_sections=["Governance Health", "Insights KPIs"],
        portfolio_governance_score=insights_kpis.portfolio_governance_score,
        insights_kpis=insights_kpis,
    )
    _analytics_summary_cache[cache_key] = (now, summary)

    # Summary path: one unified SQL execute (projects + aggs + delivery signals).
    if timer is not None:
        timer.record_meta(execute_count=1, cache_hit=False)

    total_ms = round((perf_counter() - started) * 1000, 1)
    if total_ms >= 300:
        logger.info(
            "governance_analytics_summary_profile total_ms=%s project_count=%s "
            "ranking_count=%s query_timings=%s db_executes=1 cached=false",
            total_ms,
            len(projects),
            len(top_ranking),
            query_timings,
        )

    return summary


async def get_governance_analytics_detail(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
    project_id: UUID | None = None,
    vertical: str | None = None,
) -> GovernanceAnalyticsDetailRead:
    """Heavy analytics sections: charts, recommendations, and activity."""
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    normalized_vertical = _normalize_vertical_filter(vertical)
    cache_key = _analytics_cache_key(
        current_user,
        effective_days,
        project_id=project_id,
        vertical=normalized_vertical,
    )
    now = datetime.now(UTC)
    timer = get_governance_timer()
    cached = _analytics_detail_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
        if timer is not None:
            timer.record_meta(
                cache_hit=True,
                execute_count=0,
                activity_row_count=len(cached[1].recent_activity),
            )
        return cached[1]

    started = perf_counter()
    today = now.date()
    query_timings: dict[str, float] = {}
    include_signals = _summary_include_delivery_signals(current_user)

    project_started = perf_counter()
    (
        projects,
        dependency_counts,
        escalation_counts,
        overdue_by_project,
        pending_by_project,
    ) = await _fetch_detail_project_bundle(session, current_user, today=today)
    projects = _filter_projects(
        projects,
        project_id=project_id,
        vertical=normalized_vertical,
    )
    project_ids = {project.id for project in projects}
    query_timings["detail_project_metrics"] = round((perf_counter() - project_started) * 1000, 1)

    project_names = {project.id: project.name for project in projects}

    bundle_started = perf_counter()
    detail_bundle = await _fetch_detail_second_bundle(
        session,
        current_user,
        today=today,
        days=effective_days,
        include_signals=include_signals,
    )
    query_timings["detail_source_bundle"] = round((perf_counter() - bundle_started) * 1000, 1)

    delivery_by_project: dict[UUID, dict] = {}
    if include_signals and projects:
        signal_project_ids = [project.id for project in projects]
        throughput, quality, milestones, risks, bottlenecks = _parse_governance_signal_bundle_rows(
            detail_bundle.delivery_signal_tuples,
            signal_project_ids,
        )
        delivery_by_project = build_governance_delivery_signals_from_inputs(
            current_user,
            signal_project_ids,
            {project.id: project for project in projects},
            throughput=throughput,
            quality=quality,
            milestones=milestones,
            risks=risks,
            bottlenecks=bottlenecks,
            as_of_date=today,
        )

    project_health: list[GovernanceHealthProjectRead] = []
    for project in projects:
        metrics = _merge_project_metrics(
            project.id,
            dependency_counts=dependency_counts,
            escalation_counts=escalation_counts,
            overdue_actions=overdue_by_project,
            pending_scopes=pending_by_project,
        )
        project_health.append(
            _score_project_from_metrics(
                project,
                metrics,
                delivery_signal=delivery_by_project.get(project.id),
            )
        )

    ranking = sorted(project_health, key=lambda row: (row.score, -row.priority, row.project_name))
    top_project_ids = [row.project_id for row in ranking[:10]]

    blocking_dependencies = detail_bundle.blocking_dependencies
    critical_escalations = detail_bundle.critical_escalations
    overdue_actions = detail_bundle.overdue_actions
    window_escalations = detail_bundle.window_escalations
    window_actions = detail_bundle.window_actions
    recent_activity = detail_bundle.recent_activity
    if project_ids:
        blocking_dependencies = _filter_rows_by_project_ids(blocking_dependencies, project_ids)
        critical_escalations = _filter_rows_by_project_ids(critical_escalations, project_ids)
        overdue_actions = _filter_rows_by_project_ids(overdue_actions, project_ids)
        window_escalations = _filter_rows_by_project_ids(window_escalations, project_ids)
        window_actions = _filter_rows_by_project_ids(window_actions, project_ids)
        recent_activity = [
            item
            for item in recent_activity
            if item.project_id is None or item.project_id in project_ids
        ]

    evidence_by_project = _derive_project_evidence(
        blocking_dependencies,
        critical_escalations,
        project_ids=top_project_ids,
        project_names=project_names,
    )
    if evidence_by_project:
        enriched: list[GovernanceHealthProjectRead] = []
        for row in project_health:
            fetched = evidence_by_project.get(row.project_id, [])
            if not fetched:
                enriched.append(row)
                continue
            delivery_evidence = [
                item for item in row.evidence if item.source_type == "delivery_signal"
            ]
            enriched.append(row.model_copy(update={"evidence": fetched + delivery_evidence}))
        project_health = enriched
        ranking = sorted(
            project_health, key=lambda row: (row.score, -row.priority, row.project_name)
        )

    ai_recommendations = await _fetch_ai_recommendations_for_insights(
        session,
        current_user,
        today=today,
        days=effective_days,
        project_ids=project_ids or None,
    )

    insights_kpis = _build_insights_kpis(
        project_health=project_health,
        escalations_created=_count_escalations_created(
            window_escalations,
            today=today,
            days=effective_days,
        ),
        recommendations=ai_recommendations,
        sla_adherence_pct=calculate_sla_adherence_pct(window_actions),
    )
    top_governance_risks = _build_top_governance_risks(project_health, critical_escalations)
    top_recurring_blockers = _build_top_recurring_blockers(blocking_dependencies)
    top_recurring_mitigation_failures = _build_top_mitigation_failures(ai_recommendations)
    most_affected_projects = _build_most_affected_projects(project_health)
    most_affected_departments = _build_most_affected_departments(project_health)
    risk_heatmap = _build_risk_heatmap(project_health)

    charts = {
        "dependencies_by_type": _chart_points(
            detail_bundle.dep_type_counter,
            [
                ("client_action", "Client"),
                ("internal", "Internal"),
                ("external", "External"),
            ],
        ),
        "escalations_by_severity": _chart_points(
            detail_bundle.esc_severity_counter,
            [
                ("low", "Low"),
                ("medium", "Medium"),
                ("high", "High"),
                ("critical", "Critical"),
            ],
        ),
        "actions_by_status": _chart_points(
            detail_bundle.action_status_counter,
            [
                ("open", "Open"),
                ("in_progress", "In Progress"),
                ("completed", "Completed"),
                ("overdue", "Overdue"),
            ],
        ),
        "health_distribution": _chart_points(
            Counter(row.risk_level for row in project_health),
            [
                ("excellent", "Excellent"),
                ("healthy", "Healthy"),
                ("moderate_risk", "Moderate"),
                ("high_risk", "High Risk"),
                ("critical", "Critical"),
            ],
        ),
        "most_active_projects": [
            GovernanceChartPointRead(
                label=project.project_name,
                value=float(_project_activity_count(project)),
                secondary_value=float(project.score),
            )
            for project in sorted(project_health, key=lambda row: row.priority, reverse=True)[
                :SUMMARY_RANKING_LIMIT
            ]
        ],
        "recommendation_outcomes": _recommendation_outcome_charts(ai_recommendations),
        "affected_departments": _affected_department_charts(project_health),
    }

    insights = _build_insights(
        project_health,
        blocking_dependencies,
        critical_escalations,
        overdue_actions,
    )
    recommendations = _build_recommendations(ranking)

    detail = GovernanceAnalyticsDetailRead(
        generated_at=now,
        date_range_days=effective_days,
        insights=insights,
        recommendations=recommendations,
        charts=charts,
        recent_activity=recent_activity,
        export_sections=["Charts", "Executive Insights", "Evidence Appendix", "Insights KPIs"],
        insights_kpis=insights_kpis,
        top_governance_risks=top_governance_risks,
        top_recurring_blockers=top_recurring_blockers,
        top_recurring_mitigation_failures=top_recurring_mitigation_failures,
        most_affected_projects=most_affected_projects,
        most_affected_departments=most_affected_departments,
        risk_heatmap=risk_heatmap,
    )
    _analytics_detail_cache[cache_key] = (now, detail)
    # Detail path: project metrics + source bundle + AI recommendation window.
    if timer is not None:
        timer.record_meta(
            cache_hit=False,
            execute_count=3,
            activity_row_count=len(detail.recent_activity),
            project_row_count=len(projects),
        )
    total_ms = round((perf_counter() - started) * 1000, 1)
    if total_ms >= 300:
        logger.info(
            "governance_analytics_detail_profile total_ms=%s project_count=%s "
            "activity_rows=%s query_timings=%s db_executes=3 cached=false",
            total_ms,
            len(projects),
            len(detail.recent_activity),
            query_timings,
        )
    return detail


get_governance_analytics = governance_db_timed(get_governance_analytics)
get_governance_analytics_summary = governance_db_timed(get_governance_analytics_summary)
get_governance_analytics_detail = governance_db_timed(get_governance_analytics_detail)
