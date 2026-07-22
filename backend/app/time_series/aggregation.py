"""Reusable KPI time-series aggregation, trend, and comparison helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import mean, median
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AppRole, KpiObservation, KpiObservationRollup, Project
from app.kpis.evaluation import can_view_kpi
from app.kpis.registry import get_kpi_registry
from app.schemas.time_series import (
    KpiCompareRead,
    KpiComparisonSeriesRead,
    KpiObservationRead,
    KpiSeriesPointRead,
    KpiSeriesRead,
    KpiTrendSummaryRead,
)
from app.services.scoping import scoped_project_query

logger = logging.getLogger(__name__)

MAX_RANGE_DAYS = 400
MAX_SERIES_POINTS = 366


def _as_decimal(value: Decimal | float | int | None) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def absolute_change(latest: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if latest is None or previous is None:
        return None
    return latest - previous


def percentage_change(latest: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if latest is None or previous is None:
        return None
    if previous == 0:
        return None
    return ((latest - previous) / abs(previous)) * Decimal("100")


def raw_direction(latest: Decimal | None, previous: Decimal | None) -> str:
    delta = absolute_change(latest, previous)
    if delta is None:
        return "unknown"
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def semantic_favorability(
    *,
    trend_policy: str,
    latest: Decimal | None,
    previous: Decimal | None,
    target_min: Decimal | None = None,
    target_max: Decimal | None = None,
) -> str:
    direction = raw_direction(latest, previous)
    if trend_policy == "target_range":
        if latest is None:
            return "unknown"
        if target_min is not None and target_max is not None:
            if target_min <= latest <= target_max:
                return "on_target"
            return "off_target"
        return "unknown"
    if direction == "unknown":
        return "unknown"
    if direction == "flat":
        return "stable"
    if trend_policy == "higher_is_better":
        return "improving" if direction == "up" else "declining"
    if trend_policy == "lower_is_better":
        return "improving" if direction == "down" else "declining"
    return "stable"


def _observation_read(row: KpiObservation, *, include_explainability: bool) -> KpiObservationRead:
    return KpiObservationRead(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        kpi_key=row.kpi_key,
        version=row.version,
        definition_version=row.definition_version,
        calculator_key=row.calculator_key,
        calculator_version=row.calculator_version,
        observed_at=row.observed_at,
        evaluated_at=row.evaluated_at,
        numeric_value=row.numeric_value,
        text_value=row.text_value,
        normalized_value=row.normalized_value,
        confidence=row.confidence,
        value_type=row.value_type,
        status=row.status,
        department_key=row.department_key,
        agent_key=row.agent_key,
        source_type=row.source_type,
        bucket_interval=row.bucket_interval,
        bucket_start=row.bucket_start,
        bucket_end=row.bucket_end,
        evidence_refs=list(row.evidence_refs or []),
        lineage_refs=dict(row.lineage_refs or {}),
        explainability=dict(row.explainability or {}) if include_explainability else None,
        idempotency_fingerprint=row.idempotency_fingerprint,
        supersedes_observation_id=row.supersedes_observation_id,
    )


def _assert_date_range(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    end = date_to or datetime.now(UTC)
    start = date_from or (end - timedelta(days=90))
    if start > end:
        raise ApiError(422, "INVALID_DATE_RANGE", "date_from must be before date_to.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ApiError(
            422,
            "DATE_RANGE_TOO_LARGE",
            f"Maximum date range is {MAX_RANGE_DAYS} days.",
        )
    return start, end


def _scope_filter(
    stmt: Select,
    *,
    org_id: UUID | None,
    project_id: UUID | None,
    department_key: str | None,
    agent_key: str | None,
    definition_version: str | None,
    calculator_version: str | None,
    date_from: datetime,
    date_to: datetime,
) -> Select:
    stmt = stmt.where(
        KpiObservation.observed_at >= date_from,
        KpiObservation.observed_at <= date_to,
    )
    if org_id is not None:
        stmt = stmt.where(KpiObservation.org_id == org_id)
    if project_id is not None:
        stmt = stmt.where(KpiObservation.project_id == project_id)
    if department_key is not None:
        stmt = stmt.where(KpiObservation.department_key == department_key)
    if agent_key is not None:
        stmt = stmt.where(KpiObservation.agent_key == agent_key)
    if definition_version is not None:
        stmt = stmt.where(KpiObservation.definition_version == definition_version)
    if calculator_version is not None:
        stmt = stmt.where(KpiObservation.calculator_version == calculator_version)
    return stmt


async def _authorize_kpi(current_user: CurrentUser, kpi_key: str):
    registry = get_kpi_registry()
    kpi = registry.get(kpi_key)
    if kpi is None or not can_view_kpi(kpi, current_user):
        raise ApiError(404, "NOT_FOUND", f"KPI '{kpi_key}' was not found.")
    return kpi


async def list_observations(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    org_id: UUID | None = None,
    project_id: UUID | None = None,
    department_key: str | None = None,
    agent_key: str | None = None,
    definition_version: str | None = None,
    calculator_version: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[KpiObservationRead]:
    await _authorize_kpi(current_user, kpi_key)
    start, end = _assert_date_range(date_from, date_to)
    resolved_org = org_id or current_user.org_id
    if current_user.role != AppRole.SUPER_ADMIN and resolved_org != current_user.org_id:
        raise ApiError(403, "FORBIDDEN", "Cannot read observations for another organisation.")

    stmt = select(KpiObservation).where(KpiObservation.kpi_key == kpi_key)
    stmt = _scope_filter(
        stmt,
        org_id=resolved_org,
        project_id=project_id,
        department_key=department_key,
        agent_key=agent_key,
        definition_version=definition_version,
        calculator_version=calculator_version,
        date_from=start,
        date_to=end,
    )
    stmt = stmt.order_by(KpiObservation.observed_at.desc()).offset(offset).limit(min(limit, 200))
    rows = list((await session.execute(stmt)).scalars())
    include_explain = current_user.role != AppRole.CLIENT
    return [_observation_read(row, include_explainability=include_explain) for row in rows]


async def latest_observation(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    **filters: Any,
) -> KpiObservationRead | None:
    rows = await list_observations(session, current_user, kpi_key, limit=1, **filters)
    return rows[0] if rows else None


async def build_trend_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    rolling_window: int = 7,
    **filters: Any,
) -> KpiTrendSummaryRead:
    kpi = await _authorize_kpi(current_user, kpi_key)
    rows = await list_observations(session, current_user, kpi_key, limit=max(rolling_window, 2), **filters)
    latest = rows[0] if rows else None
    previous = rows[1] if len(rows) > 1 else None
    values = [_as_decimal(r.numeric_value) for r in rows if r.numeric_value is not None]
    latest_v = None if latest is None else latest.numeric_value
    previous_v = None if previous is None else previous.numeric_value
    abs_delta = absolute_change(latest_v, previous_v)
    pct_delta = percentage_change(latest_v, previous_v)
    thresholds = dict(kpi.default_thresholds)
    return KpiTrendSummaryRead(
        kpi_key=kpi_key,
        latest=latest,
        previous=previous,
        absolute_change=abs_delta,
        percentage_change=pct_delta,
        raw_direction=raw_direction(latest_v, previous_v),  # type: ignore[arg-type]
        semantic_favorability=semantic_favorability(  # type: ignore[arg-type]
            trend_policy=kpi.trend_direction,
            latest=latest_v,
            previous=previous_v,
            target_min=_as_decimal(thresholds.get("target_min")),
            target_max=_as_decimal(thresholds.get("target_max")),
        ),
        trend_direction_policy=kpi.trend_direction,
        observation_count=len(rows),
        rolling_average=(
            Decimal(str(mean(float(v) for v in values[:rolling_window]))) if values else None
        ),
        min_value=min(values) if values else None,
        max_value=max(values) if values else None,
        average_value=Decimal(str(mean(float(v) for v in values))) if values else None,
        median_value=Decimal(str(median(float(v) for v in values))) if values else None,
    )


def _bucket_start(ts: datetime, interval: str) -> datetime:
    ts = ts.astimezone(UTC)
    if interval == "day":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "week":
        start = ts - timedelta(days=ts.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "month":
        return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if interval == "quarter":
        month = ((ts.month - 1) // 3) * 3 + 1
        return ts.replace(month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    return ts.replace(minute=0, second=0, microsecond=0)


async def series_for_kpi(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    interval: Literal["day", "week", "month", "quarter"] = "day",
    prefer_rollups: bool = True,
    **filters: Any,
) -> KpiSeriesRead:
    await _authorize_kpi(current_user, kpi_key)
    start, end = _assert_date_range(filters.get("date_from"), filters.get("date_to"))
    org_id = filters.get("org_id") or current_user.org_id
    project_id = filters.get("project_id")

    if prefer_rollups and interval in {"day", "week", "month", "quarter"}:
        rollup_stmt = select(KpiObservationRollup).where(
            KpiObservationRollup.kpi_key == kpi_key,
            KpiObservationRollup.bucket_interval == interval,
            KpiObservationRollup.bucket_start >= start,
            KpiObservationRollup.bucket_start <= end,
            KpiObservationRollup.org_id == org_id,
        )
        if project_id is not None:
            rollup_stmt = rollup_stmt.where(KpiObservationRollup.project_id == project_id)
        rollups = list(
            (
                await session.execute(
                    rollup_stmt.order_by(KpiObservationRollup.bucket_start.asc()).limit(
                        MAX_SERIES_POINTS
                    )
                )
            ).scalars()
        )
        if rollups:
            return KpiSeriesRead(
                kpi_key=kpi_key,
                interval=interval,
                source="rollups",
                points=[
                    KpiSeriesPointRead(
                        bucket_start=r.bucket_start,
                        bucket_end=r.bucket_end,
                        numeric_value=r.latest_value,
                        text_value=r.latest_text_value,
                        observation_count=r.observation_count,
                        min_value=r.min_value,
                        max_value=r.max_value,
                        avg_value=r.avg_value,
                        median_value=r.median_value,
                    )
                    for r in rollups
                ],
            )

    observations = await list_observations(
        session,
        current_user,
        kpi_key,
        org_id=org_id,
        project_id=project_id,
        department_key=filters.get("department_key"),
        agent_key=filters.get("agent_key"),
        definition_version=filters.get("definition_version"),
        calculator_version=filters.get("calculator_version"),
        date_from=start,
        date_to=end,
        limit=MAX_SERIES_POINTS,
    )
    buckets: dict[datetime, list[KpiObservationRead]] = {}
    for obs in reversed(observations):
        key = _bucket_start(obs.observed_at, interval)
        buckets.setdefault(key, []).append(obs)
    points: list[KpiSeriesPointRead] = []
    for bucket, items in sorted(buckets.items()):
        values = [v.numeric_value for v in items if v.numeric_value is not None]
        points.append(
            KpiSeriesPointRead(
                bucket_start=bucket,
                numeric_value=items[-1].numeric_value,
                text_value=items[-1].text_value,
                observation_count=len(items),
                min_value=min(values) if values else None,
                max_value=max(values) if values else None,
                avg_value=Decimal(str(mean(float(v) for v in values))) if values else None,
                median_value=Decimal(str(median(float(v) for v in values))) if values else None,
            )
        )
    return KpiSeriesRead(kpi_key=kpi_key, interval=interval, source="observations", points=points)


async def compare_scopes(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    mode: Literal["period", "baseline", "project", "department", "portfolio"] = "period",
    interval: Literal["day", "week", "month", "quarter"] = "day",
    baseline_from: datetime | None = None,
    baseline_to: datetime | None = None,
    project_ids: list[UUID] | None = None,
    **filters: Any,
) -> KpiCompareRead:
    await _authorize_kpi(current_user, kpi_key)
    start, end = _assert_date_range(filters.get("date_from"), filters.get("date_to"))
    series: list[KpiComparisonSeriesRead] = []
    absolute_deltas: dict[str, Decimal | None] = {}
    percentage_deltas: dict[str, Decimal | None] = {}

    if mode == "period":
        current = await series_for_kpi(
            session, current_user, kpi_key, interval=interval, date_from=start, date_to=end, **{
                k: v for k, v in filters.items() if k not in {"date_from", "date_to"}
            }
        )
        baseline_start, baseline_end = _assert_date_range(
            baseline_from or (start - (end - start)),
            baseline_to or start,
        )
        baseline = await series_for_kpi(
            session,
            current_user,
            kpi_key,
            interval=interval,
            date_from=baseline_start,
            date_to=baseline_end,
            **{k: v for k, v in filters.items() if k not in {"date_from", "date_to"}},
        )
        series = [
            KpiComparisonSeriesRead(
                label="current",
                scope_key="current",
                points=current.points,
                latest_value=current.points[-1].numeric_value if current.points else None,
            ),
            KpiComparisonSeriesRead(
                label="baseline",
                scope_key="baseline",
                points=baseline.points,
                latest_value=baseline.points[-1].numeric_value if baseline.points else None,
            ),
        ]
        absolute_deltas["current_vs_baseline"] = absolute_change(
            series[0].latest_value, series[1].latest_value
        )
        percentage_deltas["current_vs_baseline"] = percentage_change(
            series[0].latest_value, series[1].latest_value
        )
        return KpiCompareRead(
            kpi_key=kpi_key,
            mode=mode,
            interval=interval,
            baseline_label="previous_period",
            series=series,
            absolute_deltas=absolute_deltas,
            percentage_deltas=percentage_deltas,
        )

    # project / department / portfolio comparisons
    visible_projects = list((await session.execute(scoped_project_query(current_user))).scalars())
    if project_ids:
        allowed = {p.id for p in visible_projects}
        visible_projects = [p for p in visible_projects if p.id in set(project_ids) & allowed]
    if mode == "department":
        by_dept: dict[str, list[Project]] = {}
        for project in visible_projects:
            by_dept.setdefault(project.vertical or "unknown", []).append(project)
        for dept, projects in sorted(by_dept.items()):
            merged_points: list[KpiSeriesPointRead] = []
            latest_values: list[Decimal] = []
            for project in projects[:20]:
                s = await series_for_kpi(
                    session,
                    current_user,
                    kpi_key,
                    interval=interval,
                    date_from=start,
                    date_to=end,
                    project_id=project.id,
                    org_id=project.org_id,
                )
                if s.points:
                    merged_points = s.points
                    if s.points[-1].numeric_value is not None:
                        latest_values.append(s.points[-1].numeric_value)
            series.append(
                KpiComparisonSeriesRead(
                    label=dept,
                    scope_key=dept,
                    department_key=dept,
                    points=merged_points,
                    latest_value=(
                        Decimal(str(mean(float(v) for v in latest_values))) if latest_values else None
                    ),
                )
            )
    else:
        for project in visible_projects[:20]:
            s = await series_for_kpi(
                session,
                current_user,
                kpi_key,
                interval=interval,
                date_from=start,
                date_to=end,
                project_id=project.id,
                org_id=project.org_id,
            )
            series.append(
                KpiComparisonSeriesRead(
                    label=project.name,
                    scope_key=str(project.id),
                    project_id=project.id,
                    department_key=project.vertical,
                    points=s.points,
                    latest_value=s.points[-1].numeric_value if s.points else None,
                )
            )
    if series:
        baseline = series[0].latest_value
        for item in series[1:]:
            absolute_deltas[item.scope_key] = absolute_change(item.latest_value, baseline)
            percentage_deltas[item.scope_key] = percentage_change(item.latest_value, baseline)
    return KpiCompareRead(
        kpi_key=kpi_key,
        mode=mode,
        interval=interval,
        series=series,
        absolute_deltas=absolute_deltas,
        percentage_deltas=percentage_deltas,
    )
