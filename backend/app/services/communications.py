import json
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, func, select
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
    Organisation,
    Program,
    Project,
    ProjectAssignment,
    QualitySnapshot,
    RiskAlert,
    ThroughputSnapshot,
)
from app.schemas.domain import (
    CommunicationApprove,
    CommunicationDraftEdit,
    CommunicationListItem,
    CommunicationRead,
    CommunicationReject,
    CommunicationReview,
    QualitySummaryRead,
)
from app.services.evidence import (
    EvidenceInput,
    dedupe_evidence_inputs,
    require_complete_evidence_provenance,
    require_evidence,
)
from app.services.llm.client import LLMClient
from app.services.scoping import get_visible_project

COMMS_PLACEHOLDER_BODY = (
    "Draft generation is ready for LLM integration. "
    "This placeholder is evidence-backed and must be reviewed before sending."
)

GENERATION_FALLBACK_WARNING = (
    "The AI provider was unavailable. A temporary evidence-backed draft was created."
)

COMMUNICATIONS_LIST_DEFAULT_LIMIT = 30
COMMUNICATIONS_LIST_MAX_LIMIT = 100


@dataclass(frozen=True)
class CommunicationsListPage:
    items: list[CommunicationListItem]
    total: int
    limit: int
    offset: int
    db_ms: float


@dataclass
class DraftGenerationTimings:
    authorization_ms: float = 0.0
    evidence_query_ms: float = 0.0
    quality_summary_ms: float = 0.0
    prompt_build_ms: float = 0.0
    llm_ms: float = 0.0
    persist_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class DraftEvidenceBundle:
    evidence: list[EvidenceInput]
    throughput: ThroughputSnapshot
    quality_summary: QualitySummaryRead | None = None
    quality_snaps: list[QualitySnapshot] | None = None
    drift_alerts: list[RiskAlert] | None = None
    open_risks: list[RiskAlert] | None = None
    milestones: list[object] | None = None
    delivery_confidence: object | None = None
    quality_summary_ms: float = 0.0
    evidence_query_ms: float = 0.0


@dataclass
class DraftGenerationResult:
    communication: ClientCommunication
    generation_mode: str
    generation_warning: str | None
    timings: DraftGenerationTimings
    evidence_link_count: int


def bound_communications_list_limit(limit: int | None) -> int:
    if limit is None:
        return COMMUNICATIONS_LIST_DEFAULT_LIMIT
    return max(1, min(int(limit), COMMUNICATIONS_LIST_MAX_LIMIT))


def bound_communications_list_offset(offset: int | None) -> int:
    if offset is None or offset < 0:
        return 0
    return int(offset)


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
    open_risks: list[RiskAlert] | None = None,
    milestones: list[object] | None = None,
    delivery_confidence: object | None = None,
    instructions: str | None = None,
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
    if delivery_confidence is not None:
        parts.append(
            json.dumps(
                {
                    "delivery_confidence": {
                        "score_pct": str(getattr(delivery_confidence, "score_pct", None)),
                        "status": str(getattr(getattr(delivery_confidence, "status", None), "value", getattr(delivery_confidence, "status", None))),
                        "forecast_completion_date": str(
                            getattr(delivery_confidence, "forecast_completion_date", None)
                        ),
                    }
                },
                default=str,
            )
        )
    for milestone in milestones or []:
        parts.append(
            json.dumps(
                {
                    "milestone": {
                        "name": getattr(milestone, "name", None),
                        "status": str(
                            getattr(getattr(milestone, "status", None), "value", getattr(milestone, "status", None))
                        ),
                        "planned_date": str(getattr(milestone, "planned_date", None)),
                    }
                },
                default=str,
            )
        )
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
    for alert in open_risks or []:
        parts.append(
            json.dumps(
                {
                    "risk_alert": {
                        "title": alert.title,
                        "detail": alert.detail,
                        "risk_tier": alert.risk_tier.value,
                        "alert_type": alert.alert_type.value,
                    }
                },
                default=str,
            )
        )
    if instructions and instructions.strip():
        parts.append(json.dumps({"pm_instructions": instructions.strip()}, default=str))
    return "\n".join(parts)


