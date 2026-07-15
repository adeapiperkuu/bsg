"""Phase 13 — controlled recommendation optimization (lifecycle, rules, shadow, drift)."""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceLearningRuleRead,
    GovernanceOptimizationCompareRead,
    GovernanceOptimizationDriftAlertRead,
    GovernanceOptimizationDriftRead,
    GovernanceOptimizationFilters,
    GovernanceOptimizationReportRead,
    GovernanceOptimizationShadowRead,
    GovernanceOptimizationStrategyRead,
    GovernanceOptimizationSummaryRead,
    GovernanceRecommendationLifecycleActionRead,
    GovernanceRecommendationResolveRequest,
    GovernanceRecommendationReopenRequest,
    GovernanceRecommendationCancelResolutionRequest,
    GovernanceRecommendationChangeConversionTargetRequest,
    GovernanceRecommendationConvertRequest,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.effectiveness_metrics import (
    is_accepted,
    is_converted,
    is_resolved,
    is_reviewed,
    rate_or_null,
)
from app.agents.governance.services.effectiveness_service import (
    EffectivenessFilters,
    clear_recommendation_effectiveness_caches,
    get_effectiveness_summary,
    record_lifecycle_event,
)
from app.agents.governance.services.governance_service import _apply_org_filter
from app.agents.governance.services.learning_rules_engine import (
    ALLOWED_RULE_EFFECTS,
    RecommendationCandidateView,
    apply_learning_rule,
    compare_rankings,
    validate_rule_payload,
)
from app.agents.governance.services.recommendation_service import (
    assert_can_generate_ai_recommendations,
    assert_can_view_ai_recommendations,
    convert_governance_recommendation_to_action,
    convert_governance_recommendation_to_escalation,
    get_governance_ai_recommendation,
)
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationStatus,
    GovernanceLearningRuleStatus,
    GovernanceRecommendationConversionTarget,
    GovernanceRecommendationDriftAlert,
    GovernanceRecommendationDriftSeverity,
    GovernanceRecommendationEvaluationPeriod,
    GovernanceRecommendationEvaluationReport,
    GovernanceRecommendationLifecycleEventType,
    GovernanceRecommendationLearningRule,
    GovernanceRecommendationShadowEvaluation,
    GovernanceRecommendationShadowStatus,
    GovernanceRecommendationStrategyVersion,
    Project,
)
from app.services.scoping import scoped_project_query

logger = logging.getLogger(__name__)

_optimization_cache: dict[tuple, tuple[datetime, Any]] = {}
OPTIMIZATION_ROLES = {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}


def assert_can_manage_optimization(current_user: CurrentUser) -> None:
    if current_user.role not in OPTIMIZATION_ROLES:
        raise HTTPException(status_code=403, detail="Optimization controls require leadership access")


def clear_optimization_caches(*, org_id: UUID | None = None) -> None:
    if org_id is None:
        _optimization_cache.clear()
        return
    keys = [k for k in _optimization_cache if k and k[0] == str(org_id)]
    for key in keys:
        _optimization_cache.pop(key, None)


def _cache_get(key: tuple) -> Any | None:
    entry = _optimization_cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if datetime.now(UTC) >= expires_at:
        _optimization_cache.pop(key, None)
        return None
    return value


def _cache_set(key: tuple, value: Any) -> None:
    settings = get_settings()
    ttl = max(30, settings.governance_recommendation_optimization_cache_seconds)
    _optimization_cache[key] = (datetime.now(UTC) + timedelta(seconds=ttl), value)
    if len(_optimization_cache) > 256:
        # Bound in-process cache size
        for old in list(_optimization_cache.keys())[:64]:
            _optimization_cache.pop(old, None)


def _learning_rules_enabled() -> bool:
    return bool(get_settings().governance_recommendation_learning_rules_enabled)


@dataclass
class OptimizationQueryFilters:
    days: int = 30
    project_id: UUID | None = None
    vertical: str | None = None
    trigger_type: str | None = None
    strategy_version: str | None = None
    learning_rule_id: UUID | None = None
    quality_band: str | None = None
    confidence_band: str | None = None
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def _filters_from_schema(filters: GovernanceOptimizationFilters | None) -> OptimizationQueryFilters:
    if filters is None:
        return OptimizationQueryFilters()
    days = filters.days if filters.days in {7, 30, 90, 365} else 30
    return OptimizationQueryFilters(
        days=days,
        project_id=filters.project_id,
        vertical=filters.vertical,
        trigger_type=filters.trigger_type,
        strategy_version=filters.strategy_version,
        learning_rule_id=filters.learning_rule_id,
        quality_band=filters.quality_band,
        confidence_band=filters.confidence_band,
        status=filters.status,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )


