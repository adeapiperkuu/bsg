from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from time import perf_counter
from typing import TypeVar
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.services.delivery_signals import fetch_governance_delivery_signals
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
    GovernanceRecommendationRead,
    GovernanceTrendPointRead,
)
from app.agents.governance.services.dashboard_service import (
    _overdue_action_filter,
)
from app.agents.governance.services.governance_service import (
    _apply_org_filter,
    assert_can_read_governance,
    can_read_internal_governance,
)
from app.agents.governance.timing import governance_db_timed
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationSeverity,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    Project,
    ProjectDependency,
    ProjectScopeState,
)
from app.services.scoping import scoped_project_query
from app.db.session import session_scope

logger = logging.getLogger(__name__)

T = TypeVar("T")

RANGE_DAY_OPTIONS = {7, 30, 90, 365}
SUMMARY_RANKING_LIMIT = 8
OPEN_ESCALATION_STATUSES = {
    GovernanceEscalationStatus.OPEN,
    GovernanceEscalationStatus.IN_PROGRESS,
}
ANALYTICS_CACHE_TTL = timedelta(minutes=3)
_analytics_cache: dict[
    tuple[UUID | None, str, UUID, int],
    tuple[datetime, GovernanceAnalyticsRead],
] = {}
_analytics_summary_cache: dict[
    tuple[UUID | None, str, UUID, int],
    tuple[datetime, GovernanceAnalyticsSummaryRead],
] = {}
_analytics_detail_cache: dict[
    tuple[UUID | None, str, UUID, int],
    tuple[datetime, GovernanceAnalyticsDetailRead],
] = {}


def _analytics_cache_key(
    current_user: CurrentUser,
    days: int,
) -> tuple[UUID | None, str, UUID, int]:
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id
    return (org_id, current_user.role.value, current_user.id, days)


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
    }


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


