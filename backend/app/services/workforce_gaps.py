"""Capability gap detection, persistence, and workforce recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.services.recommendation_service import (
    generate_mitigation_copy,
    recommendation_row_to_read,
    sync_recommendations_for_project,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    AppRole,
    CapabilityGap,
    CapabilityGapSeverity,
    CapabilityGapStatus,
    CapabilityGapType,
    MitigationRecommendation,
    Project,
    ProjectSkillRequirement,
    RecommendationSeverity,
    RecommendationStatus,
    RiskAlert,
    RiskTier,
    Skill,
    SkillRequirementPriority,
    Team,
    UtilizationSnapshot,
)
from app.schemas.domain import CapabilityGapDetectionResponse, CapabilityGapRead, CapabilityGapUpdate
from app.services.workforce import (
    assert_can_manage_workforce,
    assert_can_read_annotators,
    can_read_annotators,
    get_team_or_404,
)
from app.services.workforce_skills import build_project_skill_matrix, get_skill_or_404
from app.services.workforce_training import build_project_training_gaps

UTILIZATION_OVERLOAD_THRESHOLD = Decimal("85")
UTILIZATION_UNDERLOAD_THRESHOLD = Decimal("60")
UTILIZATION_CRITICAL_THRESHOLD = Decimal("100")

OPEN_GAP_STATUSES = (CapabilityGapStatus.OPEN, CapabilityGapStatus.ACKNOWLEDGED)
OPEN_ALERT_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)
HIGH_PRIORITY = frozenset({SkillRequirementPriority.HIGH, SkillRequirementPriority.CRITICAL})


@dataclass(frozen=True)
class GapCandidate:
    gap_type: CapabilityGapType
    severity: CapabilityGapSeverity
    title: str
    detail: str
    team_id: UUID | None = None
    skill_id: UUID | None = None
    evidence: dict | None = None


def _gap_severity_to_risk_tier(severity: CapabilityGapSeverity) -> RiskTier:
    if severity == CapabilityGapSeverity.CRITICAL:
        return RiskTier.CRITICAL
    if severity == CapabilityGapSeverity.HIGH:
        return RiskTier.HIGH
    if severity == CapabilityGapSeverity.MEDIUM:
        return RiskTier.MEDIUM
    return RiskTier.LOW


def _gap_severity_to_recommendation_severity(severity: CapabilityGapSeverity) -> RecommendationSeverity:
    if severity in {CapabilityGapSeverity.CRITICAL, CapabilityGapSeverity.HIGH}:
        return RecommendationSeverity.HIGH
    if severity == CapabilityGapSeverity.MEDIUM:
        return RecommendationSeverity.MEDIUM
    return RecommendationSeverity.LOW


def _dedupe_key(
    gap_type: CapabilityGapType,
    team_id: UUID | None,
    skill_id: UUID | None,
) -> tuple[str, UUID | None, UUID | None]:
    return (gap_type.value, team_id, skill_id)


async def _load_existing_open_gaps(
    session: AsyncSession,
    project_id: UUID,
) -> dict[tuple[str, UUID | None, UUID | None], CapabilityGap]:
    rows = (
        await session.execute(
            select(CapabilityGap).where(
                CapabilityGap.project_id == project_id,
                CapabilityGap.deleted_at.is_(None),
                CapabilityGap.status.in_(OPEN_GAP_STATUSES),
            ),
        )
    ).scalars().all()
    return {
        _dedupe_key(row.gap_type, row.team_id, row.skill_id): row
        for row in rows
    }


async def _load_requirements_by_skill(
    session: AsyncSession,
    project_id: UUID,
) -> dict[UUID, ProjectSkillRequirement]:
    rows = (
        await session.execute(
            select(ProjectSkillRequirement).where(
                ProjectSkillRequirement.project_id == project_id,
                ProjectSkillRequirement.deleted_at.is_(None),
            ),
        )
    ).scalars().all()
    return {row.skill_id: row for row in rows}


async def _load_skills_by_id(session: AsyncSession, skill_ids: set[UUID]) -> dict[UUID, Skill]:
    if not skill_ids:
        return {}
    rows = (
        await session.execute(
            select(Skill).where(Skill.id.in_(skill_ids), Skill.deleted_at.is_(None)),
        )
    ).scalars().all()
    return {row.id: row for row in rows}


async def _load_latest_team_utilization(
    session: AsyncSession,
    project_id: UUID,
) -> dict[UUID, UtilizationSnapshot]:
    snapshots = (
        await session.execute(
            select(UtilizationSnapshot).where(
                UtilizationSnapshot.project_id == project_id,
                UtilizationSnapshot.deleted_at.is_(None),
                UtilizationSnapshot.team_id.is_not(None),
                UtilizationSnapshot.annotator_id.is_(None),
            ).order_by(
                UtilizationSnapshot.team_id,
                UtilizationSnapshot.snapshot_date.desc(),
                UtilizationSnapshot.created_at.desc(),
            ),
        )
    ).scalars().all()
    latest: dict[UUID, UtilizationSnapshot] = {}
    for snapshot in snapshots:
        if snapshot.team_id is not None and snapshot.team_id not in latest:
            latest[snapshot.team_id] = snapshot
    return latest


def _skill_shortage_severity(
    available_headcount: int,
    requirement: ProjectSkillRequirement | None,
    skill: Skill | None,
) -> CapabilityGapSeverity:
    if available_headcount == 0 and (
        (requirement is not None and requirement.priority in HIGH_PRIORITY)
        or (skill is not None and skill.is_critical)
    ):
        return CapabilityGapSeverity.CRITICAL
    return CapabilityGapSeverity.MEDIUM


async def detect_gap_candidates(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> list[GapCandidate]:
    assert_can_read_annotators(current_user)
    candidates: list[GapCandidate] = []

    matrix = await build_project_skill_matrix(session, project, current_user)
    requirements_by_skill = await _load_requirements_by_skill(session, project.id)
    skills_by_id = await _load_skills_by_id(session, {row.skill_id for row in matrix.rows})

    for row in matrix.rows:
        requirement = requirements_by_skill.get(row.skill_id)
        skill = skills_by_id.get(row.skill_id)

        if row.available_headcount < row.required_headcount:
            shortage = row.required_headcount - row.available_headcount
            candidates.append(
                GapCandidate(
                    gap_type=CapabilityGapType.SKILL_SHORTAGE,
                    severity=_skill_shortage_severity(row.available_headcount, requirement, skill),
                    title=f"Skill shortage: {row.skill_name}",
                    detail=(
                        f"Available headcount ({row.available_headcount}) is below required "
                        f"({row.required_headcount}); shortage of {shortage}."
                    ),
                    skill_id=row.skill_id,
                    evidence={
                        "skill_name": row.skill_name,
                        "required_headcount": row.required_headcount,
                        "available_headcount": row.available_headcount,
                        "shortage": shortage,
                        "priority": requirement.priority.value if requirement else None,
                        "is_critical_skill": skill.is_critical if skill else False,
                    },
                ),
            )

        if row.available_sme_count < row.required_sme_count:
            sme_shortage = row.required_sme_count - row.available_sme_count
            candidates.append(
                GapCandidate(
                    gap_type=CapabilityGapType.SME_SHORTAGE,
                    severity=CapabilityGapSeverity.HIGH,
                    title=f"SME shortage: {row.skill_name}",
                    detail=(
                        f"Available SMEs ({row.available_sme_count}) is below required "
                        f"({row.required_sme_count}); shortage of {sme_shortage}."
                    ),
                    skill_id=row.skill_id,
                    evidence={
                        "skill_name": row.skill_name,
                        "required_sme_count": row.required_sme_count,
                        "available_sme_count": row.available_sme_count,
                        "shortage": sme_shortage,
                    },
                ),
            )

    training_summary = await build_project_training_gaps(session, project, current_user)
    if training_summary.total_training_gaps > 0:
        candidates.append(
            GapCandidate(
                gap_type=CapabilityGapType.TRAINING_GAP,
                severity=CapabilityGapSeverity.MEDIUM,
                title="Training gaps detected",
                detail=(
                    f"{training_summary.total_training_gaps} training gap(s) across the project "
                    f"({training_summary.mandatory_training_incomplete} mandatory incomplete, "
                    f"{training_summary.expired_or_failed_training} expired/failed)."
                ),
                evidence={
                    "total_training_gaps": training_summary.total_training_gaps,
                    "mandatory_training_incomplete": training_summary.mandatory_training_incomplete,
                    "expired_or_failed_training": training_summary.expired_or_failed_training,
                },
            ),
        )

    if (
        training_summary.expired_certifications > 0
        or training_summary.pending_certification_reviews > 0
    ):
        candidates.append(
            GapCandidate(
                gap_type=CapabilityGapType.CERTIFICATION_GAP,
                severity=CapabilityGapSeverity.MEDIUM,
                title="Certification compliance gaps",
                detail=(
                    f"{training_summary.expired_certifications} expired certification(s) and "
                    f"{training_summary.pending_certification_reviews} pending review(s)."
                ),
                evidence={
                    "expired_certifications": training_summary.expired_certifications,
                    "pending_certification_reviews": training_summary.pending_certification_reviews,
                },
            ),
        )

    latest_utilization = await _load_latest_team_utilization(session, project.id)
    for team_id, snapshot in latest_utilization.items():
        pct = snapshot.utilization_pct
        if pct >= UTILIZATION_OVERLOAD_THRESHOLD:
            severity = (
                CapabilityGapSeverity.HIGH
                if pct >= UTILIZATION_CRITICAL_THRESHOLD
                else CapabilityGapSeverity.MEDIUM
            )
            candidates.append(
                GapCandidate(
                    gap_type=CapabilityGapType.UTILIZATION_OVERLOAD,
                    severity=severity,
                    title=f"Utilization overload ({pct}%)",
                    detail=f"Latest team utilization is {pct}%, at or above {UTILIZATION_OVERLOAD_THRESHOLD}%.",
                    team_id=team_id,
                    evidence={
                        "utilization_pct": float(pct),
                        "snapshot_id": str(snapshot.id),
                        "snapshot_date": snapshot.snapshot_date.isoformat(),
                    },
                ),
            )
        elif pct < UTILIZATION_UNDERLOAD_THRESHOLD:
            candidates.append(
                GapCandidate(
                    gap_type=CapabilityGapType.UTILIZATION_UNDERLOAD,
                    severity=CapabilityGapSeverity.LOW,
                    title=f"Utilization underload ({pct}%)",
                    detail=f"Latest team utilization is {pct}%, below {UTILIZATION_UNDERLOAD_THRESHOLD}%.",
                    team_id=team_id,
                    evidence={
                        "utilization_pct": float(pct),
                        "snapshot_id": str(snapshot.id),
                        "snapshot_date": snapshot.snapshot_date.isoformat(),
                    },
                ),
            )

    return candidates


async def _persist_candidates(
    session: AsyncSession,
    project: Project,
    candidates: list[GapCandidate],
    existing_by_key: dict[tuple[str, UUID | None, UUID | None], CapabilityGap],
) -> tuple[list[CapabilityGap], int]:
    now = datetime.now(timezone.utc)
    persisted: list[CapabilityGap] = []
    created_count = 0

    for candidate in candidates:
        key = _dedupe_key(candidate.gap_type, candidate.team_id, candidate.skill_id)
        existing = existing_by_key.get(key)
        if existing is not None:
            persisted.append(existing)
            continue

        gap = CapabilityGap(
            org_id=project.org_id,
            project_id=project.id,
            team_id=candidate.team_id,
            skill_id=candidate.skill_id,
            gap_type=candidate.gap_type,
            severity=candidate.severity,
            title=candidate.title,
            detail=candidate.detail,
            evidence=candidate.evidence,
            status=CapabilityGapStatus.OPEN,
            detected_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(gap)
        await session.flush()
        existing_by_key[key] = gap
        persisted.append(gap)
        created_count += 1

    return persisted, created_count


async def _find_open_workforce_risk_by_title(
    session: AsyncSession,
    project_id: UUID,
    title: str,
) -> RiskAlert | None:
    return (
        await session.execute(
            select(RiskAlert).where(
                RiskAlert.project_id == project_id,
                RiskAlert.deleted_at.is_(None),
                RiskAlert.alert_type == AlertType.WORKFORCE_IMBALANCE,
                RiskAlert.status.in_(OPEN_ALERT_STATUSES),
                RiskAlert.title == title,
            ),
        )
    ).scalar_one_or_none()


async def _create_workforce_risk_and_recommendation(
    session: AsyncSession,
    project: Project,
    gap: CapabilityGap,
) -> tuple[int, int]:
    if gap.severity not in {CapabilityGapSeverity.HIGH, CapabilityGapSeverity.CRITICAL}:
        return 0, 0

    risk_alerts_created = 0
    recommendations_created = 0

    existing_risk = await _find_open_workforce_risk_by_title(session, project.id, gap.title)
    if existing_risk is None:
        risk = RiskAlert(
            project_id=project.id,
            org_id=project.org_id,
            alert_type=AlertType.WORKFORCE_IMBALANCE,
            risk_tier=_gap_severity_to_risk_tier(gap.severity),
            title=gap.title,
            detail=gap.detail,
            status=AlertStatus.OPEN,
            contributing_causes={"workforce_imbalance": 1.0},
        )
        session.add(risk)
        await session.flush()
        risk_alerts_created = 1
        existing_risk = risk

    existing_recommendation = (
        await session.execute(
            select(MitigationRecommendation).where(
                MitigationRecommendation.project_id == project.id,
                MitigationRecommendation.deleted_at.is_(None),
                MitigationRecommendation.source_risk_id == existing_risk.id,
            ),
        )
    ).scalar_one_or_none()

    if existing_recommendation is None:
        title, description = generate_mitigation_copy(existing_risk)
        session.add(
            MitigationRecommendation(
                project_id=project.id,
                org_id=project.org_id,
                title=title,
                description=description,
                severity=_gap_severity_to_recommendation_severity(gap.severity),
                confidence_score=Decimal("0.750"),
                status=RecommendationStatus.PENDING,
                source_risk_id=existing_risk.id,
            ),
        )
        await session.flush()
        recommendations_created = 1

    return risk_alerts_created, recommendations_created


def gap_visible_to_user(gap: CapabilityGap, current_user: CurrentUser) -> bool:
    if not can_read_annotators(current_user):
        return False
    if current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        return True
    return gap.org_id == current_user.org_id


async def get_capability_gap_or_404(
    session: AsyncSession,
    gap_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> CapabilityGap:
    gap = (
        await session.execute(
            select(CapabilityGap).where(
                CapabilityGap.id == gap_id,
                CapabilityGap.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if gap is None:
        raise ApiError(404, "NOT_FOUND", "Capability gap was not found.", {"gap_id": str(gap_id)})

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and gap.org_id != current_user.org_id:
            raise ApiError(404, "NOT_FOUND", "Capability gap was not found.", {"gap_id": str(gap_id)})
        return gap

    if not gap_visible_to_user(gap, current_user):
        if current_user.role == AppRole.CLIENT:
            raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
        raise ApiError(404, "NOT_FOUND", "Capability gap was not found.", {"gap_id": str(gap_id)})
    return gap


async def list_project_capability_gaps(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> list[CapabilityGap]:
    assert_can_read_annotators(current_user)
    query = (
        select(CapabilityGap)
        .where(
            CapabilityGap.project_id == project.id,
            CapabilityGap.deleted_at.is_(None),
        )
        .order_by(CapabilityGap.detected_at.desc(), CapabilityGap.created_at.desc())
    )
    if current_user.role == AppRole.DELIVERY_MANAGER:
        query = query.where(CapabilityGap.org_id == current_user.org_id)
    return list((await session.execute(query)).scalars().all())


async def detect_and_persist_capability_gaps(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    create_alerts: bool = True,
) -> CapabilityGapDetectionResponse:
    assert_can_manage_workforce(current_user)
    if current_user.role != AppRole.SUPER_ADMIN and project.org_id != current_user.org_id:
        raise ApiError(404, "NOT_FOUND", "Project was not found.", {"project_id": str(project.id)})

    candidates = await detect_gap_candidates(session, project, current_user)
    existing_by_key = await _load_existing_open_gaps(session, project.id)
    gaps, created_count = await _persist_candidates(session, project, candidates, existing_by_key)

    risk_alerts_created = 0
    recommendations_created = 0
    if create_alerts:
        for gap in gaps:
            if gap.severity in {CapabilityGapSeverity.HIGH, CapabilityGapSeverity.CRITICAL}:
                alerts, recs = await _create_workforce_risk_and_recommendation(session, project, gap)
                risk_alerts_created += alerts
                recommendations_created += recs

    return CapabilityGapDetectionResponse(
        project_id=project.id,
        detected_count=len(candidates),
        created_count=created_count,
        gaps=[CapabilityGapRead.model_validate(gap) for gap in gaps],
        risk_alerts_created=risk_alerts_created,
        recommendations_created=recommendations_created,
    )


async def update_capability_gap(
    session: AsyncSession,
    gap: CapabilityGap,
    payload: CapabilityGapUpdate,
    current_user: CurrentUser,
) -> CapabilityGap:
    assert_can_manage_workforce(current_user)
    data = payload.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)

    if "team_id" in data or "skill_id" in data:
        raise ApiError(400, "VALIDATION_ERROR", "team_id and skill_id cannot be updated.")

    if payload.status is not None:
        previous_status = gap.status
        gap.status = payload.status
        if payload.status == CapabilityGapStatus.RESOLVED and gap.resolved_at is None:
            gap.resolved_at = now
        elif payload.status in OPEN_GAP_STATUSES and previous_status == CapabilityGapStatus.RESOLVED:
            gap.resolved_at = None

    for field in ("severity", "title", "detail"):
        if field in data:
            setattr(gap, field, data[field])

    gap.updated_at = now
    await session.flush()
    return gap


async def soft_delete_capability_gap(session: AsyncSession, gap: CapabilityGap) -> None:
    gap.deleted_at = datetime.now(timezone.utc)
    await session.flush()


async def generate_workforce_recommendations(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> tuple[int, list[dict]]:
    assert_can_manage_workforce(current_user)
    if current_user.role != AppRole.SUPER_ADMIN and project.org_id != current_user.org_id:
        raise ApiError(404, "NOT_FOUND", "Project was not found.", {"project_id": str(project.id)})

    gaps = (
        await session.execute(
            select(CapabilityGap).where(
                CapabilityGap.project_id == project.id,
                CapabilityGap.deleted_at.is_(None),
                CapabilityGap.status.in_(OPEN_GAP_STATUSES),
                CapabilityGap.severity.in_(
                    {CapabilityGapSeverity.HIGH, CapabilityGapSeverity.CRITICAL},
                ),
            ),
        )
    ).scalars().all()

    created = 0
    for gap in gaps:
        _, recs = await _create_workforce_risk_and_recommendation(session, project, gap)
        created += recs

    await sync_recommendations_for_project(
        session,
        project_id=project.id,
        org_id=project.org_id,
    )

    recommendation_rows = (
        await session.execute(
            select(MitigationRecommendation).where(
                MitigationRecommendation.project_id == project.id,
                MitigationRecommendation.deleted_at.is_(None),
                MitigationRecommendation.source_risk_id.is_not(None),
            ).order_by(MitigationRecommendation.created_at.desc()),
        )
    ).scalars().all()

    reads = [
        {
            "id": row.id,
            "project_id": row.project_id,
            "title": row.title,
            "description": row.description,
            "severity": row.severity.value,
            "confidence_score": row.confidence_score,
            "status": row.status.value,
            "owner_type": row.owner_type.value if row.owner_type else None,
            "owner_id": row.owner_id,
            "owner_label": None,
            "source_risk_id": row.source_risk_id,
            "source_risk_title": None,
            "source_risk_type": AlertType.WORKFORCE_IMBALANCE.value,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in recommendation_rows
    ]
    return created, reads


async def validate_gap_team_and_skill(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    team_id: UUID | None,
    skill_id: UUID | None,
) -> None:
    if team_id is not None:
        team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
        if team.project_id != project.id or team.org_id != project.org_id:
            raise ApiError(404, "NOT_FOUND", "Team was not found.", {"team_id": str(team_id)})
    if skill_id is not None:
        skill = await get_skill_or_404(session, skill_id, current_user, for_mutation=True)
        if skill.org_id != project.org_id:
            raise ApiError(404, "NOT_FOUND", "Skill was not found.", {"skill_id": str(skill_id)})
