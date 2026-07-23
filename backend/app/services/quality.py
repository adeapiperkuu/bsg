from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

from app.agents.quality_intelligence.alerts import create_drift_risk_alert, notify_quality_drift
from app.agents.quality_intelligence.calibration import (
    build_template_calibration_brief,
    get_cached_calibration_brief,
    identify_calibration_candidates,
    process_calibration_for_snapshot,
)
from app.agents.quality_intelligence.drift import DriftResult, evaluate_drift  # noqa: F401 – re-exported
from app.agents.quality_intelligence.evidence_pack import build_evidence_pack
from app.agents.quality_intelligence.oka_client import OKAClient
from app.agents.quality_intelligence.reasoning import reason_root_cause
from app.agents.quality_intelligence.rework_metrics import compute_rework_impact
from app.agents.quality_intelligence.root_cause import extract_signals, root_cause_to_json
from app.agents.quality_intelligence.sop_ambiguity import (
    confirm_sop_ambiguity_resolution,
    list_sop_ambiguity_flags,
    process_sop_ambiguity_for_snapshot,
    sop_ambiguity_flags_from_alerts,
)
from app.agents.knowledge.lesson_log import write_lesson_on_alert_resolve
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    GoldSetEvaluationLog,
    GoldSetMetadata,
    IaaMeasurementRecord,
    InterAgentSignal,
    OnboardingRecord,
    Organisation,
    Program,
    Project,
    ProjectStatus,
    QualityErrorEntry,
    QualityScanRun,
    QualitySnapshot,
    QualitySopLink,
    ReviewerScorecard,
    ReworkLog,
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
    GoldSetEvaluationLogCreate,
    GoldSetEvaluationLogRead,
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
    QualityPageRead,
    QualityPortfolioProjectRead,
    QualityPortfolioRead,
    QualitySnapshotCreate,
    QualitySummaryRead,
    QualityTeamScorecard,
    QualityTrendPoint,
    ReviewerScorecardCreate,
    ReviewerScorecardRead,
    RiskAlertRead,
    ReworkLogCreate,
    ReworkLogRead,
    SopAmbiguityConfirm,
    SopAmbiguityFlagRead,
    SopVersionCreate,
    SopVersionRead,
    QualitySopLinkRead,
)
from app.services.quality_scoping import filter_dashboard_for_role, team_status_label
from app.services.quality_thresholds import load_thresholds

logger = logging.getLogger(__name__)

MIN_EVALUATED_ITEMS = 30


class QualityScanExecutionError(Exception):
    """A scan failed after its audit row was safely persisted."""

    def __init__(self, run: QualityScanRun) -> None:
        self.run = run
        super().__init__(run.error_message or "Quality scan failed.")


def _quality_page_step_start(project_id: UUID, step: str) -> float:
    wall = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    logger.info("quality_page START project_id=%s step=%s at=%s", project_id, step, wall)
    return perf_counter()


def _quality_page_step_end(project_id: UUID, step: str, started: float, **extra: object) -> None:
    elapsed_ms = (perf_counter() - started) * 1000
    suffix = " ".join(f"{key}={value}" for key, value in extra.items())
    logger.info(
        "quality_page END project_id=%s step=%s elapsed_ms=%.1f %s",
        project_id,
        step,
        elapsed_ms,
        suffix,
    )


