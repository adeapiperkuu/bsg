"""Mitigation recommendation generation, sync, and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AlertStatus,
    AlertType,
    MitigationRecommendation,
    OwnerType,
    ProjectAssignment,
    RecommendationSeverity,
    RecommendationStatus,
    RiskAlert,
    RiskTier,
    Team,
    User,
)

OPEN_RISK_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)

CAUSE_ACTIONS: dict[str, tuple[str, str]] = {
    "confidence_shortfall": (
        "Rebuild milestone confidence forecast",
        "Reconcile remaining scope with current throughput and update the delivery forecast with revised assumptions.",
    ),
    "throughput_decline": (
        "Stabilize weekly throughput",
        "Investigate root throughput blockers, rebalance annotator allocation, and set a 2-week recovery target.",
    ),
    "milestone_urgency": (
        "Accelerate milestone-critical work",
        "Prioritize milestone deliverables, escalate blockers daily, and align client expectations on revised dates.",
    ),
    "open_bottlenecks": (
        "Clear active bottlenecks",
        "Assign owners to each open bottleneck and run a daily stand-down until throughput recovers.",
    ),
    "quality_drift": (
        "Contain quality drift",
        "Run targeted gold-set reviews, refresh SME calibration, and pause risky workstreams until rework drops.",
    ),
}

ALERT_ACTIONS: dict[AlertType, tuple[str, str]] = {
    AlertType.DELIVERY_RISK: (
        "Mitigate delivery slippage",
        "Review capacity, milestone sequencing, and recovery options with the delivery lead within 48 hours.",
    ),
    AlertType.QUALITY_DRIFT: (
        "Address quality drift",
        "Trigger a focused quality review and tighten review gates for the affected workstream.",
    ),
    AlertType.MILESTONE_AT_RISK: (
        "Protect at-risk milestone",
        "Re-sequence work to protect the milestone date and communicate trade-offs to stakeholders.",
    ),
    AlertType.WORKFORCE_IMBALANCE: (
        "Rebalance workforce allocation",
        "Shift annotator capacity across teams to remove imbalance and restore sustainable throughput.",
    ),
}

SEVERITY_ORDER = {
    RecommendationSeverity.HIGH: 0,
    RecommendationSeverity.MEDIUM: 1,
    RecommendationSeverity.LOW: 2,
}


@dataclass(frozen=True)
class RecommendationRow:
    recommendation: MitigationRecommendation
    owner_label: str | None
    source_risk_title: str | None
    source_risk_type: str | None


@dataclass(frozen=True)
class OwnerOption:
    owner_type: OwnerType
    owner_id: UUID
    label: str


def _map_risk_tier_to_severity(tier: RiskTier) -> RecommendationSeverity:
    if tier in {RiskTier.HIGH, RiskTier.CRITICAL}:
        return RecommendationSeverity.HIGH
    if tier == RiskTier.MEDIUM:
        return RecommendationSeverity.MEDIUM
    return RecommendationSeverity.LOW


def _confidence_from_risk(risk: RiskAlert) -> Decimal:
    if risk.slippage_probability is not None:
        return risk.slippage_probability.quantize(Decimal("0.001"))
    defaults = {
        RiskTier.CRITICAL: Decimal("0.900"),
        RiskTier.HIGH: Decimal("0.800"),
        RiskTier.MEDIUM: Decimal("0.650"),
        RiskTier.LOW: Decimal("0.450"),
    }
    return defaults[risk.risk_tier]


def _top_contributing_cause(causes: dict[str, Any] | None) -> str | None:
    if not causes:
        return None
    ranked = sorted(
        ((key, float(value)) for key, value in causes.items() if float(value) > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[0][0] if ranked else None


def generate_mitigation_copy(risk: RiskAlert) -> tuple[str, str]:
    # Title is intentionally the shared, unqualified action template: distinct risks that
    # resolve to the same template (e.g. two separate at-risk milestones) are expected to
    # share a title, since list_project_recommendations groups by this exact title below.
    top_cause = _top_contributing_cause(risk.contributing_causes)
    if top_cause and top_cause in CAUSE_ACTIONS:
        title, description = CAUSE_ACTIONS[top_cause]
        return title, f"{description} Linked risk: {risk.title}."
    title, description = ALERT_ACTIONS.get(
        risk.alert_type,
        ("Address project risk", "Review the linked risk and define a mitigation plan with accountable owners."),
    )
    return title, f"{description} Linked risk: {risk.detail}"


async def sync_recommendations_for_project(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
) -> None:
    """Upsert pending recommendations for open risks in batched queries."""
    open_risks = (
        await session.execute(
            select(RiskAlert).where(
                RiskAlert.project_id == project_id,
                RiskAlert.deleted_at.is_(None),
                RiskAlert.status.in_(OPEN_RISK_STATUSES),
            )
        )
    ).scalars().all()

    existing_rows = (
        await session.execute(
            select(MitigationRecommendation).where(
                MitigationRecommendation.project_id == project_id,
                MitigationRecommendation.deleted_at.is_(None),
                MitigationRecommendation.source_risk_id.is_not(None),
            )
        )
    ).scalars().all()
    existing_by_risk_id = {row.source_risk_id: row for row in existing_rows if row.source_risk_id is not None}
    active_risk_ids = {risk.id for risk in open_risks}

    for risk in open_risks:
        title, description = generate_mitigation_copy(risk)
        severity = _map_risk_tier_to_severity(risk.risk_tier)
        confidence = _confidence_from_risk(risk)
        existing = existing_by_risk_id.get(risk.id)
        if existing is not None:
            if existing.status != RecommendationStatus.PENDING:
                continue
            existing.title = title
            existing.description = description
            existing.severity = severity
            existing.confidence_score = confidence
            continue

        session.add(
            MitigationRecommendation(
                project_id=project_id,
                org_id=org_id,
                title=title,
                description=description,
                severity=severity,
                confidence_score=confidence,
                status=RecommendationStatus.PENDING,
                source_risk_id=risk.id,
            )
        )

    for existing in existing_rows:
        if (
            existing.source_risk_id is not None
            and existing.source_risk_id not in active_risk_ids
            and existing.status == RecommendationStatus.PENDING
        ):
            existing.deleted_at = datetime.now(timezone.utc)

    await session.flush()


async def list_project_recommendations(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
) -> tuple[list[RecommendationRow], list[OwnerOption]]:
    """Return all recommendations and assignable owners without per-row queries."""
    user_owner = User.__table__.alias("owner_user")
    team_owner = Team.__table__.alias("owner_team")

    rows = (
        await session.execute(
            select(
                MitigationRecommendation,
                user_owner.c.full_name.label("owner_user_name"),
                team_owner.c.name.label("owner_team_name"),
                RiskAlert.title.label("source_risk_title"),
                RiskAlert.alert_type.label("source_risk_type"),
            )
            .outerjoin(
                user_owner,
                and_(
                    MitigationRecommendation.owner_type == OwnerType.USER,
                    MitigationRecommendation.owner_id == user_owner.c.id,
                ),
            )
            .outerjoin(
                team_owner,
                and_(
                    MitigationRecommendation.owner_type == OwnerType.TEAM,
                    MitigationRecommendation.owner_id == team_owner.c.id,
                ),
            )
            .outerjoin(RiskAlert, MitigationRecommendation.source_risk_id == RiskAlert.id)
            .where(
                MitigationRecommendation.project_id == project_id,
                MitigationRecommendation.deleted_at.is_(None),
            )
            .order_by(
                MitigationRecommendation.confidence_score.desc(),
                MitigationRecommendation.created_at.desc(),
            )
        )
    ).all()

    recommendations = [
        RecommendationRow(
            recommendation=row[0],
            owner_label=row[1] if row[0].owner_type == OwnerType.USER else row[2],
            source_risk_title=row[3],
            source_risk_type=row[4].value if row[4] is not None else None,
        )
        for row in rows
    ]
    recommendations.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item.recommendation.severity, 99),
            -float(item.recommendation.confidence_score),
        )
    )

    assignable_owners = await _load_assignable_owners(session, project_id=project_id, org_id=org_id)
    return recommendations, assignable_owners


@dataclass(frozen=True)
class GroupedRecommendation:
    """Read-time grouping of recommendation rows that share the same action title.

    This is a display aggregation only: it does not change how recommendations
    are generated, scored, or persisted. Each underlying row keeps its own id,
    status, and confidence_score so accept/reject/assign-owner still operate
    on individual recommendations.
    """

    title: str
    severity: RecommendationSeverity
    confidence_score: Decimal
    project_id: UUID
    members: list[RecommendationRow]


def group_recommendations_by_title(rows: list[RecommendationRow]) -> list[GroupedRecommendation]:
    """Aggregate recommendation rows by their shared action title.

    Several open risks can independently produce the same static action title
    (e.g. multiple at-risk milestones each generating "Protect at-risk
    milestone"). Grouping here avoids showing visually identical cards while
    preserving every linked risk's own id, status, confidence, and description.
    """
    order: list[str] = []
    buckets: dict[str, list[RecommendationRow]] = {}
    for row in rows:
        title = row.recommendation.title
        if title not in buckets:
            buckets[title] = []
            order.append(title)
        buckets[title].append(row)

    groups = [
        GroupedRecommendation(
            title=title,
            severity=min(
                (member.recommendation.severity for member in buckets[title]),
                key=lambda severity: SEVERITY_ORDER.get(severity, 99),
            ),
            confidence_score=max(member.recommendation.confidence_score for member in buckets[title]),
            project_id=buckets[title][0].recommendation.project_id,
            members=buckets[title],
        )
        for title in order
    ]
    groups.sort(
        key=lambda group: (SEVERITY_ORDER.get(group.severity, 99), -float(group.confidence_score))
    )
    return groups


def grouped_recommendation_to_read(group: GroupedRecommendation) -> dict[str, Any]:
    """Serialize a GroupedRecommendation into the GroupedMitigationRecommendationRead shape."""
    return {
        "title": group.title,
        "severity": group.severity.value,
        "confidence_score": group.confidence_score,
        "project_id": group.project_id,
        "risks": [
            {
                "recommendation_id": member.recommendation.id,
                "source_risk_id": member.recommendation.source_risk_id,
                "source_risk_title": member.source_risk_title,
                "description": member.recommendation.description,
                "status": member.recommendation.status.value,
                "confidence_score": member.recommendation.confidence_score,
                "owner_type": member.recommendation.owner_type.value if member.recommendation.owner_type else None,
                "owner_id": member.recommendation.owner_id,
                "owner_label": member.owner_label,
            }
            for member in group.members
        ],
        "statuses": [member.recommendation.status.value for member in group.members],
        "descriptions": [
            member.recommendation.description for member in group.members if member.recommendation.description
        ],
    }


async def _load_assignable_owners(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
) -> list[OwnerOption]:
    user_rows = (
        await session.execute(
            select(User.id, User.full_name, User.email)
            .join(ProjectAssignment, ProjectAssignment.user_id == User.id)
            .where(
                ProjectAssignment.project_id == project_id,
                ProjectAssignment.is_active.is_(True),
                ProjectAssignment.deleted_at.is_(None),
                User.org_id == org_id,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
            .order_by(User.full_name.asc(), User.email.asc())
        )
    ).all()
    team_rows = (
        await session.execute(
            select(Team.id, Team.name)
            .where(
                Team.project_id == project_id,
                Team.org_id == org_id,
                Team.deleted_at.is_(None),
                Team.is_active.is_(True),
            )
            .order_by(Team.name.asc())
        )
    ).all()

    owners: list[OwnerOption] = []
    for user_id, full_name, email in user_rows:
        label = full_name or email
        owners.append(OwnerOption(owner_type=OwnerType.USER, owner_id=user_id, label=label))
    for team_id, team_name in team_rows:
        owners.append(OwnerOption(owner_type=OwnerType.TEAM, owner_id=team_id, label=team_name))
    return owners


async def validate_owner_assignment(
    session: AsyncSession,
    *,
    project_id: UUID,
    org_id: UUID,
    owner_type: OwnerType | None,
    owner_id: UUID | None,
) -> str | None:
    """Return owner label when valid; raise ValueError otherwise."""
    if owner_type is None and owner_id is None:
        return None
    if owner_type is None or owner_id is None:
        raise ValueError("owner_type and owner_id must both be set or both be null.")

    if owner_type == OwnerType.USER:
        row = (
            await session.execute(
                select(User.full_name, User.email)
                .join(ProjectAssignment, ProjectAssignment.user_id == User.id)
                .where(
                    User.id == owner_id,
                    User.org_id == org_id,
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                    ProjectAssignment.project_id == project_id,
                    ProjectAssignment.is_active.is_(True),
                    ProjectAssignment.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Owner user is not assigned to this project.")
        return row[0] or row[1]

    if owner_type == OwnerType.TEAM:
        row = (
            await session.execute(
                select(Team.name).where(
                    Team.id == owner_id,
                    Team.project_id == project_id,
                    Team.org_id == org_id,
                    Team.deleted_at.is_(None),
                    Team.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ValueError("Owner team was not found for this project.")
        return row

    raise ValueError("Unsupported owner type.")


def recommendation_row_to_read(row: RecommendationRow) -> dict[str, Any]:
    recommendation = row.recommendation
    return {
        "id": recommendation.id,
        "project_id": recommendation.project_id,
        "title": recommendation.title,
        "description": recommendation.description,
        "severity": recommendation.severity.value,
        "confidence_score": recommendation.confidence_score,
        "status": recommendation.status.value,
        "owner_type": recommendation.owner_type.value if recommendation.owner_type else None,
        "owner_id": recommendation.owner_id,
        "owner_label": row.owner_label,
        "source_risk_id": recommendation.source_risk_id,
        "source_risk_title": row.source_risk_title,
        "source_risk_type": row.source_risk_type,
        "created_at": recommendation.created_at,
        "updated_at": recommendation.updated_at,
    }


async def fetch_recommendation_row(
    session: AsyncSession,
    recommendation_id: UUID,
) -> RecommendationRow | None:
    user_owner = User.__table__.alias("owner_user")
    team_owner = Team.__table__.alias("owner_team")
    row = (
        await session.execute(
            select(
                MitigationRecommendation,
                user_owner.c.full_name.label("owner_user_name"),
                team_owner.c.name.label("owner_team_name"),
                RiskAlert.title.label("source_risk_title"),
                RiskAlert.alert_type.label("source_risk_type"),
            )
            .outerjoin(
                user_owner,
                and_(
                    MitigationRecommendation.owner_type == OwnerType.USER,
                    MitigationRecommendation.owner_id == user_owner.c.id,
                ),
            )
            .outerjoin(
                team_owner,
                and_(
                    MitigationRecommendation.owner_type == OwnerType.TEAM,
                    MitigationRecommendation.owner_id == team_owner.c.id,
                ),
            )
            .outerjoin(RiskAlert, MitigationRecommendation.source_risk_id == RiskAlert.id)
            .where(
                MitigationRecommendation.id == recommendation_id,
                MitigationRecommendation.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    recommendation = row[0]
    owner_label = row[1] if recommendation.owner_type == OwnerType.USER else row[2]
    return RecommendationRow(
        recommendation=recommendation,
        owner_label=owner_label,
        source_risk_title=row[3],
        source_risk_type=row[4].value if row[4] is not None else None,
    )


async def get_recommendation_for_mutation(
    session: AsyncSession,
    recommendation_id: UUID,
    *,
    org_id: UUID | None,
    is_super_admin: bool,
) -> MitigationRecommendation | None:
    recommendation = (
        await session.execute(
            select(MitigationRecommendation).where(
                MitigationRecommendation.id == recommendation_id,
                MitigationRecommendation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if recommendation is None:
        return None
    if not is_super_admin and recommendation.org_id != org_id:
        return None
    return recommendation
