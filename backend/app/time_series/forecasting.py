"""Deterministic bounded KPI forecasting (no LLM, no heavy ML deps)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.schemas.time_series import KpiForecastPointRead, KpiForecastRead
from app.time_series.aggregation import list_observations

logger = logging.getLogger(__name__)

FORECAST_MODEL_VERSION = "linear_ols_v1"
MIN_HISTORY = 5
MAX_HORIZON = 12
DEFAULT_HORIZON = 4


def _ols_forecast(
    values: list[float],
    horizon: int,
) -> tuple[list[float], list[tuple[float, float]], str]:
    """Ordinary least squares linear trend with residual-based confidence interval."""
    n = len(values)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    method = FORECAST_MODEL_VERSION
    if denom == 0:
        # Degenerate: flat series → moving average fallback.
        method = "moving_average_v1"
        avg = y_mean
        preds = [avg for _ in range(horizon)]
        return preds, [(avg, avg) for _ in preds], method

    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True)) / denom
    intercept = y_mean - slope * x_mean
    fitted = [intercept + slope * x for x in xs]
    residuals = [y - f for y, f in zip(values, fitted, strict=True)]
    residual_std = (sum(r * r for r in residuals) / max(n - 2, 1)) ** 0.5
    # ~95% interval using 1.96 * residual std (deterministic, no SciPy).
    half = 1.96 * residual_std
    preds: list[float] = []
    bounds: list[tuple[float, float]] = []
    for step in range(1, horizon + 1):
        value = intercept + slope * (n - 1 + step)
        preds.append(value)
        bounds.append((value - half, value + half))
    if abs(slope) < 1e-12:
        method = "moving_average_v1"
    return preds, bounds, method


async def forecast_kpi(
    session: AsyncSession,
    current_user: CurrentUser,
    kpi_key: str,
    *,
    horizon: int = DEFAULT_HORIZON,
    min_history: int = MIN_HISTORY,
    **filters: Any,
) -> KpiForecastRead:
    started = datetime.now(UTC)
    horizon = max(1, min(horizon, MAX_HORIZON))
    min_history = max(3, min_history)
    rows = await list_observations(
        session,
        current_user,
        kpi_key,
        limit=200,
        **filters,
    )
    # Oldest → newest for fitting.
    chronological = list(reversed(rows))
    numeric = [float(r.numeric_value) for r in chronological if r.numeric_value is not None]
    if len(numeric) < min_history:
        logger.info(
            "event=kpi_forecast_insufficient_data kpi_key=%s sample_count=%s min_history=%s",
            kpi_key,
            len(numeric),
            min_history,
        )
        return KpiForecastRead(
            kpi_key=kpi_key,
            status="insufficient_data",
            sample_count=len(numeric),
            message=f"Need at least {min_history} numeric observations for forecasting.",
            assumptions=["No LLM-generated forecasts", "No automatic operational actions"],
        )

    preds, bounds, method = _ols_forecast(numeric, horizon)
    last_ts = chronological[-1].observed_at
    # Infer step from median spacing, default 7 days.
    if len(chronological) >= 2:
        deltas = [
            (chronological[i].observed_at - chronological[i - 1].observed_at).total_seconds()
            for i in range(1, len(chronological))
        ]
        step_seconds = sorted(deltas)[len(deltas) // 2]
        step = timedelta(seconds=max(step_seconds, 86400))
    else:
        step = timedelta(days=7)

    points = [
        KpiForecastPointRead(
            forecast_at=last_ts + step * (idx + 1),
            value=Decimal(str(round(value, 6))),
            lower_bound=Decimal(str(round(bounds[idx][0], 6))),
            upper_bound=Decimal(str(round(bounds[idx][1], 6))),
        )
        for idx, value in enumerate(preds)
    ]
    duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000
    logger.info(
        "event=kpi_forecast_completed kpi_key=%s method=%s sample_count=%s horizon=%s duration_ms=%.2f",
        kpi_key,
        method,
        len(numeric),
        horizon,
        duration_ms,
    )
    return KpiForecastRead(
        kpi_key=kpi_key,
        status="ok",
        method=method,
        model_version=FORECAST_MODEL_VERSION,
        horizon=horizon,
        training_window_start=chronological[0].observed_at,
        training_window_end=chronological[-1].observed_at,
        sample_count=len(numeric),
        assumptions=[
            "Deterministic linear OLS or moving-average fallback",
            "Confidence interval from residual standard deviation",
            "Historical definition/calculator versions are not re-evaluated",
            "No automatic actions from forecasts",
        ],
        points=points,
    )
