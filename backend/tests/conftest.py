from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.models import AppRole
from app.db.session import get_db_session
from app.main import app

pytest_plugins = ("tests.knowledge_fixtures",)

ORG_A = uuid4()
ORG_B = uuid4()
USER_CLIENT_A = uuid4()
USER_SUPER = uuid4()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-rls",
        action="store_true",
        default=False,
        help=(
            "Run backend/tests/rls against the real database configured in "
            "DATABASE_URL (DEVELOPMENT_PLAN.md Workstream C). All writes "
            "happen inside a transaction that is always rolled back. Omit "
            "this flag (the default) to skip these tests, as plain `pytest` "
            "does."
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-rls"):
        return
    skip_live = pytest.mark.skip(reason="pass --run-live-rls to run against the real database")
    for item in items:
        parts = str(item.fspath).replace("\\", "/").split("/")
        if "rls" in parts:
            item.add_marker(skip_live)


class FakeScalars:
    def __init__(self, items: list[Any] | None = None) -> None:
        self._items = items or []

    def all(self) -> list[Any]:
        return self._items

    def __iter__(self):
        return iter(self._items)


class FakeResult:
    def __init__(self, value: Any = None, items: list[Any] | None = None) -> None:
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)

    def all(self) -> list[Any]:
        return self._items


class FakeSession:
    """Minimal async session for HTTP tests; returns empty / not-found DB results."""

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        return FakeResult()

    async def commit(self) -> None:
        return None

    async def refresh(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _clear_delivery_portfolio_cache():
    """Delivery portfolio reads are cached in-process; user/org fixture ids are reused
    across tests, so a stale entry from one test could leak into the next."""
    from app.agents.delivery.configuration import (
        invalidate_delivery_scoring_thresholds_cache,
    )
    from app.agents.delivery.services.dashboard_service import clear_delivery_portfolio_cache

    clear_delivery_portfolio_cache()
    invalidate_delivery_scoring_thresholds_cache()
    yield


@pytest.fixture
def client_a() -> CurrentUser:
    return CurrentUser(
        id=USER_CLIENT_A,
        org_id=ORG_A,
        email="client-a@example.com",
        role=AppRole.CLIENT,
        is_active=True,
    )


@pytest.fixture
def super_admin() -> CurrentUser:
    return CurrentUser(
        id=USER_SUPER,
        org_id=ORG_A,
        email="admin@example.com",
        role=AppRole.SUPER_ADMIN,
        is_active=True,
    )


@pytest.fixture
def delivery_manager() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=ORG_A,
        email="dm@example.com",
        role=AppRole.DELIVERY_MANAGER,
        is_active=True,
    )


async def _override_session() -> AsyncIterator[AsyncSession]:
    yield FakeSession()  # type: ignore[misc]


@pytest.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def override_user(user: CurrentUser):
    async def _dep() -> CurrentUser:
        return user

    app.dependency_overrides[get_current_user] = _dep


def clear_overrides() -> None:
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _cleanup_overrides() -> AsyncIterator[None]:
    yield
    clear_overrides()
