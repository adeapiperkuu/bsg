"""DB-backed dashboard aggregation for the Delivery Performance Agent."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.agents.delivery.analytics.milestones import select_current_milestone
from app.agents.delivery.configuration import (
    DeliveryScoringThresholds,
    load_delivery_scoring_thresholds,
    load_delivery_scoring_thresholds_for_organisations,
)
from app.agents.delivery.services.scoring_service import build_dashboard_response
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AppRole,
    Bottleneck,
    DeliveryConfidenceScore,
    Milestone,
    Project,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
)
from app.services.scoping import get_visible_project, scoped_project_query

THROUGHPUT_HISTORY_LIMIT = 30
# Upper bound on projects scored in one portfolio request. Each project runs the full
# scoring pipeline in-process, so this keeps a single request from loading/scoring an
# unbounded number of rows for very large orgs (super admins see every org's projects).
PORTFOLIO_PROJECT_LIMIT = 200

# Single authoritative filter for active risk/bottleneck statuses.
OPEN_STATUSES = [AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]


@dataclass(frozen=True, slots=True)
class ProjectScoringInputs:
    """ORM-backed delivery inputs for one scoring run."""

    project: Project
    milestones: list[Milestone]
    raw_data: dict[str, Any]
    open_risk_alerts: list[RiskAlert]
    bottlenecks: list[Bottleneck]
    latest_confidence_by_milestone: dict[UUID, DeliveryConfidenceScore]

    @property
    def current_milestone(self) -> Milestone | None:
        """Return the ORM milestone entity matching the active scoring milestone."""
        current_id = self.raw_data.get("current_milestone_id")
        if current_id is None:
            return None
        for milestone in self.milestones:
            if milestone.id == current_id:
                return milestone
        return None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _project_payload(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "org_id": project.org_id,
        "name": project.name,
        "description": project.description,
        "vertical": project.vertical,
        "status": _enum_value(project.status),
        "start_date": project.start_date,
        "target_end_date": project.target_end_date,
        "actual_end_date": project.actual_end_date,
        "daily_target_units": project.daily_target_units,
        # Additive: lets the Delivery page source its whole project universe from the
        # portfolio payload alone, instead of joining it against a separately-limited
        # /projects list that could disagree about which projects exist.
        "updated_at": project.updated_at,
    }


def _milestone_payload(milestone: Milestone) -> dict[str, Any]:
    return {
        "id": milestone.id,
        "project_id": milestone.project_id,
        "name": milestone.name,
        "description": milestone.description,
        "planned_date": milestone.planned_date,
        "actual_date": milestone.actual_date,
        "status": _enum_value(milestone.status),
    }


def _throughput_payload(snapshot: ThroughputSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "snapshot_date": snapshot.snapshot_date,
        "units_completed": snapshot.units_completed,
        "units_forecast": snapshot.units_forecast,
        "rolling_7day_units": snapshot.rolling_7day_units,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


def _risk_payload(risk: RiskAlert) -> dict[str, Any]:
    return {
        "id": risk.id,
        "project_id": risk.project_id,
        "milestone_id": risk.milestone_id,
        "alert_type": _enum_value(risk.alert_type),
        "risk_tier": _enum_value(risk.risk_tier),
        "title": risk.title,
        "detail": risk.detail,
        "slippage_probability": risk.slippage_probability,
        "contributing_causes": risk.contributing_causes,
        "status": _enum_value(risk.status),
        "created_at": risk.created_at,
        "updated_at": risk.updated_at,
    }


def _bottleneck_payload(bottleneck: Bottleneck) -> dict[str, Any]:
    return {
        "id": bottleneck.id,
        "project_id": bottleneck.project_id,
        "team_id": bottleneck.team_id,
        "title": bottleneck.title,
        "detail": bottleneck.detail,
        "status": _enum_value(bottleneck.status),
        # Severity only — never source_key, evidence_json, or acknowledgement audit fields.
        "severity": _enum_value(bottleneck.severity),
        "created_at": bottleneck.created_at,
        "updated_at": bottleneck.updated_at,
    }


def _quality_payload(snapshot: QualitySnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "has_drift_alert": snapshot.has_drift_alert,
        "rework_rate_pct": snapshot.rework_rate_pct,
    }


def _group_by_project_id(
    payloads: list[dict[str, Any]],
) -> dict[UUID, list[dict[str, Any]]]:
    grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        grouped[payload["project_id"]].append(payload)
    return grouped


def _build_raw_data(
    project: Project,
    *,
    as_of_date: date,
    milestones: list[dict[str, Any]],
    throughput_snapshots: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    bottlenecks: list[dict[str, Any]],
    quality_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the scoring input payload for one project."""
    return {
        "as_of_date": as_of_date,
        "project": _project_payload(project),
        "milestones": milestones,
        "throughput_snapshots": throughput_snapshots,
        "risks": risks,
        "bottlenecks": bottlenecks,
        "quality_snapshot": quality_snapshot,
    }


