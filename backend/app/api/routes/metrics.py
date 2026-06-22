from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import require_role
from app.db.models import AppRole, MetricConfiguration
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import MetricConfigurationCreate, MetricConfigurationRead, MetricConfigurationUpdate

router = APIRouter(tags=["metrics"])


@router.get("/metric-configurations", response_model=ListResponse[MetricConfigurationRead])
async def list_metrics(session: SessionDep, current_user: UserDep) -> ListResponse[MetricConfigurationRead]:
    query = (
        select(MetricConfiguration)
        .where(MetricConfiguration.deleted_at.is_(None))
        .order_by(MetricConfiguration.display_order, MetricConfiguration.metric_key)
    )
    if current_user.role == AppRole.CLIENT:
        query = query.where(MetricConfiguration.is_client_visible.is_(True))
    rows = (await session.execute(query)).scalars()
    return ListResponse(data=[MetricConfigurationRead.model_validate(row) for row in rows], pagination=Pagination(limit=100))


@router.post("/metric-configurations", response_model=DataResponse[MetricConfigurationRead])
async def create_metric(
    payload: MetricConfigurationCreate,
    session: SessionDep,
    _ = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[MetricConfigurationRead]:
    metric = MetricConfiguration(**payload.model_dump())
    session.add(metric)
    await session.commit()
    await session.refresh(metric)
    return DataResponse(data=MetricConfigurationRead.model_validate(metric))


@router.patch("/metric-configurations/{metric_id}", response_model=DataResponse[MetricConfigurationRead])
async def update_metric(
    metric_id: UUID,
    payload: MetricConfigurationUpdate,
    session: SessionDep,
    _ = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> DataResponse[MetricConfigurationRead]:
    metric = (await session.execute(select(MetricConfiguration).where(MetricConfiguration.id == metric_id))).scalar_one_or_none()
    if metric is None:
        raise ApiError(404, "NOT_FOUND", "Metric configuration was not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(metric, key, value)
    await session.commit()
    await session.refresh(metric)
    return DataResponse(data=MetricConfigurationRead.model_validate(metric))


@router.delete("/metric-configurations/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: UUID,
    session: SessionDep,
    _ = Depends(require_role(AppRole.SUPER_ADMIN)),
) -> Response:
    metric = (await session.execute(select(MetricConfiguration).where(MetricConfiguration.id == metric_id))).scalar_one_or_none()
    if metric is None:
        raise ApiError(404, "NOT_FOUND", "Metric configuration was not found.")
    metric.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=204)
