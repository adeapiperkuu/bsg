"""Quality Intelligence structured evidence adapter for Client Intelligence.

Loads QualitySnapshot aggregate facts for the current and previous reporting
ISO weeks. Does not call Quality Intelligence private modules, does not blend
scores, and never consumes ``QualitySummaryRead.client_narrative``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import (
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    QualityEvidenceFacts,
    QualitySnapshotFacts,
    ReportingPeriod,
    SourceAgent,
    VisibilityLimitation,
)
from app.agents.client_intelligence.visibility import (
    ClientVisibilityPolicy,
    ClientVisibleMetric,
)
from app.db.models import QualitySnapshot

_MAX_QUALITY_SNAPSHOTS = 50

_GENERIC_INTERNAL_DESCRIPTION = (
    "Quality snapshot aggregate for an authorized project reporting period."
)
_GENERIC_CLIENT_DESCRIPTION = (
    "Client-safe quality snapshot aggregate for an authorized reporting period."
)


@dataclass(frozen=True, slots=True)
class _QualitySnapshotRow:
    """Bounded aggregate columns only — never root_cause or drift free text."""

    id: UUID
    team_id: UUID
    iso_year: int
    iso_week: int
    gold_set_accuracy_pct: Decimal | None
    iaa_krippendorff_alpha: Decimal | None
    rework_rate_pct: Decimal | None
    evaluated_item_count: int | None
    has_drift_alert: bool
    confidence_level: str | None
    created_at: datetime | None


def iso_periods_for_reporting(
    reporting_period: ReportingPeriod,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Map reporting Monday starts to ISO (year, week) pairs."""
    current = reporting_period.start_date.isocalendar()
    previous = reporting_period.previous_start_date.isocalendar()
    return (current[0], current[1]), (previous[0], previous[1])


def _empty_quality_facts(
    current_iso_year: int,
    current_iso_week: int,
    previous_iso_year: int,
    previous_iso_week: int,
) -> QualityEvidenceFacts:
    return QualityEvidenceFacts(
        current_period=[],
        previous_period=[],
        current_iso_year=current_iso_year,
        current_iso_week=current_iso_week,
        previous_iso_year=previous_iso_year,
        previous_iso_week=previous_iso_week,
    )


