from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.alerts import create_drift_risk_alert, notify_quality_drift
from app.agents.quality_intelligence.drift import DriftResult, evaluate_drift  # noqa: F401 – re-exported
from app.agents.quality_intelligence.root_cause import analyze_root_cause, root_cause_to_json
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    Project,
    ProjectStatus,
    QualityErrorEntry,
    QualitySnapshot,
    RiskAlert,
    RiskTier,
    Team,
)
from app.schemas.domain import (
    QualityDashboardKpis,
    QualityDashboardRead,
    QualityDriftEvent,
    QualityErrorBreakdown,
    QualitySnapshotCreate,
    QualitySummaryRead,
    QualityTeamScorecard,
    QualityTrendPoint,
    RiskAlertRead,
)
from app.services.quality_scoping import filter_dashboard_for_role, team_status_label

logger = logging.getLogger(__name__)

MIN_EVALUATED_ITEMS = 30


async def upsert_quality_snapshot(
    session: AsyncSession,
    project: Project,
    team: Team,
    payload: QualitySnapshotCreate,
) -> QualitySnapshot:
    existing = (
        await session.execute(
            select(QualitySnapshot).where(
                QualitySnapshot.project_id == project.id,
                QualitySnapshot.team_id == team.id,
                QualitySnapshot.iso_year == payload.iso_year,
                QualitySnapshot.iso_week == payload.iso_week,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        snapshot = QualitySnapshot(
            project_id=project.id,
            team_id=team.id,
            org_id=project.org_id,
            iso_year=payload.iso_year,
            iso_week=payload.iso_week,
            gold_set_accuracy_pct=payload.gold_set_accuracy_pct,
            iaa_krippendorff_alpha=payload.iaa_krippendorff_alpha,
            rework_rate_pct=payload.rework_rate_pct,
            evaluated_item_count=payload.evaluated_item_count,
        )
        session.add(snapshot)
        await session.flush()
    else:
        snapshot = existing
        snapshot.gold_set_accuracy_pct = payload.gold_set_accuracy_pct
        snapshot.iaa_krippendorff_alpha = payload.iaa_krippendorff_alpha
        snapshot.rework_rate_pct = payload.rework_rate_pct
        snapshot.evaluated_item_count = payload.evaluated_item_count
        await session.flush()
        await session.execute(
            QualityErrorEntry.__table__.delete().where(
                QualityErrorEntry.quality_snapshot_id == snapshot.id
            )
        )

    for entry in payload.error_entries:
        session.add(
            QualityErrorEntry(
                quality_snapshot_id=snapshot.id,
                org_id=project.org_id,
                **entry.model_dump(),
            )
        )
    await session.flush()
    return snapshot


async def evaluate_snapshot(session: AsyncSession, snapshot: QualitySnapshot) -> DriftResult:
    drift = await evaluate_drift(session, snapshot)

    if drift.data_gap:
        snapshot.has_drift_alert = False
        snapshot.drift_alert_detail = drift.data_gap_message
        snapshot.root_cause = None
        snapshot.confidence_level = None
        await session.flush()
        return drift

    root_cause = await analyze_root_cause(session, snapshot)
    snapshot.root_cause = root_cause_to_json(root_cause)
    snapshot.confidence_level = root_cause.confidence

    if drift.has_drift:
        snapshot.has_drift_alert = True
        top_action = root_cause.recommended_actions[0]["action"] if root_cause.recommended_actions else None
        snapshot.drift_alert_detail = drift.detail
        if top_action:
            snapshot.drift_alert_detail = f"{drift.detail}. Recommended: {top_action}"

        alert = await create_drift_risk_alert(session, snapshot, drift, root_cause=root_cause)
        if alert:
            await notify_quality_drift(session, snapshot.org_id, alert, snapshot)

        if root_cause.recommended_actions:
            entries = (
                await session.execute(
                    select(QualityErrorEntry).where(
                        QualityErrorEntry.quality_snapshot_id == snapshot.id
                    )
                )
            ).scalars()
            top_rec = root_cause.recommended_actions[0]["action"]
            for entry in entries:
                if not entry.recommended_action:
                    entry.recommended_action = top_rec
    else:
        snapshot.has_drift_alert = False
        snapshot.drift_alert_detail = None

    await session.flush()
    return drift


async def load_snapshot_with_errors(session: AsyncSession, snapshot_id: UUID) -> QualitySnapshot | None:
    return (
        await session.execute(select(QualitySnapshot).where(QualitySnapshot.id == snapshot_id))
    ).scalar_one_or_none()


async def scan_all_projects(session: AsyncSession) -> dict[str, int]:
    """Evaluate latest quality snapshots for all active projects.

    Called by the scheduler and /internal/quality-scan endpoint.
    Returns a summary of projects scanned, alerts created, and data gaps found.
    """
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()

    projects = list(
        (
            await session.execute(
                select(Project).where(
                    Project.deleted_at.is_(None),
                    Project.status == ProjectStatus.ACTIVE,
                )
            )
        ).scalars()
    )

    totals = {"projects": len(projects), "snapshots": 0, "alerts": 0, "data_gaps": 0}

    for project in projects:
        latest_snaps = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(
                        QualitySnapshot.project_id == project.id,
                        QualitySnapshot.iso_year == iso_year,
                        QualitySnapshot.iso_week == iso_week,
                    )
                    .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                )
            ).scalars()
        )

        for snapshot in latest_snaps:
            totals["snapshots"] += 1
            drift_result = await evaluate_snapshot(session, snapshot)
            if drift_result.data_gap:
                totals["data_gaps"] += 1
                logger.info(
                    "Data gap for project=%s team=%s week=%s/%s: %s",
                    project.id, snapshot.team_id, iso_year, iso_week, drift_result.data_gap_message,
                )
            elif drift_result.has_drift:
                totals["alerts"] += 1

    await session.commit()
    logger.info("Quality scan complete: %s", totals)
    return totals


