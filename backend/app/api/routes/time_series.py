"""Phase 18.2 shared time-series HTTP API (dimensions + recommendation timeline)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, select

from app.api.deps import SessionDep, UserDep
from app.db.models import AppRole, KpiObservation, Project
from app.kpis.registry import get_kpi_registry
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.time_series import (
    RecommendationSubjectSummaryRead,
    RecommendationTimelineEventRead,
    TimeSeriesDimensionsRead,
)
from app.time_series.recommendations import list_recommendation_subjects, list_recommendation_timeline

router = APIRouter(prefix="/time-series", tags=["time-series"])


@router.get("/dimensions", response_model=DataResponse[TimeSeriesDimensionsRead])
async def time_series_dimensions(
    session: SessionDep,
    current_user: UserDep,
    org_id: Annotated[UUID | None, Query()] = None,
) -> DataResponse[TimeSeriesDimensionsRead]:
    resolved_org = org_id or current_user.org_id
    if current_user.role != AppRole.SUPER_ADMIN and resolved_org != current_user.org_id:
        resolved_org = current_user.org_id

    registry = get_kpi_registry()
    kpi_keys = [k.kpi_key for k in registry.list_kpis()]
    # Prefer keys that already have observations for this org.
    observed_keys = list(
        (
            await session.execute(
                select(distinct(KpiObservation.kpi_key)).where(KpiObservation.org_id == resolved_org)
            )
        ).scalars()
    )
    agents = list(
        (
            await session.execute(
                select(distinct(KpiObservation.agent_key)).where(
                    KpiObservation.org_id == resolved_org,
                    KpiObservation.agent_key.is_not(None),
                )
            )
        ).scalars()
    )
    departments = list(
        (
            await session.execute(
                select(distinct(Project.vertical)).where(
                    Project.org_id == resolved_org,
                    Project.deleted_at.is_(None),
                    Project.vertical.is_not(None),
                )
            )
        ).scalars()
    )
    bounds = (
        await session.execute(
            select(
                func.min(KpiObservation.observed_at),
                func.max(KpiObservation.observed_at),
            ).where(KpiObservation.org_id == resolved_org)
        )
    ).one()
    return DataResponse(
        data=TimeSeriesDimensionsRead(
            kpi_keys=sorted(set(kpi_keys) | set(observed_keys)),
            agents=sorted(a for a in agents if a),
            departments=sorted(d for d in departments if d),
            intervals=["hour", "day", "week", "month", "quarter"],
            min_observed_at=bounds[0],
            max_observed_at=bounds[1],
        )
    )


@router.get("/recommendations", response_model=ListResponse[RecommendationSubjectSummaryRead])
async def recommendation_subjects(
    session: SessionDep,
    current_user: UserDep,
    domain: Annotated[str | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListResponse[RecommendationSubjectSummaryRead]:
    data, pagination = await list_recommendation_subjects(
        session,
        current_user,
        domain=domain,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return ListResponse(data=data, pagination=pagination)


@router.get(
    "/recommendations/{subject_id}/timeline",
    response_model=ListResponse[RecommendationTimelineEventRead],
)
async def recommendation_timeline(
    subject_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListResponse[RecommendationTimelineEventRead]:
    data, pagination = await list_recommendation_timeline(
        session,
        current_user,
        subject_id,
        limit=limit,
        offset=offset,
    )
    return ListResponse(data=data, pagination=pagination)