# ---------------------------------------------------------------------------
# Batch dict-based loaders (used by get_dashboard_data / get_portfolio_data)
# ---------------------------------------------------------------------------


async def _fetch_throughput_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
    *,
    limit: int = THROUGHPUT_HISTORY_LIMIT,
) -> dict[UUID, list[dict[str, Any]]]:
    """Load recent throughput snapshots for many projects in one query."""
    if not project_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=ThroughputSnapshot.project_id,
            order_by=ThroughputSnapshot.snapshot_date.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(ThroughputSnapshot.id.label("snapshot_id"), row_number)
        .where(ThroughputSnapshot.project_id.in_(project_ids))
        .subquery()
    )
    rows = await session.execute(
        select(ThroughputSnapshot)
        .join(ranked, ThroughputSnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.row_number <= limit)
        .order_by(
            ThroughputSnapshot.project_id.asc(),
            ThroughputSnapshot.snapshot_date.desc(),
        )
    )
    return _group_by_project_id([_throughput_payload(row) for row in rows.scalars()])


async def _fetch_latest_quality_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[UUID, dict[str, Any] | None]:
    """Load the latest quality snapshot per project in one query."""
    if not project_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=QualitySnapshot.project_id,
            order_by=QualitySnapshot.created_at.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(QualitySnapshot.id.label("snapshot_id"), row_number)
        .where(QualitySnapshot.project_id.in_(project_ids))
        .subquery()
    )
    rows = await session.execute(
        select(QualitySnapshot)
        .join(ranked, QualitySnapshot.id == ranked.c.snapshot_id)
        .where(ranked.c.row_number == 1)
    )
    latest: dict[UUID, dict[str, Any] | None] = {project_id: None for project_id in project_ids}
    for snapshot in rows.scalars():
        latest[snapshot.project_id] = _quality_payload(snapshot)
    return latest


async def _fetch_delivery_inputs_by_project(
    session: AsyncSession,
    project_ids: list[UUID],
) -> dict[str, Any]:
    """Batch-load all delivery dashboard inputs grouped by project."""
    milestones, throughput, risks, bottlenecks, quality = await _gather_delivery_queries(
        session,
        project_ids,
    )
    return {
        "milestones": milestones,
        "throughput_snapshots": throughput,
        "risks": risks,
        "bottlenecks": bottlenecks,
        "quality_snapshots": quality,
    }


# All five delivery-input loads bundled into ONE statement (single remote round trip).
# Each UNION branch tags its rows with a `kind`, and the payload is a jsonb object in
# the exact shape the corresponding `_*_payload` helper produced. With a remote Supabase
# database a round trip costs ~150-1100ms while the SQL itself is <10ms, so collapsing
# 5 sequential executes into 1 is the dominant win (same approach as the governance
# signal bundle in app/agents/governance/services/delivery_signals.py).
_OPEN_STATUS_SQL_LITERALS = ", ".join(f"'{status.value}'" for status in OPEN_STATUSES)