async def _load_recommendations(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: OptimizationQueryFilters,
) -> list[GovernanceAIRecommendation]:
    since = datetime.now(UTC) - timedelta(days=filters.days)
    stmt: Select = select(GovernanceAIRecommendation).where(
        GovernanceAIRecommendation.deleted_at.is_(None),
        GovernanceAIRecommendation.generated_at >= since,
    )
    stmt = _apply_org_filter(stmt, GovernanceAIRecommendation.org_id, current_user)
    if filters.project_id is not None:
        stmt = stmt.where(GovernanceAIRecommendation.project_id == filters.project_id)
    if filters.trigger_type:
        stmt = stmt.where(GovernanceAIRecommendation.trigger_type == filters.trigger_type)
    if filters.strategy_version:
        stmt = stmt.where(GovernanceAIRecommendation.strategy_version == filters.strategy_version)
    if filters.quality_band:
        stmt = stmt.where(GovernanceAIRecommendation.quality_band == filters.quality_band)
    if filters.confidence_band:
        stmt = stmt.where(GovernanceAIRecommendation.confidence_band == filters.confidence_band)
    if filters.status:
        stmt = stmt.where(GovernanceAIRecommendation.status == filters.status)
    if filters.learning_rule_id is not None:
        stmt = stmt.where(
            GovernanceAIRecommendation.learning_rule_version == str(filters.learning_rule_id)
        )
    if filters.date_from is not None:
        stmt = stmt.where(
            GovernanceAIRecommendation.generated_at
            >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=UTC)
        )
    if filters.date_to is not None:
        stmt = stmt.where(
            GovernanceAIRecommendation.generated_at
            <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=UTC)
        )
    if filters.vertical:
        project_ids = (
            await session.execute(
                scoped_project_query(current_user).where(Project.vertical == filters.vertical)
            )
        ).scalars().all()
        ids = [p.id for p in project_ids]
        if not ids:
            return []
        stmt = stmt.where(GovernanceAIRecommendation.project_id.in_(ids))
    stmt = stmt.order_by(GovernanceAIRecommendation.generated_at.desc()).limit(2000)
    return list((await session.execute(stmt)).scalars())


def _metric_snapshot(rows: list[GovernanceAIRecommendation]) -> dict[str, Any]:
    reviewed = sum(1 for r in rows if is_reviewed(r))
    accepted = sum(1 for r in rows if is_accepted(r))
    converted = sum(1 for r in rows if is_converted(r))
    resolved = sum(1 for r in rows if is_resolved(r))
    fp = sum(
        1
        for r in rows
        if getattr(r, "false_positive_status", None)
        and str(getattr(r.false_positive_status, "value", r.false_positive_status))
        in {"confirmed_false_positive", "likely_false_positive"}
    )
    quality_scores = [float(r.quality_score) for r in rows if r.quality_score is not None]
    return {
        "volume": len(rows),
        "reviewed": reviewed,
        "accepted": accepted,
        "converted": converted,
        "resolved": resolved,
        "false_positives": fp,
        "acceptance_rate": rate_or_null(accepted, reviewed, reason="no_reviewed").model_dump(),
        "conversion_rate": rate_or_null(converted, accepted, reason="no_accepted").model_dump(),
        "resolution_rate": rate_or_null(resolved, converted, reason="no_converted").model_dump(),
        "false_positive_rate": rate_or_null(fp, reviewed, reason="no_reviewed").model_dump(),
        "average_quality_score": (sum(quality_scores) / len(quality_scores)) if quality_scores else None,
        "recurrence_after_acceptance": sum(int(r.recurrence_after_acceptance_count or 0) for r in rows),
        "recurrence_after_dismissal": sum(int(r.recurrence_after_dismissal_count or 0) for r in rows),
    }