def build_comms_user_prompt(
    *,
    project_name: str,
    comm_type: CommunicationType | str,
    instructions: str | None,
    max_words: int,
) -> str:
    comm_label = comm_type.value if hasattr(comm_type, "value") else str(comm_type)
    guidance = (instructions or "").strip() or "None provided."
    return (
        f'Write a {comm_label} for project "{project_name}".\n'
        f"Use only the supplied evidence.\n"
        f"Keep the report under {max_words} words.\n"
        f"Do not invent metrics. Distinguish confirmed facts from risks or estimates.\n"
        f"Use a professional client-facing tone.\n"
        f"PM guidance: {guidance}"
    )


def build_fallback_body(
    project: Project,
    throughput_snap: ThroughputSnapshot,
    *,
    comm_type: CommunicationType | str | None = None,
    open_risks: list[RiskAlert] | None = None,
    milestones: list[object] | None = None,
    instructions: str | None = None,
) -> str:
    """Client-facing evidence-backed draft when the LLM is unavailable.

    Produces structured Markdown suitable for DeliveryMarkdown preview — not a
    raw concatenated status dump.
    """
    type_value = comm_type.value if hasattr(comm_type, "value") else str(comm_type or "weekly_summary")
    heading = {
        "weekly_summary": "Weekly delivery summary",
        "executive_summary": "Executive summary",
        "ad_hoc": "Project update",
    }.get(type_value, "Project update")

    completed = throughput_snap.units_completed
    forecast = throughput_snap.units_forecast
    snap_date = throughput_snap.snapshot_date
    if forecast is not None and forecast > 0:
        delta = completed - forecast
        if delta >= 0:
            throughput_line = (
                f"As of {snap_date}, delivery completed **{completed}** units against a forecast of "
                f"**{forecast}** ({delta} above plan)."
            )
        else:
            throughput_line = (
                f"As of {snap_date}, delivery completed **{completed}** units against a forecast of "
                f"**{forecast}** ({abs(delta)} below plan)."
            )
    else:
        throughput_line = f"As of {snap_date}, delivery completed **{completed}** units."

    sections: list[str] = [
        f"## {heading} — {project.name}",
        "",
        "### Delivery posture",
        throughput_line,
    ]

    if milestones:
        sections.append("")
        sections.append("### Milestones")
        for milestone in milestones[:3]:
            name = str(getattr(milestone, "name", "Milestone"))
            status = getattr(getattr(milestone, "status", None), "value", getattr(milestone, "status", None))
            status_label = str(status).replace("_", " ") if status else "in focus"
            sections.append(f"- **{name}** — {status_label}")

    sections.append("")
    sections.append("### Risks")
    if open_risks:
        for alert in open_risks[:2]:
            sections.append(f"- {alert.title}")
    else:
        sections.append("- No open delivery risks were attached to this draft.")

    if instructions and instructions.strip():
        sections.append("")
        sections.append("### PM guidance reflected")
        sections.append(instructions.strip()[:240])

    sections.append("")
    sections.append(
        "_Evidence-backed draft for Delivery Manager review. Please edit before approval and send._"
    )
    return "\n".join(sections)


def build_comms_prompt_parts(
    project: Project,
    throughput_snap: ThroughputSnapshot,
    comm_type: CommunicationType | str,
    *,
    instructions: str | None = None,
    quality_summary: QualitySummaryRead | None = None,
    quality_snaps: list[QualitySnapshot] | None = None,
    drift_alerts: list[RiskAlert] | None = None,
    open_risks: list[RiskAlert] | None = None,
    milestones: list[object] | None = None,
    delivery_confidence: object | None = None,
) -> tuple[str, str]:
    """Return (context, user_prompt) for tests and generation."""
    settings = get_settings()
    max_words = settings.communications_max_body_words
    context = build_comms_context(
        throughput_snap,
        quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
        open_risks=open_risks,
        milestones=milestones,
        delivery_confidence=delivery_confidence,
        instructions=instructions,
    )
    user_prompt = build_comms_user_prompt(
        project_name=project.name,
        comm_type=comm_type,
        instructions=instructions,
        max_words=max_words,
    )
    return context, user_prompt


