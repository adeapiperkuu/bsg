from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.dependencies import list_project_dependencies
from app.core.security import CurrentUser
from app.db.models import AlertStatus, AlertType, GovernanceAction, Project, RiskAlert
from app.schemas.domain import (
    GovernanceActionRead,
    GovernanceDashboardKpis,
    GovernanceDashboardRead,
    ProjectDependencyRead,
)


async def get_governance_dashboard(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> GovernanceDashboardRead:
    deps = await list_project_dependencies(session, project.id)
    actions = list(
        (
            await session.execute(
                select(GovernanceAction)
                .where(GovernanceAction.project_id == project.id)
                .order_by(GovernanceAction.created_at.desc())
            )
        ).scalars()
    )
    escalations = list(
        (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project.id,
                    RiskAlert.alert_type == AlertType.QUALITY_ESCALATION,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
            )
        ).scalars()
    )

    return GovernanceDashboardRead(
        project_id=project.id,
        kpis=GovernanceDashboardKpis(
            open_dependencies=sum(1 for d in deps if d.status == "open"),
            open_actions=sum(1 for a in actions if a.status in {"open", "in_progress"}),
            quality_escalations=len(escalations),
        ),
        dependencies=[ProjectDependencyRead.model_validate(d) for d in deps],
        actions=[GovernanceActionRead.model_validate(a) for a in actions],
    )