def _rule_to_read(row: GovernanceRecommendationLearningRule) -> GovernanceLearningRuleRead:
    return GovernanceLearningRuleRead(
        id=row.id,
        org_id=row.org_id,
        rule_type=row.rule_type,
        rule_payload=row.rule_payload or {},
        version=row.version,
        status=row.status.value if hasattr(row.status, "value") else str(row.status),
        evaluation_mode=row.evaluation_mode or "none",
        change_summary=row.change_summary,
        approved_at=row.approved_at,
        activated_at=row.activated_at,
        reverted_at=row.reverted_at,
        disabled_at=row.disabled_at,
        shadow_evaluation_id=row.shadow_evaluation_id,
        supersedes_rule_id=row.supersedes_rule_id,
        performance_before=row.performance_before,
        performance_after=row.performance_after,
        allowed_effects=list(row.allowed_effects or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


async def convert_recommendation_lifecycle(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    payload: GovernanceRecommendationConvertRequest,
) -> GovernanceRecommendationLifecycleActionRead:
    """Dedicated convert endpoint — reuses Phase 7 converters; records lifecycle event."""
    assert_can_generate_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)

    if payload.target == GovernanceRecommendationConversionTarget.ACTION:
        from app.agents.governance.schemas.governance import ConvertRecommendationToActionRequest

        result = await convert_governance_recommendation_to_action(
            session,
            current_user,
            recommendation_id,
            ConvertRecommendationToActionRequest(
                project_id=payload.project_id,
                suggested_action_index=payload.suggested_action_index,
                title=payload.title or row.title,
                description=payload.description,
                owner_id=payload.owner_id,
                due_date=payload.due_date,
                note=payload.note,
                idempotency_key=payload.idempotency_key,
            ),
        )
        target_id = result.created_action_id
    else:
        from app.agents.governance.schemas.governance import ConvertRecommendationToEscalationRequest

        result = await convert_governance_recommendation_to_escalation(
            session,
            current_user,
            recommendation_id,
            ConvertRecommendationToEscalationRequest(
                project_id=payload.project_id,
                suggested_action_index=payload.suggested_action_index,
                title=payload.title or row.title,
                description=payload.description,
                assigned_to=payload.owner_id,
                note=payload.note,
                idempotency_key=payload.idempotency_key,
            ),
        )
        target_id = result.created_escalation_id

    # Phase 7 converters already commit and write accepted+converted lifecycle events.
    refreshed = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    clear_recommendation_effectiveness_caches(org_id=refreshed.org_id)
    clear_optimization_caches(org_id=refreshed.org_id)
    return GovernanceRecommendationLifecycleActionRead(
        recommendation_id=recommendation_id,
        event_type="converted",
        conversion_target=payload.target.value,
        conversion_target_id=target_id,
        resolved_at=refreshed.resolved_at,
        reopened_at=refreshed.reopened_at,
        message="Recommendation converted",
    )


async def resolve_recommendation(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    payload: GovernanceRecommendationResolveRequest,
) -> GovernanceRecommendationLifecycleActionRead:
    assert_can_generate_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    if not is_converted(row):
        raise HTTPException(status_code=400, detail="Only converted recommendations can be resolved")
    if is_resolved(row):
        raise HTTPException(status_code=409, detail="Recommendation is already resolved")
    now = datetime.now(UTC)
    row.resolved_at = now
    row.resolved_by_user_id = current_user.id
    row.reopened_at = None
    row.resolution_cancelled_at = None
    row.resolution_note = payload.note
    await record_lifecycle_event(
        session,
        org_id=row.org_id,
        recommendation_id=row.id,
        event_type=GovernanceRecommendationLifecycleEventType.RESOLVED,
        actor_user_id=current_user.id,
        metadata={"note": payload.note},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_resolved",
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendations",
        source_id=row.id,
        metadata={"note": payload.note},
    )
    await session.commit()
    clear_recommendation_effectiveness_caches(org_id=row.org_id)
    clear_optimization_caches(org_id=row.org_id)
    return GovernanceRecommendationLifecycleActionRead(
        recommendation_id=row.id,
        event_type="resolved",
        resolved_at=row.resolved_at,
        message="Recommendation resolved",
    )


async def reopen_recommendation(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    payload: GovernanceRecommendationReopenRequest,
) -> GovernanceRecommendationLifecycleActionRead:
    assert_can_generate_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    if row.resolved_at is None:
        raise HTTPException(status_code=400, detail="Recommendation is not resolved")
    now = datetime.now(UTC)
    row.reopened_at = now
    row.resolution_note = payload.note or row.resolution_note
    await record_lifecycle_event(
        session,
        org_id=row.org_id,
        recommendation_id=row.id,
        event_type=GovernanceRecommendationLifecycleEventType.REOPENED,
        actor_user_id=current_user.id,
        metadata={"note": payload.note},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_reopened",
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendations",
        source_id=row.id,
        metadata={"note": payload.note},
    )
    await session.commit()
    clear_recommendation_effectiveness_caches(org_id=row.org_id)
    clear_optimization_caches(org_id=row.org_id)
    return GovernanceRecommendationLifecycleActionRead(
        recommendation_id=row.id,
        event_type="reopened",
        reopened_at=row.reopened_at,
        resolved_at=row.resolved_at,
        message="Recommendation reopened",
    )


async def cancel_recommendation_resolution(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    payload: GovernanceRecommendationCancelResolutionRequest,
) -> GovernanceRecommendationLifecycleActionRead:
    assert_can_generate_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    if row.resolved_at is None and row.reopened_at is None:
        raise HTTPException(status_code=400, detail="No resolution to cancel")
    now = datetime.now(UTC)
    row.resolved_at = None
    row.resolved_by_user_id = None
    row.reopened_at = None
    row.resolution_cancelled_at = now
    row.resolution_note = payload.note or row.resolution_note
    await record_lifecycle_event(
        session,
        org_id=row.org_id,
        recommendation_id=row.id,
        event_type=GovernanceRecommendationLifecycleEventType.RESOLUTION_CANCELLED,
        actor_user_id=current_user.id,
        metadata={"note": payload.note},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_resolution_cancelled",
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendations",
        source_id=row.id,
        metadata={"note": payload.note},
    )
    await session.commit()
    clear_recommendation_effectiveness_caches(org_id=row.org_id)
    clear_optimization_caches(org_id=row.org_id)
    return GovernanceRecommendationLifecycleActionRead(
        recommendation_id=row.id,
        event_type="resolution_cancelled",
        message="Resolution cancelled",
    )


async def change_conversion_target(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    payload: GovernanceRecommendationChangeConversionTargetRequest,
) -> GovernanceRecommendationLifecycleActionRead:
    assert_can_generate_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    if not is_converted(row):
        raise HTTPException(status_code=400, detail="Recommendation has no conversion to change")
    previous = {
        "converted_action_id": str(row.converted_action_id) if row.converted_action_id else None,
        "converted_escalation_id": str(row.converted_escalation_id)
        if row.converted_escalation_id
        else None,
    }
    if payload.target == GovernanceRecommendationConversionTarget.ACTION:
        if payload.target_id is None:
            raise HTTPException(status_code=400, detail="target_id required for action target")
        row.converted_action_id = payload.target_id
        row.converted_escalation_id = None
    else:
        if payload.target_id is None:
            raise HTTPException(status_code=400, detail="target_id required for escalation target")
        row.converted_escalation_id = payload.target_id
        row.converted_action_id = None
    await record_lifecycle_event(
        session,
        org_id=row.org_id,
        recommendation_id=row.id,
        event_type=GovernanceRecommendationLifecycleEventType.CONVERSION_TARGET_CHANGED,
        actor_user_id=current_user.id,
        conversion_target=payload.target.value,
        conversion_target_id=payload.target_id,
        metadata={"previous": previous, "note": payload.note},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_conversion_target_changed",
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendations",
        source_id=row.id,
        metadata={"target": payload.target.value, "target_id": str(payload.target_id)},
    )
    await session.commit()
    clear_recommendation_effectiveness_caches(org_id=row.org_id)
    clear_optimization_caches(org_id=row.org_id)
    return GovernanceRecommendationLifecycleActionRead(
        recommendation_id=row.id,
        event_type="conversion_target_changed",
        conversion_target=payload.target.value,
        conversion_target_id=payload.target_id,
        message="Conversion target updated",
    )


# ---------------------------------------------------------------------------
# Learning rules
# ---------------------------------------------------------------------------


async def list_learning_rules(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceLearningRuleRead]:
    assert_can_manage_optimization(current_user)
    stmt = select(GovernanceRecommendationLearningRule).where(
        GovernanceRecommendationLearningRule.deleted_at.is_(None)
    )
    stmt = _apply_org_filter(stmt, GovernanceRecommendationLearningRule.org_id, current_user)
    stmt = stmt.order_by(GovernanceRecommendationLearningRule.created_at.desc()).limit(200)
    rows = list((await session.execute(stmt)).scalars())
    return [_rule_to_read(r) for r in rows]


async def approve_learning_rule(
    session: AsyncSession,
    current_user: CurrentUser,
    rule_id: UUID,
    *,
    activate: bool = False,
) -> GovernanceLearningRuleRead:
    assert_can_manage_optimization(current_user)
    if not _learning_rules_enabled() and activate:
        raise HTTPException(
            status_code=400,
            detail="Set GOVERNANCE_RECOMMENDATION_LEARNING_RULES_ENABLED to activate rules",
        )
    stmt = select(GovernanceRecommendationLearningRule).where(
        GovernanceRecommendationLearningRule.id == rule_id,
        GovernanceRecommendationLearningRule.deleted_at.is_(None),
    )
    stmt = _apply_org_filter(stmt, GovernanceRecommendationLearningRule.org_id, current_user)
    rule = (await session.execute(stmt)).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Learning rule not found")
    errors = validate_rule_payload(rule.rule_type, rule.rule_payload or {})
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})
    now = datetime.now(UTC)
    rule.status = GovernanceLearningRuleStatus.APPROVED
    rule.approved_at = now
    rule.approved_by_user_id = current_user.id
    rule.config_snapshot = {
        "rule_type": rule.rule_type,
        "rule_payload": rule.rule_payload or {},
        "version": rule.version,
        "allowed_effects": list(rule.allowed_effects or ALLOWED_RULE_EFFECTS),
    }
    if activate:
        if rule.shadow_evaluation_id is None:
            raise HTTPException(
                status_code=400,
                detail="Complete a shadow evaluation before activating a learning rule",
            )
        rule.previous_config_snapshot = rule.config_snapshot
        rule.status = GovernanceLearningRuleStatus.ACTIVE
        rule.evaluation_mode = "production"
        rule.activated_at = now
        rule.activated_by_user_id = current_user.id
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_learning_rule_approved",
        org_id=rule.org_id,
        source_table="governance_recommendation_learning_rules",
        source_id=rule.id,
        metadata={"activate": activate, "rule_type": rule.rule_type, "version": rule.version},
    )
    await session.commit()
    clear_optimization_caches(org_id=rule.org_id)
    return _rule_to_read(rule)


