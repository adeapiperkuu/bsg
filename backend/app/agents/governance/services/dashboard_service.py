from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.analytics.sla import (
    calculate_sla_adherence_pct,
    count_at_risk_items,
    count_blocking_dependencies,
    count_open_actions,
    count_open_escalations,
    count_overdue_actions,
    dependency_overdue_days,
    effective_action_status,
)
from app.agents.governance.schemas.governance import (
    GovernanceActionRead,
    GovernanceBootstrapRead,
    GovernanceEscalationRead,
    GovernanceEvidenceLinkRead,
    GovernanceKpisRead,
    GovernanceWeeklySummaryRead,
    ProjectDependencyRead,
    ProjectScopeStateRead,
)
from app.agents.governance.services.governance_service import (
    assert_can_read_governance,
    can_read_internal_governance,
    get_latest_weekly_summary,
    load_project_names,
    load_user_names,
    scoped_actions_query,
    scoped_dependencies_query,
    scoped_escalations_query,
    scoped_scope_states_query,
)
from app.agents.governance.services.knowledge_link_service import list_approved_charter_references
from app.core.security import CurrentUser
from app.db.models import AppRole, GovernanceEvidenceLink, GovernanceSummaryStatus


async def get_governance_bootstrap(
    session: AsyncSession,
    current_user: CurrentUser,
) -> GovernanceBootstrapRead:
    assert_can_read_governance(current_user)

    dependencies = await scoped_dependencies_query(session, current_user)
    actions = await scoped_actions_query(session, current_user)
    escalations = await scoped_escalations_query(session, current_user)
    scope_states = await scoped_scope_states_query(session, current_user)

    kpis = GovernanceKpisRead(
        open_actions=count_open_actions(actions),
        overdue_actions=count_overdue_actions(actions),
        open_escalations=count_open_escalations(escalations),
        blocking_dependencies=count_blocking_dependencies(dependencies),
        at_risk_items=count_at_risk_items(
            dependencies=dependencies,
            scope_states=scope_states,
            escalations=escalations,
        ),
        sla_adherence_pct=calculate_sla_adherence_pct(actions),
    )

    project_ids = {
        *(d.project_id for d in dependencies),
        *(a.project_id for a in actions),
        *(e.project_id for e in escalations),
        *(s.project_id for s in scope_states),
    }
    user_ids = {
        *(d.owner_id for d in dependencies if d.owner_id),
        *(a.owner_id for a in actions if a.owner_id),
        *(e.raised_by for e in escalations if e.raised_by),
        *(e.assigned_to for e in escalations if e.assigned_to),
    }
    project_names = await load_project_names(session, project_ids)
    user_names = await load_user_names(session, user_ids)

    dep_reads = [
        ProjectDependencyRead.model_validate(dep, from_attributes=True).model_copy(
            update={
                "overdue_days": dependency_overdue_days(dep),
                "project_name": project_names.get(dep.project_id),
                "owner_name": user_names.get(dep.owner_id) if dep.owner_id else None,
            }
        )
        for dep in dependencies
    ]

    esc_reads = [
        GovernanceEscalationRead.model_validate(esc, from_attributes=True).model_copy(
            update={
                "project_name": project_names.get(esc.project_id),
                "raised_by_name": user_names.get(esc.raised_by) if esc.raised_by else None,
                "assigned_to_name": user_names.get(esc.assigned_to) if esc.assigned_to else None,
            }
        )
        for esc in escalations
    ]

    action_reads = [
        GovernanceActionRead.model_validate(action, from_attributes=True).model_copy(
            update={
                "status": effective_action_status(action),
                "project_name": project_names.get(action.project_id),
                "owner_name": user_names.get(action.owner_id) if action.owner_id else None,
            }
        )
        for action in actions
    ]

    scope_reads = [
        ProjectScopeStateRead.model_validate(s, from_attributes=True) for s in scope_states
    ]

    weekly_summary_model = await get_latest_weekly_summary(session, current_user)
    weekly_summary: GovernanceWeeklySummaryRead | None = None
    if weekly_summary_model is not None:
        if (
            current_user.role == AppRole.CLIENT
            and weekly_summary_model.status != GovernanceSummaryStatus.APPROVED
        ):
            weekly_summary = None
        else:
            evidence_rows = (
                (
                    await session.execute(
                        select(GovernanceEvidenceLink).where(
                            GovernanceEvidenceLink.summary_id == weekly_summary_model.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            weekly_summary = GovernanceWeeklySummaryRead.model_validate(
                weekly_summary_model,
                from_attributes=True,
            ).model_copy(
                update={
                    "evidence_links": [
                        GovernanceEvidenceLinkRead.model_validate(row, from_attributes=True)
                        for row in evidence_rows
                    ],
                }
            )

    charter_references = []
    if can_read_internal_governance(current_user):
        charter_references = await list_approved_charter_references(session, current_user)

    return GovernanceBootstrapRead(
        kpis=kpis,
        dependencies=dep_reads,
        escalations=esc_reads,
        actions=action_reads,
        scope_states=scope_reads,
        weekly_summary=weekly_summary,
        charter_references=charter_references,
    )
