from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.security import CurrentUser, require_role
from app.db.models import Annotator, AnnotatorSkill, AppRole, ProjectSkillRequirement, Skill, Team, UtilizationSnapshot
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    AnnotatorCreate,
    AnnotatorRead,
    AnnotatorSkillCreate,
    AnnotatorSkillRead,
    AnnotatorSkillUpdate,
    AnnotatorUpdate,
    ProjectSkillRequirementCreate,
    ProjectSkillRequirementRead,
    ProjectSkillRequirementUpdate,
    SkillCreate,
    SkillMatrixRead,
    SkillRead,
    SkillUpdate,
    TeamCreate,
    TeamRead,
    TeamUpdate,
    UtilizationSnapshotCreate,
    UtilizationSnapshotRead,
    UtilizationSnapshotUpdate,
)
from app.services.scoping import get_visible_project
from app.services.workforce import (
    create_annotator,
    create_team,
    create_utilization_snapshot,
    get_annotator_or_404,
    get_team_or_404,
    get_utilization_snapshot_or_404,
    soft_delete_annotator,
    soft_delete_team,
    soft_delete_utilization_snapshot,
    update_annotator,
    update_team,
    update_utilization_snapshot,
)
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

router = APIRouter(tags=["workforce"])


@router.get("/projects/{project_id}/teams", response_model=ListResponse[TeamRead])
async def list_teams(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    limit: LimitQuery = 100,
) -> ListResponse[TeamRead]:
    project = await get_visible_project(session, project_id, current_user)
    rows = (
        await session.execute(
            select(Team)
            .where(Team.project_id == project.id, Team.deleted_at.is_(None))
            .order_by(Team.name)
            .limit(limit)
        )
    ).scalars()
    return ListResponse(
        data=[TeamRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/projects/{project_id}/teams", response_model=DataResponse[TeamRead])
async def create_team_route(
    project_id: UUID,
    payload: TeamCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TeamRead]:
    project = await get_visible_project(session, project_id, current_user)
    team = await create_team(session, project, payload)
    await session.commit()
    await session.refresh(team)
    return DataResponse(data=TeamRead.model_validate(team))


@router.patch("/teams/{team_id}", response_model=DataResponse[TeamRead])
async def update_team_route(
    team_id: UUID,
    payload: TeamUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TeamRead]:
    team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
    team = await update_team(session, team, payload)
    await session.commit()
    await session.refresh(team)
    return DataResponse(data=TeamRead.model_validate(team))


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team_route(
    team_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
    await soft_delete_team(session, team)
    await session.commit()
    return Response(status_code=204)


@router.get("/teams/{team_id}/annotators", response_model=ListResponse[AnnotatorRead])
async def list_annotators(
    team_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[AnnotatorRead]:
    team = await get_team_or_404(session, team_id, current_user)
    rows = (
        await session.execute(
            select(Annotator)
            .where(Annotator.team_id == team.id, Annotator.deleted_at.is_(None))
            .order_by(Annotator.full_name)
            .limit(limit)
        )
    ).scalars()
    return ListResponse(
        data=[AnnotatorRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/teams/{team_id}/annotators", response_model=DataResponse[AnnotatorRead])
async def create_annotator_route(
    team_id: UUID,
    payload: AnnotatorCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[AnnotatorRead]:
    team = await get_team_or_404(session, team_id, current_user, for_mutation=True)
    annotator = await create_annotator(session, team, payload)
    await session.commit()
    await session.refresh(annotator)
    return DataResponse(data=AnnotatorRead.model_validate(annotator))


@router.patch("/annotators/{annotator_id}", response_model=DataResponse[AnnotatorRead])
async def update_annotator_route(
    annotator_id: UUID,
    payload: AnnotatorUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[AnnotatorRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    annotator = await update_annotator(session, annotator, payload, current_user=current_user)
    await session.commit()
    await session.refresh(annotator)
    return DataResponse(data=AnnotatorRead.model_validate(annotator))


@router.delete("/annotators/{annotator_id}", status_code=204)
async def delete_annotator_route(
    annotator_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    await soft_delete_annotator(session, annotator)
    await session.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/utilization", response_model=ListResponse[UtilizationSnapshotRead])
async def list_utilization_snapshots(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    team_id: UUID | None = None,
    annotator_id: UUID | None = None,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: LimitQuery = 100,
) -> ListResponse[UtilizationSnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    query = (
        select(UtilizationSnapshot)
        .where(
            UtilizationSnapshot.project_id == project.id,
            UtilizationSnapshot.deleted_at.is_(None),
        )
        .order_by(UtilizationSnapshot.snapshot_date.desc())
        .limit(limit)
    )
    if team_id is not None:
        query = query.where(UtilizationSnapshot.team_id == team_id)
    if annotator_id is not None:
        query = query.where(UtilizationSnapshot.annotator_id == annotator_id)
    if from_date is not None:
        query = query.where(UtilizationSnapshot.snapshot_date >= from_date)
    if to_date is not None:
        query = query.where(UtilizationSnapshot.snapshot_date <= to_date)
    rows = (await session.execute(query)).scalars()
    return ListResponse(
        data=[UtilizationSnapshotRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/projects/{project_id}/utilization", response_model=DataResponse[UtilizationSnapshotRead])
async def create_utilization_snapshot_route(
    project_id: UUID,
    payload: UtilizationSnapshotCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[UtilizationSnapshotRead]:
    project = await get_visible_project(session, project_id, current_user)
    snapshot = await create_utilization_snapshot(session, project, payload, current_user)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=UtilizationSnapshotRead.model_validate(snapshot))


@router.patch("/utilization/{snapshot_id}", response_model=DataResponse[UtilizationSnapshotRead])
async def update_utilization_snapshot_route(
    snapshot_id: UUID,
    payload: UtilizationSnapshotUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[UtilizationSnapshotRead]:
    snapshot = await get_utilization_snapshot_or_404(
        session,
        snapshot_id,
        current_user,
        for_mutation=True,
    )
    snapshot = await update_utilization_snapshot(session, snapshot, payload, current_user)
    await session.commit()
    await session.refresh(snapshot)
    return DataResponse(data=UtilizationSnapshotRead.model_validate(snapshot))


@router.delete("/utilization/{snapshot_id}", status_code=204)
async def delete_utilization_snapshot_route(
    snapshot_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    snapshot = await get_utilization_snapshot_or_404(
        session,
        snapshot_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_utilization_snapshot(session, snapshot)
    await session.commit()
    return Response(status_code=204)


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
