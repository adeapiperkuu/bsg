"""Bundled Workforce page dashboard payload."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import TypeVar
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
from app.db.rls import set_rls_context
from app.db.session import session_scope
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

T = TypeVar("T")


async def _run_section(
    current_user: CurrentUser,
    builder: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Run one dashboard section on its own pooled connection.

    A single AsyncSession maps to one DB connection and cannot multiplex concurrent
    queries, so the sections can only run in parallel on independent sessions. Each
    fresh session must re-establish the request's RLS context (the app role has
    BYPASSRLS; ``set_rls_context`` switches to ``authenticated`` + the JWT claims, so
    without it a spawned session would run unscoped) — mirroring what
    ``get_current_user`` does for the request-injected session.
    """
    async with session_scope() as section_session:
        await set_rls_context(section_session, json.dumps({"sub": str(current_user.id)}))
        return await builder(section_session)


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

    Reuses existing batched service functions. The six sections are independent, so
    they run concurrently — each on its own pooled connection via ``_run_section`` —
    instead of serializing on the request session. Against the remote Supabase pooler
    (where every query is a network round trip) this collapses the wall time from the
    sum of the sections toward the slowest single section. The client pool is sized for
    exactly this fan-out (see ``app/db/session.py``).
    """
    assert_can_read_annotators(current_user)

    (
        summary,
        utilization_rows,
        skill_matrix,
        training_gaps,
        capability_gap_rows,
        recommendations_result,
    ) = await asyncio.gather(
        _run_section(current_user, lambda s: get_project_workforce_summary(s, project, current_user)),
        _run_section(
            current_user,
            lambda s: _list_project_utilization_snapshots(s, project.id, limit=utilization_limit),
        ),
        _run_section(current_user, lambda s: build_project_skill_matrix(s, project, current_user)),
        _run_section(current_user, lambda s: build_project_training_gaps(s, project, current_user)),
        _run_section(current_user, lambda s: list_project_capability_gaps(s, project, current_user)),
        _run_section(
            current_user,
            lambda s: list_project_recommendations(s, project_id=project.id, org_id=project.org_id),
        ),
    )

    capability_gaps = [
        CapabilityGapRead.model_validate(gap) for gap in capability_gap_rows[:capability_gaps_limit]
    ]

    recommendation_rows, owners = recommendations_result
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
