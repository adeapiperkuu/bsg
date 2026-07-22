from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import or_, select

from app.agents.delivery.configuration import (
    invalidate_delivery_scoring_thresholds_cache,
    validate_delivery_metric_threshold_config,
)
from app.agents.delivery.services.dashboard_service import clear_delivery_portfolio_cache
from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, MetricConfiguration
from app.kpis.thresholds import invalidate_kpi_threshold_cache
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    MetricConfigurationCreate,
    MetricConfigurationRead,
    MetricConfigurationUpdate,
)

router = APIRouter(tags=["metrics"])
MetricAdminDep = Annotated[CurrentUser, Depends(require_role(AppRole.SUPER_ADMIN))]


@router.get("/metric-configurations", response_model=ListResponse[MetricConfigurationRead])
async def list_metrics(
    session: SessionDep,
    current_user: UserDep,
) -> ListResponse[MetricConfigurationRead]:
    query = (
        select(MetricConfiguration)
        .where(MetricConfiguration.deleted_at.is_(None))
        .order_by(MetricConfiguration.display_order, MetricConfiguration.metric_key)
    )
    if current_user.role == AppRole.CLIENT:
        query = query.where(MetricConfiguration.is_client_visible.is_(True))
    if current_user.role != AppRole.SUPER_ADMIN:
        query = query.where(
            or_(
                MetricConfiguration.org_id.is_(None),
                MetricConfiguration.org_id == current_user.org_id,
            )
        )
    rows = (await session.execute(query)).scalars()
    return ListResponse(
        data=[MetricConfigurationRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=100),
    )


@router.post("/metric-configurations", response_model=DataResponse[MetricConfigurationRead])
async def create_metric(
    payload: MetricConfigurationCreate,
    session: SessionDep,
    _: MetricAdminDep,
) -> DataResponse[MetricConfigurationRead]:
    try:
        validate_delivery_metric_threshold_config(payload.metric_key, payload.threshold_config)
    except ValueError as exc:
        raise ApiError(422, "INVALID_DELIVERY_THRESHOLDS", str(exc)) from exc
    metric = MetricConfiguration(**payload.model_dump())
    session.add(metric)
    await session.commit()
    invalidate_delivery_scoring_thresholds_cache(metric.org_id)
    invalidate_kpi_threshold_cache(metric.metric_key, metric.org_id)
    clear_delivery_portfolio_cache(org_id=metric.org_id)
    await session.refresh(metric)
    return DataResponse(data=MetricConfigurationRead.model_validate(metric))


@router.patch(
    "/metric-configurations/{metric_id}",
    response_model=DataResponse[MetricConfigurationRead],
)
async def update_metric(
    metric_id: UUID,
    payload: MetricConfigurationUpdate,
    session: SessionDep,
    _: MetricAdminDep,
) -> DataResponse[MetricConfigurationRead]:
    metric = (
        await session.execute(
            select(MetricConfiguration).where(MetricConfiguration.id == metric_id)
        )
    ).scalar_one_or_none()
    if metric is None:
        raise ApiError(404, "NOT_FOUND", "Metric configuration was not found.")
    if "threshold_config" in payload.model_fields_set:
        try:
            validate_delivery_metric_threshold_config(
                metric.metric_key,
                payload.threshold_config,
            )
        except ValueError as exc:
            raise ApiError(422, "INVALID_DELIVERY_THRESHOLDS", str(exc)) from exc
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(metric, key, value)
    await session.commit()
    invalidate_delivery_scoring_thresholds_cache(metric.org_id)
    invalidate_kpi_threshold_cache(metric.metric_key, metric.org_id)
    clear_delivery_portfolio_cache(org_id=metric.org_id)
    await session.refresh(metric)
    return DataResponse(data=MetricConfigurationRead.model_validate(metric))


@router.delete("/metric-configurations/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: UUID,
    session: SessionDep,
    _: MetricAdminDep,
) -> Response:
    metric = (
        await session.execute(
            select(MetricConfiguration).where(MetricConfiguration.id == metric_id)
        )
    ).scalar_one_or_none()
    if metric is None:
        raise ApiError(404, "NOT_FOUND", "Metric configuration was not found.")
    metric.deleted_at = datetime.now(UTC)
    await session.commit()
    invalidate_delivery_scoring_thresholds_cache(metric.org_id)
    invalidate_kpi_threshold_cache(metric.metric_key, metric.org_id)
    clear_delivery_portfolio_cache(org_id=metric.org_id)
    return Response(status_code=204)
