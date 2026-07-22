"""Shared threshold resolution: org override → global template → code default."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MetricConfiguration

logger = logging.getLogger(__name__)

CONFIGURATION_CACHE_TTL = timedelta(seconds=60)
CONFIGURATION_CACHE_MAX_ENTRIES = 1024


@dataclass(frozen=True, slots=True)
class ResolvedThresholds:
    thresholds: dict[str, Any]
    source: str  # "org" | "global" | "default" | "none"


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    loaded_at: datetime
    payload: dict[str, Any] | None
    source: str


_threshold_cache: dict[tuple[str, UUID | None], _CacheEntry] = {}
_cache_lock = asyncio.Lock()


def invalidate_kpi_threshold_cache(
    metric_key: str | None = None,
    organisation_id: UUID | None = None,
) -> int:
    if metric_key is None and organisation_id is None:
        count = len(_threshold_cache)
        _threshold_cache.clear()
        return count
    removed = 0
    for key in list(_threshold_cache):
        cached_key, cached_org = key
        if metric_key is not None and cached_key != metric_key:
            continue
        if organisation_id is not None and cached_org != organisation_id:
            continue
        _threshold_cache.pop(key, None)
        removed += 1
    return removed


async def resolve_thresholds(
    session: AsyncSession | None,
    *,
    metric_config_key: str | None,
    organisation_id: UUID | None,
    defaults: dict[str, Any] | None = None,
) -> ResolvedThresholds:
    """Resolve thresholds with global → org override → code default precedence."""
    defaults = dict(defaults or {})
    if not metric_config_key:
        return ResolvedThresholds(thresholds=defaults, source="default" if defaults else "none")

    now = datetime.now(UTC)
    cache_key = (metric_config_key, organisation_id)
    cached = _threshold_cache.get(cache_key)
    if cached is not None and now - cached.loaded_at < CONFIGURATION_CACHE_TTL:
        merged = {**defaults, **(cached.payload or {})}
        return ResolvedThresholds(thresholds=merged, source=cached.source)

    if session is None:
        return ResolvedThresholds(thresholds=defaults, source="default" if defaults else "none")

    async with _cache_lock:
        cached = _threshold_cache.get(cache_key)
        if cached is not None and now - cached.loaded_at < CONFIGURATION_CACHE_TTL:
            merged = {**defaults, **(cached.payload or {})}
            return ResolvedThresholds(thresholds=merged, source=cached.source)

        try:
            rows = (
                (
                    await session.execute(
                        select(MetricConfiguration).where(
                            MetricConfiguration.deleted_at.is_(None),
                            MetricConfiguration.metric_key == metric_config_key,
                            or_(
                                MetricConfiguration.org_id.is_(None),
                                MetricConfiguration.org_id == organisation_id,
                            )
                            if organisation_id is not None
                            else MetricConfiguration.org_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        except Exception:
            logger.warning(
                "event=kpi_threshold_resolve_failed metric_key=%s organisation_id=%s "
                "fallback=defaults",
                metric_config_key,
                organisation_id,
            )
            _store(cache_key, None, "default", now)
            return ResolvedThresholds(thresholds=defaults, source="default" if defaults else "none")

        org_row = next((row for row in rows if row.org_id == organisation_id), None)
        global_row = next((row for row in rows if row.org_id is None), None)
        if org_row is not None and isinstance(org_row.threshold_config, dict):
            payload = dict(org_row.threshold_config)
            source = "org"
        elif global_row is not None and isinstance(global_row.threshold_config, dict):
            payload = dict(global_row.threshold_config)
            source = "global"
        else:
            payload = None
            source = "default"

        _store(cache_key, payload, source, now)
        merged = {**defaults, **(payload or {})}
        return ResolvedThresholds(
            thresholds=merged,
            source=source if payload is not None else ("default" if defaults else "none"),
        )


def _store(
    cache_key: tuple[str, UUID | None],
    payload: dict[str, Any] | None,
    source: str,
    loaded_at: datetime,
) -> None:
    if len(_threshold_cache) >= CONFIGURATION_CACHE_MAX_ENTRIES:
        oldest = min(_threshold_cache, key=lambda key: _threshold_cache[key].loaded_at)
        _threshold_cache.pop(oldest, None)
    _threshold_cache[cache_key] = _CacheEntry(
        loaded_at=loaded_at, payload=payload, source=source
    )
