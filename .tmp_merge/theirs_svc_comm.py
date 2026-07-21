import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.audit.audit_logger import AuditLogger
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
from app.schemas.domain import (
    CommunicationApprove,
    CommunicationDraftEdit,
    CommunicationReject,
    CommunicationReview,
    QualitySummaryRead,
)
from app.services.evidence import (
    EvidenceInput,
    dedupe_evidence_inputs,
    require_complete_evidence_provenance,
)
from app.services.llm.client import LLMClient

COMMS_PLACEHOLDER_BODY = (
    "Draft generation is ready for LLM integration. "
    "This placeholder is evidence-backed and must be reviewed before sending."
)

ERROR_INVALID_TRANSITION = "INVALID_COMMUNICATION_STATUS_TRANSITION"
ERROR_NO_COMMUNICATION_CHANGES = "NO_COMMUNICATION_CHANGES"
ERROR_COMMUNICATION_EVIDENCE_CHANGED = "COMMUNICATION_EVIDENCE_CHANGED"
LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING = "LEGACY_EVIDENCE_FINGERPRINT_MISSING"

# action -> allowed current statuses
_ALLOWED_TRANSITIONS: dict[str, frozenset[CommunicationStatus]] = {
    "edit": frozenset({CommunicationStatus.DRAFT, CommunicationStatus.REJECTED}),
    "submit_for_review": frozenset({CommunicationStatus.DRAFT}),
    "approve": frozenset({CommunicationStatus.IN_REVIEW}),
    "reject": frozenset({CommunicationStatus.IN_REVIEW}),
    "send": frozenset({CommunicationStatus.APPROVED}),
}

_ACTION_TARGET_STATUS: dict[str, CommunicationStatus] = {
    "edit": CommunicationStatus.DRAFT,
    "submit_for_review": CommunicationStatus.IN_REVIEW,
    "approve": CommunicationStatus.APPROVED,
    "reject": CommunicationStatus.REJECTED,
    "send": CommunicationStatus.SENT,
}

_AUDIT_EVENT_BY_ACTION: dict[str, str] = {
    "edit": "client_communication.edited",
    "submit_for_review": "client_communication.submitted_for_review",
    "approve": "client_communication.approved",
    "reject": "client_communication.rejected",
    "send": "client_communication.sent",
}


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
                    {
                        "drift_alert": {
                            "title": alert.title,
                            "detail": alert.detail,
                            "risk_tier": alert.risk_tier.value,
                        }
                    },
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


def _require_transition(
    communication: ClientCommunication,
    action: str,
) -> CommunicationStatus:
    allowed = _ALLOWED_TRANSITIONS.get(action)
    if allowed is None:
        raise ApiError(500, "INTERNAL_ERROR", "Unknown communication lifecycle action.")
    if communication.status not in allowed:
        raise ApiError(
            409,
            ERROR_INVALID_TRANSITION,
            "Communication cannot perform this action from its current status.",
            {
                "communication_id": str(communication.id),
                "current_status": communication.status.value,
                "requested_action": action,
            },
        )
    return _ACTION_TARGET_STATUS[action]


async def _append_lifecycle_audit(
    session: AsyncSession,
    *,
    communication: ClientCommunication,
    actor_id: UUID,
    action: str,
    previous_status: CommunicationStatus,
    new_status: CommunicationStatus,
    changed_fields: list[str] | None = None,
    rejection_reason_recorded: bool = False,
) -> None:
    payload: dict[str, Any] = {
        "communication_id": str(communication.id),
        "project_id": str(communication.project_id),
        "actor_user_id": str(actor_id),
        "previous_status": previous_status.value,
        "new_status": new_status.value,
        "action": action,
    }
    if changed_fields:
        payload["changed_fields"] = changed_fields
    if rejection_reason_recorded:
        payload["rejection_reason_recorded"] = True
    await AuditLogger(session).log(
        event_type=_AUDIT_EVENT_BY_ACTION[action],
        org_id=communication.org_id,
        project_id=communication.project_id,
        payload=payload,
    )


