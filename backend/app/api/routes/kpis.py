"""Phase 18.1 KPI Semantic Layer HTTP API (+ Phase 18.2 history endpoints)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole
from app.kpis.catalog import get_kpi_definition, list_kpi_definitions
from app.kpis.evaluation import build_calculation_metadata, can_view_kpi, evaluate_kpi, evaluate_kpis
from app.kpis.registry import get_kpi_registry
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.kpi import (
    KpiBatchEvaluateRequest,
    KpiCalculationMetadataRead,
    KpiDefinitionRead,
    KpiEvaluateRequest,
    KpiEvaluationRead,
)
from app.schemas.time_series import (
    KpiCompareRead,
    KpiForecastRead,
    KpiObservationRead,
    KpiSeriesRead,
    KpiTrendSummaryRead,
)
from app.time_series.aggregation import (
    build_trend_summary,
    compare_scopes,
    latest_observation,
    list_observations,
    series_for_kpi,
)
from app.time_series.forecasting import forecast_kpi

router = APIRouter(prefix="/kpis", tags=["kpis"])


@router.get("", response_model=ListResponse[KpiDefinitionRead])
async def list_kpis(
    session: SessionDep,
    current_user: UserDep,
    owner_agent: Annotated[str | None, Query()] = None,
) -> ListResponse[KpiDefinitionRead]:
    data = await list_kpi_definitions(session, current_user, owner_agent=owner_agent)
    return ListResponse(data=data, pagination=Pagination(limit=max(len(data), 1)))


@router.post("/evaluate", response_model=DataResponse[list[KpiEvaluationRead]])
async def evaluate_kpis_batch(
    payload: KpiBatchEvaluateRequest,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[list[KpiEvaluationRead]]:
    _assert_org_scope(current_user, payload.org_id)
    results = await evaluate_kpis(
        session,
        current_user,
        payload.kpi_ids,
        project_id=payload.project_id,
        org_id=payload.org_id,
        as_of=payload.as_of,
        version=payload.version,
        inputs=payload.inputs,
        include_explainability=payload.include_explainability,
        persist_observation=payload.persist_observation,
        source_type="evaluation",
    )
    return DataResponse(data=results)


@router.get("/{kpi_id}", response_model=DataResponse[KpiDefinitionRead])
async def get_kpi(
    kpi_id: str,
    session: SessionDep,
    current_user: UserDep,
    version: Annotated[str | None, Query()] = None,
) -> DataResponse[KpiDefinitionRead]:
    definition = await get_kpi_definition(session, current_user, kpi_id, version=version)
    if definition is None:
        raise ApiError(404, "NOT_FOUND", f"KPI '{kpi_id}' was not found.")
    return DataResponse(data=definition)


@router.get("/{kpi_id}/calculation", response_model=DataResponse[KpiCalculationMetadataRead])
async def get_kpi_calculation(
    kpi_id: str,
    session: SessionDep,
    current_user: UserDep,
    version: Annotated[str | None, Query()] = None,
) -> DataResponse[KpiCalculationMetadataRead]:
    registry = get_kpi_registry()
    kpi = registry.get(kpi_id, version)
    if kpi is None or not can_view_kpi(kpi, current_user):
        raise ApiError(404, "NOT_FOUND", f"KPI '{kpi_id}' was not found.")
    metadata = await build_calculation_metadata(session, kpi, current_user)
    return DataResponse(data=metadata)


@router.post("/{kpi_id}/evaluate", response_model=DataResponse[KpiEvaluationRead])
async def evaluate_single_kpi(
    kpi_id: str,
    payload: KpiEvaluateRequest,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[KpiEvaluationRead]:
    _assert_org_scope(current_user, payload.org_id)
    result = await evaluate_kpi(
        session,
        current_user,
        kpi_id,
        project_id=payload.project_id,
        org_id=payload.org_id,
        as_of=payload.as_of,
        version=payload.version,
        inputs=payload.inputs,
        include_explainability=payload.include_explainability,
        persist_observation=payload.persist_observation,
        source_type="evaluation",
    )
    return DataResponse(data=result)


@router.get("/{kpi_key}/history", response_model=ListResponse[KpiObservationRead])
async def kpi_history(
    kpi_key: str,
    session: SessionDep,
    current_user: UserDep,
    org_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    department_key: Annotated[str | None, Query()] = None,
    agent_key: Annotated[str | None, Query()] = None,
    definition_version: Annotated[str | None, Query()] = None,
    calculator_version: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListResponse[KpiObservationRead]:
    data = await list_observations(
        session,
        current_user,
        kpi_key,
        org_id=org_id,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return ListResponse(data=data, pagination=Pagination(limit=limit, offset=offset, total=len(data)))


@router.get("/{kpi_key}/latest", response_model=DataResponse[KpiObservationRead | None])
async def kpi_latest(
    kpi_key: str,
    session: SessionDep,
    current_user: UserDep,
    org_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    department_key: Annotated[str | None, Query()] = None,
    agent_key: Annotated[str | None, Query()] = None,
    definition_version: Annotated[str | None, Query()] = None,
    calculator_version: Annotated[str | None, Query()] = None,
) -> DataResponse[KpiObservationRead | None]:
    data = await latest_observation(
        session,
        current_user,
        kpi_key,
        org_id=org_id,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
    )
    return DataResponse(data=data)


@router.get("/{kpi_key}/trend", response_model=DataResponse[KpiTrendSummaryRead])
async def kpi_trend(
    kpi_key: str,
    session: SessionDep,
    current_user: UserDep,
    org_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    department_key: Annotated[str | None, Query()] = None,
    agent_key: Annotated[str | None, Query()] = None,
    definition_version: Annotated[str | None, Query()] = None,
    calculator_version: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    rolling_window: Annotated[int, Query(ge=2, le=90)] = 7,
) -> DataResponse[KpiTrendSummaryRead]:
    data = await build_trend_summary(
        session,
        current_user,
        kpi_key,
        rolling_window=rolling_window,
        org_id=org_id,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
        date_from=date_from,
        date_to=date_to,
    )
    return DataResponse(data=data)


@router.get("/{kpi_key}/series", response_model=DataResponse[KpiSeriesRead])
async def kpi_series(
    kpi_key: str,
    session: SessionDep,
    current_user: UserDep,
    interval: Annotated[Literal["day", "week", "month", "quarter"], Query()] = "day",
    org_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    department_key: Annotated[str | None, Query()] = None,
    agent_key: Annotated[str | None, Query()] = None,
    definition_version: Annotated[str | None, Query()] = None,
    calculator_version: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> DataResponse[KpiSeriesRead]:
    data = await series_for_kpi(
        session,
        current_user,
        kpi_key,
        interval=interval,
        org_id=org_id,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
        date_from=date_from,
        date_to=date_to,
    )
    return DataResponse(data=data)


@router.get("/{kpi_key}/compare", response_model=DataResponse[KpiCompareRead])
async def kpi_compare(
    kpi_key: str,
    session: SessionDep,
    current_user: UserDep,
    mode: Annotated[Literal["period", "baseline", "project", "department", "portfolio"], Query()] = "period",
    interval: Annotated[Literal["day", "week", "month", "quarter"], Query()] = "day",
    org_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    department_key: Annotated[str | None, Query()] = None,
    agent_key: Annotated[str | None, Query()] = None,
    definition_version: Annotated[str | None, Query()] = None,
    calculator_version: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    compare_project_id: Annotated[UUID | None, Query()] = None,
) -> DataResponse[KpiCompareRead]:
    data = await compare_scopes(
        session,
        current_user,
        kpi_key,
        mode=mode,
        interval=interval,
        org_id=org_id,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
        date_from=date_from,
        date_to=date_to,
        project_ids=[compare_project_id] if compare_project_id else None,
    )
    return DataResponse(data=data)


@router.get("/{kpi_key}/forecast", response_model=DataResponse[KpiForecastRead])
async def kpi_forecast(
    kpi_key: str,
    session: SessionDep,
    current_user: UserDep,
    horizon: Annotated[int, Query(ge=1, le=12)] = 4,
    org_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    department_key: Annotated[str | None, Query()] = None,
    agent_key: Annotated[str | None, Query()] = None,
    definition_version: Annotated[str | None, Query()] = None,
    calculator_version: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> DataResponse[KpiForecastRead]:
    data = await forecast_kpi(
        session,
        current_user,
        kpi_key,
        horizon=horizon,
        org_id=org_id,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
        date_from=date_from,
        date_to=date_to,
    )
    return DataResponse(data=data)


def _assert_org_scope(current_user: CurrentUser, org_id: UUID | None) -> None:
    if org_id is None:
        return
    if current_user.role != AppRole.SUPER_ADMIN and org_id != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot evaluate KPIs for another organisation.")
