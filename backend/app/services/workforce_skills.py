"""Workforce skills taxonomy, assignments, requirements, and matrix."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    Annotator,
    AnnotatorSkill,
    AppRole,
    DeliverySite,
    ProficiencyLevel,
    Project,
    ProjectSkillRequirement,
    Skill,
    SkillCoverageStatus,
    Team,
)
from app.schemas.domain import (
    AnnotatorSkillCreate,
    AnnotatorSkillUpdate,
    ProjectSkillRequirementCreate,
    ProjectSkillRequirementUpdate,
    SkillCreate,
    SkillMatrixRead,
    SkillMatrixRow,
    SkillMatrixSiteSummary,
    SkillUpdate,
)
from app.services.workforce import (
    assert_can_manage_workforce,
    assert_can_read_annotators,
    can_read_annotators,
    get_annotator_or_404,
)

PROFICIENCY_RANK: dict[ProficiencyLevel, int] = {
    ProficiencyLevel.BEGINNER: 1,
    ProficiencyLevel.INTERMEDIATE: 2,
    ProficiencyLevel.ADVANCED: 3,
    ProficiencyLevel.EXPERT: 4,
}


def meets_proficiency(actual: ProficiencyLevel, required: ProficiencyLevel) -> bool:
    return PROFICIENCY_RANK[actual] >= PROFICIENCY_RANK[required]


def compute_coverage_status(
    available_headcount: int,
    required_headcount: int,
    available_sme_count: int,
    required_sme_count: int,
) -> SkillCoverageStatus:
    if available_headcount >= required_headcount and available_sme_count >= required_sme_count:
        return SkillCoverageStatus.HIGH
    if available_headcount > 0:
        return SkillCoverageStatus.MEDIUM
    return SkillCoverageStatus.LOW


def skill_visible_to_user(skill: Skill, current_user: CurrentUser) -> bool:
    if not can_read_annotators(current_user):
        return False
    if current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        return True
    return skill.org_id == current_user.org_id


def scoped_skills_query(current_user: CurrentUser):
    assert_can_read_annotators(current_user)
    query = select(Skill).where(Skill.deleted_at.is_(None)).order_by(Skill.name)
    if current_user.role == AppRole.DELIVERY_MANAGER:
        query = query.where(Skill.org_id == current_user.org_id)
    return query


async def get_skill_or_404(
    session: AsyncSession,
    skill_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> Skill:
    skill = (
        await session.execute(
            select(Skill).where(Skill.id == skill_id, Skill.deleted_at.is_(None)),
        )
    ).scalar_one_or_none()
    if skill is None:
        raise ApiError(404, "NOT_FOUND", "Skill was not found.", {"skill_id": str(skill_id)})

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and skill.org_id != current_user.org_id:
            raise ApiError(404, "NOT_FOUND", "Skill was not found.", {"skill_id": str(skill_id)})
        return skill

    if not skill_visible_to_user(skill, current_user):
        raise ApiError(404, "NOT_FOUND", "Skill was not found.", {"skill_id": str(skill_id)})
    return skill


async def assert_skill_in_org(skill: Skill, org_id: UUID) -> None:
    if skill.org_id != org_id:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Skill org_id must match the resource org_id.",
            {"skill_id": str(skill.id)},
        )


async def assert_no_duplicate_annotator_skill(
    session: AsyncSession,
    annotator_id: UUID,
    skill_id: UUID,
) -> None:
    existing = (
        await session.execute(
            select(AnnotatorSkill.id).where(
                AnnotatorSkill.annotator_id == annotator_id,
                AnnotatorSkill.skill_id == skill_id,
                AnnotatorSkill.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            409,
            "CONFLICT",
            "Annotator already has this skill assignment.",
            {"annotator_id": str(annotator_id), "skill_id": str(skill_id)},
        )


async def assert_no_duplicate_project_requirement(
    session: AsyncSession,
    project_id: UUID,
    skill_id: UUID,
) -> None:
    existing = (
        await session.execute(
            select(ProjectSkillRequirement.id).where(
                ProjectSkillRequirement.project_id == project_id,
                ProjectSkillRequirement.skill_id == skill_id,
                ProjectSkillRequirement.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            409,
            "CONFLICT",
            "Project already has a requirement for this skill.",
            {"project_id": str(project_id), "skill_id": str(skill_id)},
        )


async def create_skill(session: AsyncSession, current_user: CurrentUser, payload: SkillCreate) -> Skill:
    assert_can_manage_workforce(current_user)
    skill = Skill(
        org_id=current_user.org_id,
        **payload.model_dump(),
    )
    session.add(skill)
    await session.flush()
    return skill


async def update_skill(session: AsyncSession, skill: Skill, payload: SkillUpdate) -> Skill:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(skill, key, value)
    return skill


async def soft_delete_skill(session: AsyncSession, skill: Skill) -> None:
    skill.deleted_at = datetime.now(timezone.utc)


async def get_annotator_skill_or_404(
    session: AsyncSession,
    annotator_skill_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> AnnotatorSkill:
    assignment = (
        await session.execute(
            select(AnnotatorSkill).where(
                AnnotatorSkill.id == annotator_skill_id,
                AnnotatorSkill.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Annotator skill assignment was not found.",
            {"annotator_skill_id": str(annotator_skill_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and assignment.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Annotator skill assignment was not found.",
                {"annotator_skill_id": str(annotator_skill_id)},
            )
        return assignment

    assert_can_read_annotators(current_user)
    if current_user.role not in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        if assignment.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Annotator skill assignment was not found.",
                {"annotator_skill_id": str(annotator_skill_id)},
            )
    return assignment


async def create_annotator_skill(
    session: AsyncSession,
    annotator: Annotator,
    payload: AnnotatorSkillCreate,
    current_user: CurrentUser,
) -> AnnotatorSkill:
    skill = await get_skill_or_404(session, payload.skill_id, current_user, for_mutation=True)
    await assert_skill_in_org(skill, annotator.org_id)
    await assert_no_duplicate_annotator_skill(session, annotator.id, payload.skill_id)

    assignment = AnnotatorSkill(
        org_id=annotator.org_id,
        annotator_id=annotator.id,
        skill_id=skill.id,
        proficiency_level=payload.proficiency_level,
        verified_by=payload.verified_by,
        verified_at=payload.verified_at,
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def update_annotator_skill(
    session: AsyncSession,
    assignment: AnnotatorSkill,
    payload: AnnotatorSkillUpdate,
) -> AnnotatorSkill:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(assignment, key, value)
    return assignment


async def soft_delete_annotator_skill(session: AsyncSession, assignment: AnnotatorSkill) -> None:
    assignment.deleted_at = datetime.now(timezone.utc)


async def get_project_skill_requirement_or_404(
    session: AsyncSession,
    requirement_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> ProjectSkillRequirement:
    requirement = (
        await session.execute(
            select(ProjectSkillRequirement).where(
                ProjectSkillRequirement.id == requirement_id,
                ProjectSkillRequirement.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if requirement is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Project skill requirement was not found.",
            {"requirement_id": str(requirement_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and requirement.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Project skill requirement was not found.",
                {"requirement_id": str(requirement_id)},
            )
        return requirement

    assert_can_read_annotators(current_user)
    if current_user.role not in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        if requirement.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Project skill requirement was not found.",
                {"requirement_id": str(requirement_id)},
            )
    return requirement


async def create_project_skill_requirement(
    session: AsyncSession,
    project: Project,
    payload: ProjectSkillRequirementCreate,
    current_user: CurrentUser,
) -> ProjectSkillRequirement:
    skill = await get_skill_or_404(session, payload.skill_id, current_user, for_mutation=True)
    await assert_skill_in_org(skill, project.org_id)
    await assert_no_duplicate_project_requirement(session, project.id, payload.skill_id)

    requirement = ProjectSkillRequirement(
        org_id=project.org_id,
        project_id=project.id,
        skill_id=skill.id,
        required_proficiency_level=payload.required_proficiency_level,
        required_headcount=payload.required_headcount,
        required_sme_count=payload.required_sme_count,
        priority=payload.priority,
    )
    session.add(requirement)
    await session.flush()
    return requirement


async def update_project_skill_requirement(
    session: AsyncSession,
    requirement: ProjectSkillRequirement,
    payload: ProjectSkillRequirementUpdate,
) -> ProjectSkillRequirement:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(requirement, key, value)
    return requirement


async def soft_delete_project_skill_requirement(
    session: AsyncSession,
    requirement: ProjectSkillRequirement,
) -> None:
    requirement.deleted_at = datetime.now(timezone.utc)


def _count_matching_annotators(
    annotators: list[Annotator],
    assignments_by_annotator: dict[UUID, list[AnnotatorSkill]],
    skill_id: UUID,
    required_level: ProficiencyLevel,
    *,
    site: DeliverySite | None = None,
    sme_only: bool = False,
) -> int:
    count = 0
    for annotator in annotators:
        if not annotator.is_active:
            continue
        if site is not None and annotator.site != site:
            continue
        if sme_only and not annotator.is_sme_certified:
            continue
        for assignment in assignments_by_annotator.get(annotator.id, []):
            if assignment.skill_id != skill_id:
                continue
            if meets_proficiency(assignment.proficiency_level, required_level):
                count += 1
                break
    return count


async def build_project_skill_matrix(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
) -> SkillMatrixRead:
    assert_can_read_annotators(current_user)

    requirements = (
        await session.execute(
            select(ProjectSkillRequirement)
            .where(
                ProjectSkillRequirement.project_id == project.id,
                ProjectSkillRequirement.deleted_at.is_(None),
            )
            .order_by(ProjectSkillRequirement.created_at),
        )
    ).scalars().all()

    if not requirements:
        return SkillMatrixRead(project_id=project.id, rows=[])

    skill_ids = {requirement.skill_id for requirement in requirements}
    skills = (
        await session.execute(
            select(Skill).where(Skill.id.in_(skill_ids), Skill.deleted_at.is_(None)),
        )
    ).scalars().all()
    skills_by_id = {skill.id: skill for skill in skills}

    teams = (
        await session.execute(
            select(Team).where(
                Team.project_id == project.id,
                Team.deleted_at.is_(None),
            ),
        )
    ).scalars().all()
    team_ids = [team.id for team in teams]

    annotators: list[Annotator] = []
    if team_ids:
        annotators = (
            await session.execute(
                select(Annotator).where(
                    Annotator.team_id.in_(team_ids),
                    Annotator.deleted_at.is_(None),
                ),
            )
        ).scalars().all()

    annotator_ids = [annotator.id for annotator in annotators]
    assignments_by_annotator: dict[UUID, list[AnnotatorSkill]] = {}
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
            assignments_by_annotator.setdefault(assignment.annotator_id, []).append(assignment)

    rows: list[SkillMatrixRow] = []
    for requirement in requirements:
        skill = skills_by_id.get(requirement.skill_id)
        if skill is None:
            continue

        available_headcount = _count_matching_annotators(
            annotators,
            assignments_by_annotator,
            requirement.skill_id,
            requirement.required_proficiency_level,
        )
        available_sme_count = _count_matching_annotators(
            annotators,
            assignments_by_annotator,
            requirement.skill_id,
            requirement.required_proficiency_level,
            sme_only=True,
        )
        coverage_status = compute_coverage_status(
            available_headcount,
            requirement.required_headcount,
            available_sme_count,
            requirement.required_sme_count,
        )

        by_site: list[SkillMatrixSiteSummary] = []
        for site in (DeliverySite.INDIA, DeliverySite.KOSOVO):
            site_headcount = _count_matching_annotators(
                annotators,
                assignments_by_annotator,
                requirement.skill_id,
                requirement.required_proficiency_level,
                site=site,
            )
            site_sme_count = _count_matching_annotators(
                annotators,
                assignments_by_annotator,
                requirement.skill_id,
                requirement.required_proficiency_level,
                site=site,
                sme_only=True,
            )
            by_site.append(
                SkillMatrixSiteSummary(
                    site=site,
                    available_headcount=site_headcount,
                    available_sme_count=site_sme_count,
                    coverage_status=compute_coverage_status(
                        site_headcount,
                        requirement.required_headcount,
                        site_sme_count,
                        requirement.required_sme_count,
                    ),
                ),
            )

        rows.append(
            SkillMatrixRow(
                skill_id=skill.id,
                skill_name=skill.name,
                category=skill.category,
                domain=skill.domain,
                required_proficiency_level=requirement.required_proficiency_level,
                required_headcount=requirement.required_headcount,
                available_headcount=available_headcount,
                required_sme_count=requirement.required_sme_count,
                available_sme_count=available_sme_count,
                coverage_status=coverage_status,
                by_site=by_site,
            ),
        )

    return SkillMatrixRead(project_id=project.id, rows=rows)
