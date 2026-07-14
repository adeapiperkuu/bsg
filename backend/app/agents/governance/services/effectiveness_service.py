"""Phase 12 recommendation effectiveness service — aggregation, lifecycle, feedback."""

from __future__ import annotations

import csv
import io
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceEffectivenessCalibrationRead,
    GovernanceEffectivenessCategoryStatRead,
    GovernanceEffectivenessDrilldownItemRead,
    GovernanceEffectivenessDrilldownRead,
    GovernanceEffectivenessFalsePositiveRead,
    GovernanceEffectivenessFunnelRead,
    GovernanceEffectivenessQualityRead,
    GovernanceEffectivenessRecurrenceRead,
    GovernanceEffectivenessReportRead,
    GovernanceEffectivenessSummaryRead,
    GovernanceEffectivenessTimingRead,
    GovernanceEffectivenessTrendPointRead,
    GovernanceEffectivenessTrendsRead,
    GovernanceNamedCountRead,
    GovernanceRecommendationLifecycleEventRead,
    GovernanceStructuredFeedbackRead,
    GovernanceStructuredFeedbackRequest,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.effectiveness_metrics import (
    CALIBRATION_VERSION,
    QUALITY_SCORE_VERSION,
    classify_false_positive,
    compute_calibration,
    compute_quality_score,
    confidence_band,
    is_accepted,
    is_converted,
    is_dismissed,
    is_resolved,
    is_reviewed,
    mean_or_none,
    median_or_none,
    rate_or_null,
    seconds_between,
)
from app.agents.governance.services.governance_service import _apply_org_filter
from app.agents.governance.services.recommendation_service import (
    assert_can_view_ai_recommendations,
)
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationFeedback,
    GovernanceFalsePositiveStatus,
    GovernanceRecommendationLifecycleEvent,
    GovernanceRecommendationLifecycleEventType,
    Project,
)
from app.services.scoping import scoped_project_query

logger = logging.getLogger(__name__)

RANGE_DAY_OPTIONS = {7, 30, 90, 365}
_effectiveness_cache: dict[tuple, tuple[datetime, Any]] = {}


@dataclass(frozen=True)
class EffectivenessFilters:
    days: int = 30
    project_id: UUID | None = None
    vertical: str | None = None
    trigger_type: str | None = None
    severity: str | None = None
    status: str | None = None
    confidence_band: str | None = None
    quality_band: str | None = None
    false_positive_status: str | None = None
    recurring_only: bool = False


def _clamp_days(days: int) -> int:
    return days if days in RANGE_DAY_OPTIONS else 30


def _cache_ttl() -> timedelta:
    settings = get_settings()
    return timedelta(seconds=max(30, settings.governance_recommendation_effectiveness_cache_seconds))


def _cache_key(user: CurrentUser, filters: EffectivenessFilters, section: str) -> tuple:
    org_id = None if user.role == AppRole.SUPER_ADMIN else user.org_id
    return (
        org_id,
        user.role.value,
        user.id,
        section,
        filters.days,
        str(filters.project_id) if filters.project_id else None,
        (filters.vertical or "").strip().lower() or None,
        filters.trigger_type,
        filters.severity,
        filters.status,
        filters.confidence_band,
        filters.quality_band,
        filters.false_positive_status,
        filters.recurring_only,
    )


def clear_recommendation_effectiveness_caches(*, org_id: UUID | None = None) -> int:
    if org_id is None:
        removed = len(_effectiveness_cache)
        _effectiveness_cache.clear()
        return removed
    keys = [key for key in _effectiveness_cache if key[0] in {org_id, None}]
    for key in keys:
        _effectiveness_cache.pop(key, None)
    return len(keys)


def _normalize_vertical(vertical: str | None) -> str | None:
    if vertical is None:
        return None
    cleaned = vertical.strip()
    return cleaned or None


async def _visible_project_map(
    session: AsyncSession,
    current_user: CurrentUser,
) -> dict[UUID, Project]:
    rows = list(
        (await session.execute(scoped_project_query(current_user).order_by(Project.name.asc()))).scalars()
    )
    return {project.id: project for project in rows}


