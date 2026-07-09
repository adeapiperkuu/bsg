"""Conversation-restore authorization: ownership alone must not be enough.

`load_delivery_chat_conversation` must also confirm the requesting user still has
access to the project the conversation is scoped to (e.g. after a project
reassignment or an org change), reusing the shared `get_visible_project` helper
rather than duplicating org/assignment logic.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.agents.delivery.services.chat_service import (
    AGENT_NAME,
    load_delivery_chat_conversation,
)
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AppRole, Project


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)

    def all(self):
        return list(self._rows)


class FakeSession:
    """Fake AsyncSession covering the three query shapes this code path issues:
    get_visible_project's project SELECT, the conversation-turn SELECT, and the
    evidence-link SELECT."""

    def __init__(self, *, anchor: AgentQuery, project: Project | None, history_rows=None):
        self.anchor = anchor
        self.project = project
        self.history_rows = history_rows or []

    async def get(self, _model, _id):
        return self.anchor

    async def execute(self, stmt):
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        if "from projects" in compiled:
            return _ScalarResult(self.project)
        if "agent_query_evidence_links" in compiled:
            return _RowsResult([])
        return _RowsResult(self.history_rows)


def _user(role: AppRole, org_id) -> CurrentUser:
    return CurrentUser(
        id=uuid4(), org_id=org_id, email=f"{role.value}@example.com", role=role, is_active=True
    )


def _project(org_id) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="Test Project",
        vertical="medical",
        status="active",
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
    )


def _anchor(*, user_id, project_id) -> AgentQuery:
    return AgentQuery(
        id=uuid4(),
        user_id=user_id,
        org_id=uuid4(),
        project_id=project_id,
        agent_name=AGENT_NAME,
        query_text="What's blocking delivery?",
        answer_text="Answer",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_conversation_restore_denied_when_user_no_longer_has_project_access() -> None:
    """Ownership matches, but the project is in a different org — must be denied."""
    project_org = uuid4()
    requesting_user_org = uuid4()
    project = _project(project_org)
    user = _user(AppRole.DELIVERY_MANAGER, requesting_user_org)
    anchor = _anchor(user_id=user.id, project_id=project.id)
    session = FakeSession(anchor=anchor, project=project)

    result = await load_delivery_chat_conversation(session, user, anchor.id)

    assert result is None


@pytest.mark.asyncio
async def test_conversation_restore_denied_when_project_no_longer_exists() -> None:
    user = _user(AppRole.DELIVERY_MANAGER, uuid4())
    anchor = _anchor(user_id=user.id, project_id=uuid4())
    session = FakeSession(anchor=anchor, project=None)

    result = await load_delivery_chat_conversation(session, user, anchor.id)

    assert result is None


@pytest.mark.asyncio
async def test_conversation_restore_allowed_when_user_still_has_project_access() -> None:
    org_id = uuid4()
    project = _project(org_id)
    user = _user(AppRole.DELIVERY_MANAGER, org_id)
    anchor = _anchor(user_id=user.id, project_id=project.id)
    session = FakeSession(anchor=anchor, project=project, history_rows=[anchor])

    result = await load_delivery_chat_conversation(session, user, anchor.id)

    assert result is not None
    assert result.conversation_id == anchor.id
    assert result.project_id == project.id


@pytest.mark.asyncio
async def test_conversation_restore_skips_project_check_for_portfolio_scoped_conversation() -> None:
    """A conversation with no project_id (portfolio-scope question) has nothing to
    re-check — only ownership applies."""
    user = _user(AppRole.DELIVERY_MANAGER, uuid4())
    anchor = _anchor(user_id=user.id, project_id=None)
    session = FakeSession(anchor=anchor, project=None, history_rows=[anchor])

    result = await load_delivery_chat_conversation(session, user, anchor.id)

    assert result is not None
    assert result.project_id is None


@pytest.mark.asyncio
async def test_conversation_restore_denied_for_non_owner_non_admin() -> None:
    org_id = uuid4()
    project = _project(org_id)
    owner = _user(AppRole.DELIVERY_MANAGER, org_id)
    other_user = _user(AppRole.DELIVERY_MANAGER, org_id)
    anchor = _anchor(user_id=owner.id, project_id=project.id)
    session = FakeSession(anchor=anchor, project=project)

    result = await load_delivery_chat_conversation(session, other_user, anchor.id)

    assert result is None


@pytest.mark.asyncio
async def test_conversation_restore_allowed_for_super_admin_across_orgs() -> None:
    """Super admins may read any conversation, matching the existing elevated-access
    pattern used elsewhere (e.g. recommendation mutations) — but access is still
    re-verified against the project via get_visible_project."""
    owner_org = uuid4()
    project = _project(owner_org)
    owner = _user(AppRole.DELIVERY_MANAGER, owner_org)
    admin = _user(AppRole.SUPER_ADMIN, uuid4())
    anchor = _anchor(user_id=owner.id, project_id=project.id)
    session = FakeSession(anchor=anchor, project=project, history_rows=[anchor])

    result = await load_delivery_chat_conversation(session, admin, anchor.id)

    assert result is not None
