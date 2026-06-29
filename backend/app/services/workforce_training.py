"""Workforce certifications, training programs, records, and gap summaries."""

from collections import defaultdict
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    Annotator,
    AppRole,
    Certification,
    CertificationStatus,
    EmployeeCertification,
    KnowledgeDocument,
    Project,
    Skill,
    Team,
    TrainingGapType,
    TrainingProgram,
    TrainingRecord,
    TrainingRecordStatus,
)
from app.schemas.domain import (
    CertificationCreate,
    CertificationUpdate,
    EmployeeCertificationCreate,
    EmployeeCertificationUpdate,
    TrainingGapRow,
    TrainingGapSummaryRead,
    TrainingProgramCreate,
    TrainingProgramUpdate,
    TrainingRecordCreate,
    TrainingRecordUpdate,
)
from app.services.workforce import (
    assert_can_manage_workforce,
    assert_can_read_annotators,
    can_read_annotators,
    get_annotator_or_404,
)
from app.services.workforce_skills import get_skill_or_404


def certification_visible_to_user(certification: Certification, current_user: CurrentUser) -> bool:
    if not can_read_annotators(current_user):
        return False
    if current_user.role in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        return True
    return certification.org_id == current_user.org_id


def scoped_certifications_query(current_user: CurrentUser):
    assert_can_read_annotators(current_user)
    query = select(Certification).where(Certification.deleted_at.is_(None)).order_by(Certification.name)
    if current_user.role == AppRole.DELIVERY_MANAGER:
        query = query.where(Certification.org_id == current_user.org_id)
    return query


def scoped_training_programs_query(current_user: CurrentUser):
    assert_can_read_annotators(current_user)
    query = select(TrainingProgram).where(TrainingProgram.deleted_at.is_(None)).order_by(TrainingProgram.name)
    if current_user.role == AppRole.DELIVERY_MANAGER:
        query = query.where(TrainingProgram.org_id == current_user.org_id)
    return query


