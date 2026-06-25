from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import Annotator, AppRole, DeliverySite, Project, Team
from app.schemas.domain import AnnotatorCreate, TeamCreate
from app.services.scoping import get_visible_project
from app.services.workforce import (
    annotator_visible_to_user,
    assert_can_manage_workforce,
    assert_can_read_annotators,
    can_manage_workforce,
    can_read_annotators,
    create_annotator,
    create_team,
    get_annotator_or_404,
    get_team_or_404,
    soft_delete_annotator,
    soft_delete_team,
    team_visible_to_user,
    update_team,
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
        is_sme_certified=True,
        is_active=True,
    )


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(
        self,
        *,
        team: Team | None = None,
        annotator: Annotator | None = None,
        project: Project | None = None,
        has_assignment: bool = False,
    ):
        self.team = team
        self.annotator = annotator
        self.project = project
        self.has_assignment = has_assignment
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "project_assignments" in compiled:
            return FakeResult(uuid4() if self.has_assignment else None)
        if "FROM teams" in compiled or "teams." in compiled:
            return FakeResult(self.team)
        if "FROM annotators" in compiled or "annotators." in compiled:
            return FakeResult(self.annotator)
        return FakeResult(self.project)


def test_can_manage_workforce_matrix() -> None:
    assert can_manage_workforce(_user(AppRole.DELIVERY_MANAGER)) is True
    assert can_manage_workforce(_user(AppRole.SUPER_ADMIN)) is True
    assert can_manage_workforce(_user(AppRole.BSG_LEADERSHIP)) is False
    assert can_manage_workforce(_user(AppRole.CLIENT)) is False


def test_can_read_annotators_matrix() -> None:
    assert can_read_annotators(_user(AppRole.DELIVERY_MANAGER)) is True
    assert can_read_annotators(_user(AppRole.BSG_LEADERSHIP)) is True
    assert can_read_annotators(_user(AppRole.SUPER_ADMIN)) is True
    assert can_read_annotators(_user(AppRole.CLIENT)) is False


def test_assert_can_manage_workforce_raises_for_client() -> None:
    with pytest.raises(ApiError) as exc:
        assert_can_manage_workforce(_user(AppRole.CLIENT))
    assert exc.value.status_code == 403


def test_assert_can_read_annotators_raises_for_client() -> None:
    with pytest.raises(ApiError) as exc:
        assert_can_read_annotators(_user(AppRole.CLIENT))
    assert exc.value.status_code == 403


def test_team_visible_to_user_matrix() -> None:
    org_a = uuid4()
    org_b = uuid4()
    team = _team(org_a, uuid4())

    assert team_visible_to_user(team, _user(AppRole.SUPER_ADMIN, org_b)) is True
    assert team_visible_to_user(team, _user(AppRole.BSG_LEADERSHIP, org_b)) is True
    assert team_visible_to_user(team, _user(AppRole.DELIVERY_MANAGER, org_a)) is True
    assert team_visible_to_user(team, _user(AppRole.DELIVERY_MANAGER, org_b)) is False
    assert team_visible_to_user(team, _user(AppRole.CLIENT, org_a)) is True
    assert team_visible_to_user(team, _user(AppRole.CLIENT, org_b)) is False


def test_annotator_visible_to_user_matrix() -> None:
    org_a = uuid4()
    org_b = uuid4()
    annotator = _annotator(org_a, uuid4())

    assert annotator_visible_to_user(annotator, _user(AppRole.SUPER_ADMIN, org_b)) is True
    assert annotator_visible_to_user(annotator, _user(AppRole.BSG_LEADERSHIP, org_b)) is True
    assert annotator_visible_to_user(annotator, _user(AppRole.DELIVERY_MANAGER, org_a)) is True
    assert annotator_visible_to_user(annotator, _user(AppRole.DELIVERY_MANAGER, org_b)) is False
    assert annotator_visible_to_user(annotator, _user(AppRole.CLIENT, org_a)) is False


@pytest.mark.asyncio
async def test_get_team_or_404_returns_team_for_org_delivery_manager() -> None:
    org_a = uuid4()
    project_id = uuid4()
    team = _team(org_a, project_id)
    session = FakeSession(team=team)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    visible = await get_team_or_404(session, team.id, user)
    assert visible.id == team.id