DELIVERY_INPUTS_BUNDLE_SQL = text(f"""
SELECT kind, project_id, payload
FROM (
    SELECT 'milestone'::text AS kind,
           m.project_id,
           jsonb_build_object(
               'id', m.id,
               'project_id', m.project_id,
               'name', m.name,
               'description', m.description,
               'planned_date', m.planned_date,
               'actual_date', m.actual_date,
               'status', m.status
           ) AS payload
    FROM milestones m
    WHERE m.project_id = ANY(:project_ids)
      AND m.deleted_at IS NULL

    UNION ALL

    SELECT 'throughput'::text,
           tr.project_id,
           jsonb_build_object(
               'id', tr.id,
               'project_id', tr.project_id,
               'snapshot_date', tr.snapshot_date,
               'units_completed', tr.units_completed,
               'units_forecast', tr.units_forecast,
               'rolling_7day_units', tr.rolling_7day_units,
               'created_at', tr.created_at,
               'updated_at', tr.updated_at
           )
    FROM (
        SELECT ts.*,
               row_number() OVER (
                   PARTITION BY ts.project_id ORDER BY ts.snapshot_date DESC
               ) AS rn
        FROM throughput_snapshots ts
        WHERE ts.project_id = ANY(:project_ids)
    ) tr
    WHERE tr.rn <= :throughput_limit

    UNION ALL

    SELECT 'risk'::text,
           r.project_id,
           jsonb_build_object(
               'id', r.id,
               'project_id', r.project_id,
               'milestone_id', r.milestone_id,
               'alert_type', r.alert_type,
               'risk_tier', r.risk_tier,
               'title', r.title,
               'detail', r.detail,
               'slippage_probability', r.slippage_probability,
               'contributing_causes', r.contributing_causes,
               'status', r.status,
               'created_at', r.created_at,
               'updated_at', r.updated_at
           )
    FROM risk_alerts r
    WHERE r.project_id = ANY(:project_ids)
      AND r.deleted_at IS NULL
      AND r.status IN ({_OPEN_STATUS_SQL_LITERALS})

    UNION ALL

    SELECT 'bottleneck'::text,
           b.project_id,
           jsonb_build_object(
               'id', b.id,
               'project_id', b.project_id,
               'team_id', b.team_id,
               'title', b.title,
               'detail', b.detail,
               'status', b.status,
               'severity', b.severity,
               'created_at', b.created_at,
               'updated_at', b.updated_at
           )
    FROM bottlenecks b
    WHERE b.project_id = ANY(:project_ids)
      AND b.deleted_at IS NULL
      AND b.status IN ({_OPEN_STATUS_SQL_LITERALS})

    UNION ALL

    SELECT 'quality'::text,
           qr.project_id,
           jsonb_build_object(
               'has_drift_alert', qr.has_drift_alert,
               'rework_rate_pct', qr.rework_rate_pct
           )
    FROM (
        SELECT q.project_id,
               q.has_drift_alert,
               q.rework_rate_pct,
               row_number() OVER (
                   PARTITION BY q.project_id ORDER BY q.created_at DESC
               ) AS rn
        FROM quality_snapshots q
        WHERE q.project_id = ANY(:project_ids)
    ) qr
    WHERE qr.rn = 1
) bundle
""").bindparams(
    bindparam("project_ids", type_=ARRAY(PG_UUID())),
    bindparam("throughput_limit"),
)


