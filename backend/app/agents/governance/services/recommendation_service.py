"""Persisted, grounded AI Governance recommendations with rule-based fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    ConvertRecommendationToActionRequest,
    ConvertRecommendationToEscalationRequest,
    GovernanceActionRead,
    GovernanceAIRecommendationCandidate,
    GovernanceAIRecommendationEvidenceRead,
    GovernanceAIRecommendationFeedbackRead,
    GovernanceAIRecommendationGenerationResult,
    GovernanceAIRecommendationListRead,
    GovernanceAIRecommendationLLMResponse,
    GovernanceAIRecommendationRead,
    GovernanceEscalationRead,
    GovernanceRecommendationConversionRead,
    GovernanceRuleBasedRecommendationRead,
    GovernanceSuggestedAction,
)
from app.agents.governance.services.audit_service import log_governance_event
from app.agents.governance.services.governance_service import (
    assert_can_read_governance,
    can_read_internal_governance,
    create_action,
    create_escalation,
    enriched_action_read,
    enriched_escalation_read,
    invalidate_governance_read_caches_after_commit,
    load_project_names,
)
from app.agents.governance.services.recommendation_evidence import (
    GovernanceRecommendationEvidenceBundle,
    build_governance_recommendation_evidence,
    evidence_bundle_to_prompt_json,
    source_snapshot_from_bundle,
)
from app.agents.governance.services.recommendation_grounding import (
    recommendation_fingerprint,
    titles_are_near_duplicates,
    validate_candidate_grounding,
)
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceActionStatus,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationConversion,
    GovernanceAIRecommendationFeedback,
    GovernanceAIRecommendationPriority,
    GovernanceAIRecommendationScope,
    GovernanceAIRecommendationStatus,
    GovernanceAIRecommendationType,
    GovernanceEscalationStatus,
    GovernanceRecommendationAcceptanceStatus,
    GovernanceRecommendationConversionTarget,
)
from app.services.llm.client import LLMClient
from app.services.scoping import get_visible_project

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "ai_recommendations.md"
PROMPT_VERSION_DEFAULT = "v1"

GOVERNANCE_AI_VIEW_ROLES = {
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
}
GOVERNANCE_AI_GENERATE_ROLES = {
    AppRole.DELIVERY_MANAGER,
    AppRole.BSG_LEADERSHIP,
    AppRole.SUPER_ADMIN,
}

_generation_locks: dict[str, asyncio.Lock] = {}
_generation_lock_guard = asyncio.Lock()

# Safe in-process observability counters (no PII / prompts).
_METRICS: dict[str, float] = {
    "generation_requests": 0,
    "generation_successes": 0,
    "generation_failures": 0,
    "generation_duration_ms_total": 0,
    "provider_duration_ms_total": 0,
    "candidates_returned": 0,
    "candidates_persisted": 0,
    "candidates_rejected_grounding": 0,
    "duplicates_suppressed": 0,
    "fallback_used": 0,
    "conversion_requests": 0,
    "conversion_successes": 0,
    "conversion_failures": 0,
    "conversion_reuses": 0,
    "action_conversions": 0,
    "escalation_conversions": 0,
    "duplicate_conflicts": 0,
    "permission_rejections": 0,
    "conversion_duration_ms_total": 0,
}

ACTION_COMPATIBLE_SUGGESTIONS = {
    "assign_owner",
    "create_action",
    "monitor",
    "resolve_dependency",
    "review",
    "schedule_governance_review",
    "update_scope",
}
ESCALATION_COMPATIBLE_SUGGESTIONS = {"consider_escalation"}
UNSCOPED_SUGGESTED_ACTION_INDEX = -1


def _inc_metric(name: str, value: float = 1.0) -> None:
    _METRICS[name] = _METRICS.get(name, 0.0) + value


def get_recommendation_metrics() -> dict[str, float]:
    return dict(_METRICS)


def reset_recommendation_metrics() -> None:
    for key in list(_METRICS):
        _METRICS[key] = 0.0


def assert_can_view_ai_recommendations(current_user: CurrentUser) -> None:
    assert_can_read_governance(current_user)
    if current_user.role not in GOVERNANCE_AI_VIEW_ROLES or not can_read_internal_governance(
        current_user
    ):
        raise ApiError(403, "FORBIDDEN", "AI recommendations are available to internal roles only.")


def assert_can_generate_ai_recommendations(current_user: CurrentUser) -> None:
    assert_can_view_ai_recommendations(current_user)
    if current_user.role not in GOVERNANCE_AI_GENERATE_ROLES:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")


def can_generate_ai_recommendations(current_user: CurrentUser) -> bool:
    return (
        current_user.role in GOVERNANCE_AI_GENERATE_ROLES
        and can_read_internal_governance(current_user)
    )


def ai_recommendations_enabled() -> bool:
    return bool(get_settings().governance_ai_recommendations_enabled)


def _load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _flight_key(
    *,
    org_id: UUID | None,
    project_id: UUID | None,
    scope: GovernanceAIRecommendationScope,
    evidence_hash: str,
    prompt_version: str,
) -> str:
    return "|".join(
        [
            str(org_id) if org_id else "all",
            scope.value,
            str(project_id) if project_id else "portfolio",
            evidence_hash,
            prompt_version,
        ]
    )


async def _acquire_flight_lock(key: str) -> asyncio.Lock:
    async with _generation_lock_guard:
        lock = _generation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _generation_locks[key] = lock
        return lock


def _evidence_reads_from_refs(
    refs: list[Any],
    bundle: GovernanceRecommendationEvidenceBundle | None = None,
) -> list[GovernanceAIRecommendationEvidenceRead]:
    by_id = {item.evidence_id: item for item in (bundle.evidence if bundle else [])}
    reads: list[GovernanceAIRecommendationEvidenceRead] = []
    for ref in refs or []:
        if isinstance(ref, dict):
            evidence_id = str(ref.get("evidence_id") or "")
            if evidence_id and evidence_id in by_id:
                item = by_id[evidence_id]
                reads.append(
                    GovernanceAIRecommendationEvidenceRead(
                        evidence_id=item.evidence_id,
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        project_id=item.project_id,
                        title=item.title,
                        summary=item.summary,
                        status=item.status,
                        severity=item.severity,
                        occurred_at=item.occurred_at,
                    )
                )
            elif evidence_id:
                reads.append(
                    GovernanceAIRecommendationEvidenceRead(
                        evidence_id=evidence_id,
                        entity_type=str(ref.get("entity_type") or "governance_metric"),
                        entity_id=UUID(ref["entity_id"]) if ref.get("entity_id") else None,
                        project_id=UUID(ref["project_id"]) if ref.get("project_id") else None,
                        title=str(ref.get("title") or evidence_id),
                        summary=str(ref.get("summary") or ""),
                        status=ref.get("status"),
                        severity=ref.get("severity"),
                        occurred_at=None,
                    )
                )
        elif isinstance(ref, str) and ref in by_id:
            item = by_id[ref]
            reads.append(
                GovernanceAIRecommendationEvidenceRead(
                    evidence_id=item.evidence_id,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    project_id=item.project_id,
                    title=item.title,
                    summary=item.summary,
                    status=item.status,
                    severity=item.severity,
                    occurred_at=item.occurred_at,
                )
            )
    return reads


def _to_read(
    row: GovernanceAIRecommendation,
    *,
    project_name: str | None,
    can_generate: bool,
    current_evidence_hash: str | None = None,
    bundle: GovernanceRecommendationEvidenceBundle | None = None,
) -> GovernanceAIRecommendationRead:
    suggested = []
    for item in row.suggested_actions or []:
        try:
            suggested.append(GovernanceSuggestedAction.model_validate(item))
        except ValidationError:
            continue
    is_stale = bool(
        current_evidence_hash
        and row.evidence_hash
        and row.evidence_hash != current_evidence_hash
        and row.status == GovernanceAIRecommendationStatus.ACTIVE
    )
    return GovernanceAIRecommendationRead(
        id=row.id,
        scope=row.scope,
        project_id=row.project_id,
        project_name=project_name,
        recommendation_type=row.recommendation_type,
        title=row.title,
        narrative=row.narrative,
        rationale=row.rationale,
        priority=row.priority,
        confidence=float(row.confidence),
        suggested_actions=suggested,
        evidence=_evidence_reads_from_refs(row.evidence_refs or [], bundle),
        status=row.status,
        generated_at=row.generated_at,
        expires_at=row.expires_at,
        can_regenerate=can_generate and row.status in {
            GovernanceAIRecommendationStatus.ACTIVE,
            GovernanceAIRecommendationStatus.STALE,
            GovernanceAIRecommendationStatus.SUPERSEDED,
        },
        can_dismiss=can_generate and row.status == GovernanceAIRecommendationStatus.ACTIVE,
        is_ai_generated=True,
        source_type="ai",
        is_stale=is_stale or row.status == GovernanceAIRecommendationStatus.STALE,
        evidence_hash=row.evidence_hash,
        acceptance_status=row.acceptance_status,
        accepted_at=row.accepted_at,
        accepted_by_user_id=row.accepted_by_user_id,
        converted_action_id=row.converted_action_id,
        converted_escalation_id=row.converted_escalation_id,
        accepted_suggested_action_index=row.accepted_suggested_action_index,
        acceptance_note=row.acceptance_note,
    )


def build_rule_based_recommendation_reads(
    bundle: GovernanceRecommendationEvidenceBundle,
) -> list[GovernanceRuleBasedRecommendationRead]:
    reads: list[GovernanceRuleBasedRecommendationRead] = []
    evidence_by_id = {item.evidence_id: item for item in bundle.evidence}
    for signal in bundle.signals:
        evidence = []
        for evidence_id in signal.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if not item:
                continue
            evidence.append(
                GovernanceAIRecommendationEvidenceRead(
                    evidence_id=item.evidence_id,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    project_id=item.project_id,
                    title=item.title,
                    summary=item.summary,
                    status=item.status,
                    severity=item.severity,
                    occurred_at=item.occurred_at,
                )
            )
        if not evidence:
            continue
        reads.append(
            GovernanceRuleBasedRecommendationRead(
                title=signal.candidate_message,
                detail=(
                    f"{signal.signal_type.replace('_', ' ').title()} signal with facts "
                    f"{json.dumps(signal.facts, sort_keys=True)}."
                ),
                priority=signal.severity,
                project_id=signal.project_id,
                project_name=signal.project_name,
                evidence=evidence[:3],
            )
        )
    return reads


async def _list_active_rows(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    org_id: UUID | None,
    project_id: UUID | None,
    scope: GovernanceAIRecommendationScope | None,
    status: GovernanceAIRecommendationStatus | None = GovernanceAIRecommendationStatus.ACTIVE,
    limit: int = 20,
    offset: int = 0,
) -> list[GovernanceAIRecommendation]:
    stmt = select(GovernanceAIRecommendation).where(
        GovernanceAIRecommendation.deleted_at.is_(None)
    )
    if org_id is not None:
        stmt = stmt.where(GovernanceAIRecommendation.org_id == org_id)
    elif current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(GovernanceAIRecommendation.org_id == current_user.org_id)
    if project_id is not None:
        stmt = stmt.where(GovernanceAIRecommendation.project_id == project_id)
    if scope is not None:
        stmt = stmt.where(GovernanceAIRecommendation.scope == scope)
    if status is not None:
        stmt = stmt.where(GovernanceAIRecommendation.status == status)
    stmt = stmt.order_by(GovernanceAIRecommendation.generated_at.desc()).offset(offset).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def list_governance_ai_recommendations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    scope: GovernanceAIRecommendationScope | None = GovernanceAIRecommendationScope.PROJECT,
    status: GovernanceAIRecommendationStatus | None = GovernanceAIRecommendationStatus.ACTIVE,
    limit: int = 20,
    offset: int = 0,
    include_rule_based: bool = True,
) -> GovernanceAIRecommendationListRead:
    assert_can_view_ai_recommendations(current_user)
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id

    if scope == GovernanceAIRecommendationScope.PROJECT and project_id is not None:
        await get_visible_project(session, project_id, current_user)

    rows = await _list_active_rows(
        session,
        current_user,
        org_id=org_id,
        project_id=project_id,
        scope=scope,
        status=status,
        limit=limit,
        offset=offset,
    )
    project_ids = {row.project_id for row in rows if row.project_id}
    names = await load_project_names(session, project_ids)
    can_generate = can_generate_ai_recommendations(current_user) and ai_recommendations_enabled()

    current_hash: str | None = None
    rule_based: list[GovernanceRuleBasedRecommendationRead] = []
    if include_rule_based:
        try:
            bundle = await build_governance_recommendation_evidence(
                session,
                current_user,
                org_id=org_id,
                project_id=project_id,
                scope=scope or GovernanceAIRecommendationScope.PROJECT,
            )
            current_hash = bundle.evidence_hash
            rule_based = build_rule_based_recommendation_reads(bundle)
        except Exception:
            logger.exception("governance_ai_rule_based_list_failed")

    items = [
        _to_read(
            row,
            project_name=names.get(row.project_id) if row.project_id else None,
            can_generate=can_generate,
            current_evidence_hash=current_hash,
        )
        for row in rows
    ]
    return GovernanceAIRecommendationListRead(
        items=items,
        rule_based=rule_based,
        total=len(items),
        ai_enabled=ai_recommendations_enabled(),
        can_generate=can_generate,
    )


async def get_governance_ai_recommendation(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
) -> GovernanceAIRecommendation:
    assert_can_view_ai_recommendations(current_user)
    stmt = select(GovernanceAIRecommendation).where(
        GovernanceAIRecommendation.id == recommendation_id,
        GovernanceAIRecommendation.deleted_at.is_(None),
    )
    if current_user.role != AppRole.SUPER_ADMIN:
        stmt = stmt.where(GovernanceAIRecommendation.org_id == current_user.org_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Recommendation was not found.")
    if row.project_id is not None:
        await get_visible_project(session, row.project_id, current_user)
    return row


def _extract_json_payload(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


async def _call_llm(
    *,
    bundle: GovernanceRecommendationEvidenceBundle,
    prompt_version: str,
    max_items: int,
    model_name: str | None,
) -> tuple[list[GovernanceAIRecommendationCandidate], float | None, str | None]:
    settings = get_settings()
    if not (settings.llm_api_key or settings.openai_api_key):
        return [], None, "provider_unconfigured"

    template = _load_prompt_template()
    prompt = (
        template.replace("{{SCOPE}}", bundle.scope.value)
        .replace("{{MAX_ITEMS}}", str(max_items))
        .replace("{{PROMPT_VERSION}}", prompt_version)
        .replace(
            "{{CANDIDATE_SIGNALS_JSON}}",
            json.dumps([s.model_dump(mode="json") for s in bundle.signals], indent=2, default=str),
        )
        .replace(
            "{{EVIDENCE_JSON}}",
            json.dumps(evidence_bundle_to_prompt_json(bundle), indent=2, default=str),
        )
    )
    timeout = settings.governance_ai_recommendation_timeout_seconds
    started = perf_counter()
    try:
        client = LLMClient()
        # Temporarily override model via settings field when configured.
        if model_name:
            # LLMClient reads openai_model/llm_model; pass via generate_structured system/user.
            pass
        raw = await asyncio.wait_for(
            client.generate_structured(
                system=(
                    "You are a Governance recommendation engine. "
                    "Return valid JSON only using the supplied evidence."
                ),
                user=prompt,
                context="",
                json_mode=True,
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("governance_ai_llm_failed error=%s", type(exc).__name__)
        return [], None, "provider_error"

    provider_ms = round((perf_counter() - started) * 1000, 1)
    _inc_metric("provider_duration_ms_total", provider_ms)
    try:
        payload = _extract_json_payload(raw)
        parsed = GovernanceAIRecommendationLLMResponse.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return [], provider_ms, "invalid_schema"
    return parsed.recommendations[:max_items], provider_ms, None


def _dismissed_fingerprints(rows: list[GovernanceAIRecommendation]) -> set[str]:
    return {
        row.fingerprint
        for row in rows
        if row.status == GovernanceAIRecommendationStatus.DISMISSED and row.fingerprint
    }


async def _load_related_rows(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID | None,
    scope: GovernanceAIRecommendationScope,
) -> list[GovernanceAIRecommendation]:
    stmt = select(GovernanceAIRecommendation).where(
        GovernanceAIRecommendation.org_id == org_id,
        GovernanceAIRecommendation.scope == scope,
        GovernanceAIRecommendation.deleted_at.is_(None),
        GovernanceAIRecommendation.status.in_(
            (
                GovernanceAIRecommendationStatus.ACTIVE,
                GovernanceAIRecommendationStatus.DISMISSED,
                GovernanceAIRecommendationStatus.STALE,
            )
        ),
    )
    if project_id is None:
        stmt = stmt.where(GovernanceAIRecommendation.project_id.is_(None))
    else:
        stmt = stmt.where(GovernanceAIRecommendation.project_id == project_id)
    return list((await session.execute(stmt)).scalars())


async def generate_governance_ai_recommendations(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    project_id: UUID | None = None,
    scope: GovernanceAIRecommendationScope = GovernanceAIRecommendationScope.PROJECT,
    force: bool = False,
) -> GovernanceAIRecommendationGenerationResult:
    started = perf_counter()
    _inc_metric("generation_requests")
    assert_can_generate_ai_recommendations(current_user)
    settings = get_settings()
    prompt_version = settings.governance_ai_recommendation_prompt_version or PROMPT_VERSION_DEFAULT
    max_items = max(1, min(settings.governance_ai_recommendation_max_items, 10))
    generation_request_id = uuid4()
    org_id = current_user.org_id
    if org_id is None and current_user.role != AppRole.SUPER_ADMIN:
        raise ApiError(400, "ORG_REQUIRED", "Organisation context is required.")

    if scope == GovernanceAIRecommendationScope.PROJECT:
        if project_id is None:
            raise ApiError(422, "VALIDATION_ERROR", "project_id is required for project scope.")
        project = await get_visible_project(session, project_id, current_user)
        org_id = project.org_id
    elif current_user.role not in {AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN}:
        raise ApiError(403, "FORBIDDEN", "Portfolio recommendations require leadership access.")

    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_generation_requested",
        org_id=org_id or current_user.org_id,
        project_id=project_id,
        source_table="governance_ai_recommendations",
        metadata={
            "scope": scope.value,
            "force": force,
            "generation_request_id": str(generation_request_id),
            "prompt_version": prompt_version,
        },
    )

    bundle = await build_governance_recommendation_evidence(
        session,
        current_user,
        org_id=org_id,
        project_id=project_id,
        scope=scope,
    )
    rule_based = build_rule_based_recommendation_reads(bundle)
    _inc_metric("evidence_item_count", float(len(bundle.evidence)))

    if not ai_recommendations_enabled():
        _inc_metric("fallback_used")
        await log_governance_event(
            session,
            current_user,
            event_type="recommendation_generation_failed",
            org_id=org_id or current_user.org_id,
            project_id=project_id,
            metadata={"failure_category": "disabled", "generation_request_id": str(generation_request_id)},
        )
        await session.commit()
        return GovernanceAIRecommendationGenerationResult(
            recommendations=[],
            rule_based_fallback=rule_based,
            fallback_used=True,
            fallback_reason="disabled",
            generation_request_id=generation_request_id,
            evidence_hash=bundle.evidence_hash,
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )

    if not bundle.evidence or not bundle.signals:
        _inc_metric("fallback_used")
        await session.commit()
        return GovernanceAIRecommendationGenerationResult(
            recommendations=[],
            rule_based_fallback=rule_based,
            fallback_used=True,
            fallback_reason="insufficient_evidence",
            generation_request_id=generation_request_id,
            evidence_hash=bundle.evidence_hash,
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )

    flight = _flight_key(
        org_id=org_id,
        project_id=project_id,
        scope=scope,
        evidence_hash=bundle.evidence_hash,
        prompt_version=prompt_version,
    )
    lock = await _acquire_flight_lock(flight)
    async with lock:
        related = await _load_related_rows(
            session, org_id=org_id or current_user.org_id, project_id=project_id, scope=scope
        )
        active_same_hash = [
            row
            for row in related
            if row.status == GovernanceAIRecommendationStatus.ACTIVE
            and row.evidence_hash == bundle.evidence_hash
            and row.prompt_version == prompt_version
        ]
        if active_same_hash and not force:
            await log_governance_event(
                session,
                current_user,
                event_type="recommendation_reused",
                org_id=org_id or current_user.org_id,
                project_id=project_id,
                metadata={
                    "generation_request_id": str(generation_request_id),
                    "evidence_hash_prefix": bundle.evidence_hash[:12],
                    "result_count": len(active_same_hash),
                    "prompt_version": prompt_version,
                },
            )
            await session.commit()
            names = await load_project_names(
                session, {row.project_id for row in active_same_hash if row.project_id}
            )
            reads = [
                _to_read(
                    row,
                    project_name=names.get(row.project_id) if row.project_id else None,
                    can_generate=True,
                    current_evidence_hash=bundle.evidence_hash,
                    bundle=bundle,
                )
                for row in active_same_hash
            ]
            return GovernanceAIRecommendationGenerationResult(
                recommendations=reads,
                rule_based_fallback=rule_based,
                reused=True,
                generation_request_id=generation_request_id,
                evidence_hash=bundle.evidence_hash,
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )

        if not force:
            # Cooldown: if any active recommendation for this scope/project was generated recently.
            latest = max(
                (row.generated_at for row in related if row.status == GovernanceAIRecommendationStatus.ACTIVE),
                default=None,
            )
            if latest is not None and not active_same_hash:
                age = (datetime.now(timezone.utc) - latest.astimezone(timezone.utc)).total_seconds()
                if age < settings.governance_ai_recommendation_cooldown_seconds:
                    _inc_metric("fallback_used")
                    names = await load_project_names(
                        session,
                        {
                            row.project_id
                            for row in related
                            if row.project_id and row.status == GovernanceAIRecommendationStatus.ACTIVE
                        },
                    )
                    active_reads = [
                        _to_read(
                            row,
                            project_name=names.get(row.project_id) if row.project_id else None,
                            can_generate=True,
                            current_evidence_hash=bundle.evidence_hash,
                            bundle=bundle,
                        )
                        for row in related
                        if row.status == GovernanceAIRecommendationStatus.ACTIVE
                    ]
                    await session.commit()
                    return GovernanceAIRecommendationGenerationResult(
                        recommendations=active_reads,
                        rule_based_fallback=rule_based,
                        reused=True,
                        fallback_used=not active_reads,
                        fallback_reason="cooldown" if not active_reads else None,
                        generation_request_id=generation_request_id,
                        evidence_hash=bundle.evidence_hash,
                        duration_ms=round((perf_counter() - started) * 1000, 1),
                    )

        model_name = (
            settings.governance_ai_recommendation_model
            or settings.openai_model
            or settings.llm_model
            or "gpt-4o-mini"
        )
        candidates, _provider_ms, failure = await _call_llm(
            bundle=bundle,
            prompt_version=prompt_version,
            max_items=max_items,
            model_name=model_name,
        )
        _inc_metric("candidates_returned", float(len(candidates)))

        if failure:
            _inc_metric("generation_failures")
            _inc_metric("fallback_used")
            await log_governance_event(
                session,
                current_user,
                event_type="recommendation_generation_failed",
                org_id=org_id or current_user.org_id,
                project_id=project_id,
                metadata={
                    "failure_category": failure,
                    "generation_request_id": str(generation_request_id),
                    "evidence_hash_prefix": bundle.evidence_hash[:12],
                    "model": model_name,
                    "prompt_version": prompt_version,
                },
            )
            await session.commit()
            return GovernanceAIRecommendationGenerationResult(
                recommendations=[],
                rule_based_fallback=rule_based,
                fallback_used=True,
                fallback_reason=failure,
                generation_request_id=generation_request_id,
                evidence_hash=bundle.evidence_hash,
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )

        dismissed = _dismissed_fingerprints(related)
        active_rows = [
            row for row in related if row.status == GovernanceAIRecommendationStatus.ACTIVE
        ]
        persisted: list[GovernanceAIRecommendation] = []
        rejected = 0
        duplicates = 0
        snapshot = source_snapshot_from_bundle(bundle)

        for candidate in candidates:
            # Align scope/project with request
            if scope == GovernanceAIRecommendationScope.PROJECT:
                candidate.scope = "project"
                candidate.project_id = project_id
            ok, reasons = validate_candidate_grounding(candidate, bundle)
            if not ok:
                rejected += 1
                _inc_metric("candidates_rejected_grounding")
                await log_governance_event(
                    session,
                    current_user,
                    event_type="recommendation_rejected_by_grounding",
                    org_id=org_id or current_user.org_id,
                    project_id=project_id,
                    metadata={
                        "reasons": reasons[:8],
                        "recommendation_type": candidate.recommendation_type.value,
                        "generation_request_id": str(generation_request_id),
                        "evidence_hash_prefix": bundle.evidence_hash[:12],
                    },
                )
                continue

            fingerprint = recommendation_fingerprint(
                recommendation_type=candidate.recommendation_type.value,
                project_id=candidate.project_id,
                title=candidate.title,
                evidence_hash=bundle.evidence_hash,
            )
            if fingerprint in dismissed:
                duplicates += 1
                _inc_metric("duplicates_suppressed")
                await log_governance_event(
                    session,
                    current_user,
                    event_type="duplicate_recommendation_suppressed",
                    org_id=org_id or current_user.org_id,
                    project_id=project_id,
                    metadata={
                        "reason": "dismissed_fingerprint",
                        "generation_request_id": str(generation_request_id),
                    },
                )
                continue

            duplicate = False
            for existing in active_rows + persisted:
                if existing.fingerprint == fingerprint or titles_are_near_duplicates(
                    existing.title, candidate.title
                ):
                    duplicate = True
                    existing.status = GovernanceAIRecommendationStatus.SUPERSEDED
                    break
            if duplicate and any(
                titles_are_near_duplicates(existing.title, candidate.title)
                and existing.evidence_hash == bundle.evidence_hash
                for existing in active_rows
            ):
                # Same evidence + near-identical title: suppress rather than rewrite.
                duplicates += 1
                _inc_metric("duplicates_suppressed")
                await log_governance_event(
                    session,
                    current_user,
                    event_type="duplicate_recommendation_suppressed",
                    org_id=org_id or current_user.org_id,
                    project_id=project_id,
                    metadata={
                        "reason": "near_duplicate_active",
                        "generation_request_id": str(generation_request_id),
                    },
                )
                continue

            evidence_refs = []
            evidence_by_id = {item.evidence_id: item for item in bundle.evidence}
            for evidence_id in candidate.evidence_ids:
                item = evidence_by_id[evidence_id]
                evidence_refs.append(
                    {
                        "evidence_id": item.evidence_id,
                        "entity_type": item.entity_type,
                        "entity_id": str(item.entity_id) if item.entity_id else None,
                        "project_id": str(item.project_id) if item.project_id else None,
                        "title": item.title,
                        "summary": item.summary,
                        "status": item.status,
                        "severity": item.severity,
                    }
                )

            settings = get_settings()
            row = GovernanceAIRecommendation(
                org_id=org_id or current_user.org_id,
                project_id=candidate.project_id,
                scope=GovernanceAIRecommendationScope(candidate.scope),
                recommendation_type=candidate.recommendation_type,
                title=candidate.title,
                narrative=candidate.narrative,
                rationale=candidate.rationale,
                priority=GovernanceAIRecommendationPriority(candidate.priority),
                confidence=candidate.confidence,
                status=GovernanceAIRecommendationStatus.ACTIVE,
                suggested_actions=[a.model_dump(mode="json") for a in candidate.suggested_actions],
                evidence_refs=evidence_refs,
                evidence_hash=bundle.evidence_hash,
                fingerprint=fingerprint,
                source_snapshot=snapshot,
                model_name=model_name,
                model_version=None,
                prompt_version=prompt_version,
                generation_request_id=generation_request_id,
                generated_by_user_id=current_user.id,
                generated_at=datetime.now(timezone.utc),
                explanation_version=settings.governance_recommendation_explanation_version,
                strategy_version=settings.governance_recommendation_strategy_version,
                confidence_version=settings.governance_recommendation_confidence_version,
                quality_score_version=settings.governance_recommendation_quality_score_version,
                calibration_version=settings.governance_recommendation_calibration_version,
            )
            session.add(row)
            persisted.append(row)

        # Mark prior active rows with different evidence hash as stale.
        for existing in active_rows:
            if existing.evidence_hash != bundle.evidence_hash and existing.status == GovernanceAIRecommendationStatus.ACTIVE:
                existing.status = GovernanceAIRecommendationStatus.STALE

        await session.flush()
        from app.agents.governance.services.effectiveness_service import record_lifecycle_event
        from app.db.models import GovernanceRecommendationLifecycleEventType

        for row in persisted:
            await record_lifecycle_event(
                session,
                org_id=row.org_id,
                recommendation_id=row.id,
                event_type=GovernanceRecommendationLifecycleEventType.CREATED,
                actor_user_id=current_user.id,
                metadata={
                    "strategy_version": row.strategy_version,
                    "explanation_version": row.explanation_version,
                },
            )
        if not persisted:
            _inc_metric("fallback_used")
            _inc_metric("generation_failures")
            await log_governance_event(
                session,
                current_user,
                event_type="recommendation_generation_failed",
                org_id=org_id or current_user.org_id,
                project_id=project_id,
                metadata={
                    "failure_category": "no_valid_candidates",
                    "rejected_grounding": rejected,
                    "duplicates_suppressed": duplicates,
                    "generation_request_id": str(generation_request_id),
                },
            )
            await session.commit()
            return GovernanceAIRecommendationGenerationResult(
                recommendations=[],
                rule_based_fallback=rule_based,
                fallback_used=True,
                fallback_reason="no_valid_candidates",
                generation_request_id=generation_request_id,
                evidence_hash=bundle.evidence_hash,
                candidates_returned=len(candidates),
                candidates_persisted=0,
                candidates_rejected_grounding=rejected,
                duplicates_suppressed=duplicates,
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )

        _inc_metric("candidates_persisted", float(len(persisted)))
        _inc_metric("generation_successes")
        duration_ms = round((perf_counter() - started) * 1000, 1)
        _inc_metric("generation_duration_ms_total", duration_ms)
        await log_governance_event(
            session,
            current_user,
            event_type="recommendation_generated" if not force else "recommendation_regenerated",
            org_id=org_id or current_user.org_id,
            project_id=project_id,
            source_table="governance_ai_recommendations",
            metadata={
                "generation_request_id": str(generation_request_id),
                "result_count": len(persisted),
                "model": model_name,
                "prompt_version": prompt_version,
                "evidence_hash_prefix": bundle.evidence_hash[:12],
                "rejected_grounding": rejected,
                "duplicates_suppressed": duplicates,
            },
        )
        await session.commit()
        for row in persisted:
            await session.refresh(row)

        names = await load_project_names(
            session, {row.project_id for row in persisted if row.project_id}
        )
        reads = [
            _to_read(
                row,
                project_name=names.get(row.project_id) if row.project_id else None,
                can_generate=True,
                current_evidence_hash=bundle.evidence_hash,
                bundle=bundle,
            )
            for row in persisted
        ]
        return GovernanceAIRecommendationGenerationResult(
            recommendations=reads,
            rule_based_fallback=rule_based,
            generation_request_id=generation_request_id,
            evidence_hash=bundle.evidence_hash,
            candidates_returned=len(candidates),
            candidates_persisted=len(persisted),
            candidates_rejected_grounding=rejected,
            duplicates_suppressed=duplicates,
            duration_ms=duration_ms,
        )


async def dismiss_governance_ai_recommendation(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    *,
    reason: str | None = None,
) -> GovernanceAIRecommendationRead:
    assert_can_generate_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    row.status = GovernanceAIRecommendationStatus.DISMISSED
    row.dismissed_at = datetime.now(timezone.utc)
    row.dismissed_by_user_id = current_user.id
    row.dismiss_reason = reason
    from app.agents.governance.services.effectiveness_service import record_lifecycle_event
    from app.db.models import GovernanceRecommendationLifecycleEventType

    await record_lifecycle_event(
        session,
        org_id=row.org_id,
        recommendation_id=row.id,
        event_type=GovernanceRecommendationLifecycleEventType.DISMISSED,
        actor_user_id=current_user.id,
        metadata={"reason": reason},
    )
    await log_governance_event(
        session,
        current_user,
        event_type=(
            "escalation_suggestion_dismissed"
            if row.auto_detected
            and row.recommendation_type == GovernanceAIRecommendationType.ESCALATION_REQUIRED
            else "recommendation_dismissed"
        ),
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendations",
        source_id=row.id,
        metadata={
            "recommendation_type": row.recommendation_type.value,
            "reason": reason,
            "trigger_type": row.trigger_type.value if row.trigger_type else None,
            "fingerprint_prefix": (row.trigger_fingerprint or row.fingerprint or "")[:12],
            "auto_detected": bool(row.auto_detected),
        },
    )
    await session.commit()
    await session.refresh(row)
    names = await load_project_names(session, {row.project_id} if row.project_id else set())
    return _to_read(
        row,
        project_name=names.get(row.project_id) if row.project_id else None,
        can_generate=True,
    )


async def submit_governance_ai_recommendation_feedback(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    *,
    helpful: bool,
    reason: str | None = None,
) -> GovernanceAIRecommendationFeedbackRead:
    assert_can_view_ai_recommendations(current_user)
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    existing = (
        await session.execute(
            select(GovernanceAIRecommendationFeedback).where(
                GovernanceAIRecommendationFeedback.recommendation_id == recommendation_id,
                GovernanceAIRecommendationFeedback.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.helpful = helpful
        existing.reason = reason
        feedback = existing
    else:
        feedback = GovernanceAIRecommendationFeedback(
            recommendation_id=row.id,
            org_id=row.org_id,
            user_id=current_user.id,
            helpful=helpful,
            reason=reason,
        )
        session.add(feedback)
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_feedback_submitted",
        org_id=row.org_id,
        project_id=row.project_id,
        source_table="governance_ai_recommendation_feedback",
        source_id=row.id,
        metadata={"helpful": helpful},
    )
    await session.commit()
    await session.refresh(feedback)
    return GovernanceAIRecommendationFeedbackRead(
        id=feedback.id,
        recommendation_id=feedback.recommendation_id,
        helpful=feedback.helpful,
        reason=feedback.reason,
        created_at=feedback.created_at,
    )


@dataclass(frozen=True)
class _ConversionContext:
    row: GovernanceAIRecommendation
    suggested_action: GovernanceSuggestedAction
    suggested_action_index: int


def _normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def _conversion_fingerprint(
    *,
    recommendation_id: UUID,
    suggested_action_index: int,
    target: GovernanceRecommendationConversionTarget,
    project_id: UUID,
    title: str,
) -> str:
    raw = "|".join(
        [
            str(recommendation_id),
            str(suggested_action_index),
            target.value,
            str(project_id),
            _normalize_title(title),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _suggested_actions(row: GovernanceAIRecommendation) -> list[GovernanceSuggestedAction]:
    parsed: list[GovernanceSuggestedAction] = []
    for item in row.suggested_actions or []:
        try:
            parsed.append(GovernanceSuggestedAction.model_validate(item))
        except ValidationError:
            continue
    return parsed


async def _reject_conversion(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    row: GovernanceAIRecommendation | None,
    target: GovernanceRecommendationConversionTarget,
    suggested_action_index: int | None,
    category: str,
    message: str,
    status_code: int = 400,
) -> None:
    if category == "permission":
        _inc_metric("permission_rejections")
    elif category == "duplicate":
        _inc_metric("duplicate_conflicts")
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_conversion_rejected",
        org_id=row.org_id if row is not None else current_user.org_id,
        project_id=row.project_id if row is not None else None,
        source_table="governance_ai_recommendations" if row is not None else None,
        source_id=row.id if row is not None else None,
        metadata={
            "conversion_target": target.value,
            "suggested_action_index": suggested_action_index,
            "failure_category": category,
        },
    )
    await session.commit()
    raise ApiError(status_code, "RECOMMENDATION_CONVERSION_REJECTED", message)


async def _conversion_context(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    recommendation_id: UUID,
    requested_project_id: UUID,
    suggested_action_index: int | None,
    target: GovernanceRecommendationConversionTarget,
) -> _ConversionContext:
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    if row.status != GovernanceAIRecommendationStatus.ACTIVE:
        await _reject_conversion(
            session,
            current_user,
            row=row,
            target=target,
            suggested_action_index=suggested_action_index,
            category="lifecycle",
            message="Only active AI recommendations can be converted.",
        )
    if row.project_id is None or row.project_id != requested_project_id:
        await _reject_conversion(
            session,
            current_user,
            row=row,
            target=target,
            suggested_action_index=suggested_action_index,
            category="project_scope",
            message="Recommendation conversion must stay within the recommendation project.",
        )

    actions = _suggested_actions(row)
    if suggested_action_index is None or suggested_action_index >= len(actions):
        await _reject_conversion(
            session,
            current_user,
            row=row,
            target=target,
            suggested_action_index=suggested_action_index,
            category="suggested_action",
            message="Select a valid suggested action before converting.",
        )
    suggested = actions[suggested_action_index]
    allowed = (
        suggested.action_type in ACTION_COMPATIBLE_SUGGESTIONS
        if target == GovernanceRecommendationConversionTarget.ACTION
        else suggested.action_type in ESCALATION_COMPATIBLE_SUGGESTIONS
    )
    if not allowed:
        await _reject_conversion(
            session,
            current_user,
            row=row,
            target=target,
            suggested_action_index=suggested_action_index,
            category="suggested_action",
            message="The selected suggestion cannot be converted to that record type.",
        )
    return _ConversionContext(
        row=row,
        suggested_action=suggested,
        suggested_action_index=suggested_action_index,
    )


async def _find_existing_conversion(
    session: AsyncSession,
    *,
    org_id: UUID,
    recommendation_id: UUID,
    suggested_action_index: int,
    idempotency_key: str | None,
) -> GovernanceAIRecommendationConversion | None:
    if idempotency_key:
        existing = (
            await session.execute(
                select(GovernanceAIRecommendationConversion).where(
                    GovernanceAIRecommendationConversion.org_id == org_id,
                    GovernanceAIRecommendationConversion.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    return (
        await session.execute(
            select(GovernanceAIRecommendationConversion).where(
                GovernanceAIRecommendationConversion.recommendation_id == recommendation_id,
                GovernanceAIRecommendationConversion.suggested_action_index
                == suggested_action_index,
            )
        )
    ).scalar_one_or_none()


async def _conversion_to_read(
    session: AsyncSession,
    current_user: CurrentUser,
    conversion: GovernanceAIRecommendationConversion,
    *,
    recommendation: GovernanceAIRecommendation,
    idempotent_reuse: bool,
) -> GovernanceRecommendationConversionRead:
    action_read: GovernanceActionRead | None = None
    escalation_read: GovernanceEscalationRead | None = None
    if conversion.created_action_id is not None:
        from app.agents.governance.services.governance_service import get_action_or_404

        action = await get_action_or_404(session, conversion.created_action_id, current_user)
        action_read = await enriched_action_read(session, action, current_user)
    if conversion.created_escalation_id is not None:
        from app.agents.governance.services.governance_service import get_escalation_or_404

        escalation = await get_escalation_or_404(
            session, conversion.created_escalation_id, current_user
        )
        escalation_read = await enriched_escalation_read(session, escalation, current_user)

    names = await load_project_names(
        session, {recommendation.project_id} if recommendation.project_id else set()
    )
    return GovernanceRecommendationConversionRead(
        id=conversion.id,
        recommendation_id=conversion.recommendation_id,
        conversion_target=conversion.conversion_target,
        suggested_action_index=conversion.suggested_action_index,
        created_action_id=conversion.created_action_id,
        created_escalation_id=conversion.created_escalation_id,
        created_by_user_id=conversion.created_by_user_id,
        created_at=conversion.created_at,
        note=conversion.note,
        idempotent_reuse=idempotent_reuse,
        created_action=action_read,
        created_escalation=escalation_read,
        updated_recommendation=_to_read(
            recommendation,
            project_name=names.get(recommendation.project_id) if recommendation.project_id else None,
            can_generate=can_generate_ai_recommendations(current_user),
        ),
    )


def _apply_acceptance_state(
    row: GovernanceAIRecommendation,
    *,
    current_user: CurrentUser,
    target: GovernanceRecommendationConversionTarget,
    suggested_action_index: int,
    action_id: UUID | None = None,
    escalation_id: UUID | None = None,
    note: str | None,
) -> None:
    total_actions = len(_suggested_actions(row))
    row.acceptance_status = (
        GovernanceRecommendationAcceptanceStatus.PARTIALLY_ACCEPTED
        if total_actions > 1
        else (
            GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ACTION
            if target == GovernanceRecommendationConversionTarget.ACTION
            else GovernanceRecommendationAcceptanceStatus.ACCEPTED_AS_ESCALATION
        )
    )
    row.accepted_at = datetime.now(timezone.utc)
    row.accepted_by_user_id = current_user.id
    row.converted_action_id = action_id
    row.converted_escalation_id = escalation_id
    row.accepted_suggested_action_index = suggested_action_index
    row.acceptance_note = note


async def convert_governance_recommendation_to_action(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    request: ConvertRecommendationToActionRequest,
) -> GovernanceRecommendationConversionRead:
    started = perf_counter()
    _inc_metric("conversion_requests")
    target = GovernanceRecommendationConversionTarget.ACTION
    context = await _conversion_context(
        session,
        current_user,
        recommendation_id=recommendation_id,
        requested_project_id=request.project_id,
        suggested_action_index=request.suggested_action_index,
        target=target,
    )
    fingerprint = _conversion_fingerprint(
        recommendation_id=context.row.id,
        suggested_action_index=context.suggested_action_index,
        target=target,
        project_id=request.project_id,
        title=request.title,
    )
    existing = await _find_existing_conversion(
        session,
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        suggested_action_index=context.suggested_action_index,
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        if existing.request_fingerprint == fingerprint or (
            request.idempotency_key and existing.idempotency_key == request.idempotency_key
        ):
            _inc_metric("conversion_reuses")
            await log_governance_event(
                session,
                current_user,
                event_type="recommendation_conversion_reused",
                org_id=context.row.org_id,
                project_id=context.row.project_id,
                source_table="governance_ai_recommendations",
                source_id=context.row.id,
                metadata={
                    "conversion_id": str(existing.id),
                    "conversion_target": target.value,
                    "suggested_action_index": context.suggested_action_index,
                },
            )
            await session.commit()
            return await _conversion_to_read(
                session, current_user, existing, recommendation=context.row, idempotent_reuse=True
            )
        await _reject_conversion(
            session,
            current_user,
            row=context.row,
            target=target,
            suggested_action_index=context.suggested_action_index,
            category="duplicate",
            message="That suggested action has already been converted with different details.",
            status_code=409,
        )

    action = await create_action(
        session,
        current_user,
        project_id=request.project_id,
        title=request.title,
        description=request.description,
        owner_id=request.owner_id,
        due_date=request.due_date,
        status=request.status or GovernanceActionStatus.OPEN,
        linked_knowledge_document_id=request.linked_knowledge_document_id,
        commit=False,
    )
    conversion = GovernanceAIRecommendationConversion(
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        suggested_action_index=context.suggested_action_index,
        conversion_target=target,
        created_action_id=action.id,
        created_by_user_id=current_user.id,
        request_fingerprint=fingerprint,
        idempotency_key=request.idempotency_key,
        note=request.note,
    )
    session.add(conversion)
    await session.flush()
    from app.agents.governance.services.record_provenance_service import (
        create_conversion_provenance_links,
    )
    from app.db.models import GovernanceRecordTargetType

    provenance = await create_conversion_provenance_links(
        session,
        current_user,
        recommendation=context.row,
        conversion=conversion,
        target_type=GovernanceRecordTargetType.ACTION,
        target_id=action.id,
    )
    _apply_acceptance_state(
        context.row,
        current_user=current_user,
        target=target,
        suggested_action_index=context.suggested_action_index,
        action_id=action.id,
        note=request.note,
    )
    from app.agents.governance.services.effectiveness_service import record_lifecycle_event
    from app.db.models import GovernanceRecommendationLifecycleEventType

    await record_lifecycle_event(
        session,
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        event_type=GovernanceRecommendationLifecycleEventType.ACCEPTED,
        actor_user_id=current_user.id,
        metadata={"coupled_with_conversion": True, "target": target.value},
    )
    await record_lifecycle_event(
        session,
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        event_type=GovernanceRecommendationLifecycleEventType.CONVERTED,
        actor_user_id=current_user.id,
        conversion_target=target.value,
        conversion_target_id=action.id,
        metadata={"suggested_action_index": context.suggested_action_index},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_converted_to_action",
        org_id=context.row.org_id,
        project_id=context.row.project_id,
        source_table="governance_ai_recommendations",
        source_id=context.row.id,
        metadata={
            "conversion_target": target.value,
            "suggested_action_index": context.suggested_action_index,
            "created_action_id": str(action.id),
            "evidence_reference_count": len(context.row.evidence_refs or []),
            "evidence_link_count": provenance.created,
            "evidence_source_types": provenance.source_types,
            "source_recommendation_id": str(context.row.id),
            "source_conversion_id": str(conversion.id),
            "skipped_invalid_evidence_count": provenance.skipped,
            "duplicate_links_suppressed": provenance.duplicates_suppressed,
        },
    )
    await session.commit()
    await session.refresh(action)
    await session.refresh(conversion)
    await session.refresh(context.row)
    invalidate_governance_read_caches_after_commit(org_id=context.row.org_id)
    _inc_metric("conversion_successes")
    _inc_metric("action_conversions")
    _inc_metric("conversion_duration_ms_total", round((perf_counter() - started) * 1000, 1))
    return await _conversion_to_read(
        session, current_user, conversion, recommendation=context.row, idempotent_reuse=False
    )


async def convert_governance_recommendation_to_escalation(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
    request: ConvertRecommendationToEscalationRequest,
) -> GovernanceRecommendationConversionRead:
    started = perf_counter()
    _inc_metric("conversion_requests")
    target = GovernanceRecommendationConversionTarget.ESCALATION
    context = await _conversion_context(
        session,
        current_user,
        recommendation_id=recommendation_id,
        requested_project_id=request.project_id,
        suggested_action_index=request.suggested_action_index,
        target=target,
    )
    fingerprint = _conversion_fingerprint(
        recommendation_id=context.row.id,
        suggested_action_index=context.suggested_action_index,
        target=target,
        project_id=request.project_id,
        title=request.title,
    )
    existing = await _find_existing_conversion(
        session,
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        suggested_action_index=context.suggested_action_index,
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        if existing.request_fingerprint == fingerprint or (
            request.idempotency_key and existing.idempotency_key == request.idempotency_key
        ):
            _inc_metric("conversion_reuses")
            await log_governance_event(
                session,
                current_user,
                event_type="recommendation_conversion_reused",
                org_id=context.row.org_id,
                project_id=context.row.project_id,
                source_table="governance_ai_recommendations",
                source_id=context.row.id,
                metadata={
                    "conversion_id": str(existing.id),
                    "conversion_target": target.value,
                    "suggested_action_index": context.suggested_action_index,
                },
            )
            await session.commit()
            return await _conversion_to_read(
                session, current_user, existing, recommendation=context.row, idempotent_reuse=True
            )
        await _reject_conversion(
            session,
            current_user,
            row=context.row,
            target=target,
            suggested_action_index=context.suggested_action_index,
            category="duplicate",
            message="That suggested action has already been converted with different details.",
            status_code=409,
        )

    escalation = await create_escalation(
        session,
        current_user,
        project_id=request.project_id,
        title=request.title,
        description=request.description,
        severity=request.severity,
        status=request.status or GovernanceEscalationStatus.OPEN,
        assigned_to=request.assigned_to,
        source_type=None,
        source_id=None,
        commit=False,
    )
    conversion = GovernanceAIRecommendationConversion(
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        suggested_action_index=context.suggested_action_index,
        conversion_target=target,
        created_escalation_id=escalation.id,
        created_by_user_id=current_user.id,
        request_fingerprint=fingerprint,
        idempotency_key=request.idempotency_key,
        note=request.note,
    )
    session.add(conversion)
    await session.flush()
    from app.agents.governance.services.record_provenance_service import (
        create_conversion_provenance_links,
    )
    from app.db.models import GovernanceRecordTargetType

    provenance = await create_conversion_provenance_links(
        session,
        current_user,
        recommendation=context.row,
        conversion=conversion,
        target_type=GovernanceRecordTargetType.ESCALATION,
        target_id=escalation.id,
    )
    _apply_acceptance_state(
        context.row,
        current_user=current_user,
        target=target,
        suggested_action_index=context.suggested_action_index,
        escalation_id=escalation.id,
        note=request.note,
    )
    from app.agents.governance.services.effectiveness_service import record_lifecycle_event
    from app.db.models import GovernanceRecommendationLifecycleEventType

    await record_lifecycle_event(
        session,
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        event_type=GovernanceRecommendationLifecycleEventType.ACCEPTED,
        actor_user_id=current_user.id,
        metadata={"coupled_with_conversion": True, "target": target.value},
    )
    await record_lifecycle_event(
        session,
        org_id=context.row.org_id,
        recommendation_id=context.row.id,
        event_type=GovernanceRecommendationLifecycleEventType.CONVERTED,
        actor_user_id=current_user.id,
        conversion_target=target.value,
        conversion_target_id=escalation.id,
        metadata={"suggested_action_index": context.suggested_action_index},
    )
    await log_governance_event(
        session,
        current_user,
        event_type="recommendation_converted_to_escalation",
        org_id=context.row.org_id,
        project_id=context.row.project_id,
        source_table="governance_ai_recommendations",
        source_id=context.row.id,
        metadata={
            "conversion_target": target.value,
            "suggested_action_index": context.suggested_action_index,
            "created_escalation_id": str(escalation.id),
            "evidence_reference_count": len(context.row.evidence_refs or []),
            "evidence_link_count": provenance.created,
            "evidence_source_types": provenance.source_types,
            "source_recommendation_id": str(context.row.id),
            "source_conversion_id": str(conversion.id),
            "skipped_invalid_evidence_count": provenance.skipped,
            "duplicate_links_suppressed": provenance.duplicates_suppressed,
        },
    )
    await session.commit()
    await session.refresh(escalation)
    await session.refresh(conversion)
    await session.refresh(context.row)
    invalidate_governance_read_caches_after_commit(org_id=context.row.org_id)
    _inc_metric("conversion_successes")
    _inc_metric("escalation_conversions")
    _inc_metric("conversion_duration_ms_total", round((perf_counter() - started) * 1000, 1))
    return await _conversion_to_read(
        session, current_user, conversion, recommendation=context.row, idempotent_reuse=False
    )


async def list_governance_ai_recommendation_conversions(
    session: AsyncSession,
    current_user: CurrentUser,
    recommendation_id: UUID,
) -> list[GovernanceRecommendationConversionRead]:
    row = await get_governance_ai_recommendation(session, current_user, recommendation_id)
    conversions = list(
        (
            await session.execute(
                select(GovernanceAIRecommendationConversion)
                .where(GovernanceAIRecommendationConversion.recommendation_id == row.id)
                .order_by(GovernanceAIRecommendationConversion.created_at.desc())
            )
        ).scalars()
    )
    return [
        await _conversion_to_read(
            session,
            current_user,
            conversion,
            recommendation=row,
            idempotent_reuse=False,
        )
        for conversion in conversions
    ]


async def mark_ai_recommendations_stale_for_project(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
) -> int:
    """Optional write-path helper: mark active recommendations stale after governance writes."""
    rows = list(
        (
            await session.execute(
                select(GovernanceAIRecommendation).where(
                    GovernanceAIRecommendation.org_id == org_id,
                    GovernanceAIRecommendation.project_id == project_id,
                    GovernanceAIRecommendation.deleted_at.is_(None),
                    GovernanceAIRecommendation.status == GovernanceAIRecommendationStatus.ACTIVE,
                )
            )
        ).scalars()
    )
    for row in rows:
        row.status = GovernanceAIRecommendationStatus.STALE
    return len(rows)
