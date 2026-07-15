"""Phase 8: provenance links from AI-created actions/escalations to recommendations and evidence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.governance.schemas.governance import (
    GovernanceRecordEvidenceLinkRead,
    GovernanceSourceRecommendationRead,
)
from app.agents.governance.services.governance_service import (
    can_read_internal_governance,
    load_project_names,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    GovernanceAction,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationConversion,
    GovernanceEscalation,
    GovernanceRecordEvidenceLink,
    GovernanceRecordEvidenceSourceType,
    GovernanceRecordLinkType,
    GovernanceRecordTargetType,
    ProjectDependency,
    ProjectScopeState,
)
from app.services.scoping import get_visible_project

logger = logging.getLogger(__name__)

MAX_SUPPORTING_EVIDENCE_LINKS = 10

ENTITY_TYPE_TO_SOURCE: dict[str, GovernanceRecordEvidenceSourceType] = {
    "project": GovernanceRecordEvidenceSourceType.PROJECT,
    "dependency": GovernanceRecordEvidenceSourceType.DEPENDENCY,
    "escalation": GovernanceRecordEvidenceSourceType.ESCALATION,
    "action": GovernanceRecordEvidenceSourceType.ACTION,
    "scope_state": GovernanceRecordEvidenceSourceType.SCOPE_STATE,
    "delivery_signal": GovernanceRecordEvidenceSourceType.DELIVERY_SIGNAL,
    "milestone": GovernanceRecordEvidenceSourceType.MILESTONE,
    "trend": GovernanceRecordEvidenceSourceType.TREND,
    "governance_metric": GovernanceRecordEvidenceSourceType.GOVERNANCE_METRIC,
    "recent_activity": GovernanceRecordEvidenceSourceType.RECENT_ACTIVITY,
}

ENTITY_TYPE_TO_RELATED_LINK: dict[str, GovernanceRecordLinkType] = {
    "dependency": GovernanceRecordLinkType.RELATED_DEPENDENCY,
    "escalation": GovernanceRecordLinkType.RELATED_ESCALATION,
    "action": GovernanceRecordLinkType.RELATED_ACTION,
    "scope_state": GovernanceRecordLinkType.RELATED_SCOPE_STATE,
    "delivery_signal": GovernanceRecordLinkType.RELATED_DELIVERY_SIGNAL,
}

_METRICS: dict[str, float] = {
    "evidence_links_created": 0,
    "evidence_links_skipped": 0,
    "evidence_links_duplicate_suppressed": 0,
    "evidence_link_creation_ms_total": 0,
    "evidence_endpoint_requests": 0,
    "evidence_endpoint_latency_ms_total": 0,
    "unavailable_sources": 0,
    "permission_filtered_sources": 0,
}


def _inc(name: str, value: float = 1.0) -> None:
    _METRICS[name] = _METRICS.get(name, 0.0) + value


def get_provenance_metrics() -> dict[str, float]:
    return dict(_METRICS)


@dataclass(frozen=True)
class ProvenanceLinkResult:
    created: int
    skipped: int
    duplicates_suppressed: int
    source_types: list[str]


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _source_exists(
    session: AsyncSession,
    *,
    org_id: UUID,
    source_type: GovernanceRecordEvidenceSourceType,
    source_id: UUID | None,
    project_id: UUID | None,
) -> bool:
    if source_type == GovernanceRecordEvidenceSourceType.AI_RECOMMENDATION:
        if source_id is None:
            return False
        row = (
            await session.execute(
                select(GovernanceAIRecommendation.id).where(
                    GovernanceAIRecommendation.id == source_id,
                    GovernanceAIRecommendation.org_id == org_id,
                    GovernanceAIRecommendation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return row is not None

    if source_type == GovernanceRecordEvidenceSourceType.DEPENDENCY and source_id:
        row = (
            await session.execute(
                select(ProjectDependency.id).where(
                    ProjectDependency.id == source_id,
                    ProjectDependency.org_id == org_id,
                    ProjectDependency.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return row is not None

    if source_type == GovernanceRecordEvidenceSourceType.ESCALATION and source_id:
        row = (
            await session.execute(
                select(GovernanceEscalation.id).where(
                    GovernanceEscalation.id == source_id,
                    GovernanceEscalation.org_id == org_id,
                    GovernanceEscalation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return row is not None

    if source_type == GovernanceRecordEvidenceSourceType.ACTION and source_id:
        row = (
            await session.execute(
                select(GovernanceAction.id).where(
                    GovernanceAction.id == source_id,
                    GovernanceAction.org_id == org_id,
                    GovernanceAction.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return row is not None

    if source_type == GovernanceRecordEvidenceSourceType.SCOPE_STATE and source_id:
        row = (
            await session.execute(
                select(ProjectScopeState.id).where(
                    ProjectScopeState.id == source_id,
                    ProjectScopeState.org_id == org_id,
                    ProjectScopeState.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return row is not None

    # Soft entities (delivery_signal / trend / project / metrics) may only have project_id.
    if source_type in {
        GovernanceRecordEvidenceSourceType.DELIVERY_SIGNAL,
        GovernanceRecordEvidenceSourceType.TREND,
        GovernanceRecordEvidenceSourceType.MILESTONE,
        GovernanceRecordEvidenceSourceType.PROJECT,
        GovernanceRecordEvidenceSourceType.GOVERNANCE_METRIC,
        GovernanceRecordEvidenceSourceType.RECENT_ACTIVITY,
    }:
        return project_id is not None or source_id is not None

    return False


async def create_conversion_provenance_links(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    recommendation: GovernanceAIRecommendation,
    conversion: GovernanceAIRecommendationConversion,
    target_type: GovernanceRecordTargetType,
    target_id: UUID,
) -> ProvenanceLinkResult:
    """Create source + supporting evidence links inside the open conversion transaction."""
    started = perf_counter()
    created = 0
    skipped = 0
    duplicates = 0
    source_types: set[str] = set()

    existing_source = (
        await session.execute(
            select(GovernanceRecordEvidenceLink.id).where(
                GovernanceRecordEvidenceLink.org_id == recommendation.org_id,
                GovernanceRecordEvidenceLink.target_type == target_type,
                GovernanceRecordEvidenceLink.target_id == target_id,
                GovernanceRecordEvidenceLink.link_type
                == GovernanceRecordLinkType.AI_RECOMMENDATION_SOURCE,
                GovernanceRecordEvidenceLink.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_source is not None:
        # Idempotent reuse / backfill-safe: do not duplicate provenance.
        _inc("evidence_links_duplicate_suppressed", 1)
        return ProvenanceLinkResult(
            created=0,
            skipped=0,
            duplicates_suppressed=1,
            source_types=[GovernanceRecordEvidenceSourceType.AI_RECOMMENDATION.value],
        )

    # Always create the source recommendation link.
    source_link = GovernanceRecordEvidenceLink(
        org_id=recommendation.org_id,
        target_type=target_type,
        target_id=target_id,
        source_type=GovernanceRecordEvidenceSourceType.AI_RECOMMENDATION,
        source_id=recommendation.id,
        recommendation_id=recommendation.id,
        conversion_id=conversion.id,
        evidence_id=None,
        link_type=GovernanceRecordLinkType.AI_RECOMMENDATION_SOURCE,
        title=recommendation.title,
        description=None,
        status_snapshot=recommendation.status.value,
        severity_snapshot=recommendation.priority.value,
        project_id=recommendation.project_id,
        occurred_at=recommendation.generated_at,
        metadata_json={
            "prompt_version": recommendation.prompt_version,
            "evidence_hash_prefix": (recommendation.evidence_hash or "")[:12],
            "conversion_id": str(conversion.id),
        },
        created_by_user_id=current_user.id,
    )
    session.add(source_link)
    created += 1
    source_types.add(GovernanceRecordEvidenceSourceType.AI_RECOMMENDATION.value)

    converted_link = GovernanceRecordEvidenceLink(
        org_id=recommendation.org_id,
        target_type=target_type,
        target_id=target_id,
        source_type=GovernanceRecordEvidenceSourceType.AI_RECOMMENDATION,
        source_id=recommendation.id,
        recommendation_id=recommendation.id,
        conversion_id=conversion.id,
        evidence_id=None,
        link_type=GovernanceRecordLinkType.CONVERTED_FROM,
        title=recommendation.title,
        description="Converted from AI Governance recommendation",
        status_snapshot=recommendation.status.value,
        severity_snapshot=recommendation.priority.value,
        project_id=recommendation.project_id,
        occurred_at=recommendation.generated_at,
        metadata_json={"conversion_id": str(conversion.id)},
        created_by_user_id=current_user.id,
    )
    session.add(converted_link)
    created += 1

    seen_keys: set[tuple[str, str | None, str | None]] = set()
    refs = list(recommendation.evidence_refs or [])
    for ref in refs:
        if created - 2 >= MAX_SUPPORTING_EVIDENCE_LINKS:
            skipped += len(refs) - (created - 2)
            break
        if not isinstance(ref, dict):
            skipped += 1
            _inc("evidence_links_skipped")
            continue

        entity_type = str(ref.get("entity_type") or "")
        source_type = ENTITY_TYPE_TO_SOURCE.get(entity_type)
        if source_type is None:
            skipped += 1
            _inc("evidence_links_skipped")
            continue

        evidence_id = str(ref.get("evidence_id") or "") or None
        source_id = _parse_uuid(ref.get("entity_id"))
        project_id = _parse_uuid(ref.get("project_id")) or recommendation.project_id
        key = (source_type.value, str(source_id) if source_id else None, evidence_id)
        if key in seen_keys:
            duplicates += 1
            _inc("evidence_links_duplicate_suppressed")
            continue
        seen_keys.add(key)

        if project_id is not None:
            try:
                await get_visible_project(session, project_id, current_user)
            except ApiError:
                skipped += 1
                _inc("evidence_links_skipped")
                _inc("permission_filtered_sources")
                continue

        exists = await _source_exists(
            session,
            org_id=recommendation.org_id,
            source_type=source_type,
            source_id=source_id,
            project_id=project_id,
        )
        if not exists and source_id is not None:
            # Keep historical snapshot link even if live row is gone? Spec says
            # retain historical links for later reads, but at creation time skip
            # clearly invalid/unknown org entities.
            skipped += 1
            _inc("evidence_links_skipped")
            continue

        link_type = ENTITY_TYPE_TO_RELATED_LINK.get(
            entity_type, GovernanceRecordLinkType.SUPPORTING_EVIDENCE
        )
        session.add(
            GovernanceRecordEvidenceLink(
                org_id=recommendation.org_id,
                target_type=target_type,
                target_id=target_id,
                source_type=source_type,
                source_id=source_id,
                recommendation_id=recommendation.id,
                conversion_id=conversion.id,
                evidence_id=evidence_id,
                link_type=link_type,
                title=str(ref.get("title") or "")[:500] or None,
                description=str(ref.get("summary") or "")[:800] or None,
                status_snapshot=str(ref.get("status")) if ref.get("status") is not None else None,
                severity_snapshot=(
                    str(ref.get("severity")) if ref.get("severity") is not None else None
                ),
                project_id=project_id,
                occurred_at=None,
                metadata_json={"from_evidence_ref": True},
                created_by_user_id=current_user.id,
            )
        )
        created += 1
        source_types.add(source_type.value)

    await session.flush()
    _inc("evidence_links_created", float(created))
    _inc("evidence_link_creation_ms_total", round((perf_counter() - started) * 1000, 1))
    return ProvenanceLinkResult(
        created=created,
        skipped=skipped,
        duplicates_suppressed=duplicates,
        source_types=sorted(source_types),
    )


async def _assert_can_view_provenance(current_user: CurrentUser) -> None:
    if not can_read_internal_governance(current_user):
        raise ApiError(403, "FORBIDDEN", "Provenance is available to internal roles only.")


async def count_record_evidence_links(
    session: AsyncSession,
    *,
    org_id: UUID,
    target_type: GovernanceRecordTargetType,
    target_id: UUID,
) -> int:
    rows = (
        await session.execute(
            select(GovernanceRecordEvidenceLink.id).where(
                GovernanceRecordEvidenceLink.org_id == org_id,
                GovernanceRecordEvidenceLink.target_type == target_type,
                GovernanceRecordEvidenceLink.target_id == target_id,
                GovernanceRecordEvidenceLink.deleted_at.is_(None),
            )
        )
    ).all()
    return len(rows)


async def get_source_recommendation_summary(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    target_type: GovernanceRecordTargetType,
    target_id: UUID,
    org_id: UUID,
) -> GovernanceSourceRecommendationRead | None:
    await _assert_can_view_provenance(current_user)
    link = (
        await session.execute(
            select(GovernanceRecordEvidenceLink).where(
                GovernanceRecordEvidenceLink.org_id == org_id,
                GovernanceRecordEvidenceLink.target_type == target_type,
                GovernanceRecordEvidenceLink.target_id == target_id,
                GovernanceRecordEvidenceLink.link_type
                == GovernanceRecordLinkType.AI_RECOMMENDATION_SOURCE,
                GovernanceRecordEvidenceLink.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if link is None or link.recommendation_id is None:
        return None

    recommendation = (
        await session.execute(
            select(GovernanceAIRecommendation).where(
                GovernanceAIRecommendation.id == link.recommendation_id,
                GovernanceAIRecommendation.org_id == org_id,
                GovernanceAIRecommendation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if recommendation is None:
        _inc("unavailable_sources")
        return GovernanceSourceRecommendationRead(
            id=link.recommendation_id,
            title=link.title or "Source recommendation unavailable",
            recommendation_type=None,
            priority=None,
            confidence=None,
            generated_at=link.occurred_at or link.created_at,
            status=None,
            accepted_at=None,
            source_type="ai_recommendation",
            can_view=False,
            source_available=False,
        )

    if recommendation.project_id is not None:
        try:
            await get_visible_project(session, recommendation.project_id, current_user)
        except ApiError:
            _inc("permission_filtered_sources")
            return GovernanceSourceRecommendationRead(
                id=recommendation.id,
                title="Source unavailable",
                recommendation_type=None,
                priority=None,
                confidence=None,
                generated_at=recommendation.generated_at,
                status=None,
                accepted_at=None,
                source_type="ai_recommendation",
                can_view=False,
                source_available=False,
            )

    return GovernanceSourceRecommendationRead(
        id=recommendation.id,
        title=recommendation.title,
        recommendation_type=recommendation.recommendation_type.value,
        priority=recommendation.priority.value,
        confidence=float(recommendation.confidence),
        generated_at=recommendation.generated_at,
        status=recommendation.status.value,
        accepted_at=recommendation.accepted_at,
        source_type="ai_recommendation",
        can_view=True,
        source_available=True,
    )


async def list_record_evidence_links(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    target_type: GovernanceRecordTargetType,
    target_id: UUID,
    org_id: UUID,
) -> list[GovernanceRecordEvidenceLinkRead]:
    started = perf_counter()
    _inc("evidence_endpoint_requests")
    await _assert_can_view_provenance(current_user)

    links = list(
        (
            await session.execute(
                select(GovernanceRecordEvidenceLink)
                .where(
                    GovernanceRecordEvidenceLink.org_id == org_id,
                    GovernanceRecordEvidenceLink.target_type == target_type,
                    GovernanceRecordEvidenceLink.target_id == target_id,
                    GovernanceRecordEvidenceLink.deleted_at.is_(None),
                )
                .order_by(GovernanceRecordEvidenceLink.created_at.asc())
            )
        ).scalars()
    )
    project_ids = {link.project_id for link in links if link.project_id}
    names = await load_project_names(session, project_ids)
    visible_projects: set[UUID] = set()
    for project_id in project_ids:
        try:
            await get_visible_project(session, project_id, current_user)
            visible_projects.add(project_id)
        except ApiError:
            _inc("permission_filtered_sources")

    reads: list[GovernanceRecordEvidenceLinkRead] = []
    for link in links:
        can_view = link.project_id is None or link.project_id in visible_projects
        source_available = can_view
        if not can_view:
            pass
        elif (
            link.source_type != GovernanceRecordEvidenceSourceType.AI_RECOMMENDATION
            and link.source_id is not None
        ):
            source_available = await _source_exists(
                session,
                org_id=org_id,
                source_type=link.source_type,
                source_id=link.source_id,
                project_id=link.project_id,
            )
            if not source_available:
                _inc("unavailable_sources")

        reads.append(
            GovernanceRecordEvidenceLinkRead(
                id=link.id,
                link_type=link.link_type,
                source_type=link.source_type,
                source_id=link.source_id,
                evidence_id=link.evidence_id,
                recommendation_id=link.recommendation_id,
                conversion_id=link.conversion_id,
                title=link.title if can_view else "Source unavailable",
                description=link.description if can_view else None,
                status=link.status_snapshot if can_view else None,
                severity=link.severity_snapshot if can_view else None,
                project_id=link.project_id,
                project_name=names.get(link.project_id) if link.project_id and can_view else None,
                occurred_at=link.occurred_at,
                created_at=link.created_at,
                source_available=source_available and can_view,
                can_view_source=can_view and source_available,
            )
        )

    _inc("evidence_endpoint_latency_ms_total", round((perf_counter() - started) * 1000, 1))
    return reads


async def provenance_summary_for_target(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    target_type: GovernanceRecordTargetType,
    target_id: UUID,
    org_id: UUID,
) -> dict[str, Any]:
    """Lightweight provenance fields for action/escalation detail reads."""
    if not can_read_internal_governance(current_user):
        return {
            "provenance_source_type": "manual",
            "source_recommendation_id": None,
            "source_recommendation_title": None,
            "source_conversion_id": None,
            "evidence_link_count": 0,
            "has_ai_source": False,
        }

    source_link = (
        await session.execute(
            select(GovernanceRecordEvidenceLink).where(
                GovernanceRecordEvidenceLink.org_id == org_id,
                GovernanceRecordEvidenceLink.target_type == target_type,
                GovernanceRecordEvidenceLink.target_id == target_id,
                GovernanceRecordEvidenceLink.link_type
                == GovernanceRecordLinkType.AI_RECOMMENDATION_SOURCE,
                GovernanceRecordEvidenceLink.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    count = await count_record_evidence_links(
        session, org_id=org_id, target_type=target_type, target_id=target_id
    )
    if source_link is None:
        return {
            "provenance_source_type": "manual",
            "source_recommendation_id": None,
            "source_recommendation_title": None,
            "source_conversion_id": None,
            "evidence_link_count": count,
            "has_ai_source": False,
        }

    title: str | None = source_link.title
    can_view_title = True
    if source_link.project_id is not None:
        try:
            await get_visible_project(session, source_link.project_id, current_user)
        except ApiError:
            can_view_title = False
            title = None
            _inc("permission_filtered_sources")

    return {
        "provenance_source_type": "ai_recommendation",
        "source_recommendation_id": source_link.recommendation_id or source_link.source_id,
        "source_recommendation_title": title if can_view_title else None,
        "source_conversion_id": source_link.conversion_id,
        "evidence_link_count": count,
        "has_ai_source": True,
    }