def _coerce_bundle_date(value: Any) -> date | None:
    """jsonb serializes DATE columns as ISO strings; scoring compares real dates."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _coerce_bundle_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _normalize_bundle_milestone(payload: dict[str, Any]) -> dict[str, Any]:
    payload["planned_date"] = _coerce_bundle_date(payload.get("planned_date"))
    payload["actual_date"] = _coerce_bundle_date(payload.get("actual_date"))
    return payload


def _normalize_bundle_throughput(payload: dict[str, Any]) -> dict[str, Any]:
    payload["snapshot_date"] = _coerce_bundle_date(payload.get("snapshot_date"))
    payload["created_at"] = _coerce_bundle_datetime(payload.get("created_at"))
    payload["updated_at"] = _coerce_bundle_datetime(payload.get("updated_at"))
    return payload


def _normalize_bundle_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    payload["created_at"] = _coerce_bundle_datetime(payload.get("created_at"))
    payload["updated_at"] = _coerce_bundle_datetime(payload.get("updated_at"))
    return payload


def _parse_delivery_inputs_bundle_rows(
    rows: list[tuple[str, UUID, dict[str, Any]]],
) -> tuple[
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, dict[str, Any] | None],
]:
    milestones: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    throughput: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    risks: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    bottlenecks: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    quality: dict[UUID, dict[str, Any] | None] = {}

    for kind, project_id, payload in rows:
        data = dict(payload)
        if kind == "milestone":
            milestones[project_id].append(_normalize_bundle_milestone(data))
        elif kind == "throughput":
            throughput[project_id].append(_normalize_bundle_throughput(data))
        elif kind == "risk":
            risks[project_id].append(_normalize_bundle_timestamps(data))
        elif kind == "bottleneck":
            bottlenecks[project_id].append(_normalize_bundle_timestamps(data))
        elif kind == "quality":
            quality[project_id] = data

    # UNION ALL provides no ordering guarantee; restore the per-source ORDER BY the
    # replaced individual queries had, which downstream scoring relies on.
    for items in milestones.values():
        items.sort(key=lambda item: item["planned_date"])
    for items in throughput.values():
        items.sort(key=lambda item: item["snapshot_date"], reverse=True)
    for items in risks.values():
        items.sort(key=lambda item: item["created_at"], reverse=True)
    for items in bottlenecks.values():
        items.sort(key=lambda item: item["created_at"], reverse=True)

    return milestones, throughput, risks, bottlenecks, quality


async def _gather_delivery_queries(
    session: AsyncSession,
    project_ids: list[UUID],
) -> tuple[
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, list[dict[str, Any]]],
    dict[UUID, dict[str, Any] | None],
]:
    """Load all five delivery dashboard inputs in a single DB round trip."""
    if not project_ids:
        return {}, {}, {}, {}, {}

    rows = (
        await session.execute(
            DELIVERY_INPUTS_BUNDLE_SQL,
            {"project_ids": project_ids, "throughput_limit": THROUGHPUT_HISTORY_LIMIT},
        )
    ).all()
    normalized_rows: list[tuple[str, UUID, dict[str, Any]]] = [
        (kind, project_id, payload) for kind, project_id, payload in rows
    ]
    return _parse_delivery_inputs_bundle_rows(normalized_rows)


# ---------------------------------------------------------------------------
# ORM loaders (used only by load_project_scoring_inputs / scoring path)
# ---------------------------------------------------------------------------


async def _fetch_orm_milestones(
    session: AsyncSession,
    project_id: UUID,
) -> list[Milestone]:
    rows = await session.execute(
        select(Milestone)
        .where(Milestone.project_id == project_id, Milestone.deleted_at.is_(None))
        .order_by(Milestone.planned_date.asc())
    )
    return list(rows.scalars())


async def _fetch_orm_open_risks(
    session: AsyncSession,
    project_id: UUID,
) -> list[RiskAlert]:
    rows = await session.execute(
        select(RiskAlert)
        .where(
            RiskAlert.project_id == project_id,
            RiskAlert.deleted_at.is_(None),
            RiskAlert.status.in_(OPEN_STATUSES),
        )
        .order_by(RiskAlert.created_at.desc())
    )
    return list(rows.scalars())


async def _fetch_orm_open_bottlenecks(
    session: AsyncSession,
    project_id: UUID,
) -> list[Bottleneck]:
    rows = await session.execute(
        select(Bottleneck)
        .where(
            Bottleneck.project_id == project_id,
            Bottleneck.deleted_at.is_(None),
            Bottleneck.status.in_(OPEN_STATUSES),
        )
        .order_by(Bottleneck.created_at.desc())
    )
    return list(rows.scalars())


async def _fetch_latest_confidence_by_milestone(
    session: AsyncSession,
    project_id: UUID,
) -> dict[UUID, DeliveryConfidenceScore]:
    """Load the latest confidence score row for each milestone in one query."""
    row_number = (
        func.row_number()
        .over(
            partition_by=DeliveryConfidenceScore.milestone_id,
            order_by=DeliveryConfidenceScore.created_at.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(DeliveryConfidenceScore.id.label("score_id"), row_number)
        .where(DeliveryConfidenceScore.project_id == project_id)
        .subquery()
    )
    rows = await session.execute(
        select(DeliveryConfidenceScore)
        .join(ranked, DeliveryConfidenceScore.id == ranked.c.score_id)
        .where(ranked.c.row_number == 1)
    )
    return {score.milestone_id: score for score in rows.scalars()}


# ---------------------------------------------------------------------------
# Scoring input loader (scoring path only — ORM + raw_data in one shot)
# ---------------------------------------------------------------------------


async def load_project_scoring_inputs(
    session: AsyncSession,
    project: Project,
    *,
    as_of_date: date | None = None,
) -> ProjectScoringInputs:
    """Load ORM entities and scoring raw_data for one project without duplicate queries."""
    effective_date = as_of_date or date.today()

    milestones = await _fetch_orm_milestones(session, project.id)
    throughput_map = await _fetch_throughput_by_project(session, [project.id])
    quality_map = await _fetch_latest_quality_by_project(session, [project.id])
    open_risk_alerts = await _fetch_orm_open_risks(session, project.id)
    bottlenecks = await _fetch_orm_open_bottlenecks(session, project.id)
    latest_confidence_by_milestone = await _fetch_latest_confidence_by_milestone(
        session, project.id
    )

    milestone_payloads = [_milestone_payload(m) for m in milestones]
    current_milestone = select_current_milestone(milestone_payloads, as_of_date=effective_date)

    raw_data = _build_raw_data(
        project,
        as_of_date=effective_date,
        milestones=milestone_payloads,
        throughput_snapshots=throughput_map.get(project.id, []),
        risks=[_risk_payload(alert) for alert in open_risk_alerts],
        bottlenecks=[_bottleneck_payload(b) for b in bottlenecks],
        quality_snapshot=quality_map.get(project.id),
    )
    raw_data["current_milestone_id"] = (
        current_milestone["id"] if current_milestone is not None else None
    )

    return ProjectScoringInputs(
        project=project,
        milestones=milestones,
        raw_data=raw_data,
        open_risk_alerts=open_risk_alerts,
        bottlenecks=bottlenecks,
        latest_confidence_by_milestone=latest_confidence_by_milestone,
    )


# ---------------------------------------------------------------------------
# Portfolio cache
# ---------------------------------------------------------------------------

# Delivery inputs change on a slow cadence (snapshots, alerts, milestones) while chat
# turns and dashboard section loads are bursty, so a short TTL removes the expensive
# load-and-score work from consecutive requests without meaningful staleness. Same
# in-process pattern as the governance bootstrap KPI cache.
PORTFOLIO_CACHE_TTL = timedelta(seconds=30)
_portfolio_cache: dict[tuple[UUID | None, str, UUID], tuple[datetime, dict[str, Any]]] = {}


def _portfolio_cache_key(current_user: CurrentUser) -> tuple[UUID | None, str, UUID]:
    # user_id is part of the key because CLIENT visibility depends on per-user
    # project assignments, not just the org.
    org_id = None if current_user.role == AppRole.SUPER_ADMIN else current_user.org_id
    return (org_id, current_user.role.value, current_user.id)


def clear_delivery_portfolio_cache(*, org_id: UUID | None = None) -> int:
    """Drop cached portfolio payloads after a committed delivery-data write.

    ``org_id=None`` clears everything (also used by tests); otherwise entries for that
    org plus all super-admin (cross-org) entries are cleared.
    """
    if org_id is None:
        keys_to_remove = list(_portfolio_cache)
    else:
        keys_to_remove = [key for key in _portfolio_cache if key[0] in {org_id, None}]
    for key in keys_to_remove:
        _portfolio_cache.pop(key, None)
    return len(keys_to_remove)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _score_projects(
    projects: list[Project],
    inputs: dict[str, Any],
    effective_date: date,
    thresholds_by_org: dict[UUID, DeliveryScoringThresholds],
) -> list[dict[str, Any]]:
    """Run the scoring pipeline for each project. Pure CPU; no I/O, no session access.

    Runs in a worker thread. It only reads already-loaded column attributes off `projects`
    and plain dicts out of `inputs`, so it triggers no lazy load — which matters, because a
    lazy load here would try to emit async I/O from a non-async thread and fail outright.
    Keep it that way: no relationship access, no session use.
    """
    scored: list[dict[str, Any]] = []
    for project in projects:
        raw_data = _build_raw_data(
            project,
            as_of_date=effective_date,
            milestones=inputs["milestones"].get(project.id, []),
            throughput_snapshots=inputs["throughput_snapshots"].get(project.id, []),
            risks=inputs["risks"].get(project.id, []),
            bottlenecks=inputs["bottlenecks"].get(project.id, []),
            quality_snapshot=inputs["quality_snapshots"].get(project.id),
        )
        scored.append(
            {
                "project_id": project.id,
                "dashboard": build_dashboard_response(
                    raw_data,
                    thresholds=thresholds_by_org[project.org_id],
                ),
            }
        )
    return scored


async def get_dashboard_data(
    *,
    session: AsyncSession,
    project_id: UUID,
    current_user: CurrentUser,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Fetch raw delivery data and return the computed dashboard payload."""
    project = await get_visible_project(session, project_id, current_user)
    thresholds = await load_delivery_scoring_thresholds(session, project.org_id)
    effective_date = as_of_date or date.today()
    inputs = await _fetch_delivery_inputs_by_project(session, [project.id])
    raw_data = _build_raw_data(
        project,
        as_of_date=effective_date,
        milestones=inputs["milestones"].get(project.id, []),
        throughput_snapshots=inputs["throughput_snapshots"].get(project.id, []),
        risks=inputs["risks"].get(project.id, []),
        bottlenecks=inputs["bottlenecks"].get(project.id, []),
        quality_snapshot=inputs["quality_snapshots"].get(project.id),
    )
    return build_dashboard_response(raw_data, thresholds=thresholds)


