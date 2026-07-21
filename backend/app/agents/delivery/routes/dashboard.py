"""Dashboard route for the Delivery Performance Agent."""

from uuid import UUID

from fastapi import APIRouter, Query

from app.agents.delivery.schemas.dashboard_schema import DashboardResponse, DeliveryPortfolioResponse
from app.agents.delivery.services.dashboard_service import get_dashboard_data, get_portfolio_data
from app.agents.delivery.services.operational_briefing_service import (
    attach_operational_briefing_to_dashboard,
)
from app.api.deps import SessionDep, UserDep
from app.db.models import AppRole

router = APIRouter(tags=["delivery"])


@router.get("/delivery/portfolio", response_model=DeliveryPortfolioResponse)
async def get_delivery_portfolio(
    session: SessionDep,
    current_user: UserDep,
) -> DeliveryPortfolioResponse:
    """Return delivery dashboard summaries for all visible projects without AI summaries."""
    portfolio_data = await get_portfolio_data(session=session, current_user=current_user)
    return DeliveryPortfolioResponse.model_validate(portfolio_data)


@router.get("/delivery/dashboard/{project_id}", response_model=DashboardResponse)
async def get_delivery_dashboard(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
    with_ai_briefing: bool = Query(
        default=True,
        description="When true, attach Phase 15.4 operational briefing (AI narrative fail-open).",
    ),
) -> DashboardResponse:
    """Return the aggregated Delivery Performance dashboard for one project.

    Portfolio remains AI-free. Project dashboards optionally attach the grounded
    operational briefing and set ``daily_summary`` from its narrative.
    """
    dashboard_data = await get_dashboard_data(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    if with_ai_briefing and current_user.role != AppRole.CLIENT:
        await attach_operational_briefing_to_dashboard(
            session,
            project_id=project_id,
            current_user=current_user,
            dashboard_data=dashboard_data,
            with_ai=True,
        )
    else:
        dashboard_data["daily_summary"] = None
        dashboard_data["operational_briefing"] = None
    return DashboardResponse.model_validate(dashboard_data)
