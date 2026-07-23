from __future__ import annotations

import csv
from html import escape
from io import BytesIO, StringIO
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
from app.db.models import AppRole, ClientCommunication, CommunicationStatus
from app.schemas.client_portal import (
    ClientChangeRequestCreate,
    ClientChangeRequestRead,
    ClientProjectDashboardRead,
)
from app.schemas.common import DataResponse
from app.services.client_portal import (
    build_client_project_dashboard,
    create_client_change_request,
)
from app.services.scoping import get_visible_project

router = APIRouter(tags=["client-portal"])

_ClientRoleDep = Annotated[CurrentUser, Depends(require_role(AppRole.CLIENT))]


@router.get(
    "/client/projects/{project_id}/dashboard",
    response_model=DataResponse[ClientProjectDashboardRead],
)
async def get_client_project_dashboard(
    project_id: UUID,
    session: SessionDep,
    current_user: UserDep,
) -> DataResponse[ClientProjectDashboardRead]:
    dashboard = await build_client_project_dashboard(session, current_user, project_id)
    return DataResponse(data=dashboard)


@router.post(
    "/client/projects/{project_id}/change-requests",
    response_model=DataResponse[ClientChangeRequestRead],
    status_code=201,
)
async def submit_client_change_request(
    project_id: UUID,
    payload: ClientChangeRequestCreate,
    session: SessionDep,
    current_user: _ClientRoleDep,
) -> DataResponse[ClientChangeRequestRead]:
    change_request = await create_client_change_request(
        session,
        current_user,
        project_id,
        payload,
    )
    return DataResponse(data=change_request)


async def _get_sent_report(
    session: SessionDep,
    current_user: CurrentUser,
    communication_id: UUID,
) -> ClientCommunication:
    report = (
        await session.execute(
            select(ClientCommunication).where(ClientCommunication.id == communication_id)
        )
    ).scalar_one_or_none()
    if report is None or report.status != CommunicationStatus.SENT:
        raise ApiError(404, "NOT_FOUND", "Published report was not found.")
    await get_visible_project(session, report.project_id, current_user)
    return report


def _safe_file_stem(value: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return (stem or "project-report")[:100]


def _report_pdf(report: ClientCommunication) -> bytes:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=report.subject,
        author="BSG Insights Hub",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "ClientReportBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=7,
    )
    story = [
        Paragraph(escape(report.subject), styles["Title"]),
        Spacer(1, 6 * mm),
    ]
    body = report.body_approved or report.body_draft
    for block in re.split(r"\n\s*\n", body):
        cleaned = block.strip()
        if not cleaned:
            continue
        story.append(Paragraph(escape(cleaned).replace("\n", "<br/>"), body_style))
    document.build(story)
    return buffer.getvalue()


def _report_csv(report: ClientCommunication) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["report_id", "report_type", "title", "published_at", "executive_summary"])
    writer.writerow(
        [
            str(report.id),
            getattr(report.comm_type, "value", report.comm_type),
            report.subject,
            (report.sent_at or report.updated_at).isoformat(),
            report.body_approved or report.body_draft,
        ]
    )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


@router.get("/client/reports/{communication_id}/download/{format}")
async def download_client_report(
    communication_id: UUID,
    format: Literal["pdf", "csv"],
    session: SessionDep,
    current_user: UserDep,
) -> Response:
    report = await _get_sent_report(session, current_user, communication_id)
    file_stem = _safe_file_stem(report.subject)
    if format == "pdf":
        content = _report_pdf(report)
        content_type = "application/pdf"
    else:
        content = _report_csv(report)
        content_type = "text/csv; charset=utf-8"
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_stem}.{format}"',
            "Cache-Control": "private, no-store",
        },
    )