async def get_portfolio_data(
    *,
    session: AsyncSession,
    current_user: CurrentUser,
    as_of_date: date | None = None,
    limit: int = PORTFOLIO_PROJECT_LIMIT,
    projects: list[Project] | None = None,
) -> dict[str, Any]:
    """Return delivery dashboard summaries for every visible project in one payload.

    `total_count` reports how many projects the caller can actually see, which may exceed
    the `limit` applied here. Clients must compare it against len(projects) and disclose
    the shortfall rather than presenting a truncated portfolio as the whole picture.
    """
    # Only the default read shape is cacheable — caller-supplied project subsets and
    # historical as_of_date reads bypass the cache entirely.
    cache_eligible = projects is None and as_of_date is None and limit == PORTFOLIO_PROJECT_LIMIT
    if cache_eligible:
        cache_key = _portfolio_cache_key(current_user)
        cached = _portfolio_cache.get(cache_key)
        if cached and datetime.now(UTC) - cached[0] < PORTFOLIO_CACHE_TTL:
            return cached[1]

    if projects is None:
        project_rows = (
            await session.execute(
                scoped_project_query(current_user)
                # count(*) OVER () is evaluated before LIMIT, so the visible-project
                # total rides along in the same round trip instead of a second query.
                .add_columns(func.count().over().label("total_count"))
                # Tie-break on id so the truncated window is total, not merely sorted:
                # two projects sharing a name would otherwise straddle the limit boundary
                # in an unspecified order and swap between requests.
                .order_by(Project.name.asc(), Project.id.asc())
                .limit(limit)
            )
        ).all()
        projects = [row[0] for row in project_rows]
        total_count = int(project_rows[0][1]) if project_rows else 0
    else:
        # The caller supplied the universe (e.g. operational_tower's in-flight subset), so
        # nothing was truncated here and no extra count query is warranted.
        total_count = len(projects)

    if not projects:
        empty_result = {"projects": [], "milestones": [], "total_count": total_count}
        if cache_eligible:
            _portfolio_cache[cache_key] = (datetime.now(UTC), empty_result)
        return empty_result

    effective_date = as_of_date or date.today()
    project_ids = [project.id for project in projects]
    thresholds_by_org = await load_delivery_scoring_thresholds_for_organisations(
        session,
        {project.org_id for project in projects},
    )
    inputs = await _fetch_delivery_inputs_by_project(session, project_ids)

    # Scoring is pure CPU over already-fetched rows, and it is not cheap: ~700ms of the
    # ~1550ms this function takes for a 28-project portfolio. Run it off the event loop so
    # it cannot stall the dashboard's other section requests, which are issued in parallel
    # and would otherwise block behind it despite needing none of its work.
    portfolio_projects = await run_in_threadpool(
        _score_projects,
        projects,
        inputs,
        effective_date,
        thresholds_by_org,
    )

    # DeliveryPortfolioResponse declares a portfolio-wide `milestones` list, but this
    # function never populated it, so it always serialized as its default [] and the
    # clients' milestone hit-rate read as "no data". These are already batch-loaded
    # above, so flattening them here costs no extra query.
    portfolio_milestones = [
        milestone
        for project_id in project_ids
        for milestone in inputs["milestones"].get(project_id, [])
    ]

    result = {
        "projects": portfolio_projects,
        "milestones": portfolio_milestones,
        "total_count": total_count,
    }
    if cache_eligible:
        _portfolio_cache[cache_key] = (datetime.now(UTC), result)
    return result
