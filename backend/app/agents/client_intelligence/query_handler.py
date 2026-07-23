"""Grounded Client Intelligence Q&A handler.

Replaces the placeholder client_interaction_agent answer path with
project-scoped, evidence-pack-backed answers and audited latency.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from datetime import date
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    EvidenceVisibility,
    MilestoneFacts,
    SourceAgent,
)
from app.agents.client_intelligence.delivery_confidence_intelligence import (
    assess_delivery_confidence,
)
from app.agents.client_intelligence.delivery_trend import assess_delivery_trend
from app.agents.client_intelligence.evidence_pack import build_client_evidence_pack
from app.agents.client_intelligence.project_health import assess_project_health
from app.agents.client_intelligence.query_contracts import (
    ClientIntelligenceAnswerAvailability,
    ClientIntelligenceConfidenceLevel,
    ClientIntelligenceQueryEvidenceLink,
    ClientIntelligenceQueryRead,
    ClientIntelligenceQueryRetrievalParams,
    ClientIntelligenceQuestionCategory,
    ClientIntelligenceQuestionCreate,
)
from app.agents.client_intelligence.risk_transparency import assess_risk_transparency
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AgentQuery,
    AgentQueryEvidenceLink,
    AppRole,
    CommunicationStatus,
)
from app.services.evidence import EvidenceInput
from app.services.scoping import get_visible_project

CLIENT_INTERACTION_AGENT_NAME = "client_interaction_agent"
QUESTION_MAX_LENGTH = 2000
PLACEHOLDER_ANSWER = (
    "The LLM provider is not configured yet; this response is grounded in the "
    "attached evidence placeholders."
)
LEGACY_PLACEHOLDER_REDACTION = (
    "This legacy query does not contain a grounded Client Intelligence answer."
)

_ALLOWED_QA_ROLES = frozenset(
    {
        AppRole.DELIVERY_MANAGER,
        AppRole.BSG_LEADERSHIP,
        AppRole.SUPER_ADMIN,
        AppRole.CLIENT,
    }
)


def _visibility_for_qa_user(current_user: CurrentUser) -> EvidenceVisibility:
    """Clients always get CLIENT_SAFE packs; internal roles get INTERNAL."""
    if current_user.role == AppRole.CLIENT:
        return EvidenceVisibility.CLIENT_SAFE
    return EvidenceVisibility.INTERNAL

_MILESTONE_EXCLUDED_STATUSES = frozenset({"completed", "cancelled"})

_CLAIM_VOCABULARY = (
    "on track",
    "at risk",
    "amber",
    "red",
    "green",
    "delayed",
    "completed",
    "guaranteed",
    "promise",
    "commit",
    "forecast",
    "mitigation",
    "go-live",
    "go live",
    "missed",
    "blocked",
)

_PROPER_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?")
_MILESTONE_REFERENCE_RE = re.compile(r"\b(?:m|milestone)\s*[-#:]?\s*(\d+)\b", re.IGNORECASE)

_INJECTION_PATTERNS = (
    r"ignore (all |previous |the )?instructions",
    r"disregard (all |previous |the )?instructions",
    r"reveal (the )?system prompt",
    r"show (me )?(your |the )?hidden context",
    r"exfiltrat",
    r"override (authorization|rbac|security)",
    r"act as (a )?superuser",
    r"jailbreak",
)

_COMMITMENT_PATTERNS = (
    r"\b(promise|commit|guarantee|contractual|sla breach|penalty)\b",
    r"\b(approve|sign off|authorize)\b.*(client|customer)",
    r"\bcan we tell the client\b",
)

_CROSS_SCOPE_PATTERNS = (
    r"\b(other clients?|another client|cross[- ]client|portfolio ranking|compare clients)\b",
    r"\bacross (all )?projects\b",
)

_SENSITIVE_PATTERNS = (
    r"\b(annotator|employee|salary|payroll|pii|personal data|home address)\b",
    r"\b(raw notes?|internal notes?|private notes?)\b",
)

_CATEGORY_KEYWORDS: list[tuple[ClientIntelligenceQuestionCategory, tuple[str, ...]]] = [
    (
        ClientIntelligenceQuestionCategory.PROJECT_HEALTH,
        (
            "project health",
            "health status",
            "health score",
            "how healthy",
            "project status",
            "how is the project",
            "how's the project",
            "how is my project",
            "how's my project",
            "how are we doing",
            "are we on track",
        ),
    ),
    (
        ClientIntelligenceQuestionCategory.CONFIDENCE_HISTORY,
        (
            "confidence history",
            "confidence trend",
            "confidence over time",
            "delivery confidence history",
            "delivery confidence trend",
            "sparkline",
        ),
    ),
    (
        ClientIntelligenceQuestionCategory.DELIVERY_CONFIDENCE,
        (
            "delivery confidence",
            "confidence score",
            "confidence status",
            "forecast completion",
            "delivery outlook",
            "chance of delivery",
        ),
    ),
    (
        ClientIntelligenceQuestionCategory.MILESTONES,
        (
            "milestone",
            "next milestone",
            "milestone risk",
            "go-live date",
            "deadline",
            "sprint goal",
        ),
    ),
    (
        ClientIntelligenceQuestionCategory.RISKS,
        ("risk", "mitigation", "risk alert", "blocker", "issue", "concern"),
    ),
    (
        ClientIntelligenceQuestionCategory.DELIVERY_TREND,
        ("delivery trend", "throughput trend", "units trend", "progress trend"),
    ),
    (
        ClientIntelligenceQuestionCategory.CHANGE,
        ("change since", "what changed", "previous cycle", "week over week", "since last week"),
    ),
    (
        ClientIntelligenceQuestionCategory.REPORTS,
        (
            "approved report",
            "sent report",
            "client report",
            "weekly summary",
            "status report",
            "latest report",
        ),
    ),
    (
        ClientIntelligenceQuestionCategory.QUALITY,
        ("quality", "defect", "rework", "accuracy"),
    ),
    (
        ClientIntelligenceQuestionCategory.WORKFORCE,
        ("workforce", "capacity", "skill coverage", "training", "team", "teams"),
    ),
    (
        ClientIntelligenceQuestionCategory.GOVERNANCE,
        ("governance", "charter", "escalation", "dependency"),
    ),
    (
        ClientIntelligenceQuestionCategory.KNOWLEDGE,
        ("knowledge", "document", "lesson", "playbook"),
    ),
]


def classify_client_intelligence_question(
    question: str,
) -> ClientIntelligenceQuestionCategory:
    lower = question.lower().strip()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, lower):
            return ClientIntelligenceQuestionCategory.INJECTION
    for pattern in _COMMITMENT_PATTERNS:
        if re.search(pattern, lower):
            return ClientIntelligenceQuestionCategory.COMMITMENT
    for pattern in _CROSS_SCOPE_PATTERNS:
        if re.search(pattern, lower):
            return ClientIntelligenceQuestionCategory.CROSS_SCOPE
    for pattern in _SENSITIVE_PATTERNS:
        if re.search(pattern, lower):
            return ClientIntelligenceQuestionCategory.SENSITIVE
    if any(token in lower for token in ("readiness", "go-live scoring", "go live score")):
        return ClientIntelligenceQuestionCategory.UNSUPPORTED
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lower for keyword in keywords):
            return category
    # Project teams naturally refer to milestones by shorthand (for example,
    # "What will happen in M2?"). Treat that as a milestone question rather
    # than rejecting it just because the word "milestone" is absent.
    if _MILESTONE_REFERENCE_RE.search(lower):
        return ClientIntelligenceQuestionCategory.MILESTONES
    if any(
        token in lower
        for token in (
            "status",
            "how is",
            "how's",
            "overview",
            "summary",
            "update",
            "progress",
            "what's going",
            "what is going",
            "tell me about the project",
            "tell me about this project",
            "tell me about my project",
        )
    ):
        return ClientIntelligenceQuestionCategory.GENERAL_STATUS
    # Conversational defaults for client portal — prefer a status summary over hard reject.
    if any(
        token in lower
        for token in ("project", "delivery", "sprint", "timeline", "schedule")
    ):
        return ClientIntelligenceQuestionCategory.GENERAL_STATUS
    return ClientIntelligenceQuestionCategory.UNSUPPORTED


def _client_facing_limitations(codes: list[str]) -> list[str]:
    """Drop internal DQ/source codes that are not meaningful to client users."""
    kept: list[str] = []
    for code in codes:
        upper = code.upper()
        if upper.startswith(
            (
                "DQ_",
                "CI-D",
                "FRESHNESS_",
                "VISIBILITY_",
                "WORKFLOW_",
                "PLAN_SERIES",
                "BACKLOG_",
                "CLIENT_COMMUNICATION_NOTES",
                "KNOWLEDGE ",
                "TEAM-LEVEL",
                "POLICY_UNAVAILABLE",
            )
        ):
            continue
        if "UNAVAILABLE BECAUSE" in upper or "PHASE 1" in upper:
            continue
        if upper.startswith("SOURCE_QUALITY_"):
            continue
        kept.append(code)
    return kept


def _partial_status_answer(
    pack: ClientEvidencePack,
    *,
    health_status: str | None,
    period_as_of: date,
) -> tuple[str, list[ClientEvidenceReference], list[str], bool]:
    """Build a useful client status summary from whatever governed facts exist."""
    limitations: list[str] = []
    parts = [
        f"Here is what governed evidence shows for {pack.project.project_name} "
        f"as of {period_as_of.isoformat()}."
    ]
    if health_status is not None:
        parts.append(f"Project Health: {health_status}.")
    else:
        parts.append("A full Project Health status is not available yet.")
        limitations.append("PROJECT_HEALTH_PARTIAL")

    score = pack.delivery.latest_delivery_confidence
    if score is not None:
        observed = score.observed_at.date().isoformat() if score.observed_at else period_as_of.isoformat()
        parts.append(
            f"Delivery Confidence: {score.score_pct}% ({score.status}) as of {observed}."
        )
        if score.forecast_completion_date is not None:
            parts.append(
                f"Forecast completion date: {score.forecast_completion_date.isoformat()}."
            )
    else:
        parts.append("Delivery Confidence: not available yet.")
        limitations.append("DELIVERY_CONFIDENCE_PARTIAL")

    milestones = list(pack.delivery.milestones)
    completed = [
        m for m in milestones if m.status == "completed" or m.actual_date is not None
    ]
    at_risk = [m for m in milestones if m.status in {"at_risk", "delayed", "missed"}]
    upcoming = sorted(
        [
            m
            for m in milestones
            if m.status not in _MILESTONE_EXCLUDED_STATUSES and m.planned_date >= period_as_of
        ],
        key=lambda item: (item.planned_date, str(item.id)),
    )
    if completed:
        latest = sorted(
            completed,
            key=lambda item: (item.actual_date or item.planned_date, str(item.id)),
            reverse=True,
        )[0]
        parts.append(f"Most recently reached milestone: {_format_milestone_fact(latest)}.")
    if upcoming:
        parts.append(f"Next milestone: {_format_milestone_fact(upcoming[0])}.")
    if at_risk:
        parts.append(
            f"{len(at_risk)} milestone(s) currently at risk or delayed: "
            + "; ".join(_format_milestone_fact(m) for m in at_risk[:3])
            + "."
        )
    if not milestones:
        limitations.append("MILESTONES_PARTIAL")

    open_risks = list(pack.delivery.open_risks)
    if open_risks:
        titles = ", ".join(alert.title for alert in open_risks[:3])
        parts.append(f"{len(open_risks)} open risk alert(s): {titles}.")
    else:
        parts.append("No open risk alerts are present in the current evidence pack.")

    refs = _refs_for_tables(
        pack,
        {
            "delivery_confidence_scores",
            "milestones",
            "risk_alerts",
            "throughput_snapshots",
        },
    )
    has_useful_fact = (
        score is not None or bool(milestones) or bool(open_risks) or health_status is not None
    )
    return " ".join(parts), refs[:12], limitations, has_useful_fact

def _dedupe_evidence(
    refs: list[ClientEvidenceReference],
    *,
    pack_source_fingerprint: str | None = None,
) -> list[EvidenceInput]:
    seen: set[tuple[str, UUID]] = set()
    items: list[EvidenceInput] = []
    ordered = sorted(
        refs,
        key=lambda item: (item.source_table, str(item.source_row_id), item.description),
    )
    for ref in ordered:
        key = (ref.source_table, ref.source_row_id)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            EvidenceInput(
                source_table=ref.source_table,
                source_row_id=ref.source_row_id,
                description=ref.description,
                visibility=ref.visibility.value,
                observed_at=ref.observed_at,
                claim_keys=tuple(ref.claim_keys),
                pack_source_fingerprint=pack_source_fingerprint,
            )
        )
    return items


def _refs_for_tables(
    pack: ClientEvidencePack,
    tables: set[str],
) -> list[ClientEvidenceReference]:
    return [ref for ref in pack.evidence if ref.source_table in tables]


def _agents_from_refs(refs: list[ClientEvidenceReference]) -> list[str]:
    return sorted({ref.source_agent.value for ref in refs})


def _sanitize_document_text(text: str) -> str:
    """Treat retrieved knowledge as untrusted content, not instructions."""
    lowered = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return "[retrieved document content redacted: embedded instruction detected]"
    return text


def _rewrite_is_grounded(*, rewrite: str, allowed_text: str) -> bool:
    """Partial historical checker — insufficient for production acceptance.

    Absence from a finite vocabulary is not proof of grounding. Production Q&A
    must not accept LLM rewrites until a complete structured claim validator
    exists; see `_llm_refine_answer`.
    """
    if PLACEHOLDER_ANSWER in rewrite:
        return False
    for match in _NUMBER_TOKEN_RE.findall(rewrite):
        if match not in allowed_text:
            return False
    for match in _ISO_DATE_RE.findall(rewrite):
        if match not in allowed_text:
            return False
    allowed_lower = allowed_text.lower()
    rewrite_lower = rewrite.lower()
    for term in _CLAIM_VOCABULARY:
        pattern = rf"\b{re.escape(term)}\b"
        if re.search(pattern, rewrite_lower) and not re.search(pattern, allowed_lower):
            return False
    return all(name in allowed_text for name in _PROPER_NAME_RE.findall(rewrite))


def _milestone_question_intent(question: str | None) -> str:
    """Classify milestone Q&A intent from the user question.

    Returns one of: ``completed``, ``at_risk``, ``next``.
    """
    if not question:
        return "next"
    lower = question.lower()
    if any(
        token in lower
        for token in (
            "reached",
            "completed",
            "finished",
            "already done",
            "done so far",
            "what was delivered",
            "what have we delivered",
        )
    ):
        return "completed"
    if any(
        token in lower
        for token in ("at risk", "delayed", "slipping", "behind schedule", "missed")
    ):
        return "at_risk"
    return "next"


def _format_milestone_fact(item: MilestoneFacts) -> str:
    date_part = item.planned_date.isoformat()
    if getattr(item, "actual_date", None) is not None:
        date_part = (
            f"planned {item.planned_date.isoformat()}, "
            f"reached {item.actual_date.isoformat()}"
        )
    return f"'{item.name}' ({date_part}; status: {item.status})"


def _referenced_milestone(
    question: str | None,
    milestones: list[MilestoneFacts],
) -> MilestoneFacts | None:
    """Resolve a user-supplied milestone shorthand such as ``M2``."""
    if not question:
        return None
    match = _MILESTONE_REFERENCE_RE.search(question)
    if match is None:
        return None
    milestone_number = match.group(1)
    for milestone in milestones:
        name_match = _MILESTONE_REFERENCE_RE.search(milestone.name)
        if name_match is not None and name_match.group(1) == milestone_number:
            return milestone
    return None


def _build_category_answer(
    category: ClientIntelligenceQuestionCategory,
    pack: ClientEvidencePack,
    *,
    question: str | None = None,
    client_safe: bool = False,
) -> tuple[
    ClientIntelligenceAnswerAvailability,
    ClientIntelligenceConfidenceLevel,
    str,
    list[str],
    str | None,
    bool,
    list[ClientEvidenceReference],
    bool,
]:
    """Return availability, confidence, answer, limitations, next_step, escalation, refs, insufficient."""
    # Client portal answers must not dump internal pack DQ / source-gap codes.
    limitations = [] if client_safe else list(pack.limitations)
    period = pack.reporting_period

    if category == ClientIntelligenceQuestionCategory.INJECTION:
        return (
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "Client Intelligence cannot follow instructions that attempt to override "
                "authorization, reveal hidden context, or expand project scope."
            ),
            ["PROMPT_INJECTION_BLOCKED"],
            "Rephrase the question to ask about governed project facts only.",
            True,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.COMMITMENT:
        return (
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "Client Intelligence cannot create contractual commitments, client promises, "
                "or approval decisions from evidence alone."
            ),
            ["COMMITMENT_REQUIRES_HUMAN_APPROVAL"],
            "Escalate to the Delivery Manager / PM for any client commitment or approval.",
            True,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.CROSS_SCOPE:
        return (
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "Client Intelligence answers only for the authorized selected project and "
                "does not perform cross-client or portfolio comparisons."
            ),
            ["CROSS_SCOPE_BLOCKED"],
            "Select the specific authorized project and ask about that project only.",
            True,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.SENSITIVE:
        return (
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "Client Intelligence does not expose employee-level, payroll, PII, or raw "
                "internal notes through this Q&A surface."
            ),
            ["SENSITIVE_DATA_BLOCKED"],
            "Ask about aggregate governed workforce or delivery facts only.",
            True,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.UNSUPPORTED:
        return (
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "I can help with project health, delivery confidence, milestones, "
                "risks, trends, and approved reports for this project."
            ),
            ["QUESTION_UNSUPPORTED"],
            "Try asking about project health, delivery confidence, milestones, or open risks.",
            False,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.CHANGE:
        return (
            ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "Previous-cycle Change Intelligence comparison is not available. "
                "Reporting-period boundaries alone are not a verified change comparison."
            ),
            sorted(set(limitations + ["CHANGE_COMPARISON_NOT_AVAILABLE"])),
            "Use Change Intelligence when previous-cycle evidence exists.",
            False,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.CONFIDENCE_HISTORY:
        return (
            ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            (
                "Delivery Confidence history cannot be inferred from the evidence pack alone. "
                "Persisted history points are required."
            ),
            sorted(set(limitations + ["CONFIDENCE_HISTORY_REQUIRES_PERSISTED_POINTS"])),
            "Ask again so Client Intelligence can load persisted Delivery Confidence history.",
            False,
            [],
            True,
        )

    if category == ClientIntelligenceQuestionCategory.MILESTONES:
        milestones = list(pack.delivery.milestones)
        refs = _refs_for_tables(pack, {"milestones"})
        if not milestones:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "No governed milestone facts are available for this project.",
                sorted(set(limitations + ["MILESTONES_UNAVAILABLE"])),
                "Confirm milestones are configured in Delivery/Governance sources.",
                False,
                [],
                True,
            )

        intent = _milestone_question_intent(question)
        at_risk = [m for m in milestones if m.status in {"at_risk", "delayed", "missed"}]
        referenced = _referenced_milestone(question, milestones)

        if referenced is not None:
            referenced_refs = [
                ref for ref in refs if ref.source_row_id == referenced.id
            ]
            return (
                ClientIntelligenceAnswerAvailability.ANSWERED,
                ClientIntelligenceConfidenceLevel.MEDIUM
                if limitations
                else ClientIntelligenceConfidenceLevel.HIGH,
                f"Milestone {_format_milestone_fact(referenced)}.",
                sorted(set(limitations)),
                "Ask about milestone risks or the next planned milestone for more detail.",
                False,
                referenced_refs[:1] or refs[:8],
                False,
            )

        if intent == "completed":
            completed = [
                item
                for item in milestones
                if item.status == "completed" or item.actual_date is not None
            ]
            completed = sorted(
                completed,
                key=lambda item: (
                    item.actual_date or item.planned_date,
                    str(item.id),
                ),
                reverse=True,
            )
            if not completed:
                return (
                    ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                    ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                    (
                        f"No reached/completed governed milestones are recorded "
                        f"as of {period.as_of.isoformat()}."
                    ),
                    sorted(set(limitations + ["NO_COMPLETED_MILESTONE"])),
                    "Ask about the next upcoming milestone, or check with your BSG PM.",
                    False,
                    refs[:8],
                    True,
                )
            latest = completed[0]
            answer = (
                f"Most recently reached milestone is {_format_milestone_fact(latest)}."
            )
            if len(completed) > 1:
                others = "; ".join(_format_milestone_fact(item) for item in completed[1:3])
                answer += f" Other reached milestones: {others}."
                if len(completed) > 3:
                    answer += f" ({len(completed)} reached in total.)"
            return (
                ClientIntelligenceAnswerAvailability.ANSWERED,
                ClientIntelligenceConfidenceLevel.MEDIUM
                if limitations
                else ClientIntelligenceConfidenceLevel.HIGH,
                answer,
                sorted(set(limitations)),
                "Ask about the next upcoming milestone if you need the forward plan.",
                False,
                refs[:12],
                False,
            )

        if intent == "at_risk":
            if not at_risk:
                return (
                    ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                    ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                    (
                        f"No governed milestones are currently marked at risk or delayed "
                        f"as of {period.as_of.isoformat()}."
                    ),
                    sorted(set(limitations + ["NO_AT_RISK_MILESTONE"])),
                    "Ask about the next upcoming milestone for the forward plan.",
                    False,
                    refs[:8],
                    True,
                )
            named = "; ".join(_format_milestone_fact(item) for item in at_risk[:5])
            answer = (
                f"{len(at_risk)} milestone(s) are currently at risk or delayed: {named}."
            )
            return (
                ClientIntelligenceAnswerAvailability.ANSWERED,
                ClientIntelligenceConfidenceLevel.MEDIUM
                if limitations
                else ClientIntelligenceConfidenceLevel.HIGH,
                answer,
                sorted(set(limitations)),
                "Review milestone risk details with your BSG PM.",
                False,
                refs[:12],
                False,
            )

        eligible = [
            item
            for item in milestones
            if item.status not in _MILESTONE_EXCLUDED_STATUSES
            and item.planned_date >= period.as_of
        ]
        eligible = sorted(eligible, key=lambda item: (item.planned_date, str(item.id)))
        if not eligible:
            answer = (
                f"No upcoming governed milestone is available as of {period.as_of.isoformat()}."
            )
            if at_risk:
                answer += (
                    f" {len(at_risk)} milestone(s) are currently at risk or delayed: "
                    + "; ".join(_format_milestone_fact(item) for item in at_risk[:3])
                    + "."
                )
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                answer,
                sorted(set(limitations + ["NO_UPCOMING_MILESTONE"])),
                "Review milestone configuration if an upcoming milestone is expected.",
                False,
                refs[:8],
                True,
            )
        nxt = eligible[0]
        answer = (
            f"Next milestone by planned date is {_format_milestone_fact(nxt)}."
        )
        if at_risk:
            answer += (
                f" {len(at_risk)} milestone(s) are currently at risk or delayed: "
                + "; ".join(_format_milestone_fact(item) for item in at_risk[:3])
                + "."
            )
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM
            if limitations
            else ClientIntelligenceConfidenceLevel.HIGH,
            answer,
            sorted(set(limitations)),
            "Review milestone risk details with your BSG PM if status is at_risk or delayed.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.PROJECT_HEALTH:
        health = assess_project_health(pack, policy=None)
        refs = _refs_for_tables(
            pack,
            {
                "throughput_snapshots",
                "delivery_confidence_scores",
                "milestones",
                "risk_alerts",
                "quality_snapshots",
            },
        )
        if health.overall_data_quality.value == "unavailable" or health.status is None:
            answer, partial_refs, partial_limits, has_facts = _partial_status_answer(
                pack,
                health_status=None,
                period_as_of=period.as_of,
            )
            if has_facts:
                return (
                    (
                        ClientIntelligenceAnswerAvailability.ANSWERED
                        if partial_refs
                        else ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
                    ),
                    (
                        ClientIntelligenceConfidenceLevel.MEDIUM
                        if partial_refs
                        else ClientIntelligenceConfidenceLevel.INSUFFICIENT
                    ),
                    answer,
                    sorted(set(partial_limits + (["PROJECT_HEALTH_UNAVAILABLE"] if not client_safe else []))),
                    "Ask about delivery confidence, milestones, or risks for more detail.",
                    False,
                    partial_refs[:12] if partial_refs else refs[:8],
                    not bool(partial_refs),
                )
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                (
                    "Project Health cannot be determined yet because governed delivery "
                    "evidence is still incomplete for this project."
                ),
                sorted(
                    set(
                        ["PROJECT_HEALTH_UNAVAILABLE"]
                        if client_safe
                        else limitations + list(health.limitations) + ["PROJECT_HEALTH_UNAVAILABLE"]
                    )
                ),
                "Please check with your BSG PM, or ask again after delivery data is refreshed.",
                False,
                refs[:8],
                True,
            )
        answer = (
            f"Project Health for {pack.project.project_name} is {health.status.value} "
            f"as of {period.as_of.isoformat()}. "
            f"This is independent of Delivery Confidence status."
        )
        conf = (
            ClientIntelligenceConfidenceLevel.MEDIUM
            if health.overall_data_quality.value in {"partial", "stale", "conflicting"}
            or limitations
            else ClientIntelligenceConfidenceLevel.HIGH
        )
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            conf,
            answer,
            sorted(set(limitations + list(health.limitations))),
            "Ask about delivery confidence, milestones, or risks if you need more detail.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.DELIVERY_CONFIDENCE:
        confidence = assess_delivery_confidence(pack, explanation_policy=None)
        refs = _refs_for_tables(pack, {"delivery_confidence_scores", "milestones", "throughput_snapshots"})
        score = pack.delivery.latest_delivery_confidence
        if score is None or confidence.availability.value in {"unavailable", "no_score"}:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "Delivery Confidence is not available from governed Delivery evidence for this project.",
                sorted(set(limitations + list(confidence.limitations) + ["DELIVERY_CONFIDENCE_UNAVAILABLE"])),
                "Ensure a Delivery Confidence score exists for the selected project.",
                False,
                refs[:8],
                True,
            )
        answer = (
            f"Delivery Confidence is {score.score_pct}% ({score.status}) as of "
            f"{(score.observed_at.date() if score.observed_at else period.as_of).isoformat()}. "
            f"This is not Project Health."
        )
        if score.forecast_completion_date:
            answer += f" Forecast completion date is {score.forecast_completion_date.isoformat()}."
        conf = (
            ClientIntelligenceConfidenceLevel.MEDIUM
            if confidence.availability.value in {"partial", "stale"} or limitations
            else ClientIntelligenceConfidenceLevel.HIGH
        )
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            conf,
            answer,
            sorted(set(limitations + list(confidence.limitations))),
            "Inspect Delivery Confidence drivers and history in Client Detail.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.RISKS:
        risks = assess_risk_transparency(pack, policy=None)
        refs = _refs_for_tables(pack, {"risk_alerts", "bottlenecks"})
        open_risks = list(pack.delivery.open_risks)
        if risks.availability.value in {"unavailable", "no_data"} and not open_risks:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "Material delivery risks cannot be confirmed from the current evidence pack.",
                sorted(set(limitations + list(risks.limitations) + ["RISKS_UNAVAILABLE"])),
                "Ensure risk alerts are populated for the selected project.",
                False,
                refs[:8],
                True,
            )
        if not open_risks:
            answer = "No open governed risk alerts are present in the current evidence pack."
        else:
            titles = ", ".join(alert.title for alert in open_risks[:5])
            answer = f"{len(open_risks)} governed risk alert(s) are present. Leading items: {titles}."
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM,
            answer,
            sorted(set(limitations + list(risks.limitations))),
            "Review Risk Transparency in Client Detail and confirm mitigations with the PM.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.DELIVERY_TREND:
        trend = assess_delivery_trend(pack, policy=None)
        refs = _refs_for_tables(pack, {"throughput_snapshots"})
        if trend.availability.value in {"unavailable", "no_data"}:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "Delivery trend cannot be determined from available throughput evidence.",
                sorted(set(limitations + list(trend.limitations) + ["DELIVERY_TREND_UNAVAILABLE"])),
                "Ensure throughput snapshots exist across the reporting period.",
                False,
                refs[:8],
                True,
            )
        answer = (
            f"Delivery trend assessment availability is {trend.availability.value} "
            f"for reporting period {period.start_date.isoformat()} to {period.end_date.isoformat()}."
        )
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM,
            answer,
            sorted(set(limitations + list(trend.limitations))),
            "Review Delivery Trend details in Client Detail.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.QUALITY:
        refs = _refs_for_tables(pack, {"quality_snapshots"})
        snap = pack.quality.current_period[0] if pack.quality.current_period else None
        if snap is None:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "No governed quality snapshot is available for this project.",
                sorted(set(limitations + ["QUALITY_SNAPSHOT_UNAVAILABLE"])),
                "Wait for Quality Intelligence snapshots, then retry.",
                False,
                [],
                True,
            )
        answer = f"Latest quality snapshot week is {snap.iso_year}-W{snap.iso_week:02d}."
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM,
            answer,
            sorted(set(limitations)),
            "Open Quality Intelligence for deeper metrics.",
            False,
            refs[:8],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.WORKFORCE:
        refs = [
            ref
            for ref in pack.evidence
            if ref.source_agent == SourceAgent.WORKFORCE_CAPABILITY
        ]
        capacity = pack.workforce.capacity
        if (
            not refs
            and not pack.workforce.team_capacity
            and capacity.active_team_count is None
        ):
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "No governed workforce capacity facts are available for this project.",
                sorted(set(limitations + ["WORKFORCE_EVIDENCE_UNAVAILABLE"])),
                "Confirm workforce capacity data is loaded for the project.",
                False,
                [],
                True,
            )
        if capacity.active_team_count is None:
            answer = (
                "Team-level capacity is not available in the current governed evidence pack."
            )
        elif capacity.active_team_count == 0:
            answer = "No active teams are currently recorded for this project."
        else:
            answer = (
                f"This project has {capacity.active_team_count} active team(s)."
            )
            if capacity.utilization_pct is not None:
                observed = (
                    f" as of {capacity.latest_snapshot_date.isoformat()}"
                    if capacity.latest_snapshot_date is not None
                    else ""
                )
                covered = capacity.teams_with_utilization
                if covered is not None:
                    answer += (
                        f" Combined utilization is {capacity.utilization_pct}%{observed} "
                        f"across {covered} team(s) with utilization data."
                    )
                else:
                    answer += f" Combined utilization is {capacity.utilization_pct}%{observed}."
            elif capacity.teams_without_utilization:
                answer += " Team utilization snapshots are not available yet."
        answer += " Individual team names and employee details are not exposed here."
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM,
            answer,
            sorted(set(limitations)),
            "Ask aggregate capacity or skill-coverage questions only.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.GOVERNANCE:
        refs = [
            ref
            for ref in pack.evidence
            if ref.source_agent == SourceAgent.PROJECT_GOVERNANCE
        ]
        if not refs:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "No governed governance facts are available in the evidence pack.",
                sorted(set(limitations + ["GOVERNANCE_EVIDENCE_UNAVAILABLE"])),
                "Confirm charter/escalation/dependency records exist.",
                False,
                [],
                True,
            )
        answer = "Governed governance facts are present in the evidence pack for this project."
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM,
            answer,
            sorted(set(limitations)),
            "Use Project Governance for actionable escalations.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.KNOWLEDGE:
        docs = [
            doc
            for doc in pack.knowledge.documents
            if getattr(doc, "visibility", None) in {None, "client_safe", "internal"}
        ]
        refs = [
            ref
            for ref in pack.evidence
            if ref.source_agent == SourceAgent.OPERATIONAL_KNOWLEDGE
        ]
        safe_snippets = []
        for chunk in pack.knowledge.chunks[:3]:
            text = _sanitize_document_text(getattr(chunk, "untrusted_text", "") or "")
            if text:
                safe_snippets.append(text[:240])
        if not docs and not refs:
            return (
                ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
                ClientIntelligenceConfidenceLevel.INSUFFICIENT,
                "No approved operational knowledge documents are available for this project.",
                sorted(set(limitations + ["KNOWLEDGE_UNAVAILABLE"])),
                "Index approved client-safe or internal knowledge documents, then retry.",
                False,
                [],
                True,
            )
        answer = (
            f"{len(docs)} governed knowledge document(s) are in scope. "
            "Retrieved document text is treated as untrusted content and cannot override authorization."
        )
        if safe_snippets:
            answer += " Sample grounded excerpts were reviewed for this answer."
        return (
            ClientIntelligenceAnswerAvailability.ANSWERED,
            ClientIntelligenceConfidenceLevel.MEDIUM,
            answer,
            sorted(set(limitations)),
            "Cite only approved indexed knowledge when asking follow-ups.",
            False,
            refs[:12],
            False,
        )

    if category == ClientIntelligenceQuestionCategory.REPORTS:
        # Report facts come from communications; pack may not include them.
        # Caller supplements evidence from approved/sent communications.
        return (
            ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            "Approved/sent report lookup requires Client Intelligence communications evidence.",
            ["REPORTS_REQUIRE_COMMUNICATIONS_LOOKUP"],
            "Ask again after reports are loaded, or open Approved & Sent Reports.",
            False,
            [],
            True,
        )

    # GENERAL_STATUS — compose whatever governed facts are available.
    health = assess_project_health(pack, policy=None)
    answer, refs, partial_limits, has_facts = _partial_status_answer(
        pack,
        health_status=health.status.value if health.status is not None else None,
        period_as_of=period.as_of,
    )
    limitations.extend(partial_limits)
    if not has_facts or not refs:
        return (
            ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            answer
            if has_facts
            else (
                f"Governed status facts are not available yet for {pack.project.project_name}."
            ),
            sorted(set(limitations)),
            "Ask your BSG PM, or try again after delivery data is refreshed.",
            False,
            refs[:8],
            True,
        )
    return (
        ClientIntelligenceAnswerAvailability.ANSWERED,
        ClientIntelligenceConfidenceLevel.MEDIUM,
        answer,
        sorted(set(limitations)),
        "Ask about delivery confidence, milestones, or risks for more detail.",
        False,
        refs,
        False,
    )


async def _load_report_evidence(
    session: AsyncSession,
    project_id: UUID,
    *,
    pack_source_fingerprint: str,
    visibility: EvidenceVisibility = EvidenceVisibility.INTERNAL,
) -> tuple[str, list[EvidenceInput], list[str]]:
    from app.db.models import ClientCommunication

    report_filter = (
        ClientCommunication.project_id == project_id,
        ClientCommunication.drafted_by_agent == CLIENT_INTERACTION_AGENT_NAME,
        ClientCommunication.status.in_(
            (CommunicationStatus.APPROVED, CommunicationStatus.SENT)
        ),
    )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(ClientCommunication).where(*report_filter)
            )
        ).scalar_one()
        or 0
    )
    rows = list(
        (
            await session.execute(
                select(ClientCommunication)
                .where(*report_filter)
                .order_by(ClientCommunication.updated_at.desc(), ClientCommunication.id.desc())
                .limit(5)
            )
        ).scalars()
    )
    if total == 0 or not rows:
        return (
            "No approved or sent Client Intelligence reports exist for this project.",
            [],
            ["REPORTS_NONE"],
        )
    evidence = [
        EvidenceInput(
            source_table="client_communications",
            source_row_id=row.id,
            description=f"{row.status.value}: {row.subject}",
            visibility=visibility.value,
            observed_at=getattr(row, "updated_at", None)
            or getattr(row, "created_at", None),
            claim_keys=("communication_id", "status", "subject"),
            pack_source_fingerprint=pack_source_fingerprint,
        )
        for row in rows
    ]
    subjects = "; ".join(f"{row.status.value} — {row.subject}" for row in rows[:3])
    if total <= 5:
        answer = (
            f"{total} approved/sent Client Intelligence report(s) found. Recent: {subjects}."
        )
    else:
        answer = (
            f"Showing the 5 most recent approved/sent reports of {total} total. "
            f"Recent: {subjects}."
        )
    return answer, evidence, []


async def _llm_refine_answer(
    *,
    question: str,
    deterministic_answer: str,
    facts_context: dict[str, Any],
) -> tuple[str, str | None]:
    """Generative refinement is disabled until complete claim validation exists.

    Vocabulary, numeric/date, and title-case checks are not sufficient proof that
    an LLM rewrite is grounded. Keep the deterministic evidence-backed answer and
    never persist an LLM rewrite (`model_used` stays null). Provider availability
    must not reduce answer safety.
    """
    _ = (question, facts_context)
    return deterministic_answer, None


def _link_provenance_complete(link: AgentQueryEvidenceLink) -> bool:
    claim_keys = getattr(link, "claim_keys", None) or []
    return bool(
        getattr(link, "visibility", None)
        and getattr(link, "observed_at", None) is not None
        and getattr(link, "pack_source_fingerprint", None)
        and claim_keys
        and len(claim_keys) > 0
    )


def _to_query_read(
    query: AgentQuery,
    evidence_links: list[AgentQueryEvidenceLink],
) -> ClientIntelligenceQueryRead:
    params_raw = query.retrieval_params or {}
    source_fingerprint: str | None = None
    try:
        params = ClientIntelligenceQueryRetrievalParams.model_validate(params_raw)
        availability = params.answer_availability
        confidence = params.confidence_level
        limitations = list(params.limitations)
        next_step = params.next_step
        escalation = params.escalation_required
        insufficient = params.insufficient_evidence
        source_agents = list(params.source_agents)
        as_of = params.as_of
        period_start = params.reporting_period_start
        period_end = params.reporting_period_end
        category = params.category
        source_fingerprint = params.source_fingerprint
    except Exception:
        availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
        confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
        limitations = ["QUERY_RETRIEVAL_PARAMS_INCOMPLETE"]
        next_step = "Re-run the question to refresh structured metadata."
        escalation = False
        insufficient = True
        source_agents = []
        as_of = None
        period_start = None
        period_end = None
        category = None

    links = [
        ClientIntelligenceQueryEvidenceLink(
            id=link.id,
            source_table=link.source_table,
            source_row_id=link.source_row_id,
            description=link.description,
            created_at=getattr(link, "created_at", None),
            visibility=getattr(link, "visibility", None),
            observed_at=getattr(link, "observed_at", None),
            claim_keys=list(getattr(link, "claim_keys", None) or []),
            pack_source_fingerprint=getattr(link, "pack_source_fingerprint", None),
            evidence_provenance_complete=_link_provenance_complete(link),
        )
        for link in sorted(
            evidence_links,
            key=lambda item: (
                item.source_table,
                str(item.source_row_id),
                item.description,
            ),
        )
    ]

    if availability == ClientIntelligenceAnswerAvailability.ANSWERED and not links:
        availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
        confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
        insufficient = True
        limitations = sorted(set(limitations + ["ANSWERED_WITHOUT_EVIDENCE_LINKS"]))

    answer_text = query.answer_text
    if answer_text == PLACEHOLDER_ANSWER or (
        answer_text is not None and PLACEHOLDER_ANSWER in answer_text
    ):
        answer_text = LEGACY_PLACEHOLDER_REDACTION
        availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
        confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
        insufficient = True
        limitations = sorted(set(limitations + ["LEGACY_PLACEHOLDER_ANSWER_REDACTED"]))

    if query.latency_ms is None:
        latency_ms = None
        limitations = sorted(set(limitations + ["QUERY_LATENCY_NOT_RECORDED"]))
    else:
        latency_ms = int(query.latency_ms)

    links_complete = bool(links) and all(link.evidence_provenance_complete for link in links)
    provenance_complete = bool(source_fingerprint) and links_complete
    provenance_state: str | None = None

    evidence_free_outcome = availability in {
        ClientIntelligenceAnswerAvailability.UNSUPPORTED,
        ClientIntelligenceAnswerAvailability.PROVIDER_UNAVAILABLE,
    } or (
        availability == ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
        and not links
        and category
        in {
            ClientIntelligenceQuestionCategory.INJECTION,
            ClientIntelligenceQuestionCategory.COMMITMENT,
            ClientIntelligenceQuestionCategory.CROSS_SCOPE,
            ClientIntelligenceQuestionCategory.SENSITIVE,
            ClientIntelligenceQuestionCategory.UNSUPPORTED,
        }
    )

    if availability == ClientIntelligenceAnswerAvailability.ANSWERED:
        if not provenance_complete:
            # Genuine legacy answered rows: persisted before provenance columns /
            # pack fingerprints existed. Current answered rows must fail closed.
            legacy_shape = source_fingerprint is None and all(
                not link.visibility
                and not link.pack_source_fingerprint
                and not link.claim_keys
                for link in links
            )
            if legacy_shape:
                provenance_state = "LEGACY_EVIDENCE_PROVENANCE_INCOMPLETE"
                limitations = sorted(set(limitations + [provenance_state]))
            else:
                raise ApiError(
                    409,
                    "EVIDENCE_PROVENANCE_INCOMPLETE",
                    (
                        "Answered Client Intelligence queries require complete "
                        "server-authored evidence provenance."
                    ),
                    {"query_id": str(query.id)},
                )
        else:
            provenance_state = None
    elif evidence_free_outcome:
        # Current refusal/unsupported paths intentionally have no evidence.
        provenance_complete = None
        provenance_state = "not_applicable"
    elif not provenance_complete:
        # Other insufficient outcomes with missing provenance: only label legacy
        # when the row looks pre-migration (no fingerprint and no link provenance).
        if source_fingerprint is None and not any(
            link.visibility or link.pack_source_fingerprint or link.claim_keys
            for link in links
        ):
            if links or "QUERY_RETRIEVAL_PARAMS_INCOMPLETE" in limitations:
                provenance_state = "LEGACY_EVIDENCE_PROVENANCE_INCOMPLETE"
                limitations = sorted(set(limitations + [provenance_state]))
            else:
                provenance_state = "not_applicable"
                provenance_complete = None
        else:
            provenance_state = "LEGACY_EVIDENCE_PROVENANCE_INCOMPLETE"
            limitations = sorted(set(limitations + [provenance_state]))

    return ClientIntelligenceQueryRead(
        query_id=query.id,
        project_id=query.project_id,
        question=query.query_text,
        answer_text=answer_text,
        answer_availability=availability,
        confidence_level=confidence,
        limitations=limitations,
        next_step=next_step,
        escalation_required=escalation,
        source_agents=source_agents,
        evidence_links=links,
        as_of=as_of,
        reporting_period_start=period_start,
        reporting_period_end=period_end,
        model_used=query.model_used,
        latency_ms=latency_ms,
        created_at=query.created_at,
        category=category,
        insufficient_evidence=insufficient,
        evidence_source_fingerprint=source_fingerprint,
        evidence_provenance_complete=provenance_complete,
        evidence_provenance_state=provenance_state,
    )


def _build_category_answer_without_pack(
    category: ClientIntelligenceQuestionCategory,
) -> tuple[
    ClientIntelligenceAnswerAvailability,
    ClientIntelligenceConfidenceLevel,
    str,
    list[str],
    str | None,
    bool,
    list[ClientEvidenceReference],
    bool,
]:
    blocked = {
        ClientIntelligenceQuestionCategory.INJECTION: (
            "Client Intelligence cannot follow instructions that attempt to override "
            "authorization, reveal hidden context, or expand project scope.",
            ["PROMPT_INJECTION_BLOCKED"],
            "Rephrase the question to ask about governed project facts only.",
            True,
        ),
        ClientIntelligenceQuestionCategory.COMMITMENT: (
            "Client Intelligence cannot create contractual commitments, client promises, "
            "or approval decisions from evidence alone.",
            ["COMMITMENT_REQUIRES_HUMAN_APPROVAL"],
            "Escalate to the Delivery Manager / PM for any client commitment or approval.",
            True,
        ),
        ClientIntelligenceQuestionCategory.CROSS_SCOPE: (
            "Client Intelligence answers only for the authorized selected project and "
            "does not perform cross-client or portfolio comparisons.",
            ["CROSS_SCOPE_BLOCKED"],
            "Select the specific authorized project and ask about that project only.",
            True,
        ),
        ClientIntelligenceQuestionCategory.SENSITIVE: (
            "Client Intelligence does not expose employee-level, payroll, PII, or raw "
            "internal notes through this Q&A surface.",
            ["SENSITIVE_DATA_BLOCKED"],
            "Ask about aggregate governed workforce or delivery facts only.",
            True,
        ),
    }
    if category in blocked:
        answer, limitations, next_step, escalation = blocked[category]
        return (
            ClientIntelligenceAnswerAvailability.UNSUPPORTED,
            ClientIntelligenceConfidenceLevel.INSUFFICIENT,
            answer,
            limitations,
            next_step,
            escalation,
            [],
            True,
        )
    return (
        ClientIntelligenceAnswerAvailability.UNSUPPORTED,
        ClientIntelligenceConfidenceLevel.INSUFFICIENT,
        "That question is outside the supported Client Intelligence evidence scope.",
        ["QUESTION_UNSUPPORTED"],
        "Ask about Project Health, Delivery Confidence, milestones, risks, trends, or reports.",
        False,
        [],
        True,
    )


_BLOCKED_CATEGORIES = frozenset(
    {
        ClientIntelligenceQuestionCategory.INJECTION,
        ClientIntelligenceQuestionCategory.COMMITMENT,
        ClientIntelligenceQuestionCategory.CROSS_SCOPE,
        ClientIntelligenceQuestionCategory.SENSITIVE,
        ClientIntelligenceQuestionCategory.UNSUPPORTED,
    }
)


async def answer_client_intelligence_question(
    session: AsyncSession,
    current_user: CurrentUser,
    project_id: UUID,
    payload: ClientIntelligenceQuestionCreate,
) -> tuple[ClientIntelligenceQueryRead, AgentQuery]:
    """Authorize, ground, answer, and persist one Client Intelligence query."""
    if current_user.role not in _ALLOWED_QA_ROLES:
        raise ApiError(
            403,
            "FORBIDDEN",
            "Client Intelligence Q&A requires Delivery Manager, BSG Leadership, "
            "Super Admin, or Client role.",
        )

    question = payload.question
    project = await get_visible_project(session, project_id, current_user)
    assert project.id == project_id
    visibility_mode = _visibility_for_qa_user(current_user)

    started = perf_counter()
    category = classify_client_intelligence_question(question)

    pack: ClientEvidencePack | None = None
    availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
    confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
    answer_text = ""
    limitations: list[str] = []
    next_step: str | None = None
    escalation = False
    insufficient = True
    evidence_inputs: list[EvidenceInput] = []
    source_agents: list[str] = []
    as_of = None
    period_start = None
    period_end = None
    source_fingerprint = None
    model_used: str | None = None

    try:
        if category == ClientIntelligenceQuestionCategory.REPORTS:
            pack = await build_client_evidence_pack(
                session,
                current_user,
                project_id,
                visibility_mode=visibility_mode,
            )
            source_fingerprint = pack.source_fingerprint
            as_of = pack.reporting_period.as_of
            period_start = pack.reporting_period.start_date
            period_end = pack.reporting_period.end_date
            answer_text, evidence_inputs, limitations = await _load_report_evidence(
                session,
                project_id,
                pack_source_fingerprint=source_fingerprint,
                visibility=visibility_mode,
            )
            if evidence_inputs:
                availability = ClientIntelligenceAnswerAvailability.ANSWERED
                confidence = ClientIntelligenceConfidenceLevel.MEDIUM
                insufficient = False
                next_step = "Open Approved & Sent Reports for full bodies."
                source_agents = [SourceAgent.CLIENT_INTELLIGENCE.value]
            else:
                next_step = "Create and approve a Client Intelligence report first."
        elif category == ClientIntelligenceQuestionCategory.CONFIDENCE_HISTORY:
            from app.services.client_intelligence import build_delivery_confidence_history

            pack = await build_client_evidence_pack(
                session,
                current_user,
                project_id,
                visibility_mode=visibility_mode,
            )
            source_fingerprint = pack.source_fingerprint
            as_of = pack.reporting_period.as_of
            period_start = pack.reporting_period.start_date
            period_end = pack.reporting_period.end_date
            pack_by_key = {
                (ref.source_table, ref.source_row_id): ref for ref in pack.evidence
            }
            history = await build_delivery_confidence_history(
                session, current_user, project_id
            )
            points = list(history.points)
            if not points:
                answer_text = (
                    "No Delivery Confidence history points are available for this project."
                )
                limitations = sorted(
                    set(list(history.limitations) + ["CONFIDENCE_HISTORY_UNAVAILABLE"])
                )
                next_step = "Wait for Delivery Confidence scores to be persisted, then retry."
                insufficient = True
                availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
                confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
                evidence_inputs = []
            elif len(points) == 1:
                point = points[0]
                answer_text = (
                    f"The latest governed Delivery Confidence point is {point.score_pct}% "
                    f"({point.confidence_status}) as of {point.observed_at.date().isoformat()}. "
                    "A trend cannot be determined from a single history point."
                )
                limitations = sorted(
                    set(
                        list(history.limitations)
                        + ["CONFIDENCE_TREND_REQUIRES_MULTIPLE_POINTS"]
                    )
                )
                next_step = (
                    "Wait for additional Delivery Confidence scores before asking for a trend."
                )
                insufficient = True
                availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
                confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
                ref = pack_by_key.get(
                    ("delivery_confidence_scores", point.source_row_id)
                )
                evidence_inputs = (
                    [
                        EvidenceInput(
                            source_table=ref.source_table,
                            source_row_id=ref.source_row_id,
                            description=ref.description,
                            visibility=ref.visibility.value,
                            observed_at=ref.observed_at,
                            claim_keys=tuple(ref.claim_keys),
                            pack_source_fingerprint=source_fingerprint,
                        )
                    ]
                    if ref is not None and ref.claim_keys
                    else []
                )
                source_agents = [SourceAgent.DELIVERY_PERFORMANCE.value]
            else:
                first = points[0]
                last = points[-1]
                answer_text = (
                    f"Delivery Confidence moved from {first.score_pct}% "
                    f"({first.confidence_status}) on {first.observed_at.date().isoformat()} "
                    f"to {last.score_pct}% ({last.confidence_status}) on "
                    f"{last.observed_at.date().isoformat()} across {len(points)} "
                    "governed history points (oldest to newest)."
                )
                limitations = sorted(set(history.limitations))
                next_step = "Open the Delivery Confidence sparkline in Client Detail."
                matched: list[EvidenceInput] = []
                for point in points:
                    ref = pack_by_key.get(
                        ("delivery_confidence_scores", point.source_row_id)
                    )
                    if ref is None or not ref.claim_keys:
                        matched = []
                        break
                    matched.append(
                        EvidenceInput(
                            source_table=ref.source_table,
                            source_row_id=ref.source_row_id,
                            description=ref.description,
                            visibility=ref.visibility.value,
                            observed_at=ref.observed_at,
                            claim_keys=tuple(ref.claim_keys),
                            pack_source_fingerprint=source_fingerprint,
                        )
                    )
                if matched:
                    insufficient = False
                    availability = ClientIntelligenceAnswerAvailability.ANSWERED
                    confidence = ClientIntelligenceConfidenceLevel.MEDIUM
                    evidence_inputs = matched
                    source_agents = [SourceAgent.DELIVERY_PERFORMANCE.value]
                else:
                    insufficient = True
                    availability = (
                        ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
                    )
                    confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
                    evidence_inputs = []
                    limitations = sorted(
                        set(limitations + ["CONFIDENCE_HISTORY_EVIDENCE_UNMATCHED"])
                    )
                    next_step = (
                        "Retry after Delivery Confidence scores are present in the "
                        "governed evidence pack."
                    )
        elif category in _BLOCKED_CATEGORIES:
            (
                availability,
                confidence,
                answer_text,
                limitations,
                next_step,
                escalation,
                _refs,
                insufficient,
            ) = _build_category_answer_without_pack(category)
        else:
            pack = await build_client_evidence_pack(
                session,
                current_user,
                project_id,
                visibility_mode=visibility_mode,
            )
            as_of = pack.reporting_period.as_of
            period_start = pack.reporting_period.start_date
            period_end = pack.reporting_period.end_date
            source_fingerprint = pack.source_fingerprint
            (
                availability,
                confidence,
                answer_text,
                limitations,
                next_step,
                escalation,
                refs,
                insufficient,
            ) = _build_category_answer(
                category,
                pack,
                question=question,
                client_safe=visibility_mode == EvidenceVisibility.CLIENT_SAFE,
            )
            if visibility_mode == EvidenceVisibility.CLIENT_SAFE:
                limitations = _client_facing_limitations(limitations)
            evidence_inputs = _dedupe_evidence(
                refs,
                pack_source_fingerprint=source_fingerprint,
            )
            source_agents = _agents_from_refs(refs)
            # Generative LLM polish is intentionally skipped until complete
            # structured claim validation exists. Deterministic answer is final.
            model_used = None

        if PLACEHOLDER_ANSWER in answer_text:
            raise ApiError(
                500,
                "PLACEHOLDER_ANSWER_FORBIDDEN",
                "Client Intelligence refused to return a placeholder answer.",
            )

        if (
            availability == ClientIntelligenceAnswerAvailability.ANSWERED
            and not evidence_inputs
        ):
            availability = ClientIntelligenceAnswerAvailability.INSUFFICIENT_EVIDENCE
            confidence = ClientIntelligenceConfidenceLevel.INSUFFICIENT
            insufficient = True
            limitations = sorted(set(limitations + ["ZERO_EVIDENCE_BLOCKED"]))
            next_step = next_step or "Retry after governed evidence is available."

        if current_user.role == AppRole.CLIENT:
            limitations = _client_facing_limitations(limitations)

        if availability == ClientIntelligenceAnswerAvailability.ANSWERED:
            from app.services.evidence import require_complete_evidence_provenance

            require_complete_evidence_provenance(evidence_inputs)
            if not source_fingerprint:
                raise ApiError(
                    409,
                    "EVIDENCE_FINGERPRINT_REQUIRED",
                    "Answered Client Intelligence queries require a pack fingerprint.",
                )

        latency_ms = max(0, int((perf_counter() - started) * 1000))
        retrieval = ClientIntelligenceQueryRetrievalParams(
            answer_availability=availability,
            confidence_level=confidence,
            category=category,
            limitations=limitations,
            next_step=next_step,
            escalation_required=escalation,
            insufficient_evidence=insufficient,
            source_agents=source_agents,
            as_of=as_of,
            reporting_period_start=period_start,
            reporting_period_end=period_end,
            source_fingerprint=source_fingerprint,
        )

        query = AgentQuery(
            user_id=current_user.id,
            org_id=project.org_id,
            project_id=project_id,
            agent_name=CLIENT_INTERACTION_AGENT_NAME,
            query_text=question,
            answer_text=answer_text,
            model_used=model_used,
            latency_ms=latency_ms,
            retrieval_params=retrieval.model_dump(mode="json"),
        )
        session.add(query)
        await session.flush()

        link_rows: list[AgentQueryEvidenceLink] = []
        for item in evidence_inputs:
            link = AgentQueryEvidenceLink(
                agent_query_id=query.id,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
                visibility=item.visibility,
                observed_at=item.observed_at,
                claim_keys=list(item.claim_keys or ()),
                pack_source_fingerprint=item.pack_source_fingerprint or source_fingerprint,
            )
            session.add(link)
            link_rows.append(link)
        await session.flush()
        return _to_query_read(query, link_rows), query
    except Exception:
        await session.rollback()
        raise
