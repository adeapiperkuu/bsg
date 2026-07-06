"""Evidence pack: the single, bounded, cite-able view of quality data the LLM
reasoning layer (reasoning.py) is allowed to see.

Anonymization happens here, at the source — reviewers are exposed only as
stable handles (R1, R2, ...) never as annotator_id/full_name. This makes the
pack itself client-safe by construction, instead of relying on downstream
regex scrubbing of prose (see quality_reasoning_upgrade_plan.md §1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.oka_client import OKAClient
from app.db.models import (
    AlertStatus,
    AlertType,
    Annotator,
    AppRole,
    GoldSetEvaluationLog,
    GoldSetMetadata,
    IaaMeasurementRecord,
    OnboardingRecord,
    QualityErrorEntry,
    QualitySnapshot,
    ReviewerScorecard,
    RiskAlert,
    SopVersionHistory,
    ThroughputSnapshot,
)
from app.db.optional_tables import query_optional_table

SNAPSHOT_TIMELINE_WEEKS = 12
MAX_REVIEWER_SCORECARDS = 15
MAX_IAA_RECORDS = 20
MAX_SOP_VERSIONS = 10
MAX_GOLD_SET_VERSIONS = 5
MAX_THROUGHPUT_ROWS = 14
MAX_ONBOARDING_EVENTS = 20
MAX_OPEN_ALERTS = 5
ONBOARDING_LOOKBACK_DAYS = 60
REVIEWER_SCORECARD_MIN_ITEMS = 50
FREE_TEXT_LIMIT = 300

# Reviewer/annotator-level detail is withheld from the CLIENT persona, mirroring
# the RBAC boundary already enforced in quality_scoping.py (only CLIENT is
# special-cased anywhere in this codebase's role filtering today).
_REVIEWER_LEVEL_EXCLUDED_ROLES = {AppRole.CLIENT}


def _truncate(text: str | None, limit: int = FREE_TEXT_LIMIT) -> str | None:
    if not text:
        return text
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _num(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


class _Anonymizer:
    """Assigns stable R1..Rn handles to annotator UUIDs for a single pack build."""

    def __init__(self) -> None:
        self._map: dict[UUID, str] = {}

    def handle(self, annotator_id: UUID) -> str:
        if annotator_id not in self._map:
            self._map[annotator_id] = f"R{len(self._map) + 1}"
        return self._map[annotator_id]


@dataclass(frozen=True)
class EvidenceItem:
    key: str
    source_table: str
    source_row_id: UUID
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {"key": self.key, "summary": self.summary, **self.data}


@dataclass(frozen=True)
class EvidencePack:
    project_id: UUID
    team_id: UUID | None
    role: AppRole
    snapshot_timeline: list[EvidenceItem]
    error_taxonomy_trend: dict[str, list[dict[str, Any]]]
    reviewer_scorecards: list[EvidenceItem]
    eval_log_rollup: dict[str, Any]
    iaa_records: list[EvidenceItem]
    sop_timeline: list[EvidenceItem]
    gold_set_versions: list[EvidenceItem]
    throughput_timeline: list[EvidenceItem]
    onboarding_events: list[EvidenceItem]
    open_alerts: list[EvidenceItem]
    oka_lessons: list[dict[str, Any]]
    key_index: dict[str, EvidenceItem]

    def all_items(self) -> list[EvidenceItem]:
        return [
            *self.snapshot_timeline,
            *self.reviewer_scorecards,
            *self.iaa_records,
            *self.sop_timeline,
            *self.gold_set_versions,
            *self.throughput_timeline,
            *self.onboarding_events,
            *self.open_alerts,
        ]

    def to_prompt_json(self) -> dict[str, Any]:
        """Compact, anonymized, cite-able context. Never includes raw PII."""
        return {
            "snapshot_timeline": [i.to_prompt_dict() for i in self.snapshot_timeline],
            "error_taxonomy_trend": self.error_taxonomy_trend,
            "reviewer_scorecards": [i.to_prompt_dict() for i in self.reviewer_scorecards],
            "eval_log_rollup": self.eval_log_rollup,
            "iaa_records": [i.to_prompt_dict() for i in self.iaa_records],
            "sop_timeline": [i.to_prompt_dict() for i in self.sop_timeline],
            "gold_set_versions": [i.to_prompt_dict() for i in self.gold_set_versions],
            "throughput_timeline": [i.to_prompt_dict() for i in self.throughput_timeline],
            "onboarding_events": [i.to_prompt_dict() for i in self.onboarding_events],
            "open_alerts": [i.to_prompt_dict() for i in self.open_alerts],
            "oka_lessons": self.oka_lessons[:5],
        }


async def _fetch_snapshot_timeline(
    session: AsyncSession, snapshot: QualitySnapshot
) -> tuple[list[EvidenceItem], list[QualitySnapshot]]:
    rows = list(
        (
            await session.execute(
                select(QualitySnapshot)
                .where(
                    QualitySnapshot.project_id == snapshot.project_id,
                    QualitySnapshot.team_id == snapshot.team_id,
                )
                .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                .limit(SNAPSHOT_TIMELINE_WEEKS)
            )
        ).scalars()
    )
    items = [
        EvidenceItem(
            key=f"SNAP-{s.iso_year}W{s.iso_week}",
            source_table="quality_snapshots",
            source_row_id=s.id,
            summary=(
                f"W{s.iso_week}/{s.iso_year}: gold-set accuracy {s.gold_set_accuracy_pct}%, "
                f"IAA {s.iaa_krippendorff_alpha}, rework {s.rework_rate_pct}%"
                + (", drift alert active" if s.has_drift_alert else "")
            ),
            data={
                "iso_year": s.iso_year,
                "iso_week": s.iso_week,
                "gold_set_accuracy_pct": _num(s.gold_set_accuracy_pct),
                "iaa_krippendorff_alpha": _num(s.iaa_krippendorff_alpha),
                "rework_rate_pct": _num(s.rework_rate_pct),
                "evaluated_item_count": s.evaluated_item_count,
                "has_drift_alert": s.has_drift_alert,
            },
        )
        for s in rows
    ]
    return items, rows


async def _fetch_error_taxonomy_trend(
    session: AsyncSession, snapshots: list[QualitySnapshot]
) -> dict[str, list[dict[str, Any]]]:
    trend: dict[str, list[dict[str, Any]]] = {}
    for snap in snapshots:
        entries = (
            await session.execute(
                select(QualityErrorEntry).where(QualityErrorEntry.quality_snapshot_id == snap.id)
            )
        ).scalars()
        week_label = f"{snap.iso_year}W{snap.iso_week}"
        for entry in entries:
            trend.setdefault(entry.error_category, []).append(
                {"week": week_label, "share_pct": _num(entry.share_pct)}
            )
    for category in trend:
        trend[category].sort(key=lambda row: row["week"])
    return trend


async def _fetch_reviewer_scorecards(
    session: AsyncSession, snapshot: QualitySnapshot, anonymizer: _Anonymizer
) -> list[EvidenceItem]:
    rows = list(
        (
            await session.execute(
                select(ReviewerScorecard)
                .where(
                    ReviewerScorecard.project_id == snapshot.project_id,
                    ReviewerScorecard.iso_year == snapshot.iso_year,
                    ReviewerScorecard.iso_week == snapshot.iso_week,
                )
            )
        ).scalars()
    )
    # Worst accuracy first — most relevant for root-cause reasoning, bounded by cap.
    rows.sort(key=lambda r: (_num(r.accuracy_pct) if r.accuracy_pct is not None else 100.0))
    items: list[EvidenceItem] = []
    for row in rows[:MAX_REVIEWER_SCORECARDS]:
        handle = anonymizer.handle(row.annotator_id)
        items.append(
            EvidenceItem(
                key=handle,
                source_table="reviewer_scorecards",
                source_row_id=row.id,
                summary=(
                    f"{handle}: {row.accuracy_pct}% accuracy over {row.items_evaluated} items "
                    f"({snapshot.iso_year}W{snapshot.iso_week})"
                ),
                data={
                    "items_evaluated": row.items_evaluated,
                    "accuracy_pct": _num(row.accuracy_pct),
                    "error_breakdown": row.error_breakdown or {},
                    "meets_min_sample": row.items_evaluated >= REVIEWER_SCORECARD_MIN_ITEMS,
                },
            )
        )
    return items


async def _fetch_eval_log_rollup(
    session: AsyncSession, snapshot: QualitySnapshot, anonymizer: _Anonymizer
) -> dict[str, Any]:
    async def _query() -> list[GoldSetEvaluationLog]:
        return list(
            (
                await session.execute(
                    select(GoldSetEvaluationLog).where(
                        GoldSetEvaluationLog.project_id == snapshot.project_id,
                    )
                )
            ).scalars()
        )

    logs = await query_optional_table(session, _query, [])
    if not logs:
        return {}

    team_annotator_ids = {
        a.id
        for a in (
            await session.execute(select(Annotator).where(Annotator.team_id == snapshot.team_id))
        ).scalars()
    }

    by_reviewer: dict[str, list[float]] = {}
    by_category: dict[str, int] = {}
    total = 0
    for log in logs:
        if log.annotator_id not in team_annotator_ids or log.score is None:
            continue
        handle = anonymizer.handle(log.annotator_id)
        by_reviewer.setdefault(handle, []).append(float(log.score))
        if log.error_category:
            by_category[log.error_category] = by_category.get(log.error_category, 0) + 1
        total += 1

    if total == 0:
        return {}

    return {
        "by_reviewer": {
            handle: {
                "items": len(scores),
                "avg_score": round(sum(scores) / len(scores), 2),
                "meets_min_sample": len(scores) >= REVIEWER_SCORECARD_MIN_ITEMS,
            }
            for handle, scores in by_reviewer.items()
        },
        "by_error_category": {
            category: {"count": count, "share_pct": round(count / total * 100, 1)}
            for category, count in by_category.items()
        },
        "total_evaluated_items": total,
    }


async def _fetch_iaa_records(session: AsyncSession, snapshot: QualitySnapshot) -> list[EvidenceItem]:
    rows = list(
        (
            await session.execute(
                select(IaaMeasurementRecord)
                .where(
                    IaaMeasurementRecord.project_id == snapshot.project_id,
                    IaaMeasurementRecord.iso_year == snapshot.iso_year,
                    IaaMeasurementRecord.iso_week == snapshot.iso_week,
                )
                .limit(MAX_IAA_RECORDS)
            )
        ).scalars()
    )
    # Deliberately excludes reviewer_a_id/reviewer_b_id — only the aggregate
    # alpha and task_type matter for the systemic-ambiguity hypothesis (BR-03).
    return [
        EvidenceItem(
            key=f"IAA-{row.id}",
            source_table="iaa_measurement_records",
            source_row_id=row.id,
            summary=f"{row.task_type or 'unspecified task'}: alpha={row.krippendorff_alpha}",
            data={
                "task_type": row.task_type,
                "krippendorff_alpha": _num(row.krippendorff_alpha),
                "iso_year": row.iso_year,
                "iso_week": row.iso_week,
            },
        )
        for row in rows
    ]


async def _fetch_sop_timeline(session: AsyncSession, snapshot: QualitySnapshot) -> list[EvidenceItem]:
    async def _query() -> list[SopVersionHistory]:
        return list(
            (
                await session.execute(
                    select(SopVersionHistory)
                    .where(SopVersionHistory.org_id == snapshot.org_id)
                    .order_by(SopVersionHistory.effective_date.desc())
                    .limit(MAX_SOP_VERSIONS)
                )
            ).scalars()
        )

    rows = await query_optional_table(session, _query, [])
    return [
        EvidenceItem(
            key=f"SOP-{row.version}",
            source_table="sop_version_history",
            source_row_id=row.id,
            summary=f"SOP version {row.version} effective {row.effective_date}: {_truncate(row.change_summary) or 'no summary'}",
            data={"version": row.version, "effective_date": str(row.effective_date)},
        )
        for row in rows
    ]


async def _fetch_gold_set_versions(session: AsyncSession, snapshot: QualitySnapshot) -> list[EvidenceItem]:
    async def _query() -> list[GoldSetMetadata]:
        return list(
            (
                await session.execute(
                    select(GoldSetMetadata)
                    .where(GoldSetMetadata.project_id == snapshot.project_id)
                    .order_by(GoldSetMetadata.last_updated.desc())
                    .limit(MAX_GOLD_SET_VERSIONS)
                )
            ).scalars()
        )

    rows = await query_optional_table(session, _query, [])
    return [
        EvidenceItem(
            key=f"GOLDSET-{row.version}",
            source_table="gold_set_metadata",
            source_row_id=row.id,
            summary=f"Gold-set version {row.version}, {row.item_count} items, updated {row.last_updated}",
            data={"version": row.version, "item_count": row.item_count, "last_updated": str(row.last_updated)},
        )
        for row in rows
    ]


async def _fetch_throughput_timeline(session: AsyncSession, snapshot: QualitySnapshot) -> list[EvidenceItem]:
    rows = list(
        (
            await session.execute(
                select(ThroughputSnapshot)
                .where(ThroughputSnapshot.project_id == snapshot.project_id)
                .order_by(ThroughputSnapshot.snapshot_date.desc())
                .limit(MAX_THROUGHPUT_ROWS)
            )
        ).scalars()
    )
    return [
        EvidenceItem(
            key=f"THROUGHPUT-{row.snapshot_date}",
            source_table="throughput_snapshots",
            source_row_id=row.id,
            summary=f"{row.snapshot_date}: {row.units_completed} units, 7-day rolling {row.rolling_7day_units}",
            data={
                "snapshot_date": str(row.snapshot_date),
                "units_completed": row.units_completed,
                "rolling_7day_units": row.rolling_7day_units,
            },
        )
        for row in rows
    ]


async def _fetch_onboarding_events(
    session: AsyncSession, snapshot: QualitySnapshot, anonymizer: _Anonymizer
) -> list[EvidenceItem]:
    team_annotator_ids = {
        a.id
        for a in (
            await session.execute(select(Annotator).where(Annotator.team_id == snapshot.team_id))
        ).scalars()
    }
    if not team_annotator_ids:
        return []

    async def _query() -> list[OnboardingRecord]:
        cutoff = date.today() - timedelta(days=ONBOARDING_LOOKBACK_DAYS)
        return list(
            (
                await session.execute(
                    select(OnboardingRecord)
                    .where(
                        OnboardingRecord.annotator_id.in_(team_annotator_ids),
                        OnboardingRecord.onboarding_date >= cutoff,
                    )
                    .order_by(OnboardingRecord.onboarding_date.desc())
                    .limit(MAX_ONBOARDING_EVENTS)
                )
            ).scalars()
        )

    rows = await query_optional_table(session, _query, [])
    items: list[EvidenceItem] = []
    for row in rows:
        handle = anonymizer.handle(row.annotator_id)
        items.append(
            EvidenceItem(
                key=f"ONBOARD-{handle}",
                source_table="onboarding_records",
                source_row_id=row.id,
                summary=f"{handle} onboarded {row.onboarding_date}, calibration status: {row.calibration_status}",
                data={
                    "onboarding_date": str(row.onboarding_date),
                    "calibration_status": row.calibration_status,
                },
            )
        )
    return items


async def _fetch_open_alerts(session: AsyncSession, snapshot: QualitySnapshot) -> list[EvidenceItem]:
    # Scoped to quality-drift alerts only. Other agents' alerts (workforce
    # imbalance, delivery risk, milestone-at-risk) share the risk_alerts table
    # but are not quality evidence — leaking them in gives the reasoning LLM
    # an unrelated but real-looking signal to fabricate a root cause from.
    rows = list(
        (
            await session.execute(
                select(RiskAlert)
                .where(
                    RiskAlert.project_id == snapshot.project_id,
                    RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                    RiskAlert.deleted_at.is_(None),
                    RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(RiskAlert.created_at.desc())
                .limit(MAX_OPEN_ALERTS)
            )
        ).scalars()
    )
    return [
        EvidenceItem(
            key=f"ALERT-{row.id}",
            source_table="risk_alerts",
            source_row_id=row.id,
            summary=f"{row.title}: {_truncate(row.detail)}",
            data={"risk_tier": row.risk_tier.value, "status": row.status.value},
        )
        for row in rows
    ]


async def build_evidence_pack(
    session: AsyncSession,
    snapshot: QualitySnapshot,
    *,
    role: AppRole,
) -> EvidencePack:
    """Gather the full grounded, anonymized, bounded evidence set for one snapshot's team/project."""
    anonymizer = _Anonymizer()
    reviewer_level_allowed = role not in _REVIEWER_LEVEL_EXCLUDED_ROLES

    snapshot_timeline, snapshot_rows = await _fetch_snapshot_timeline(session, snapshot)
    error_taxonomy_trend = await _fetch_error_taxonomy_trend(session, snapshot_rows)

    reviewer_scorecards: list[EvidenceItem] = []
    eval_log_rollup: dict[str, Any] = {}
    onboarding_events: list[EvidenceItem] = []
    if reviewer_level_allowed:
        reviewer_scorecards = await _fetch_reviewer_scorecards(session, snapshot, anonymizer)
        eval_log_rollup = await _fetch_eval_log_rollup(session, snapshot, anonymizer)
        onboarding_events = await _fetch_onboarding_events(session, snapshot, anonymizer)

    iaa_records = await _fetch_iaa_records(session, snapshot)
    sop_timeline = await _fetch_sop_timeline(session, snapshot)
    gold_set_versions = await _fetch_gold_set_versions(session, snapshot)
    throughput_timeline = await _fetch_throughput_timeline(session, snapshot)
    open_alerts = await _fetch_open_alerts(session, snapshot)

    oka = OKAClient()
    oka_lessons = await oka.retrieve_lessons(org_id=str(snapshot.org_id), error_category="quality")

    key_index: dict[str, EvidenceItem] = {}
    for item in (
        *snapshot_timeline,
        *reviewer_scorecards,
        *iaa_records,
        *sop_timeline,
        *gold_set_versions,
        *throughput_timeline,
        *onboarding_events,
        *open_alerts,
    ):
        key_index[item.key] = item

    return EvidencePack(
        project_id=snapshot.project_id,
        team_id=snapshot.team_id,
        role=role,
        snapshot_timeline=snapshot_timeline,
        error_taxonomy_trend=error_taxonomy_trend,
        reviewer_scorecards=reviewer_scorecards,
        eval_log_rollup=eval_log_rollup,
        iaa_records=iaa_records,
        sop_timeline=sop_timeline,
        gold_set_versions=gold_set_versions,
        throughput_timeline=throughput_timeline,
        onboarding_events=onboarding_events,
        open_alerts=open_alerts,
        oka_lessons=oka_lessons,
        key_index=key_index,
    )