@pytest.mark.asyncio
async def test_get_team_or_404_returns_404_for_cross_org_delivery_manager() -> None:
    org_a = uuid4()
    org_b = uuid4()
    team = _team(org_a, uuid4())
    session = FakeSession(team=team)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_team_or_404(session, team.id, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_team_or_404_mutation_returns_404_for_cross_org_delivery_manager() -> None:
    org_a = uuid4()
    org_b = uuid4()
    team = _team(org_a, uuid4())
    session = FakeSession(team=team)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_team_or_404(session, team.id, user, for_mutation=True)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_annotator_or_404_returns_404_for_cross_org_delivery_manager() -> None:
    org_a = uuid4()
    org_b = uuid4()
    annotator = _annotator(org_a, uuid4())
    session = FakeSession(annotator=annotator)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_annotator_or_404(session, annotator.id, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_visible_project_returns_403_for_cross_org_team_create() -> None:
    org_a = uuid4()
    org_b = uuid4()
    project = _project(org_a)
    session = FakeSession(project=project)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_visible_project(session, project.id, user)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_team_sets_org_id_from_project() -> None:
    org_a = uuid4()
    project = _project(org_a)
    session = FakeSession()

    team = await create_team(
        session,
        project,
        TeamCreate(name="Finance Docs", site=DeliverySite.KOSOVO, domain="finance"),
    )

    assert team.project_id == project.id
    assert team.org_id == project.org_id
    assert team.name == "Finance Docs"
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_create_annotator_sets_org_id_from_team() -> None:
    org_a = uuid4()
    project_id = uuid4()
    team = _team(org_a, project_id)
    session = FakeSession(team=team)

    annotator = await create_annotator(
        session,
        team,
        AnnotatorCreate(full_name="A. Hoxha", site=DeliverySite.KOSOVO),
    )

    assert annotator.team_id == team.id
    assert annotator.org_id == team.org_id
    assert annotator.full_name == "A. Hoxha"
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_soft_delete_team_marks_deleted_at() -> None:
    team = _team(uuid4(), uuid4())
    session = FakeSession(team=team)

    await soft_delete_team(session, team)

    assert team.deleted_at is not None
    assert team.is_active is False


@pytest.mark.asyncio
async def test_soft_delete_annotator_marks_deleted_at() -> None:
    annotator = _annotator(uuid4(), uuid4())
    session = FakeSession(annotator=annotator)

    await soft_delete_annotator(session, annotator)

    assert annotator.deleted_at is not None
    assert annotator.is_active is False


@pytest.mark.asyncio
async def test_update_team_changes_allowed_fields() -> None:
    from app.schemas.domain import TeamUpdate

    team = _team(uuid4(), uuid4())
    session = FakeSession(team=team)

    updated = await update_team(
        session,
        team,
        TeamUpdate(name="Updated Pod", domain="pathology", is_active=False),
    )

    assert updated.name == "Updated Pod"
    assert updated.domain == "pathology"
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_leadership_can_read_team_in_other_org() -> None:
    org_a = uuid4()
    team = _team(org_a, uuid4())
    session = FakeSession(team=team)
    user = _user(AppRole.BSG_LEADERSHIP, uuid4())

    visible = await get_team_or_404(session, team.id, user)
    assert visible.id == team.id


@pytest.mark.asyncio
async def test_client_cannot_mutate_team_via_get_team_or_404() -> None:
    org_a = uuid4()
    team = _team(org_a, uuid4())
    session = FakeSession(team=team)
    user = _user(AppRole.CLIENT, org_a)

    with pytest.raises(ApiError) as exc:
        await get_team_or_404(session, team.id, user, for_mutation=True)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delivery_manager_cannot_create_annotator_on_cross_org_team() -> None:
    org_a = uuid4()
    org_b = uuid4()
    team = _team(org_a, uuid4())
    session = FakeSession(team=team)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_team_or_404(session, team.id, user, for_mutation=True)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_client_cannot_list_annotators_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/teams/{uuid4()}/annotators",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_create_team_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/teams",
        json={"name": "Blocked", "site": "india", "domain": "nlp"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_update_team_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.patch(
        f"/api/v1/teams/{uuid4()}",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_delete_team_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.delete(
        f"/api/v1/teams/{uuid4()}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_client_cannot_create_annotator_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.post(
        f"/api/v1/teams/{uuid4()}/annotators",
        json={"full_name": "Blocked", "site": "india"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_leadership_cannot_update_team_http(api_client: AsyncClient) -> None:
    override_user(
        CurrentUser(
            id=uuid4(),
            org_id=ORG_A,
            email="lead@example.com",
            role=AppRole.BSG_LEADERSHIP,
            is_active=True,
        )
    )
    response = await api_client.patch(
        f"/api/v1/teams/{uuid4()}",
        json={"name": "Blocked"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_delivery_manager_create_team_cross_org_project_http(
    api_client: AsyncClient,
    delivery_manager,
) -> None:
    override_user(delivery_manager)
    response = await api_client.post(
        f"/api/v1/projects/{uuid4()}/teams",
        json={"name": "Finance Docs", "site": "india", "domain": "finance"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code in {403, 404, 500}
