"""Workforce & Capability structured evidence adapter for Client Intelligence.

Produces aggregated capacity, skill-coverage, training, and capability-gap facts.
Never projects annotator names or individual utilization/training into the pack.
Does not call ``build_project_skill_matrix`` or other identity-gated Workforce DTOs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import (
    CapabilityGapCountFacts,
    CapabilityGapFacts,
    ClientEvidenceReference,
    DataQualityIssue,
    DataQualityState,
    EvidenceVisibility,
    ReportingPeriod,
    SkillCoverageFacts,
    SkillCoverageSummaryFacts,
    SourceAgent,
    TeamCapacityFacts,
    TrainingCompletionFacts,
    VisibilityLimitation,
    WorkforceCapacityFacts,
    WorkforceEvidenceFacts,
)
from app.db.models import (
    Annotator,
    AnnotatorSkill,
    CapabilityGap,
    CapabilityGapStatus,
    ProficiencyLevel,
    ProjectSkillRequirement,
    Skill,
    SkillCoverageStatus,
    Team,
    TrainingProgram,
    TrainingRecord,
    TrainingRecordStatus,
    UtilizationSnapshot,
)
from app.services.workforce_skills import compute_coverage_status, meets_proficiency
from app.services.workforce_training import is_expired_or_failed_training

_MAX_TEAMS = 50
_MAX_ANNOTATORS = 500
_MAX_UTILIZATION_ROWS = 200
_MAX_REQUIREMENTS = 100
_MAX_ANNOTATOR_SKILLS = 2000
_MAX_TRAINING_PROGRAMS = 100
_MAX_TRAINING_RECORDS = 2000
_MAX_CAPABILITY_GAPS = 100

_OPEN_GAP_STATUSES = (CapabilityGapStatus.OPEN, CapabilityGapStatus.ACKNOWLEDGED)

_COVERAGE_LABEL = {
    SkillCoverageStatus.HIGH: "covered",
    SkillCoverageStatus.MEDIUM: "partial",
    SkillCoverageStatus.LOW: "gap",
}

_PROFICIENCY_RANK: dict[ProficiencyLevel, int] = {
    ProficiencyLevel.BEGINNER: 1,
    ProficiencyLevel.INTERMEDIATE: 2,
    ProficiencyLevel.ADVANCED: 3,
    ProficiencyLevel.EXPERT: 4,
}

_GENERIC_DESCRIPTION = "Workforce & Capability aggregate evidence for an authorized project."

_HISTORICAL_LIMITATION = (
    "Workforce roster, skill, training, and capability-gap status are primarily "
    "current-state records; a past as_of cannot fully reconstruct historical state."
)

# UtilizationSnapshot evidence supports utilization aggregates only — not roster counts.
_UTILIZATION_CLAIM_KEYS = [
    "latest_snapshot_date",
    "allocated_hours_total",
    "available_hours_total",
    "utilization_pct",
    "teams_with_utilization",
    "teams_without_utilization",
]

_TEAM_ROSTER_CLAIM_KEYS = ["active_team_count"]

_SKILL_SUMMARY_CLAIM_KEYS = [
    "requirement_count",
    "covered_requirement_count",
    "partial_requirement_count",
    "gap_requirement_count",
    "unavailable_requirement_count",
    "required_headcount_slots",
    "available_headcount_slots",
    "required_sme_slots",
    "available_sme_slots",
]

_TRAINING_CLAIM_KEYS = [
    "mandatory_program_count",
    "required_assignment_count",
    "completed_assignment_count",
    "incomplete_assignment_count",
    "expired_or_failed_assignment_count",
    "completion_pct",
]

_GAP_COUNT_CLAIM_KEYS = ["open_gap_counts"]

_DQ_PRECEDENCE: dict[DataQualityState, int] = {
    DataQualityState.COMPLETE: 0,
    DataQualityState.PARTIAL: 1,
    DataQualityState.STALE: 2,
    DataQualityState.UNAVAILABLE: 3,
    DataQualityState.CONFLICTING: 4,
}


@dataclass(frozen=True, slots=True)
class _TeamRow:
    id: UUID


@dataclass(frozen=True, slots=True)
class _AnnotatorRow:
    id: UUID
    team_id: UUID
    is_sme_certified: bool
    is_active: bool


@dataclass(frozen=True, slots=True)
class _UtilRow:
    id: UUID
    team_id: UUID
    snapshot_date: date
    allocated_hours: Decimal
    available_hours: Decimal
    utilization_pct: Decimal
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _RequirementRow:
    id: UUID
    skill_id: UUID
    required_proficiency_level: ProficiencyLevel
    priority: object
    required_headcount: int
    required_sme_count: int
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _AnnotatorSkillRow:
    annotator_id: UUID
    skill_id: UUID
    proficiency_level: ProficiencyLevel


@dataclass(frozen=True, slots=True)
class _ProgramRow:
    id: UUID


@dataclass(frozen=True, slots=True)
class _TrainingRecordRow:
    id: UUID
    annotator_id: UUID
    training_program_id: UUID
    status: TrainingRecordStatus
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class _GapRow:
    id: UUID
    gap_type: object
    severity: object
    status: object
    team_id: UUID | None
    skill_id: UUID | None
    detected_at: datetime
    resolved_at: datetime | None
    created_at: datetime | None


def _as_of_end_utc(as_of: date) -> datetime:
    return datetime.combine(as_of, time.max, tzinfo=UTC)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _evidence_visibility(client_safe: bool) -> EvidenceVisibility:
    return EvidenceVisibility.CLIENT_SAFE if client_safe else EvidenceVisibility.INTERNAL


def _issue(
    source: str,
    state: DataQualityState,
    detail: str,
) -> DataQualityIssue:
    return DataQualityIssue(source=source, state=state, detail=detail, observed_at=None)


def _set_source_issue(
    issues_by_source: dict[str, DataQualityIssue],
    source: str,
    state: DataQualityState,
    detail: str,
) -> None:
    """Keep one issue per source: CONFLICTING > UNAVAILABLE > PARTIAL > COMPLETE."""
    existing = issues_by_source.get(source)
    if existing is None or _DQ_PRECEDENCE[state] > _DQ_PRECEDENCE[existing.state]:
        issues_by_source[source] = _issue(source, state, detail)
    elif existing.state == state and state != DataQualityState.COMPLETE:
        # Prefer the more specific non-COMPLETE detail when states match.
        issues_by_source[source] = _issue(source, state, detail)


def _finalize_issues(issues_by_source: dict[str, DataQualityIssue]) -> list[DataQualityIssue]:
    return [issues_by_source[key] for key in sorted(issues_by_source)]


def _trim_limit_plus_one(rows: list, max_rows: int) -> tuple[list, bool]:
    """Return at most max_rows; truncated True only when more than max_rows were fetched."""
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


async def load_workforce_evidence(
    session: AsyncSession,
    project_id: UUID,
    org_id: UUID,
    reporting_period: ReportingPeriod,
    *,
    visibility_mode: EvidenceVisibility,
) -> tuple[
    WorkforceEvidenceFacts,
    list[ClientEvidenceReference],
    list[DataQualityIssue],
    list[VisibilityLimitation],
    list[str],
]:
    """Load bounded Workforce aggregates for an already-authorized project."""
    client_safe = visibility_mode == EvidenceVisibility.CLIENT_SAFE
    as_of = reporting_period.as_of
    as_of_end = _as_of_end_utc(as_of)
    today = datetime.now(UTC).date()

    evidence: list[ClientEvidenceReference] = []
    issues_by_source: dict[str, DataQualityIssue] = {}
    visibility_limitations: list[VisibilityLimitation] = []
    limitations: list[str] = []

    if as_of < today:
        limitations.append(_HISTORICAL_LIMITATION)

    teams, teams_truncated = await _load_active_teams(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if teams_truncated:
        limitations.append("Active team query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_roster",
            DataQualityState.PARTIAL,
            "Active team query reached the configured row bound.",
        )

    team_ids = [team.id for team in teams]
    for team in teams:
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.WORKFORCE_CAPABILITY,
                source_table="teams",
                source_row_id=team.id,
                description=_GENERIC_DESCRIPTION,
                visibility=_evidence_visibility(client_safe),
                observed_at=None,
                claim_keys=list(_TEAM_ROSTER_CLAIM_KEYS),
            )
        )
    annotators, annotators_truncated = await _load_active_annotators(
        session,
        team_ids=team_ids,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if team_ids and annotators_truncated:
        limitations.append("Active worker query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_roster",
            DataQualityState.PARTIAL,
            "Active worker query reached the configured row bound.",
        )

    capacity, team_capacity, util_limitations = await _build_capacity(
        session,
        project_id=project_id,
        org_id=org_id,
        teams=teams,
        annotators=annotators,
        as_of=as_of,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(util_limitations)

    skill_summary, skill_rows, skill_limitations = await _build_skill_coverage(
        session,
        project_id=project_id,
        org_id=org_id,
        annotators=annotators,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(skill_limitations)

    training, training_limitations = await _build_training(
        session,
        org_id=org_id,
        annotators=annotators,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(training_limitations)

    gap_counts, open_gaps, gap_limitations = await _build_capability_gaps(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
        client_safe=client_safe,
        evidence=evidence,
        issues_by_source=issues_by_source,
    )
    limitations.extend(gap_limitations)

    if client_safe:
        evidence = [
            item for item in evidence if item.visibility == EvidenceVisibility.CLIENT_SAFE
        ]

    facts = WorkforceEvidenceFacts(
        capacity=capacity,
        team_capacity=[] if client_safe else team_capacity,
        skill_coverage=skill_summary,
        skill_requirements=[] if client_safe else skill_rows,
        training=training,
        open_gap_counts=gap_counts,
        open_gaps=[] if client_safe else open_gaps,
        as_of=as_of,
    )
    return (
        facts,
        evidence,
        _finalize_issues(issues_by_source),
        visibility_limitations,
        limitations,
    )


async def _load_active_teams(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_TeamRow], bool]:
    result = await session.execute(
        select(Team.id)
        .where(
            Team.project_id == project_id,
            Team.org_id == org_id,
            Team.deleted_at.is_(None),
            Team.is_active.is_(True),
            Team.created_at <= as_of_end,
        )
        .order_by(Team.id.asc())
        .limit(_MAX_TEAMS + 1)
    )
    rows = [_TeamRow(id=row.id) for row in result.all()]
    return _trim_limit_plus_one(rows, _MAX_TEAMS)


async def _load_active_annotators(
    session: AsyncSession,
    *,
    team_ids: list[UUID],
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_AnnotatorRow], bool]:
    if not team_ids:
        return [], False
    result = await session.execute(
        select(
            Annotator.id,
            Annotator.team_id,
            Annotator.is_sme_certified,
            Annotator.is_active,
        )
        .where(
            Annotator.team_id.in_(team_ids),
            Annotator.org_id == org_id,
            Annotator.deleted_at.is_(None),
            Annotator.is_active.is_(True),
            Annotator.created_at <= as_of_end,
        )
        .order_by(Annotator.id.asc())
        .limit(_MAX_ANNOTATORS + 1)
    )
    rows = [
        _AnnotatorRow(
            id=row.id,
            team_id=row.team_id,
            is_sme_certified=bool(row.is_sme_certified),
            is_active=bool(row.is_active),
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_ANNOTATORS)


async def _build_capacity(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    teams: list[_TeamRow],
    annotators: list[_AnnotatorRow],
    as_of: date,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[WorkforceCapacityFacts, list[TeamCapacityFacts], list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)

    active_team_count = len(teams)
    active_worker_count = len(annotators)
    certified_sme_count = sum(1 for row in annotators if row.is_sme_certified)

    if active_team_count == 0:
        _set_source_issue(
            issues_by_source,
            "workforce_roster",
            DataQualityState.UNAVAILABLE,
            "No active teams found for the authorized project.",
        )
    elif active_worker_count == 0:
        _set_source_issue(
            issues_by_source,
            "workforce_roster",
            DataQualityState.PARTIAL,
            "Active teams exist but no active workers were found.",
        )
    else:
        _set_source_issue(
            issues_by_source,
            "workforce_roster",
            DataQualityState.COMPLETE,
            "Active team and worker roster counts were loaded.",
        )

    team_capacity: list[TeamCapacityFacts] = []
    selected: list[_UtilRow] = []
    util_truncated = False

    if teams:
        util_rows, util_truncated = await _load_team_utilization(
            session,
            project_id=project_id,
            org_id=org_id,
            team_ids=[team.id for team in teams],
            as_of=as_of,
            as_of_end=as_of_end,
        )
        if util_truncated:
            limitations.append("Utilization snapshot query reached the configured row bound.")
            _set_source_issue(
                issues_by_source,
                "workforce_utilization",
                DataQualityState.PARTIAL,
                "Utilization snapshot query reached the configured row bound.",
            )

        selected_by_team: dict[UUID, _UtilRow] = {}
        for row in util_rows:
            if row.team_id not in selected_by_team:
                selected_by_team[row.team_id] = row
        selected = [selected_by_team[team.id] for team in teams if team.id in selected_by_team]
        selected.sort(key=lambda row: (row.snapshot_date, str(row.id)))

        for row in selected:
            team_capacity.append(
                TeamCapacityFacts(
                    team_id=row.team_id,
                    snapshot_id=row.id,
                    snapshot_date=row.snapshot_date,
                    allocated_hours=row.allocated_hours,
                    available_hours=row.available_hours,
                    utilization_pct=row.utilization_pct,
                    observed_at=row.created_at,
                )
            )
            evidence.append(
                ClientEvidenceReference(
                    source_agent=SourceAgent.WORKFORCE_CAPABILITY,
                    source_table="utilization_snapshots",
                    source_row_id=row.id,
                    description=_GENERIC_DESCRIPTION,
                    visibility=visibility,
                    observed_at=row.created_at,
                    claim_keys=list(_UTILIZATION_CLAIM_KEYS),
                )
            )

    teams_with = len(selected)
    teams_without = active_team_count - teams_with
    allocated_total = (
        sum((row.allocated_hours for row in selected), Decimal("0")) if selected else None
    )
    available_total = (
        sum((row.available_hours for row in selected), Decimal("0")) if selected else None
    )
    latest_snapshot_date = max((row.snapshot_date for row in selected), default=None)

    utilization_pct: Decimal | None = None
    if available_total is None:
        _set_source_issue(
            issues_by_source,
            "workforce_utilization",
            DataQualityState.UNAVAILABLE,
            "No team-level utilization snapshots at or before as_of.",
        )
        limitations.append("Team-level utilization is unavailable.")
    elif available_total == 0:
        _set_source_issue(
            issues_by_source,
            "workforce_utilization",
            DataQualityState.PARTIAL,
            "Selected team-level snapshots have zero total available hours.",
        )
        limitations.append("Utilization percentage cannot be computed from zero available hours.")
    elif teams_without > 0 or util_truncated:
        utilization_pct = _quantize_pct(allocated_total / available_total * Decimal("100"))
        detail = (
            "Utilization snapshot query reached the configured row bound."
            if util_truncated and teams_without == 0
            else (
                "Some active teams lack a team-level utilization snapshot "
                "at or before as_of."
            )
        )
        if util_truncated and teams_without > 0:
            detail = (
                "Utilization bound prevented complete team coverage; "
                "some active teams lack a selected snapshot."
            )
        _set_source_issue(
            issues_by_source,
            "workforce_utilization",
            DataQualityState.PARTIAL,
            detail,
        )
        limitations.append("Utilization coverage is incomplete across active teams.")
    else:
        utilization_pct = _quantize_pct(allocated_total / available_total * Decimal("100"))
        _set_source_issue(
            issues_by_source,
            "workforce_utilization",
            DataQualityState.COMPLETE,
            "Team-level utilization snapshots loaded for all active teams.",
        )

    capacity = WorkforceCapacityFacts(
        active_team_count=active_team_count,
        active_worker_count=active_worker_count,
        certified_sme_count=certified_sme_count,
        latest_snapshot_date=latest_snapshot_date,
        allocated_hours_total=allocated_total,
        available_hours_total=available_total,
        utilization_pct=utilization_pct,
        teams_with_utilization=teams_with,
        teams_without_utilization=teams_without,
    )
    return capacity, team_capacity, limitations


async def _load_team_utilization(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    team_ids: list[UUID],
    as_of: date,
    as_of_end: datetime,
) -> tuple[list[_UtilRow], bool]:
    result = await session.execute(
        select(
            UtilizationSnapshot.id,
            UtilizationSnapshot.team_id,
            UtilizationSnapshot.snapshot_date,
            UtilizationSnapshot.allocated_hours,
            UtilizationSnapshot.available_hours,
            UtilizationSnapshot.utilization_pct,
            UtilizationSnapshot.created_at,
        )
        .where(
            UtilizationSnapshot.project_id == project_id,
            UtilizationSnapshot.org_id == org_id,
            UtilizationSnapshot.deleted_at.is_(None),
            UtilizationSnapshot.annotator_id.is_(None),
            UtilizationSnapshot.team_id.in_(team_ids),
            UtilizationSnapshot.snapshot_date <= as_of,
            UtilizationSnapshot.created_at <= as_of_end,
        )
        .order_by(
            UtilizationSnapshot.snapshot_date.desc(),
            UtilizationSnapshot.id.desc(),
        )
        .limit(_MAX_UTILIZATION_ROWS + 1)
    )
    rows: list[_UtilRow] = []
    for row in result.all():
        if row.team_id is None:
            continue
        rows.append(
            _UtilRow(
                id=row.id,
                team_id=row.team_id,
                snapshot_date=row.snapshot_date,
                allocated_hours=Decimal(row.allocated_hours),
                available_hours=Decimal(row.available_hours),
                utilization_pct=Decimal(row.utilization_pct),
                created_at=row.created_at,
            )
        )
    return _trim_limit_plus_one(rows, _MAX_UTILIZATION_ROWS)


async def _build_skill_coverage(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    annotators: list[_AnnotatorRow],
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[SkillCoverageSummaryFacts, list[SkillCoverageFacts], list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)

    requirements, req_truncated = await _load_requirements(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if req_truncated:
        limitations.append("Skill requirement query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_skill_coverage",
            DataQualityState.PARTIAL,
            "Skill requirement query reached the configured row bound.",
        )

    if not requirements:
        _set_source_issue(
            issues_by_source,
            "workforce_skill_coverage",
            DataQualityState.UNAVAILABLE,
            "No project skill requirements found; absence is not treated as full coverage.",
        )
        return SkillCoverageSummaryFacts(), [], limitations

    skill_ids = sorted({row.skill_id for row in requirements}, key=str)
    active_skill_ids = await _load_active_skill_ids(
        session,
        org_id=org_id,
        skill_ids=skill_ids,
        as_of_end=as_of_end,
    )
    if len(active_skill_ids) < len(skill_ids):
        _set_source_issue(
            issues_by_source,
            "workforce_skill_coverage",
            DataQualityState.PARTIAL,
            "One or more skill requirements reference missing or deleted skills.",
        )
        limitations.append("Some skill requirements reference unavailable skills.")

    annotator_ids = [row.id for row in annotators]
    assignments, assignments_truncated = await _load_annotator_skills(
        session,
        org_id=org_id,
        annotator_ids=annotator_ids,
        skill_ids=list(active_skill_ids),
        as_of_end=as_of_end,
    )
    if annotator_ids and assignments_truncated:
        limitations.append("Worker skill assignment query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_skill_coverage",
            DataQualityState.PARTIAL,
            "Worker skill assignment query reached the configured row bound.",
        )

    proficiency_index: dict[tuple[UUID, UUID], ProficiencyLevel] = {}
    for assignment in assignments:
        key = (assignment.annotator_id, assignment.skill_id)
        existing = proficiency_index.get(key)
        if (
            existing is None
            or _PROFICIENCY_RANK[assignment.proficiency_level] > _PROFICIENCY_RANK[existing]
        ):
            proficiency_index[key] = assignment.proficiency_level

    skill_rows: list[SkillCoverageFacts] = []
    covered = 0
    partial = 0
    gap = 0
    unavailable = 0
    required_headcount_slots = 0
    available_headcount_slots = 0
    required_sme_slots = 0
    available_sme_slots = 0

    for requirement in requirements:
        required_headcount_slots += requirement.required_headcount
        required_sme_slots += requirement.required_sme_count

        if requirement.skill_id not in active_skill_ids:
            unavailable += 1
            skill_rows.append(
                SkillCoverageFacts(
                    requirement_id=requirement.id,
                    skill_id=requirement.skill_id,
                    required_proficiency_level=_enum_str(requirement.required_proficiency_level),
                    priority=_enum_str(requirement.priority),
                    required_headcount=requirement.required_headcount,
                    available_headcount=None,
                    required_sme_count=requirement.required_sme_count,
                    available_sme_count=None,
                    coverage_status="unavailable",
                    observed_at=requirement.created_at,
                )
            )
        else:
            available_headcount = 0
            available_sme = 0
            for annotator in annotators:
                actual = proficiency_index.get((annotator.id, requirement.skill_id))
                if actual is None:
                    continue
                if not meets_proficiency(actual, requirement.required_proficiency_level):
                    continue
                available_headcount += 1
                if annotator.is_sme_certified:
                    available_sme += 1

            status = compute_coverage_status(
                available_headcount,
                requirement.required_headcount,
                available_sme,
                requirement.required_sme_count,
            )
            label = _COVERAGE_LABEL[status]
            if label == "covered":
                covered += 1
            elif label == "partial":
                partial += 1
            else:
                gap += 1

            available_headcount_slots += available_headcount
            available_sme_slots += available_sme
            skill_rows.append(
                SkillCoverageFacts(
                    requirement_id=requirement.id,
                    skill_id=requirement.skill_id,
                    required_proficiency_level=_enum_str(requirement.required_proficiency_level),
                    priority=_enum_str(requirement.priority),
                    required_headcount=requirement.required_headcount,
                    available_headcount=available_headcount,
                    required_sme_count=requirement.required_sme_count,
                    available_sme_count=available_sme,
                    coverage_status=label,
                    observed_at=requirement.created_at,
                )
            )

        claim_keys = list(_SKILL_SUMMARY_CLAIM_KEYS)
        if not client_safe:
            claim_keys.extend(
                [
                    "requirement_id",
                    "skill_id",
                    "required_proficiency_level",
                    "priority",
                    "required_headcount",
                    "available_headcount",
                    "required_sme_count",
                    "available_sme_count",
                    "coverage_status",
                ]
            )
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.WORKFORCE_CAPABILITY,
                source_table="project_skill_requirements",
                source_row_id=requirement.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=requirement.created_at,
                claim_keys=claim_keys,
            )
        )

    _set_source_issue(
        issues_by_source,
        "workforce_skill_coverage",
        DataQualityState.COMPLETE,
        "Project skill requirement coverage was computed from structured sources.",
    )

    summary = SkillCoverageSummaryFacts(
        requirement_count=len(requirements),
        covered_requirement_count=covered,
        partial_requirement_count=partial,
        gap_requirement_count=gap,
        unavailable_requirement_count=unavailable,
        required_headcount_slots=required_headcount_slots,
        available_headcount_slots=available_headcount_slots,
        required_sme_slots=required_sme_slots,
        available_sme_slots=available_sme_slots,
    )
    return summary, skill_rows, limitations


async def _load_requirements(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_RequirementRow], bool]:
    result = await session.execute(
        select(
            ProjectSkillRequirement.id,
            ProjectSkillRequirement.skill_id,
            ProjectSkillRequirement.required_proficiency_level,
            ProjectSkillRequirement.priority,
            ProjectSkillRequirement.required_headcount,
            ProjectSkillRequirement.required_sme_count,
            ProjectSkillRequirement.created_at,
        )
        .where(
            ProjectSkillRequirement.project_id == project_id,
            ProjectSkillRequirement.org_id == org_id,
            ProjectSkillRequirement.deleted_at.is_(None),
            ProjectSkillRequirement.created_at <= as_of_end,
        )
        .order_by(ProjectSkillRequirement.id.asc())
        .limit(_MAX_REQUIREMENTS + 1)
    )
    rows: list[_RequirementRow] = []
    for row in result.all():
        level = row.required_proficiency_level
        if not isinstance(level, ProficiencyLevel):
            level = ProficiencyLevel(level)
        rows.append(
            _RequirementRow(
                id=row.id,
                skill_id=row.skill_id,
                required_proficiency_level=level,
                priority=row.priority,
                required_headcount=int(row.required_headcount),
                required_sme_count=int(row.required_sme_count),
                created_at=row.created_at,
            )
        )
    return _trim_limit_plus_one(rows, _MAX_REQUIREMENTS)


async def _load_active_skill_ids(
    session: AsyncSession,
    *,
    org_id: UUID,
    skill_ids: list[UUID],
    as_of_end: datetime,
) -> set[UUID]:
    if not skill_ids:
        return set()
    result = await session.execute(
        select(Skill.id)
        .where(
            Skill.id.in_(skill_ids),
            Skill.org_id == org_id,
            Skill.deleted_at.is_(None),
            Skill.created_at <= as_of_end,
        )
        .order_by(Skill.id.asc())
        .limit(_MAX_REQUIREMENTS + 1)
    )
    return {row.id for row in result.all()[:_MAX_REQUIREMENTS]}


async def _load_annotator_skills(
    session: AsyncSession,
    *,
    org_id: UUID,
    annotator_ids: list[UUID],
    skill_ids: list[UUID],
    as_of_end: datetime,
) -> tuple[list[_AnnotatorSkillRow], bool]:
    if not annotator_ids or not skill_ids:
        return [], False
    result = await session.execute(
        select(
            AnnotatorSkill.annotator_id,
            AnnotatorSkill.skill_id,
            AnnotatorSkill.proficiency_level,
        )
        .where(
            AnnotatorSkill.org_id == org_id,
            AnnotatorSkill.annotator_id.in_(annotator_ids),
            AnnotatorSkill.skill_id.in_(skill_ids),
            AnnotatorSkill.deleted_at.is_(None),
            AnnotatorSkill.created_at <= as_of_end,
        )
        .order_by(AnnotatorSkill.annotator_id.asc(), AnnotatorSkill.skill_id.asc())
        .limit(_MAX_ANNOTATOR_SKILLS + 1)
    )
    rows: list[_AnnotatorSkillRow] = []
    for row in result.all():
        level = row.proficiency_level
        if not isinstance(level, ProficiencyLevel):
            level = ProficiencyLevel(level)
        rows.append(
            _AnnotatorSkillRow(
                annotator_id=row.annotator_id,
                skill_id=row.skill_id,
                proficiency_level=level,
            )
        )
    return _trim_limit_plus_one(rows, _MAX_ANNOTATOR_SKILLS)


async def _build_training(
    session: AsyncSession,
    *,
    org_id: UUID,
    annotators: list[_AnnotatorRow],
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[TrainingCompletionFacts, list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)

    programs, programs_truncated = await _load_mandatory_programs(
        session,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if programs_truncated:
        limitations.append("Mandatory training program query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_training",
            DataQualityState.PARTIAL,
            "Mandatory training program query reached the configured row bound.",
        )

    for program in programs:
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.WORKFORCE_CAPABILITY,
                source_table="training_programs",
                source_row_id=program.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=None,
                claim_keys=list(_TRAINING_CLAIM_KEYS),
            )
        )

    if not programs:
        _set_source_issue(
            issues_by_source,
            "workforce_training",
            DataQualityState.UNAVAILABLE,
            "No mandatory training programs found; completion is not treated as 100%.",
        )
        return (
            TrainingCompletionFacts(
                mandatory_program_count=0,
                required_assignment_count=0,
                completed_assignment_count=0,
                incomplete_assignment_count=0,
                expired_or_failed_assignment_count=0,
                completion_pct=None,
                observed_at=None,
            ),
            limitations,
        )

    if not annotators:
        _set_source_issue(
            issues_by_source,
            "workforce_training",
            DataQualityState.PARTIAL,
            "Mandatory programs exist but no active project workers were found.",
        )
        return (
            TrainingCompletionFacts(
                mandatory_program_count=len(programs),
                required_assignment_count=0,
                completed_assignment_count=0,
                incomplete_assignment_count=0,
                expired_or_failed_assignment_count=0,
                completion_pct=None,
                observed_at=None,
            ),
            limitations,
        )

    records, records_truncated = await _load_training_records(
        session,
        org_id=org_id,
        annotator_ids=[row.id for row in annotators],
        program_ids=[row.id for row in programs],
        as_of_end=as_of_end,
    )
    if records_truncated:
        limitations.append("Training record query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_training",
            DataQualityState.PARTIAL,
            "Training record query reached the configured row bound.",
        )

    selected_by_pair: dict[tuple[UUID, UUID], _TrainingRecordRow] = {}
    duplicate_pairs: set[tuple[UUID, UUID]] = set()
    for record in records:
        key = (record.annotator_id, record.training_program_id)
        if key in selected_by_pair:
            duplicate_pairs.add(key)
            continue
        selected_by_pair[key] = record

    if duplicate_pairs:
        _set_source_issue(
            issues_by_source,
            "workforce_training",
            DataQualityState.CONFLICTING,
            "Duplicate active training records exist for one or more assignments.",
        )
        limitations.append("Duplicate training records were resolved deterministically.")

    if not client_safe:
        for record in selected_by_pair.values():
            evidence.append(
                ClientEvidenceReference(
                    source_agent=SourceAgent.WORKFORCE_CAPABILITY,
                    source_table="training_records",
                    source_row_id=record.id,
                    description=_GENERIC_DESCRIPTION,
                    visibility=EvidenceVisibility.INTERNAL,
                    observed_at=record.created_at,
                    claim_keys=list(_TRAINING_CLAIM_KEYS),
                )
            )

    program_ids = {program.id for program in programs}
    annotator_ids = {annotator.id for annotator in annotators}
    required = len(annotators) * len(programs)
    completed = 0
    expired_or_failed = 0
    for annotator_id in annotator_ids:
        for program_id in program_ids:
            record = selected_by_pair.get((annotator_id, program_id))
            if record is not None and record.status == TrainingRecordStatus.COMPLETED:
                completed += 1
            if record is not None and is_expired_or_failed_training(
                SimpleNamespace(status=record.status)
            ):
                expired_or_failed += 1

    incomplete = required - completed
    completion_pct = (
        None
        if required == 0
        else _quantize_pct(Decimal(completed) / Decimal(required) * Decimal("100"))
    )

    _set_source_issue(
        issues_by_source,
        "workforce_training",
        DataQualityState.COMPLETE,
        "Mandatory training completion aggregates were computed.",
    )

    return (
        TrainingCompletionFacts(
            mandatory_program_count=len(programs),
            required_assignment_count=required,
            completed_assignment_count=completed,
            incomplete_assignment_count=incomplete,
            expired_or_failed_assignment_count=expired_or_failed,
            completion_pct=completion_pct,
            observed_at=None,
        ),
        limitations,
    )


async def _load_mandatory_programs(
    session: AsyncSession,
    *,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_ProgramRow], bool]:
    result = await session.execute(
        select(TrainingProgram.id)
        .where(
            TrainingProgram.org_id == org_id,
            TrainingProgram.is_mandatory.is_(True),
            TrainingProgram.deleted_at.is_(None),
            TrainingProgram.created_at <= as_of_end,
        )
        .order_by(TrainingProgram.id.asc())
        .limit(_MAX_TRAINING_PROGRAMS + 1)
    )
    rows = [_ProgramRow(id=row.id) for row in result.all()]
    return _trim_limit_plus_one(rows, _MAX_TRAINING_PROGRAMS)


async def _load_training_records(
    session: AsyncSession,
    *,
    org_id: UUID,
    annotator_ids: list[UUID],
    program_ids: list[UUID],
    as_of_end: datetime,
) -> tuple[list[_TrainingRecordRow], bool]:
    if not annotator_ids or not program_ids:
        return [], False
    result = await session.execute(
        select(
            TrainingRecord.id,
            TrainingRecord.annotator_id,
            TrainingRecord.training_program_id,
            TrainingRecord.status,
            TrainingRecord.created_at,
        )
        .where(
            TrainingRecord.org_id == org_id,
            TrainingRecord.annotator_id.in_(annotator_ids),
            TrainingRecord.training_program_id.in_(program_ids),
            TrainingRecord.deleted_at.is_(None),
            TrainingRecord.created_at <= as_of_end,
        )
        .order_by(
            TrainingRecord.annotator_id.asc(),
            TrainingRecord.training_program_id.asc(),
            TrainingRecord.created_at.desc(),
            TrainingRecord.id.desc(),
        )
        .limit(_MAX_TRAINING_RECORDS + 1)
    )
    rows: list[_TrainingRecordRow] = []
    for row in result.all():
        status = row.status
        if not isinstance(status, TrainingRecordStatus):
            status = TrainingRecordStatus(status)
        rows.append(
            _TrainingRecordRow(
                id=row.id,
                annotator_id=row.annotator_id,
                training_program_id=row.training_program_id,
                status=status,
                created_at=row.created_at,
            )
        )
    return _trim_limit_plus_one(rows, _MAX_TRAINING_RECORDS)


async def _build_capability_gaps(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
    client_safe: bool,
    evidence: list[ClientEvidenceReference],
    issues_by_source: dict[str, DataQualityIssue],
) -> tuple[list[CapabilityGapCountFacts], list[CapabilityGapFacts], list[str]]:
    limitations: list[str] = []
    visibility = _evidence_visibility(client_safe)

    gaps, gaps_truncated = await _load_open_gaps(
        session,
        project_id=project_id,
        org_id=org_id,
        as_of_end=as_of_end,
    )
    if gaps_truncated:
        limitations.append("Capability gap query reached the configured row bound.")
        _set_source_issue(
            issues_by_source,
            "workforce_capability_gaps",
            DataQualityState.PARTIAL,
            "Capability gap query reached the configured row bound.",
        )

    counts: dict[tuple[str, str], int] = defaultdict(int)
    open_gaps: list[CapabilityGapFacts] = []
    for gap in gaps:
        gap_type = _enum_str(gap.gap_type)
        severity = _enum_str(gap.severity)
        counts[(gap_type, severity)] += 1
        open_gaps.append(
            CapabilityGapFacts(
                gap_id=gap.id,
                gap_type=gap_type,
                severity=severity,
                status=_enum_str(gap.status),
                team_id=gap.team_id,
                skill_id=gap.skill_id,
                detected_at=gap.detected_at,
                resolved_at=gap.resolved_at,
                observed_at=gap.created_at,
            )
        )
        claim_keys = list(_GAP_COUNT_CLAIM_KEYS)
        if not client_safe:
            claim_keys.extend(
                [
                    "gap_id",
                    "gap_type",
                    "severity",
                    "status",
                    "team_id",
                    "skill_id",
                    "detected_at",
                    "resolved_at",
                ]
            )
        evidence.append(
            ClientEvidenceReference(
                source_agent=SourceAgent.WORKFORCE_CAPABILITY,
                source_table="capability_gaps",
                source_row_id=gap.id,
                description=_GENERIC_DESCRIPTION,
                visibility=visibility,
                observed_at=gap.created_at,
                claim_keys=claim_keys,
            )
        )

    gap_counts = [
        CapabilityGapCountFacts(gap_type=gap_type, severity=severity, count=count)
        for (gap_type, severity), count in sorted(counts.items(), key=lambda item: item[0])
    ]

    _set_source_issue(
        issues_by_source,
        "workforce_capability_gaps",
        DataQualityState.COMPLETE,
        (
            "Open capability-gap query succeeded; "
            f"{len(gaps)} unresolved gap(s) at or before as_of."
        ),
    )

    return gap_counts, open_gaps, limitations


async def _load_open_gaps(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    as_of_end: datetime,
) -> tuple[list[_GapRow], bool]:
    result = await session.execute(
        select(
            CapabilityGap.id,
            CapabilityGap.gap_type,
            CapabilityGap.severity,
            CapabilityGap.status,
            CapabilityGap.team_id,
            CapabilityGap.skill_id,
            CapabilityGap.detected_at,
            CapabilityGap.resolved_at,
            CapabilityGap.created_at,
        )
        .where(
            CapabilityGap.project_id == project_id,
            CapabilityGap.org_id == org_id,
            CapabilityGap.deleted_at.is_(None),
            CapabilityGap.status.in_(_OPEN_GAP_STATUSES),
            CapabilityGap.detected_at <= as_of_end,
        )
        .order_by(
            CapabilityGap.detected_at.desc(),
            CapabilityGap.id.desc(),
        )
        .limit(_MAX_CAPABILITY_GAPS + 1)
    )
    rows = [
        _GapRow(
            id=row.id,
            gap_type=row.gap_type,
            severity=row.severity,
            status=row.status,
            team_id=row.team_id,
            skill_id=row.skill_id,
            detected_at=row.detected_at,
            resolved_at=row.resolved_at,
            created_at=row.created_at,
        )
        for row in result.all()
    ]
    return _trim_limit_plus_one(rows, _MAX_CAPABILITY_GAPS)
