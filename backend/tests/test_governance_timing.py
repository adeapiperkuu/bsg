from uuid import uuid4

import pytest

import inspect

from app.agents.governance.services.governance_service import (
    map_action_list_row,
    map_dependency_list_row,
    map_escalation_list_row,
)
from app.agents.governance.timing import (
    GovernanceEndpointTimer,
    governance_db_section,
    instrument_governance_endpoint,
    row_count_from_result,
)
from app.core.security import CurrentUser
from app.db.models import AppRole
from app.schemas.common import DataResponse, ListResponse, Pagination


def _user(role: AppRole = AppRole.DELIVERY_MANAGER) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def test_governance_list_row_mappers_stay_synchronous() -> None:
    for mapper in (map_dependency_list_row, map_action_list_row, map_escalation_list_row):
        assert not inspect.iscoroutinefunction(mapper)


def test_row_count_from_list_and_data_responses() -> None:
    pagination = Pagination(limit=10)
    assert row_count_from_result(ListResponse(data=[1, 2, 3], pagination=pagination)) == 3
    assert row_count_from_result(DataResponse(data={"id": "x"})) == 1
    assert row_count_from_result(DataResponse(data=None)) == 0


@pytest.mark.asyncio
async def test_governance_db_section_accumulates_db_time() -> None:
    timer = GovernanceEndpointTimer("GET /governance/bootstrap", _user())
    token = None
    from app.agents.governance import timing as timing_module

    token = timing_module._set_governance_timer(timer)
    try:
        async with governance_db_section():
            pass
        assert timer.db_ms >= 0
        assert timer.serialization_ms >= 0
    finally:
        timing_module._reset_governance_timer(token)


@pytest.mark.asyncio
async def test_instrument_governance_endpoint_logs_structured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[dict[str, object]] = []

    def _capture(_logger: object, _msg: str, *, extra: dict[str, object]) -> None:
        logged.append(extra)

    monkeypatch.setattr(
        "app.agents.governance.timing.logger.info",
        lambda msg, *, extra: _capture(None, msg, extra=extra),
    )

    @instrument_governance_endpoint("GET /governance/actions")
    async def handler(current_user: CurrentUser) -> ListResponse[int]:
        async with governance_db_section():
            pass
        return ListResponse(data=[1, 2], pagination=Pagination(limit=2))

    user = _user()
    result = await handler(current_user=user)

    assert len(result.data) == 2
    assert logged
    entry = logged[0]
    assert entry["endpoint"] == "GET /governance/actions"
    assert entry["org_id"] == str(user.org_id)
    assert entry["role"] == user.role.value
    assert entry["row_count"] == 2
    assert "db_ms" in entry
    assert "serialization_ms" in entry
    assert "total_ms" in entry
