"""Phase 18.2 Platform Time-Series Engine."""

from app.time_series.aggregation import build_trend_summary, compare_scopes, series_for_kpi
from app.time_series.forecasting import forecast_kpi
from app.time_series.observations import persist_kpi_observation, publish_agent_score
from app.time_series.recommendations import append_recommendation_timeline

__all__ = [
    "append_recommendation_timeline",
    "build_trend_summary",
    "compare_scopes",
    "forecast_kpi",
    "persist_kpi_observation",
    "publish_agent_score",
    "series_for_kpi",
]
