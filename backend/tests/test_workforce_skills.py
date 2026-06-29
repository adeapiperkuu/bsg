from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

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
    SkillRequirementPriority,
    Team,
)
from app.schemas.domain import AnnotatorSkillCreate, ProjectSkillRequirementCreate, SkillCreate
from app.services.workforce_skills import (
    assert_no_duplicate_annotator_skill,
    assert_no_duplicate_project_requirement,
    build_project_skill_matrix,
    compute_coverage_status,
    create_annotator_skill,
    create_project_skill_requirement,
    create_skill,
    get_skill_or_404,
    meets_proficiency,
)
from tests.conftest import ORG_A, client_a, delivery_manager, override_user


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


def _team(org_id, project_id, *, site=DeliverySite.INDIA) -> Team:
    return Team(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name="Radiology Pod A",
        site=site,
        domain="radiology",
        is_active=True,
    )


def _annotator(org_id, team_id, *, site=DeliverySite.INDIA, sme=False) -> Annotator:
    return Annotator(
        id=uuid4(),
        org_id=org_id,
        team_id=team_id,
        full_name="Priya Sharma",
        site=site,
        is_sme_certified=sme,
        is_active=True,
    )


def _skill(org_id, name="Radiology QA") -> Skill:
    return Skill(
        id=uuid4(),
        org_id=org_id,
        name=name,
        category="Life Sciences",
        domain="radiology",
        is_critical=True,
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
        self.skill = kwargs.get("skill")
        self.annotator = kwargs.get("annotator")
        self.project = kwargs.get("project")
        self.existing_id = kwargs.get("existing_id")
        self.requirements = kwargs.get("requirements", [])
        self.skills = kwargs.get("skills", [])
        self.teams = kwargs.get("teams", [])
        self.annotators = kwargs.get("annotators", [])
        self.assignments = kwargs.get("assignments", [])
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM skills" in compiled:
            if "skills.id IN" in compiled:
                return FakeResult(None, self.skills)
            if "WHERE skills.id" in compiled and "skills.deleted_at" in compiled:
                return FakeResult(self.skill)
            return FakeResult(None, self.skills if self.skills else ([self.skill] if self.skill else []))
        if "FROM annotators" in compiled:
            if "annotators.id IN" in compiled or "annotators.full_name" in compiled:
                return FakeResult(None, self.annotators)
            return FakeResult(self.annotator)
        if "FROM teams" in compiled:
            return FakeResult(None, self.teams)
        if "FROM project_skill_requirements" in compiled:
            if "project_skill_requirements.required_headcount" in compiled:
                return FakeResult(None, self.requirements)
            if "project_skill_requirements.id" in compiled:
                return FakeResult(self.existing_id)
            return FakeResult(None, self.requirements)
        if "FROM annotator_skills" in compiled:
            if "annotator_skills.proficiency_level" in compiled:
                return FakeResult(None, self.assignments)
            if "annotator_skills.id" in compiled:
                return FakeResult(self.existing_id)
            return FakeResult(None, self.assignments)
        return FakeResult(self.project)


def test_meets_proficiency_matrix() -> None:
    assert meets_proficiency(ProficiencyLevel.EXPERT, ProficiencyLevel.ADVANCED) is True
    assert meets_proficiency(ProficiencyLevel.ADVANCED, ProficiencyLevel.ADVANCED) is True
    assert meets_proficiency(ProficiencyLevel.INTERMEDIATE, ProficiencyLevel.ADVANCED) is False


def test_compute_coverage_status_matrix() -> None:
    assert compute_coverage_status(5, 5, 2, 2) == SkillCoverageStatus.HIGH
    assert compute_coverage_status(3, 5, 1, 2) == SkillCoverageStatus.MEDIUM
    assert compute_coverage_status(0, 5, 0, 2) == SkillCoverageStatus.LOW


def test_skill_requirement_schema_rejects_invalid_priority() -> None:
    with pytest.raises(ValidationError):
        ProjectSkillRequirementCreate(
            skill_id=uuid4(),
            required_proficiency_level=ProficiencyLevel.ADVANCED,
            priority="urgent",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_create_skill_sets_org_from_user() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    session = FakeSession()

    skill = await create_skill(session, user, SkillCreate(name="Clinical NLP", domain="nlp"))

    assert skill.org_id == org_a
    assert skill.name == "Clinical NLP"
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_get_skill_or_404_cross_org_returns_404() -> None:
    org_a = uuid4()
    org_b = uuid4()
    skill = _skill(org_a)
    session = FakeSession(skill=skill)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_skill_or_404(session, skill.id, user, for_mutation=True)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_annotator_skill_validates_same_org() -> None:
    org_a = uuid4()
    org_b = uuid4()
    skill = _skill(org_b)
    annotator = _annotator(org_a, uuid4())
    session = FakeSession(skill=skill, annotator=annotator)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_annotator_skill(
            session,
            annotator,
            AnnotatorSkillCreate(skill_id=skill.id, proficiency_level=ProficiencyLevel.ADVANCED),
            user,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_annotator_skill_raises_conflict() -> None:
    org_a = uuid4()
    skill = _skill(org_a)
    annotator = _annotator(org_a, uuid4())
    session = FakeSession(skill=skill, annotator=annotator, existing_id=uuid4())
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_annotator_skill(
            session,
            annotator,
            AnnotatorSkillCreate(skill_id=skill.id, proficiency_level=ProficiencyLevel.ADVANCED),
            user,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_project_skill_requirement_raises_conflict() -> None:
    org_a = uuid4()
    project = _project(org_a)
    skill = _skill(org_a)
    session = FakeSession(skill=skill, project=project, existing_id=uuid4())
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_project_skill_requirement(
            session,
            project,
            ProjectSkillRequirementCreate(
                skill_id=skill.id,
                required_proficiency_level=ProficiencyLevel.ADVANCED,
                required_headcount=3,
                required_sme_count=1,
            ),
            user,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_project_skill_requirement_rejects_cross_org_skill() -> None:
    org_a = uuid4()
    org_b = uuid4()
    project = _project(org_a)
    skill = _skill(org_b)
    session = FakeSession(skill=skill, project=project)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    with pytest.raises(ApiError) as exc:
        await create_project_skill_requirement(
            session,
            project,
            ProjectSkillRequirementCreate(
                skill_id=skill.id,
                required_proficiency_level=ProficiencyLevel.ADVANCED,
            ),
            user,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_build_project_skill_matrix_counts_coverage() -> None:
    org_a = uuid4()
    project = _project(org_a)
    skill = _skill(org_a)
    team_india = _team(org_a, project.id, site=DeliverySite.INDIA)
    team_kosovo = _team(org_a, project.id, site=DeliverySite.KOSOVO)
    annotator_india = _annotator(org_a, team_india.id, site=DeliverySite.INDIA, sme=True)
    annotator_kosovo = _annotator(org_a, team_kosovo.id, site=DeliverySite.KOSOVO, sme=False)
    requirement = ProjectSkillRequirement(
        id=uuid4(),
        org_id=org_a,
        project_id=project.id,
        skill_id=skill.id,
        required_proficiency_level=ProficiencyLevel.ADVANCED,
        required_headcount=2,
        required_sme_count=1,
        priority=SkillRequirementPriority.HIGH,
    )
    assignments = [
        AnnotatorSkill(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotator_india.id,
            skill_id=skill.id,
            proficiency_level=ProficiencyLevel.EXPERT,
        ),
        AnnotatorSkill(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotator_kosovo.id,
            skill_id=skill.id,
            proficiency_level=ProficiencyLevel.INTERMEDIATE,
        ),
    ]
    session = FakeSession(
        requirements=[requirement],
        skills=[skill],
        teams=[team_india, team_kosovo],
        annotators=[annotator_india, annotator_kosovo],
        assignments=assignments,
    )
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    matrix = await build_project_skill_matrix(session, project, user)

    assert matrix.project_id == project.id
    assert len(matrix.rows) == 1
    row = matrix.rows[0]
    assert row.skill_name == skill.name
    assert row.available_headcount == 1
    assert row.available_sme_count == 1
    assert row.coverage_status == SkillCoverageStatus.MEDIUM
    india = next(site for site in row.by_site if site.site == DeliverySite.INDIA)
    kosovo = next(site for site in row.by_site if site.site == DeliverySite.KOSOVO)
    assert india.available_headcount == 1
    assert india.coverage_status == SkillCoverageStatus.MEDIUM
    assert kosovo.available_headcount == 0
    assert kosovo.coverage_status == SkillCoverageStatus.LOW


@pytest.mark.asyncio
async def test_build_project_skill_matrix_high_coverage() -> None:
    org_a = uuid4()
    project = _project(org_a)
    skill = _skill(org_a)
    team = _team(org_a, project.id)
    annotators = [
        _annotator(org_a, team.id, sme=True),
        _annotator(org_a, team.id, sme=False),
    ]
    requirement = ProjectSkillRequirement(
        id=uuid4(),
        org_id=org_a,
        project_id=project.id,
        skill_id=skill.id,
        required_proficiency_level=ProficiencyLevel.ADVANCED,
        required_headcount=2,
        required_sme_count=1,
        priority=SkillRequirementPriority.MEDIUM,
    )
    assignments = [
        AnnotatorSkill(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotators[0].id,
            skill_id=skill.id,
            proficiency_level=ProficiencyLevel.EXPERT,
        ),
        AnnotatorSkill(
            id=uuid4(),
            org_id=org_a,
            annotator_id=annotators[1].id,
            skill_id=skill.id,
            proficiency_level=ProficiencyLevel.ADVANCED,
        ),
    ]
    session = FakeSession(
        requirements=[requirement],
        skills=[skill],
        teams=[team],
        annotators=annotators,
        assignments=assignments,
    )
    user = _user(AppRole.BSG_LEADERSHIP, uuid4())

    matrix = await build_project_skill_matrix(session, project, user)

    assert matrix.rows[0].coverage_status == SkillCoverageStatus.HIGH
    assert matrix.rows[0].available_headcount == 2
    assert matrix.rows[0].available_sme_count == 1


@pytest.mark.asyncio
async def test_assert_no_duplicate_helpers() -> None:
    session = FakeSession(existing_id=uuid4())

    with pytest.raises(ApiError) as exc:
        await assert_no_duplicate_annotator_skill(session, uuid4(), uuid4())
    assert exc.value.status_code == 409

    with pytest.raises(ApiError) as exc:
        await assert_no_duplicate_project_requirement(session, uuid4(), uuid4())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_client_cannot_list_annotator_skills_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/annotators/{uuid4()}/skills",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_list_skills_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        "/api/v1/workforce/skills",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_create_skill_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        "/api/v1/workforce/skills",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_update_skill_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.patch(
        f"/api/v1/workforce/skills/{uuid4()}",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_delete_skill_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.delete(
        f"/api/v1/workforce/skills/{uuid4()}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_create_annotator_skill_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/annotators/{uuid4()}/skills",
        json={"skill_id": str(uuid4()), "proficiency_level": "advanced"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_list_skill_requirements_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/skill-requirements",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_create_skill_requirement_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/skill-requirements",
        json={
            "skill_id": str(uuid4()),
            "required_proficiency_level": "advanced",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_read_skill_matrix_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/skill-matrix",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_create_skill_http(api_client: AsyncClient) -> None:
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
        "/api/v1/workforce/skills",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_create_annotator_skill_http(api_client: AsyncClient) -> None:
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
        f"/api/v1/annotators/{uuid4()}/skills",
        json={"skill_id": str(uuid4()), "proficiency_level": "advanced"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leadership_cannot_create_skill_requirement_http(api_client: AsyncClient) -> None:
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
        f"/api/v1/projects/{uuid4()}/skill-requirements",
        json={
            "skill_id": str(uuid4()),
            "required_proficiency_level": "advanced",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delivery_manager_cross_org_annotator_skill_http(
    api_client: AsyncClient,
    delivery_manager,
) -> None:
    override_user(delivery_manager)
    response = await api_client.post(
        f"/api/v1/annotators/{uuid4()}/skills",
        json={"skill_id": str(uuid4()), "proficiency_level": "advanced"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code in {403, 404, 500}
