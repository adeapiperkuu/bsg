"""Idempotent backfill of Phase 8 provenance links for existing Phase 7 conversions.

Usage (from backend/ with venv active):

  python -m scripts.backfill_governance_record_provenance --dry-run
  python -m scripts.backfill_governance_record_provenance

Creates source recommendation + supporting evidence links for conversions that do not
already have an ai_recommendation_source link. Safe to re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    GovernanceAIRecommendation,
    GovernanceAIRecommendationConversion,
    GovernanceRecordEvidenceLink,
    GovernanceRecordLinkType,
    GovernanceRecordTargetType,
    User,
)
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _conversions_missing_source(
    session: AsyncSession,
) -> list[GovernanceAIRecommendationConversion]:
    linked_ids = select(GovernanceRecordEvidenceLink.conversion_id).where(
        GovernanceRecordEvidenceLink.link_type == GovernanceRecordLinkType.AI_RECOMMENDATION_SOURCE,
        GovernanceRecordEvidenceLink.deleted_at.is_(None),
        GovernanceRecordEvidenceLink.conversion_id.is_not(None),
    )
    rows = (
        await session.execute(
            select(GovernanceAIRecommendationConversion).where(
                GovernanceAIRecommendationConversion.id.not_in(linked_ids)
            )
        )
    ).scalars()
    return list(rows)


async def _actor_for_conversion(
    session: AsyncSession, conversion: GovernanceAIRecommendationConversion
) -> CurrentUser:
    user_id = conversion.created_by_user_id
    if user_id is None:
        return CurrentUser(
            id=UUID(int=0),
            org_id=conversion.org_id,
            email="backfill@system",
            role=AppRole.SUPER_ADMIN,
            is_active=True,
        )
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        return CurrentUser(
            id=user_id,
            org_id=conversion.org_id,
            email="backfill@system",
            role=AppRole.SUPER_ADMIN,
            is_active=True,
        )
    return CurrentUser(
        id=user.id,
        org_id=user.org_id or conversion.org_id,
        email=user.email,
        role=user.role,
        is_active=bool(user.is_active),
    )


async def backfill(*, dry_run: bool) -> dict[str, int]:
    from app.agents.governance.services.record_provenance_service import (
        create_conversion_provenance_links,
    )

    stats = {
        "conversions_scanned": 0,
        "links_created": 0,
        "skipped": 0,
        "errors": 0,
        "duplicates_suppressed": 0,
    }
    async with AsyncSessionLocal() as session:
        conversions = await _conversions_missing_source(session)
        stats["conversions_scanned"] = len(conversions)
        for conversion in conversions:
            recommendation = (
                await session.execute(
                    select(GovernanceAIRecommendation).where(
                        GovernanceAIRecommendation.id == conversion.recommendation_id,
                        GovernanceAIRecommendation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if recommendation is None:
                stats["skipped"] += 1
                continue

            if conversion.created_action_id:
                target_type = GovernanceRecordTargetType.ACTION
                target_id = conversion.created_action_id
            elif conversion.created_escalation_id:
                target_type = GovernanceRecordTargetType.ESCALATION
                target_id = conversion.created_escalation_id
            else:
                stats["skipped"] += 1
                continue

            if dry_run:
                stats["links_created"] += 2  # source + converted_from at minimum
                continue

            try:
                actor = await _actor_for_conversion(session, conversion)
                result = await create_conversion_provenance_links(
                    session,
                    actor,
                    recommendation=recommendation,
                    conversion=conversion,
                    target_type=target_type,
                    target_id=target_id,
                )
                stats["links_created"] += result.created
                stats["skipped"] += result.skipped
                stats["duplicates_suppressed"] += result.duplicates_suppressed
                await session.commit()
            except Exception:
                await session.rollback()
                stats["errors"] += 1
                logger.exception("Backfill failed for conversion %s", conversion.id)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    stats = asyncio.run(backfill(dry_run=args.dry_run))
    logger.info("Backfill complete: %s", stats)
    print(stats)


if __name__ == "__main__":
    main()
