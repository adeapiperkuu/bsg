"""Event-driven publishers for KPI/score observations (fail-open side effects)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AppRole
from app.kpis.evaluation import evaluate_kpi
from app.time_series.observations import publish_agent_score

logger = logging.getLogger(__name__)


def _system_user(org_id: UUID) -> CurrentUser:
    return CurrentUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        org_id=org_id,
        email="time-series-engine@internal",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )


async def publish_delivery_scoring_snapshot(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    confidence: Decimal | float | int | None,
    as_of: datetime | None = None,
) -> None:
    settings = get_settings()
    if not settings.time_series_publish_enabled:
        return
    try:
        if confidence is not None:
            await publish_agent_score(
                session,
                org_id=org_id,
                project_id=project_id,
                score_key="delivery.confidence",
                agent_key="delivery",
                numeric_value=Decimal(str(confidence)),
                source_type="agent_event",
                observed_at=as_of or datetime.now(UTC),
                lineage_refs={"source": "delivery_scoring"},
            )
        user = _system_user(org_id)
        for kpi_key in ("delivery.confidence", "delivery.risk", "delivery.traffic_light"):
            try:
                await evaluate_kpi(
                    session,
                    user,
                    kpi_key,
                    org_id=org_id,
                    project_id=project_id,
                    version="1.0.0",
                    persist_observation=True,
                    source_type="agent_event",
                    include_explainability=False,
                )
            except Exception:
                logger.exception(
                    "event=time_series_delivery_kpi_publish_failed kpi_key=%s project_id=%s",
                    kpi_key,
                    project_id,
                )
    except Exception:
        logger.exception(
            "event=time_series_delivery_publish_failed project_id=%s",
            project_id,
        )


async def publish_quality_snapshot_observations(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    quality_score: Decimal | float | int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    if not settings.time_series_publish_enabled:
        return
    try:
        if quality_score is not None:
            await publish_agent_score(
                session,
                org_id=org_id,
                project_id=project_id,
                score_key="quality.score",
                agent_key="quality",
                numeric_value=Decimal(str(quality_score)),
                source_type="agent_event",
                lineage_refs={"source": "quality_snapshot", **(extra or {})},
            )
        user = _system_user(org_id)
        for kpi_key in ("quality.gold_set_accuracy", "quality.iaa", "quality.rework_rate"):
            try:
                await evaluate_kpi(
                    session,
                    user,
                    kpi_key,
                    org_id=org_id,
                    project_id=project_id,
                    version="1.0.0",
                    persist_observation=True,
                    source_type="agent_event",
                    include_explainability=False,
                )
            except Exception:
                logger.exception(
                    "event=time_series_quality_kpi_publish_failed kpi_key=%s project_id=%s",
                    kpi_key,
                    project_id,
                )
    except Exception:
        logger.exception(
            "event=time_series_quality_publish_failed project_id=%s",
            project_id,
        )


async def publish_workforce_utilization_observation(
    session: AsyncSession,
    *,
    org_id: UUID,
    utilization_pct: Decimal | float | int | None,
    project_id: UUID | None = None,
    team_id: UUID | None = None,
) -> None:
    settings = get_settings()
    if not settings.time_series_publish_enabled:
        return
    try:
        if utilization_pct is not None:
            await publish_agent_score(
                session,
                org_id=org_id,
                project_id=project_id,
                score_key="workforce.utilization",
                agent_key="workforce",
                numeric_value=Decimal(str(utilization_pct)),
                source_type="agent_event",
                lineage_refs={"source": "utilization_snapshot", "team_id": str(team_id) if team_id else None},
            )
        user = _system_user(org_id)
        await evaluate_kpi(
            session,
            user,
            "workforce.avg_utilization",
            org_id=org_id,
            version="1.0.0",
            persist_observation=True,
            source_type="agent_event",
            include_explainability=False,
        )
    except Exception:
        logger.exception("event=time_series_workforce_publish_failed org_id=%s", org_id)


async def publish_governance_score(
    session: AsyncSession,
    *,
    org_id: UUID,
    score_key: str,
    numeric_value: Decimal | float | int | None,
    project_id: UUID | None = None,
    score_version: str = "1.0.0",
    lineage: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    if not settings.time_series_publish_enabled:
        return
    if numeric_value is None:
        return
    try:
        await publish_agent_score(
            session,
            org_id=org_id,
            project_id=project_id,
            score_key=score_key,
            agent_key="governance",
            score_version=score_version,
            numeric_value=Decimal(str(numeric_value)),
            source_type="agent_event",
            lineage_refs=lineage or {"source": "governance"},
        )
    except Exception:
        logger.exception(
            "event=time_series_governance_score_publish_failed score_key=%s org_id=%s",
            score_key,
            org_id,
        )
