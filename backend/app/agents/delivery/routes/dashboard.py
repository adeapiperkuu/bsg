"""Dashboard route for the Delivery Performance Agent."""

from uuid import UUID

from fastapi import APIRouter

from app.agents.delivery.ai.summary_service import generate_daily_summary
from app.agents.delivery.schemas.dashboard_schema import DashboardResponse, DeliveryPortfolioResponse
from app.agents.delivery.services.dashboard_service import get_dashboard_data, get_portfolio_data
from app.api.deps import SessionDep, UserDep

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
) -> DashboardResponse:
    """Return the aggregated Delivery Performance dashboard for one project."""
    dashboard_data = await get_dashboard_data(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    dashboard_data["daily_summary"] = None
    return DashboardResponse.model_validate(dashboard_data)


@router.get("/delivery/dashboard/{project_id}/summary")
async def get_delivery_dashboard_summary(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> dict[str, str | None]:
    """Return the AI-generated daily summary for one project's dashboard, computed on demand."""
    dashboard_data = await get_dashboard_data(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    daily_summary = await generate_daily_summary(dashboard_data)
    return {"daily_summary": daily_summary}
