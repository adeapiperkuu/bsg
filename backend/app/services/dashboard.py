from __future__ import annotations

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import (
    AlertStatus,
    AlertType,
    ClientCommunication,
    CommunicationStatus,
    Project,
    ProjectStatus,
    RiskAlert,
)
from app.schemas.domain import DashboardSummaryRead
from app.services.pdf_export import generate_simple_pdf
from app.services.scoping import scoped_project_query
from app.services.workforce import get_workforce_dashboard


async def get_dashboard_summary(
    session: AsyncSession,
    current_user: CurrentUser,
) -> DashboardSummaryRead:
    projects = list((await session.execute(scoped_project_query(current_user))).scalars())
    project_ids = [p.id for p in projects]

    open_alerts = 0
    open_drifts = 0
    pending_comms = 0

    if project_ids:
        open_alerts = len(
            list(
                (
                    await session.execute(
                        select(RiskAlert).where(
                            RiskAlert.project_id.in_(project_ids),
                            RiskAlert.deleted_at.is_(None),
                            RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                        )
                    )
                ).scalars()
            )
        )
        open_drifts = len(
            list(
                (
                    await session.execute(
                        select(RiskAlert).where(
                            RiskAlert.project_id.in_(project_ids),
                            RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                            RiskAlert.deleted_at.is_(None),
                            RiskAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                        )
                    )
                ).scalars()
            )
        )
        pending_comms = len(
            list(
                (
                    await session.execute(
                        select(ClientCommunication).where(
                            ClientCommunication.project_id.in_(project_ids),
                            ClientCommunication.status.in_(
                                [CommunicationStatus.DRAFT, CommunicationStatus.IN_REVIEW]
                            ),
                        )
                    )
                ).scalars()
            )
        )

    avg_util = None
    if current_user.role.value in {"delivery_manager", "bsg_leadership", "super_admin"}:
        try:
            wf = await get_workforce_dashboard(session, current_user)
            avg_util = wf.kpis.avg_utilization_pct
        except Exception:
            pass

    active = sum(1 for p in projects if p.status == ProjectStatus.ACTIVE)
    return DashboardSummaryRead(
        active_projects=active,
        open_risk_alerts=open_alerts,
        open_quality_drifts=open_drifts,
        pending_communications=pending_comms,
        avg_utilization_pct=avg_util,
    )


async def export_project_report_pdf(session: AsyncSession, project: Project, title: str, body: str) -> Response:
    pdf_bytes = generate_simple_pdf(title, body)
    filename = f"{project.name.replace(' ', '_')}_report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
