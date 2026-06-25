from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    Annotator,
    AppRole,
    Certification,
    CertificationStatus,
    DeliverySite,
    EmployeeCertification,
    Project,
    Team,
    TrainingGapType,
    TrainingProgram,
    TrainingRecord,
    TrainingRecordStatus,
)
from app.schemas.domain import (
    CertificationCreate,
    EmployeeCertificationCreate,
    TrainingProgramCreate,
    TrainingRecordCreate,
)
from app.services.workforce_training import (
    assert_no_duplicate_employee_certification,
    assert_no_duplicate_training_record,
    build_project_training_gaps,
    create_certification,
    create_employee_certification,
    create_training_record,
    get_certification_or_404,
    is_certification_expired,
    is_mandatory_training_incomplete,
)
from tests.conftest import ORG_A, client_a, override_user


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="Test Project",
        vertical="medical",
        status="active",
        start_date="2026-01-01",
        target_end_date="2026-12-31",
    )


def _team(org_id, project_id) -> Team:
    return Team(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name="Radiology Pod A",
        site=DeliverySite.INDIA,
        domain="radiology",
        is_active=True,
    )


def _annotator(org_id, team_id) -> Annotator:
    return Annotator(
        id=uuid4(),
        org_id=org_id,
        team_id=team_id,
        full_name="Priya Sharma",
        site=DeliverySite.INDIA,
        is_sme_certified=False,
        is_active=True,
    )


def _certification(org_id, name="Clinical QA") -> Certification:
    return Certification(
        id=uuid4(),
        org_id=org_id,
        name=name,
        validity_months=24,
        is_required_for_sme=True,
    )


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeResult:
    def __init__(self, value=None, items=None):
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    def __init__(self, **kwargs):
        self.certification = kwargs.get("certification")
        self.annotator = kwargs.get("annotator")
        self.program = kwargs.get("program")
        self.existing_id = kwargs.get("existing_id")
        self.teams = kwargs.get("teams", [])
        self.annotators = kwargs.get("annotators", [])
        self.employee_certifications = kwargs.get("employee_certifications", [])
        self.training_records = kwargs.get("training_records", [])
        self.mandatory_programs = kwargs.get("mandatory_programs", [])
        self.certifications = kwargs.get("certifications", [])
        self.programs = kwargs.get("programs", [])
        self.skills = kwargs.get("skills", [])
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM certifications" in compiled:
            if "certifications.id IN" in compiled:
                return FakeResult(None, self.certifications)
            if "WHERE certifications.id" in compiled and "certifications.deleted_at" in compiled:
                return FakeResult(self.certification)
            return FakeResult(None, self.certifications)
        if "FROM training_programs" in compiled:
            if "training_programs.id IN" in compiled:
                return FakeResult(None, self.programs)
            if "WHERE training_programs.id" in compiled and "training_programs.deleted_at" in compiled:
                return FakeResult(self.program)
            if "training_programs.is_mandatory" in compiled:
                return FakeResult(None, self.mandatory_programs)
            return FakeResult(None, self.mandatory_programs)
        if "FROM employee_certifications" in compiled:
            if "employee_certifications.evidence_url" in compiled:
                return FakeResult(None, self.employee_certifications)
            if "employee_certifications.id" in compiled:
                return FakeResult(self.existing_id)
            return FakeResult(None, self.employee_certifications)
        if "FROM training_records" in compiled:
            if "training_records.score_pct" in compiled:
                return FakeResult(None, self.training_records)
            if "training_records.id" in compiled:
                return FakeResult(self.existing_id)
            return FakeResult(None, self.training_records)
        if "FROM annotators" in compiled:
            if "annotators.id IN" in compiled or "annotators.full_name" in compiled:
                return FakeResult(None, self.annotators)
            return FakeResult(self.annotator)
        if "FROM teams" in compiled:
            return FakeResult(None, self.teams)
        if "FROM skills" in compiled:
            return FakeResult(None, self.skills)
        if "FROM knowledge_documents" in compiled:
            return FakeResult(None)
        return FakeResult(None)


def test_is_certification_expired_detects_status_and_date() -> None:
    expired = EmployeeCertification(
        id=uuid4(),
        org_id=uuid4(),
        annotator_id=uuid4(),
        certification_id=uuid4(),
        status=CertificationStatus.EXPIRED,
    )
    active_past = EmployeeCertification(
        id=uuid4(),
        org_id=uuid4(),
        annotator_id=uuid4(),
        certification_id=uuid4(),
        status=CertificationStatus.ACTIVE,
        expires_at=date(2020, 1, 1),
    )
    assert is_certification_expired(expired, date(2026, 6, 1)) is True
    assert is_certification_expired(active_past, date(2026, 6, 1)) is True


def test_is_mandatory_training_incomplete() -> None:
    assert is_mandatory_training_incomplete(None) is True
    assert (
        is_mandatory_training_incomplete(
            TrainingRecord(
                id=uuid4(),
                org_id=uuid4(),
                annotator_id=uuid4(),
                training_program_id=uuid4(),
                status=TrainingRecordStatus.IN_PROGRESS,
            ),
        )
        is True
    )
    assert (
        is_mandatory_training_incomplete(
            TrainingRecord(
                id=uuid4(),
                org_id=uuid4(),
                annotator_id=uuid4(),
                training_program_id=uuid4(),
                status=TrainingRecordStatus.COMPLETED,
            ),
        )
        is False
    )


