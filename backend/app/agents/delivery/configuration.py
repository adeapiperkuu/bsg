"""Validated, organisation-scoped Delivery scoring configuration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MetricConfiguration

logger = logging.getLogger(__name__)

CONFIGURATION_CACHE_TTL = timedelta(seconds=60)
CONFIGURATION_CACHE_MAX_ENTRIES = 1024


class DeliveryMetricKey(StrEnum):
    CONFIDENCE = "delivery_confidence"
    RISK = "delivery_risk"
    TRAFFIC_LIGHT = "delivery_traffic_light"
    BOTTLENECK = "delivery_bottleneck"


class _ImmutableThresholdModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DeliveryConfidenceThresholds(_ImmutableThresholdModel):
    on_track: Decimal = Field(
        default=Decimal("80.00"),
        ge=0,
        le=100,
        description="Inclusive confidence boundary for the on-track band.",
    )
    critical: Decimal = Field(
        default=Decimal("50.00"),
        ge=0,
        le=100,
        description="Confidence values strictly below this boundary are critical.",
    )

    @field_validator("on_track", "critical", mode="before")
    @classmethod
    def validate_numeric_type(cls, value: object) -> object:
        return _require_finite_number(value)

    @model_validator(mode="after")
    def validate_order(self) -> DeliveryConfidenceThresholds:
        if self.critical > self.on_track:
            raise ValueError("critical must be less than or equal to on_track")
        return self


class DeliveryRiskThresholds(_ImmutableThresholdModel):
    medium: Decimal = Field(
        default=Decimal("30.00"), ge=0, le=100, description="Inclusive medium-risk boundary."
    )
    high: Decimal = Field(
        default=Decimal("60.00"), ge=0, le=100, description="Inclusive high-risk boundary."
    )
    critical: Decimal = Field(
        default=Decimal("85.00"),
        ge=0,
        le=100,
        description="Inclusive critical-risk boundary.",
    )
    trend_tolerance: Decimal = Field(
        default=Decimal("5.00"),
        ge=0,
        le=100,
        description="Absolute throughput movement treated as a flat trend.",
    )
    throughput_decline_tolerance: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        le=100,
        description="Decline that must be exceeded before throughput adds delivery risk.",
    )
    milestone_warning_window_days: StrictInt = Field(
        default=14,
        ge=1,
        le=365,
        description="Days before a milestone when urgency risk begins.",
    )

    @field_validator(
        "medium",
        "high",
        "critical",
        "trend_tolerance",
        "throughput_decline_tolerance",
        mode="before",
    )
    @classmethod
    def validate_numeric_type(cls, value: object) -> object:
        return _require_finite_number(value)

    @model_validator(mode="after")
    def validate_order(self) -> DeliveryRiskThresholds:
        if not self.medium <= self.high <= self.critical:
            raise ValueError("risk thresholds must satisfy medium <= high <= critical")
        return self


class DeliveryTrafficLightRules(_ImmutableThresholdModel):
    red_on_critical_confidence: StrictBool = True
    red_on_critical_risk: StrictBool = True
    red_on_critical_open_risk: StrictBool = True
    red_on_missed_milestone: StrictBool = True
    yellow_on_warning_confidence: StrictBool = True
    yellow_on_warning_risk: StrictBool = True
    yellow_on_warning_open_risk: StrictBool = True
    yellow_on_open_bottleneck: StrictBool = True


class DeliveryBottleneckThresholds(_ImmutableThresholdModel):
    observation_days: StrictInt = Field(
        default=5, ge=1, le=365, description="Reserved sustained-decline observation window."
    )
    decline_threshold_pct: Decimal = Field(
        default=Decimal("20.00"),
        gt=0,
        le=100,
        description="Reserved team-share decline candidate boundary.",
    )
    recovery_days: StrictInt = Field(
        default=3, ge=1, le=365, description="Reserved sustained-recovery window."
    )

    @field_validator("decline_threshold_pct", mode="before")
    @classmethod
    def validate_numeric_type(cls, value: object) -> object:
        return _require_finite_number(value)


class DeliveryScoringThresholds(_ImmutableThresholdModel):
    confidence: DeliveryConfidenceThresholds = Field(default_factory=DeliveryConfidenceThresholds)
    risk: DeliveryRiskThresholds = Field(default_factory=DeliveryRiskThresholds)
    traffic_light: DeliveryTrafficLightRules = Field(default_factory=DeliveryTrafficLightRules)
    bottleneck: DeliveryBottleneckThresholds = Field(default_factory=DeliveryBottleneckThresholds)


DEFAULT_DELIVERY_SCORING_THRESHOLDS = DeliveryScoringThresholds()

_SECTION_MODEL_BY_KEY: dict[DeliveryMetricKey, type[_ImmutableThresholdModel]] = {
    DeliveryMetricKey.CONFIDENCE: DeliveryConfidenceThresholds,
    DeliveryMetricKey.RISK: DeliveryRiskThresholds,
    DeliveryMetricKey.TRAFFIC_LIGHT: DeliveryTrafficLightRules,
    DeliveryMetricKey.BOTTLENECK: DeliveryBottleneckThresholds,
}
_SECTION_NAME_BY_KEY: dict[DeliveryMetricKey, str] = {
    DeliveryMetricKey.CONFIDENCE: "confidence",
    DeliveryMetricKey.RISK: "risk",
    DeliveryMetricKey.TRAFFIC_LIGHT: "traffic_light",
    DeliveryMetricKey.BOTTLENECK: "bottleneck",
}


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    loaded_at: datetime
    thresholds: DeliveryScoringThresholds


_threshold_cache: dict[UUID, _CacheEntry] = {}
_cache_lock = asyncio.Lock()


def _require_finite_number(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValueError("value must be a JSON number")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("value must be finite")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("value must be finite")
    return value


def invalidate_delivery_scoring_thresholds_cache(organisation_id: UUID | None = None) -> int:
    """Invalidate one organisation's cached thresholds, or every entry."""
    if organisation_id is None:
        count = len(_threshold_cache)
        _threshold_cache.clear()
        return count
    return int(_threshold_cache.pop(organisation_id, None) is not None)