async def build_quality_dashboard(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> QualityDashboardRead:
    snapshots = list(
        (
            await session.execute(
                select(QualitySnapshot)
                .where(QualitySnapshot.project_id == project.id)
                .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
            )
        ).scalars()
    )

    teams = {
        t.id: t
        for t in (
            await session.execute(select(Team).where(Team.project_id == project.id))
        ).scalars()
    }

    latest_by_team: dict[UUID, QualitySnapshot] = {}
    for snap in snapshots:
        if snap.team_id not in latest_by_team:
            latest_by_team[snap.team_id] = snap

    latest_week_snaps = list(latest_by_team.values())
    active_drift = sum(1 for s in latest_week_snaps if s.has_drift_alert)

    data_gap_teams = [
        teams[snap.team_id].name if snap.team_id in teams else str(snap.team_id)
        for snap in latest_week_snaps
        if snap.evaluated_item_count is not None and snap.evaluated_item_count < MIN_EVALUATED_ITEMS
    ]

    def avg_metric(getter):
        values = [getter(s) for s in latest_week_snaps if getter(s) is not None]
        if not values:
            return None
        return sum(values) / len(values)

    kpis = QualityDashboardKpis(
        gold_set_accuracy_pct=avg_metric(lambda s: s.gold_set_accuracy_pct),
        iaa_krippendorff_alpha=avg_metric(lambda s: s.iaa_krippendorff_alpha),
        rework_rate_pct=avg_metric(lambda s: s.rework_rate_pct),
        active_drift_alerts=active_drift,
    )

    trend_snaps = sorted(snapshots, key=lambda s: (s.iso_year, s.iso_week))[-6:]
    trend = [
        QualityTrendPoint(
            iso_year=s.iso_year,
            iso_week=s.iso_week,
            gold_set_accuracy_pct=s.gold_set_accuracy_pct,
            iaa_krippendorff_alpha=s.iaa_krippendorff_alpha,
        )
        for s in trend_snaps
    ]

    error_breakdown: list[QualityErrorBreakdown] = []
    if snapshots:
        current = snapshots[0]
        entries = (
            await session.execute(
                select(QualityErrorEntry).where(QualityErrorEntry.quality_snapshot_id == current.id)
            )
        ).scalars()
        error_breakdown = [
            QualityErrorBreakdown(error_category=e.error_category, share_pct=e.share_pct)
            for e in entries
        ]

    team_scorecard: list[QualityTeamScorecard] = []
    for team_id, snap in latest_by_team.items():
        team = teams.get(team_id)
        team_scorecard.append(
            QualityTeamScorecard(
                team_id=team_id,
                team_name=team.name if team else str(team_id),
                gold_set_accuracy_pct=snap.gold_set_accuracy_pct,
                iaa_krippendorff_alpha=snap.iaa_krippendorff_alpha,
                rework_rate_pct=snap.rework_rate_pct,
                status=team_status_label(snap),
                has_drift_alert=snap.has_drift_alert,
            )
        )

    drift_alerts = list(
        (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project.id,
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(RiskAlert.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )

    narrative = None
    if current_user.role == AppRole.CLIENT and snapshots:
        latest = snapshots[0]
        status = "on track" if not latest.has_drift_alert else "at risk"
        acc = latest.gold_set_accuracy_pct
        narrative = (
            f"Overall quality posture is {status} with blended gold-set accuracy at {acc}% "
            f"for the latest reporting week."
        )

    dashboard = QualityDashboardRead(
        kpis=kpis,
        trend=trend,
        error_breakdown=error_breakdown,
        team_scorecard=team_scorecard,
        drift_alerts=[RiskAlertRead.model_validate(a) for a in drift_alerts],
        narrative=narrative,
        data_gap_teams=data_gap_teams,
    )
    return filter_dashboard_for_role(dashboard, current_user.role)


def _overall_status(drift_alerts: list[RiskAlert]) -> str:
    if any(a.risk_tier == RiskTier.CRITICAL for a in drift_alerts):
        return "critical"
    if any(a.risk_tier in {RiskTier.HIGH, RiskTier.MEDIUM} for a in drift_alerts):
        return "at_risk"
    return "on_track"


def _confidence_from_alerts(drift_alerts: list[RiskAlert], snapshots: list[QualitySnapshot]) -> str:
    if not snapshots:
        return "low"
    levels = [s.confidence_level for s in snapshots if s.confidence_level]
    if not levels:
        return "low"
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


async def generate_quality_summary(
    session: AsyncSession,
    project: Project,
    iso_year: int,
    iso_week: int,
    current_user: CurrentUser,
) -> QualitySummaryRead:
    """Generate a §8.4-compliant quality summary for the given project/week."""
    snapshots = list(
        (
            await session.execute(
                select(QualitySnapshot).where(
                    QualitySnapshot.project_id == project.id,
                    QualitySnapshot.iso_year == iso_year,
                    QualitySnapshot.iso_week == iso_week,
                )
            )
        ).scalars()
    )

    drift_alerts = list(
        (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project.id,
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                )
                .order_by(RiskAlert.created_at.desc())
                .limit(20)
            )
        ).scalars()
    )

    period_alerts = [
        a for a in drift_alerts
        if a.status in {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED}
    ]

    def blended(getter):
        vals = [getter(s) for s in snapshots if getter(s) is not None]
        if not vals:
            return None
        return str(round(sum(vals) / len(vals), 2))

    gold_acc = blended(lambda s: s.gold_set_accuracy_pct)
    iaa = blended(lambda s: s.iaa_krippendorff_alpha)
    rework = blended(lambda s: s.rework_rate_pct)

    overall_status = _overall_status(period_alerts)
    confidence = _confidence_from_alerts(period_alerts, snapshots)

    teams = {
        t.id: t
        for t in (await session.execute(select(Team).where(Team.project_id == project.id))).scalars()
    }

    drift_events = [
        QualityDriftEvent(
            team=teams[a.source_row_id].name if a.source_row_id and a.source_row_id in teams else a.title,
            week=iso_week,
            status=a.status.value,
            resolution_summary=None,
        )
        for a in period_alerts
    ]

    status_word = {"on_track": "on track", "at_risk": "at risk", "critical": "critical"}.get(overall_status, "on track")
    narrative = (
        f"Quality posture for week {iso_week} is {status_word}. "
        f"Blended gold-set accuracy: {gold_acc or 'N/A'}%. "
        f"Rework rate: {rework or 'N/A'}%."
    )

    summary = QualitySummaryRead(
        period=f"W{iso_week}",
        project_id=project.id,
        overall_status=overall_status,
        gold_set_accuracy_blended=gold_acc,
        rework_rate=rework,
        rework_rate_target="4.0",
        iaa_score=iaa,
        drift_events_this_period=drift_events,
        client_narrative=narrative,
        confidence=confidence,
    )

    if current_user.role == AppRole.CLIENT:
        return QualitySummaryRead(
            period=summary.period,
            project_id=summary.project_id,
            overall_status=summary.overall_status,
            gold_set_accuracy_blended=None,
            rework_rate=None,
            rework_rate_target=summary.rework_rate_target,
            iaa_score=None,
            drift_events_this_period=[],
            client_narrative=summary.client_narrative,
            confidence=summary.confidence,
        )
    return summary
