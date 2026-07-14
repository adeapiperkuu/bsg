import inspect
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.agents.governance.schemas.governance import (
    GovernanceAnalyticsRead,
    GovernanceBootstrapRead,
    GovernanceKpisRead,
    GovernanceRegisterRowRead,
)
from app.agents.governance.services.governance_service import (
    PaginatedGovernanceRows,
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
from tests.conftest import override_user


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

    def _capture(msg: str, *args: object, extra: dict[str, object]) -> None:
        logged.append(extra)

    monkeypatch.setattr(
        "app.agents.governance.timing.logger.info",
        _capture,
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


@pytest.mark.asyncio
async def test_instrument_governance_endpoint_records_optional_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[dict[str, object]] = []

    def _capture(msg: str, *args: object, extra: dict[str, object]) -> None:
        logged.append(extra)

    monkeypatch.setattr("app.agents.governance.timing.logger.info", _capture)

    @instrument_governance_endpoint("GET /governance/dependencies")
    async def handler(
        current_user: CurrentUser,
        limit: int = 6,
        offset: int = 0,
    ) -> ListResponse[int]:
        from app.agents.governance.timing import get_governance_timer

        timer = get_governance_timer()
        assert timer is not None
        timer.record_meta(
            execute_count=1,
            cache_hit=False,
            activity_row_count=8,
            project_row_count=12,
        )
        return ListResponse(data=[1], pagination=Pagination(limit=limit, offset=offset))

    result = await handler(current_user=_user(), limit=6, offset=0)

    assert len(result.data) == 1
    entry = logged[0]
    assert entry["limit"] == 6
    assert entry["offset"] == 0
    assert entry["execute_count"] == 1
    assert entry["cache_hit"] is False
    assert entry["activity_row_count"] == 8
    assert entry["project_row_count"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "endpoint"),
    [
        ("/api/v1/governance/bootstrap", "GET /governance/bootstrap"),
        ("/api/v1/governance/analytics?days=30", "GET /governance/analytics"),
        ("/api/v1/governance/dependencies", "GET /governance/dependencies"),
        ("/api/v1/governance/register", "GET /governance/register"),
    ],
)
async def test_governance_baseline_endpoints_emit_timing_logs(
    api_client: AsyncClient,
    delivery_manager: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    endpoint: str,
) -> None:
    logged: list[dict[str, object]] = []

    def _capture(_msg: str, *args: object, extra: dict[str, object]) -> None:
        logged.append(extra)

    monkeypatch.setattr("app.agents.governance.timing.logger.info", _capture)

    async def _bootstrap(_session: object, _user: CurrentUser) -> GovernanceBootstrapRead:
        return GovernanceBootstrapRead(
            kpis=GovernanceKpisRead(
                open_actions=0,
                overdue_actions=0,
                open_escalations=0,
                blocking_dependencies=0,
                at_risk_items=0,
                sla_adherence_pct=100.0,
            )
        )

    async def _analytics(
        _session: object,
        _user: CurrentUser,
        *,
        days: int,
        **_kwargs: object,
    ) -> GovernanceAnalyticsRead:
        return GovernanceAnalyticsRead(
            generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            date_range_days=days,
            project_health=[],
            portfolio_risk_ranking=[],
            insights=[],
            recommendations=[],
            charts={},
            recent_activity=[],
            export_sections=[],
        )

    async def _dependencies_page(
        _session: object,
        _user: CurrentUser,
        **kwargs: object,
    ) -> PaginatedGovernanceRows:
        return PaginatedGovernanceRows(items=[], total=0, limit=50, offset=0)

    async def _register_page(
        _session: object,
        _user: CurrentUser,
        **kwargs: object,
    ) -> PaginatedGovernanceRows:
        project_id = uuid4()
        return PaginatedGovernanceRows(
            items=[
                GovernanceRegisterRowRead(
                    project_id=project_id,
                    project_name="Alpha",
                    scope_status=None,
                    scope_version=None,
                    open_dependencies=0,
                    blocking_dependencies=0,
                    open_actions=0,
                    open_escalations=0,
                    health="green",
                )
            ],
            total=1,
            limit=50,
            offset=0,
        )

    monkeypatch.setattr(
        "app.agents.governance.routes.governance.get_governance_bootstrap",
        _bootstrap,
    )
    monkeypatch.setattr(
        "app.agents.governance.routes.governance.get_governance_analytics",
        _analytics,
    )
    monkeypatch.setattr(
        "app.agents.governance.routes.governance.list_governance_dependencies_page",
        _dependencies_page,
    )
    monkeypatch.setattr(
        "app.agents.governance.routes.governance.list_governance_register_page",
        _register_page,
    )

    override_user(delivery_manager)
    response = await api_client.get(path)

    assert response.status_code == 200, response.text
    assert logged
    entry = logged[-1]
    assert entry["endpoint"] == endpoint
    assert entry["role"] == delivery_manager.role.value
    assert entry["org_id"] == str(delivery_manager.org_id)
    assert "db_ms" in entry
    assert "serialization_ms" in entry
    assert "total_ms" in entry