async def rollback_learning_rule(
    session: AsyncSession,
    current_user: CurrentUser,
    rule_id: UUID,
    *,
    disable_only: bool = False,
) -> GovernanceLearningRuleRead:
    assert_can_manage_optimization(current_user)
    stmt = select(GovernanceRecommendationLearningRule).where(
        GovernanceRecommendationLearningRule.id == rule_id,
        GovernanceRecommendationLearningRule.deleted_at.is_(None),
    )
    stmt = _apply_org_filter(stmt, GovernanceRecommendationLearningRule.org_id, current_user)
    rule = (await session.execute(stmt)).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Learning rule not found")
    now = datetime.now(UTC)
    rows = await _load_recommendations(
        session, current_user, OptimizationQueryFilters(days=30)
    )
    rule.performance_after = _metric_snapshot(rows)
    if disable_only:
        rule.status = GovernanceLearningRuleStatus.DISABLED
        rule.disabled_at = now
        rule.disabled_by_user_id = current_user.id
        rule.evaluation_mode = "none"
        event_type = "recommendation_learning_rule_disabled"
    else:
        if rule.previous_config_snapshot:
            prev = rule.previous_config_snapshot
            rule.rule_payload = prev.get("rule_payload") or rule.rule_payload
            rule.rule_type = prev.get("rule_type") or rule.rule_type
            rule.version = int(prev.get("version") or rule.version)
        rule.status = GovernanceLearningRuleStatus.REVERTED
        rule.reverted_at = now
        rule.reverted_by_user_id = current_user.id
        rule.evaluation_mode = "none"
        event_type = "recommendation_learning_rule_rolled_back"
    await log_governance_event(
        session,
        current_user,
        event_type=event_type,
        org_id=rule.org_id,
        source_table="governance_recommendation_learning_rules",
        source_id=rule.id,
        metadata={
            "disable_only": disable_only,
            "performance_before": rule.performance_before,
            "performance_after": rule.performance_after,
        },
    )
    await session.commit()
    clear_optimization_caches(org_id=rule.org_id)
    return _rule_to_read(rule)


