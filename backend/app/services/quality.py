from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.alerts import create_drift_risk_alert, notify_quality_drift
from app.agents.quality_intelligence.calibration import (
    generate_calibration_brief,
    identify_calibration_candidates,
    process_calibration_for_snapshot,
)
from app.agents.quality_intelligence.drift import DriftResult, evaluate_drift  # noqa: F401 – re-exported
from app.agents.quality_intelligence.oka_client import OKAClient
from app.agents.quality_intelligence.root_cause import analyze_root_cause, root_cause_to_json
from app.agents.quality_intelligence.sop_ambiguity import list_sop_ambiguity_flags, process_sop_ambiguity_for_snapshot
from app.agents.knowledge.lesson_log import write_lesson_on_alert_resolve
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    GoldSetMetadata,
    IaaMeasurementRecord,
    InterAgentSignal,
    OnboardingRecord,
    Organisation,
    Project,
    ProjectStatus,
    QualityErrorEntry,
    QualityScanRun,
    QualitySnapshot,
    ReviewerScorecard,
    RiskAlert,
    RiskTier,
    ScanStatus,
    ScanTrigger,
    SopVersionHistory,
    Team,
)
from app.schemas.domain import (
    AdminProjectRead,
    CalibrationBriefRead,
    GoldSetMetadataCreate,
    GoldSetMetadataRead,
    IaaMeasurementCreate,
    IaaMeasurementRead,
    InterAgentSignalRead,
    OnboardingRecordCreate,
    OnboardingRecordRead,
    QualityDashboardKpis,
    QualityDashboardRead,
    QualityDriftEvent,
    QualityErrorBreakdown,
    QualityPortfolioProjectRead,
    QualityPortfolioRead,
    QualitySnapshotCreate,
    QualitySummaryRead,
    QualityTeamScorecard,
    QualityTrendPoint,
    ReviewerScorecardCreate,
    ReviewerScorecardRead,
    RiskAlertRead,
    SopAmbiguityFlagRead,
    SopVersionCreate,
    SopVersionRead,
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

    project = (
        await session.execute(select(Project).where(Project.id == snapshot.project_id))
    ).scalar_one_or_none()
    if project:
        await process_calibration_for_snapshot(
            session, project, iso_year=snapshot.iso_year, iso_week=snapshot.iso_week
        )
        await process_sop_ambiguity_for_snapshot(session, project, snapshot)

    await session.flush()
    return drift


async def load_snapshot_with_errors(session: AsyncSession, snapshot_id: UUID) -> QualitySnapshot | None:
    return (
        await session.execute(select(QualitySnapshot).where(QualitySnapshot.id == snapshot_id))
    ).scalar_one_or_none()


async def scan_all_projects(
    session: AsyncSession,
    *,
    trigger: str = ScanTrigger.SCHEDULER,
    triggered_by: UUID | None = None,
) -> QualityScanRun:
    """Evaluate latest quality snapshots for all active projects.

    Persists a quality_scan_runs row for admin observability.
    """
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()

    run = QualityScanRun(
        trigger=trigger,
        triggered_by=triggered_by,
        iso_year=iso_year,
        iso_week=iso_week,
        status=ScanStatus.RUNNING,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    per_project_results: list[dict] = []
    totals = {"snapshots": 0, "alerts": 0, "data_gaps": 0}

    try:
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

        for project in projects:
            project_result = {
                "project_id": str(project.id),
                "name": project.name,
                "snapshots": 0,
                "alerts": 0,
                "data_gaps": 0,
                "teams": [],
            }

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
                project_result["snapshots"] += 1
                drift_result = await evaluate_snapshot(session, snapshot)
                team_entry = {
                    "team_id": str(snapshot.team_id),
                    "has_drift": drift_result.has_drift,
                    "data_gap": drift_result.data_gap,
                    "detail": drift_result.detail or drift_result.data_gap_message,
                }
                project_result["teams"].append(team_entry)

                if drift_result.data_gap:
                    totals["data_gaps"] += 1
                    project_result["data_gaps"] += 1
                    logger.info(
                        "Data gap for project=%s team=%s week=%s/%s: %s",
                        project.id,
                        snapshot.team_id,
                        iso_year,
                        iso_week,
                        drift_result.data_gap_message,
                    )
                elif drift_result.has_drift:
                    totals["alerts"] += 1
                    project_result["alerts"] += 1

            per_project_results.append(project_result)

        run.projects_scanned = len(projects)
        run.snapshots_evaluated = totals["snapshots"]
        run.alerts_created = totals["alerts"]
        run.data_gaps = totals["data_gaps"]
        run.per_project_results = per_project_results
        run.status = ScanStatus.COMPLETED
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(run)
        logger.info(
            "Quality scan complete run_id=%s projects=%s snapshots=%s alerts=%s data_gaps=%s",
            run.id,
            run.projects_scanned,
            run.snapshots_evaluated,
            run.alerts_created,
            run.data_gaps,
        )
        return run
    except Exception as exc:
        run.status = ScanStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = str(exc)
        run.per_project_results = per_project_results or None
        await session.commit()
        await session.refresh(run)
        logger.exception("Quality scan failed run_id=%s", run.id)
        raise


async def list_quality_scan_runs(session: AsyncSession, *, limit: int = 50) -> list[QualityScanRun]:
    return list(
        (
            await session.execute(
                select(QualityScanRun).order_by(QualityScanRun.started_at.desc()).limit(limit)
            )
        ).scalars()
    )


async def list_admin_projects(session: AsyncSession) -> list[AdminProjectRead]:
    """Cross-org project list with quality posture for super-admin."""
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()

    projects = list(
        (
            await session.execute(
                select(Project, Organisation)
                .join(Organisation, Project.org_id == Organisation.id)
                .where(Project.deleted_at.is_(None))
                .order_by(Project.name)
            )
        ).all()
    )

    teams_by_project: dict[UUID, dict[UUID, Team]] = {}
    all_teams = list((await session.execute(select(Team))).scalars())
    for team in all_teams:
        teams_by_project.setdefault(team.project_id, {})[team.id] = team

    results: list[AdminProjectRead] = []
    for project, org in projects:
        snapshots = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(QualitySnapshot.project_id == project.id)
                    .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                )
            ).scalars()
        )

        latest_by_team: dict[UUID, QualitySnapshot] = {}
        for snap in snapshots:
            if snap.team_id not in latest_by_team:
                latest_by_team[snap.team_id] = snap

        latest_week_snaps = [
            s for s in latest_by_team.values() if s.iso_year == iso_year and s.iso_week == iso_week
        ]
        project_teams = teams_by_project.get(project.id, {})
        data_gap_teams = [
            project_teams[snap.team_id].name if snap.team_id in project_teams else str(snap.team_id)
            for snap in latest_week_snaps
            if snap.evaluated_item_count is not None and snap.evaluated_item_count < MIN_EVALUATED_ITEMS
        ]

        drift_count = (
            await session.execute(
                select(RiskAlert).where(
                    RiskAlert.project_id == project.id,
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
            )
        ).scalars()
        active_drift = len(list(drift_count))

        latest_iso_year = snapshots[0].iso_year if snapshots else None
        latest_iso_week = snapshots[0].iso_week if snapshots else None

        results.append(
            AdminProjectRead(
                id=project.id,
                name=project.name,
                org_id=project.org_id,
                org_name=org.name,
                status=project.status,
                vertical=project.vertical,
                start_date=project.start_date,
                target_end_date=project.target_end_date,
                latest_iso_year=latest_iso_year,
                latest_iso_week=latest_iso_week,
                active_drift_alerts=active_drift,
                data_gap_teams=data_gap_teams,
            )
        )
    return results


async def get_leadership_quality_portfolio(session: AsyncSession) -> QualityPortfolioRead:
    """Portfolio-level quality aggregation for leadership (UC-07 stub)."""
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()

    admin_projects = await list_admin_projects(session)
    per_project: list[QualityPortfolioProjectRead] = []
    gold_values: list = []
    rework_values: list = []
    projects_with_drift = 0

    for ap in admin_projects:
        snapshots = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(
                        QualitySnapshot.project_id == ap.id,
                        QualitySnapshot.iso_year == iso_year,
                        QualitySnapshot.iso_week == iso_week,
                    )
                )
            ).scalars()
        )

        latest_gold = None
        if snapshots:
            accs = [s.gold_set_accuracy_pct for s in snapshots if s.gold_set_accuracy_pct is not None]
            if accs:
                latest_gold = str(round(sum(accs) / len(accs), 2))
                gold_values.extend(accs)
            reworks = [s.rework_rate_pct for s in snapshots if s.rework_rate_pct is not None]
            rework_values.extend(reworks)

        has_data_gap = len(ap.data_gap_teams) > 0
        if ap.active_drift_alerts > 0:
            projects_with_drift += 1
            proj_status = "critical" if ap.active_drift_alerts >= 2 else "at_risk"
        elif not snapshots:
            proj_status = "no_data"
        else:
            proj_status = "on_track"

        per_project.append(
            QualityPortfolioProjectRead(
                project_id=ap.id,
                name=ap.name,
                org_name=ap.org_name,
                status=proj_status,
                active_drift_alerts=ap.active_drift_alerts,
                latest_gold_accuracy=latest_gold,
                data_gap=has_data_gap,
            )
        )

    blended_gold = str(round(sum(gold_values) / len(gold_values), 2)) if gold_values else None
    blended_rework = str(round(sum(rework_values) / len(rework_values), 2)) if rework_values else None

    return QualityPortfolioRead(
        portfolio_week=f"W{iso_week}/{iso_year}",
        projects_total=len(admin_projects),
        projects_with_drift=projects_with_drift,
        blended_gold_accuracy=blended_gold,
        blended_rework_rate=blended_rework,
        per_project=per_project,
    )


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


