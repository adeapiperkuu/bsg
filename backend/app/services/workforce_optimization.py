"""Workforce Optimization engines (Phase 16).

Deterministic, evidence-backed recommendations for:
- Skill matching (person → staffing requirement)
- Workload rebalancing (transfer suggestions only — no auto-reassign)
- Resource planning (hiring / role headcount from roadmap + capacity)
- SME coverage (SPOF / succession / knowledge concentration)

All recommendations include confidence, reasoning, and RecommendationLineage.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import (
    Annotator,
    AnnotatorSkill,
    Certification,
    CertificationStatus,
    EmployeeCertification,
    Milestone,
    MilestoneStatus,
    ProficiencyLevel,
    Project,
    ProjectSkillRequirement,
    Skill,
    SkillRequirementPriority,
    Team,
    ThroughputSnapshot,
    UtilizationSnapshot,
)
from app.schemas.domain import (
    ResourcePlanningRecommendation,
    SkillMatchCandidate,
    SkillMatchRecommendation,
    SmeCoverageFinding,
    SmeCoverageRecommendation,
    UtilizationForecastPoint,
    WorkloadRebalanceRecommendation,
    WorkforceInsight,
    WorkforceOptimizationRead,
    WorkforcePriorityAction,
    WorkforceSkillShortage,
)
from app.schemas.recommendation_lineage import (
    RecommendationCalculation,
    RecommendationEvidenceItem,
    RecommendationSourceEntity,
    build_lineage,
)
from app.services.workforce import assert_can_read_annotators
from app.services.workforce_gaps import (
    UTILIZATION_OVERLOAD_THRESHOLD,
    UTILIZATION_UNDERLOAD_THRESHOLD,
)
from app.services.workforce_skills import PROFICIENCY_RANK, meets_proficiency

MODEL_VERSION = "workforce_optimization_v1"
TARGET_UTILIZATION = Decimal("75")
FORECAST_WEEKS = 4
OPEN_MILESTONE_STATUSES = {
    MilestoneStatus.PENDING,
    MilestoneStatus.ON_TRACK,
    MilestoneStatus.AT_RISK,
}
HIGH_PRIORITY = frozenset(
    {
        SkillRequirementPriority.HIGH.value,
        SkillRequirementPriority.CRITICAL.value,
        SkillRequirementPriority.HIGH,
        SkillRequirementPriority.CRITICAL,
    },
)


def _enum_value(value) -> str | None:
    """Normalize DB enum/Text columns that may arrive as StrEnum or plain str."""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _as_proficiency(value: ProficiencyLevel | str | None) -> ProficiencyLevel | None:
    if value is None:
        return None
    if isinstance(value, ProficiencyLevel):
        return value
    return ProficiencyLevel(str(value))


def _proficiency_rank(value: ProficiencyLevel | str) -> int:
    level = _as_proficiency(value)
    if level is None:
        return 0
    return PROFICIENCY_RANK[level]


def _meets_requirement(
    ctx: _OptimizationContext,
    annotator_id: UUID,
    requirement: ProjectSkillRequirement,
) -> bool:
    actual = _proficiency_for(ctx, annotator_id, requirement.skill_id)
    required = _as_proficiency(requirement.required_proficiency_level)
    if actual is None or required is None:
        return False
    return meets_proficiency(actual, required)


@dataclass
class _OptimizationContext:
    project: Project
    teams: list[Team]
    annotators: list[Annotator]
    skills_by_id: dict[UUID, Skill]
    requirements: list[ProjectSkillRequirement]
    assignments_by_annotator: dict[UUID, list[AnnotatorSkill]]
    certifications_by_annotator: dict[UUID, list[EmployeeCertification]]
    certification_defs: dict[UUID, Certification]
    utilization_by_team: dict[UUID, UtilizationSnapshot]
    utilization_by_annotator: dict[UUID, UtilizationSnapshot]
    milestones: list[Milestone]
    throughput: list[ThroughputSnapshot]
    teams_by_id: dict[UUID, Team] = field(default_factory=dict)
    annotators_by_id: dict[UUID, Annotator] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.teams_by_id = {team.id: team for team in self.teams}
        self.annotators_by_id = {a.id: a for a in self.annotators}


async def _load_optimization_context(
    session: AsyncSession,
    project: Project,
) -> _OptimizationContext:
    """Batch-load all inputs for optimization engines (avoids N+1)."""
    teams = list(
        (
            await session.execute(
                select(Team).where(
                    Team.project_id == project.id,
                    Team.deleted_at.is_(None),
                    Team.is_active.is_(True),
                ),
            )
        )
        .scalars()
        .all(),
    )
    team_ids = [team.id for team in teams]

    annotators: list[Annotator] = []
    if team_ids:
        annotators = list(
            (
                await session.execute(
                    select(Annotator).where(
                        Annotator.team_id.in_(team_ids),
                        Annotator.deleted_at.is_(None),
                        Annotator.is_active.is_(True),
                    ),
                )
            )
            .scalars()
            .all(),
        )

    requirements = list(
        (
            await session.execute(
                select(ProjectSkillRequirement).where(
                    ProjectSkillRequirement.project_id == project.id,
                    ProjectSkillRequirement.deleted_at.is_(None),
                ),
            )
        )
        .scalars()
        .all(),
    )

    skill_ids = {req.skill_id for req in requirements}
    skills_by_id: dict[UUID, Skill] = {}
    if skill_ids:
        skills = (
            await session.execute(
                select(Skill).where(Skill.id.in_(skill_ids), Skill.deleted_at.is_(None)),
            )
        ).scalars().all()
        skills_by_id = {skill.id: skill for skill in skills}

    annotator_ids = [a.id for a in annotators]
    assignments_by_annotator: dict[UUID, list[AnnotatorSkill]] = defaultdict(list)
    certifications_by_annotator: dict[UUID, list[EmployeeCertification]] = defaultdict(list)
    certification_defs: dict[UUID, Certification] = {}

    if annotator_ids:
        assignments = (
            await session.execute(
                select(AnnotatorSkill).where(
                    AnnotatorSkill.annotator_id.in_(annotator_ids),
                    AnnotatorSkill.deleted_at.is_(None),
                ),
            )
        ).scalars().all()
        for assignment in assignments:
            assignments_by_annotator[assignment.annotator_id].append(assignment)

        certs = (
            await session.execute(
                select(EmployeeCertification).where(
                    EmployeeCertification.annotator_id.in_(annotator_ids),
                    EmployeeCertification.deleted_at.is_(None),
                ),
            )
        ).scalars().all()
        cert_ids = {c.certification_id for c in certs}
        for cert in certs:
            certifications_by_annotator[cert.annotator_id].append(cert)
        if cert_ids:
            cert_defs = (
                await session.execute(
                    select(Certification).where(
                        Certification.id.in_(cert_ids),
                        Certification.deleted_at.is_(None),
                    ),
                )
            ).scalars().all()
            certification_defs = {c.id: c for c in cert_defs}

    utilization_rows = list(
        (
            await session.execute(
                select(UtilizationSnapshot)
                .where(
                    UtilizationSnapshot.project_id == project.id,
                    UtilizationSnapshot.deleted_at.is_(None),
                )
                .order_by(UtilizationSnapshot.snapshot_date.desc()),
            )
        )
        .scalars()
        .all(),
    )
    utilization_by_team: dict[UUID, UtilizationSnapshot] = {}
    utilization_by_annotator: dict[UUID, UtilizationSnapshot] = {}
    for row in utilization_rows:
        if row.annotator_id is not None:
            utilization_by_annotator.setdefault(row.annotator_id, row)
        elif row.team_id is not None:
            utilization_by_team.setdefault(row.team_id, row)

    milestones = list(
        (
            await session.execute(
                select(Milestone).where(
                    Milestone.project_id == project.id,
                    Milestone.deleted_at.is_(None),
                    Milestone.status.in_(OPEN_MILESTONE_STATUSES),
                )
                .order_by(Milestone.planned_date),
            )
        )
        .scalars()
        .all(),
    )

    throughput = list(
        (
            await session.execute(
                select(ThroughputSnapshot)
                .where(ThroughputSnapshot.project_id == project.id)
                .order_by(ThroughputSnapshot.snapshot_date.desc())
                .limit(30),
            )
        )
        .scalars()
        .all(),
    )

    return _OptimizationContext(
        project=project,
        teams=teams,
        annotators=annotators,
        skills_by_id=skills_by_id,
        requirements=requirements,
        assignments_by_annotator=dict(assignments_by_annotator),
        certifications_by_annotator=dict(certifications_by_annotator),
        certification_defs=certification_defs,
        utilization_by_team=utilization_by_team,
        utilization_by_annotator=utilization_by_annotator,
        milestones=milestones,
        throughput=throughput,
    )


def _proficiency_for(ctx: _OptimizationContext, annotator_id: UUID, skill_id: UUID) -> ProficiencyLevel | None:
    best: ProficiencyLevel | None = None
    for assignment in ctx.assignments_by_annotator.get(annotator_id, []):
        if assignment.skill_id != skill_id:
            continue
        level = _as_proficiency(assignment.proficiency_level)
        if level is None:
            continue
        if best is None or _proficiency_rank(level) > _proficiency_rank(best):
            best = level
    return best


def _annotator_utilization(ctx: _OptimizationContext, annotator: Annotator) -> Decimal | None:
    snap = ctx.utilization_by_annotator.get(annotator.id)
    if snap is not None:
        return snap.utilization_pct
    team_snap = ctx.utilization_by_team.get(annotator.team_id)
    if team_snap is not None:
        return team_snap.utilization_pct
    return None


def _availability_score(utilization: Decimal | None) -> float:
    if utilization is None:
        return 0.55  # unknown → moderate availability assumption
    pct = float(utilization)
    if pct >= 100:
        return 0.05
    if pct >= float(UTILIZATION_OVERLOAD_THRESHOLD):
        return 0.25
    if pct <= float(UTILIZATION_UNDERLOAD_THRESHOLD):
        return 1.0
    # Linear interpolate between underload and overload thresholds.
    span = float(UTILIZATION_OVERLOAD_THRESHOLD - UTILIZATION_UNDERLOAD_THRESHOLD)
    return max(0.0, min(1.0, (float(UTILIZATION_OVERLOAD_THRESHOLD) - pct) / span))


def _seniority_score(annotator: Annotator, assignments: list[AnnotatorSkill]) -> float:
    """Proxy seniority from SME flag + peak proficiency (no dedicated seniority column)."""
    if not assignments:
        base = 0.2
    else:
        peak = max(_proficiency_rank(a.proficiency_level) for a in assignments)
        base = peak / 4.0
    if annotator.is_sme_certified:
        base = min(1.0, base + 0.2)
    return base


def _active_cert_count(ctx: _OptimizationContext, annotator_id: UUID) -> int:
    today = date.today()
    count = 0
    for cert in ctx.certifications_by_annotator.get(annotator_id, []):
        status = _enum_value(cert.status)
        if status != CertificationStatus.ACTIVE.value:
            continue
        if cert.expires_at is not None and cert.expires_at < today:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# 16.1 Skill Matching
# ---------------------------------------------------------------------------


def _score_skill_match(
    ctx: _OptimizationContext,
    annotator: Annotator,
    requirement: ProjectSkillRequirement,
) -> SkillMatchCandidate | None:
    skill = ctx.skills_by_id.get(requirement.skill_id)
    if skill is None:
        return None

    assignments = ctx.assignments_by_annotator.get(annotator.id, [])
    actual = _proficiency_for(ctx, annotator.id, requirement.skill_id)
    required = _as_proficiency(requirement.required_proficiency_level)
    if required is None:
        return None
    utilization = _annotator_utilization(ctx, annotator)
    availability = _availability_score(utilization)
    seniority = _seniority_score(annotator, assignments)
    cert_count = _active_cert_count(ctx, annotator.id)
    team = ctx.teams_by_id.get(annotator.team_id)

    strengths: list[str] = []
    missing_skills: list[str] = []
    calculations: list[RecommendationCalculation] = []
    required_label = _enum_value(required) or ""
    actual_label = _enum_value(actual)

    if actual is not None and meets_proficiency(actual, required):
        skill_score = 1.0
        strengths.append(
            f"Meets {skill.name} at {actual_label} (required {required_label})",
        )
    elif actual is not None:
        skill_score = _proficiency_rank(actual) / _proficiency_rank(required)
        skill_score = min(0.85, skill_score)
        missing_skills.append(
            f"{skill.name} at {required_label} (has {actual_label})",
        )
    else:
        skill_score = 0.0
        missing_skills.append(f"{skill.name} at {required_label}")

    calculations.append(
        RecommendationCalculation(
            name="skill_proficiency_score",
            description="Proficiency match against project requirement",
            inputs={
                "required": required_label,
                "actual": actual_label,
            },
            result=round(skill_score, 3),
            formula="rank(actual)/rank(required) when below; 1.0 when meets",
        ),
    )

    # Experience proxy: number of verified skill assignments + proficiency breadth.
    experience_score = min(1.0, len(assignments) / max(3, len(ctx.requirements) or 3))
    if experience_score >= 0.6:
        strengths.append(f"Broad skill profile ({len(assignments)} skills)")

    cert_score = min(1.0, cert_count / 2.0) if cert_count else 0.15
    if cert_count > 0:
        strengths.append(f"{cert_count} active certification(s)")

    if annotator.is_sme_certified:
        strengths.append("SME certified")
        sme_bonus = 0.1
    else:
        sme_bonus = 0.0
        if requirement.required_sme_count > 0:
            missing_skills.append("SME certification")

    if utilization is not None and utilization <= UTILIZATION_UNDERLOAD_THRESHOLD:
        strengths.append(f"Available capacity ({float(utilization):.0f}% utilized)")
    elif utilization is not None and utilization >= UTILIZATION_OVERLOAD_THRESHOLD:
        missing_skills.append(f"Limited availability ({float(utilization):.0f}% utilized)")

    # Same-site preference (location).
    location_score = 1.0
    # Domain alignment (department proxy via team.domain vs skill.domain).
    domain_score = 0.5
    if team and skill.domain and team.domain and team.domain.lower() == skill.domain.lower():
        domain_score = 1.0
        strengths.append(f"Domain alignment ({team.domain})")

    match_score = (
        0.40 * skill_score
        + 0.15 * experience_score
        + 0.10 * seniority
        + 0.15 * availability
        + 0.10 * cert_score
        + 0.05 * domain_score
        + 0.05 * location_score
        + sme_bonus
    )
    match_score = max(0.0, min(1.0, match_score))

    # Confidence rises with data completeness.
    data_points = sum(
        [
            actual is not None,
            utilization is not None,
            cert_count > 0 or bool(ctx.certifications_by_annotator.get(annotator.id)),
            len(assignments) > 0,
        ],
    )
    confidence = 0.45 + 0.12 * data_points
    if skill_score == 0.0:
        confidence = min(confidence, 0.55)
    confidence = max(0.35, min(0.95, confidence))

    calculations.extend(
        [
            RecommendationCalculation(
                name="composite_match_score",
                description="Weighted skill/experience/seniority/availability/certs/domain",
                inputs={
                    "skill": round(skill_score, 3),
                    "experience": round(experience_score, 3),
                    "seniority": round(seniority, 3),
                    "availability": round(availability, 3),
                    "certs": round(cert_score, 3),
                    "domain": round(domain_score, 3),
                    "sme_bonus": sme_bonus,
                },
                result=round(match_score, 3),
                formula="0.4*skill + 0.15*exp + 0.1*sen + 0.15*avail + 0.1*cert + 0.05*domain + 0.05*loc + sme",
            ),
        ],
    )

    reasoning_parts = [
        f"{annotator.full_name} scored {match_score:.0%} for {skill.name}.",
    ]
    if strengths:
        reasoning_parts.append("Strengths: " + "; ".join(strengths[:3]) + ".")
    if missing_skills:
        reasoning_parts.append("Gaps: " + "; ".join(missing_skills[:3]) + ".")

    rec_id = f"skill-match:{annotator.id}:{requirement.id}"
    evidence = [
        RecommendationEvidenceItem(
            evidence_id=f"annotator:{annotator.id}",
            summary=f"Annotator {annotator.full_name} on team {team.name if team else 'unknown'}",
            source_entities=[
                RecommendationSourceEntity(
                    source_table="annotators",
                    source_row_id=annotator.id,
                    label=annotator.full_name,
                ),
            ],
            metric_keys=["utilization_pct", "proficiency_level"],
            observed_at=ctx.generated_at,
            visibility="internal",
        ),
        RecommendationEvidenceItem(
            evidence_id=f"requirement:{requirement.id}",
            summary=(
                f"Requires {requirement.required_headcount}× {skill.name} "
                f"at {required_label}"
            ),
            source_entities=[
                RecommendationSourceEntity(
                    source_table="project_skill_requirements",
                    source_row_id=requirement.id,
                    label=skill.name,
                ),
            ],
            metric_keys=["required_headcount", "required_proficiency_level"],
            observed_at=ctx.generated_at,
            visibility="internal",
        ),
    ]
    if utilization is not None:
        snap = ctx.utilization_by_annotator.get(annotator.id) or ctx.utilization_by_team.get(annotator.team_id)
        if snap is not None:
            evidence.append(
                RecommendationEvidenceItem(
                    evidence_id=f"utilization:{snap.id}",
                    summary=f"Utilization {float(utilization):.1f}% as of {snap.snapshot_date.isoformat()}",
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="utilization_snapshots",
                            source_row_id=snap.id,
                            label=f"{float(utilization):.1f}%",
                        ),
                    ],
                    metric_keys=["utilization_pct"],
                    observed_at=ctx.generated_at,
                    visibility="internal",
                ),
            )

    lineage = build_lineage(
        recommendation_id=rec_id,
        recommendation_type="skill_match",
        generated_at=ctx.generated_at,
        confidence_score=confidence,
        evidence=evidence,
        calculations=calculations,
        metrics_involved=["match_score", "utilization_pct", "proficiency_level"],
        related_entity_ids={
            "annotator_ids": [annotator.id],
            "skill_ids": [skill.id],
            "team_ids": [annotator.team_id],
            "requirement_ids": [requirement.id],
        },
        model_version=MODEL_VERSION,
    )

    return SkillMatchCandidate(
        annotator_id=annotator.id,
        annotator_name=annotator.full_name,
        team_id=annotator.team_id,
        team_name=team.name if team else None,
        site=_enum_value(annotator.site) or str(annotator.site),
        is_sme_certified=annotator.is_sme_certified,
        match_score=round(match_score, 3),
        confidence_score=round(confidence, 3),
        strengths=strengths,
        missing_skills=missing_skills,
        reasoning=" ".join(reasoning_parts),
        utilization_pct=float(utilization) if utilization is not None else None,
        proficiency_level=actual_label,
        active_certification_count=cert_count,
        lineage=lineage,
    )


def generate_skill_matches(
    ctx: _OptimizationContext,
    *,
    skill_id: UUID | None = None,
    limit_per_requirement: int = 5,
) -> list[SkillMatchRecommendation]:
    """Match available employees to project skill requirements."""
    results: list[SkillMatchRecommendation] = []
    requirements = ctx.requirements
    if skill_id is not None:
        requirements = [r for r in requirements if r.skill_id == skill_id]

    for requirement in requirements:
        skill = ctx.skills_by_id.get(requirement.skill_id)
        if skill is None:
            continue
        candidates: list[SkillMatchCandidate] = []
        for annotator in ctx.annotators:
            scored = _score_skill_match(ctx, annotator, requirement)
            if scored is not None and scored.match_score >= 0.35:
                candidates.append(scored)
        candidates.sort(key=lambda c: (c.match_score, c.confidence_score), reverse=True)
        top = candidates[:limit_per_requirement]
        if not top:
            continue
        shortfall = max(0, requirement.required_headcount - sum(
            1
            for a in ctx.annotators
            if _meets_requirement(ctx, a.id, requirement)
        ))
        results.append(
            SkillMatchRecommendation(
                skill_id=skill.id,
                skill_name=skill.name,
                required_proficiency_level=_enum_value(requirement.required_proficiency_level) or "",
                required_headcount=requirement.required_headcount,
                required_sme_count=requirement.required_sme_count,
                priority=_enum_value(requirement.priority) or "",
                headcount_shortfall=shortfall,
                candidates=top,
            ),
        )
    results.sort(key=lambda r: (0 if r.priority in {"critical", "high"} else 1, -r.headcount_shortfall))
    return results


# ---------------------------------------------------------------------------
# 16.2 Workload Rebalancing
# ---------------------------------------------------------------------------


def generate_rebalancing_recommendations(
    ctx: _OptimizationContext,
    *,
    limit: int = 10,
) -> list[WorkloadRebalanceRecommendation]:
    """Suggest employee transfers between overloaded and underutilized teams.

    Recommendations only — never mutates team membership.
    """
    overloaded: list[tuple[Team, UtilizationSnapshot]] = []
    underutilized: list[tuple[Team, UtilizationSnapshot]] = []
    for team in ctx.teams:
        snap = ctx.utilization_by_team.get(team.id)
        if snap is None:
            continue
        if snap.utilization_pct >= UTILIZATION_OVERLOAD_THRESHOLD:
            overloaded.append((team, snap))
        elif snap.utilization_pct <= UTILIZATION_UNDERLOAD_THRESHOLD:
            underutilized.append((team, snap))

    overloaded.sort(key=lambda pair: pair[1].utilization_pct, reverse=True)
    underutilized.sort(key=lambda pair: pair[1].utilization_pct)

    recommendations: list[WorkloadRebalanceRecommendation] = []
    used_annotators: set[UUID] = set()

    for source_team, source_snap in overloaded:
        if not underutilized:
            break
        source_members = [
            a
            for a in ctx.annotators
            if a.team_id == source_team.id and a.id not in used_annotators
        ]
        # Prefer transferring non-SME, higher-util or mid-skill members to protect coverage.
        source_members.sort(
            key=lambda a: (
                a.is_sme_certified,
                -(_annotator_utilization(ctx, a) or Decimal("0")),
            ),
        )
        for dest_team, dest_snap in underutilized:
            if source_team.id == dest_team.id:
                continue
            if not source_members:
                break
            candidate = source_members.pop(0)
            used_annotators.add(candidate.id)

            source_util = float(source_snap.utilization_pct)
            dest_util = float(dest_snap.utilization_pct)
            # Approximate: one FTE move shifts ~ (100 / team_size) points.
            source_size = max(1, sum(1 for a in ctx.annotators if a.team_id == source_team.id))
            dest_size = max(1, sum(1 for a in ctx.annotators if a.team_id == dest_team.id))
            source_delta = -round(100.0 / source_size, 1)
            dest_delta = round(100.0 / max(1, dest_size + 1), 1)
            improvement = abs(source_delta) + abs(
                min(float(TARGET_UTILIZATION) - dest_util, dest_delta),
            )

            risks: list[str] = []
            if candidate.is_sme_certified:
                risks.append("Transferring an SME may reduce source-team knowledge coverage")
            if source_team.site != dest_team.site:
                risks.append(
                    f"Cross-site move ({_enum_value(source_team.site)} → {_enum_value(dest_team.site)})",
                )
            if source_team.domain != dest_team.domain:
                risks.append(f"Domain change ({source_team.domain} → {dest_team.domain})")

            confidence = 0.7
            if not risks:
                confidence = 0.82
            elif len(risks) >= 2:
                confidence = 0.55
            if ctx.utilization_by_annotator.get(candidate.id) is None:
                confidence -= 0.08  # team-level util only

            rec_id = f"rebalance:{candidate.id}:{source_team.id}:{dest_team.id}"
            reasoning = (
                f"Move {candidate.full_name} from {source_team.name} "
                f"({source_util:.0f}% util) to {dest_team.name} ({dest_util:.0f}% util) "
                f"to reduce overload and absorb spare capacity. "
                f"Estimated combined utilization improvement ≈ {improvement:.1f} pts."
            )
            impact = (
                f"Source utilization expected {source_util:.0f}% → "
                f"{max(0.0, source_util + source_delta):.0f}%; "
                f"destination {dest_util:.0f}% → {min(120.0, dest_util + dest_delta):.0f}%."
            )

            evidence = [
                RecommendationEvidenceItem(
                    evidence_id=f"source-util:{source_snap.id}",
                    summary=f"{source_team.name} at {source_util:.1f}% (overload ≥ {float(UTILIZATION_OVERLOAD_THRESHOLD):.0f}%)",
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="utilization_snapshots",
                            source_row_id=source_snap.id,
                            label=source_team.name,
                        ),
                        RecommendationSourceEntity(
                            source_table="teams",
                            source_row_id=source_team.id,
                            label=source_team.name,
                        ),
                    ],
                    metric_keys=["utilization_pct"],
                    observed_at=ctx.generated_at,
                    visibility="internal",
                ),
                RecommendationEvidenceItem(
                    evidence_id=f"dest-util:{dest_snap.id}",
                    summary=f"{dest_team.name} at {dest_util:.1f}% (underload ≤ {float(UTILIZATION_UNDERLOAD_THRESHOLD):.0f}%)",
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="utilization_snapshots",
                            source_row_id=dest_snap.id,
                            label=dest_team.name,
                        ),
                        RecommendationSourceEntity(
                            source_table="teams",
                            source_row_id=dest_team.id,
                            label=dest_team.name,
                        ),
                    ],
                    metric_keys=["utilization_pct"],
                    observed_at=ctx.generated_at,
                    visibility="internal",
                ),
            ]
            calculations = [
                RecommendationCalculation(
                    name="utilization_improvement_estimate",
                    description="Estimated point improvement from one-FTE transfer",
                    inputs={
                        "source_size": source_size,
                        "dest_size": dest_size,
                        "source_util": source_util,
                        "dest_util": dest_util,
                    },
                    result=improvement,
                    formula="|100/source_size| + min(target-dest, 100/(dest_size+1))",
                ),
            ]
            lineage = build_lineage(
                recommendation_id=rec_id,
                recommendation_type="workload_rebalance",
                generated_at=ctx.generated_at,
                confidence_score=confidence,
                evidence=evidence,
                calculations=calculations,
                metrics_involved=["utilization_pct", "estimated_improvement_pts"],
                related_entity_ids={
                    "annotator_ids": [candidate.id],
                    "team_ids": [source_team.id, dest_team.id],
                },
                model_version=MODEL_VERSION,
            )

            recommendations.append(
                WorkloadRebalanceRecommendation(
                    recommendation_id=rec_id,
                    annotator_id=candidate.id,
                    annotator_name=candidate.full_name,
                    source_team_id=source_team.id,
                    source_team_name=source_team.name,
                    source_utilization_pct=source_util,
                    destination_team_id=dest_team.id,
                    destination_team_name=dest_team.name,
                    destination_utilization_pct=dest_util,
                    estimated_utilization_improvement=round(improvement, 2),
                    confidence_score=round(max(0.35, min(0.95, confidence)), 3),
                    risks=risks,
                    expected_business_impact=impact,
                    reasoning=reasoning,
                    lineage=lineage,
                ),
            )
            if len(recommendations) >= limit:
                return recommendations

    return recommendations


# ---------------------------------------------------------------------------
# 16.3 Resource Planning
# ---------------------------------------------------------------------------


def generate_resource_planning(
    ctx: _OptimizationContext,
) -> list[ResourcePlanningRecommendation]:
    """Hiring / role recommendations from requirements, milestones, and capacity."""
    recommendations: list[ResourcePlanningRecommendation] = []
    upcoming = [
        m
        for m in ctx.milestones
        if m.planned_date <= date.today() + timedelta(days=60)
    ]
    at_risk_milestones = [
        m for m in upcoming if _enum_value(m.status) == MilestoneStatus.AT_RISK.value
    ]

    # Delivery pressure from throughput forecast vs actual.
    delivery_pressure = 0.0
    if ctx.throughput:
        latest = ctx.throughput[0]
        if latest.units_forecast and latest.units_forecast > 0:
            ratio = latest.units_completed / latest.units_forecast
            if ratio < 0.85:
                delivery_pressure = 1.0 - ratio

    avg_team_util: float | None = None
    if ctx.utilization_by_team:
        avg_team_util = float(
            sum(s.utilization_pct for s in ctx.utilization_by_team.values())
            / len(ctx.utilization_by_team),
        )

    for requirement in ctx.requirements:
        skill = ctx.skills_by_id.get(requirement.skill_id)
        if skill is None:
            continue
        available = sum(
            1
            for a in ctx.annotators
            if _meets_requirement(ctx, a.id, requirement)
        )
        shortfall = requirement.required_headcount - available
        sme_available = sum(
            1
            for a in ctx.annotators
            if a.is_sme_certified and _meets_requirement(ctx, a.id, requirement)
        )
        sme_shortfall = max(0, requirement.required_sme_count - sme_available)

        if shortfall <= 0 and sme_shortfall <= 0:
            continue

        # Fractional PM / lead when many high-priority shortfalls + milestones.
        estimated_headcount = float(max(shortfall, 0))
        sme_only = sme_shortfall > 0 and shortfall <= 0
        if sme_only:
            estimated_headcount = float(sme_shortfall)

        urgency = "medium"
        hiring_priority = "medium"
        priority = _enum_value(requirement.priority)
        if priority in HIGH_PRIORITY or shortfall >= 2 or sme_only:
            urgency = "high"
            hiring_priority = "high"
        if priority == SkillRequirementPriority.CRITICAL.value or (
            at_risk_milestones and (shortfall >= 1 or sme_only)
        ):
            urgency = "critical"
            hiring_priority = "critical"
        if avg_team_util is not None and avg_team_util >= float(UTILIZATION_OVERLOAD_THRESHOLD):
            if urgency == "medium":
                urgency = "high"
            if hiring_priority == "medium":
                hiring_priority = "high"

        confidence = 0.6
        if available > 0 or shortfall > 0 or sme_shortfall > 0:
            confidence += 0.1
        if upcoming:
            confidence += 0.08
        if delivery_pressure > 0:
            confidence += 0.07
        confidence = min(0.92, confidence)

        role_label = skill.name
        if skill.category:
            role_label = f"{skill.name} ({skill.category})"
        if sme_only:
            role_label = f"SME for {role_label}"

        affected = [ctx.project.name]
        affected.extend(m.name for m in upcoming[:3])

        rec_id = f"resource-plan:{requirement.id}"
        if sme_only:
            reasoning = (
                f"Headcount for {skill.name} is met ({available}/"
                f"{requirement.required_headcount}), but SME coverage is "
                f"{sme_available}/{requirement.required_sme_count}. "
                f"Certify or hire {estimated_headcount:g} SME(s)."
            )
        else:
            reasoning = (
                f"Need {estimated_headcount:g}× {role_label} at "
                f"{_enum_value(requirement.required_proficiency_level)}. "
                f"Current coverage {available}/{requirement.required_headcount}"
            )
            if sme_shortfall:
                reasoning += f"; SME shortfall {sme_shortfall}"
        if at_risk_milestones:
            reasoning += f"; {len(at_risk_milestones)} at-risk milestone(s) within 60 days"
        if delivery_pressure > 0:
            reasoning += f"; delivery trailing forecast by {delivery_pressure:.0%}"
        reasoning += "."

        evidence = [
            RecommendationEvidenceItem(
                evidence_id=f"req:{requirement.id}",
                summary=(
                    f"Requirement {requirement.required_headcount} headcount / "
                    f"{requirement.required_sme_count} SME for {skill.name}"
                ),
                source_entities=[
                    RecommendationSourceEntity(
                        source_table="project_skill_requirements",
                        source_row_id=requirement.id,
                        label=skill.name,
                        attributes={
                            "required_headcount": requirement.required_headcount,
                            "available": available,
                            "shortfall": shortfall,
                        },
                    ),
                ],
                metric_keys=["required_headcount", "available_headcount", "shortfall"],
                observed_at=ctx.generated_at,
                visibility="internal",
            ),
        ]
        for milestone in upcoming[:5]:
            evidence.append(
                RecommendationEvidenceItem(
                    evidence_id=f"milestone:{milestone.id}",
                    summary=f"Milestone '{milestone.name}' ({_enum_value(milestone.status)}) on {milestone.planned_date.isoformat()}",
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="milestones",
                            source_row_id=milestone.id,
                            label=milestone.name,
                        ),
                    ],
                    metric_keys=["planned_date", "milestone_status"],
                    observed_at=ctx.generated_at,
                    visibility="internal",
                ),
            )
        if ctx.throughput:
            latest = ctx.throughput[0]
            evidence.append(
                RecommendationEvidenceItem(
                    evidence_id=f"throughput:{latest.id}",
                    summary=(
                        f"Throughput {latest.units_completed}"
                        + (f"/{latest.units_forecast} forecast" if latest.units_forecast else "")
                        + f" on {latest.snapshot_date.isoformat()}"
                    ),
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="throughput_snapshots",
                            source_row_id=latest.id,
                            label="throughput",
                        ),
                    ],
                    metric_keys=["units_completed", "units_forecast"],
                    observed_at=ctx.generated_at,
                    visibility="internal",
                ),
            )

        calculations = [
            RecommendationCalculation(
                name="headcount_shortfall",
                description="Required headcount minus qualified available annotators",
                inputs={
                    "required_headcount": requirement.required_headcount,
                    "available": available,
                    "sme_required": requirement.required_sme_count,
                    "sme_available": sme_available,
                },
                result=estimated_headcount,
                formula="max(required - available, sme_required - sme_available)",
            ),
        ]
        lineage = build_lineage(
            recommendation_id=rec_id,
            recommendation_type="resource_planning",
            generated_at=ctx.generated_at,
            confidence_score=confidence,
            evidence=evidence,
            calculations=calculations,
            metrics_involved=[
                "required_headcount",
                "available_headcount",
                "utilization_pct",
                "units_completed",
                "units_forecast",
            ],
            related_entity_ids={
                "skill_ids": [skill.id],
                "requirement_ids": [requirement.id],
                "milestone_ids": [m.id for m in upcoming[:5]],
            },
            model_version=MODEL_VERSION,
        )

        recommendations.append(
            ResourcePlanningRecommendation(
                recommendation_id=rec_id,
                role=role_label,
                skill_id=skill.id,
                skill_name=skill.name,
                estimated_headcount=estimated_headcount,
                hiring_priority=hiring_priority,
                urgency=urgency,
                confidence_score=round(confidence, 3),
                affected_projects=affected,
                reasoning=reasoning,
                required_proficiency_level=_enum_value(requirement.required_proficiency_level),
                current_available=available,
                current_shortfall=max(0, shortfall),
                sme_shortfall=sme_shortfall,
                lineage=lineage,
            ),
        )

    # Suggest fractional PM when many critical gaps + at-risk milestones.
    critical_count = sum(1 for r in recommendations if r.urgency == "critical")
    if critical_count >= 2 or (critical_count >= 1 and at_risk_milestones):
        rec_id = f"resource-plan:pm:{ctx.project.id}"
        confidence = 0.62
        reasoning = (
            "Multiple critical staffing gaps with upcoming delivery pressure suggest "
            "0.5 Project Manager capacity for coordination and ramp oversight."
        )
        lineage = build_lineage(
            recommendation_id=rec_id,
            recommendation_type="resource_planning",
            generated_at=ctx.generated_at,
            confidence_score=confidence,
            evidence=[
                RecommendationEvidenceItem(
                    evidence_id=f"critical-gaps:{ctx.project.id}",
                    summary=f"{critical_count} critical role gaps; {len(at_risk_milestones)} at-risk milestones",
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="projects",
                            source_row_id=ctx.project.id,
                            label=ctx.project.name,
                        ),
                    ],
                    metric_keys=["critical_gap_count", "at_risk_milestone_count"],
                    observed_at=ctx.generated_at,
                    visibility="internal",
                ),
            ],
            calculations=[
                RecommendationCalculation(
                    name="coordination_overhead",
                    description="Fractional PM when ≥2 critical gaps or gap+at-risk milestone",
                    inputs={"critical_gaps": critical_count, "at_risk_milestones": len(at_risk_milestones)},
                    result=0.5,
                ),
            ],
            metrics_involved=["critical_gap_count"],
            related_entity_ids={"project_ids": [ctx.project.id]},
            model_version=MODEL_VERSION,
        )
        recommendations.append(
            ResourcePlanningRecommendation(
                recommendation_id=rec_id,
                role="Project Manager",
                skill_id=None,
                skill_name=None,
                estimated_headcount=0.5,
                hiring_priority="high",
                urgency="high",
                confidence_score=confidence,
                affected_projects=[ctx.project.name],
                reasoning=reasoning,
                required_proficiency_level=None,
                current_available=0,
                current_shortfall=0,
                sme_shortfall=0,
                lineage=lineage,
            ),
        )

    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda r: (priority_rank.get(r.urgency, 9), -r.estimated_headcount))
    return recommendations


# ---------------------------------------------------------------------------
# 16.4 SME Coverage
# ---------------------------------------------------------------------------


def generate_sme_coverage(
    ctx: _OptimizationContext,
) -> list[SmeCoverageRecommendation]:
    """Identify SPOFs, missing backups, and succession / concentration risks."""
    recommendations: list[SmeCoverageRecommendation] = []

    for requirement in ctx.requirements:
        skill = ctx.skills_by_id.get(requirement.skill_id)
        if skill is None:
            continue
        if requirement.required_sme_count <= 0 and not skill.is_critical:
            continue

        qualified_smes = [
            a
            for a in ctx.annotators
            if a.is_sme_certified and _meets_requirement(ctx, a.id, requirement)
        ]
        qualified_non_sme = [
            a
            for a in ctx.annotators
            if not a.is_sme_certified and _meets_requirement(ctx, a.id, requirement)
        ]
        # Near-backup: one proficiency level below or same skill without SME flag.
        near_backups = [
            a
            for a in ctx.annotators
            if a.id not in {s.id for s in qualified_smes}
            and _proficiency_for(ctx, a.id, requirement.skill_id) is not None
        ]

        findings: list[SmeCoverageFinding] = []
        actions: list[str] = []

        if len(qualified_smes) == 0 and (requirement.required_sme_count > 0 or skill.is_critical):
            findings.append(
                SmeCoverageFinding(
                    finding_type="missing_sme",
                    severity="critical",
                    summary=f"No SME covers critical skill {skill.name}",
                ),
            )
            actions.extend(["Assign backup SME", "Cross-train employees", "Increase documentation"])
        elif len(qualified_smes) == 1:
            sme = qualified_smes[0]
            findings.append(
                SmeCoverageFinding(
                    finding_type="single_point_of_failure",
                    severity="high",
                    summary=f"{sme.full_name} is the sole SME for {skill.name}",
                    annotator_id=sme.id,
                    annotator_name=sme.full_name,
                ),
            )
            actions.extend(["Assign backup SME", "Cross-train employees", "Rotate ownership"])
            if not near_backups:
                findings.append(
                    SmeCoverageFinding(
                        finding_type="missing_backup",
                        severity="high",
                        summary=f"No backup candidate identified for {skill.name}",
                    ),
                )
                actions.append("Increase documentation")
            findings.append(
                SmeCoverageFinding(
                    finding_type="succession_risk",
                    severity="medium",
                    summary=f"Succession risk if {sme.full_name} is unavailable",
                    annotator_id=sme.id,
                    annotator_name=sme.full_name,
                ),
            )
        elif len(qualified_smes) < requirement.required_sme_count:
            findings.append(
                SmeCoverageFinding(
                    finding_type="sme_shortage",
                    severity="medium",
                    summary=(
                        f"SME coverage {len(qualified_smes)}/{requirement.required_sme_count} "
                        f"for {skill.name}"
                    ),
                ),
            )
            actions.append("Assign backup SME")

        # Knowledge concentration: one person holds majority of advanced+ skills on a team.
        if len(qualified_smes) == 1 and len(qualified_non_sme) <= 1:
            findings.append(
                SmeCoverageFinding(
                    finding_type="knowledge_concentration",
                    severity="medium",
                    summary=f"Knowledge for {skill.name} concentrated in very few people",
                    annotator_id=qualified_smes[0].id if qualified_smes else None,
                    annotator_name=qualified_smes[0].full_name if qualified_smes else None,
                ),
            )
            if "Increase documentation" not in actions:
                actions.append("Increase documentation")
            if "Cross-train employees" not in actions:
                actions.append("Cross-train employees")

        if not findings:
            continue

        # Deduplicate actions preserving order.
        seen_actions: set[str] = set()
        unique_actions: list[str] = []
        for action in actions:
            if action not in seen_actions:
                seen_actions.add(action)
                unique_actions.append(action)

        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        top_severity = min(findings, key=lambda f: severity_rank.get(f.severity, 9)).severity
        confidence = 0.78 if qualified_smes or requirement.required_sme_count else 0.65
        if skill.is_critical:
            confidence = min(0.92, confidence + 0.05)

        rec_id = f"sme-coverage:{requirement.id}"
        reasoning = (
            f"{skill.name}: {len(qualified_smes)} SME(s), "
            f"{len(near_backups)} near-backup candidate(s). "
            + "; ".join(f.summary for f in findings[:2])
            + "."
        )

        evidence = [
            RecommendationEvidenceItem(
                evidence_id=f"sme-req:{requirement.id}",
                summary=(
                    f"Required SME count {requirement.required_sme_count}; "
                    f"qualified SMEs {len(qualified_smes)}"
                ),
                source_entities=[
                    RecommendationSourceEntity(
                        source_table="project_skill_requirements",
                        source_row_id=requirement.id,
                        label=skill.name,
                    ),
                    *[
                        RecommendationSourceEntity(
                            source_table="annotators",
                            source_row_id=sme.id,
                            label=sme.full_name,
                            attributes={"is_sme_certified": True},
                        )
                        for sme in qualified_smes
                    ],
                ],
                metric_keys=["required_sme_count", "available_sme_count"],
                observed_at=ctx.generated_at,
                visibility="internal",
            ),
        ]
        lineage = build_lineage(
            recommendation_id=rec_id,
            recommendation_type="sme_coverage",
            generated_at=ctx.generated_at,
            confidence_score=confidence,
            evidence=evidence,
            calculations=[
                RecommendationCalculation(
                    name="sme_coverage_ratio",
                    description="Qualified SMEs vs required SME count",
                    inputs={
                        "required": requirement.required_sme_count,
                        "qualified": len(qualified_smes),
                        "near_backups": len(near_backups),
                    },
                    result=len(qualified_smes) / max(1, requirement.required_sme_count or 1),
                ),
            ],
            metrics_involved=["required_sme_count", "available_sme_count"],
            related_entity_ids={
                "skill_ids": [skill.id],
                "annotator_ids": [s.id for s in qualified_smes],
            },
            model_version=MODEL_VERSION,
        )

        recommendations.append(
            SmeCoverageRecommendation(
                recommendation_id=rec_id,
                skill_id=skill.id,
                skill_name=skill.name,
                severity=top_severity,
                confidence_score=round(confidence, 3),
                findings=findings,
                recommended_actions=unique_actions,
                sme_count=len(qualified_smes),
                required_sme_count=requirement.required_sme_count,
                backup_candidate_count=len(near_backups),
                reasoning=reasoning,
                lineage=lineage,
            ),
        )

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda r: (severity_rank.get(r.severity, 9), -r.confidence_score))
    return recommendations


# ---------------------------------------------------------------------------
# Forecast + shortages + insights (16.5 helpers)
# ---------------------------------------------------------------------------


def _utilization_forecast(ctx: _OptimizationContext) -> list[UtilizationForecastPoint]:
    """Simple linear projection from latest team utilization toward target."""
    if not ctx.utilization_by_team:
        return []
    avg = float(
        sum(s.utilization_pct for s in ctx.utilization_by_team.values())
        / len(ctx.utilization_by_team),
    )
    points: list[UtilizationForecastPoint] = []
    today = date.today()
    # Drift 15% of the gap toward target each week (stabilizing forecast).
    current = avg
    for week in range(FORECAST_WEEKS + 1):
        points.append(
            UtilizationForecastPoint(
                week_offset=week,
                forecast_date=(today + timedelta(weeks=week)).isoformat(),
                projected_utilization_pct=round(current, 1),
                confidence_score=round(max(0.4, 0.85 - week * 0.08), 2),
            ),
        )
        gap = float(TARGET_UTILIZATION) - current
        current = current + gap * 0.15
    return points


def _skill_shortages(ctx: _OptimizationContext) -> list[WorkforceSkillShortage]:
    shortages: list[WorkforceSkillShortage] = []
    for requirement in ctx.requirements:
        skill = ctx.skills_by_id.get(requirement.skill_id)
        if skill is None:
            continue
        available = sum(
            1
            for a in ctx.annotators
            if _meets_requirement(ctx, a.id, requirement)
        )
        shortfall = requirement.required_headcount - available
        if shortfall <= 0:
            continue
        severity = "medium"
        priority = _enum_value(requirement.priority) or ""
        if priority in {SkillRequirementPriority.HIGH.value, SkillRequirementPriority.CRITICAL.value} or shortfall >= 2:
            severity = "high"
        if priority == SkillRequirementPriority.CRITICAL.value:
            severity = "critical"
        shortages.append(
            WorkforceSkillShortage(
                skill_id=skill.id,
                skill_name=skill.name,
                required_headcount=requirement.required_headcount,
                available_headcount=available,
                shortfall=shortfall,
                severity=severity,
                priority=priority,
            ),
        )
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    shortages.sort(key=lambda s: (severity_rank.get(s.severity, 9), -s.shortfall))
    return shortages


def _build_insights(
    *,
    skill_matches: list[SkillMatchRecommendation],
    rebalancing: list[WorkloadRebalanceRecommendation],
    planning: list[ResourcePlanningRecommendation],
    sme: list[SmeCoverageRecommendation],
    shortages: list[WorkforceSkillShortage],
    forecast: list[UtilizationForecastPoint],
    team_count: int = 0,
) -> list[WorkforceInsight]:
    """Build a de-duplicated insight list aligned with matrix / util / gaps."""
    insights: list[WorkforceInsight] = []
    covered_skills: set[str] = set()

    if rebalancing:
        top = rebalancing[0]
        insights.append(
            WorkforceInsight(
                insight_id=f"insight-rebalance-{top.recommendation_id}",
                category="rebalancing",
                urgency="high",
                title="Workload imbalance detected",
                detail=(
                    f"Transfer {top.annotator_name} from {top.source_team_name} "
                    f"({top.source_utilization_pct:.0f}%) to {top.destination_team_name} "
                    f"({top.destination_utilization_pct:.0f}%)."
                ),
                confidence_score=top.confidence_score,
                related_recommendation_ids=[top.recommendation_id],
            ),
        )
    elif team_count <= 1 and forecast and forecast[0].projected_utilization_pct >= float(
        UTILIZATION_OVERLOAD_THRESHOLD,
    ):
        insights.append(
            WorkforceInsight(
                insight_id="insight-util-single-team",
                category="utilization_forecast",
                urgency="high",
                title="Team utilization above capacity",
                detail=(
                    f"Average utilization is {forecast[0].projected_utilization_pct:.0f}% "
                    f"(threshold {float(UTILIZATION_OVERLOAD_THRESHOLD):.0f}%). "
                    "Add a second team or hire capacity before rebalancing is possible."
                ),
                confidence_score=forecast[0].confidence_score,
                related_recommendation_ids=[],
            ),
        )

    critical_sme = [r for r in sme if r.severity in {"critical", "high"}]
    if critical_sme:
        top = critical_sme[0]
        covered_skills.add(top.skill_name.lower())
        insights.append(
            WorkforceInsight(
                insight_id=f"insight-sme-{top.recommendation_id}",
                category="sme_coverage",
                urgency=top.severity if top.severity in {"critical", "high"} else "medium",
                title=f"SME risk: {top.skill_name}",
                detail=(
                    f"SMEs {top.sme_count}/{top.required_sme_count} · "
                    f"{top.backup_candidate_count} backup candidate(s). "
                    + (top.recommended_actions[0] if top.recommended_actions else top.reasoning)
                ),
                confidence_score=top.confidence_score,
                related_recommendation_ids=[top.recommendation_id],
            ),
        )

    # Prefer hiring recommendations for shortfalls; skip a separate shortage card
    # when hiring already covers the same skill (avoids duplicate Critical rows).
    if planning:
        top = planning[0]
        skill_key = (top.skill_name or top.role).lower()
        covered_skills.add(skill_key)
        available = top.current_available
        needed = available + top.current_shortfall
        coverage = (
            f"Coverage {available}/{needed}"
            if top.current_shortfall > 0
            else top.reasoning
        )
        insights.append(
            WorkforceInsight(
                insight_id=f"insight-hire-{top.recommendation_id}",
                category="hiring",
                urgency=top.urgency if top.urgency in {"critical", "high", "medium"} else "medium",
                title=f"Hire {top.estimated_headcount:g}× {top.role}",
                detail=coverage if top.current_shortfall > 0 else top.reasoning,
                confidence_score=top.confidence_score,
                related_recommendation_ids=[top.recommendation_id],
            ),
        )

    for shortage in shortages:
        if shortage.skill_name.lower() in covered_skills:
            continue
        covered_skills.add(shortage.skill_name.lower())
        insights.append(
            WorkforceInsight(
                insight_id=f"insight-shortage-{shortage.skill_id}",
                category="skill_shortage",
                urgency=(
                    shortage.severity
                    if shortage.severity in {"critical", "high", "medium"}
                    else "medium"
                ),
                title=f"Skill shortage: {shortage.skill_name}",
                detail=(
                    f"Coverage {shortage.available_headcount}/{shortage.required_headcount} "
                    f"(short {shortage.shortfall})."
                ),
                confidence_score=0.8,
                related_recommendation_ids=[],
            ),
        )
        break  # one additional shortage max — rest live in the shortages list

    # Only promote strong matches (≥50%) so weak candidates aren't framed as staffing solutions.
    match_with_candidates = [
        m
        for m in skill_matches
        if m.headcount_shortfall > 0
        and m.candidates
        and m.candidates[0].match_score >= 0.5
    ]
    if match_with_candidates:
        top = match_with_candidates[0]
        best = top.candidates[0]
        insights.append(
            WorkforceInsight(
                insight_id=f"insight-match-{top.skill_id}",
                category="skill_match",
                urgency="medium",
                title=f"Staffing candidate: {top.skill_name}",
                detail=(
                    f"{best.annotator_name} match {best.match_score:.0%} · "
                    f"coverage shortfall {top.headcount_shortfall} "
                    f"(need {top.required_headcount})."
                ),
                confidence_score=best.confidence_score,
                related_recommendation_ids=[],
            ),
        )

    if (
        forecast
        and forecast[0].projected_utilization_pct >= float(UTILIZATION_OVERLOAD_THRESHOLD)
        and not any(i.category == "utilization_forecast" for i in insights)
        and not rebalancing
    ):
        insights.append(
            WorkforceInsight(
                insight_id="insight-util-forecast",
                category="utilization_forecast",
                urgency="high",
                title="Utilization above capacity threshold",
                detail=(
                    f"Current average {forecast[0].projected_utilization_pct:.0f}% "
                    f"(threshold {float(UTILIZATION_OVERLOAD_THRESHOLD):.0f}%). "
                    f"Projected to ease toward {forecast[-1].projected_utilization_pct:.0f}% "
                    f"over {FORECAST_WEEKS} weeks without action."
                ),
                confidence_score=forecast[0].confidence_score,
                related_recommendation_ids=[],
            ),
        )

    urgency_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    insights.sort(key=lambda i: (urgency_rank.get(i.urgency, 9), -i.confidence_score))
    return insights


def _priority_actions(insights: list[WorkforceInsight], limit: int = 4) -> list[WorkforcePriorityAction]:
    """Top urgent actions only — keep the strip short and non-duplicative."""
    actions: list[WorkforcePriorityAction] = []
    seen_categories: set[str] = set()
    for insight in insights:
        # One card per category in the priority strip.
        if insight.category in seen_categories:
            continue
        if insight.urgency not in {"critical", "high"} and len(actions) >= 2:
            continue
        seen_categories.add(insight.category)
        actions.append(
            WorkforcePriorityAction(
                action_id=f"action-{insight.insight_id}",
                title=insight.title,
                detail=insight.detail,
                urgency=insight.urgency,
                category=insight.category,
                confidence_score=insight.confidence_score,
            ),
        )
        if len(actions) >= limit:
            break
    return actions


# ---------------------------------------------------------------------------
# Public orchestration
# ---------------------------------------------------------------------------


async def build_workforce_optimization(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    skill_id: UUID | None = None,
) -> WorkforceOptimizationRead:
    """Run all Phase 16 engines and assemble the optimization dashboard payload."""
    assert_can_read_annotators(current_user)
    ctx = await _load_optimization_context(session, project)

    skill_matches = generate_skill_matches(ctx, skill_id=skill_id)
    rebalancing = generate_rebalancing_recommendations(ctx)
    planning = generate_resource_planning(ctx)
    sme = generate_sme_coverage(ctx)
    forecast = _utilization_forecast(ctx)
    shortages = _skill_shortages(ctx)
    insights = _build_insights(
        skill_matches=skill_matches,
        rebalancing=rebalancing,
        planning=planning,
        sme=sme,
        shortages=shortages,
        forecast=forecast,
        team_count=len(ctx.teams),
    )
    priority_actions = _priority_actions(insights)

    return WorkforceOptimizationRead(
        project_id=project.id,
        generated_at=ctx.generated_at,
        skill_matches=skill_matches,
        rebalancing=rebalancing,
        resource_planning=planning,
        sme_coverage=sme,
        utilization_forecast=forecast,
        skill_shortages=shortages,
        insights=insights,
        priority_actions=priority_actions,
    )