async def create_draft(
    session: AsyncSession,
    project: Project,
    subject: str,
    body_draft: str,
    comm_type: str,
    evidence: list[EvidenceInput],
    *,
    evidence_source_fingerprint: str,
) -> ClientCommunication:
    """Create a Client Intelligence draft with complete governed evidence provenance.

    ``evidence_source_fingerprint`` is required for new drafts. Null fingerprints
    exist only on genuine pre-migration legacy rows and must never be written here.
    """
    if (
        len(evidence_source_fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in evidence_source_fingerprint)
    ):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "evidence_source_fingerprint must be a 64-character lowercase SHA-256 hex digest.",
        )
    deduped = dedupe_evidence_inputs(evidence)
    require_complete_evidence_provenance(deduped)
    for item in deduped:
        if item.pack_source_fingerprint != evidence_source_fingerprint:
            raise ApiError(
                409,
                "EVIDENCE_FINGERPRINT_MISMATCH",
                "Evidence link pack fingerprint must match the communication fingerprint.",
                {
                    "source_table": item.source_table,
                    "source_row_id": str(item.source_row_id),
                },
            )
    communication = ClientCommunication(
        project_id=project.id,
        org_id=project.org_id,
        comm_type=comm_type,
        subject=subject,
        body_draft=body_draft,
        status=CommunicationStatus.DRAFT,
        drafted_by_agent="client_interaction_agent",
        evidence_source_fingerprint=evidence_source_fingerprint,
    )
    session.add(communication)
    await session.flush()
    for item in deduped:
        session.add(
            CommunicationEvidenceLink(
                communication_id=communication.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
                visibility=item.visibility,
                observed_at=item.observed_at,
                claim_keys=list(item.claim_keys or ()),
                pack_source_fingerprint=item.pack_source_fingerprint,
            )
        )
    return communication


async def _current_evidence_fingerprint(
    session: AsyncSession,
    communication: ClientCommunication,
    current_user: CurrentUser,
) -> str:
    from app.agents.client_intelligence.contracts import EvidenceVisibility
    from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack

    pack = await build_client_evidence_pack(
        session,
        current_user,
        communication.project_id,
        visibility_mode=EvidenceVisibility.INTERNAL,
    )
    return pack.source_fingerprint


async def _assert_evidence_fingerprint_for_lifecycle(
    session: AsyncSession,
    communication: ClientCommunication,
    current_user: CurrentUser,
    *,
    action: str,
) -> str | None:
    """Compare stored pack fingerprint to current governed evidence.

    Legacy rows without a fingerprint are disclosed (not fabricated) and allowed
    to proceed. Changed fingerprints block Approve/Send.
    """
    stored = communication.evidence_source_fingerprint
    if not stored:
        return LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING
    current = await _current_evidence_fingerprint(session, communication, current_user)
    if current != stored:
        raise ApiError(
            409,
            ERROR_COMMUNICATION_EVIDENCE_CHANGED,
            (
                "Governed evidence changed after this communication was reviewed. "
                "Regenerate or revise the draft and submit for human review again."
            ),
            {
                "communication_id": str(communication.id),
                "project_id": str(communication.project_id),
                "requested_action": action,
                "stored_evidence_source_fingerprint": stored,
                "current_evidence_source_fingerprint": current,
            },
        )
    return None


async def edit_draft(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationDraftEdit,
    current_user: CurrentUser,
) -> ClientCommunication:
    previous_status = communication.status
    _require_transition(communication, "edit")

    changed_fields: list[str] = []
    if communication.subject != payload.subject:
        changed_fields.append("subject")
    if communication.body_draft != payload.body_draft:
        changed_fields.append("body_draft")

    if previous_status == CommunicationStatus.DRAFT and not changed_fields:
        raise ApiError(
            409,
            ERROR_NO_COMMUNICATION_CHANGES,
            "Draft subject and body are unchanged.",
            {
                "communication_id": str(communication.id),
                "current_status": previous_status.value,
                "requested_action": "edit",
            },
        )

    communication.subject = payload.subject
    communication.body_draft = payload.body_draft
    communication.status = CommunicationStatus.DRAFT

    if previous_status == CommunicationStatus.REJECTED:
        communication.rejection_reason = None
        communication.rejected_by = None
        communication.rejected_at = None
        communication.body_approved = None
        communication.reviewed_by = None
        communication.reviewed_at = None
        communication.approved_by = None
        communication.approved_at = None
        communication.sent_at = None
        for field in (
            "rejection_reason",
            "rejected_by",
            "rejected_at",
            "body_approved",
            "reviewed_by",
            "reviewed_at",
            "approved_by",
            "approved_at",
            "sent_at",
            "status",
        ):
            if field not in changed_fields:
                changed_fields.append(field)

    await _append_lifecycle_audit(
        session,
        communication=communication,
        actor_id=current_user.id,
        action="edit",
        previous_status=previous_status,
        new_status=CommunicationStatus.DRAFT,
        changed_fields=changed_fields,
    )
    await session.flush()
    return communication