async def _fetch_trend_series_bundle(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> tuple[list[ProjectDependency], list[GovernanceEscalation], list[GovernanceAction], list]:
    """Fetch all trend source rows sequentially on one session."""
    trend_dependencies = await _fetch_trend_dependencies(
        session, current_user, today=today, days=days
    )
    trend_escalations = await _fetch_trend_escalations(
        session, current_user, today=today, days=days
    )
    trend_actions = await _fetch_trend_actions(session, current_user, today=today, days=days)
    trend_scopes = await _fetch_trend_scopes(session, current_user, today=today, days=days)
    return trend_dependencies, trend_escalations, trend_actions, trend_scopes


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


async def _fetch_trend_dependencies(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[ProjectDependency]:
    if not can_read_internal_governance(current_user):
        return []
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(ProjectDependency).where(
        ProjectDependency.deleted_at.is_(None),
        or_(
            ProjectDependency.status != GovernanceDependencyStatus.RESOLVED,
            ProjectDependency.resolved_at >= window_start,
            ProjectDependency.created_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, ProjectDependency.org_id, current_user)
    return list((await session.execute(stmt)).scalars())


async def _fetch_trend_escalations(
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


async def _fetch_trend_actions(
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


async def _fetch_trend_scopes(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    today: date,
    days: int,
) -> list[ProjectScopeState]:
    if not can_read_internal_governance(current_user):
        return []
    window_start = _trend_window_start(today=today, days=days)
    stmt = select(ProjectScopeState).where(
        ProjectScopeState.deleted_at.is_(None),
        or_(
            ProjectScopeState.scope_status == GovernanceScopeStatus.PENDING_REVISION,
            ProjectScopeState.updated_at >= window_start,
        ),
    )
    stmt = _apply_org_filter(stmt, ProjectScopeState.org_id, current_user)
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


def _bucket_date(value: datetime | date | None, start: date, end: date) -> date | None:
    value_dt = _dt(value)
    if value_dt is None:
        return None
    value_date = value_dt.date()
    if start <= value_date <= end:
        return value_date
    return None


def _build_trends(
    *,
    days: int,
    project_health: list[GovernanceHealthProjectRead],
    dependencies: list,
    escalations: list,
    actions: list[GovernanceAction],
    scopes: list,
) -> list[GovernanceTrendPointRead]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    points: list[GovernanceTrendPointRead] = []
    portfolio_health = round(mean([project.score for project in project_health]), 1) if project_health else 100.0
    sla = calculate_sla_adherence_pct(actions)
    for offset in range(days):
        day = start + timedelta(days=offset)
        created_deps = [dep for dep in dependencies if _bucket_date(dep.created_at, day, day) == day]
        resolved_deps = [dep for dep in dependencies if _bucket_date(dep.resolved_at, day, day) == day]
        created_escalations = [
            esc for esc in escalations if _bucket_date(esc.raised_at, day, day) == day
        ]
        resolved_escalations = [
            esc for esc in escalations if _bucket_date(esc.resolved_at, day, day) == day
        ]
        created_actions = [action for action in actions if _bucket_date(action.created_at, day, day) == day]
        completed_actions = [
            action for action in actions if _bucket_date(action.completed_at, day, day) == day
        ]
        updated_scopes = [scope for scope in scopes if _bucket_date(scope.updated_at, day, day) == day]
        points.append(
            GovernanceTrendPointRead(
                date=day,
                open_dependencies=sum(
                    1
                    for dep in dependencies
                    if dep.status != GovernanceDependencyStatus.RESOLVED
                    and _dt(dep.created_at)
                    and _dt(dep.created_at).date() <= day
                ),
                resolved_dependencies=len(resolved_deps),
                blocking_dependencies=sum(
                    1 for dep in created_deps if dep.status == GovernanceDependencyStatus.BLOCKING
                ),
                escalations_created=len(created_escalations),
                escalations_resolved=len(resolved_escalations),
                critical_escalations=sum(
                    1 for esc in created_escalations if esc.severity == GovernanceEscalationSeverity.CRITICAL
                ),
                actions_created=len(created_actions),
                actions_completed=len(completed_actions),
                overdue_actions=sum(
                    1
                    for action in actions
                    if action.due_date is not None
                    and action.due_date <= day
                    and effective_action_status(action).value != "completed"
                ),
                scope_revisions=sum(
                    1
                    for scope in updated_scopes
                    if scope.scope_status == GovernanceScopeStatus.PENDING_REVISION
                ),
                scope_approvals=sum(
                    1 for scope in updated_scopes if scope.scope_status == GovernanceScopeStatus.APPROVED
                ),
                locked_scope=sum(
                    1 for scope in updated_scopes if scope.scope_status == GovernanceScopeStatus.LOCKED
                ),
                portfolio_health=portfolio_health,
                sla_adherence_pct=sla,
            )
        )
    return points


async def get_governance_analytics(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
) -> GovernanceAnalyticsRead:
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    cache_key = _analytics_cache_key(current_user, effective_days)
    now = datetime.now(UTC)
    cached = _analytics_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
        return cached[1]

    total_started = perf_counter()
    today = now.date()

    projects = await _fetch_visible_projects(session, current_user)
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

    blocking_dependencies = await _fetch_blocking_dependencies(session, current_user)
    critical_escalations = await _fetch_critical_escalations(session, current_user)

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

    trends_started = perf_counter()
    (
        trend_dependencies,
        trend_escalations,
        trend_actions,
        trend_scopes,
    ) = await _fetch_trend_series_bundle(session, current_user, today=today, days=effective_days)

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
        return (
            dep_type_counter,
            esc_severity_counter,
            action_status_counter,
            overdue_actions,
            recent_activity,
        )

    trends, (
        dep_type_counter,
        esc_severity_counter,
        action_status_counter,
        overdue_actions,
        recent_activity,
    ) = await asyncio.gather(
        asyncio.to_thread(
            _build_trends,
            days=effective_days,
            project_health=project_health,
            dependencies=trend_dependencies,
            escalations=trend_escalations,
            actions=trend_actions,
            scopes=trend_scopes,
        ),
        _fetch_chart_and_activity(),
    )
    trends_ms = round((perf_counter() - trends_started) * 1000, 1)

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
                value=float(
                    project.open_dependencies
                    + project.open_escalations
                    + project.overdue_actions
                    + project.pending_scope_revisions
                ),
                secondary_value=float(project.score),
            )
            for project in sorted(project_health, key=lambda row: row.priority, reverse=True)[:8]
        ],
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
        trends=trends,
        charts=charts,
        recent_activity=recent_activity,
        export_sections=[
            "Charts",
            "Executive Insights",
            "Governance Health",
            "Evidence Appendix",
        ],
    )
    _analytics_cache[cache_key] = (now, analytics)

    total_ms = round((perf_counter() - total_started) * 1000, 1)
    wave_ms = round(max(counts_ms, portfolio_ms, trends_ms, evidence_ms), 1)
    logger.info(
        "governance_analytics_timing org_id=%s role=%s days=%s total_ms=%s wave_ms=%s "
        "counts_ms=%s trends_ms=%s portfolio_ms=%s evidence_ms=%s recommendations_ms=%s",
        str(current_user.org_id) if current_user.org_id else None,
        current_user.role.value,
        effective_days,
        total_ms,
        wave_ms,
        counts_ms,
        trends_ms,
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
            "trends_ms": trends_ms,
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

    for project, dep_open, dep_blocking, esc_open, esc_critical, overdue_actions, pending_scopes in rows:
        projects.append(project)
        if internal:
            dependency_counts[project.id] = (int(dep_open or 0), int(dep_blocking or 0))
            overdue_by_project[project.id] = int(overdue_actions or 0)
            pending_by_project[project.id] = int(pending_scopes or 0)
        escalation_counts[project.id] = (int(esc_open or 0), int(esc_critical or 0))

    return projects, dependency_counts, escalation_counts, overdue_by_project, pending_by_project


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
    """Load visible projects + governance aggregates in one query, then delivery signals."""
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


async def get_governance_analytics_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    days: int = 30,
) -> GovernanceAnalyticsSummaryRead:
    """Fast executive header: top risk ranking without heavy analytics work."""
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    cache_key = _analytics_cache_key(current_user, effective_days)
    now = datetime.now(UTC)
    cached = _analytics_summary_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
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

    summary = GovernanceAnalyticsSummaryRead(
        generated_at=now,
        date_range_days=effective_days,
        project_health=top_health,
        portfolio_risk_ranking=top_ranking,
        charts=_summary_health_charts(project_health),
        export_sections=["Governance Health"],
    )
    _analytics_summary_cache[cache_key] = (now, summary)

    total_ms = round((perf_counter() - started) * 1000, 1)
    if total_ms >= 300:
        logger.info(
            "governance_analytics_summary_profile total_ms=%s project_count=%s "
            "ranking_count=%s query_timings=%s",
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
) -> GovernanceAnalyticsDetailRead:
    """Heavy analytics sections: trends, charts, recommendations, and activity."""
    assert_can_read_governance(current_user)
    effective_days = _clamp_range(days)
    cache_key = _analytics_cache_key(current_user, effective_days)
    now = datetime.now(UTC)
    cached = _analytics_detail_cache.get(cache_key)
    if cached and now - cached[0] < ANALYTICS_CACHE_TTL:
        return cached[1]

    today = now.date()
    projects = await _fetch_visible_projects(session, current_user)
    project_names = {project.id: project.name for project in projects}

    dependency_counts = await _fetch_dependency_counts_by_project(session, current_user)
    escalation_counts = await _fetch_escalation_counts_by_project(session, current_user)
    overdue_by_project = await _fetch_overdue_action_counts_by_project(
        session, current_user, today=today
    )
    pending_by_project = await _fetch_pending_scope_counts_by_project(session, current_user)
    delivery_by_project = await _fetch_delivery_by_project(
        session, current_user, projects=projects
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

    blocking_dependencies = await _fetch_blocking_dependencies(session, current_user)
    critical_escalations = await _fetch_critical_escalations(session, current_user)
    evidence_by_project = await _fetch_project_evidence(
        session,
        current_user,
        project_ids=top_project_ids,
        project_names=project_names,
        blocking_dependencies=blocking_dependencies,
        critical_escalations=critical_escalations,
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

    (
        trend_dependencies,
        trend_escalations,
        trend_actions,
        trend_scopes,
    ) = await _fetch_trend_series_bundle(session, current_user, today=today, days=effective_days)

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
        return (
            dep_type_counter,
            esc_severity_counter,
            action_status_counter,
            overdue_actions,
            recent_activity,
        )

    trends, (
        dep_type_counter,
        esc_severity_counter,
        action_status_counter,
        overdue_actions,
        recent_activity,
    ) = await asyncio.gather(
        asyncio.to_thread(
            _build_trends,
            days=effective_days,
            project_health=project_health,
            dependencies=trend_dependencies,
            escalations=trend_escalations,
            actions=trend_actions,
            scopes=trend_scopes,
        ),
        _fetch_chart_and_activity(),
    )

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
                value=float(
                    project.open_dependencies
                    + project.open_escalations
                    + project.overdue_actions
                    + project.pending_scope_revisions
                ),
                secondary_value=float(project.score),
            )
            for project in sorted(project_health, key=lambda row: row.priority, reverse=True)[
                :SUMMARY_RANKING_LIMIT
            ]
        ],
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
        trends=trends,
        charts=charts,
        recent_activity=recent_activity,
        export_sections=["Charts", "Executive Insights", "Evidence Appendix"],
    )
    _analytics_detail_cache[cache_key] = (now, detail)
    return detail


get_governance_analytics = governance_db_timed(get_governance_analytics)
get_governance_analytics_summary = governance_db_timed(get_governance_analytics_summary)
get_governance_analytics_detail = governance_db_timed(get_governance_analytics_detail)
