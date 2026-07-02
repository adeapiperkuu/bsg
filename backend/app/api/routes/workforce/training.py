from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import LimitQuery, SessionDep
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, EmployeeCertification, TrainingRecord
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    CertificationCreate,
    CertificationRead,
    CertificationUpdate,
    EmployeeCertificationCreate,
    EmployeeCertificationRead,
    EmployeeCertificationUpdate,
    TrainingGapSummaryRead,
    TrainingProgramCreate,
    TrainingProgramRead,
    TrainingProgramUpdate,
    TrainingRecordCreate,
    TrainingRecordRead,
    TrainingRecordUpdate,
)
from app.services.scoping import get_visible_project
from app.services.workforce import get_annotator_or_404
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

router = APIRouter()


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