async def run_shadow_evaluation(
    session: AsyncSession,
    current_user: CurrentUser,
    rule_id: UUID,
) -> GovernanceOptimizationShadowRead:
    assert_can_manage_optimization(current_user)
    stmt = select(GovernanceRecommendationLearningRule).where(
        GovernanceRecommendationLearningRule.id == rule_id,
        GovernanceRecommendationLearningRule.deleted_at.is_(None),
    )
    stmt = _apply_org_filter(stmt, GovernanceRecommendationLearningRule.org_id, current_user)
    rule = (await session.execute(stmt)).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Learning rule not found")
    errors = validate_rule_payload(rule.rule_type, rule.rule_payload or {})
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    settings = get_settings()
    rows = await _load_recommendations(
        session, current_user, OptimizationQueryFilters(days=30)
    )
    sample = rows[: max(10, settings.governance_recommendation_shadow_sample_limit)]
    baseline_candidates = [
        RecommendationCandidateView(
            id=str(r.id),
            title=r.title,
            confidence=float(r.confidence or 0),
            priority=str(getattr(r.priority, "value", r.priority) or "medium"),
            trigger_type=str(getattr(r.trigger_type, "value", r.trigger_type))
            if r.trigger_type
            else None,
            fingerprint=r.fingerprint,
            evidence_count=len(r.evidence_refs or []),
            ranking_score=float(r.confidence or 0) * 100
            + (10 if str(getattr(r.priority, "value", r.priority)) == "critical" else 0),
        )
        for r in sample
    ]
    result = apply_learning_rule(
        baseline_candidates,
        rule_type=rule.rule_type,
        rule_payload=rule.rule_payload or {},
        allowed_effects=list(rule.allowed_effects or ALLOWED_RULE_EFFECTS),
    )
    ranking_compare = compare_rankings(baseline_candidates, result.candidates)
    baseline_metrics = _metric_snapshot(sample)
    # Shadow never mutates production; estimate impact from ranking shifts only.
    expected_impact = {
        "rank_changes": ranking_compare["rank_changes"],
        "suppressed_count": ranking_compare["suppressed_count"],
        "applied_effects": result.applied_effects,
        "explanations": result.explanations,
        "production_unaffected": True,
    }
    now = datetime.now(UTC)
    shadow = GovernanceRecommendationShadowEvaluation(
        org_id=rule.org_id,
        learning_rule_id=rule.id,
        status=GovernanceRecommendationShadowStatus.COMPLETED,
        sample_size=len(sample),
        baseline_metrics=baseline_metrics,
        shadow_metrics={
            **baseline_metrics,
            "ranking": ranking_compare,
            "adjusted_confidence_count": sum(
                1 for c in result.candidates if "adjusted_confidence" in c.metadata
            ),
        },
        comparison_summary=ranking_compare,
        expected_impact=expected_impact,
        started_at=now,
        completed_at=now,
        created_by_user_id=current_user.id,
    )
    session.add(shadow)
    await session.flush()
    rule.status = GovernanceLearningRuleStatus.SHADOW
    rule.evaluation_mode = "shadow"
    rule.shadow_evaluation_id = shadow.id
    rule.performance_before = baseline_metrics
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_learning_rule_shadow_evaluated",
        org_id=rule.org_id,
        source_table="governance_recommendation_shadow_evaluations",
        source_id=shadow.id,
        metadata={"rule_id": str(rule.id), "sample_size": len(sample)},
    )
    await session.commit()
    clear_optimization_caches(org_id=rule.org_id)
    return GovernanceOptimizationShadowRead(
        id=shadow.id,
        learning_rule_id=rule.id,
        status=shadow.status.value,
        sample_size=shadow.sample_size,
        baseline_metrics=shadow.baseline_metrics,
        shadow_metrics=shadow.shadow_metrics,
        comparison_summary=shadow.comparison_summary,
        expected_impact=shadow.expected_impact,
        started_at=shadow.started_at,
        completed_at=shadow.completed_at,
        created_at=shadow.created_at,
    )


