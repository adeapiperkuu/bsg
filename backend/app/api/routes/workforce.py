from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep, UserDep
from app.core.security import CurrentUser, require_role
from app.db.models import (
    Annotator,
    AnnotatorSkill,
    AppRole,
    EmployeeCertification,
    ProjectSkillRequirement,
    Skill,
    Team,
    TrainingRecord,
    UtilizationSnapshot,
)
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    AnnotatorCreate,
    AnnotatorRead,
    AnnotatorSkillCreate,
    AnnotatorSkillRead,
    AnnotatorSkillUpdate,
    AnnotatorUpdate,
    CapabilityGapDetectionResponse,
    CapabilityGapRead,
    CapabilityGapUpdate,
    CertificationCreate,
    CertificationRead,
    CertificationUpdate,
    EmployeeCertificationCreate,
    EmployeeCertificationRead,
    EmployeeCertificationUpdate,
    ProjectSkillRequirementCreate,
    ProjectSkillRequirementRead,
    ProjectSkillRequirementUpdate,
    SkillCreate,
    SkillMatrixRead,
    SkillRead,
    SkillUpdate,
    SmeAllocationRead,
    TeamCreate,
    TeamRead,
    TeamUpdate,
    TrainingGapSummaryRead,
    TrainingProgramCreate,
    TrainingProgramRead,
    TrainingProgramUpdate,
    TrainingRecordCreate,
    TrainingRecordRead,
    TrainingRecordUpdate,
    UtilizationSnapshotCreate,
    UtilizationSnapshotRead,
    UtilizationSnapshotUpdate,
    WorkforceDashboardRead,
    WorkforceRecommendationGenerateResponse,
)
from app.services.scoping import get_visible_project
from app.services.workforce import (
    create_annotator,
    create_team,
    create_utilization_snapshot,
    get_annotator_or_404,
    get_sme_allocation,
    get_team_or_404,
    get_utilization_snapshot_or_404,
    get_workforce_dashboard,
    soft_delete_annotator,
    soft_delete_team,
    soft_delete_utilization_snapshot,
    update_annotator,
    update_team,
    update_utilization_snapshot,
)
from app.services.workforce_gaps import (
    detect_and_persist_capability_gaps,
    generate_workforce_recommendations,
    get_capability_gap_or_404,
    list_project_capability_gaps,
    soft_delete_capability_gap,
    update_capability_gap,
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
from app.services.workforce_training import (
    build_project_training_gaps,
    create_certification,
    create_employee_certification,
    create_training_program,
    create_training_record,
    get_certification_or_404,
    get_employee_certification_or_404,
    get_training_program_or_404,
    get_training_record_or_404,
    scoped_certifications_query,
    scoped_training_programs_query,
    soft_delete_certification,
    soft_delete_employee_certification,
    soft_delete_training_program,
    soft_delete_training_record,
    update_certification,
    update_employee_certification,
    update_training_program,
    update_training_record,
)

router = APIRouter(tags=["workforce"])


@router.get("/workforce/dashboard", response_model=DataResponse[WorkforceDashboardRead])
async def workforce_dashboard(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[WorkforceDashboardRead]:
    dashboard = await get_workforce_dashboard(session, current_user)
    return DataResponse(data=dashboard)


@router.get("/workforce/skill-matrix", response_model=DataResponse[WorkforceDashboardRead])
async def workforce_skill_matrix(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[WorkforceDashboardRead]:
    dashboard = await get_workforce_dashboard(session, current_user)
    return DataResponse(
        data=WorkforceDashboardRead(
            kpis=dashboard.kpis,
            skill_matrix=dashboard.skill_matrix,
            skill_gap_signals=dashboard.skill_gap_signals,
        )
    )


@router.get("/workforce/sme-allocation", response_model=ListResponse[SmeAllocationRead])
async def workforce_sme_allocation(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[SmeAllocationRead]:
    rows = await get_sme_allocation(session, current_user.org_id)
    return ListResponse(data=rows, pagination=Pagination(limit=100))


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


@router.get("/workforce/certifications", response_model=ListResponse[CertificationRead])
async def list_certifications(
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[CertificationRead]:
    rows = (await session.execute(scoped_certifications_query(current_user).limit(limit))).scalars()
    return ListResponse(
        data=[CertificationRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/workforce/certifications", response_model=DataResponse[CertificationRead])
async def create_certification_route(
    payload: CertificationCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CertificationRead]:
    certification = await create_certification(session, current_user, payload)
    await session.commit()
    await session.refresh(certification)
    return DataResponse(data=CertificationRead.model_validate(certification))


@router.patch("/workforce/certifications/{certification_id}", response_model=DataResponse[CertificationRead])
async def update_certification_route(
    certification_id: UUID,
    payload: CertificationUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CertificationRead]:
    certification = await get_certification_or_404(session, certification_id, current_user, for_mutation=True)
    certification = await update_certification(session, certification, payload)
    await session.commit()
    await session.refresh(certification)
    return DataResponse(data=CertificationRead.model_validate(certification))


@router.delete("/workforce/certifications/{certification_id}", status_code=204)
async def delete_certification_route(
    certification_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    certification = await get_certification_or_404(session, certification_id, current_user, for_mutation=True)
    await soft_delete_certification(session, certification)
    await session.commit()
    return Response(status_code=204)


@router.get("/annotators/{annotator_id}/certifications", response_model=ListResponse[EmployeeCertificationRead])
async def list_annotator_certifications(
    annotator_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[EmployeeCertificationRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user)
    rows = (
        await session.execute(
            select(EmployeeCertification)
            .where(
                EmployeeCertification.annotator_id == annotator.id,
                EmployeeCertification.deleted_at.is_(None),
            )
            .order_by(EmployeeCertification.created_at.desc())
            .limit(limit),
        )
    ).scalars()
    return ListResponse(
        data=[EmployeeCertificationRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/annotators/{annotator_id}/certifications", response_model=DataResponse[EmployeeCertificationRead])
async def create_employee_certification_route(
    annotator_id: UUID,
    payload: EmployeeCertificationCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[EmployeeCertificationRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    assignment = await create_employee_certification(session, annotator, payload, current_user)
    await session.commit()
    await session.refresh(assignment)
    return DataResponse(data=EmployeeCertificationRead.model_validate(assignment))


@router.patch(
    "/employee-certifications/{employee_certification_id}",
    response_model=DataResponse[EmployeeCertificationRead],
)
async def update_employee_certification_route(
    employee_certification_id: UUID,
    payload: EmployeeCertificationUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[EmployeeCertificationRead]:
    assignment = await get_employee_certification_or_404(
        session,
        employee_certification_id,
        current_user,
        for_mutation=True,
    )
    assignment = await update_employee_certification(session, assignment, payload)
    await session.commit()
    await session.refresh(assignment)
    return DataResponse(data=EmployeeCertificationRead.model_validate(assignment))


@router.delete("/employee-certifications/{employee_certification_id}", status_code=204)
async def delete_employee_certification_route(
    employee_certification_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    assignment = await get_employee_certification_or_404(
        session,
        employee_certification_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_employee_certification(session, assignment)
    await session.commit()
    return Response(status_code=204)


@router.get("/workforce/training-programs", response_model=ListResponse[TrainingProgramRead])
async def list_training_programs(
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[TrainingProgramRead]:
    rows = (await session.execute(scoped_training_programs_query(current_user).limit(limit))).scalars()
    return ListResponse(
        data=[TrainingProgramRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/workforce/training-programs", response_model=DataResponse[TrainingProgramRead])
async def create_training_program_route(
    payload: TrainingProgramCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TrainingProgramRead]:
    program = await create_training_program(session, current_user, payload)
    await session.commit()
    await session.refresh(program)
    return DataResponse(data=TrainingProgramRead.model_validate(program))


@router.patch("/workforce/training-programs/{training_program_id}", response_model=DataResponse[TrainingProgramRead])
async def update_training_program_route(
    training_program_id: UUID,
    payload: TrainingProgramUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TrainingProgramRead]:
    program = await get_training_program_or_404(
        session,
        training_program_id,
        current_user,
        for_mutation=True,
    )
    program = await update_training_program(session, program, payload, current_user)
    await session.commit()
    await session.refresh(program)
    return DataResponse(data=TrainingProgramRead.model_validate(program))


@router.delete("/workforce/training-programs/{training_program_id}", status_code=204)
async def delete_training_program_route(
    training_program_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    program = await get_training_program_or_404(
        session,
        training_program_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_training_program(session, program)
    await session.commit()
    return Response(status_code=204)


@router.get("/annotators/{annotator_id}/training-records", response_model=ListResponse[TrainingRecordRead])
async def list_annotator_training_records(
    annotator_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
    limit: LimitQuery = 100,
) -> ListResponse[TrainingRecordRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user)
    rows = (
        await session.execute(
            select(TrainingRecord)
            .where(
                TrainingRecord.annotator_id == annotator.id,
                TrainingRecord.deleted_at.is_(None),
            )
            .order_by(TrainingRecord.created_at.desc())
            .limit(limit),
        )
    ).scalars()
    return ListResponse(
        data=[TrainingRecordRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=limit),
    )


@router.post("/annotators/{annotator_id}/training-records", response_model=DataResponse[TrainingRecordRead])
async def create_training_record_route(
    annotator_id: UUID,
    payload: TrainingRecordCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TrainingRecordRead]:
    annotator = await get_annotator_or_404(session, annotator_id, current_user, for_mutation=True)
    record = await create_training_record(session, annotator, payload, current_user)
    await session.commit()
    await session.refresh(record)
    return DataResponse(data=TrainingRecordRead.model_validate(record))


@router.patch("/training-records/{training_record_id}", response_model=DataResponse[TrainingRecordRead])
async def update_training_record_route(
    training_record_id: UUID,
    payload: TrainingRecordUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[TrainingRecordRead]:
    record = await get_training_record_or_404(
        session,
        training_record_id,
        current_user,
        for_mutation=True,
    )
    record = await update_training_record(session, record, payload)
    await session.commit()
    await session.refresh(record)
    return DataResponse(data=TrainingRecordRead.model_validate(record))


@router.delete("/training-records/{training_record_id}", status_code=204)
async def delete_training_record_route(
    training_record_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    record = await get_training_record_or_404(
        session,
        training_record_id,
        current_user,
        for_mutation=True,
    )
    await soft_delete_training_record(session, record)
    await session.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/training-gaps", response_model=DataResponse[TrainingGapSummaryRead])
async def get_project_training_gaps(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
) -> DataResponse[TrainingGapSummaryRead]:
    project = await get_visible_project(session, project_id, current_user)
    summary = await build_project_training_gaps(session, project, current_user)
    return DataResponse(data=summary)


@router.get("/projects/{project_id}/capability-gaps", response_model=ListResponse[CapabilityGapRead])
async def list_capability_gaps_route(
    project_id: UUID,
    session: SessionDep,
    limit: LimitQuery = 50,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN),
    ),
) -> ListResponse[CapabilityGapRead]:
    project = await get_visible_project(session, project_id, current_user)
    gaps = await list_project_capability_gaps(session, project, current_user)
    page = gaps[:limit]
    return ListResponse(
        data=page,
        pagination=Pagination(total=len(gaps), limit=limit, offset=0),
    )


@router.post(
    "/projects/{project_id}/capability-gaps/detect",
    response_model=DataResponse[CapabilityGapDetectionResponse],
)
async def detect_capability_gaps_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CapabilityGapDetectionResponse]:
    project = await get_visible_project(session, project_id, current_user)
    result = await detect_and_persist_capability_gaps(session, project, current_user)
    await session.commit()
    return DataResponse(data=result)


@router.patch("/capability-gaps/{gap_id}", response_model=DataResponse[CapabilityGapRead])
async def update_capability_gap_route(
    gap_id: UUID,
    payload: CapabilityGapUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[CapabilityGapRead]:
    gap = await get_capability_gap_or_404(session, gap_id, current_user, for_mutation=True)
    updated = await update_capability_gap(session, gap, payload, current_user)
    await session.commit()
    return DataResponse(data=updated)


@router.delete("/capability-gaps/{gap_id}", status_code=204)
async def delete_capability_gap_route(
    gap_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> Response:
    gap = await get_capability_gap_or_404(session, gap_id, current_user, for_mutation=True)
    await soft_delete_capability_gap(session, gap)
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/projects/{project_id}/workforce-recommendations/generate",
    response_model=DataResponse[WorkforceRecommendationGenerateResponse],
)
async def generate_workforce_recommendations_route(
    project_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[WorkforceRecommendationGenerateResponse]:
    project = await get_visible_project(session, project_id, current_user)
    created_count, recommendations = await generate_workforce_recommendations(
        session,
        project,
        current_user,
    )
    await session.commit()
    return DataResponse(
        data=WorkforceRecommendationGenerateResponse(
            project_id=project.id,
            recommendations_created=created_count,
            recommendations=recommendations,
        ),
    )