def validate_delivery_metric_threshold_config(metric_key: str, payload: object) -> None:
    """Reject invalid Delivery payloads at write time; unrelated metric keys are ignored."""
    try:
        key = DeliveryMetricKey(metric_key)
    except ValueError:
        return
    if not isinstance(payload, dict):
        raise ValueError("Delivery threshold_config must be an object.")
    section_name = _SECTION_NAME_BY_KEY[key]
    defaults = getattr(DEFAULT_DELIVERY_SCORING_THRESHOLDS, section_name)
    try:
        _SECTION_MODEL_BY_KEY[key].model_validate({**defaults.model_dump(), **payload})
    except ValidationError as exc:
        raise ValueError(_validation_summary(exc)) from exc


async def load_delivery_scoring_thresholds(
    session: AsyncSession,
    organisation_id: UUID,
) -> DeliveryScoringThresholds:
    """Load one organisation's thresholds using at most one query on a cache miss."""
    loaded = await load_delivery_scoring_thresholds_for_organisations(
        session,
        {organisation_id},
    )
    return loaded[organisation_id]


async def load_delivery_scoring_thresholds_for_organisations(
    session: AsyncSession,
    organisation_ids: set[UUID],
) -> dict[UUID, DeliveryScoringThresholds]:
    """Load global templates and org overrides once for all requested organisations."""
    if not organisation_ids:
        return {}

    now = datetime.now(UTC)
    resolved: dict[UUID, DeliveryScoringThresholds] = {}
    missing: set[UUID] = set()
    for organisation_id in organisation_ids:
        entry = _threshold_cache.get(organisation_id)
        if entry is not None and now - entry.loaded_at < CONFIGURATION_CACHE_TTL:
            resolved[organisation_id] = entry.thresholds
            _log_loaded(
                organisation_id,
                source="cache",
                custom_sections=(),
                fallback_sections=(),
                cache_hit=True,
                duration_ms=0.0,
            )
        else:
            missing.add(organisation_id)

    if not missing:
        return resolved

    async with _cache_lock:
        now = datetime.now(UTC)
        still_missing: set[UUID] = set()
        for organisation_id in missing:
            entry = _threshold_cache.get(organisation_id)
            if entry is not None and now - entry.loaded_at < CONFIGURATION_CACHE_TTL:
                resolved[organisation_id] = entry.thresholds
            else:
                still_missing.add(organisation_id)
        if not still_missing:
            return resolved

        started = perf_counter()
        try:
            rows = (
                (
                    await session.execute(
                        select(MetricConfiguration).where(
                            MetricConfiguration.deleted_at.is_(None),
                            MetricConfiguration.metric_key.in_(
                                [key.value for key in DeliveryMetricKey]
                            ),
                            or_(
                                MetricConfiguration.org_id.is_(None),
                                MetricConfiguration.org_id.in_(still_missing),
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
        except Exception as exc:
            logger.warning(
                "event=delivery_scoring_thresholds_load_failed organisation_ids=%s "
                "error_type=%s fallback=all_defaults",
                ",".join(sorted(str(item) for item in still_missing)),
                type(exc).__name__,
            )
            for organisation_id in still_missing:
                _store_cache_entry(
                    organisation_id,
                    DEFAULT_DELIVERY_SCORING_THRESHOLDS,
                    now,
                )
                resolved[organisation_id] = DEFAULT_DELIVERY_SCORING_THRESHOLDS
            return resolved
        duration_ms = (perf_counter() - started) * 1000

        global_rows: dict[str, MetricConfiguration] = {}
        org_rows: dict[UUID, dict[str, MetricConfiguration]] = {}
        for row in rows:
            if row.org_id is None:
                global_rows[row.metric_key] = row
            else:
                org_rows.setdefault(row.org_id, {})[row.metric_key] = row

        for organisation_id in still_missing:
            thresholds, custom_sections, fallback_sections = _build_thresholds(
                organisation_id=organisation_id,
                global_rows=global_rows,
                organisation_rows=org_rows.get(organisation_id, {}),
            )
            _store_cache_entry(organisation_id, thresholds, now)
            resolved[organisation_id] = thresholds
            source: Literal["default", "database", "mixed"]
            if custom_sections and not fallback_sections:
                source = "database"
            elif custom_sections or global_rows:
                source = "mixed"
            else:
                source = "default"
            _log_loaded(
                organisation_id,
                source=source,
                custom_sections=custom_sections,
                fallback_sections=fallback_sections,
                cache_hit=False,
                duration_ms=duration_ms,
            )

    return resolved


def _build_thresholds(
    *,
    organisation_id: UUID,
    global_rows: dict[str, MetricConfiguration],
    organisation_rows: dict[str, MetricConfiguration],
) -> tuple[DeliveryScoringThresholds, tuple[str, ...], tuple[str, ...]]:
    sections: dict[str, _ImmutableThresholdModel] = {}
    custom_sections: list[str] = []
    fallback_sections: list[str] = []

    for metric_key in DeliveryMetricKey:
        row = organisation_rows.get(metric_key.value) or global_rows.get(metric_key.value)
        section_name = _SECTION_NAME_BY_KEY[metric_key]
        section_model = _SECTION_MODEL_BY_KEY[metric_key]
        default_section = getattr(DEFAULT_DELIVERY_SCORING_THRESHOLDS, section_name)
        if row is None:
            sections[section_name] = default_section
            fallback_sections.append(section_name)
            continue

        payload = row.threshold_config
        if not isinstance(payload, dict):
            sections[section_name] = default_section
            fallback_sections.append(section_name)
            _log_invalid(organisation_id, metric_key, "threshold_config must be an object")
            continue

        try:
            merged_payload = {**default_section.model_dump(), **payload}
            sections[section_name] = section_model.model_validate(merged_payload)
            custom_sections.append(section_name)
        except ValidationError as exc:
            sections[section_name] = default_section
            fallback_sections.append(section_name)
            _log_invalid(organisation_id, metric_key, _validation_summary(exc))

    return (
        DeliveryScoringThresholds.model_validate(sections),
        tuple(custom_sections),
        tuple(fallback_sections),
    )


def _store_cache_entry(
    organisation_id: UUID,
    thresholds: DeliveryScoringThresholds,
    loaded_at: datetime,
) -> None:
    if len(_threshold_cache) >= CONFIGURATION_CACHE_MAX_ENTRIES:
        oldest_key = min(_threshold_cache, key=lambda key: _threshold_cache[key].loaded_at)
        _threshold_cache.pop(oldest_key, None)
    _threshold_cache[organisation_id] = _CacheEntry(loaded_at=loaded_at, thresholds=thresholds)


def _validation_summary(exc: ValidationError) -> str:
    first = exc.errors(include_url=False)[0]
    location = ".".join(str(item) for item in first.get("loc", ())) or "section"
    return f"{location}: {first.get('msg', 'invalid value')}"


def _log_invalid(
    organisation_id: UUID,
    metric_key: DeliveryMetricKey,
    validation_error: str,
) -> None:
    logger.warning(
        "event=delivery_scoring_thresholds_invalid organisation_id=%s metric_key=%s "
        "validation_error=%s fallback=default_section",
        organisation_id,
        metric_key.value,
        validation_error,
    )


def _log_loaded(
    organisation_id: UUID,
    *,
    source: str,
    custom_sections: tuple[str, ...],
    fallback_sections: tuple[str, ...],
    cache_hit: bool,
    duration_ms: float,
) -> None:
    logger.info(
        "event=delivery_scoring_thresholds_loaded organisation_id=%s source=%s "
        "custom_sections=%s fallback_sections=%s cache_hit=%s duration_ms=%.2f",
        organisation_id,
        source,
        ",".join(custom_sections) or "none",
        ",".join(fallback_sections) or "none",
        cache_hit,
        duration_ms,
    )