async def load_quality_evidence(
    session: AsyncSession,
    project_id: UUID,
    reporting_period: ReportingPeriod,
    *,
    visibility_mode: EvidenceVisibility,
    policy: ClientVisibilityPolicy | None,
) -> tuple[
    QualityEvidenceFacts,
    list[ClientEvidenceReference],
    list[DataQualityIssue],
    list[VisibilityLimitation],
    list[str],
]:
    """Load bounded QualitySnapshot facts for current and previous ISO weeks."""
    (current_year, current_week), (previous_year, previous_week) = iso_periods_for_reporting(
        reporting_period
    )
    empty = _empty_quality_facts(current_year, current_week, previous_year, previous_week)
    evidence: list[ClientEvidenceReference] = []
    quality_issues: list[DataQualityIssue] = []
    visibility_limitations: list[VisibilityLimitation] = []
    limitations: list[str] = []
    client_safe = visibility_mode == EvidenceVisibility.CLIENT_SAFE

    if client_safe:
        assert policy is not None
        if not policy.allows_any_quality():
            visibility_limitations.append(
                VisibilityLimitation(
                    source="quality_snapshots",
                    reason="not_configured",
                    detail=(
                        "No client-visible quality metrics are configured; "
                        "quality snapshot facts are redacted."
                    ),
                )
            )
            return empty, evidence, quality_issues, visibility_limitations, limitations

    rows = await _load_quality_snapshots(
        session,
        project_id,
        current_year=current_year,
        current_week=current_week,
        previous_year=previous_year,
        previous_week=previous_week,
    )

    current_rows = [
        row for row in rows if row.iso_year == current_year and row.iso_week == current_week
    ]
    previous_rows = [
        row for row in rows if row.iso_year == previous_year and row.iso_week == previous_week
    ]

    if not current_rows and not previous_rows:
        quality_issues.append(
            DataQualityIssue(
                source="quality_snapshots",
                state=DataQualityState.UNAVAILABLE,
                detail="No quality snapshots found for the current or previous reporting period.",
                observed_at=None,
            )
        )
        limitations.append("Quality snapshot data is unavailable for the reporting periods.")
        return empty, evidence, quality_issues, visibility_limitations, limitations

    if not current_rows and previous_rows:
        quality_issues.append(
            DataQualityIssue(
                source="quality_snapshots",
                state=DataQualityState.UNAVAILABLE,
                detail=(
                    "Current-period quality snapshots are missing; "
                    "current quality posture cannot be established."
                ),
                observed_at=None,
            )
        )
        limitations.append(
            "Current-period quality snapshots are missing; "
            "prior-period rows alone are insufficient."
        )
    elif current_rows and not previous_rows:
        quality_issues.append(
            DataQualityIssue(
                source="quality_snapshots",
                state=DataQualityState.PARTIAL,
                detail=(
                    "Previous-period quality snapshots are missing; "
                    "period comparison is unavailable."
                ),
                observed_at=None,
            )
        )
        limitations.append("Period-over-period quality comparison is unavailable.")
    else:
        quality_issues.append(
            DataQualityIssue(
                source="quality_snapshots",
                state=DataQualityState.COMPLETE,
                detail=(
                    f"Loaded {len(current_rows)} current and {len(previous_rows)} previous "
                    "quality snapshot row(s)."
                ),
                observed_at=None,
            )
        )

    current_facts, current_evidence, current_partial = _project_snapshots(
        current_rows,
        client_safe=client_safe,
        policy=policy,
    )
    previous_facts, previous_evidence, previous_partial = _project_snapshots(
        previous_rows,
        client_safe=client_safe,
        policy=policy,
    )
    evidence.extend(current_evidence)
    evidence.extend(previous_evidence)

    if current_partial or previous_partial:
        for index, issue in enumerate(quality_issues):
            if issue.source == "quality_snapshots" and issue.state == DataQualityState.COMPLETE:
                quality_issues[index] = DataQualityIssue(
                    source="quality_snapshots",
                    state=DataQualityState.PARTIAL,
                    detail=(
                        "Quality snapshots are present but one or more required aggregate "
                        "fields are missing."
                    ),
                    observed_at=None,
                )
                break
        limitations.append(
            "One or more quality snapshot aggregate fields are missing; values were not fabricated."
        )

    facts = QualityEvidenceFacts(
        current_period=current_facts,
        previous_period=previous_facts,
        current_iso_year=current_year,
        current_iso_week=current_week,
        previous_iso_year=previous_year,
        previous_iso_week=previous_week,
    )
    return facts, evidence, quality_issues, visibility_limitations, limitations


async def _load_quality_snapshots(
    session: AsyncSession,
    project_id: UUID,
    *,
    current_year: int,
    current_week: int,
    previous_year: int,
    previous_week: int,
) -> list[_QualitySnapshotRow]:
    result = await session.execute(
        select(
            QualitySnapshot.id,
            QualitySnapshot.team_id,
            QualitySnapshot.iso_year,
            QualitySnapshot.iso_week,
            QualitySnapshot.gold_set_accuracy_pct,
            QualitySnapshot.iaa_krippendorff_alpha,
            QualitySnapshot.rework_rate_pct,
            QualitySnapshot.evaluated_item_count,
            QualitySnapshot.has_drift_alert,
            QualitySnapshot.confidence_level,
            QualitySnapshot.created_at,
        )
        .where(
            QualitySnapshot.project_id == project_id,
            or_(
                and_(
                    QualitySnapshot.iso_year == current_year,
                    QualitySnapshot.iso_week == current_week,
                ),
                and_(
                    QualitySnapshot.iso_year == previous_year,
                    QualitySnapshot.iso_week == previous_week,
                ),
            ),
        )
        .order_by(
            QualitySnapshot.iso_year.asc(),
            QualitySnapshot.iso_week.asc(),
            QualitySnapshot.team_id.asc(),
            QualitySnapshot.id.asc(),
        )
        .limit(_MAX_QUALITY_SNAPSHOTS)
    )
    rows: list[_QualitySnapshotRow] = []
    for item in result.all():
        rows.append(
            _QualitySnapshotRow(
                id=item.id,
                team_id=item.team_id,
                iso_year=item.iso_year,
                iso_week=item.iso_week,
                gold_set_accuracy_pct=item.gold_set_accuracy_pct,
                iaa_krippendorff_alpha=item.iaa_krippendorff_alpha,
                rework_rate_pct=item.rework_rate_pct,
                evaluated_item_count=item.evaluated_item_count,
                has_drift_alert=bool(item.has_drift_alert),
                confidence_level=item.confidence_level,
                created_at=item.created_at,
            )
        )
    return rows