def test_training_record_schema_rejects_invalid_score() -> None:
    with pytest.raises(ValidationError):
        TrainingRecordCreate(
            training_program_id=uuid4(),
            score_pct=Decimal("120"),
        )


@pytest.mark.asyncio
async def test_create_certification_sets_org_from_user() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession()

    certification = await create_certification(
        session,
        user,
        CertificationCreate(name="Radiology SME", validity_months=12),
    )

    assert certification.org_id == org_a
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_get_certification_or_404_cross_org_returns_404() -> None:
    org_a = uuid4()
    org_b = uuid4()
    certification = _certification(org_a)
    session = FakeSession(certification=certification)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_certification_or_404(session, certification.id, user, for_mutation=True)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_employee_certification_rejects_cross_org() -> None:
    org_a = uuid4()
    org_b = uuid4()
    certification = _certification(org_b)
    annotator = _annotator(org_a, uuid4())
    session = FakeSession(certification=certification, annotator=annotator)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_employee_certification(
            session,
            annotator,
            EmployeeCertificationCreate(certification_id=certification.id),
            user,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_employee_certification_raises_conflict() -> None:
    org_a = uuid4()
    certification = _certification(org_a)
    annotator = _annotator(org_a, uuid4())
    session = FakeSession(certification=certification, annotator=annotator, existing_id=uuid4())
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_employee_certification(
            session,
            annotator,
            EmployeeCertificationCreate(certification_id=certification.id),
            user,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_training_record_raises_conflict() -> None:
    org_a = uuid4()
    program = TrainingProgram(
        id=uuid4(),
        org_id=org_a,
        name="Safety 101",
        is_mandatory=True,
    )
    annotator = _annotator(org_a, uuid4())
    session = FakeSession(program=program, annotator=annotator, existing_id=uuid4())
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_training_record(
            session,
            annotator,
            TrainingRecordCreate(training_program_id=program.id),
            user,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_build_project_training_gaps_summary() -> None:
    org_a = uuid4()
    project = _project(org_a)
    team = _team(org_a, project.id)
    annotator = _annotator(org_a, team.id)
    certification = _certification(org_a)
    mandatory_program = TrainingProgram(
        id=uuid4(),
        org_id=org_a,
        name="Mandatory Safety",
        is_mandatory=True,
    )
    optional_program = TrainingProgram(
        id=uuid4(),
        org_id=org_a,
        name="Optional Refresher",
        is_mandatory=False,
    )
    employee_certifications = [
        EmployeeCertification(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotator.id,
            certification_id=certification.id,
            status=CertificationStatus.EXPIRED,
        ),
        EmployeeCertification(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotator.id,
            certification_id=uuid4(),
            status=CertificationStatus.PENDING_REVIEW,
        ),
    ]
    employee_certifications[1].certification_id = certification.id
    training_records = [
        TrainingRecord(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotator.id,
            training_program_id=optional_program.id,
            status=TrainingRecordStatus.FAILED,
        ),
    ]
    session = FakeSession(
        teams=[team],
        annotators=[annotator],
        employee_certifications=employee_certifications,
        training_records=training_records,
        mandatory_programs=[mandatory_program],
        certifications=[certification],
        programs=[mandatory_program, optional_program],
    )
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    summary = await build_project_training_gaps(session, project, user, today=date(2026, 6, 1))

    assert summary.project_id == project.id
    assert summary.mandatory_training_incomplete == 1
    assert summary.expired_or_failed_training == 1
    assert summary.expired_certifications == 1
    assert summary.pending_certification_reviews == 1
    assert summary.total_training_gaps == 4
    assert len(summary.rows) >= 3
    gap_types = {row.gap_type for row in summary.rows}
    assert TrainingGapType.MANDATORY_TRAINING_INCOMPLETE in gap_types
    assert TrainingGapType.EXPIRED_CERTIFICATION in gap_types
    assert all(row.affected_count >= 1 for row in summary.rows)
    assert all("Priya" not in str(row.model_dump()) for row in summary.rows)


@pytest.mark.asyncio
async def test_assert_no_duplicate_helpers() -> None:
    session = FakeSession(existing_id=uuid4())

    with pytest.raises(ApiError) as exc:
        await assert_no_duplicate_employee_certification(session, uuid4(), uuid4())
    assert exc.value.status_code == 409

    with pytest.raises(ApiError) as exc:
        await assert_no_duplicate_training_record(session, uuid4(), uuid4())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_client_cannot_list_certifications_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        "/api/v1/workforce/certifications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_list_annotator_certifications_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/annotators/{uuid4()}/certifications",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_create_certification_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        "/api/v1/workforce/certifications",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_list_training_programs_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        "/api/v1/workforce/training-programs",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_list_training_records_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/annotators/{uuid4()}/training-records",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_read_training_gaps_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/training-gaps",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_create_certification_http(api_client: AsyncClient) -> None:
    override_user(
        CurrentUser(
            id=uuid4(),
            org_id=ORG_A,
            email="lead@example.com",
            role=AppRole.BSG_LEADERSHIP,
            is_active=True,
        )
    )
    response = await api_client.post(
        "/api/v1/workforce/certifications",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_create_training_record_http(api_client: AsyncClient) -> None:
    override_user(
        CurrentUser(
            id=uuid4(),
            org_id=ORG_A,
            email="lead@example.com",
            role=AppRole.BSG_LEADERSHIP,
            is_active=True,
        )
    )
    response = await api_client.post(
        f"/api/v1/annotators/{uuid4()}/training-records",
        json={"training_program_id": str(uuid4())},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