# ---------------------------------------------------------------------------
# Drift, strategies, compare, reports, summary
# ---------------------------------------------------------------------------


async def get_optimization_drift(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: GovernanceOptimizationFilters | None = None,
    *,
    persist: bool = True,
) -> GovernanceOptimizationDriftRead:
    assert_can_manage_optimization(current_user)
    qf = _filters_from_schema(filters)
    current_rows = await _load_recommendations(session, current_user, qf)
    baseline_filters = OptimizationQueryFilters(
        days=qf.days,
        project_id=qf.project_id,
        vertical=qf.vertical,
        strategy_version=qf.strategy_version,
    )
    # Compare recent half vs prior half of window
    mid = datetime.now(UTC) - timedelta(days=max(1, qf.days // 2))
    recent = [r for r in current_rows if r.generated_at >= mid]
    prior = [r for r in current_rows if r.generated_at < mid]
    recent_m = _metric_snapshot(recent)
    prior_m = _metric_snapshot(prior)
    settings = get_settings()
    alerts: list[GovernanceOptimizationDriftAlertRead] = []
    org_id = current_user.org_id

    def _rate(snapshot: dict[str, Any], key: str) -> float | None:
        metric = snapshot.get(key) or {}
        return metric.get("value")

    checks = [
        (
            "acceptance_drop",
            "acceptance_rate",
            settings.governance_recommendation_drift_acceptance_drop_pp,
            True,
        ),
        (
            "false_positive_rise",
            "false_positive_rate",
            settings.governance_recommendation_drift_fp_rise_pp,
            False,
        ),
    ]
    for alert_type, metric_key, threshold, drop in checks:
        cur = _rate(recent_m, metric_key)
        base = _rate(prior_m, metric_key)
        if cur is None or base is None:
            continue
        delta = (base - cur) if drop else (cur - base)
        if delta >= threshold:
            severity = (
                GovernanceRecommendationDriftSeverity.CRITICAL
                if delta >= threshold * 1.5
                else GovernanceRecommendationDriftSeverity.WARNING
            )
            message = (
                f"{metric_key} {'dropped' if drop else 'rose'} by {delta:.1f}pp "
                f"(baseline {base:.1f} → current {cur:.1f})"
            )
            alert_row = None
            if persist and org_id is not None:
                alert_row = GovernanceRecommendationDriftAlert(
                    org_id=org_id,
                    alert_type=alert_type,
                    severity=severity,
                    metric_name=metric_key,
                    baseline_value=base,
                    current_value=cur,
                    threshold_value=threshold,
                    message=message,
                    details={"prior": prior_m, "recent": recent_m},
                    strategy_version=qf.strategy_version,
                )
                session.add(alert_row)
                await session.flush()
            alerts.append(
                GovernanceOptimizationDriftAlertRead(
                    id=alert_row.id if alert_row else None,
                    alert_type=alert_type,
                    severity=severity.value,
                    metric_name=metric_key,
                    baseline_value=base,
                    current_value=cur,
                    threshold_value=threshold,
                    message=message,
                    strategy_version=qf.strategy_version,
                    created_at=datetime.now(UTC),
                )
            )

    # Volume spike
    if prior_m["volume"] > 0 and recent_m["volume"] >= prior_m["volume"] * settings.governance_recommendation_drift_volume_ratio:
        message = (
            f"Recommendation volume spiked "
            f"({prior_m['volume']} → {recent_m['volume']})"
        )
        alerts.append(
            GovernanceOptimizationDriftAlertRead(
                alert_type="volume_spike",
                severity=GovernanceRecommendationDriftSeverity.WARNING.value,
                metric_name="volume",
                baseline_value=float(prior_m["volume"]),
                current_value=float(recent_m["volume"]),
                threshold_value=settings.governance_recommendation_drift_volume_ratio,
                message=message,
                strategy_version=qf.strategy_version,
                created_at=datetime.now(UTC),
            )
        )

    if persist and alerts:
        await session.commit()

    return GovernanceOptimizationDriftRead(
        window_days=qf.days,
        baseline_metrics=prior_m,
        current_metrics=recent_m,
        alerts=alerts,
        auto_remediation=False,
    )


async def list_strategy_versions(
    session: AsyncSession,
    current_user: CurrentUser,
) -> list[GovernanceOptimizationStrategyRead]:
    assert_can_manage_optimization(current_user)
    stmt = select(GovernanceRecommendationStrategyVersion).where(
        GovernanceRecommendationStrategyVersion.deleted_at.is_(None)
    )
    stmt = _apply_org_filter(stmt, GovernanceRecommendationStrategyVersion.org_id, current_user)
    stmt = stmt.order_by(GovernanceRecommendationStrategyVersion.created_at.desc()).limit(100)
    rows = list((await session.execute(stmt)).scalars())
    if not rows and current_user.org_id is not None:
        settings = get_settings()
        default = GovernanceRecommendationStrategyVersion(
            org_id=current_user.org_id,
            strategy_version=settings.governance_recommendation_strategy_version,
            confidence_version=settings.governance_recommendation_confidence_version,
            quality_version=settings.governance_recommendation_quality_score_version,
            explanation_version=settings.governance_recommendation_explanation_version,
            is_active=True,
            activated_at=datetime.now(UTC),
            activated_by_user_id=current_user.id,
            created_by_user_id=current_user.id,
            change_summary="Default strategy version",
            config_snapshot={"source": "phase13_default"},
        )
        session.add(default)
        await session.commit()
        rows = [default]
    return [
        GovernanceOptimizationStrategyRead(
            id=r.id,
            strategy_version=r.strategy_version,
            confidence_version=r.confidence_version,
            quality_version=r.quality_version,
            explanation_version=r.explanation_version,
            learning_rule_version=r.learning_rule_version,
            is_active=r.is_active,
            change_summary=r.change_summary,
            activated_at=r.activated_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def compare_strategy_versions(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    strategy_a: str,
    strategy_b: str,
    days: int = 30,
) -> GovernanceOptimizationCompareRead:
    assert_can_manage_optimization(current_user)
    rows_a = await _load_recommendations(
        session,
        current_user,
        OptimizationQueryFilters(days=days, strategy_version=strategy_a),
    )
    rows_b = await _load_recommendations(
        session,
        current_user,
        OptimizationQueryFilters(days=days, strategy_version=strategy_b),
    )
    metrics_a = _metric_snapshot(rows_a)
    metrics_b = _metric_snapshot(rows_b)

    def _delta(key: str) -> float | None:
        va = (metrics_a.get(key) or {}).get("value") if isinstance(metrics_a.get(key), dict) else metrics_a.get(key)
        vb = (metrics_b.get(key) or {}).get("value") if isinstance(metrics_b.get(key), dict) else metrics_b.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            return float(vb) - float(va)
        return None

    return GovernanceOptimizationCompareRead(
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        days=days,
        metrics_a=metrics_a,
        metrics_b=metrics_b,
        deltas={
            "volume": _delta("volume"),
            "acceptance_rate": _delta("acceptance_rate"),
            "conversion_rate": _delta("conversion_rate"),
            "resolution_rate": _delta("resolution_rate"),
            "false_positive_rate": _delta("false_positive_rate"),
            "average_quality_score": _delta("average_quality_score"),
        },
        generated_at=datetime.now(UTC),
    )


async def list_shadow_evaluations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    limit: int = 50,
) -> list[GovernanceOptimizationShadowRead]:
    assert_can_manage_optimization(current_user)
    stmt = select(GovernanceRecommendationShadowEvaluation).order_by(
        GovernanceRecommendationShadowEvaluation.created_at.desc()
    ).limit(min(limit, 200))
    stmt = _apply_org_filter(stmt, GovernanceRecommendationShadowEvaluation.org_id, current_user)
    rows = list((await session.execute(stmt)).scalars())
    return [
        GovernanceOptimizationShadowRead(
            id=r.id,
            learning_rule_id=r.learning_rule_id,
            status=r.status.value if hasattr(r.status, "value") else str(r.status),
            sample_size=r.sample_size,
            baseline_metrics=r.baseline_metrics or {},
            shadow_metrics=r.shadow_metrics or {},
            comparison_summary=r.comparison_summary or {},
            expected_impact=r.expected_impact or {},
            started_at=r.started_at,
            completed_at=r.completed_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def generate_evaluation_report(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    period: GovernanceRecommendationEvaluationPeriod,
    days: int | None = None,
) -> GovernanceOptimizationReportRead:
    assert_can_manage_optimization(current_user)
    if current_user.org_id is None:
        raise HTTPException(status_code=400, detail="Organization required")
    period_days = days or {
        GovernanceRecommendationEvaluationPeriod.WEEKLY: 7,
        GovernanceRecommendationEvaluationPeriod.MONTHLY: 30,
        GovernanceRecommendationEvaluationPeriod.QUARTERLY: 90,
    }[period]
    end = date.today()
    start = end - timedelta(days=period_days)
    summary = await get_effectiveness_summary(
        session,
        current_user,
        EffectivenessFilters(days=period_days),
    )
    drift = await get_optimization_drift(
        session,
        current_user,
        GovernanceOptimizationFilters(days=period_days),
        persist=False,
    )
    rules = await list_learning_rules(session, current_user)
    strategies = await list_strategy_versions(session, current_user)
    payload = {
        "kpi_summary": summary.model_dump(mode="json"),
        "drift": drift.model_dump(mode="json"),
        "learning_rules": [r.model_dump(mode="json") for r in rules],
        "strategies": [s.model_dump(mode="json") for s in strategies],
        "recommendations_for_review": [a.message for a in drift.alerts],
    }
    existing = (
        await session.execute(
            select(GovernanceRecommendationEvaluationReport).where(
                GovernanceRecommendationEvaluationReport.org_id == current_user.org_id,
                GovernanceRecommendationEvaluationReport.period == period,
                GovernanceRecommendationEvaluationReport.period_start == start,
                GovernanceRecommendationEvaluationReport.period_end == end,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.report_payload = payload
        existing.generated_at = datetime.now(UTC)
        existing.generated_by_user_id = current_user.id
        report = existing
    else:
        report = GovernanceRecommendationEvaluationReport(
            org_id=current_user.org_id,
            period=period,
            period_start=start,
            period_end=end,
            strategy_version=next((s.strategy_version for s in strategies if s.is_active), None),
            report_payload=payload,
            generated_by_user_id=current_user.id,
        )
        session.add(report)
        await session.flush()
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_evaluation_report_generated",
        org_id=current_user.org_id,
        source_table="governance_recommendation_evaluation_reports",
        source_id=report.id,
        metadata={"period": period.value},
    )
    await session.commit()
    await session.refresh(report)
    return GovernanceOptimizationReportRead(
        id=report.id,
        period=report.period.value,
        period_start=report.period_start,
        period_end=report.period_end,
        strategy_version=report.strategy_version,
        report_payload=report.report_payload,
        generated_at=report.generated_at,
    )


async def list_evaluation_reports(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    limit: int = 50,
) -> list[GovernanceOptimizationReportRead]:
    assert_can_manage_optimization(current_user)
    stmt = select(GovernanceRecommendationEvaluationReport).order_by(
        GovernanceRecommendationEvaluationReport.generated_at.desc()
    ).limit(min(limit, 200))
    stmt = _apply_org_filter(stmt, GovernanceRecommendationEvaluationReport.org_id, current_user)
    rows = list((await session.execute(stmt)).scalars())
    return [
        GovernanceOptimizationReportRead(
            id=r.id,
            period=r.period.value if hasattr(r.period, "value") else str(r.period),
            period_start=r.period_start,
            period_end=r.period_end,
            strategy_version=r.strategy_version,
            report_payload=r.report_payload or {},
            generated_at=r.generated_at,
        )
        for r in rows
    ]


def optimization_report_csv(report: GovernanceOptimizationReportRead) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "key", "value"])
    writer.writerow(["meta", "period", report.period])
    writer.writerow(["meta", "period_start", str(report.period_start)])
    writer.writerow(["meta", "period_end", str(report.period_end)])
    writer.writerow(["meta", "strategy_version", report.strategy_version or ""])
    kpi = (report.report_payload or {}).get("kpi_summary") or {}
    for key, value in kpi.items():
        writer.writerow(["kpi", key, json.dumps(value) if isinstance(value, (dict, list)) else value])
    for alert in ((report.report_payload or {}).get("drift") or {}).get("alerts") or []:
        writer.writerow(["drift", alert.get("alert_type"), alert.get("message")])
    return output.getvalue()


async def get_optimization_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    filters: GovernanceOptimizationFilters | None = None,
) -> GovernanceOptimizationSummaryRead:
    assert_can_manage_optimization(current_user)
    qf = _filters_from_schema(filters)
    cache_key = (
        str(current_user.org_id),
        "opt_summary",
        qf.days,
        str(qf.project_id),
        qf.vertical,
        qf.strategy_version,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    rules = await list_learning_rules(session, current_user)
    active_rules = [r for r in rules if r.status == "active"]
    pending = [r for r in rules if r.status in {"pending_approval", "approved", "shadow"}]
    shadows = await list_shadow_evaluations(session, current_user, limit=20)
    strategies = await list_strategy_versions(session, current_user)
    drift = await get_optimization_drift(session, current_user, filters, persist=False)
    reports = await list_evaluation_reports(session, current_user, limit=10)
    rows = await _load_recommendations(session, current_user, qf)
    snapshot = _metric_snapshot(rows)

    result = GovernanceOptimizationSummaryRead(
        generated_at=datetime.now(UTC),
        filters={
            "days": qf.days,
            "project_id": str(qf.project_id) if qf.project_id else None,
            "vertical": qf.vertical,
            "strategy_version": qf.strategy_version,
        },
        metrics=snapshot,
        active_learning_rules=active_rules,
        pending_approvals=pending,
        recent_shadow_evaluations=shadows[:5],
        drift_warnings=drift.alerts,
        strategy_versions=strategies,
        recent_reports=reports[:5],
        learning_rules_enabled=_learning_rules_enabled(),
    )
    _cache_set(cache_key, result)
    return result