def _project_snapshots(
    rows: list[_QualitySnapshotRow],
    *,
    client_safe: bool,
    policy: ClientVisibilityPolicy | None,
) -> tuple[list[QualitySnapshotFacts], list[ClientEvidenceReference], bool]:
    facts: list[QualitySnapshotFacts] = []
    evidence: list[ClientEvidenceReference] = []
    partial = False

    for row in rows:
        if client_safe:
            assert policy is not None
            show_gold = policy.allows(ClientVisibleMetric.GOLD_SET_ACCURACY)
            show_rework = policy.allows(ClientVisibleMetric.REWORK_RATE)
            if not show_gold and not show_rework:
                continue
            gold = row.gold_set_accuracy_pct if show_gold else None
            rework = row.rework_rate_pct if show_rework else None
            if show_gold and row.gold_set_accuracy_pct is None:
                partial = True
            if show_rework and row.rework_rate_pct is None:
                partial = True
            claim_keys = ["iso_year", "iso_week"]
            if show_gold:
                claim_keys.append("gold_set_accuracy_pct")
            if show_rework:
                claim_keys.append("rework_rate_pct")
            facts.append(
                QualitySnapshotFacts(
                    snapshot_id=row.id,
                    iso_year=row.iso_year,
                    iso_week=row.iso_week,
                    team_id=None,
                    gold_set_accuracy_pct=gold,
                    rework_rate_pct=rework,
                    iaa_krippendorff_alpha=None,
                    evaluated_item_count=None,
                    has_drift_alert=None,
                    confidence_level=None,
                    observed_at=row.created_at,
                )
            )
            evidence.append(
                ClientEvidenceReference(
                    source_agent=SourceAgent.QUALITY_INTELLIGENCE,
                    source_table="quality_snapshots",
                    source_row_id=row.id,
                    description=_GENERIC_CLIENT_DESCRIPTION,
                    visibility=EvidenceVisibility.CLIENT_SAFE,
                    observed_at=row.created_at,
                    claim_keys=claim_keys,
                )
            )
            continue

        if row.evaluated_item_count is None:
            partial = True
        if (
            row.gold_set_accuracy_pct is None
            and row.rework_rate_pct is None
            and row.iaa_krippendorff_alpha is None
        ):
            partial = True

        facts.append(
            QualitySnapshotFacts(
                snapshot_id=row.id,
                iso_year=row.iso_year,
                iso_week=row.iso_week,
                team_id=row.team_id,
                gold_set_accuracy_pct=row.gold_set_accuracy_pct,
                rework_rate_pct=row.rework_rate_pct,
                iaa_krippendorff_alpha=row.iaa_krippendorff_alpha,
                evaluated_item_count=row.evaluated_item_count,
                has_drift_alert=row.has_drift_alert,
                confidence_level=row.confidence_level,
                observed_at=row.created_at,
            )
        )
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.QUALITY_INTELLIGENCE,
                source_table="quality_snapshots",
                source_row_id=row.id,
                description=_GENERIC_INTERNAL_DESCRIPTION,
                visibility=EvidenceVisibility.INTERNAL,
                observed_at=row.created_at,
                claim_keys=[
                    "iso_year",
                    "iso_week",
                    "team_id",
                    "gold_set_accuracy_pct",
                    "rework_rate_pct",
                    "iaa_krippendorff_alpha",
                    "evaluated_item_count",
                    "has_drift_alert",
                    "confidence_level",
                ],
            )
        )

    return facts, evidence, partial
