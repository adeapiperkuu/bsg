from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.db.models import (
    GovernanceAction,
    GovernanceActionStatus,
    GovernanceDependencyStatus,
    GovernanceEscalation,
    GovernanceEscalationStatus,
    GovernanceScopeStatus,
    ProjectDependency,
    ProjectScopeState,
)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def effective_action_status(
    action: GovernanceAction, *, today: date | None = None
) -> GovernanceActionStatus:
    """Derive overdue status for open actions past due date."""
    ref = today or _today()
    if action.status in {GovernanceActionStatus.COMPLETED}:
        return action.status
    if (
        action.due_date is not None
        and action.due_date < ref
        and action.status != GovernanceActionStatus.COMPLETED
    ):
        return GovernanceActionStatus.OVERDUE
    return action.status


def count_open_actions(actions: list[GovernanceAction], *, today: date | None = None) -> int:
    ref = today or _today()
    return sum(
        1
        for action in actions
        if effective_action_status(action, today=ref)
        in {
            GovernanceActionStatus.OPEN,
            GovernanceActionStatus.IN_PROGRESS,
            GovernanceActionStatus.OVERDUE,
        }
    )


def count_overdue_actions(actions: list[GovernanceAction], *, today: date | None = None) -> int:
    ref = today or _today()
    return sum(
        1
        for action in actions
        if effective_action_status(action, today=ref) == GovernanceActionStatus.OVERDUE
    )


def count_open_escalations(escalations: list[GovernanceEscalation]) -> int:
    return sum(
        1
        for escalation in escalations
        if escalation.status
        in {GovernanceEscalationStatus.OPEN, GovernanceEscalationStatus.IN_PROGRESS}
    )


def count_blocking_dependencies(dependencies: list[ProjectDependency]) -> int:
    return sum(1 for dep in dependencies if dep.status == GovernanceDependencyStatus.BLOCKING)


def count_at_risk_items(
    *,
    dependencies: list[ProjectDependency],
    scope_states: list[ProjectScopeState],
    escalations: list[GovernanceEscalation],
) -> int:
    blocking = count_blocking_dependencies(dependencies)
    pending_scope = sum(
        1 for scope in scope_states if scope.scope_status == GovernanceScopeStatus.PENDING_REVISION
    )
    critical_escalations = sum(
        1
        for escalation in escalations
        if escalation.status != GovernanceEscalationStatus.RESOLVED
        and escalation.severity.value in {"high", "critical"}
    )
    return blocking + pending_scope + critical_escalations


def dependency_overdue_days(dep: ProjectDependency, *, today: date | None = None) -> int:
    if dep.due_date is None or dep.status == GovernanceDependencyStatus.RESOLVED:
        return 0
    ref = today or _today()
    if dep.due_date >= ref:
        return 0
    return (ref - dep.due_date).days


def calculate_sla_adherence_pct(
    actions: list[GovernanceAction], *, today: date | None = None
) -> float:
    """Percentage of completed actions closed on or before due date (last 90 days)."""
    ref = today or _today()
    window_start = ref - timedelta(days=90)
    completed = [
        action
        for action in actions
        if action.status == GovernanceActionStatus.COMPLETED and action.completed_at is not None
    ]
    recent = [
        action
        for action in completed
        if action.completed_at is not None and action.completed_at.date() >= window_start
    ]
    if not recent:
        return 100.0
    on_time = 0
    for action in recent:
        if action.due_date is None:
            on_time += 1
            continue
        if action.completed_at is not None and action.completed_at.date() <= action.due_date:
            on_time += 1
    return round((on_time / len(recent)) * 100.0, 1)
