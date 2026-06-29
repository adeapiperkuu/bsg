from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import SessionDep, UserDep
from app.schemas.common import DataResponse
from app.schemas.domain import DashboardSummaryRead
from app.services.dashboard import export_project_report_pdf, get_dashboard_summary
from app.services.scoping import get_visible_project

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DataResponse[DashboardSummaryRead])
async def dashboard_summary(session: SessionDep, current_user: UserDep) -> DataResponse[DashboardSummaryRead]:
    summary = await get_dashboard_summary(session, current_user)
    return DataResponse(data=summary)