async def get_calibration_brief_for_project(
    session: AsyncSession,
    project: Project,
    *,
    iso_year: int,
    iso_week: int,
) -> CalibrationBriefRead:
    candidates = await identify_calibration_candidates(
        session, project.id, iso_year=iso_year, iso_week=iso_week
    )
    return await generate_calibration_brief(session, project, candidates, iso_year=iso_year, iso_week=iso_week)


async def create_reviewer_scorecard(
    session: AsyncSession,
    project: Project,
    payload: ReviewerScorecardCreate,
) -> ReviewerScorecard:
    existing = (
        await session.execute(
            select(ReviewerScorecard).where(
                ReviewerScorecard.annotator_id == payload.annotator_id,
                ReviewerScorecard.project_id == project.id,
                ReviewerScorecard.iso_year == payload.iso_year,
                ReviewerScorecard.iso_week == payload.iso_week,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.items_evaluated = payload.items_evaluated
        existing.accuracy_pct = payload.accuracy_pct
        existing.error_breakdown = payload.error_breakdown
        await session.flush()
        return existing

    card = ReviewerScorecard(
        annotator_id=payload.annotator_id,
        project_id=project.id,
        org_id=project.org_id,
        iso_year=payload.iso_year,
        iso_week=payload.iso_week,
        items_evaluated=payload.items_evaluated,
        accuracy_pct=payload.accuracy_pct,
        error_breakdown=payload.error_breakdown,
    )
    session.add(card)
    await session.flush()
    return card


async def list_reviewer_scorecards(
    session: AsyncSession,
    project_id: UUID,
    *,
    iso_year: int | None = None,
    iso_week: int | None = None,
) -> list[ReviewerScorecard]:
    query = select(ReviewerScorecard).where(ReviewerScorecard.project_id == project_id)
    if iso_year is not None:
        query = query.where(ReviewerScorecard.iso_year == iso_year)
    if iso_week is not None:
        query = query.where(ReviewerScorecard.iso_week == iso_week)
    return list((await session.execute(query.order_by(ReviewerScorecard.iso_week.desc()))).scalars())


async def create_iaa_measurement(
    session: AsyncSession,
    project: Project,
    payload: IaaMeasurementCreate,
) -> IaaMeasurementRecord:
    row = IaaMeasurementRecord(
        project_id=project.id,
        org_id=project.org_id,
        team_id=payload.team_id,
        reviewer_a_id=payload.reviewer_a_id,
        reviewer_b_id=payload.reviewer_b_id,
        task_type=payload.task_type,
        krippendorff_alpha=payload.krippendorff_alpha,
        iso_year=payload.iso_year,
        iso_week=payload.iso_week,
    )
    session.add(row)
    await session.flush()
    return row


async def create_sop_version(
    session: AsyncSession,
    project: Project,
    payload: SopVersionCreate,
) -> SopVersionHistory:
    row = SopVersionHistory(
        sop_document_id=payload.sop_document_id,
        org_id=project.org_id,
        version=payload.version,
        change_summary=payload.change_summary,
        effective_date=payload.effective_date,
    )
    session.add(row)
    await session.flush()
    return row


async def upsert_gold_set_metadata(
    session: AsyncSession,
    project: Project,
    payload: GoldSetMetadataCreate,
) -> GoldSetMetadata:
    row = GoldSetMetadata(
        project_id=project.id,
        org_id=project.org_id,
        version=payload.version,
        item_count=payload.item_count,
        last_updated=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def create_onboarding_record(
    session: AsyncSession,
    project: Project,
    payload: OnboardingRecordCreate,
) -> OnboardingRecord:
    row = OnboardingRecord(
        annotator_id=payload.annotator_id,
        org_id=project.org_id,
        onboarding_date=payload.onboarding_date,
        calibration_status=payload.calibration_status,
        notes=payload.notes,
    )
    session.add(row)
    await session.flush()
    return row


async def list_inter_agent_signals(session: AsyncSession, *, limit: int = 50) -> list[InterAgentSignal]:
    return list(
        (
            await session.execute(
                select(InterAgentSignal).order_by(InterAgentSignal.created_at.desc()).limit(limit)
            )
        ).scalars()
    )


async def write_quality_lesson(
    session: AsyncSession,
    alert: RiskAlert,
    *,
    created_by: UUID,
    resolution_summary: str | None = None,
) -> None:
    """BR-08: write lesson on resolve via local knowledge store + optional OKA."""
    oka = OKAClient()
    summary = resolution_summary or alert.detail
    await oka.write_lesson(
        event_id=str(alert.id),
        summary=summary,
        source_table="risk_alerts",
        org_id=str(alert.org_id),
    )
    await write_lesson_on_alert_resolve(
        session, alert, created_by=created_by, resolution_summary=resolution_summary
    )


async def resolve_risk_alert(
    session: AsyncSession,
    alert: RiskAlert,
    *,
    resolved_by: UUID,
    resolution_summary: str | None = None,
) -> RiskAlert:
    if alert.status in {AlertStatus.RESOLVED, AlertStatus.DISMISSED}:
        return alert
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolved_by = resolved_by
    await write_quality_lesson(session, alert, created_by=resolved_by, resolution_summary=resolution_summary)
    await session.flush()
    return alert


async def get_sop_ambiguity_flags(session: AsyncSession, project_id: UUID) -> list[SopAmbiguityFlagRead]:
    return await list_sop_ambiguity_flags(session, project_id)
