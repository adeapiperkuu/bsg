from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApiError
from app.core.security import CurrentUser, can_read_all_orgs
from app.db.models import AppRole, Project
from app.services.scoping import can_access_project, get_visible_project, scoped_project_query


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


def test_super_admin_can_read_all_orgs() -> None:
    assert can_read_all_orgs(AppRole.SUPER_ADMIN) is True


def test_leadership_cannot_read_all_orgs() -> None:
    assert can_read_all_orgs(AppRole.BSG_LEADERSHIP) is False


def test_client_cannot_read_all_orgs() -> None:
    assert can_read_all_orgs(AppRole.CLIENT) is False


def test_delivery_manager_sees_org_projects_only() -> None:
    org_a = uuid4()
    user = _user(AppRole.DELIVERY_MANAGER, org_a)
    query = scoped_project_query(user)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "projects.org_id" in compiled
    assert str(org_a).replace("-", "") in compiled


def test_leadership_sees_org_projects_only() -> None:
    org_a = uuid4()
    user = _user(AppRole.BSG_LEADERSHIP, org_a)
    query = scoped_project_query(user)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "projects.org_id" in compiled
    assert str(org_a).replace("-", "") in compiled


def test_client_query_uses_project_assignments() -> None:
    user = _user(AppRole.CLIENT)
    query = scoped_project_query(user)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "project_assignments" in compiled


def test_can_access_project_matrix() -> None:
    org_a = uuid4()
    org_b = uuid4()
    project = _project(org_a)

    assert can_access_project(project, _user(AppRole.SUPER_ADMIN, org_b)) is True
    assert can_access_project(project, _user(AppRole.DELIVERY_MANAGER, org_a)) is True
    assert can_access_project(project, _user(AppRole.BSG_LEADERSHIP, org_a)) is True
    assert can_access_project(project, _user(AppRole.CLIENT, org_a), has_assignment=True) is True
    assert can_access_project(project, _user(AppRole.CLIENT, org_a), has_assignment=False) is False
    assert can_access_project(project, _user(AppRole.DELIVERY_MANAGER, org_b)) is False


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, project: Project | None, *, has_assignment: bool = False):
        self.project = project
        self.has_assignment = has_assignment
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "project_assignments" in compiled:
            return FakeResult(uuid4() if self.has_assignment else None)
        return FakeResult(self.project)


@pytest.mark.asyncio
async def test_get_visible_project_returns_403_for_cross_org_delivery_manager() -> None:
    org_a = uuid4()
    org_b = uuid4()
    project = _project(org_a)
    session = FakeSession(project)
    user = _user(AppRole.DELIVERY_MANAGER, org_b)

    with pytest.raises(ApiError) as exc:
        await get_visible_project(session, project.id, user)

    assert exc.value.status_code == 403
    assert exc.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_get_visible_project_returns_200_for_org_delivery_manager() -> None:
    org_a = uuid4()
    project = _project(org_a)
    session = FakeSession(project)
    user = _user(AppRole.DELIVERY_MANAGER, org_a)

    visible = await get_visible_project(session, project.id, user)
    assert visible.id == project.id


@pytest.mark.asyncio
async def test_get_visible_project_returns_403_for_unassigned_client() -> None:
    org_a = uuid4()
    project = _project(org_a)
    session = FakeSession(project, has_assignment=False)
    user = _user(AppRole.CLIENT, org_a)

    with pytest.raises(ApiError) as exc:
        await get_visible_project(session, project.id, user)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_visible_project_returns_project_for_assigned_client() -> None:
    org_a = uuid4()
    project = _project(org_a)
    session = FakeSession(project, has_assignment=True)
    user = _user(AppRole.CLIENT, org_a)

    visible = await get_visible_project(session, project.id, user)
    assert visible.id == project.id


@pytest.mark.asyncio
async def test_get_visible_project_returns_404_when_missing() -> None:
    session = FakeSession(None)
    user = _user(AppRole.SUPER_ADMIN)

    with pytest.raises(ApiError) as exc:
        await get_visible_project(session, uuid4(), user)

    assert exc.value.status_code == 404
