"""Workforce & Capability Agent: evidence-backed internal Q&A.

This agent answers internal workforce/capability questions using deterministic,
aggregated evidence from Workforce-owned tables. It never exposes individual
annotator names and redirects out-of-scope questions to the owning agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AlertType,
    Annotator,
    AppRole,
    CapabilityGap,
    MitigationRecommendation,
    Project,
    ProjectSkillRequirement,
    RiskAlert,
    Team,
    UtilizationSnapshot,
)
from app.schemas.domain import AgentQueryCreate
from app.services.evidence import EvidenceInput
from app.services.scoping import get_visible_project
from app.services.workforce import can_read_annotators
from app.services.workforce_gaps import (
    OPEN_GAP_STATUSES,
    UTILIZATION_OVERLOAD_THRESHOLD,
    UTILIZATION_UNDERLOAD_THRESHOLD,
)
from app.services.workforce_skills import build_project_skill_matrix
from app.services.workforce_training import build_project_training_gaps

WORKFORCE_AGENT_NAME = "workforce_capability_agent"

# Utilization snapshots older than this many days are treated as stale.
UTILIZATION_STALE_DAYS = 14

INSUFFICIENT_DATA_MESSAGE = (
    "There is not enough workforce evidence to answer this question. "
    "Add teams, utilization snapshots, skill requirements, or run capability gap "
    "detection for the selected project, then ask again."
)

PROJECT_REQUIRED_MESSAGE = (
    "Select a project so the Workforce Agent can scope evidence to that engagement, "
    "then ask the question again."
)


@dataclass(frozen=True)
class WorkforceRedirect:
    target_agent: str
    message: str


# Out-of-scope routing. Order matters: the first matching rule wins.
_REDIRECT_RULES: tuple[tuple[WorkforceRedirect, tuple[str, ...]], ...] = (
    (
        WorkforceRedirect(
            "Delivery Performance Agent",
            "Delivery confidence and milestone slippage are owned by the Delivery "
            "Performance Agent. Please ask that agent for delivery confidence questions.",
        ),
        (
            "delivery confidence",
            "milestone confidence",
            "slippage",
            "will we hit the deadline",
            "on track to deliver",
            "delivery forecast",
        ),
    ),
    (
        WorkforceRedirect(
            "Quality Intelligence Agent",
            "Quality drift and error-rate trends are owned by the Quality Intelligence "
            "Agent. Please ask that agent for quality questions.",
        ),
        (
            "quality drift",
            "error rate",
            "defect rate",
            "rework rate",
            "quality score",
            "gold set",
        ),
    ),
    (
        WorkforceRedirect(
            "Client Interaction Agent",
            "Client-facing communications are owned by the Client Interaction Agent. "
            "Please ask that agent to draft or review client communications.",
        ),
        (
            "client email",
            "email the client",
            "client update",
            "client communication",
            "draft a message",
            "csat",
        ),
    ),
    (
        WorkforceRedirect(
            "Operational Knowledge Agent",
            "SOPs and document retrieval are owned by the Operational Knowledge Agent. "
            "Please ask that agent to find policies, SOPs, or documents.",
        ),
        (
            "sop",
            "standard operating procedure",
            "document",
            "policy doc",
            "knowledge base",
            "where is the doc",
        ),
    ),
)


def classify_workforce_question(question: str) -> WorkforceRedirect | None:
    """Return a redirect when the question is owned by another agent."""
    lowered = question.lower()
    for redirect, keywords in _REDIRECT_RULES:
        if any(keyword in lowered for keyword in keywords):
            return redirect
    return None


@dataclass
class WorkforceMetrics:
    active_annotators: int = 0
    sme_count: int = 0
    sme_coverage_pct: int | None = None
    team_count: int = 0
    teams_overloaded: int = 0
    teams_underloaded: int = 0
    team_utilization: list[tuple[str, float]] = field(default_factory=list)
    has_utilization_data: bool = False
    latest_utilization_date: date | None = None
    utilization_age_days: int | None = None
    utilization_stale: bool = False
    skill_requirements: int = 0
    skill_low_coverage: int = 0
    low_coverage_skills: list[str] = field(default_factory=list)
    has_skill_matrix_coverage: bool = False
    has_training_data: bool = False
    training_total_gaps: int = 0
    mandatory_training_incomplete: int = 0
    expired_or_failed_training: int = 0
    expired_certifications: int = 0
    pending_certification_reviews: int = 0
    open_capability_gaps: int = 0
    high_critical_gaps: int = 0
    top_capability_gaps: list[str] = field(default_factory=list)
    workforce_risk_alerts: int = 0
    workforce_recommendations: int = 0
    recommendation_titles: list[str] = field(default_factory=list)


@dataclass
class WorkforceEvidenceBundle:
    project_id: UUID | None
    project_name: str | None
    metrics: WorkforceMetrics
    evidence: list[EvidenceInput]

    @property
    def has_data(self) -> bool:
        return bool(self.evidence) and self.metrics.team_count > 0


def _utilization_value(snapshot: UtilizationSnapshot) -> float:
    try:
        return float(snapshot.utilization_pct)
    except (TypeError, ValueError):
        return 0.0


async def gather_workforce_evidence(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> WorkforceEvidenceBundle:
    """Collect deterministic, aggregated, org/project-scoped workforce evidence."""
    metrics = WorkforceMetrics()
    evidence: list[EvidenceInput] = [
        EvidenceInput(
            source_table="projects",
            source_row_id=project.id,
            description=f"Workforce evidence scoped to project '{project.name}'.",
        )
    ]

    teams = (
        await session.execute(
            select(Team).where(Team.project_id == project.id, Team.deleted_at.is_(None)),
        )
    ).scalars().all()
    metrics.team_count = len(teams)
    team_ids = [team.id for team in teams]
    team_names = {team.id: team.name for team in teams}
    for team in teams[:3]:
        evidence.append(
            EvidenceInput(
                source_table="teams",
                source_row_id=team.id,
                description=f"Team '{team.name}' ({team.site.value}).",
            )
        )

    if team_ids:
        annotators = (
            await session.execute(
                select(Annotator).where(
                    Annotator.team_id.in_(team_ids),
                    Annotator.deleted_at.is_(None),
                    Annotator.is_active.is_(True),
                ),
            )
        ).scalars().all()
        # Aggregated only - never cite or expose individual annotators.
        metrics.active_annotators = len(annotators)
        metrics.sme_count = sum(1 for a in annotators if a.is_sme_certified)
        if metrics.active_annotators > 0:
            metrics.sme_coverage_pct = round(
                metrics.sme_count / metrics.active_annotators * 100
            )

    # Latest team-level utilization snapshot per team (annotator_id is None).
    snapshots = (
        await session.execute(
            select(UtilizationSnapshot)
            .where(
                UtilizationSnapshot.project_id == project.id,
                UtilizationSnapshot.deleted_at.is_(None),
                UtilizationSnapshot.team_id.is_not(None),
                UtilizationSnapshot.annotator_id.is_(None),
            )
            .order_by(
                UtilizationSnapshot.team_id,
                UtilizationSnapshot.snapshot_date.desc(),
                UtilizationSnapshot.created_at.desc(),
            ),
        )
    ).scalars().all()
    latest_by_team: dict[UUID, UtilizationSnapshot] = {}
    for snapshot in snapshots:
        if snapshot.team_id is not None and snapshot.team_id not in latest_by_team:
            latest_by_team[snapshot.team_id] = snapshot
    for team_id, snapshot in latest_by_team.items():
        pct = _utilization_value(snapshot)
        metrics.team_utilization.append((team_names.get(team_id, "Team"), pct))
        if pct >= float(UTILIZATION_OVERLOAD_THRESHOLD):
            metrics.teams_overloaded += 1
        elif pct < float(UTILIZATION_UNDERLOAD_THRESHOLD):
            metrics.teams_underloaded += 1
    for snapshot in list(latest_by_team.values())[:3]:
        evidence.append(
            EvidenceInput(
                source_table="utilization_snapshots",
                source_row_id=snapshot.id,
                description=(
                    f"Latest team utilization {_utilization_value(snapshot):.0f}% "
                    f"on {snapshot.snapshot_date.isoformat()}."
                ),
            )
        )

    requirements = (
        await session.execute(
            select(ProjectSkillRequirement).where(
                ProjectSkillRequirement.project_id == project.id,
                ProjectSkillRequirement.deleted_at.is_(None),
            ),
        )
    ).scalars().all()
    metrics.skill_requirements = len(requirements)
    for requirement in requirements[:3]:
        evidence.append(
            EvidenceInput(
                source_table="project_skill_requirements",
                source_row_id=requirement.id,
                description="Project skill requirement used for coverage comparison.",
            )
        )

    metrics.has_utilization_data = bool(latest_by_team)
    snapshot_dates = [s.snapshot_date for s in latest_by_team.values() if s.snapshot_date]
    if snapshot_dates:
        newest = max(snapshot_dates)
        if isinstance(newest, datetime):
            newest = newest.date()
        today = datetime.now(timezone.utc).date()
        metrics.latest_utilization_date = newest
        metrics.utilization_age_days = (today - newest).days
        metrics.utilization_stale = metrics.utilization_age_days > UTILIZATION_STALE_DAYS

    matrix = await build_project_skill_matrix(session, project, current_user)
    metrics.has_skill_matrix_coverage = bool(matrix.rows)
    low_rows = [row for row in matrix.rows if row.coverage_status == "low"]
    metrics.skill_low_coverage = len(low_rows)
    metrics.low_coverage_skills = [row.skill_name for row in low_rows[:5]]

    training = await build_project_training_gaps(session, project, current_user)
    metrics.training_total_gaps = training.total_training_gaps
    metrics.mandatory_training_incomplete = training.mandatory_training_incomplete
    metrics.expired_or_failed_training = training.expired_or_failed_training
    metrics.expired_certifications = training.expired_certifications
    metrics.pending_certification_reviews = training.pending_certification_reviews
    metrics.has_training_data = bool(training.rows) or any(
        (
            training.total_training_gaps,
            training.mandatory_training_incomplete,
            training.expired_or_failed_training,
            training.expired_certifications,
            training.pending_certification_reviews,
        )
    )
    seen_training_evidence: set[tuple[str, UUID]] = set()
    for row in training.rows[:5]:
        if row.training_program_id is not None:
            key = ("training_programs", row.training_program_id)
            if key not in seen_training_evidence:
                seen_training_evidence.add(key)
                evidence.append(
                    EvidenceInput(
                        source_table="training_programs",
                        source_row_id=row.training_program_id,
                        description=(
                            f"Training program gap ({row.gap_type}) affecting "
                            f"{row.affected_count} (aggregated)."
                        ),
                    )
                )
        if row.certification_id is not None:
            key = ("certifications", row.certification_id)
            if key not in seen_training_evidence:
                seen_training_evidence.add(key)
                evidence.append(
                    EvidenceInput(
                        source_table="certifications",
                        source_row_id=row.certification_id,
                        description=(
                            f"Certification gap ({row.gap_type}) affecting "
                            f"{row.affected_count} (aggregated)."
                        ),
                    )
                )

    gaps = (
        await session.execute(
            select(CapabilityGap).where(
                CapabilityGap.project_id == project.id,
                CapabilityGap.deleted_at.is_(None),
            ),
        )
    ).scalars().all()
    open_gaps = [gap for gap in gaps if gap.status in OPEN_GAP_STATUSES]
    metrics.open_capability_gaps = len(open_gaps)
    metrics.high_critical_gaps = sum(
        1 for gap in open_gaps if gap.severity in {"high", "critical"}
    )
    metrics.top_capability_gaps = [
        f"{gap.severity} {gap.gap_type}: {gap.title}" for gap in open_gaps[:5]
    ]
    for gap in open_gaps[:5]:
        evidence.append(
            EvidenceInput(
                source_table="capability_gaps",
                source_row_id=gap.id,
                description=f"{gap.severity} {gap.gap_type} capability gap: {gap.title}.",
            )
        )

    risk_alerts = (
        await session.execute(
            select(RiskAlert).where(
                RiskAlert.project_id == project.id,
                RiskAlert.deleted_at.is_(None),
                RiskAlert.alert_type == AlertType.WORKFORCE_IMBALANCE,
            ),
        )
    ).scalars().all()
    metrics.workforce_risk_alerts = len(risk_alerts)
    risk_ids = {alert.id for alert in risk_alerts}
    for alert in risk_alerts[:3]:
        evidence.append(
            EvidenceInput(
                source_table="risk_alerts",
                source_row_id=alert.id,
                description=f"Workforce imbalance risk alert: {alert.title}.",
            )
        )

    if risk_ids:
        recommendations = (
            await session.execute(
                select(MitigationRecommendation).where(
                    MitigationRecommendation.project_id == project.id,
                    MitigationRecommendation.deleted_at.is_(None),
                    MitigationRecommendation.source_risk_id.in_(risk_ids),
                ),
            )
        ).scalars().all()
        metrics.workforce_recommendations = len(recommendations)
        metrics.recommendation_titles = [rec.title for rec in recommendations[:5]]
        for recommendation in recommendations[:3]:
            evidence.append(
                EvidenceInput(
                    source_table="mitigation_recommendations",
                    source_row_id=recommendation.id,
                    description=(
                        "Internal workforce mitigation recommendation "
                        f"'{recommendation.title}'."
                    ),
                )
            )

    return WorkforceEvidenceBundle(
        project_id=project.id,
        project_name=project.name,
        metrics=metrics,
        evidence=evidence,
    )


# In-scope intent detection. Order matters: first match wins.
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sme", ("sme", "subject matter expert", "subject-matter expert")),
    (
        "utilization",
        ("overload", "underload", "under-load", "underutil", "utilization", "utilisation", "at capacity"),
    ),
    ("capacity", ("headcount", "annotator", "capacity", "staff", "resourc", "how many people")),
    ("skills", ("skill", "competenc")),
    ("training", ("training",)),
    ("certification", ("certif",)),
    ("capability_gaps", ("capability gap", "capability", "biggest gap", "open gap", "what gaps", "which gaps")),
    ("recommendations", ("recommend",)),
    ("summary", ("summar", "overall", "overview", "status")),
)

# Evidence source tables ranked by relevance per intent (highest priority first).
# Records whose table is not listed are kept but ranked after the listed ones.
_INTENT_PRIORITY: dict[str, tuple[str, ...]] = {
    "sme": ("teams", "projects"),
    "capacity": ("teams", "projects"),
    "utilization": ("utilization_snapshots", "teams", "projects"),
    "skills": ("project_skill_requirements", "teams", "projects"),
    "training": ("training_programs", "certifications", "projects"),
    "certification": ("certifications", "training_programs", "projects"),
    "capability_gaps": ("capability_gaps", "risk_alerts", "projects"),
    "recommendations": ("mitigation_recommendations", "capability_gaps", "risk_alerts", "projects"),
    "summary": ("projects", "teams"),
}


def detect_workforce_intent(question: str) -> str:
    lowered = question.lower()
    for intent, keywords in _INTENT_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return intent
    return "summary"


def rank_evidence_for_intent(
    evidence: list[EvidenceInput],
    intent: str,
) -> list[EvidenceInput]:
    """Order evidence so records matching the question intent come first.

    All evidence is retained (stable sort); intent-relevant tables are promoted to
    the top so the most relevant grounding is surfaced first.
    """
    priority = _INTENT_PRIORITY.get(intent, ("projects",))

    def rank(item: EvidenceInput) -> int:
        try:
            return priority.index(item.source_table)
        except ValueError:
            return len(priority) + 1

    return [item for _, item in sorted(enumerate(evidence), key=lambda pair: (rank(pair[1]), pair[0]))]


def _grounding_line(bundle: WorkforceEvidenceBundle) -> str:
    count = len(bundle.evidence)
    return (
        f"Grounded in {count} workforce evidence record(s). "
        "Figures are aggregated at the team level; individual annotator details are not exposed."
    )


def _confidence_for_intent(metrics: WorkforceMetrics, intent: str) -> str:
    """Deterministic confidence: High (fresh+present), Medium (partial), Low (missing/stale)."""
    if intent == "utilization":
        if not metrics.has_utilization_data:
            return "Low"
        return "Medium" if metrics.utilization_stale else "High"
    if intent == "capacity":
        if metrics.active_annotators == 0:
            return "Low"
        if not metrics.has_utilization_data or metrics.utilization_stale:
            return "Medium"
        return "High"
    if intent == "sme":
        return "High" if metrics.active_annotators > 0 else "Low"
    if intent == "skills":
        if metrics.skill_requirements == 0:
            return "Low"
        return "High" if metrics.has_skill_matrix_coverage else "Medium"
    if intent == "training":
        return "High" if metrics.has_training_data else "Medium"
    if intent == "certification":
        if metrics.expired_certifications + metrics.pending_certification_reviews > 0:
            return "High"
        return "Medium" if metrics.has_training_data else "Low"
    if intent == "capability_gaps":
        return "High" if metrics.open_capability_gaps > 0 else "Low"
    if intent == "recommendations":
        return "High" if metrics.workforce_recommendations > 0 else "Low"
    # summary: based on how many workforce signals are present and fresh.
    signals = (
        metrics.active_annotators > 0,
        metrics.has_utilization_data and not metrics.utilization_stale,
        metrics.skill_requirements > 0,
        metrics.has_skill_matrix_coverage,
        metrics.has_training_data,
    )
    present = sum(1 for signal in signals if signal)
    if present >= 4:
        return "High"
    if present >= 2:
        return "Medium"
    return "Low"


def _footer(bundle: WorkforceEvidenceBundle, intent: str) -> str:
    confidence = _confidence_for_intent(bundle.metrics, intent)
    return f"{_grounding_line(bundle)}\nConfidence: {confidence}."


def _utilization_freshness_note(metrics: WorkforceMetrics) -> str | None:
    """Return a caution note when utilization data is missing or stale."""
    if not metrics.has_utilization_data:
        return "Note: no utilization snapshots are available, so live workload is not confirmed."
    if metrics.utilization_stale:
        return (
            f"Note: the latest utilization snapshot is {metrics.utilization_age_days} days old "
            f"(older than {UTILIZATION_STALE_DAYS} days), so live workload may be out of date."
        )
    return None


def _generic_summary(bundle: WorkforceEvidenceBundle) -> str:
    metrics = bundle.metrics
    project_label = bundle.project_name or "the selected project"
    lines: list[str] = [f"Workforce summary for {project_label}:"]
    lines.append(
        f"- Capacity: {metrics.active_annotators} active annotators across "
        f"{metrics.team_count} team(s)."
    )
    if metrics.sme_coverage_pct is not None:
        lines.append(
            f"- SME coverage: {metrics.sme_count} SMEs "
            f"({metrics.sme_coverage_pct}% of active annotators)."
        )
    if metrics.has_utilization_data:
        util_line = (
            f"- Utilization: {metrics.teams_overloaded} team(s) at or above "
            f"{float(UTILIZATION_OVERLOAD_THRESHOLD):.0f}%, "
            f"{metrics.teams_underloaded} below "
            f"{float(UTILIZATION_UNDERLOAD_THRESHOLD):.0f}%."
        )
        if metrics.utilization_stale:
            util_line += f" (snapshot {metrics.utilization_age_days}d old; may be stale)"
        lines.append(util_line)
    else:
        lines.append("- Utilization: no snapshots available.")
    if metrics.skill_requirements > 0:
        lines.append(
            f"- Skill coverage: {metrics.skill_low_coverage} of "
            f"{metrics.skill_requirements} required skill(s) at low coverage."
        )
    if metrics.training_total_gaps > 0:
        lines.append(f"- Training: {metrics.training_total_gaps} open training/certification gap(s).")
    if metrics.open_capability_gaps > 0:
        lines.append(
            f"- Capability gaps: {metrics.open_capability_gaps} open "
            f"({metrics.high_critical_gaps} high/critical)."
        )
    if metrics.workforce_risk_alerts > 0:
        lines.append(
            f"- Workforce risk alerts: {metrics.workforce_risk_alerts}; "
            f"recommendations: {metrics.workforce_recommendations}."
        )
    lines.append(_footer(bundle, "summary"))
    return "\n".join(lines)


def build_workforce_answer(question: str, bundle: WorkforceEvidenceBundle) -> str:
    """Deterministic, evidence-grounded, question-specific fallback answer."""
    if not bundle.has_data:
        return INSUFFICIENT_DATA_MESSAGE

    intent = detect_workforce_intent(question)
    metrics = bundle.metrics
    label = bundle.project_name or "the selected project"
    footer = _footer(bundle, intent)
    over = float(UTILIZATION_OVERLOAD_THRESHOLD)
    under = float(UTILIZATION_UNDERLOAD_THRESHOLD)

    if intent == "sme":
        if metrics.active_annotators == 0:
            return (
                f"No active annotators are recorded for {label}, so SME coverage "
                f"cannot be calculated.\n{footer}"
            )
        line = f"SME coverage for {label}: {metrics.sme_count} SME(s)"
        if metrics.sme_coverage_pct is not None:
            line += f" ({metrics.sme_coverage_pct}% of {metrics.active_annotators} active annotators)"
        line += "."
        lines = [line]
        if metrics.sme_coverage_pct is not None and metrics.sme_coverage_pct < 50:
            lines.append("SME coverage is below 50%; consider certifying more annotators.")
        lines.append(footer)
        return "\n".join(lines)

    if intent == "utilization":
        if not metrics.has_utilization_data:
            return (
                f"No utilization snapshots are available for {label} yet, so I cannot confirm "
                f"overloaded or underloaded teams from utilization data.\n{footer}"
            )
        lines = [
            f"Utilization for {label}: {metrics.teams_overloaded} team(s) at or above "
            f"{over:.0f}% and {metrics.teams_underloaded} below {under:.0f}% "
            f"(of {len(metrics.team_utilization)} team(s) with snapshots)."
        ]
        overloaded = [f"{name} ({pct:.0f}%)" for name, pct in metrics.team_utilization if pct >= over]
        if overloaded:
            lines.append("Overloaded: " + ", ".join(overloaded[:5]) + ".")
        if metrics.utilization_stale:
            lines.append(
                f"Caution: the latest utilization snapshot is {metrics.utilization_age_days} days "
                f"old (older than {UTILIZATION_STALE_DAYS} days), so these figures may be stale."
            )
        lines.append(footer)
        return "\n".join(lines)

    if intent == "capacity":
        if metrics.active_annotators == 0:
            return (
                f"{label} has {metrics.team_count} team(s) but no active annotators recorded.\n"
                f"{footer}"
            )
        lines = [
            f"Capacity for {label}: {metrics.active_annotators} active annotators across "
            f"{metrics.team_count} team(s)."
        ]
        util_note = _utilization_freshness_note(metrics)
        if util_note:
            lines.append(util_note)
        lines.append(footer)
        return "\n".join(lines)

    if intent == "skills":
        if metrics.skill_requirements == 0:
            return (
                f"No skill requirements are configured for {label}, so skill coverage "
                f"cannot be assessed.\n{footer}"
            )
        if not metrics.has_skill_matrix_coverage:
            return (
                f"{label} has {metrics.skill_requirements} skill requirement(s) configured, but no "
                f"skill matrix coverage data is available yet, so missing skills cannot be "
                f"confirmed.\n{footer}"
            )
        lines = [
            f"Skill coverage for {label}: {metrics.skill_low_coverage} of "
            f"{metrics.skill_requirements} required skill(s) at low coverage."
        ]
        if metrics.low_coverage_skills:
            lines.append("Lowest coverage: " + ", ".join(metrics.low_coverage_skills) + ".")
        lines.append(footer)
        return "\n".join(lines)

    if intent == "training":
        if metrics.training_total_gaps == 0:
            suffix = "" if metrics.has_training_data else " (no training records available)"
            return f"No open training gaps are recorded for {label}{suffix}.\n{footer}"
        return (
            f"Training gaps for {label}: {metrics.training_total_gaps} open "
            f"({metrics.mandatory_training_incomplete} mandatory incomplete, "
            f"{metrics.expired_or_failed_training} expired/failed).\n{footer}"
        )

    if intent == "certification":
        total_cert = metrics.expired_certifications + metrics.pending_certification_reviews
        if total_cert == 0:
            suffix = "" if metrics.has_training_data else " (no certification records available)"
            return f"No certification gaps are recorded for {label}{suffix}.\n{footer}"
        return (
            f"Certification gaps for {label}: {metrics.expired_certifications} expired "
            f"certification(s) and {metrics.pending_certification_reviews} pending review(s).\n"
            f"{footer}"
        )

    if intent == "capability_gaps":
        if metrics.open_capability_gaps == 0:
            return (
                f"No open capability gaps are recorded for {label}. Run capability gap "
                f"detection to scan the latest workforce data.\n{footer}"
            )
        lines = [
            f"Capability gaps for {label}: {metrics.open_capability_gaps} open "
            f"({metrics.high_critical_gaps} high/critical)."
        ]
        if metrics.top_capability_gaps:
            lines.append("Top gaps: " + "; ".join(metrics.top_capability_gaps) + ".")
        lines.append(footer)
        return "\n".join(lines)

    if intent == "recommendations":
        if metrics.workforce_recommendations == 0:
            return (
                f"No workforce recommendations exist yet for {label}. Generate workforce "
                f"recommendations from open high/critical gaps.\n{footer}"
            )
        lines = [
            f"Workforce recommendations for {label}: {metrics.workforce_recommendations}."
        ]
        if metrics.recommendation_titles:
            lines.append("Recommendations: " + "; ".join(metrics.recommendation_titles) + ".")
        lines.append(footer)
        return "\n".join(lines)

    return _generic_summary(bundle)


async def answer_workforce_query(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: AgentQueryCreate,
) -> AgentQuery:
    """Handle a Workforce Agent question: scope, retrieve evidence, persist."""
    if not can_read_annotators(current_user):
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    started = perf_counter()
    settings = get_settings()
    evidence: list[EvidenceInput] = []

    redirect = classify_workforce_question(payload.query_text)
    if redirect is not None:
        answer_text = redirect.message
        if payload.project_id:
            project = await get_visible_project(session, payload.project_id, current_user)
            evidence.append(
                EvidenceInput(
                    source_table="projects",
                    source_row_id=project.id,
                    description=f"Question scoped to project '{project.name}'.",
                )
            )
    elif payload.project_id is None:
        answer_text = PROJECT_REQUIRED_MESSAGE
    else:
        project = await get_visible_project(session, payload.project_id, current_user)
        bundle = await gather_workforce_evidence(session, project, current_user)
        answer_text = build_workforce_answer(payload.query_text, bundle)
        intent = detect_workforce_intent(payload.query_text)
        evidence = rank_evidence_for_intent(bundle.evidence, intent)

    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=payload.project_id,
        agent_name=WORKFORCE_AGENT_NAME,
        query_text=payload.query_text,
        answer_text=answer_text,
        model_used=settings.llm_model,
        latency_ms=int((perf_counter() - started) * 1000),
    )
    session.add(query)
    await session.flush()
    for item in evidence:
        session.add(
            AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return query
