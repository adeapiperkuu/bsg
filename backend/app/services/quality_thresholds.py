from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MetricConfiguration, RiskTier
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_THRESHOLD_CACHE_TTL_S = 60
_threshold_cache: tuple[dict[str, "ThresholdConfig"], float] | None = None

Direction = Literal["higher_is_better", "lower_is_better"]

DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "gold_set_accuracy": {
        "green_min": 96.0,
        "amber_min": 94.0,
        "red_min": 92.0,
        "wow_drop_amber": 1.0,
        "wow_drop_red": 2.0,
        "wow_drop_critical": 4.0,
        "direction": "higher_is_better",
    },
    "iaa_krippendorff_alpha": {
        "green_min": 0.90,
        "amber_min": 0.85,
        "red_min": 0.80,
        "wow_drop_amber": 0.03,
        "wow_drop_red": 0.05,
        "wow_drop_critical": 0.08,
        "direction": "higher_is_better",
    },
    "rework_rate": {
        "green_max": 3.0,
        "amber_max": 4.0,
        "red_max": 6.0,
        "wow_rise_amber": 1.0,
        "wow_rise_red": 2.0,
        "wow_rise_critical": 4.0,
        "direction": "lower_is_better",
    },
}

_logged_defaults: set[str] = set()


@dataclass(frozen=True)
class ThresholdConfig:
    metric_key: str
    direction: Direction
    green_min: float | None = None
    amber_min: float | None = None
    red_min: float | None = None
    green_max: float | None = None
    amber_max: float | None = None
    red_max: float | None = None
    wow_drop_amber: float = 1.0
    wow_drop_red: float = 2.0
    wow_drop_critical: float = 4.0
    wow_rise_amber: float = 1.0
    wow_rise_red: float = 2.0
    wow_rise_critical: float = 4.0

    @classmethod
    def from_dict(cls, metric_key: str, data: dict[str, Any]) -> ThresholdConfig:
        return cls(metric_key=metric_key, **{k: v for k, v in data.items() if k != "metric_key"})


async def _load_thresholds_from_db(session: AsyncSession) -> dict[str, ThresholdConfig]:
    rows = (
        await session.execute(
            select(MetricConfiguration).where(
                MetricConfiguration.deleted_at.is_(None),
                MetricConfiguration.metric_key.in_(DEFAULT_THRESHOLDS.keys()),
            )
        )
    ).scalars()

    configs: dict[str, ThresholdConfig] = {}
    db_keys: set[str] = set()
    for row in rows:
        db_keys.add(row.metric_key)
        raw = row.threshold_config or DEFAULT_THRESHOLDS[row.metric_key]
        if row.threshold_config is None and row.metric_key not in _logged_defaults:
            logger.info("Using default threshold config for %s", row.metric_key)
            _logged_defaults.add(row.metric_key)
        configs[row.metric_key] = ThresholdConfig.from_dict(row.metric_key, raw)

    for key, default in DEFAULT_THRESHOLDS.items():
        if key not in db_keys:
            if key not in _logged_defaults:
                logger.info("Using default threshold config for %s (no DB row)", key)
                _logged_defaults.add(key)
            configs[key] = ThresholdConfig.from_dict(key, default)

    return configs


async def load_thresholds(session: AsyncSession) -> dict[str, ThresholdConfig]:
    global _threshold_cache

    if _threshold_cache is not None and time.monotonic() < _threshold_cache[1]:
        return _threshold_cache[0]

    configs = await _load_thresholds_from_db(session)
    _threshold_cache = (configs, time.monotonic() + _THRESHOLD_CACHE_TTL_S)
    return configs


async def warm_thresholds_cache() -> None:
    """Pre-load thresholds at startup so the first quality-page request avoids a cold DB read."""
    async with AsyncSessionLocal() as session:
        await load_thresholds(session)


def _to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def classify_value_severity(config: ThresholdConfig, value: Decimal | float | None) -> RiskTier:
    v = _to_float(value)
    if v is None:
        return RiskTier.LOW

    if config.direction == "higher_is_better":
        if config.red_min is not None and v < config.red_min:
            return RiskTier.CRITICAL
        if config.amber_min is not None and v < config.amber_min:
            return RiskTier.HIGH
        if config.green_min is not None and v < config.green_min:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    if config.red_max is not None and v > config.red_max:
        return RiskTier.CRITICAL
    if config.amber_max is not None and v > config.amber_max:
        return RiskTier.HIGH
    if config.green_max is not None and v > config.green_max:
        return RiskTier.MEDIUM
    return RiskTier.LOW


def classify_wow_change(
    config: ThresholdConfig,
    current: Decimal | float | None,
    prior: Decimal | float | None,
) -> RiskTier:
    cur = _to_float(current)
    prev = _to_float(prior)
    if cur is None or prev is None:
        return RiskTier.LOW

    if config.direction == "higher_is_better":
        drop = prev - cur
        if drop >= config.wow_drop_critical:
            return RiskTier.CRITICAL
        if drop >= config.wow_drop_red:
            return RiskTier.HIGH
        if drop >= config.wow_drop_amber:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    rise = cur - prev
    if rise >= config.wow_rise_critical:
        return RiskTier.CRITICAL
    if rise >= config.wow_rise_red:
        return RiskTier.HIGH
    if rise >= config.wow_rise_amber:
        return RiskTier.MEDIUM
    return RiskTier.LOW


def max_tier(*tiers: RiskTier) -> RiskTier:
    order = [RiskTier.LOW, RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.CRITICAL]
    return max(tiers, key=lambda t: order.index(t))
