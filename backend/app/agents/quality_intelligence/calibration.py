from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.comms_prompts import CALIBRATION_SYSTEM_PROMPT
from app.agents.quality_intelligence.oka_client import OKAClient
from app.agents.quality_intelligence.signals import emit_inter_agent_signal
from app.core.config import get_settings
from app.db.models import (
    Annotator,
    AppRole,
    Notification,
    NotificationType,
    Project,
    ReviewerScorecard,
    SignalType,
    User,
)
from app.schemas.domain import CalibrationBriefRead, CalibrationCandidateRead
from app.services.llm.client import LLMClient
from app.services.quality_thresholds import load_thresholds

MIN_REVIEWER_ITEMS = 50


@dataclass(frozen=True)
class CalibrationCandidate:
    annotator_id: str
    accuracy_pct: float | None
    items_evaluated: int
    error_breakdown: dict[str, Any] | None
    error_category: str | None
    reason: str


async def identify_calibration_candidates(
    session: AsyncSession,
    project_id: UUID,
    *,
    iso_year: int,
    iso_week: int,
    accuracy_threshold: float | None = None,
) -> list[CalibrationCandidate]:
    thresholds = await load_thresholds(session)
    acc_cfg = thresholds.get("gold_set_accuracy")
    threshold = accuracy_threshold
    if threshold is None and acc_cfg and acc_cfg.amber_min is not None:
        threshold = float(acc_cfg.amber_min)
    threshold = threshold or 85.0

    scorecards = list(
        (
            await session.execute(
                select(ReviewerScorecard).where(
                    ReviewerScorecard.project_id == project_id,
                    ReviewerScorecard.iso_year == iso_year,
                    ReviewerScorecard.iso_week == iso_week,
                    ReviewerScorecard.items_evaluated >= MIN_REVIEWER_ITEMS,
                )
            )
        ).scalars()
    )

    candidates: list[CalibrationCandidate] = []
    for card in scorecards:
        acc = float(card.accuracy_pct) if card.accuracy_pct is not None else None
        if acc is not None and acc < threshold:
            dominant_cat = None
            if card.error_breakdown:
                dominant_cat = max(card.error_breakdown, key=lambda k: card.error_breakdown.get(k, 0))
            candidates.append(
                CalibrationCandidate(
                    annotator_id=str(card.annotator_id),
                    accuracy_pct=acc,
                    items_evaluated=card.items_evaluated,
                    error_breakdown=card.error_breakdown,
                    error_category=dominant_cat,
                    reason=f"Accuracy {acc:.1f}% below threshold {threshold}%",
                )
            )
    return candidates


# Backward-compatible alias
find_calibration_candidates = identify_calibration_candidates


async def generate_calibration_brief(
    session: AsyncSession,
    project: Project,
    candidates: list[CalibrationCandidate],
    *,
    iso_year: int,
    iso_week: int,
) -> CalibrationBriefRead:
    candidate_reads = [
        CalibrationCandidateRead(
            annotator_id=UUID(c.annotator_id),
            accuracy_pct=c.accuracy_pct,
            items_evaluated=c.items_evaluated,
            error_category=c.error_category,
            priority="immediate" if c.accuracy_pct is not None and c.accuracy_pct < 80 else "this_week",
            reason=c.reason,
        )
        for c in candidates
    ]

    brief_text = None
    if candidates:
        context = "\n".join(
            f"Reviewer {c.annotator_id}: accuracy {c.accuracy_pct}%, items {c.items_evaluated}, "
            f"dominant error {c.error_category or 'unknown'}"
            for c in candidates
        )
        settings = get_settings()
        if settings.llm_api_key:
            try:
                llm = LLMClient()
                brief_text = await llm.generate_structured(
                    system=CALIBRATION_SYSTEM_PROMPT,
                    user=f"Draft calibration brief for project '{project.name}' week W{iso_week}/{iso_year}.",
                    context=context,
                )
            except Exception:
                pass
        if not brief_text:
            brief_text = (
                f"{len(candidates)} reviewer(s) require calibration for W{iso_week}/{iso_year}. "
                "Schedule targeted sessions on dominant error categories."
            )

    return CalibrationBriefRead(
        project_id=project.id,
        iso_year=iso_year,
        iso_week=iso_week,
        candidates=candidate_reads,
        brief_text=brief_text,
    )


async def emit_skill_gap_signal(
    session: AsyncSession,
    project: Project,
    candidates: list[CalibrationCandidate],
) -> Any:
    if not candidates:
        return None

    payload = {
        "signal_type": "skill_gap",
        "reviewer_ids": [c.annotator_id for c in candidates],
        "project_id": str(project.id),
        "task_type": None,
        "error_category": candidates[0].error_category,
        "recommendation": "calibration",
        "urgency": "immediate" if any(c.accuracy_pct and c.accuracy_pct < 80 for c in candidates) else "this_week",
    }
    return await emit_inter_agent_signal(
        session,
        signal_type=SignalType.SKILL_GAP,
        target_agent="workforce_agent",
        payload=payload,
        project_id=project.id,
        org_id=project.org_id,
    )


async def notify_qa_lead_calibration(
    session: AsyncSession,
    org_id: UUID,
    project: Project,
    brief: CalibrationBriefRead,
    *,
    source_row_id: UUID | None = None,
) -> list[Notification]:
    if source_row_id:
        existing = (
            await session.execute(
                select(Notification).where(
                    Notification.org_id == org_id,
                    Notification.notification_type == NotificationType.CALIBRATION_REQUIRED,
                    Notification.source_table == "projects",
                    Notification.source_row_id == source_row_id,
                )
            )
        ).scalars()
        if list(existing):
            return []

    dm_users = (
        await session.execute(
            select(User).where(
                User.org_id == org_id,
                User.role == AppRole.DELIVERY_MANAGER,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
    ).scalars()

    notifications: list[Notification] = []
    body = brief.brief_text or f"{len(brief.candidates)} reviewer(s) flagged for calibration."
    for user in dm_users:
        note = Notification(
            user_id=user.id,
            org_id=org_id,
            notification_type=NotificationType.CALIBRATION_REQUIRED,
            title=f"Calibration required — {project.name}",
            body=body,
            source_table="projects",
            source_row_id=source_row_id or project.id,
        )
        session.add(note)
        notifications.append(note)
    await session.flush()
    return notifications


async def process_calibration_for_snapshot(
    session: AsyncSession,
    project: Project,
    *,
    iso_year: int,
    iso_week: int,
) -> CalibrationBriefRead | None:
    candidates = await identify_calibration_candidates(
        session, project.id, iso_year=iso_year, iso_week=iso_week
    )
    if not candidates:
        return None

    brief = await generate_calibration_brief(session, project, candidates, iso_year=iso_year, iso_week=iso_week)
    await emit_skill_gap_signal(session, project, candidates)
    await notify_qa_lead_calibration(session, project.org_id, project, brief, source_row_id=project.id)
    brief = CalibrationBriefRead(
        **brief.model_dump(),
        signal_sent_at=datetime.now(timezone.utc),
    )
    return brief