async def move_to_review(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationReview,
    current_user: CurrentUser,
) -> ClientCommunication:
    previous_status = communication.status
    _require_transition(communication, "submit_for_review")
    communication.status = CommunicationStatus.IN_REVIEW
    communication.body_approved = payload.body_approved
    communication.reviewed_by = current_user.id
    communication.reviewed_at = datetime.now(UTC)
    communication.approved_by = None
    communication.approved_at = None
    communication.sent_at = None
    communication.rejection_reason = None
    communication.rejected_by = None
    communication.rejected_at = None
    await _append_lifecycle_audit(
        session,
        communication=communication,
        actor_id=current_user.id,
        action="submit_for_review",
        previous_status=previous_status,
        new_status=CommunicationStatus.IN_REVIEW,
    )
    await session.flush()
    return communication


async def approve(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationApprove,
    current_user: CurrentUser,
) -> ClientCommunication:
    previous_status = communication.status
    _require_transition(communication, "approve")
    reviewed = (communication.body_approved or "").strip()
    if not reviewed:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Reviewed body is required before approval.",
            {"communication_id": str(communication.id)},
        )
    if payload.body_approved is not None and payload.body_approved != reviewed:
        raise ApiError(
            409,
            ERROR_INVALID_TRANSITION,
            "Approval cannot replace reviewed content. Edit and resubmit for review.",
            {
                "communication_id": str(communication.id),
                "current_status": previous_status.value,
                "requested_action": "approve",
            },
        )
    fingerprint_limitation = await _assert_evidence_fingerprint_for_lifecycle(
        session,
        communication,
        current_user,
        action="approve",
    )
    communication.status = CommunicationStatus.APPROVED
    communication.approved_by = current_user.id
    communication.approved_at = datetime.now(UTC)
    await _append_lifecycle_audit(
        session,
        communication=communication,
        actor_id=current_user.id,
        action="approve",
        previous_status=previous_status,
        new_status=CommunicationStatus.APPROVED,
        changed_fields=(
            ["evidence_fingerprint_legacy_missing"]
            if fingerprint_limitation == LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING
            else None
        ),
    )
    await session.flush()
    return communication


async def reject(
    session: AsyncSession,
    communication: ClientCommunication,
    payload: CommunicationReject,
    current_user: CurrentUser,
) -> ClientCommunication:
    previous_status = communication.status
    _require_transition(communication, "reject")
    communication.status = CommunicationStatus.REJECTED
    communication.rejection_reason = payload.rejection_reason
    communication.rejected_by = current_user.id
    communication.rejected_at = datetime.now(UTC)
    communication.approved_by = None
    communication.approved_at = None
    communication.sent_at = None
    await _append_lifecycle_audit(
        session,
        communication=communication,
        actor_id=current_user.id,
        action="reject",
        previous_status=previous_status,
        new_status=CommunicationStatus.REJECTED,
        rejection_reason_recorded=True,
    )
    await session.flush()
    return communication


async def send(
    session: AsyncSession,
    communication: ClientCommunication,
    current_user: CurrentUser,
) -> ClientCommunication:
    previous_status = communication.status
    _require_transition(communication, "send")
    if (
        communication.approved_by is None
        or communication.approved_at is None
        or not (communication.body_approved or "").strip()
    ):
        raise ApiError(
            409,
            "COMMUNICATION_APPROVAL_REQUIRED",
            "Communication must be fully approved before it can be sent.",
            {"communication_id": str(communication.id)},
        )
    fingerprint_limitation = await _assert_evidence_fingerprint_for_lifecycle(
        session,
        communication,
        current_user,
        action="send",
    )
    communication.status = CommunicationStatus.SENT
    communication.sent_at = datetime.now(UTC)
    await _append_lifecycle_audit(
        session,
        communication=communication,
        actor_id=current_user.id,
        action="send",
        previous_status=previous_status,
        new_status=CommunicationStatus.SENT,
        changed_fields=(
            ["evidence_fingerprint_legacy_missing"]
            if fingerprint_limitation == LIMITATION_LEGACY_EVIDENCE_FINGERPRINT_MISSING
            else None
        ),
    )
    await session.flush()
    return communication
