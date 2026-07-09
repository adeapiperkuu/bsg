from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AnnotatorSkill, AppRole, ProjectSkillRequirement
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    AnnotatorSkillCreate,
    AnnotatorSkillRead,
    AnnotatorSkillUpdate,
    ProjectSkillRequirementCreate,
    ProjectSkillRequirementRead,
    ProjectSkillRequirementUpdate,
    SkillCreate,
    SkillMatrixRead,
    SkillRead,
    SkillUpdate,
)
from app.services.scoping import get_visible_project
from app.services.workforce import get_annotator_or_404
from app.services.workforce_skills import (
    build_project_skill_matrix,
    create_annotator_skill,
    create_project_skill_requirement,
    create_skill,
    get_annotator_skill_or_404,
    get_project_skill_requirement_or_404,
    get_skill_or_404,
    scoped_skills_query,
    soft_delete_annotator_skill,
    soft_delete_project_skill_requirement,
    soft_delete_skill,
    update_annotator_skill,
    update_project_skill_requirement,
    update_skill,
)

router = APIRouter()


@router.get("/workforce/skills", response_model=ListResponse[SkillRead])
async def list_skills(
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[SkillRead]:
    rows = (await session.execute(scoped_skills_query(current_user).limit(limit))).scalars()
    return ListResponse(
        data=[SkillRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/workforce/skills", response_model=DataResponse[SkillRead])
async def create_skill_route(
    payload: SkillCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[SkillRead]:
    skill = await create_skill(session, current_user, payload)
    await session.commit()
    await session.refresh(skill)
    return DataResponse(data=SkillRead.model_validate(skill))


@router.patch("/workforce/skills/{skill_id}", response_model=DataResponse[SkillRead])
async def update_skill_route(
    skill_id: UUID,
    payload: SkillUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[SkillRead]:
    skill = await get_skill_or_404(session, skill_id, current_user, for_mutation=True)
    skill = await update_skill(session, skill, payload)
    await session.commit()
    await session.refresh(skill)
    return DataResponse(data=SkillRead.model_validate(skill))


@router.delete("/workforce/skills/{skill_id}", status_code=204)
async def delete_skill_route(
    skill_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    skill = await get_skill_or_404(session, skill_id, current_user, for_mutation=True)
    await soft_delete_skill(session, skill)
    await session.commit()
    return Response(status_code=204)


@router.get("/annotators/{annotator_id}/skills", response_model=ListResponse[AnnotatorSkillRead])
async def list_annotator_skills(
    annotator_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[AnnotatorSkillRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user)
    rows = (
        await session.execute(
            select(AnnotatorSkill)
            .where(
                AnnotatorSkill.annotator_id == annotator.id,
                AnnotatorSkill.deleted_at.is_(None),
            )
            .order_by(AnnotatorSkill.created_at.desc())
            .limit(limit),
        )
    ).scalars()
    return ListResponse(
        data=[AnnotatorSkillRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/annotators/{annotator_id}/skills", response_model=DataResponse[AnnotatorSkillRead])
async def create_annotator_skill_route(
    annotator_id: UUID,
    payload: AnnotatorSkillCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[AnnotatorSkillRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    assignment = await create_annotator_skill(session, annotator, payload, current_user)
    await session.commit()
    await session.refresh(assignment)
    return DataResponse(data=AnnotatorSkillRead.model_validate(assignment))


@router.patch("/annotator-skills/{annotator_skill_id}", response_model=DataResponse[AnnotatorSkillRead])
async def update_annotator_skill_route(
    annotator_skill_id: UUID,
    payload: AnnotatorSkillUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[AnnotatorSkillRead]:
    assignment = await get_annotator_skill_or_404(
        session,
        annotator_skill_id,
        current_user,
        for_mutation=True,
    )
    assignment = await update_annotator_skill(session, assignment, payload)
    await session.commit()
    await session.refresh(assignment)
    return DataResponse(data=AnnotatorSkillRead.model_validate(assignment))


@router.delete("/annotator-skills/{annotator_skill_id}", status_code=204)
async def delete_annotator_skill_route(
    annotator_skill_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    assignment = await get_annotator_skill_or_404(
        session,
        annotator_skill_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_annotator_skill(session, assignment)
    await session.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/skill-requirements", response_model=ListResponse[ProjectSkillRequirementRead])
async def list_project_skill_requirements(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[ProjectSkillRequirementRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(ProjectSkillRequirement)
            .where(
                ProjectSkillRequirement.project_id == project.id,
                ProjectSkillRequirement.deleted_at.is_(None),
            )
            .order_by(ProjectSkillRequirement.created_at.desc())
            .limit(limit),
        )
    ).scalars()
    return ListResponse(
        data=[ProjectSkillRequirementRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/projects/{project_id}/skill-requirements", response_model=DataResponse[ProjectSkillRequirementRead])
async def create_project_skill_requirement_route(
    project_id: UUID,
    payload: ProjectSkillRequirementCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectSkillRequirementRead]:
    project = await get_visible_project(session, project_id, current_user)
    requirement = await create_project_skill_requirement(session, project, payload, current_user)
    await session.commit()
    await session.refresh(requirement)
    return DataResponse(data=ProjectSkillRequirementRead.model_validate(requirement))


@router.patch("/skill-requirements/{requirement_id}", response_model=DataResponse[ProjectSkillRequirementRead])
async def update_project_skill_requirement_route(
    requirement_id: UUID,
    payload: ProjectSkillRequirementUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[ProjectSkillRequirementRead]:
    requirement = await get_project_skill_requirement_or_404(
        session,
        requirement_id,
        current_user,
        for_mutation=True,
    )
    requirement = await update_project_skill_requirement(session, requirement, payload)
    await session.commit()
    await session.refresh(requirement)
    return DataResponse(data=ProjectSkillRequirementRead.model_validate(requirement))


@router.delete("/skill-requirements/{requirement_id}", status_code=204)
async def delete_project_skill_requirement_route(
    requirement_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    requirement = await get_project_skill_requirement_or_404(
        session,
        requirement_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_project_skill_requirement(session, requirement)
    await session.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/skill-matrix", response_model=DataResponse[SkillMatrixRead])
async def get_project_skill_matrix(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
) -> DataResponse[SkillMatrixRead]:
    project = await get_visible_project(session, project_id, current_user)
    matrix = await build_project_skill_matrix(session, project, current_user)
    return DataResponse(data=matrix)