def _apply_row_filters(
    stmt: Select,
    filters: EffectivenessFilters,
    *,
    project_ids: set[UUID] | None,
) -> Select:
    if filters.project_id is not None:
        stmt = stmt.where(GovernanceAIRecommendation.project_id == filters.project_id)
    elif project_ids is not None:
        stmt = stmt.where(
            or_(
                GovernanceAIRecommendation.project_id.in_(project_ids),
                GovernanceAIRecommendation.project_id.is_(None),
            )
        )
    if filters.trigger_type:
        stmt = stmt.where(GovernanceAIRecommendation.trigger_type == filters.trigger_type)
    if filters.status:
        stmt = stmt.where(GovernanceAIRecommendation.status == filters.status)
    if filters.false_positive_status:
        stmt = stmt.where(
            GovernanceAIRecommendation.false_positive_status == filters.false_positive_status
        )
    if filters.quality_band:
        stmt = stmt.where(GovernanceAIRecommendation.quality_band == filters.quality_band)
    if filters.recurring_only:
        stmt = stmt.where(
            or_(
                GovernanceAIRecommendation.recurrence_after_acceptance_count > 0,
                GovernanceAIRecommendation.recurrence_after_dismissal_count > 0,
            )
        )
    return stmt


async def _fetch_recommendation_rows(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> tuple[list[GovernanceAIRecommendation], dict[UUID, Project]]:
    assert_can_view_ai_recommendations(current_user)
    effective_days = _clamp_days(filters.days)
    projects = await _visible_project_map(session, current_user)
    vertical = _normalize_vertical(filters.vertical)
    if vertical is not None:
        needle = vertical.casefold()
        projects = {
            pid: project
            for pid, project in projects.items()
            if (project.vertical or "").casefold() == needle
        }
    project_ids = set(projects)
    window_start = datetime.combine(
        date.today() - timedelta(days=effective_days - 1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    stmt = (
        select(GovernanceAIRecommendation)
        .where(
            GovernanceAIRecommendation.deleted_at.is_(None),
            GovernanceAIRecommendation.generated_at >= window_start,
        )
        .order_by(GovernanceAIRecommendation.generated_at.desc())
        .limit(5000)
    )
    stmt = _apply_org_filter(stmt, GovernanceAIRecommendation.org_id, current_user)
    stmt = _apply_row_filters(stmt, filters, project_ids=project_ids or None)
    rows = list((await session.execute(stmt)).scalars())
    if filters.confidence_band:
        rows = [
            row
            for row in rows
            if confidence_band(float(row.confidence) if row.confidence is not None else None)
            == filters.confidence_band
        ]
    if filters.severity:
        rows = [
            row
            for row in rows
            if (row.priority.value if hasattr(row.priority, "value") else str(row.priority))
            == filters.severity
        ]
    return rows, projects


async def _feedback_by_recommendation(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_ids: list[UUID],
) -> dict[UUID, list[GovernanceAIRecommendationFeedback]]:
    if not recommendation_ids:
        return {}
    stmt = select(GovernanceAIRecommendationFeedback).where(
        GovernanceAIRecommendationFeedback.recommendation_id.in_(recommendation_ids)
    )
    stmt = _apply_org_filter(stmt, GovernanceAIRecommendationFeedback.org_id, current_user)
    rows = list((await session.execute(stmt)).scalars())
    grouped: dict[UUID, list[GovernanceAIRecommendationFeedback]] = defaultdict(list)
    for row in rows:
        grouped[row.recommendation_id].append(row)
    return grouped


def _build_summary(
    rows: list[GovernanceAIRecommendation],
    *,
    feedback_map: dict[UUID, list[GovernanceAIRecommendationFeedback]],
    days: int,
) -> GovernanceEffectivenessSummaryRead:
    accepted = [row for row in rows if is_accepted(row)]
    dismissed = [row for row in rows if is_dismissed(row)]
    reviewed = [row for row in rows if is_reviewed(row)]
    converted = [row for row in accepted if is_converted(row)]
    resolved = [row for row in converted if is_resolved(row)]
    false_positives = sum(
        1
        for row in reviewed
        if classify_false_positive(row, feedback_rows=feedback_map.get(row.id, []))
        in {
            GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE,
            GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE,
        }
    )
    review_seconds = [
        sec
        for row in reviewed
        for sec in [
            seconds_between(
                row.generated_at,
                row.accepted_at if is_accepted(row) else row.dismissed_at,
            )
        ]
        if sec is not None
    ]
    convert_seconds = [
        sec
        for row in converted
        for sec in [seconds_between(row.accepted_at or row.generated_at, row.updated_at)]
        if sec is not None
    ]
    resolve_seconds = [
        sec
        for row in resolved
        for sec in [seconds_between(row.accepted_at or row.updated_at, row.resolved_at)]
        if sec is not None
    ]
    quality_scores: list[float] = []
    for row in rows:
        score = compute_quality_score(
            row,
            feedback_rows=feedback_map.get(row.id, []),
            has_outcome_data=is_reviewed(row),
        )
        if score.quality_score is not None and not score.provisional:
            quality_scores.append(score.quality_score)

    return GovernanceEffectivenessSummaryRead(
        generated_at=datetime.now(UTC),
        date_range_days=days,
        total_recommendations=len(rows),
        reviewed=len(reviewed),
        pending=len(rows) - len(reviewed),
        acceptance_rate=rate_or_null(
            len(accepted), len(reviewed), reason="no_reviewed_recommendations"
        ),
        dismissal_rate=rate_or_null(
            len(dismissed), len(reviewed), reason="no_reviewed_recommendations"
        ),
        conversion_rate=rate_or_null(
            len(converted), len(accepted), reason="no_accepted_recommendations"
        ),
        resolution_rate=rate_or_null(
            len(resolved), len(converted), reason="no_converted_recommendations"
        ),
        false_positive_rate=rate_or_null(
            false_positives, len(reviewed), reason="no_reviewed_recommendations"
        ),
        average_quality_score=round(mean(quality_scores), 1) if quality_scores else None,
        median_time_to_review_seconds=median_or_none(review_seconds),
        average_time_to_review_seconds=mean_or_none(review_seconds),
        median_time_to_convert_seconds=median_or_none(convert_seconds),
        average_time_to_convert_seconds=mean_or_none(convert_seconds),
        median_time_to_resolve_seconds=median_or_none(resolve_seconds),
        average_time_to_resolve_seconds=mean_or_none(resolve_seconds),
        recurrence_after_acceptance=sum(row.recurrence_after_acceptance_count or 0 for row in rows),
        recurrence_after_dismissal=sum(row.recurrence_after_dismissal_count or 0 for row in rows),
        metric_version="v1",
    )


async def get_effectiveness_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessSummaryRead:
    days = _clamp_days(filters.days)
    filters = EffectivenessFilters(**{**filters.__dict__, "days": days})
    cache_key = _cache_key(current_user, filters, "summary")
    now = datetime.now(UTC)
    cached = _effectiveness_cache.get(cache_key)
    if cached and now - cached[0] < _cache_ttl():
        return cached[1]
    rows, _ = await _fetch_recommendation_rows(session, current_user, filters)
    feedback_map = await _feedback_by_recommendation(session, current_user, [r.id for r in rows])
    summary = _build_summary(rows, feedback_map=feedback_map, days=days)
    _effectiveness_cache[cache_key] = (now, summary)
    return summary


async def get_effectiveness_funnel(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessFunnelRead:
    rows, _ = await _fetch_recommendation_rows(session, current_user, filters)
    accepted = [row for row in rows if is_accepted(row)]
    converted = [row for row in accepted if is_converted(row)]
    return GovernanceEffectivenessFunnelRead(
        created=len(rows),
        reviewed=sum(1 for row in rows if is_reviewed(row)),
        accepted=len(accepted),
        dismissed=sum(1 for row in rows if is_dismissed(row)),
        converted=len(converted),
        resolved=sum(1 for row in converted if is_resolved(row)),
    )


async def get_effectiveness_trends(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessTrendsRead:
    rows, _ = await _fetch_recommendation_rows(session, current_user, filters)
    feedback_map = await _feedback_by_recommendation(session, current_user, [r.id for r in rows])
    days = _clamp_days(filters.days)
    today = date.today()
    start = today - timedelta(days=days - 1)
    points: list[GovernanceEffectivenessTrendPointRead] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_rows = [
            row
            for row in rows
            if row.generated_at
            and (
                row.generated_at.astimezone(UTC).date()
                if row.generated_at.tzinfo
                else row.generated_at.date()
            )
            == day
        ]
        reviewed = [row for row in day_rows if is_reviewed(row)]
        accepted = [row for row in day_rows if is_accepted(row)]
        converted = [row for row in accepted if is_converted(row)]
        qualities = []
        for row in day_rows:
            score = compute_quality_score(
                row,
                feedback_rows=feedback_map.get(row.id, []),
                has_outcome_data=is_reviewed(row),
            )
            if score.quality_score is not None:
                qualities.append(score.quality_score)
        points.append(
            GovernanceEffectivenessTrendPointRead(
                date=day,
                created=len(day_rows),
                reviewed=len(reviewed),
                accepted=len(accepted),
                dismissed=sum(1 for row in day_rows if is_dismissed(row)),
                converted=len(converted),
                resolved=sum(1 for row in converted if is_resolved(row)),
                false_positives=sum(
                    1
                    for row in reviewed
                    if classify_false_positive(row, feedback_rows=feedback_map.get(row.id, []))
                    in {
                        GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE,
                        GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE,
                    }
                ),
                average_quality_score=round(mean(qualities), 1) if qualities else None,
                recurrence_after_acceptance=sum(
                    row.recurrence_after_acceptance_count or 0 for row in day_rows
                ),
                recurrence_after_dismissal=sum(
                    row.recurrence_after_dismissal_count or 0 for row in day_rows
                ),
            )
        )
    return GovernanceEffectivenessTrendsRead(points=points)


async def get_effectiveness_timing(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessTimingRead:
    summary = await get_effectiveness_summary(session, current_user, filters)
    return GovernanceEffectivenessTimingRead(
        average_time_to_review_seconds=summary.average_time_to_review_seconds,
        median_time_to_review_seconds=summary.median_time_to_review_seconds,
        average_time_to_convert_seconds=summary.average_time_to_convert_seconds,
        median_time_to_convert_seconds=summary.median_time_to_convert_seconds,
        average_time_to_resolve_seconds=summary.average_time_to_resolve_seconds,
        median_time_to_resolve_seconds=summary.median_time_to_resolve_seconds,
    )


async def get_effectiveness_quality(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessQualityRead:
    rows, _ = await _fetch_recommendation_rows(session, current_user, filters)
    feedback_map = await _feedback_by_recommendation(session, current_user, [r.id for r in rows])
    scores = [
        compute_quality_score(
            row,
            feedback_rows=feedback_map.get(row.id, []),
            has_outcome_data=is_reviewed(row),
        )
        for row in rows
    ]
    band_counts = Counter(score.quality_band for score in scores)
    numeric = [score.quality_score for score in scores if score.quality_score is not None]
    return GovernanceEffectivenessQualityRead(
        average_quality_score=round(mean(numeric), 1) if numeric else None,
        band_distribution=[
            GovernanceNamedCountRead(label=band, count=count)
            for band, count in band_counts.most_common()
        ],
        provisional_count=sum(1 for score in scores if score.provisional),
        score_version=get_settings().governance_recommendation_quality_score_version
        or QUALITY_SCORE_VERSION,
        sample_scores=scores[:20],
    )


async def get_effectiveness_calibration(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessCalibrationRead:
    rows, _ = await _fetch_recommendation_rows(session, current_user, filters)
    return compute_calibration(
        rows,
        min_sample=get_settings().governance_recommendation_calibration_min_sample,
    )


def _category_key(row: GovernanceAIRecommendation, projects: dict[UUID, Project]) -> str:
    trigger = row.trigger_type.value if row.trigger_type else "none"
    priority = row.priority.value if hasattr(row.priority, "value") else str(row.priority)
    band = confidence_band(float(row.confidence) if row.confidence is not None else None)
    vertical = "unassigned"
    if row.project_id and row.project_id in projects:
        vertical = projects[row.project_id].vertical or "unassigned"
    return f"{trigger}|{priority}|{band}|{vertical}|{row.explanation_version or 'v1'}"


async def _category_stats(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
    *,
    mode: str,
) -> list[GovernanceEffectivenessCategoryStatRead]:
    rows, projects = await _fetch_recommendation_rows(session, current_user, filters)
    feedback_map = await _feedback_by_recommendation(session, current_user, [r.id for r in rows])
    min_sample = get_settings().governance_recommendation_effectiveness_min_sample
    grouped: dict[str, list[GovernanceAIRecommendation]] = defaultdict(list)
    for row in rows:
        grouped[_category_key(row, projects)].append(row)

    stats: list[GovernanceEffectivenessCategoryStatRead] = []
    for key, group in grouped.items():
        reviewed = [row for row in group if is_reviewed(row)]
        if len(reviewed) < min_sample:
            continue
        accepted = [row for row in reviewed if is_accepted(row)]
        dismissed = [row for row in reviewed if is_dismissed(row)]
        converted = [row for row in accepted if is_converted(row)]
        resolved = [row for row in converted if is_resolved(row)]
        fps = [
            row
            for row in reviewed
            if classify_false_positive(row, feedback_rows=feedback_map.get(row.id, []))
            in {
                GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE,
                GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE,
            }
        ]
        trigger, severity, conf_band, vertical, explanation = key.split("|")
        acceptance = rate_or_null(len(accepted), len(reviewed), reason="no_reviewed")
        dismissal = rate_or_null(len(dismissed), len(reviewed), reason="no_reviewed")
        conversion = rate_or_null(len(converted), len(accepted), reason="no_accepted")
        resolution = rate_or_null(len(resolved), len(converted), reason="no_converted")
        fp_rate = rate_or_null(len(fps), len(reviewed), reason="no_reviewed")
        successful = (
            (conversion.value or 0) >= 40
            and (resolution.value or 0) >= 30
            and (fp_rate.value or 100) <= 25
            and (acceptance.value or 0) >= 40
        )
        if mode == "dismissed" and (dismissal.value or 0) < 60:
            continue
        if mode == "accepted" and not ((acceptance.value or 0) >= 60 and successful):
            continue
        if mode == "false_positives" and (fp_rate.value or 0) < 40:
            continue
        stats.append(
            GovernanceEffectivenessCategoryStatRead(
                category_key=key,
                trigger_type=trigger,
                severity=severity,
                confidence_band=conf_band,
                vertical=vertical,
                explanation_version=explanation,
                sample_size=len(reviewed),
                acceptance_rate=acceptance,
                dismissal_rate=dismissal,
                conversion_rate=conversion,
                resolution_rate=resolution,
                false_positive_rate=fp_rate,
                recurrence_after_acceptance=sum(
                    row.recurrence_after_acceptance_count or 0 for row in group
                ),
                recurrence_after_dismissal=sum(
                    row.recurrence_after_dismissal_count or 0 for row in group
                ),
                successful=successful,
            )
        )
    stats.sort(
        key=lambda item: (
            -(item.dismissal_rate.value or 0)
            if mode == "dismissed"
            else -(item.false_positive_rate.value or 0)
            if mode == "false_positives"
            else -(item.acceptance_rate.value or 0)
        )
    )
    return stats[:25]


async def get_frequently_dismissed(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> list[GovernanceEffectivenessCategoryStatRead]:
    return await _category_stats(session, current_user, filters, mode="dismissed")


async def get_frequently_accepted(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> list[GovernanceEffectivenessCategoryStatRead]:
    return await _category_stats(session, current_user, filters, mode="accepted")


async def get_effectiveness_false_positives(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessFalsePositiveRead:
    rows, _ = await _fetch_recommendation_rows(session, current_user, filters)
    feedback_map = await _feedback_by_recommendation(session, current_user, [r.id for r in rows])
    reviewed = [row for row in rows if is_reviewed(row)]
    counts = Counter(
        classify_false_positive(row, feedback_rows=feedback_map.get(row.id, [])).value
        for row in reviewed
    )
    fp_count = counts.get(GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE.value, 0) + counts.get(
        GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE.value, 0
    )
    return GovernanceEffectivenessFalsePositiveRead(
        confirmed=counts.get(GovernanceFalsePositiveStatus.CONFIRMED_FALSE_POSITIVE.value, 0),
        likely=counts.get(GovernanceFalsePositiveStatus.LIKELY_FALSE_POSITIVE.value, 0),
        not_false_positive=counts.get(GovernanceFalsePositiveStatus.NOT_FALSE_POSITIVE.value, 0),
        insufficient_evidence=counts.get(
            GovernanceFalsePositiveStatus.INSUFFICIENT_EVIDENCE.value, 0
        ),
        rate=rate_or_null(fp_count, len(reviewed), reason="no_reviewed_recommendations"),
        categories=await _category_stats(session, current_user, filters, mode="false_positives"),
    )


async def get_effectiveness_recurrence(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessRecurrenceRead:
    rows, projects = await _fetch_recommendation_rows(session, current_user, filters)
    recurring = [
        row
        for row in rows
        if (row.recurrence_after_acceptance_count or 0) > 0
        or (row.recurrence_after_dismissal_count or 0) > 0
    ]
    return GovernanceEffectivenessRecurrenceRead(
        after_acceptance=sum(row.recurrence_after_acceptance_count or 0 for row in rows),
        after_dismissal=sum(row.recurrence_after_dismissal_count or 0 for row in rows),
        recurring_recommendations=[
            GovernanceNamedCountRead(
                label=row.title,
                count=(row.recurrence_after_acceptance_count or 0)
                + (row.recurrence_after_dismissal_count or 0),
                project_id=row.project_id,
                project_name=projects.get(row.project_id).name if row.project_id in projects else None,
            )
            for row in sorted(
                recurring,
                key=lambda item: (item.recurrence_after_acceptance_count or 0)
                + (item.recurrence_after_dismissal_count or 0),
                reverse=True,
            )[:25]
        ],
    )


async def get_effectiveness_drilldown(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
    *,
    limit: int = 25,
    offset: int = 0,
) -> GovernanceEffectivenessDrilldownRead:
    rows, projects = await _fetch_recommendation_rows(session, current_user, filters)
    feedback_map = await _feedback_by_recommendation(session, current_user, [r.id for r in rows])
    total = len(rows)
    page = rows[offset : offset + limit]
    items: list[GovernanceEffectivenessDrilldownItemRead] = []
    for row in page:
        score = compute_quality_score(
            row,
            feedback_rows=feedback_map.get(row.id, []),
            has_outcome_data=is_reviewed(row),
        )
        fp = classify_false_positive(row, feedback_rows=feedback_map.get(row.id, []))
        items.append(
            GovernanceEffectivenessDrilldownItemRead(
                recommendation_id=row.id,
                title=row.title,
                project_id=row.project_id,
                project_name=projects.get(row.project_id).name if row.project_id in projects else None,
                vertical=projects.get(row.project_id).vertical if row.project_id in projects else None,
                trigger_type=row.trigger_type.value if row.trigger_type else None,
                status=row.status.value if hasattr(row.status, "value") else str(row.status),
                acceptance_status=row.acceptance_status.value
                if hasattr(row.acceptance_status, "value")
                else str(row.acceptance_status),
                confidence=float(row.confidence) if row.confidence is not None else None,
                calibrated_confidence=float(row.calibrated_confidence)
                if row.calibrated_confidence is not None
                else None,
                quality_score=score.quality_score,
                quality_band=score.quality_band,
                false_positive_status=fp.value,
                generated_at=row.generated_at,
            )
        )
    return GovernanceEffectivenessDrilldownRead(
        items=items, total=total, limit=limit, offset=offset
    )


async def get_effectiveness_report(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: EffectivenessFilters,
) -> GovernanceEffectivenessReportRead:
    summary = await get_effectiveness_summary(session, current_user, filters)
    calibration = await get_effectiveness_calibration(session, current_user, filters)
    quality = await get_effectiveness_quality(session, current_user, filters)
    funnel = await get_effectiveness_funnel(session, current_user, filters)
    warnings: list[str] = []
    if summary.reviewed == 0:
        warnings.append("No reviewed recommendations in the selected window.")
    if calibration.insufficient_history:
        warnings.append("Confidence calibration fell back to original confidence (insufficient sample).")
    if quality.provisional_count:
        warnings.append(f"{quality.provisional_count} recommendations have provisional quality scores.")
    actions: list[str] = []
    if (summary.false_positive_rate.value or 0) >= 30:
        actions.append("Review high false-positive categories before expanding auto-detection.")
    if (summary.conversion_rate.value or 100) < 40 and summary.acceptance_rate.value:
        actions.append("Investigate accepted recommendations that are not converted.")
    return GovernanceEffectivenessReportRead(
        generated_at=datetime.now(UTC),
        date_range_days=_clamp_days(filters.days),
        filters={
            "days": filters.days,
            "project_id": str(filters.project_id) if filters.project_id else None,
            "vertical": filters.vertical,
            "trigger_type": filters.trigger_type,
            "severity": filters.severity,
            "status": filters.status,
            "confidence_band": filters.confidence_band,
            "quality_band": filters.quality_band,
            "false_positive_status": filters.false_positive_status,
            "recurring_only": filters.recurring_only,
        },
        sample_sizes={
            "total": summary.total_recommendations,
            "reviewed": summary.reviewed,
            "calibration": calibration.sample_size,
        },
        summary=summary,
        calibration=calibration,
        quality=quality,
        funnel=funnel,
        warnings=warnings,
        recommended_review_actions=actions,
        metric_definitions={
            "acceptance_rate": "accepted / reviewed",
            "dismissal_rate": "dismissed / reviewed",
            "conversion_rate": "converted / accepted",
            "resolution_rate": "resolved / converted",
            "false_positive_rate": "(confirmed + likely FP) / reviewed",
        },
        calculation_versions={
            "metrics": "v1",
            "quality_score": get_settings().governance_recommendation_quality_score_version
            or QUALITY_SCORE_VERSION,
            "calibration": get_settings().governance_recommendation_calibration_version
            or CALIBRATION_VERSION,
        },
        data_completeness=round(
            mean([score.data_completeness for score in quality.sample_scores] or [0.0]),
            2,
        ),
    )


def effectiveness_report_csv(report: GovernanceEffectivenessReportRead) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "metric", "value", "null_reason"])
    summary = report.summary
    for name, metric in [
        ("acceptance_rate", summary.acceptance_rate),
        ("dismissal_rate", summary.dismissal_rate),
        ("conversion_rate", summary.conversion_rate),
        ("resolution_rate", summary.resolution_rate),
        ("false_positive_rate", summary.false_positive_rate),
    ]:
        writer.writerow(["summary", name, metric.value if metric.value is not None else "", metric.null_reason or ""])
    writer.writerow(["summary", "total_recommendations", summary.total_recommendations, ""])
    writer.writerow(["summary", "reviewed", summary.reviewed, ""])
    writer.writerow(["summary", "average_quality_score", summary.average_quality_score or "", ""])
    for warning in report.warnings:
        writer.writerow(["warning", warning, "", ""])
    return output.getvalue()


async def record_lifecycle_event(
    session: AsyncSession,
    *,
    org_id: UUID,
    recommendation_id: UUID,
    event_type: GovernanceRecommendationLifecycleEventType,
    actor_user_id: UUID | None = None,
    conversion_target: str | None = None,
    conversion_target_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> GovernanceRecommendationLifecycleEvent:
    event = GovernanceRecommendationLifecycleEvent(
        org_id=org_id,
        recommendation_id=recommendation_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        conversion_target=conversion_target,
        conversion_target_id=conversion_target_id,
        event_metadata=metadata or {},
    )
    session.add(event)
    await session.flush()
    return event


async def get_recommendation_lifecycle(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
) -> list[GovernanceRecommendationLifecycleEventRead]:
    assert_can_view_ai_recommendations(current_user)
    stmt = (
        select(GovernanceRecommendationLifecycleEvent)
        .where(GovernanceRecommendationLifecycleEvent.recommendation_id == recommendation_id)
        .order_by(GovernanceRecommendationLifecycleEvent.created_at.asc())
    )
    stmt = _apply_org_filter(stmt, GovernanceRecommendationLifecycleEvent.org_id, current_user)
    rows = list((await session.execute(stmt)).scalars())
    return [
        GovernanceRecommendationLifecycleEventRead(
            id=row.id,
            recommendation_id=row.recommendation_id,
            event_type=row.event_type.value,
            actor_user_id=row.actor_user_id,
            conversion_target=row.conversion_target,
            conversion_target_id=row.conversion_target_id,
            metadata=row.event_metadata or {},
            created_at=row.created_at,
        )
        for row in rows
    ]


async def submit_structured_recommendation_feedback(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    payload: GovernanceStructuredFeedbackRequest,
) -> GovernanceStructuredFeedbackRead:
    assert_can_view_ai_recommendations(current_user)
    rec_stmt = select(GovernanceAIRecommendation).where(
        GovernanceAIRecommendation.id == recommendation_id,
        GovernanceAIRecommendation.deleted_at.is_(None),
    )
    rec_stmt = _apply_org_filter(rec_stmt, GovernanceAIRecommendation.org_id, current_user)
    recommendation = (await session.execute(rec_stmt)).scalar_one_or_none()
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    existing_stmt = select(GovernanceAIRecommendationFeedback).where(
        GovernanceAIRecommendationFeedback.recommendation_id == recommendation_id,
        GovernanceAIRecommendationFeedback.user_id == current_user.id,
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    helpful = payload.helpful
    if helpful is None and payload.useful is not None:
        helpful = payload.useful
    if helpful is None:
        helpful = True

    if existing:
        existing.helpful = helpful
        existing.reason = payload.reason
        existing.accurate = payload.accurate
        existing.useful = payload.useful
        existing.actionable = payload.actionable
        existing.clear = payload.clear
        existing.missing_evidence = payload.missing_evidence
        existing.duplicate = payload.duplicate
        existing.already_handled = payload.already_handled
        existing.rating = payload.rating
        existing.comment = payload.comment
        existing.feedback_version = "v1"
        feedback = existing
    else:
        feedback = GovernanceAIRecommendationFeedback(
            recommendation_id=recommendation_id,
            org_id=recommendation.org_id,
            user_id=current_user.id,
            helpful=helpful,
            reason=payload.reason,
            accurate=payload.accurate,
            useful=payload.useful,
            actionable=payload.actionable,
            clear=payload.clear,
            missing_evidence=payload.missing_evidence,
            duplicate=payload.duplicate,
            already_handled=payload.already_handled,
            rating=payload.rating,
            comment=payload.comment,
            feedback_version="v1",
        )
        session.add(feedback)

    await record_lifecycle_event(
        session,
        org_id=recommendation.org_id,
        recommendation_id=recommendation_id,
        event_type=GovernanceRecommendationLifecycleEventType.FEEDBACK_SUBMITTED,
        actor_user_id=current_user.id,
        metadata={"helpful": helpful, "rating": payload.rating},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_feedback_submitted",
        org_id=recommendation.org_id,
        source_table="governance_ai_recommendation_feedback",
        source_id=recommendation_id,
        metadata={"structured": True},
    )
    await session.flush()
    await session.refresh(feedback)
    clear_recommendation_effectiveness_caches(org_id=recommendation.org_id)
    return GovernanceStructuredFeedbackRead(
        id=feedback.id,
        recommendation_id=feedback.recommendation_id,
        helpful=feedback.helpful,
        accurate=feedback.accurate,
        useful=feedback.useful,
        actionable=feedback.actionable,
        clear=feedback.clear,
        missing_evidence=feedback.missing_evidence,
        duplicate=feedback.duplicate,
        already_handled=feedback.already_handled,
        rating=feedback.rating,
        comment=feedback.comment,
        reason=feedback.reason,
        feedback_version=feedback.feedback_version,
        created_at=feedback.created_at,
    )