async def generate_comms_draft_body(
    project: Project,
    throughput_snap: ThroughputSnapshot,
    comm_type: CommunicationType | str,
    *,
    quality_summary: QualitySummaryRead | None = None,
    quality_snaps: list[QualitySnapshot] | None = None,
    drift_alerts: list[RiskAlert] | None = None,
    open_risks: list[RiskAlert] | None = None,
    milestones: list[object] | None = None,
    delivery_confidence: object | None = None,
    instructions: str | None = None,
) -> tuple[str, str, str | None, float]:
    """Generate draft body. Returns (body, generation_mode, warning, llm_ms)."""
    settings = get_settings()
    context, user_prompt = build_comms_prompt_parts(
        project,
        throughput_snap,
        comm_type,
        instructions=instructions,
        quality_summary=quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
        open_risks=open_risks,
        milestones=milestones,
        delivery_confidence=delivery_confidence,
    )

    api_key = settings.openai_api_key or settings.llm_api_key
    if not api_key:
        body = build_fallback_body(
            project,
            throughput_snap,
            comm_type=comm_type,
            open_risks=open_risks,
            milestones=milestones,
            instructions=instructions,
        )
        return body, "fallback", GENERATION_FALLBACK_WARNING, 0.0

    model = settings.communications_llm_model or settings.openai_model or settings.llm_model or "gpt-4o-mini"
    timeout = settings.communications_llm_timeout_seconds
    max_tokens = settings.communications_llm_max_tokens
    llm_started = perf_counter()
    try:
        llm = LLMClient()
        body = await llm.generate_structured(
            system=COMMS_SYSTEM_PROMPT,
            user=user_prompt,
            context=context,
            model=model,
            max_tokens=max_tokens,
            timeout_seconds=timeout,
        )
        llm_ms = (perf_counter() - llm_started) * 1000
        cleaned = (body or "").strip()
        if cleaned:
            return cleaned, "ai", None, llm_ms
        fallback = build_fallback_body(
            project,
            throughput_snap,
            comm_type=comm_type,
            open_risks=open_risks,
            milestones=milestones,
            instructions=instructions,
        )
        return fallback, "fallback", GENERATION_FALLBACK_WARNING, llm_ms
    except (ApiError, TimeoutError, Exception):
        llm_ms = (perf_counter() - llm_started) * 1000
        body = build_fallback_body(
            project,
            throughput_snap,
            comm_type=comm_type,
            open_risks=open_risks,
            milestones=milestones,
            instructions=instructions,
        )
        return body, "fallback", GENERATION_FALLBACK_WARNING, llm_ms


