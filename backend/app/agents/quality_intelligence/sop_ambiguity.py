"""UC-04: SOP ambiguity detection and update trigger."""

from __future__ import annotations

from datetime import date, timedelta

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.comms_prompts import SOP_AMBIGUITY_PROMPT
from app.agents.quality_intelligence.sop_workflow import SopAmbiguityFlag, detect_sop_ambiguity
from app.core.config import get_settings
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    IaaMeasurementRecord,
    Notification,
    NotificationType,
    Project,
    QualitySnapshot,
    QualitySopLink,
    RiskAlert,
    SopVersionHistory,
    User,
)
from app.db.optional_tables import query_optional_table
from app.schemas.domain import SopAmbiguityFlagRead
from app.services.llm.client import LLMClient

IAA_LOW_THRESHOLD = 0.80
MIN_LOW_PAIRS = 3


async def _dominant_task_type_from_iaa(
    session: AsyncSession,
    snapshot: QualitySnapshot,
) -> str | None:
    records = list(
        (
            await session.execute(
                select(IaaMeasurementRecord).where(
                    IaaMeasurementRecord.project_id == snapshot.project_id,
                    IaaMeasurementRecord.iso_year == snapshot.iso_year,
                    IaaMeasurementRecord.iso_week == snapshot.iso_week,
                )
            )
        ).scalars()
    )
    low = [
        r for r in records
        if r.krippendorff_alpha is not None and float(r.krippendorff_alpha) < IAA_LOW_THRESHOLD
    ]
    if not low:
        return None
    counts: dict[str, int] = {}
    for row in low:
        if row.task_type:
            counts[row.task_type] = counts.get(row.task_type, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


async def detect_distributed_iaa_drop(session: AsyncSession, snapshot: QualitySnapshot) -> bool:
    flag = await detect_sop_ambiguity(session, snapshot)
    return flag.detected and flag.affected_reviewers >= MIN_LOW_PAIRS


async def correlate_sop_change(
    session: AsyncSession,
    org_id,
    *,
    iso_year: int,
    iso_week: int,
    reference_date: date | None = None,
) -> SopVersionHistory | None:
    ref = reference_date or date.today()
    window_start = ref - timedelta(days=14)

    async def _query() -> SopVersionHistory | None:
        return (
            await session.execute(
                select(SopVersionHistory)
                .where(
                    SopVersionHistory.org_id == org_id,
                    SopVersionHistory.effective_date >= window_start,
                    SopVersionHistory.effective_date <= ref,
                )
                .order_by(SopVersionHistory.effective_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    return await query_optional_table(session, _query, None)


async def draft_sop_amendment(
    session: AsyncSession,
    project: Project,
    sop_version: SopVersionHistory | None,
    flag: SopAmbiguityFlag,
) -> str:
    context = (
        f"SOP version: {sop_version.version if sop_version else 'unknown'}\n"
        f"Change: {sop_version.change_summary if sop_version else 'n/a'}\n"
        f"Affected reviewer pairs: {flag.affected_reviewers}\n"
        f"Detail: {flag.detail}"
    )
    settings = get_settings()
    if settings.llm_api_key:
        try:
            llm = LLMClient()
            return await llm.generate_structured(
                system=SOP_AMBIGUITY_PROMPT,
                user=f"Draft SOP amendment recommendation for project '{project.name}'.",
                context=context,
            )
        except Exception:
            pass
    return (
        f"Recommend clarifying SOP {sop_version.version if sop_version else ''} with worked examples "
        f"for divergent decisions affecting {flag.affected_reviewers} reviewer pair(s)."
    )


async def flag_sop_ambiguity(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    sop_version: SopVersionHistory | None,
    flag: SopAmbiguityFlag,
    draft_amendment: str,
    *,
    task_type: str | None = None,
) -> RiskAlert | None:
    if not flag.detected:
        return None

    existing = (
        await session.execute(
            select(RiskAlert).where(
                RiskAlert.project_id == snapshot.project_id,
                RiskAlert.deleted_at.is_(None),
                RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                RiskAlert.title.like("SOP ambiguity flag%"),
                RiskAlert.source_table == "quality_snapshots",
                RiskAlert.source_row_id == snapshot.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    from app.db.models import RiskTier

    alert = RiskAlert(
        project_id=snapshot.project_id,
        org_id=snapshot.org_id,
        alert_type=AlertType.QUALITY_DRIFT,
        risk_tier=RiskTier.MEDIUM,
        title=f"SOP ambiguity flag — W{snapshot.iso_week}",
        detail=flag.detail or "Distributed IAA drop detected",
        contributing_causes={
            "sop_ambiguity_flag": {
                "task_type": task_type,
                "affected_reviewer_count": flag.affected_reviewers,
                "sop_version": sop_version.version if sop_version else flag.sop_version,
                "draft_amendment": draft_amendment,
            }
        },
        status=AlertStatus.OPEN,
        source_table="quality_snapshots",
        source_row_id=snapshot.id,
    )
    session.add(alert)
    await session.flush()
    return alert


async def notify_sop_ambiguity(
    session: AsyncSession,
    org_id,
    alert: RiskAlert,
) -> list[Notification]:
    existing = (
        await session.execute(
            select(Notification).where(
                Notification.org_id == org_id,
                Notification.notification_type == NotificationType.SOP_AMBIGUITY_FLAGGED,
                Notification.source_table == "risk_alerts",
                Notification.source_row_id == alert.id,
            )
        )
    ).scalars()
    if list(existing):
        return []

    users = (
        await session.execute(
            select(User).where(
                User.org_id == org_id,
                User.role == AppRole.DELIVERY_MANAGER,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
    ).scalars()

    notes: list[Notification] = []
    for user in users:
        note = Notification(
            user_id=user.id,
            org_id=org_id,
            notification_type=NotificationType.SOP_AMBIGUITY_FLAGGED,
            title=alert.title,
            body=alert.detail,
            source_table="risk_alerts",
            source_row_id=alert.id,
        )
        session.add(note)
        notes.append(note)
    await session.flush()
    return notes


async def process_sop_ambiguity_for_snapshot(
    session: AsyncSession,
    project: Project,
    snapshot: QualitySnapshot,
) -> SopAmbiguityFlagRead | None:
    flag = await detect_sop_ambiguity(session, snapshot)
    if not flag.detected:
        return None

    sop_version = await correlate_sop_change(
        session, snapshot.org_id, iso_year=snapshot.iso_year, iso_week=snapshot.iso_week
    )
    task_type = await _dominant_task_type_from_iaa(session, snapshot)
    amendment = await draft_sop_amendment(session, project, sop_version, flag)
    alert = await flag_sop_ambiguity(
        session, snapshot, sop_version, flag, amendment, task_type=task_type
    )
    if alert:
        await notify_sop_ambiguity(session, snapshot.org_id, alert)

    return SopAmbiguityFlagRead(
        alert_id=alert.id if alert else None,
        task_type=task_type,
        affected_reviewer_count=flag.affected_reviewers,
        sop_version=sop_version.version if sop_version else flag.sop_version,
        draft_amendment=amendment,
        detail=flag.detail,
    )


async def list_sop_ambiguity_flags(session: AsyncSession, project_id) -> list[SopAmbiguityFlagRead]:
    alerts = list(
        (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project_id,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
            )
        ).scalars()
    )
    flags: list[SopAmbiguityFlagRead] = []
    for alert in alerts:
        payload = (alert.contributing_causes or {}).get("sop_ambiguity_flag")
        if not payload:
            continue
        flags.append(
            SopAmbiguityFlagRead(
                alert_id=alert.id,
                task_type=payload.get("task_type"),
                affected_reviewer_count=payload.get("affected_reviewer_count", 0),
                sop_version=payload.get("sop_version"),
                draft_amendment=payload.get("draft_amendment"),
                detail=alert.detail,
            )
        )
    return flags


async def confirm_sop_ambiguity_resolution(
    session: AsyncSession,
    project: Project,
    *,
    alert_id,
    sop_version_id,
    confirmed_by,
) -> QualitySopLink:
    """Link a resolved SOP version to the triggering quality alert (BR-09 audit trail)."""
    alert = (
        await session.execute(select(RiskAlert).where(RiskAlert.id == alert_id))
    ).scalar_one_or_none()
    if alert is None or alert.project_id != project.id:
        from app.core.exceptions import ApiError
        raise ApiError(404, "NOT_FOUND", "Risk alert was not found.")

    sop_version = (
        await session.execute(
            select(SopVersionHistory).where(
                SopVersionHistory.id == sop_version_id,
                SopVersionHistory.org_id == project.org_id,
            )
        )
    ).scalar_one_or_none()
    if sop_version is None:
        from app.core.exceptions import ApiError
        raise ApiError(404, "NOT_FOUND", "SOP version was not found.")

    existing = (
        await session.execute(
            select(QualitySopLink).where(
                QualitySopLink.risk_alert_id == alert.id,
                QualitySopLink.sop_version_id == sop_version.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    link = QualitySopLink(
        org_id=project.org_id,
        risk_alert_id=alert.id,
        sop_version_id=sop_version.id,
        confirmed_by=confirmed_by,
    )
    session.add(link)
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    await session.flush()
    return link
