from datetime import datetime, timezone
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.quality_intelligence.comms_prompts import COMMS_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, can_read_all_orgs
from app.db.models import (
    AppRole,
    ClientCommunication,
    CommunicationEvidenceLink,
    CommunicationStatus,
    CommunicationType,
    Project,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
)
from app.schemas.domain import CommunicationApprove, CommunicationReview, QualitySummaryRead
from app.services.evidence import EvidenceInput, require_evidence
from app.services.llm.client import LLMClient

COMMS_PLACEHOLDER_BODY = (
    "Draft generation is ready for LLM integration. "
    "This placeholder is evidence-backed and must be reviewed before sending."
)


def build_comms_context(
    throughput_snap: ThroughputSnapshot,
    quality_summary: QualitySummaryRead | None = None,
    *,
    quality_snaps: list[QualitySnapshot] | None = None,
    drift_alerts: list[RiskAlert] | None = None,
) -> str:
    parts: list[str] = [
        json.dumps(
            {
                "throughput": {
                    "snapshot_date": str(throughput_snap.snapshot_date),
                    "units_completed": throughput_snap.units_completed,
                    "units_forecast": throughput_snap.units_forecast,
                    "rolling_7day_units": throughput_snap.rolling_7day_units,
                }
            },
            default=str,
        )
    ]
    if quality_summary is not None:
        parts.append(
            json.dumps(
                {
                    "quality_summary": quality_summary.model_dump(mode="json"),
                },
                default=str,
            )
        )
    else:
        for snap in quality_snaps or []:
            parts.append(
                json.dumps(
                    {
                        "quality_snapshot": {
                            "iso_week": snap.iso_week,
                            "iso_year": snap.iso_year,
                            "gold_set_accuracy_pct": str(snap.gold_set_accuracy_pct),
                            "iaa": str(snap.iaa_krippendorff_alpha),
                            "rework_rate_pct": str(snap.rework_rate_pct),
                            "has_drift_alert": snap.has_drift_alert,
                        }
                    },
                    default=str,
                )
            )
        for alert in drift_alerts or []:
            parts.append(
                json.dumps(
                    {"drift_alert": {"title": alert.title, "detail": alert.detail, "risk_tier": alert.risk_tier.value}},
                    default=str,
                )
            )
    return "\n".join(parts)


async def generate_comms_draft_body(
    project: Project,
    throughput_snap: ThroughputSnapshot,
    comm_type: CommunicationType | str,
    *,
    quality_summary: QualitySummaryRead | None = None,
    quality_snaps: list[QualitySnapshot] | None = None,
    drift_alerts: list[RiskAlert] | None = None,
) -> str:
    settings = get_settings()
    if not settings.llm_api_key:
        return COMMS_PLACEHOLDER_BODY

    context = build_comms_context(
        throughput_snap,
        quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
    )
    comm_label = comm_type.value if hasattr(comm_type, "value") else str(comm_type)
    try:
        llm = LLMClient()
        return await llm.generate_structured(
            system=COMMS_SYSTEM_PROMPT,
            user=f"Write a {comm_label} for project '{project.name}'.",
            context=context,
        )
    except ApiError:
        return COMMS_PLACEHOLDER_BODY


async def get_visible_communication(
    session: AsyncSession,
    communication_id: UUID,
    current_user: CurrentUser,
) -> ClientCommunication:
    query = select(ClientCommunication).where(ClientCommunication.id == communication_id)
    if current_user.role == AppRole.CLIENT:
        query = query.where(
            ClientCommunication.org_id == current_user.org_id,
            ClientCommunication.status == CommunicationStatus.SENT,
        )
    elif not can_read_all_orgs(current_user.role):
        query = query.where(ClientCommunication.org_id == current_user.org_id)

    communication = (await session.execute(query)).scalar_one_or_none()
    if communication is None:
        raise ApiError(404, "NOT_FOUND", "Communication was not found.")
    return communication


async def create_draft(
    session: AsyncSession,
    project: Project,
    subject: str,
    body_draft: str,
    comm_type: str,
    evidence: list[EvidenceInput],
) -> ClientCommunication:
    require_evidence(evidence)
    communication = ClientCommunication(
        project_id=project.id,
        org_id=project.org_id,
        comm_type=comm_type,
        subject=subject,
        body_draft=body_draft,
        status=CommunicationStatus.DRAFT,
        drafted_by_agent="client_interaction_agent",
    )
    session.add(communication)
    await session.flush()
    for item in evidence:
        session.add(
            CommunicationEvidenceLink(
                communication_id=communication.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
        )
    return communication


async def move_to_review(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationReview,
    current_user: CurrentUser,
) -> ClientCommunication:
    if communication.status not in {CommunicationStatus.DRAFT, CommunicationStatus.IN_REVIEW}:
        raise ApiError(400, "INVALID_STATUS_TRANSITION", "Communication cannot move to review from its current state.")
    communication.status = CommunicationStatus.IN_REVIEW
    communication.body_approved = payload.body_approved
    communication.reviewed_by = current_user.id
    communication.reviewed_at = datetime.now(timezone.utc)
    await session.flush()
    return communication


async def approve(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationApprove,
    current_user: CurrentUser,
) -> ClientCommunication:
    body_approved = payload.body_approved or communication.body_approved
    if not body_approved:
        raise ApiError(400, "VALIDATION_ERROR", "Approved body is required.")
    communication.body_approved = body_approved
    communication.status = CommunicationStatus.APPROVED
    communication.approved_by = current_user.id
    communication.approved_at = datetime.now(timezone.utc)
    await session.flush()
    return communication


async def reject(session: AsyncSession, communication: ClientCommunication) -> ClientCommunication:
    communication.status = CommunicationStatus.REJECTED
    await session.flush()
    return communication


async def send(session: AsyncSession, communication: ClientCommunication) -> ClientCommunication:
    if communication.status != CommunicationStatus.APPROVED or communication.approved_by is None:
        raise ApiError(
            409,
            "COMMUNICATION_APPROVAL_REQUIRED",
            "Communication must be approved before it can be sent.",
            {"communication_id": str(communication.id)},
        )
    communication.status = CommunicationStatus.SENT
    communication.sent_at = datetime.now(timezone.utc)
    await session.flush()
    return communication
