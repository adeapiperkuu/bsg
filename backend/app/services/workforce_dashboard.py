"""Bundled Workforce page dashboard payload."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.recommendation_service import (
    group_recommendations_by_title,
    grouped_recommendation_to_read,
    list_project_recommendations,
)
from app.core.security import CurrentUser
from app.db.models import AlertType, Project, UtilizationSnapshot
from app.schemas.common import Pagination
from app.schemas.domain import (
    CapabilityGapRead,
    GroupedMitigationRecommendationRead,
    OwnerOptionRead,
    ProjectRecommendationsResponse,
    ProjectWorkforceDashboardRead,
    UtilizationSnapshotRead,
)
from app.services.workforce import assert_can_read_annotators, get_project_workforce_summary
from app.services.workforce_gaps import list_project_capability_gaps
from app.services.workforce_skills import build_project_skill_matrix
from app.services.workforce_training import build_project_training_gaps

WORKFORCE_RISK_TYPE = AlertType.WORKFORCE_IMBALANCE.value
DEFAULT_UTILIZATION_LIMIT = 100
DEFAULT_CAPABILITY_GAPS_LIMIT = 100


async def _list_project_utilization_snapshots(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = DEFAULT_UTILIZATION_LIMIT,
) -> list[UtilizationSnapshot]:
    rows = (
        await session.execute(
            select(UtilizationSnapshot)
            .where(
                UtilizationSnapshot.project_id == project_id,
                UtilizationSnapshot.deleted_at.is_(None),
            )
            .order_by(UtilizationSnapshot.snapshot_date.desc())
            .limit(limit),
        )
    ).scalars().all()
    return list(rows)


async def get_project_workforce_dashboard(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    utilization_limit: int = DEFAULT_UTILIZATION_LIMIT,
    capability_gaps_limit: int = DEFAULT_CAPABILITY_GAPS_LIMIT,
) -> ProjectWorkforceDashboardRead:
    """Assemble the Workforce page sections in one service call.

    Reuses existing batched service functions. Same AsyncSession cannot safely
    run concurrent queries, so sections are loaded sequentially.
    """
    assert_can_read_annotators(current_user)

    summary = await get_project_workforce_summary(session, project, current_user)
    utilization_rows = await _list_project_utilization_snapshots(
        session,
        project.id,
        limit=utilization_limit,
    )
    skill_matrix = await build_project_skill_matrix(session, project, current_user)
    training_gaps = await build_project_training_gaps(session, project, current_user)
    capability_gap_rows = await list_project_capability_gaps(session, project, current_user)
    capability_gaps = [
        CapabilityGapRead.model_validate(gap) for gap in capability_gap_rows[:capability_gaps_limit]
    ]

    recommendation_rows, owners = await list_project_recommendations(
        session,
        project_id=project.id,
        org_id=project.org_id,
    )
    workforce_rows = [
        row for row in recommendation_rows if row.source_risk_type == WORKFORCE_RISK_TYPE
    ]
    grouped = group_recommendations_by_title(workforce_rows)
    recommendations = ProjectRecommendationsResponse(
        data=[
            GroupedMitigationRecommendationRead.model_validate(grouped_recommendation_to_read(group))
            for group in grouped
        ],
        assignable_owners=[
            OwnerOptionRead(
                owner_type=owner.owner_type.value,
                owner_id=owner.owner_id,
                label=owner.label,
            )
            for owner in owners
        ],
        pagination=Pagination(limit=100),
    )

    return ProjectWorkforceDashboardRead(
        project_id=project.id,
        summary=summary,
        utilization=[UtilizationSnapshotRead.model_validate(row) for row in utilization_rows],
        skill_matrix=skill_matrix,
        training_gaps=training_gaps,
        capability_gaps=capability_gaps,
        recommendations=recommendations,
    )
