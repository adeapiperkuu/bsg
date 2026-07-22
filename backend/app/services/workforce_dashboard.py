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
    RecommendationRow,
    group_recommendations_by_title,
    grouped_recommendation_to_read,
    list_project_recommendations,
)
from app.core.field_permissions import authorize_fields
from app.core.security import CurrentUser
from app.db.models import AlertType, Project, UtilizationSnapshot
from app.db.rls import set_rls_context
from app.db.session import session_scope
from app.schemas.common import Pagination
from app.schemas.domain import (
    CapabilityGapRead,
    GroupedMitigationRecommendationRead,
    ProjectRecommendationsResponse,
    ProjectWorkforceDashboardRead,
    ProjectWorkforceSummaryRead,
    SkillMatrixRead,
    TrainingGapSummaryRead,
    UtilizationSnapshotRead,
)
from app.services.workforce import (
    assert_can_read_annotators,
    load_project_roster,
    project_workforce_summary_from_roster,
)
from app.services.workforce_gaps import (
    list_project_capability_gaps,
    project_can_rebalance_from_utilization,
    workforce_mitigation_copy_for_gap,
)
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
    """Team-level snapshots only — charts/trends ignore annotator-scoped rows."""
    rows = (
        await session.execute(
            select(UtilizationSnapshot)
            .where(
                UtilizationSnapshot.project_id == project_id,
                UtilizationSnapshot.deleted_at.is_(None),
                UtilizationSnapshot.team_id.is_not(None),
                UtilizationSnapshot.annotator_id.is_(None),
            )
            .order_by(UtilizationSnapshot.snapshot_date.desc())
            .limit(limit),
        )
    ).scalars().all()
    return list(rows)


def _latest_team_utilization(
    snapshots: list[UtilizationSnapshot],
) -> dict:
    latest: dict = {}
    for snap in snapshots:
        if snap.team_id is None or snap.annotator_id is not None:
            continue
        latest.setdefault(snap.team_id, snap)
    return latest


def _align_workforce_recommendation_rows(
    rows: list[RecommendationRow],
    gaps: list,
    *,
    can_rebalance: bool,
) -> list[RecommendationRow]:
    """Rewrite mitigation titles/descriptions so they match gap type + Optimization."""
    gaps_by_title = {gap.title: gap for gap in gaps}
    for row in rows:
        gap = gaps_by_title.get(row.source_risk_title or "")
        if gap is None:
            continue
        title, description = workforce_mitigation_copy_for_gap(gap, can_rebalance=can_rebalance)
        row.recommendation.title = title
        row.recommendation.description = description
    return rows


async def _build_roster_backed_sections(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> tuple[ProjectWorkforceSummaryRead, SkillMatrixRead, TrainingGapSummaryRead]:
    """Load teams/annotators once, then build summary + matrix + training gaps."""
    teams, annotators = await load_project_roster(session, project)
    summary = project_workforce_summary_from_roster(project, teams, annotators)
    skill_matrix = await build_project_skill_matrix(
        session,
        project,
        current_user,
        teams=teams,
        annotators=annotators,
    )
    training_gaps = await build_project_training_gaps(
        session,
        project,
        current_user,
        teams=teams,
        annotators=annotators,
    )
    return summary, skill_matrix, training_gaps


async def get_project_workforce_dashboard(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    utilization_limit: int = DEFAULT_UTILIZATION_LIMIT,
    capability_gaps_limit: int = DEFAULT_CAPABILITY_GAPS_LIMIT,
) -> ProjectWorkforceDashboardRead:
    """Assemble the Workforce page sections in one service call.

    Core sections run concurrently on pooled connections. Summary, skill matrix, and
    training gaps share one roster load (one section) so fan-out stays within the
    session-mode concurrency budget instead of re-querying teams/annotators three times.

    Optimization is intentionally omitted: it is the heaviest section and is loaded
    via ``GET .../workforce-optimization`` after first paint so KPIs/matrix are not
    blocked by match/rebalance/SME engines.
    """
    assert_can_read_annotators(current_user)
    # Request session is unused for section work (parallel sessions via _run_section).
    del session

    (
        roster_sections,
        utilization_rows,
        capability_gap_rows,
        recommendations_result,
    ) = await asyncio.gather(
        _run_section(
            current_user,
            lambda s: _build_roster_backed_sections(s, project, current_user),
        ),
        _run_section(
            current_user,
            lambda s: _list_project_utilization_snapshots(s, project.id, limit=utilization_limit),
        ),
        _run_section(
            current_user,
            lambda s: list_project_capability_gaps(
                s,
                project,
                current_user,
                limit=capability_gaps_limit,
            ),
        ),
        _run_section(
            current_user,
            lambda s: list_project_recommendations(
                s,
                project_id=project.id,
                org_id=project.org_id,
                source_risk_types={WORKFORCE_RISK_TYPE},
                include_assignable_owners=False,
            ),
        ),
    )

    summary, skill_matrix, training_gaps = roster_sections

    capability_gaps = [CapabilityGapRead.model_validate(gap) for gap in capability_gap_rows]

    recommendation_rows, _owners = recommendations_result
    can_rebalance = project_can_rebalance_from_utilization(
        _latest_team_utilization(utilization_rows),
    )
    workforce_rows = _align_workforce_recommendation_rows(
        recommendation_rows,
        capability_gap_rows,
        can_rebalance=can_rebalance,
    )
    grouped = group_recommendations_by_title(workforce_rows)
    recommendations = ProjectRecommendationsResponse(
        data=[
            GroupedMitigationRecommendationRead.model_validate(grouped_recommendation_to_read(group))
            for group in grouped
        ],
        assignable_owners=[],
        pagination=Pagination(limit=100),
    )

    dashboard = ProjectWorkforceDashboardRead(
        project_id=project.id,
        summary=summary,
        utilization=[UtilizationSnapshotRead.model_validate(row) for row in utilization_rows],
        skill_matrix=skill_matrix,
        training_gaps=training_gaps,
        capability_gaps=capability_gaps,
        recommendations=recommendations,
        optimization=None,
    )
    # Phase 19.1 — never send unauthorized top-level fields to the client.
    filtered = authorize_fields(dashboard, current_user.role, domain="workforce")
    return ProjectWorkforceDashboardRead.model_validate(filtered)