async def gather_draft_evidence(
    session: AsyncSession,
    project: Project,
    comm_type: CommunicationType,
    current_user: CurrentUser,
) -> DraftEvidenceBundle:
    """Sequential evidence reads on a shared session (no concurrent session use)."""
    from app.db.models import (
        AlertStatus,
        AlertType,
        DeliveryConfidenceScore,
        Milestone,
        MilestoneStatus,
    )
    from app.services.quality import generate_quality_summary

    evidence_started = perf_counter()
    latest_throughput = (
        await session.execute(
            select(ThroughputSnapshot)
            .where(ThroughputSnapshot.project_id == project.id)
            .order_by(ThroughputSnapshot.snapshot_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_throughput is None:
        raise ApiError(409, "EVIDENCE_REQUIRED", "Communication draft requires at least one evidence row.")

    evidence: list[EvidenceInput] = [
        EvidenceInput(
            source_table="throughput_snapshots",
            source_row_id=latest_throughput.id,
            description="Latest throughput snapshot for communication grounding.",
        )
    ]
    quality_snaps: list[QualitySnapshot] = []
    drift_alerts: list[RiskAlert] = []
    open_risks: list[RiskAlert] = []
    milestones: list[object] = []
    delivery_confidence = None
    quality_summary = None
    quality_summary_ms = 0.0

    open_statuses = [AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]

    if comm_type == CommunicationType.WEEKLY_SUMMARY:
        milestones = list(
            (
                await session.execute(
                    select(Milestone)
                    .where(
                        Milestone.project_id == project.id,
                        Milestone.deleted_at.is_(None),
                        Milestone.status.in_(
                            [MilestoneStatus.PENDING, MilestoneStatus.ON_TRACK, MilestoneStatus.AT_RISK]
                        ),
                    )
                    .order_by(Milestone.planned_date.asc())
                    .limit(5)
                )
            ).scalars()
        )
        for milestone in milestones:
            evidence.append(
                EvidenceInput(
                    source_table="milestones",
                    source_row_id=milestone.id,
                    description=f"Milestone '{milestone.name}' ({milestone.status.value}).",
                )
            )

        open_risks = list(
            (
                await session.execute(
                    select(RiskAlert)
                    .where(
                        RiskAlert.project_id == project.id,
                        RiskAlert.deleted_at.is_(None),
                        RiskAlert.status.in_(open_statuses),
                    )
                    .order_by(RiskAlert.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )
        for alert in open_risks:
            evidence.append(
                EvidenceInput(
                    source_table="risk_alerts",
                    source_row_id=alert.id,
                    description=f"Open risk: {alert.title}",
                )
            )

        qs_started = perf_counter()
        now = datetime.now(timezone.utc)
        iso_year, iso_week, _ = now.isocalendar()
        quality_summary = await generate_quality_summary(session, project, iso_year, iso_week, current_user)
        quality_summary_ms = (perf_counter() - qs_started) * 1000
        evidence.append(
            EvidenceInput(
                source_table="quality_summaries",
                source_row_id=project.id,
                description=f"Sanitized quality summary W{iso_week}/{iso_year}.",
            )
        )

        quality_snaps = list(
            (
                await session.execute(
                    select(QualitySnapshot)
                    .where(QualitySnapshot.project_id == project.id)
                    .order_by(QualitySnapshot.iso_year.desc(), QualitySnapshot.iso_week.desc())
                    .limit(10)
                )
            ).scalars()
        )
        seen_teams: set[UUID] = set()
        deduped: list[QualitySnapshot] = []
        for snap in quality_snaps:
            if snap.team_id not in seen_teams:
                seen_teams.add(snap.team_id)
                deduped.append(snap)
                evidence.append(
                    EvidenceInput(
                        source_table="quality_snapshots",
                        source_row_id=snap.id,
                        description=f"Quality snapshot W{snap.iso_week}/{snap.iso_year} for team {snap.team_id}.",
                    )
                )
        quality_snaps = deduped

        drift_alerts = list(
            (
                await session.execute(
                    select(RiskAlert)
                    .where(
                        RiskAlert.project_id == project.id,
                        RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                        RiskAlert.deleted_at.is_(None),
                        RiskAlert.status.in_(open_statuses),
                    )
                    .order_by(RiskAlert.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )
        for alert in drift_alerts:
            evidence.append(
                EvidenceInput(
                    source_table="risk_alerts",
                    source_row_id=alert.id,
                    description=f"Open quality drift alert: {alert.title}",
                )
            )

    elif comm_type == CommunicationType.EXECUTIVE_SUMMARY:
        delivery_confidence = (
            await session.execute(
                select(DeliveryConfidenceScore)
                .where(DeliveryConfidenceScore.project_id == project.id)
                .order_by(DeliveryConfidenceScore.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if delivery_confidence is not None:
            evidence.append(
                EvidenceInput(
                    source_table="delivery_confidence_scores",
                    source_row_id=delivery_confidence.id,
                    description="Latest delivery confidence score.",
                )
            )

        open_risks = list(
            (
                await session.execute(
                    select(RiskAlert)
                    .where(
                        RiskAlert.project_id == project.id,
                        RiskAlert.deleted_at.is_(None),
                        RiskAlert.status.in_(open_statuses),
                    )
                    .order_by(RiskAlert.created_at.desc())
                    .limit(2)
                )
            ).scalars()
        )
        for alert in open_risks:
            evidence.append(
                EvidenceInput(
                    source_table="risk_alerts",
                    source_row_id=alert.id,
                    description=f"Top open risk: {alert.title}",
                )
            )

        milestones = list(
            (
                await session.execute(
                    select(Milestone)
                    .where(
                        Milestone.project_id == project.id,
                        Milestone.deleted_at.is_(None),
                        Milestone.status.in_([MilestoneStatus.ON_TRACK, MilestoneStatus.AT_RISK, MilestoneStatus.PENDING]),
                    )
                    .order_by(Milestone.planned_date.asc())
                    .limit(3)
                )
            ).scalars()
        )
        for milestone in milestones:
            evidence.append(
                EvidenceInput(
                    source_table="milestones",
                    source_row_id=milestone.id,
                    description=f"Key milestone '{milestone.name}' ({milestone.status.value}).",
                )
            )

        # Material quality signal only when drift is open.
        drift_alerts = list(
            (
                await session.execute(
                    select(RiskAlert)
                    .where(
                        RiskAlert.project_id == project.id,
                        RiskAlert.alert_type == AlertType.QUALITY_DRIFT,
                        RiskAlert.deleted_at.is_(None),
                        RiskAlert.status.in_(open_statuses),
                    )
                    .order_by(RiskAlert.created_at.desc())
                    .limit(1)
                )
            ).scalars()
        )
        for alert in drift_alerts:
            evidence.append(
                EvidenceInput(
                    source_table="risk_alerts",
                    source_row_id=alert.id,
                    description=f"Material quality drift: {alert.title}",
                )
            )

    else:  # AD_HOC
        open_risks = list(
            (
                await session.execute(
                    select(RiskAlert)
                    .where(
                        RiskAlert.project_id == project.id,
                        RiskAlert.deleted_at.is_(None),
                        RiskAlert.status.in_(open_statuses),
                    )
                    .order_by(RiskAlert.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )
        for alert in open_risks:
            evidence.append(
                EvidenceInput(
                    source_table="risk_alerts",
                    source_row_id=alert.id,
                    description=f"Current risk: {alert.title}",
                )
            )

    evidence_query_ms = (perf_counter() - evidence_started) * 1000 - quality_summary_ms
    return DraftEvidenceBundle(
        evidence=evidence,
        throughput=latest_throughput,
        quality_summary=quality_summary,
        quality_snaps=quality_snaps,
        drift_alerts=drift_alerts,
        open_risks=open_risks,
        milestones=milestones,
        delivery_confidence=delivery_confidence,
        quality_summary_ms=quality_summary_ms,
        evidence_query_ms=max(evidence_query_ms, 0.0),
    )


async def get_visible_communication(
    session: AsyncSession,
    communication_id: UUID,
    current_user: CurrentUser,
) -> ClientCommunication:
    query = select(ClientCommunication).where(ClientCommunication.id == communication_id)
    if current_user.role == AppRole.CLIENT:
        assignment_exists = (
            select(ProjectAssignment.id)
            .where(
                ProjectAssignment.project_id == ClientCommunication.project_id,
                ProjectAssignment.user_id == current_user.id,
                ProjectAssignment.is_active.is_(True),
                ProjectAssignment.deleted_at.is_(None),
            )
            .correlate(ClientCommunication)
        )
        query = query.where(
            ClientCommunication.org_id == current_user.org_id,
            ClientCommunication.status == CommunicationStatus.SENT,
            exists(assignment_exists),
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
    evidence_source_fingerprint: str | None = None,
    generation_mode: str | None = None,
    generation_warning: str | None = None,
) -> ClientCommunication:
    """Create a communication draft.

    When ``evidence_source_fingerprint`` is provided, the draft is a governed
    Client Intelligence draft with complete evidence provenance (fail closed).
    When omitted, the draft follows the legacy generation pipeline path and only
    requires at least one evidence row.
    """
    if evidence_source_fingerprint is not None:
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
    else:
        require_evidence(evidence)
        deduped = evidence
    communication = ClientCommunication(
        project_id=project.id,
        org_id=project.org_id,
        comm_type=comm_type,
        subject=subject,
        body_draft=body_draft,
        status=CommunicationStatus.DRAFT,
        drafted_by_agent="client_interaction_agent",
        evidence_source_fingerprint=evidence_source_fingerprint,
        generation_mode=generation_mode,
        generation_warning=generation_warning,
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


async def create_communication_draft(
    session: AsyncSession,
    project: Project,
    *,
    subject: str,
    comm_type: CommunicationType,
    instructions: str | None,
    current_user: CurrentUser,
    authorization_ms: float = 0.0,
) -> DraftGenerationResult:
    """End-to-end synchronous draft: evidence → LLM/fallback → persist. Never auto-approves/sends."""
    total_started = perf_counter()
    timings = DraftGenerationTimings(authorization_ms=authorization_ms)

    bundle = await gather_draft_evidence(session, project, comm_type, current_user)
    timings.evidence_query_ms = bundle.evidence_query_ms
    timings.quality_summary_ms = bundle.quality_summary_ms

    prompt_started = perf_counter()
    _context, _user = build_comms_prompt_parts(
        project,
        bundle.throughput,
        comm_type,
        instructions=instructions,
        quality_summary=bundle.quality_summary,
        quality_snaps=bundle.quality_snaps,
        drift_alerts=bundle.drift_alerts,
        open_risks=bundle.open_risks,
        milestones=bundle.milestones,
        delivery_confidence=bundle.delivery_confidence,
    )
    timings.prompt_build_ms = (perf_counter() - prompt_started) * 1000

    body, generation_mode, generation_warning, llm_ms = await generate_comms_draft_body(
        project,
        bundle.throughput,
        comm_type,
        quality_summary=bundle.quality_summary,
        quality_snaps=bundle.quality_snaps,
        drift_alerts=bundle.drift_alerts,
        open_risks=bundle.open_risks,
        milestones=bundle.milestones,
        delivery_confidence=bundle.delivery_confidence,
        instructions=instructions,
    )
    timings.llm_ms = llm_ms

    persist_started = perf_counter()
    try:
        communication = await create_draft(
            session,
            project,
            subject.strip(),
            body,
            comm_type,
            bundle.evidence,
            generation_mode=generation_mode,
            generation_warning=generation_warning,
        )
        await session.commit()
        await session.refresh(communication)
    except Exception as exc:
        await session.rollback()
        raise ApiError(503, "COMMUNICATION_GENERATION_FAILED", "Report generation failed.") from exc
    timings.persist_ms = (perf_counter() - persist_started) * 1000
    timings.total_ms = (perf_counter() - total_started) * 1000

    return DraftGenerationResult(
        communication=communication,
        generation_mode=generation_mode,
        generation_warning=generation_warning,
        timings=timings,
        evidence_link_count=len(bundle.evidence),
    )


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
    """Submit edited content for review (draft → in_review).

    Writes the working body into `body_approved` and sets status to `in_review`.
    This is not a silent draft-only save — use `update_communication_content` for that.
    """
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


async def update_communication_content(
    session: AsyncSession,
    communication: ClientCommunication,
    *,
    subject: str | None,
    body: str | None,
) -> ClientCommunication:
    """Edit subject/body without a status transition. Allowed for draft and in_review only.

    - draft: updates `body_draft`
    - in_review: updates `body_approved` (working reviewed body); also keeps `body_draft` in sync
      when body_approved was empty
    """
    if communication.status not in {CommunicationStatus.DRAFT, CommunicationStatus.IN_REVIEW}:
        raise ApiError(
            409,
            "INVALID_COMMUNICATION_TRANSITION",
            "Communication content cannot be edited in its current state.",
            {"communication_id": str(communication.id), "status": communication.status.value},
        )
    if subject is None and body is None:
        raise ApiError(400, "VALIDATION_ERROR", "Provide subject and/or body to update.")

    if subject is not None:
        cleaned_subject = subject.strip()
        if not cleaned_subject:
            raise ApiError(400, "VALIDATION_ERROR", "Subject cannot be empty.")
        communication.subject = cleaned_subject

    if body is not None:
        cleaned_body = body.strip()
        if not cleaned_body:
            raise ApiError(400, "VALIDATION_ERROR", "Body cannot be empty.")
        if communication.status == CommunicationStatus.DRAFT:
            communication.body_draft = cleaned_body
        else:
            # in_review — edit the working approved body shown to reviewers
            communication.body_approved = cleaned_body

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
    # Idempotent: already visible to clients.
    if communication.status == CommunicationStatus.SENT and communication.sent_at is not None:
        return communication
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


def _evidence_count_subquery():
    return (
        select(
            CommunicationEvidenceLink.communication_id.label("communication_id"),
            func.count().label("evidence_link_count"),
        )
        .group_by(CommunicationEvidenceLink.communication_id)
        .subquery()
    )


def _apply_communications_list_scope(
    stmt: Select,
    current_user: CurrentUser,
    *,
    status: CommunicationStatus | None,
    project_id: UUID | None,
) -> Select:
    """Org/project visibility + optional filters. Clients are rejected at the route layer."""
    stmt = stmt.where(Project.deleted_at.is_(None))
    if not can_read_all_orgs(current_user.role):
        stmt = stmt.where(ClientCommunication.org_id == current_user.org_id)
    if status is not None:
        stmt = stmt.where(ClientCommunication.status == status)
    if project_id is not None:
        stmt = stmt.where(ClientCommunication.project_id == project_id)
    return stmt


def build_communications_list_stmt(
    current_user: CurrentUser,
    *,
    status: CommunicationStatus | None = None,
    project_id: UUID | None = None,
    limit: int = COMMUNICATIONS_LIST_DEFAULT_LIMIT,
    offset: int = 0,
) -> Select:
    """Single lightweight list query: project/program names + evidence counts, no bodies."""
    evidence_counts = _evidence_count_subquery()
    stmt = (
        select(
            ClientCommunication.id,
            ClientCommunication.project_id,
            Project.name.label("project_name"),
            Project.program_id.label("program_id"),
            Program.name.label("program_name"),
            Project.org_id.label("org_id"),
            Organisation.name.label("org_name"),
            ClientCommunication.comm_type,
            ClientCommunication.subject,
            ClientCommunication.status,
            ClientCommunication.created_at,
            ClientCommunication.updated_at,
            ClientCommunication.sent_at,
            func.coalesce(evidence_counts.c.evidence_link_count, 0).label("evidence_link_count"),
        )
        .join(Project, Project.id == ClientCommunication.project_id)
        .join(Organisation, Organisation.id == Project.org_id)
        .outerjoin(
            Program,
            (Program.id == Project.program_id) & Program.deleted_at.is_(None),
        )
        .outerjoin(
            evidence_counts,
            evidence_counts.c.communication_id == ClientCommunication.id,
        )
    )
    stmt = _apply_communications_list_scope(
        stmt, current_user, status=status, project_id=project_id
    )
    return (
        stmt.order_by(ClientCommunication.created_at.desc(), ClientCommunication.id.desc())
        .limit(limit)
        .offset(offset)
    )


def build_communications_list_count_stmt(
    current_user: CurrentUser,
    *,
    status: CommunicationStatus | None = None,
    project_id: UUID | None = None,
) -> Select:
    stmt = (
        select(func.count())
        .select_from(ClientCommunication)
        .join(Project, Project.id == ClientCommunication.project_id)
    )
    return _apply_communications_list_scope(
        stmt, current_user, status=status, project_id=project_id
    )


def _row_to_list_item(row) -> CommunicationListItem:
    return CommunicationListItem(
        id=row.id,
        project_id=row.project_id,
        project_name=row.project_name,
        program_id=getattr(row, "program_id", None),
        program_name=getattr(row, "program_name", None),
        org_id=row.org_id,
        org_name=row.org_name,
        comm_type=row.comm_type,
        subject=row.subject,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sent_at=row.sent_at,
        evidence_link_count=int(row.evidence_link_count or 0),
    )


async def list_client_sent_communications(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> CommunicationsListPage:
    """Org-scoped client archive: sent communications only. Never returns drafts/approved/etc.

    Exactly two DB executes (count + page). Ignores any caller desire for other statuses.
    Evidence counts are zeroed for clients (no internal evidence metadata in the archive list).
    """
    if current_user.role != AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    bounded_limit = bound_communications_list_limit(limit)
    bounded_offset = bound_communications_list_offset(offset)

    assignment_exists = (
        select(ProjectAssignment.id)
        .where(
            ProjectAssignment.project_id == ClientCommunication.project_id,
            ProjectAssignment.user_id == current_user.id,
            ProjectAssignment.is_active.is_(True),
            ProjectAssignment.deleted_at.is_(None),
        )
        .correlate(ClientCommunication)
    )
    visibility = (
        Project.deleted_at.is_(None),
        ClientCommunication.org_id == current_user.org_id,
        ClientCommunication.status == CommunicationStatus.SENT,
        exists(assignment_exists),
    )

    list_stmt = (
        select(
            ClientCommunication.id,
            ClientCommunication.project_id,
            Project.name.label("project_name"),
            Project.program_id.label("program_id"),
            Program.name.label("program_name"),
            Project.org_id.label("org_id"),
            Organisation.name.label("org_name"),
            ClientCommunication.comm_type,
            ClientCommunication.subject,
            ClientCommunication.status,
            ClientCommunication.created_at,
            ClientCommunication.updated_at,
            ClientCommunication.sent_at,
        )
        .join(Project, Project.id == ClientCommunication.project_id)
        .join(Organisation, Organisation.id == Project.org_id)
        .outerjoin(
            Program,
            (Program.id == Project.program_id) & Program.deleted_at.is_(None),
        )
        .where(*visibility)
        .order_by(
            ClientCommunication.sent_at.desc().nullslast(),
            ClientCommunication.created_at.desc(),
            ClientCommunication.id.desc(),
        )
        .limit(bounded_limit)
        .offset(bounded_offset)
    )
    count_stmt = (
        select(func.count())
        .select_from(ClientCommunication)
        .join(Project, Project.id == ClientCommunication.project_id)
        .where(*visibility)
    )

    db_started = perf_counter()
    rows = list((await session.execute(list_stmt)).all())
    total = int((await session.execute(count_stmt)).scalar_one_or_none() or 0)
    db_ms = (perf_counter() - db_started) * 1000

    items = [
        CommunicationListItem(
            id=row.id,
            project_id=row.project_id,
            project_name=row.project_name,
            program_id=getattr(row, "program_id", None),
            program_name=getattr(row, "program_name", None),
            org_id=row.org_id,
            org_name=row.org_name,
            comm_type=row.comm_type,
            subject=row.subject,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            sent_at=row.sent_at,
            evidence_link_count=0,
        )
        for row in rows
    ]
    return CommunicationsListPage(
        items=items,
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
        db_ms=db_ms,
    )


def sanitize_communication_read_for_client(data: CommunicationRead) -> CommunicationRead:
    """Strip internal-only fields from a communication returned to clients."""
    data.generation_mode = None
    data.generation_warning = None
    data.evidence_links = []
    data.drafted_by_agent = "client_interaction_agent"
    # Prefer approved body; never expose a draft-only working copy as the primary payload.
    if data.body_approved and data.body_approved.strip():
        data.body_draft = data.body_approved
    return data


async def list_org_communications(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    status: CommunicationStatus | None = None,
    project_id: UUID | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> CommunicationsListPage:
    """Org-scoped PM inbox list. Exactly two DB executes (count + page)."""
    if current_user.role == AppRole.CLIENT:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    bounded_limit = bound_communications_list_limit(limit)
    bounded_offset = bound_communications_list_offset(offset)

    if project_id is not None:
        # Enforce project visibility (org / assignment / super_admin) before listing.
        await get_visible_project(session, project_id, current_user)

    list_stmt = build_communications_list_stmt(
        current_user,
        status=status,
        project_id=project_id,
        limit=bounded_limit,
        offset=bounded_offset,
    )
    count_stmt = build_communications_list_count_stmt(
        current_user,
        status=status,
        project_id=project_id,
    )

    db_started = perf_counter()
    rows = list((await session.execute(list_stmt)).all())
    total = int((await session.execute(count_stmt)).scalar_one_or_none() or 0)
    db_ms = (perf_counter() - db_started) * 1000

    return CommunicationsListPage(
        items=[_row_to_list_item(row) for row in rows],
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
        db_ms=db_ms,
    )