async def get_certification_or_404(
    session: AsyncSession,
    certification_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> Certification:
    certification = (
        await session.execute(
            select(Certification).where(
                Certification.id == certification_id,
                Certification.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if certification is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Certification was not found.",
            {"certification_id": str(certification_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and certification.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Certification was not found.",
                {"certification_id": str(certification_id)},
            )
        return certification

    if not certification_visible_to_user(certification, current_user):
        raise ApiError(
            404,
            "NOT_FOUND",
            "Certification was not found.",
            {"certification_id": str(certification_id)},
        )
    return certification


async def get_training_program_or_404(
    session: AsyncSession,
    training_program_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> TrainingProgram:
    program = (
        await session.execute(
            select(TrainingProgram).where(
                TrainingProgram.id == training_program_id,
                TrainingProgram.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if program is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Training program was not found.",
            {"training_program_id": str(training_program_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and program.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Training program was not found.",
                {"training_program_id": str(training_program_id)},
            )
        return program

    assert_can_read_annotators(current_user)
    if current_user.role not in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        if program.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Training program was not found.",
                {"training_program_id": str(training_program_id)},
            )
    return program


async def assert_resource_in_org(org_id: UUID, resource_org_id: UUID, *, resource_label: str) -> None:
    if resource_org_id != org_id:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            f"{resource_label} org_id must match the resource org_id.",
        )


async def assert_no_duplicate_employee_certification(
    session: AsyncSession,
    annotator_id: UUID,
    certification_id: UUID,
) -> None:
    existing = (
        await session.execute(
            select(EmployeeCertification.id).where(
                EmployeeCertification.annotator_id == annotator_id,
                EmployeeCertification.certification_id == certification_id,
                EmployeeCertification.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            409,
            "CONFLICT",
            "Annotator already has this certification assignment.",
            {"annotator_id": str(annotator_id), "certification_id": str(certification_id)},
        )


async def assert_no_duplicate_training_record(
    session: AsyncSession,
    annotator_id: UUID,
    training_program_id: UUID,
) -> None:
    existing = (
        await session.execute(
            select(TrainingRecord.id).where(
                TrainingRecord.annotator_id == annotator_id,
                TrainingRecord.training_program_id == training_program_id,
                TrainingRecord.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            409,
            "CONFLICT",
            "Annotator already has this training record.",
            {"annotator_id": str(annotator_id), "training_program_id": str(training_program_id)},
        )


async def validate_training_program_references(
    session: AsyncSession,
    org_id: UUID,
    payload: TrainingProgramCreate | TrainingProgramUpdate,
    current_user: CurrentUser,
    *,
    existing: TrainingProgram | None = None,
) -> None:
    data = payload.model_dump(exclude_unset=True)
    skill_id = data.get("skill_id", existing.skill_id if existing else None)
    knowledge_document_id = data.get(
        "knowledge_document_id",
        existing.knowledge_document_id if existing else None,
    )

    if skill_id is not None:
        skill = await get_skill_or_404(session, skill_id, current_user, for_mutation=True)
        await assert_resource_in_org(org_id, skill.org_id, resource_label="Skill")

    if knowledge_document_id is not None:
        document = (
            await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id == knowledge_document_id,
                    KnowledgeDocument.deleted_at.is_(None),
                ),
            )
        ).scalar_one_or_none()
        if document is None:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Knowledge document was not found.",
                {"knowledge_document_id": str(knowledge_document_id)},
            )
        await assert_resource_in_org(org_id, document.org_id, resource_label="Knowledge document")


async def create_certification(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: CertificationCreate,
) -> Certification:
    assert_can_manage_workforce(current_user)
    certification = Certification(org_id=current_user.org_id, **payload.model_dump())
    session.add(certification)
    await session.flush()
    return certification


async def update_certification(
    session: AsyncSession,
    certification: Certification,
    payload: CertificationUpdate,
) -> Certification:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(certification, key, value)
    return certification


async def soft_delete_certification(session: AsyncSession, certification: Certification) -> None:
    certification.deleted_at = datetime.now(timezone.utc)


async def get_employee_certification_or_404(
    session: AsyncSession,
    employee_certification_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> EmployeeCertification:
    assignment = (
        await session.execute(
            select(EmployeeCertification).where(
                EmployeeCertification.id == employee_certification_id,
                EmployeeCertification.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Employee certification was not found.",
            {"employee_certification_id": str(employee_certification_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and assignment.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Employee certification was not found.",
                {"employee_certification_id": str(employee_certification_id)},
            )
        return assignment

    assert_can_read_annotators(current_user)
    if current_user.role not in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        if assignment.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Employee certification was not found.",
                {"employee_certification_id": str(employee_certification_id)},
            )
    return assignment


async def create_employee_certification(
    session: AsyncSession,
    annotator: Annotator,
    payload: EmployeeCertificationCreate,
    current_user: CurrentUser,
) -> EmployeeCertification:
    certification = await get_certification_or_404(
        session,
        payload.certification_id,
        current_user,
        for_mutation=True,
    )
    await assert_resource_in_org(annotator.org_id, certification.org_id, resource_label="Certification")
    await assert_no_duplicate_employee_certification(session, annotator.id, payload.certification_id)

    assignment = EmployeeCertification(
        org_id=annotator.org_id,
        annotator_id=annotator.id,
        certification_id=certification.id,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        status=payload.status,
        evidence_url=payload.evidence_url,
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def update_employee_certification(
    session: AsyncSession,
    assignment: EmployeeCertification,
    payload: EmployeeCertificationUpdate,
) -> EmployeeCertification:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(assignment, key, value)
    return assignment


async def soft_delete_employee_certification(
    session: AsyncSession,
    assignment: EmployeeCertification,
) -> None:
    assignment.deleted_at = datetime.now(timezone.utc)


async def create_training_program(
    session: AsyncSession,
    current_user: CurrentUser,
    payload: TrainingProgramCreate,
) -> TrainingProgram:
    assert_can_manage_workforce(current_user)
    await validate_training_program_references(session, current_user.org_id, payload, current_user)
    program = TrainingProgram(org_id=current_user.org_id, **payload.model_dump())
    session.add(program)
    await session.flush()
    return program


async def update_training_program(
    session: AsyncSession,
    program: TrainingProgram,
    payload: TrainingProgramUpdate,
    current_user: CurrentUser,
) -> TrainingProgram:
    await validate_training_program_references(
        session,
        program.org_id,
        payload,
        current_user,
        existing=program,
    )
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(program, key, value)
    return program


async def soft_delete_training_program(session: AsyncSession, program: TrainingProgram) -> None:
    program.deleted_at = datetime.now(timezone.utc)


async def get_training_record_or_404(
    session: AsyncSession,
    training_record_id: UUID,
    current_user: CurrentUser,
    *,
    for_mutation: bool = False,
) -> TrainingRecord:
    record = (
        await session.execute(
            select(TrainingRecord).where(
                TrainingRecord.id == training_record_id,
                TrainingRecord.deleted_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if record is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            "Training record was not found.",
            {"training_record_id": str(training_record_id)},
        )

    if for_mutation:
        assert_can_manage_workforce(current_user)
        if current_user.role != AppRole.SUPER_ADMIN and record.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Training record was not found.",
                {"training_record_id": str(training_record_id)},
            )
        return record

    assert_can_read_annotators(current_user)
    if current_user.role not in {AppRole.SUPER_ADMIN, AppRole.BSG_LEADERSHIP}:
        if record.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Training record was not found.",
                {"training_record_id": str(training_record_id)},
            )
    return record


async def create_training_record(
    session: AsyncSession,
    annotator: Annotator,
    payload: TrainingRecordCreate,
    current_user: CurrentUser,
) -> TrainingRecord:
    program = await get_training_program_or_404(
        session,
        payload.training_program_id,
        current_user,
        for_mutation=True,
    )
    await assert_resource_in_org(annotator.org_id, program.org_id, resource_label="Training program")
    await assert_no_duplicate_training_record(session, annotator.id, payload.training_program_id)

    record = TrainingRecord(
        org_id=annotator.org_id,
        annotator_id=annotator.id,
        training_program_id=program.id,
        status=payload.status,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        score_pct=payload.score_pct,
    )
    session.add(record)
    await session.flush()
    return record


async def update_training_record(
    session: AsyncSession,
    record: TrainingRecord,
    payload: TrainingRecordUpdate,
) -> TrainingRecord:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    return record


async def soft_delete_training_record(session: AsyncSession, record: TrainingRecord) -> None:
    record.deleted_at = datetime.now(timezone.utc)


def is_certification_expired(assignment: EmployeeCertification, today: date) -> bool:
    if assignment.status == CertificationStatus.EXPIRED:
        return True
    if assignment.status == CertificationStatus.ACTIVE and assignment.expires_at is not None:
        return assignment.expires_at < today
    return False


def is_pending_certification_review(assignment: EmployeeCertification) -> bool:
    return assignment.status == CertificationStatus.PENDING_REVIEW


def is_mandatory_training_incomplete(
    record: TrainingRecord | None,
) -> bool:
    if record is None:
        return True
    return record.status not in {TrainingRecordStatus.COMPLETED}


def is_expired_or_failed_training(record: TrainingRecord) -> bool:
    return record.status in {TrainingRecordStatus.FAILED, TrainingRecordStatus.EXPIRED}


async def build_project_training_gaps(
    session: AsyncSession,
    project: Project,
    current_user: CurrentUser,
    *,
    today: date | None = None,
) -> TrainingGapSummaryRead:
    assert_can_read_annotators(current_user)
    reference_date = today or date.today()

    teams = (
        await session.execute(
            select(Team).where(Team.project_id == project.id, Team.deleted_at.is_(None)),
        )
    ).scalars().all()
    team_by_id = {team.id: team for team in teams}
    team_ids = list(team_by_id.keys())

    annotators: list[Annotator] = []
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

    annotator_ids = [annotator.id for annotator in annotators]

    employee_certifications: list[EmployeeCertification] = []
    training_records: list[TrainingRecord] = []
    if annotator_ids:
        employee_certifications = (
            await session.execute(
                select(EmployeeCertification).where(
                    EmployeeCertification.annotator_id.in_(annotator_ids),
                    EmployeeCertification.deleted_at.is_(None),
                ),
            )
        ).scalars().all()
        training_records = (
            await session.execute(
                select(TrainingRecord).where(
                    TrainingRecord.annotator_id.in_(annotator_ids),
                    TrainingRecord.deleted_at.is_(None),
                ),
            )
        ).scalars().all()

    mandatory_programs = (
        await session.execute(
            select(TrainingProgram).where(
                TrainingProgram.org_id == project.org_id,
                TrainingProgram.is_mandatory.is_(True),
                TrainingProgram.deleted_at.is_(None),
            ),
        )
    ).scalars().all()

    certification_ids = {item.certification_id for item in employee_certifications}
    program_ids = {item.training_program_id for item in training_records}
    program_ids.update(program.id for program in mandatory_programs)
    skill_ids = {program.skill_id for program in mandatory_programs if program.skill_id}

    certifications_by_id: dict[UUID, Certification] = {}
    if certification_ids:
        certifications = (
            await session.execute(
                select(Certification).where(
                    Certification.id.in_(certification_ids),
                    Certification.deleted_at.is_(None),
                ),
            )
        ).scalars().all()
        certifications_by_id = {item.id: item for item in certifications}

    programs_by_id: dict[UUID, TrainingProgram] = {program.id: program for program in mandatory_programs}
    if program_ids:
        programs = (
            await session.execute(
                select(TrainingProgram).where(
                    TrainingProgram.id.in_(program_ids),
                    TrainingProgram.deleted_at.is_(None),
                ),
            )
        ).scalars().all()
        programs_by_id.update({item.id: item for item in programs})

    skills_by_id: dict[UUID, Skill] = {}
    if skill_ids:
        skills = (
            await session.execute(
                select(Skill).where(Skill.id.in_(skill_ids), Skill.deleted_at.is_(None)),
            )
        ).scalars().all()
        skills_by_id = {item.id: item for item in skills}

    records_by_annotator_program: dict[tuple[UUID, UUID], TrainingRecord] = {}
    for record in training_records:
        records_by_annotator_program[(record.annotator_id, record.training_program_id)] = record

    row_counts: dict[tuple, int] = defaultdict(int)
    mandatory_incomplete = 0
    expired_or_failed = 0
    expired_certifications = 0
    pending_reviews = 0

    for annotator in annotators:
        team = team_by_id.get(annotator.team_id)

        for program in mandatory_programs:
            record = records_by_annotator_program.get((annotator.id, program.id))
            if is_mandatory_training_incomplete(record):
                mandatory_incomplete += 1
                skill = skills_by_id.get(program.skill_id) if program.skill_id else None
                key = (
                    team.id if team else None,
                    team.name if team else None,
                    program.skill_id,
                    skill.name if skill else None,
                    program.id,
                    program.name,
                    None,
                    None,
                    TrainingGapType.MANDATORY_TRAINING_INCOMPLETE,
                )
                row_counts[key] += 1

        for record in training_records:
            if record.annotator_id != annotator.id:
                continue
            if not is_expired_or_failed_training(record):
                continue
            program = programs_by_id.get(record.training_program_id)
            if program is None or program.is_mandatory:
                continue
            expired_or_failed += 1
            skill = skills_by_id.get(program.skill_id) if program.skill_id else None
            key = (
                team.id if team else None,
                team.name if team else None,
                program.skill_id,
                skill.name if skill else None,
                program.id,
                program.name,
                None,
                None,
                TrainingGapType.EXPIRED_OR_FAILED_TRAINING,
            )
            row_counts[key] += 1

        for assignment in employee_certifications:
            if assignment.annotator_id != annotator.id:
                continue
            certification = certifications_by_id.get(assignment.certification_id)
            if certification is None:
                continue

            if is_certification_expired(assignment, reference_date):
                expired_certifications += 1
                key = (
                    team.id if team else None,
                    team.name if team else None,
                    None,
                    None,
                    None,
                    None,
                    certification.id,
                    certification.name,
                    TrainingGapType.EXPIRED_CERTIFICATION,
                )
                row_counts[key] += 1

            if is_pending_certification_review(assignment):
                pending_reviews += 1
                key = (
                    team.id if team else None,
                    team.name if team else None,
                    None,
                    None,
                    None,
                    None,
                    certification.id,
                    certification.name,
                    TrainingGapType.PENDING_CERTIFICATION_REVIEW,
                )
                row_counts[key] += 1

    rows = [
        TrainingGapRow(
            team_id=team_id,
            team_name=team_name,
            skill_id=skill_id,
            skill_name=skill_name,
            training_program_id=training_program_id,
            training_program_name=training_program_name,
            certification_id=certification_id,
            certification_name=certification_name,
            gap_type=gap_type,
            affected_count=count,
        )
        for (
            team_id,
            team_name,
            skill_id,
            skill_name,
            training_program_id,
            training_program_name,
            certification_id,
            certification_name,
            gap_type,
        ), count in sorted(row_counts.items(), key=lambda item: (-item[1], str(item[0][8])))
    ]

    total = mandatory_incomplete + expired_or_failed + expired_certifications + pending_reviews

    return TrainingGapSummaryRead(
        project_id=project.id,
        total_training_gaps=total,
        mandatory_training_incomplete=mandatory_incomplete,
        expired_or_failed_training=expired_or_failed,
        expired_certifications=expired_certifications,
        pending_certification_reviews=pending_reviews,
        rows=rows,
    )
