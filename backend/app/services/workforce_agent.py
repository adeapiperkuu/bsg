"""Workforce & Capability Agent: evidence-backed internal Q&A.

This agent answers internal workforce/capability questions using deterministic,
aggregated evidence from Workforce-owned tables. It never exposes individual
annotator names and redirects out-of-scope questions to the owning agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    skill_requirements: int = 0
    skill_low_coverage: int = 0
    training_total_gaps: int = 0
    open_capability_gaps: int = 0
    high_critical_gaps: int = 0
    workforce_risk_alerts: int = 0
    workforce_recommendations: int = 0


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

    matrix = await build_project_skill_matrix(session, project, current_user)
    metrics.skill_low_coverage = sum(
        1 for row in matrix.rows if row.coverage_status == "low"
    )

    training = await build_project_training_gaps(session, project, current_user)
    metrics.training_total_gaps = training.total_training_gaps

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


def build_workforce_answer(question: str, bundle: WorkforceEvidenceBundle) -> str:
    """Deterministic, evidence-grounded fallback answer."""
    if not bundle.has_data:
        return INSUFFICIENT_DATA_MESSAGE

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
    if metrics.team_utilization:
        lines.append(
            f"- Utilization: {metrics.teams_overloaded} team(s) at or above "
            f"{float(UTILIZATION_OVERLOAD_THRESHOLD):.0f}%, "
            f"{metrics.teams_underloaded} below "
            f"{float(UTILIZATION_UNDERLOAD_THRESHOLD):.0f}%."
        )
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

    lines.append(
        f"Grounded in {len(bundle.evidence)} workforce evidence record(s). "
        "Figures are aggregated at the team level; individual annotator details are not exposed."
    )
    return "\n".join(lines)


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
        evidence = bundle.evidence
        answer_text = build_workforce_answer(payload.query_text, bundle)

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
