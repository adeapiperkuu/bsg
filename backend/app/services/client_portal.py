from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.visibility import (
    ClientVisibleMetric,
    load_client_visibility_policy,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    ClientChangeRequest,
    ClientCommunication,
    ClientDeliverable,
    ClientMeeting,
    CommunicationStatus,
    CommunicationType,
    DeliveryConfidenceScore,
    GovernanceDependencyType,
    GovernanceEscalation,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeVisibility,
    Milestone,
    MilestoneStatus,
    ProjectDependency,
)
from app.schemas.client_portal import (
    ClientActionRead,
    ClientAiSummaryRead,
    ClientChangeRequestCreate,
    ClientChangeRequestRead,
    ClientDeliverableRead,
    ClientDocumentRead,
    ClientMeetingActionItemRead,
    ClientMeetingRead,
    ClientMilestoneRead,
    ClientNotificationRead,
    ClientProjectDashboardRead,
    ClientProjectOverviewRead,
    ClientReportRead,
    ClientRiskRead,
)
from app.services.scoping import get_visible_project


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _confidence_value(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return max(0, min(100, round(float(value))))


def _health_for_confidence(score: int | None) -> str:
    if score is None:
        return "insufficient"
    if score >= 85:
        return "green"
    if score >= 70:
        return "amber"
    return "red"


def _confidence_label(score: int | None) -> str:
    if score is None:
        return "Awaiting data"
    if score >= 85:
        return "High confidence"
    if score >= 70:
        return "Moderate confidence"
    return "Low confidence"


def _milestone_progress(status: MilestoneStatus) -> int:
    return {
        MilestoneStatus.COMPLETED: 100,
        MilestoneStatus.ON_TRACK: 65,
        MilestoneStatus.AT_RISK: 45,
        MilestoneStatus.PENDING: 10,
        MilestoneStatus.MISSED: 100,
    }.get(status, 0)


def _action_type(title: str) -> str:
    normalized = title.lower()
    if any(word in normalized for word in ("approve", "approval", "sign-off", "signoff")):
        return "approval"
    if any(word in normalized for word in ("provide", "information", "data", "access", "confirm")):
        return "information_request"
    return "client_action"


def _split_client_risk_summary(summary: str | None) -> tuple[str | None, str | None]:
    if not summary:
        return None, None
    marker = "mitigation:"
    index = summary.lower().find(marker)
    if index < 0:
        return summary.strip(), None
    impact = summary[:index].strip().rstrip("-—: ")
    mitigation = summary[index + len(marker) :].strip()
    return impact or None, mitigation or None


def _current_phase(milestones: list[Milestone]) -> str:
    for milestone in milestones:
        if milestone.status in {
            MilestoneStatus.ON_TRACK,
            MilestoneStatus.AT_RISK,
        }:
            return milestone.name
    for milestone in milestones:
        if milestone.status == MilestoneStatus.PENDING:
            return milestone.name
    if milestones and all(item.status == MilestoneStatus.COMPLETED for item in milestones):
        return "Delivery complete"
    return "Planning"


def _summary_preview(body: str, limit: int = 280) -> str:
    compact = " ".join(body.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _meeting_action_items(raw: object) -> list[ClientMeetingActionItemRead]:
    if not isinstance(raw, list):
        return []
    items: list[ClientMeetingActionItemRead] = []
    for value in raw:
        if not isinstance(value, dict) or not str(value.get("title", "")).strip():
            continue
        try:
            items.append(ClientMeetingActionItemRead.model_validate(value))
        except ValueError:
            continue
    return items


async def build_client_project_dashboard(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
) -> ClientProjectDashboardRead:
    project = await get_visible_project(session, project_id, current_user)

    milestones = list(
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project.id, Milestone.deleted_at.is_(None))
                .order_by(Milestone.planned_date.asc(), Milestone.id.asc())
            )
        ).scalars()
    )
    visibility_policy = await load_client_visibility_policy(session)
    latest_confidence = None
    if visibility_policy.allows(ClientVisibleMetric.DELIVERY_CONFIDENCE):
        latest_confidence = (
            await session.execute(
                select(DeliveryConfidenceScore)
                .where(DeliveryConfidenceScore.project_id == project.id)
                .order_by(
                    DeliveryConfidenceScore.created_at.desc(),
                    DeliveryConfidenceScore.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    escalations = list(
        (
            await session.execute(
                select(GovernanceEscalation)
                .where(
                    GovernanceEscalation.project_id == project.id,
                    GovernanceEscalation.client_visible.is_(True),
                    GovernanceEscalation.deleted_at.is_(None),
                )
                .order_by(GovernanceEscalation.updated_at.desc(), GovernanceEscalation.id.desc())
            )
        ).scalars()
    )
    dependencies = list(
        (
            await session.execute(
                select(ProjectDependency)
                .where(
                    ProjectDependency.project_id == project.id,
                    ProjectDependency.dependency_type == GovernanceDependencyType.CLIENT_ACTION,
                    ProjectDependency.deleted_at.is_(None),
                )
                .order_by(ProjectDependency.due_date.asc().nullslast(), ProjectDependency.id.asc())
            )
        ).scalars()
    )
    communications = list(
        (
            await session.execute(
                select(ClientCommunication)
                .where(
                    ClientCommunication.project_id == project.id,
                    ClientCommunication.status == CommunicationStatus.SENT,
                )
                .order_by(ClientCommunication.sent_at.desc().nullslast(), ClientCommunication.id.desc())
                .limit(50)
            )
        ).scalars()
    )
    documents = list(
        (
            await session.execute(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.org_id == project.org_id,
                    KnowledgeDocument.visibility == KnowledgeVisibility.CLIENT_SAFE,
                    KnowledgeDocument.status == KnowledgeDocumentStatus.APPROVED,
                    KnowledgeDocument.deleted_at.is_(None),
                    or_(
                        KnowledgeDocument.project == project.name,
                        KnowledgeDocument.project.is_(None),
                    ),
                )
                .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id.desc())
                .limit(100)
            )
        ).scalars()
    )
    deliverable_rows = list(
        (
            await session.execute(
                select(ClientDeliverable)
                .where(
                    ClientDeliverable.project_id == project.id,
                    ClientDeliverable.client_visible.is_(True),
                    ClientDeliverable.deleted_at.is_(None),
                )
                .order_by(ClientDeliverable.due_date.asc().nullslast(), ClientDeliverable.id.asc())
            )
        ).scalars()
    )
    change_request_rows = list(
        (
            await session.execute(
                select(ClientChangeRequest)
                .where(
                    ClientChangeRequest.project_id == project.id,
                    ClientChangeRequest.deleted_at.is_(None),
                )
                .order_by(ClientChangeRequest.created_at.desc(), ClientChangeRequest.id.desc())
            )
        ).scalars()
    )
    meeting_rows = list(
        (
            await session.execute(
                select(ClientMeeting)
                .where(
                    ClientMeeting.project_id == project.id,
                    ClientMeeting.client_visible.is_(True),
                    ClientMeeting.deleted_at.is_(None),
                )
                .order_by(ClientMeeting.starts_at.desc(), ClientMeeting.id.desc())
                .limit(100)
            )
        ).scalars()
    )

    confidence = _confidence_value(
        latest_confidence.score_pct if latest_confidence is not None else None
    )
    completed_count = sum(item.status == MilestoneStatus.COMPLETED for item in milestones)
    completion = round((completed_count / len(milestones)) * 100) if milestones else 0

    milestone_reads = [
        ClientMilestoneRead(
            id=item.id,
            name=item.name,
            description=item.description,
            planned_date=item.planned_date,
            actual_date=item.actual_date,
            status=_enum_value(item.status),
            progress_percentage=_milestone_progress(item.status),
        )
        for item in milestones
    ]
    risk_reads: list[ClientRiskRead] = []
    for item in escalations:
        impact, mitigation = _split_client_risk_summary(item.client_summary)
        risk_reads.append(
            ClientRiskRead(
                id=item.id,
                title=item.title,
                severity=_enum_value(item.severity),
                impact=impact,
                mitigation=mitigation,
                status=_enum_value(item.status),
                updated_at=item.updated_at,
            )
        )

    today = date.today()
    action_reads = [
        ClientActionRead(
            id=item.id,
            title=item.title,
            description=item.description,
            action_type=_action_type(item.title),
            due_date=item.due_date,
            status=_enum_value(item.status),
            is_overdue=bool(
                item.due_date
                and item.due_date < today
                and _enum_value(item.status) != "resolved"
            ),
        )
        for item in dependencies
    ]
    report_reads = [
        ClientReportRead(
            id=item.id,
            title=item.subject,
            report_type=_enum_value(item.comm_type),
            executive_summary=_summary_preview(item.body_approved or item.body_draft),
            published_at=item.sent_at or item.updated_at,
            pdf_download_url=f"/api/v1/client/reports/{item.id}/download/pdf",
            csv_download_url=f"/api/v1/client/reports/{item.id}/download/csv",
        )
        for item in communications
    ]
    document_reads = [
        ClientDocumentRead(
            id=item.id,
            title=item.title,
            document_type=item.document_type or _enum_value(item.source_type),
            version=item.version,
            description=item.description,
            file_name=item.file_name,
            file_url=item.file_url,
            shared_at=item.updated_at,
        )
        for item in documents
    ]

    if deliverable_rows:
        deliverable_reads = [
            ClientDeliverableRead(
                id=item.id,
                title=item.title,
                description=item.description,
                status=_enum_value(item.status),
                due_date=item.due_date,
                completed_at=item.completed_at,
                file_name=item.file_name,
                file_url=item.file_url,
            )
            for item in deliverable_rows
        ]
    else:
        deliverable_reads = [
            ClientDeliverableRead(
                id=item.id,
                title=item.name,
                description=item.description,
                status=(
                    "completed"
                    if item.status == MilestoneStatus.COMPLETED
                    else "in_progress"
                    if item.status in {MilestoneStatus.ON_TRACK, MilestoneStatus.AT_RISK}
                    else "planned"
                ),
                due_date=item.planned_date,
                completed_at=None,
            )
            for item in milestones
        ]

    meeting_reads = [
        ClientMeetingRead(
            id=item.id,
            title=item.title,
            starts_at=item.starts_at,
            duration_minutes=item.duration_minutes,
            meeting_url=item.meeting_url,
            agenda=item.agenda,
            minutes=item.minutes,
            action_items=_meeting_action_items(item.action_items),
            status=_enum_value(item.status),
        )
        for item in meeting_rows
    ]

    published_summary = next(
        (
            item
            for item in communications
            if item.comm_type
            in {CommunicationType.WEEKLY_SUMMARY, CommunicationType.EXECUTIVE_SUMMARY}
        ),
        None,
    )
    current_progress = [
        f"{item.name}: {_enum_value(item.status).replace('_', ' ')}"
        for item in milestones
        if item.status in {MilestoneStatus.COMPLETED, MilestoneStatus.ON_TRACK}
    ][:4]
    upcoming_work = [
        f"{item.name} — due {item.planned_date.isoformat()}"
        for item in milestones
        if item.status in {MilestoneStatus.PENDING, MilestoneStatus.ON_TRACK, MilestoneStatus.AT_RISK}
    ][:4]
    ai_summary = ClientAiSummaryRead(
        title=published_summary.subject if published_summary else "Weekly project summary",
        summary=(
            published_summary.body_approved or published_summary.body_draft
            if published_summary
            else "No approved AI project summary has been published yet."
        ),
        current_progress=current_progress,
        risks=[item.title for item in risk_reads[:4]],
        upcoming_work=upcoming_work,
        generated_at=(
            published_summary.sent_at or published_summary.updated_at
            if published_summary
            else None
        ),
    )

    notification_reads: list[ClientNotificationRead] = []
    notification_reads.extend(
        ClientNotificationRead(
            id=f"report:{item.id}",
            notification_type="report_published",
            title="New report published",
            detail=item.subject,
            occurred_at=item.sent_at or item.updated_at,
            href="/client/reports",
        )
        for item in communications[:10]
    )
    notification_reads.extend(
        ClientNotificationRead(
            id=f"milestone:{item.id}",
            notification_type="milestone_completed",
            title="Milestone completed",
            detail=item.name,
            occurred_at=datetime.combine(
                item.actual_date or item.planned_date,
                datetime.min.time(),
                tzinfo=UTC,
            ),
            href="/client/status?view=progress",
        )
        for item in milestones
        if item.status == MilestoneStatus.COMPLETED
    )
    notification_reads.extend(
        ClientNotificationRead(
            id=f"risk:{item.id}",
            notification_type="risk_updated",
            title="Risk updated",
            detail=item.title,
            occurred_at=item.updated_at,
            href="/client/status?view=risks",
        )
        for item in escalations
    )
    notification_reads.extend(
        ClientNotificationRead(
            id=f"document:{item.id}",
            notification_type="document_shared",
            title="Document shared",
            detail=item.title,
            occurred_at=item.updated_at,
            href="/client/status?view=documents",
        )
        for item in documents
    )
    notification_reads.extend(
        ClientNotificationRead(
            id=f"meeting:{item.id}",
            notification_type="meeting_scheduled",
            title="Meeting scheduled",
            detail=item.title,
            occurred_at=item.created_at,
            href="/client/status?view=meetings",
        )
        for item in meeting_rows
    )
    notification_reads.sort(key=lambda item: item.occurred_at, reverse=True)

    return ClientProjectDashboardRead(
        overview=ClientProjectOverviewRead(
            project_id=project.id,
            project_name=project.name,
            description=project.description,
            current_status=_enum_value(project.status),
            overall_health=_health_for_confidence(confidence),
            delivery_confidence=confidence,
            delivery_confidence_label=_confidence_label(confidence),
            current_phase=_current_phase(milestones),
            completion_percentage=completion,
            start_date=project.start_date,
            target_end_date=project.target_end_date,
        ),
        milestones=milestone_reads,
        risks=risk_reads,
        client_actions=action_reads,
        reports=report_reads,
        ai_summary=ai_summary,
        documents=document_reads,
        deliverables=deliverable_reads,
        change_requests=[
            ClientChangeRequestRead.model_validate(item) for item in change_request_rows
        ],
        meetings=meeting_reads,
        notifications=notification_reads[:50],
        generated_at=datetime.now(UTC),
    )


async def create_client_change_request(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    payload: ClientChangeRequestCreate,
) -> ClientChangeRequestRead:
    project = await get_visible_project(session, project_id, current_user)
    title = payload.title.strip()
    description = payload.description.strip()
    if len(title) < 3 or len(description) < 10:
        raise ApiError(422, "VALIDATION_ERROR", "Change request details are incomplete.")

    row = ClientChangeRequest(
        project_id=project.id,
        org_id=project.org_id,
        submitted_by=current_user.id,
        title=title,
        description=description,
        business_justification=(
            payload.business_justification.strip()
            if payload.business_justification and payload.business_justification.strip()
            else None
        ),
        priority=payload.priority,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ClientChangeRequestRead.model_validate(row)