def _uuid_or_none(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def _decimal_or_none(value: str | None) -> Decimal | None:
    # Numeric columns are cast to ::text in _QUALITY_PAGE_COMBINED_SQL so the
    # exact stored scale/precision round-trips through JSON (a bare numeric
    # column would come back as a JSON number and lose trailing zeros /
    # introduce float rounding when parsed, e.g. 94.50 -> 94.5).
    return Decimal(value) if value is not None else None


def _datetime_or_none(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


# Phase 2A (docs/PERF_IMPLEMENTATION_PLAN.md): collapse the five independent
# per-table SELECTs `build_quality_page` used to issue sequentially
# (snapshots, teams, open alerts, this week's reviewer scorecards, error
# entries for the latest snapshot) into ONE round trip on the caller's
# request-scoped `session` -- which already carries this request's RLS
# context (app/db/rls.py), so no new connection/session is opened and RLS
# stays enforced automatically, same as any other query on this session.
#
# Each dataset is built as a CTE and aggregated with json_agg(row_to_json(..)
# ORDER BY ...) so the aggregate order is pinned explicitly (does not depend
# on whether Postgres decides to materialize or inline the CTE feeding it).
# Numeric columns are cast to ::text before aggregation (see
# _decimal_or_none) to avoid float precision loss through JSON. SQLAlchemy's
# asyncpg dialect registers a json/jsonb type codec on every connection
# (sqlalchemy.dialects.postgresql.asyncpg.PGDialect_asyncpg.on_connect), so
# each `..._json` column below is already a Python list of dicts by the time
# it reaches this code -- no extra json.loads needed.
_QUALITY_PAGE_COMBINED_SQL = text(
    """
    WITH snap AS (
        SELECT
            id, project_id, team_id, org_id, iso_year, iso_week,
            gold_set_accuracy_pct::text AS gold_set_accuracy_pct,
            iaa_krippendorff_alpha::text AS iaa_krippendorff_alpha,
            rework_rate_pct::text AS rework_rate_pct,
            evaluated_item_count, has_drift_alert, drift_alert_detail,
            root_cause, confidence_level, created_at, updated_at
        FROM quality_snapshots
        WHERE project_id = :project_id
    ),
    team AS (
        SELECT id, project_id, org_id, name, site, domain, is_active,
               created_at, updated_at, deleted_at
        FROM teams
        WHERE project_id = :project_id
    ),
    first_snap AS (
        SELECT id FROM quality_snapshots
        WHERE project_id = :project_id
        ORDER BY iso_year DESC, iso_week DESC
        LIMIT 1
    ),
    alert AS (
        SELECT
            id, project_id, org_id, milestone_id, alert_type, risk_tier, title, detail,
            slippage_probability::text AS slippage_probability,
            contributing_causes, status, source_table, source_row_id,
            resolved_at, resolved_by, created_at, updated_at, deleted_at
        FROM risk_alerts
        WHERE project_id = :project_id
          AND deleted_at IS NULL
          AND status IN (:status_open, :status_ack)
    ),
    scorecard AS (
        SELECT
            id, annotator_id, project_id, org_id, iso_year, iso_week,
            items_evaluated, accuracy_pct::text AS accuracy_pct, error_breakdown,
            created_at, updated_at
        FROM reviewer_scorecards
        WHERE project_id = :project_id AND iso_year = :iso_year AND iso_week = :iso_week
    ),
    error_entry AS (
        SELECT id, quality_snapshot_id, org_id, error_category,
               share_pct::text AS share_pct, recommended_action, created_at, updated_at
        FROM quality_error_entries
        WHERE quality_snapshot_id = (SELECT id FROM first_snap)
    )
    SELECT
        (SELECT COALESCE(json_agg(row_to_json(s) ORDER BY s.iso_year DESC, s.iso_week DESC), '[]'::json)
           FROM snap s) AS snapshots_json,
        (SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
           FROM team t) AS teams_json,
        (SELECT COALESCE(json_agg(row_to_json(a) ORDER BY a.created_at DESC), '[]'::json)
           FROM alert a) AS alerts_json,
        (SELECT COALESCE(json_agg(row_to_json(sc) ORDER BY sc.iso_week DESC), '[]'::json)
           FROM scorecard sc) AS scorecards_json,
        (SELECT COALESCE(json_agg(row_to_json(ee)), '[]'::json)
           FROM error_entry ee) AS error_entries_json
    """
)


def _snapshot_from_row(row: dict) -> QualitySnapshot:
    return QualitySnapshot(
        id=_uuid_or_none(row["id"]),
        project_id=_uuid_or_none(row["project_id"]),
        team_id=_uuid_or_none(row["team_id"]),
        org_id=_uuid_or_none(row["org_id"]),
        iso_year=row["iso_year"],
        iso_week=row["iso_week"],
        gold_set_accuracy_pct=_decimal_or_none(row["gold_set_accuracy_pct"]),
        iaa_krippendorff_alpha=_decimal_or_none(row["iaa_krippendorff_alpha"]),
        rework_rate_pct=_decimal_or_none(row["rework_rate_pct"]),
        evaluated_item_count=row["evaluated_item_count"],
        has_drift_alert=row["has_drift_alert"],
        drift_alert_detail=row["drift_alert_detail"],
        root_cause=row["root_cause"],
        confidence_level=row["confidence_level"],
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _team_from_row(row: dict) -> Team:
    return Team(
        id=_uuid_or_none(row["id"]),
        project_id=_uuid_or_none(row["project_id"]),
        org_id=_uuid_or_none(row["org_id"]),
        name=row["name"],
        site=row["site"],
        domain=row["domain"],
        is_active=row["is_active"],
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        deleted_at=_datetime_or_none(row["deleted_at"]),
    )


def _alert_from_row(row: dict) -> RiskAlert:
    return RiskAlert(
        id=_uuid_or_none(row["id"]),
        project_id=_uuid_or_none(row["project_id"]),
        org_id=_uuid_or_none(row["org_id"]),
        milestone_id=_uuid_or_none(row["milestone_id"]),
        alert_type=row["alert_type"],
        risk_tier=row["risk_tier"],
        title=row["title"],
        detail=row["detail"],
        slippage_probability=_decimal_or_none(row["slippage_probability"]),
        contributing_causes=row["contributing_causes"],
        status=row["status"],
        source_table=row["source_table"],
        source_row_id=_uuid_or_none(row["source_row_id"]),
        resolved_at=_datetime_or_none(row["resolved_at"]),
        resolved_by=_uuid_or_none(row["resolved_by"]),
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
        deleted_at=_datetime_or_none(row["deleted_at"]),
    )


def _scorecard_from_row(row: dict) -> ReviewerScorecard:
    return ReviewerScorecard(
        id=_uuid_or_none(row["id"]),
        annotator_id=_uuid_or_none(row["annotator_id"]),
        project_id=_uuid_or_none(row["project_id"]),
        org_id=_uuid_or_none(row["org_id"]),
        iso_year=row["iso_year"],
        iso_week=row["iso_week"],
        items_evaluated=row["items_evaluated"],
        accuracy_pct=_decimal_or_none(row["accuracy_pct"]),
        error_breakdown=row["error_breakdown"],
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _error_entry_from_row(row: dict) -> QualityErrorEntry:
    return QualityErrorEntry(
        id=_uuid_or_none(row["id"]),
        quality_snapshot_id=_uuid_or_none(row["quality_snapshot_id"]),
        org_id=_uuid_or_none(row["org_id"]),
        error_category=row["error_category"],
        share_pct=_decimal_or_none(row["share_pct"]),
        recommended_action=row["recommended_action"],
        created_at=_datetime_or_none(row["created_at"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


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

    # Full-detail pack for computation — RBAC narrowing is applied at read
    # time (filter_dashboard_for_role / filter_response_for_role), not here.
    pack = await build_evidence_pack(session, snapshot, role=AppRole.SUPER_ADMIN)
    signals = extract_signals(pack)
    root_cause = await reason_root_cause(session, snapshot, pack, signals)
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
    try:
        from app.time_series.publishers import publish_quality_snapshot_observations

        await publish_quality_snapshot_observations(
            session,
            org_id=snapshot.org_id,
            project_id=snapshot.project_id,
            quality_score=snapshot.gold_set_accuracy_pct,
            extra={
                "snapshot_id": str(snapshot.id),
                "iso_year": snapshot.iso_year,
                "iso_week": snapshot.iso_week,
            },
        )
    except Exception:
        logger.exception(
            "event=time_series_quality_hook_failed snapshot_id=%s",
            snapshot.id,
        )
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
    totals = {"snapshots": 0, "alerts": 0, "data_gaps": 0, "errors": 0}

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
                "errors": 0,
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
                snapshot_id = snapshot.id
                team_id = snapshot.team_id
                totals["snapshots"] += 1
                project_result["snapshots"] += 1
                try:
                    # A concurrent snapshot update can make SQLAlchemy raise while
                    # flushing this evaluation. Keep that rollback inside a savepoint
                    # so the scan run can record the failed team and continue with the
                    # remaining snapshots instead of leaving the outer session unusable.
                    async with session.begin_nested():
                        drift_result = await evaluate_snapshot(session, snapshot)
                except Exception:
                    totals["errors"] += 1
                    project_result["errors"] += 1
                    project_result["teams"].append(
                        {
                            "team_id": str(team_id),
                            "error": "Snapshot evaluation failed.",
                        }
                    )
                    logger.exception(
                        "Quality scan snapshot evaluation failed run_id=%s project_id=%s snapshot_id=%s",
                        run.id,
                        project.id,
                        snapshot_id,
                    )
                    continue
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
        run.status = ScanStatus.FAILED if totals["errors"] else ScanStatus.COMPLETED
        if totals["errors"]:
            run.error_message = (
                f"{totals['errors']} snapshot evaluation(s) failed. "
                "Review the per-project results for affected teams."
            )
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(run)
        logger.info(
            "Quality scan complete run_id=%s status=%s projects=%s snapshots=%s alerts=%s data_gaps=%s errors=%s",
            run.id,
            run.status,
            run.projects_scanned,
            run.snapshots_evaluated,
            run.alerts_created,
            run.data_gaps,
            totals["errors"],
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
        raise QualityScanExecutionError(run) from exc


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

    # Only the columns the Projects table needs — no full-ORM hydration of
    # Project/Organisation and no relationship loading.
    project_rows = (
        await session.execute(
            select(
                Project.id,
                Project.name,
                Project.org_id,
                Project.status,
                Project.vertical,
                Project.start_date,
                Project.target_end_date,
                Project.program_id,
                Organisation.name.label("org_name"),
                Program.name.label("program_name"),
            )
            .join(Organisation, Project.org_id == Organisation.id)
            .outerjoin(Program, Project.program_id == Program.id)
            .where(Project.deleted_at.is_(None))
            .order_by(Organisation.name, Program.name.nulls_last(), Project.name)
        )
    ).all()

    # Latest (iso_year, iso_week) per project computed in the database as a single
    # aggregate row per project, instead of transferring/grouping the whole snapshot
    # history. iso_week is 1..53, so (year * 100 + week) preserves chronological order.
    latest_by_project: dict[UUID, tuple[int, int]] = {}
    for project_id, encoded in (
        await session.execute(
            select(
                QualitySnapshot.project_id,
                func.max(QualitySnapshot.iso_year * 100 + QualitySnapshot.iso_week),
            ).group_by(QualitySnapshot.project_id)
        )
    ).all():
        latest_by_project[project_id] = (encoded // 100, encoded % 100)

    # Data-gap teams: current-week snapshots below the evaluation threshold only.
    # The unique (project, team, year, week) constraint means one row per team,
    # so the current-week filter is exact — no need to dedupe latest-per-team.
    # The team name is joined in, eliminating the separate all-teams fetch.
    gaps_by_project: dict[UUID, list[str]] = {}
    gap_rows = (
        await session.execute(
            select(QualitySnapshot.project_id, Team.name)
            .join(Team, QualitySnapshot.team_id == Team.id)
            .where(
                QualitySnapshot.iso_year == iso_year,
                QualitySnapshot.iso_week == iso_week,
                QualitySnapshot.evaluated_item_count.is_not(None),
                QualitySnapshot.evaluated_item_count < MIN_EVALUATED_ITEMS,
            )
        )
    ).all()
    for row in gap_rows:
        gaps_by_project.setdefault(row.project_id, []).append(row.name)

    drift_by_project: dict[UUID, int] = dict(
        (
            await session.execute(
                select(RiskAlert.project_id, func.count())
                .where(
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .group_by(RiskAlert.project_id)
            )
        ).all()
    )

    results: list[AdminProjectRead] = []
    for project in project_rows:
        latest_year, latest_week = latest_by_project.get(project.id, (None, None))
        results.append(
            AdminProjectRead(
                id=project.id,
                name=project.name,
                org_id=project.org_id,
                org_name=project.org_name,
                status=project.status,
                vertical=project.vertical,
                start_date=project.start_date,
                target_end_date=project.target_end_date,
                program_id=project.program_id,
                program_name=project.program_name,
                latest_iso_year=latest_year,
                latest_iso_week=latest_week,
                active_drift_alerts=drift_by_project.get(project.id, 0),
                data_gap_teams=gaps_by_project.get(project.id, []),
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


def _assemble_quality_dashboard(
    *,
    snapshots: list[QualitySnapshot],
    teams: dict[UUID, Team],
    thresholds: dict,
    drift_alerts: list[RiskAlert],
    error_entries: list[QualityErrorEntry],
    current_user: CurrentUser,
) -> QualityDashboardRead:
    latest_by_team: dict[UUID, QualitySnapshot] = {}
    for snap in snapshots:
        if snap.team_id not in latest_by_team:
            latest_by_team[snap.team_id] = snap

    latest_week_snaps = list(latest_by_team.values())

    data_gap_teams = [
        teams[snap.team_id].name if snap.team_id in teams else str(snap.team_id)
        for snap in latest_week_snaps
        if snap.evaluated_item_count is not None and snap.evaluated_item_count < MIN_EVALUATED_ITEMS
    ]

    from app.kpis.adapters import quality_dashboard_kpi_values

    kpi_values = quality_dashboard_kpi_values(
        latest_week_snaps,
        gold_getter=lambda s: s.gold_set_accuracy_pct,
        iaa_getter=lambda s: s.iaa_krippendorff_alpha,
        rework_getter=lambda s: s.rework_rate_pct,
        drift_getter=lambda s: s.has_drift_alert,
    )

    kpis = QualityDashboardKpis(
        gold_set_accuracy_pct=kpi_values["gold_set_accuracy_pct"],
        iaa_krippendorff_alpha=kpi_values["iaa_krippendorff_alpha"],
        rework_rate_pct=kpi_values["rework_rate_pct"],
        active_drift_alerts=int(kpi_values["active_drift_alerts"] or 0),
    )
    rework_cfg = thresholds.get("rework_rate")
    if rework_cfg and rework_cfg.green_max is not None:
        kpis = kpis.model_copy(update={"rework_rate_target_pct": Decimal(str(rework_cfg.green_max))})

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

    error_breakdown = [
        QualityErrorBreakdown(error_category=e.error_category, share_pct=e.share_pct)
        for e in error_entries
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
                has_data_gap=(
                    snap.evaluated_item_count is not None
                    and snap.evaluated_item_count < MIN_EVALUATED_ITEMS
                ),
                evaluated_item_count=snap.evaluated_item_count,
            )
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

    thresholds = await load_thresholds(session)

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

    error_entries: list[QualityErrorEntry] = []
    if snapshots:
        error_entries = list(
            (
                await session.execute(
                    select(QualityErrorEntry).where(
                        QualityErrorEntry.quality_snapshot_id == snapshots[0].id
                    )
                )
            ).scalars()
        )

    return _assemble_quality_dashboard(
        snapshots=snapshots,
        teams=teams,
        thresholds=thresholds,
        drift_alerts=drift_alerts,
        error_entries=error_entries,
        current_user=current_user,
    )


async def build_quality_page(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> QualityPageRead:
    request_started = _quality_page_step_start(project.id, "build_quality_page.total")
    now = datetime.now(timezone.utc)
    cal = now.isocalendar()
    iso_year = cal[0]
    iso_week = cal[1]

    # Phase 2A: snapshots, teams, open alerts, this week's reviewer
    # scorecards, and error entries for the latest snapshot used to be five
    # sequential SELECTs on this same session -- each a ~150ms round trip to
    # the remote DB. They have no data dependency on one another (only
    # error_entries depends on "the latest snapshot's id", which is resolved
    # server-side via the first_snap CTE), so they are now issued as ONE
    # round trip (_QUALITY_PAGE_COMBINED_SQL) and the per-dataset JSON arrays
    # are mapped back into the exact same ORM objects the sequential loaders
    # produced (see _snapshot_from_row etc.), so every downstream consumer
    # (_assemble_quality_dashboard, calibration, sop_ambiguity, response
    # assembly) is unchanged.
    t = _quality_page_step_start(project.id, "load_combined")
    combined_row = (
        await session.execute(
            _QUALITY_PAGE_COMBINED_SQL,
            {
                "project_id": project.id,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "status_open": AlertStatus.OPEN.value,
                "status_ack": AlertStatus.ACKNOWLEDGED.value,
            },
        )
    ).mappings().one()
    _quality_page_step_end(project.id, "load_combined", t)

    t = _quality_page_step_start(project.id, "load_snapshots")
    snapshots = [_snapshot_from_row(r) for r in combined_row["snapshots_json"]]
    _quality_page_step_end(project.id, "load_snapshots", t, rows=len(snapshots))

    t = _quality_page_step_start(project.id, "load_teams")
    teams = {team.id: team for team in (_team_from_row(r) for r in combined_row["teams_json"])}
    _quality_page_step_end(project.id, "load_teams", t, rows=len(teams))

    t = _quality_page_step_start(project.id, "load_thresholds")
    thresholds = await load_thresholds(session)
    _quality_page_step_end(project.id, "load_thresholds", t, metrics=len(thresholds))

    t = _quality_page_step_start(project.id, "load_open_alerts")
    open_alerts = [_alert_from_row(r) for r in combined_row["alerts_json"]]
    _quality_page_step_end(project.id, "load_open_alerts", t, rows=len(open_alerts))

    t = _quality_page_step_start(project.id, "load_week_scorecards")
    week_scorecards = [_scorecard_from_row(r) for r in combined_row["scorecards_json"]]
    _quality_page_step_end(
        project.id,
        "load_week_scorecards",
        t,
        rows=len(week_scorecards),
        iso_year=iso_year,
        iso_week=iso_week,
    )

    error_entries: list[QualityErrorEntry] = []
    if snapshots:
        t = _quality_page_step_start(project.id, "load_error_entries")
        error_entries = [_error_entry_from_row(r) for r in combined_row["error_entries_json"]]
        _quality_page_step_end(project.id, "load_error_entries", t, rows=len(error_entries))
    else:
        logger.info(
            "quality_page SKIP project_id=%s step=load_error_entries reason=no_snapshots",
            project.id,
        )

    cached_calibration: CalibrationBriefRead | None = None
    cache_lookup_done = False
    if week_scorecards:
        t = _quality_page_step_start(project.id, "calibration_brief.cache_lookup")
        cached_calibration = await get_cached_calibration_brief(
            session, project.id, iso_year=iso_year, iso_week=iso_week
        )
        cache_lookup_done = True
        _quality_page_step_end(
            project.id,
            "calibration_brief.cache_lookup",
            t,
            hit=cached_calibration is not None,
        )
    else:
        logger.info(
            "quality_page SKIP project_id=%s step=calibration_brief.cache_lookup reason=empty_scorecards",
            project.id,
        )

    drift_alerts = [
        alert
        for alert in open_alerts
        if alert.alert_type == AlertType.QUALITY_DRIFT
    ][:10]

    t = _quality_page_step_start(project.id, "assemble_dashboard")
    dashboard = _assemble_quality_dashboard(
        snapshots=snapshots,
        teams=teams,
        thresholds=thresholds,
        drift_alerts=drift_alerts,
        error_entries=error_entries,
        current_user=current_user,
    )
    _quality_page_step_end(
        project.id,
        "assemble_dashboard",
        t,
        drift_alerts=len(drift_alerts),
        team_rows=len(dashboard.team_scorecard),
    )

    t = _quality_page_step_start(project.id, "load_calibration_brief")
    calibration_brief = await get_calibration_brief_for_project(
        project,
        iso_year=iso_year,
        iso_week=iso_week,
        scorecards=week_scorecards,
        thresholds=thresholds,
        cached_brief=cached_calibration,
        cache_lookup_done=cache_lookup_done,
        session=session,
    )
    _quality_page_step_end(
        project.id,
        "load_calibration_brief",
        t,
        candidates=len(calibration_brief.candidates),
    )

    t = _quality_page_step_start(project.id, "assemble_response")
    sop_flags = sop_ambiguity_flags_from_alerts(open_alerts)
    reviewer_scorecards = [ReviewerScorecardRead.model_validate(r) for r in week_scorecards]
    page = QualityPageRead(
        dashboard=dashboard,
        calibration_brief=calibration_brief,
        sop_ambiguity_flags=sop_flags,
        reviewer_scorecards=reviewer_scorecards,
    )
    _quality_page_step_end(
        project.id,
        "assemble_response",
        t,
        sop_flags=len(sop_flags),
        reviewer_scorecards=len(reviewer_scorecards),
    )

    _quality_page_step_end(project.id, "build_quality_page.total", request_started)
    return page


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
    project: Project,
    *,
    iso_year: int,
    iso_week: int,
    scorecards: list[ReviewerScorecard] | None = None,
    thresholds: dict | None = None,
    cached_brief: CalibrationBriefRead | None = None,
    cache_lookup_done: bool = False,
    session: AsyncSession | None = None,
) -> CalibrationBriefRead:
    if scorecards is not None and not scorecards:
        t = _quality_page_step_start(project.id, "calibration_brief.template")
        brief = build_template_calibration_brief(
            project, [], iso_year=iso_year, iso_week=iso_week
        )
        _quality_page_step_end(project.id, "calibration_brief.template", t)
        return brief

    if not cache_lookup_done:
        if session is None:
            async with AsyncSessionLocal() as query_session:
                return await get_calibration_brief_for_project(
                    project,
                    iso_year=iso_year,
                    iso_week=iso_week,
                    scorecards=scorecards,
                    thresholds=thresholds,
                    session=query_session,
                )
        t = _quality_page_step_start(project.id, "calibration_brief.cache_lookup")
        cached_brief = await get_cached_calibration_brief(
            session, project.id, iso_year=iso_year, iso_week=iso_week
        )
        _quality_page_step_end(
            project.id,
            "calibration_brief.cache_lookup",
            t,
            hit=cached_brief is not None,
        )
        cache_lookup_done = True

    if cached_brief is not None:
        return cached_brief

    t = _quality_page_step_start(project.id, "calibration_brief.identify_candidates")
    if session is None:
        async with AsyncSessionLocal() as query_session:
            candidates = await identify_calibration_candidates(
                query_session,
                project.id,
                iso_year=iso_year,
                iso_week=iso_week,
                scorecards=scorecards,
                thresholds=thresholds,
            )
    else:
        candidates = await identify_calibration_candidates(
            session,
            project.id,
            iso_year=iso_year,
            iso_week=iso_week,
            scorecards=scorecards,
            thresholds=thresholds,
        )
    _quality_page_step_end(
        project.id,
        "calibration_brief.identify_candidates",
        t,
        candidates=len(candidates),
    )

    t = _quality_page_step_start(project.id, "calibration_brief.template")
    brief = build_template_calibration_brief(
        project, candidates, iso_year=iso_year, iso_week=iso_week
    )
    _quality_page_step_end(project.id, "calibration_brief.template", t)
    return brief


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


async def create_gold_set_evaluation_log(
    session: AsyncSession,
    project: Project,
    payload: GoldSetEvaluationLogCreate,
) -> GoldSetEvaluationLog:
    row = GoldSetEvaluationLog(
        annotator_id=payload.annotator_id,
        project_id=project.id,
        org_id=project.org_id,
        item_id=payload.item_id,
        score=payload.score,
        error_category=payload.error_category,
        evaluated_at=payload.evaluated_at or datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def list_gold_set_evaluation_logs(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = 200,
) -> list[GoldSetEvaluationLog]:
    return list(
        (
            await session.execute(
                select(GoldSetEvaluationLog)
                .where(GoldSetEvaluationLog.project_id == project_id)
                .order_by(GoldSetEvaluationLog.evaluated_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def create_rework_log(
    session: AsyncSession,
    project: Project,
    payload: ReworkLogCreate,
) -> ReworkLog:
    row = ReworkLog(
        project_id=project.id,
        org_id=project.org_id,
        annotator_id=payload.annotator_id,
        item_id=payload.item_id,
        reason=payload.reason,
        rework_date=payload.rework_date,
    )
    session.add(row)
    await session.flush()
    return row


async def list_rework_logs(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit: int = 200,
) -> list[ReworkLog]:
    return list(
        (
            await session.execute(
                select(ReworkLog)
                .where(ReworkLog.project_id == project_id)
                .order_by(ReworkLog.rework_date.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def confirm_sop_ambiguity(
    session: AsyncSession,
    project: Project,
    payload: SopAmbiguityConfirm,
    *,
    confirmed_by: UUID,
) -> QualitySopLink:
    return await confirm_sop_ambiguity_resolution(
        session,
        project,
        alert_id=payload.alert_id,
        sop_version_id=payload.sop_version_id,
        confirmed_by=confirmed_by,
    )
