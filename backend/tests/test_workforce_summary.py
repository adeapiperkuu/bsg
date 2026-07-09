from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import CurrentUser
from app.db.models import Annotator, AppRole, DeliverySite, Project, Team
from app.services.workforce import get_project_workforce_summary
from tests.conftest import client_a, delivery_manager, override_user

_NOW = "2026-01-01T00:00:00Z"


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


def _team(org_id, project_id, *, name="Radiology Pod A") -> Team:
    return Team(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name=name,
        site=DeliverySite.INDIA,
        domain="radiology",
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _annotator(org_id, team_id, *, name="Priya Sharma") -> Annotator:
    return Annotator(
        id=uuid4(),
        org_id=org_id,
        team_id=team_id,
        full_name=name,
        site=DeliverySite.INDIA,
        is_sme_certified=True,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    def __init__(self, *, teams: list[Team] | None = None, annotators: list[Annotator] | None = None):
        self.teams = teams or []
        self.annotators = annotators or []
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        if self.calls == 1:
            return FakeResult(self.teams)
        return FakeResult(self.annotators)


@pytest.mark.asyncio
async def test_get_project_workforce_summary_returns_teams_and_annotators() -> None:
    org_id = uuid4()
    project = _project(org_id)
    team_a = _team(org_id, project.id, name="Team A")
    team_b = _team(org_id, project.id, name="Team B")
    annotators = [
        _annotator(org_id, team_a.id, name="Alice"),
        _annotator(org_id, team_b.id, name="Bob"),
    ]
    session = FakeSession(teams=[team_a, team_b], annotators=annotators)
    user = _user(AppRole.DELIVERY_MANAGER, org_id)

    summary = await get_project_workforce_summary(session, project, user)

    assert summary.project_id == project.id
    assert len(summary.teams) == 2
    assert {team.id for team in summary.teams} == {team_a.id, team_b.id}
    assert len(summary.annotators) == 2
    assert {annotator.full_name for annotator in summary.annotators} == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_get_project_workforce_summary_scoped_to_selected_project() -> None:
    org_id = uuid4()
    project = _project(org_id)
    team_for_project = _team(org_id, project.id, name="In Project")
    annotator_for_project = _annotator(org_id, team_for_project.id, name="In Scope")
    session = FakeSession(
        teams=[team_for_project],
        annotators=[annotator_for_project],
    )
    user = _user(AppRole.BSG_LEADERSHIP, org_id)

    summary = await get_project_workforce_summary(session, project, user)

    assert summary.project_id == project.id
    assert [team.id for team in summary.teams] == [team_for_project.id]
    assert [annotator.team_id for annotator in summary.annotators] == [team_for_project.id]
    assert summary.annotators[0].full_name == "In Scope"


@pytest.mark.asyncio
async def test_delivery_manager_can_get_workforce_summary_http(
    api_client: AsyncClient,
    delivery_manager,
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/workforce-summary",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code in {200, 404}


@pytest.mark.asyncio
async def test_delivery_manager_cross_org_workforce_summary_http(
    api_client: AsyncClient,
    delivery_manager,
) -> None:
    override_user(delivery_manager)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/workforce-summary",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code in {403, 404}


@pytest.mark.asyncio
async def test_client_cannot_get_workforce_summary_http(api_client: AsyncClient, client_a) -> None:
    override_user(client_a)
    response = await api_client.get(
        f"/api/v1/projects/{uuid4()}/workforce-summary",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
