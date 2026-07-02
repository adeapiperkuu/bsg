"""Delivery Agent chat — grounded answers from live delivery performance data."""

from __future__ import annotations

import difflib
import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.schemas.chat_schema import (
    DeliveryChatConversationRead,
    DeliveryChatRead,
    DeliveryChatSource,
    DeliveryChatTurnRead,
)
from app.agents.delivery.services.dashboard_service import get_dashboard_data, get_portfolio_data
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink, AppRole
from app.services.llm.client import LLMClient
from app.services.scoping import get_visible_project

logger = logging.getLogger(__name__)

AGENT_NAME = "delivery_performance_agent"
MAX_HISTORY_TURNS = 3
MAX_HISTORY_ANSWER_CHARS = 450
# Cap on turns returned by the conversation-restore endpoint — independent of
# MAX_HISTORY_TURNS, which only bounds how much history is fed back into the LLM prompt.
MAX_CONVERSATION_TURNS_RETURNED = 50

EVIDENCE_SOURCE_TABLE_BY_TYPE = {
    "risk": "risk_alerts",
    "bottleneck": "bottlenecks",
    "milestone": "milestones",
}
EVIDENCE_TYPE_BY_SOURCE_TABLE = {table: kind for kind, table in EVIDENCE_SOURCE_TABLE_BY_TYPE.items()}


def _source_from_risk(risk: dict[str, Any]) -> DeliveryChatSource:
    return DeliveryChatSource(
        title=str(risk.get("title") or "Delivery risk"),
        type="risk",
        id=risk.get("id"),
        description=str(risk.get("detail") or "") or None,
    )


def _source_from_bottleneck(bottleneck: dict[str, Any]) -> DeliveryChatSource:
    return DeliveryChatSource(
        title=str(bottleneck.get("title") or "Bottleneck"),
        type="bottleneck",
        id=bottleneck.get("id"),
        description=str(bottleneck.get("detail") or "") or None,
    )


def _source_from_milestone(milestone: dict[str, Any]) -> DeliveryChatSource:
    return DeliveryChatSource(
        title=str(milestone.get("name") or "Milestone"),
        type="milestone",
        id=milestone.get("id"),
        description=str(milestone.get("status") or "") or None,
    )


MILESTONE_EVIDENCE_STATUSES = {"at_risk", "missed"}


def _collect_sources(dashboard: dict[str, Any]) -> list[DeliveryChatSource]:
    sources: list[DeliveryChatSource] = []
    for risk in dashboard.get("risks") or []:
        if isinstance(risk, dict):
            sources.append(_source_from_risk(risk))
    for bottleneck in dashboard.get("bottlenecks") or []:
        if isinstance(bottleneck, dict):
            sources.append(_source_from_bottleneck(bottleneck))
    for milestone in dashboard.get("milestones") or []:
        if isinstance(milestone, dict) and milestone.get("status") in MILESTONE_EVIDENCE_STATUSES:
            sources.append(_source_from_milestone(milestone))
    return sources


def _severity_score(dashboard: dict[str, Any]) -> float:
    traffic = str(dashboard.get("traffic_light") or "green")
    traffic_weight = {"red": 30.0, "yellow": 15.0, "green": 0.0}.get(traffic, 10.0)
    confidence = float(dashboard.get("confidence") or 0)
    open_risks = len(dashboard.get("risks") or [])
    open_bottlenecks = len(dashboard.get("bottlenecks") or [])
    return traffic_weight + open_risks * 5 + open_bottlenecks * 4 + max(0.0, 100.0 - confidence) / 5


ROOT_CAUSE_LABELS: dict[str, str] = {
    "confidence_shortfall": "Schedule confidence shortfall",
    "throughput_decline": "Throughput decline",
    "milestone_urgency": "Milestone urgency",
    "open_bottlenecks": "Open bottlenecks",
    "quality_drift": "Quality drift",
}


def _extract_root_causes(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    overview = dashboard.get("overview")
    if not isinstance(overview, dict):
        return []
    calculated_risk = overview.get("calculated_risk")
    if not isinstance(calculated_risk, dict):
        return []
    causes = calculated_risk.get("contributing_causes")
    if not isinstance(causes, dict):
        return []
    ranked = sorted(
        (
            {
                "cause": ROOT_CAUSE_LABELS.get(key, key.replace("_", " ")),
                "weight": float(value) if isinstance(value, (int, float)) else 0.0,
            }
            for key, value in causes.items()
            if isinstance(value, (int, float)) and float(value) > 0
        ),
        key=lambda item: item["weight"],
        reverse=True,
    )
    return ranked[:4]


def _project_operational_brief(dashboard: dict[str, Any], project_id: Any) -> dict[str, Any]:
    overview = dashboard.get("overview") if isinstance(dashboard.get("overview"), dict) else {}
    project = overview.get("project") if isinstance(overview.get("project"), dict) else {}
    risks = dashboard.get("risks") or []
    bottlenecks = dashboard.get("bottlenecks") or []
    risk_titles = [str(r.get("title") or "") for r in risks if isinstance(r, dict)]
    bottleneck_titles = [str(b.get("title") or "") for b in bottlenecks if isinstance(b, dict)]
    root_causes = _extract_root_causes(dashboard)
    confidence = float(dashboard.get("confidence") or 0)
    traffic = str(dashboard.get("traffic_light") or "green")
    return {
        "project_id": project_id,
        "project_name": project.get("name"),
        "traffic_light": traffic,
        "schedule_confidence_pct": confidence,
        "open_risks": len(risks),
        "open_bottlenecks": len(bottlenecks),
        "risk_titles": [title for title in risk_titles if title],
        "bottleneck_titles": [title for title in bottleneck_titles if title],
        "top_root_causes": root_causes,
        "severity_score": round(_severity_score(dashboard), 1),
        "urgency_tier": (
            "critical" if traffic == "red" and confidence < 15
            else "high" if traffic == "red" or confidence < 25
            else "elevated" if traffic == "yellow"
            else "stable"
        ),
    }


def _portfolio_summary(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for entry in portfolio.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        dashboard = entry.get("dashboard")
        if not isinstance(dashboard, dict):
            continue
        summaries.append(_project_operational_brief(dashboard, entry.get("project_id")))
    summaries.sort(key=lambda item: float(item.get("severity_score") or 0), reverse=True)
    return summaries


def _match_cited_sources(
    catalog: list[DeliveryChatSource],
    cited_titles: list[str],
    answer_text: str,
) -> list[DeliveryChatSource]:
    if not catalog:
        return []

    matched: list[DeliveryChatSource] = []
    seen: set[str] = set()
    answer_lower = answer_text.lower()

    def try_add(source: DeliveryChatSource) -> None:
        key = source.title.lower()
        if key in seen:
            return
        seen.add(key)
        matched.append(source)

    for cited in cited_titles:
        cited_lower = cited.lower().strip()
        if not cited_lower:
            continue
        for source in catalog:
            title_lower = source.title.lower()
            if title_lower == cited_lower or cited_lower in title_lower or title_lower in cited_lower:
                try_add(source)

    if not matched:
        for source in catalog:
            if source.title.lower() in answer_lower:
                try_add(source)

    return matched[:6]


def _detect_portfolio_patterns(portfolio: dict[str, Any]) -> dict[str, Any]:
    risk_themes: Counter[str] = Counter()
    bottleneck_themes: Counter[str] = Counter()
    root_cause_themes: Counter[str] = Counter()
    red_projects = 0
    low_confidence_projects = 0

    for entry in portfolio.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        dashboard = entry.get("dashboard")
        if not isinstance(dashboard, dict):
            continue
        if str(dashboard.get("traffic_light")) == "red":
            red_projects += 1
        if float(dashboard.get("confidence") or 0) < 15:
            low_confidence_projects += 1
        for risk in dashboard.get("risks") or []:
            if isinstance(risk, dict) and risk.get("title"):
                risk_themes[str(risk["title"]).lower()] += 1
        for bottleneck in dashboard.get("bottlenecks") or []:
            if isinstance(bottleneck, dict) and bottleneck.get("title"):
                bottleneck_themes[str(bottleneck["title"]).lower()] += 1
        for cause in _extract_root_causes(dashboard):
            root_cause_themes[str(cause["cause"]).lower()] += 1

    def top_items(counter: Counter[str], limit: int = 4) -> list[dict[str, Any]]:
        return [
            {"theme": theme, "project_count": count}
            for theme, count in counter.most_common(limit)
            if count >= 1
        ]

    return {
        "red_status_project_count": red_projects,
        "sub_15pct_confidence_count": low_confidence_projects,
        "recurring_risk_themes": top_items(risk_themes),
        "recurring_bottleneck_themes": top_items(bottleneck_themes),
        "recurring_root_causes": top_items(root_cause_themes),
    }


def _portfolio_patterns_summary(patterns: dict[str, Any]) -> str:
    """Condense the full portfolio pattern breakdown into one brief sentence."""
    red_count = int(patterns.get("red_status_project_count") or 0)
    low_confidence_count = int(patterns.get("sub_15pct_confidence_count") or 0)
    top_theme: str | None = None
    for key in ("recurring_root_causes", "recurring_risk_themes", "recurring_bottleneck_themes"):
        items = patterns.get(key) or []
        if items and isinstance(items[0], dict) and items[0].get("theme"):
            top_theme = str(items[0]["theme"])
            break
    theme_clause = f"; most recurring theme: {top_theme}" if top_theme else ""
    return (
        f"{red_count} project(s) are red-status and {low_confidence_count} are below 15% "
        f"schedule confidence across the portfolio{theme_clause}."
    )


def _classify_question(message: str) -> str:
    q = message.lower()
    portfolio_signals = (
        "which project",
        "at risk",
        "portfolio",
        "leadership",
        "this week",
        "focus",
        "driving",
        "confidence down",
        "decline",
        "blocking delivery",
        "what's blocking",
        "whats blocking",
        "throughput",
        "milestone",
        "slip",
        "attention",
        "priorit",
        "across",
        "all project",
        "where should",
        "need attention",
    )
    if any(signal in q for signal in portfolio_signals):
        return "portfolio"
    return "project"


# ── Project-reference resolution ──────────────────────────────────────────────
# Resolve project names in the user's query BEFORE calling the LLM so that
# ambiguous, misspelled, or nonexistent references are caught deterministically.

_MATCH_HIGH_CONFIDENCE: float = 0.82
_MATCH_MIN_DETECTION: float = 0.55

# Function words that are never distinctive identifiers for a project name.
_MATCH_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "for", "of", "in", "on",
    "at", "to", "with", "about", "and", "or", "this", "that", "has", "have",
    "had", "its", "our", "your", "their", "what", "which", "where", "when",
    "who", "how", "why", "do", "does", "did", "tell", "show", "give", "me",
    "us",
})

# Domain words that appear both in delivery conversation AND in project names —
# exclude them from token-level matching to prevent false positives.
_MATCH_GENERIC_PROJECT_TERMS: frozenset[str] = frozenset({
    "project", "delivery", "sprint", "phase", "release", "initiative",
    "program", "work", "task", "service", "system", "platform", "pipeline",
    "workflow", "process", "team", "group", "module", "component", "feature",
    "product", "dashboard", "portal", "app", "application", "api",
})


@dataclass
class _AvailableProject:
    name: str
    project_id: Any = None  # UUID | None


@dataclass
class _ProjectMatchResult:
    """Outcome of resolving project references in a user query."""
    # no_reference | exact | fuzzy | ambiguous | not_found
    status: str
    # The query fragment used as the reference (for user-facing messages).
    reference: str = ""
    # Set for exact/fuzzy — the name of the project we matched to.
    matched_project: str | None = None
    # Set for ambiguous — all candidate project names.
    candidates: list[str] = field(default_factory=list)


def _normalize_for_matching(text: str) -> str:
    """Lowercase, collapse punctuation to spaces, strip edges."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _distinctive_tokens(name_norm: str) -> list[str]:
    """Tokens from a normalised project name that are long and non-generic.

    These are the tokens used for token-overlap matching. Excluding stopwords
    and common delivery terms prevents words like 'delivery' or 'sprint' from
    falsely triggering matches on portfolio-level questions.
    """
    return [
        w for w in name_norm.split()
        if len(w) >= 4
        and w not in _MATCH_STOPWORDS
        and w not in _MATCH_GENERIC_PROJECT_TERMS
    ]


def _best_window_ratio(query_words: list[str], name_words: list[str]) -> float:
    """Highest SequenceMatcher ratio between *name* and any same-length (±1) window
    of *query* words.  Used as a fallback when token overlap is inconclusive."""
    n = len(name_words)
    if n == 0 or not query_words:
        return 0.0
    name_str = " ".join(name_words)
    best = 0.0
    for w in range(max(1, n - 1), min(n + 2, len(query_words) + 1)):
        for i in range(len(query_words) - w + 1):
            window = " ".join(query_words[i : i + w])
            r = difflib.SequenceMatcher(None, name_str, window).ratio()
            if r > best:
                best = r
    return best


def _score_project_match(query_norm: str, name_norm: str) -> float:
    """Return a 0–1 similarity score between *query* and *project name*.

    Priority order:
    1. Exact substring containment → 1.0
    2. All distinctive name tokens present in the query → 0.95
    3. ≥ 50 % of distinctive tokens present → 0.70–0.90 (scaled)
    4. Window-based character-level similarity (SequenceMatcher)
    """
    if name_norm in query_norm:
        return 1.0

    query_words = query_norm.split()
    name_words = name_norm.split()

    distinctive = _distinctive_tokens(name_norm)
    if distinctive:
        query_token_set = set(query_words)
        hits = [t for t in distinctive if t in query_token_set]
        fraction = len(hits) / len(distinctive)
        if fraction >= 1.0:
            return 0.95
        if fraction >= 0.5:
            return 0.70 + fraction * 0.20  # 0.80 at 50 %, 0.90 at 100 %

    return _best_window_ratio(query_words, name_words)


def _check_ambiguous_token(
    query_norm: str,
    available: list[_AvailableProject],
) -> tuple[str, list[str]] | None:
    """Return *(token, [matching project names])* if a single query token appears
    in two or more available project names.  Returns None otherwise.

    This catches cases like 'Tell me about Apollo' when both 'Apollo API' and
    'Apollo Dashboard' exist — the user's reference is unambiguous in intent but
    cannot be resolved without clarification.
    """
    for token in query_norm.split():
        if (
            len(token) < 4
            or token in _MATCH_STOPWORDS
            or token in _MATCH_GENERIC_PROJECT_TERMS
        ):
            continue
        hits = [
            p.name
            for p in available
            if token in _normalize_for_matching(p.name).split()
        ]
        if len(hits) >= 2:
            return token, hits
    return None


def _extract_proper_noun_candidate(message: str) -> str | None:
    """Return the first capitalised word in the query (excluding sentence-start
    and generic delivery terms) that might be an unknown project name reference.

    Used only for NOT_FOUND detection — we require ≥ 5 characters to reduce
    false positives from abbreviations and mid-sentence pronouns.
    """
    words = message.split()
    for word in words[1:]:
        clean = re.sub(r"[^\w]", "", word)
        if (
            clean
            and clean[0].isupper()
            and len(clean) >= 5
            and clean.lower() not in _MATCH_STOPWORDS
            and clean.lower() not in _MATCH_GENERIC_PROJECT_TERMS
        ):
            return clean
    return None


def _resolve_project_references(
    message: str,
    available: list[_AvailableProject],
) -> _ProjectMatchResult:
    """Resolve project name references in *message* against *available* projects.

    Resolution order (first match wins):
    1. A distinctive query token appears in 2+ project names → AMBIGUOUS
    2. Exact substring match (normalised) against a single project → EXACT
    3. Single project scores ≥ HIGH_CONFIDENCE → FUZZY
    4. No high-confidence match, but a proper-noun candidate is present and the
       best score ≥ MIN_DETECTION → NOT_FOUND
    5. Otherwise → NO_REFERENCE (no identifiable project reference)
    """
    if not available:
        return _ProjectMatchResult(status="no_reference")

    q = _normalize_for_matching(message)

    # Step 1 — ambiguous token check, but an exact match always takes priority.
    # Example: "status of apollo" with projects "Apollo" and "Apollo Plus" —
    # "apollo" appears in both names, but the full name "Apollo" is an exact
    # substring match and should resolve without asking for clarification.
    ambiguity = _check_ambiguous_token(q, available)
    if ambiguity is not None:
        token, candidates = ambiguity
        exact_for_ambiguity = [
            p for p in available if _normalize_for_matching(p.name) in q
        ]
        if len(exact_for_ambiguity) == 1:
            return _ProjectMatchResult(status="exact", matched_project=exact_for_ambiguity[0].name)
        if not exact_for_ambiguity:
            return _ProjectMatchResult(
                status="ambiguous",
                reference=token,
                candidates=candidates,
            )

    # Step 2/3 — score every project
    scored = sorted(
        (
            (p, _score_project_match(q, _normalize_for_matching(p.name)))
            for p in available
        ),
        key=lambda x: x[1],
        reverse=True,
    )
    best_project, best_score = scored[0]

    if best_score >= 1.0:
        return _ProjectMatchResult(status="exact", matched_project=best_project.name)

    if best_score >= _MATCH_HIGH_CONFIDENCE:
        return _ProjectMatchResult(
            status="fuzzy",
            reference=q,
            matched_project=best_project.name,
        )

    # Step 4 — not-found: a proper-noun candidate is present but nothing matched.
    # We rely on the ≥5-char / non-generic filter in _extract_proper_noun_candidate
    # to keep false-positive rates low rather than requiring a minimum similarity score
    # (which would miss cases like "Zephyr" vs "Alpha Delivery" where there is no
    # character-level overlap at all).
    candidate_ref = _extract_proper_noun_candidate(message)
    if candidate_ref:
        return _ProjectMatchResult(status="not_found", reference=candidate_ref)

    return _ProjectMatchResult(status="no_reference")


def _list_available_projects(
    portfolio: dict[str, Any],
    project_dashboard: dict[str, Any] | None,
    project_id: UUID | None,
) -> list[_AvailableProject]:
    """Build a flat, deduplicated list of all projects visible to the user.

    The focused project (if any) is always first so it has the highest priority
    in scoring when the user asks about a project they already have open.
    """
    projects: list[_AvailableProject] = []
    seen_ids: set[Any] = set()

    def _name_from_dashboard(dash: dict[str, Any]) -> str | None:
        overview = dash.get("overview") if isinstance(dash.get("overview"), dict) else {}
        p = overview.get("project") if isinstance(overview.get("project"), dict) else {}
        name = p.get("name")
        return str(name).strip() if isinstance(name, str) and name.strip() else None

    if project_dashboard is not None:
        name = _name_from_dashboard(project_dashboard)
        if name:
            projects.append(_AvailableProject(name=name, project_id=project_id))
            if project_id is not None:
                seen_ids.add(project_id)

    for entry in portfolio.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("project_id")
        if pid in seen_ids:
            continue
        dashboard = entry.get("dashboard")
        if not isinstance(dashboard, dict):
            continue
        name = _name_from_dashboard(dashboard)
        if name:
            projects.append(_AvailableProject(name=name, project_id=pid))
            if pid is not None:
                seen_ids.add(pid)

    return projects


def _project_not_found_answer(reference: str, available: list[_AvailableProject]) -> str:
    if available:
        name_list = "\n".join(f"- {p.name}" for p in available)
        return (
            f"I couldn't find a project matching **{reference}** in your available data.\n\n"
            f"The projects currently available are:\n{name_list}\n\n"
            "Please check the name and try again, or ask a portfolio-level question."
        )
    return (
        f"I couldn't find a project matching **{reference}**. "
        "No project data is currently available in your portfolio."
    )


def _project_ambiguous_answer(reference: str, candidates: list[str]) -> str:
    candidate_list = "\n".join(f"- {c}" for c in candidates)
    return (
        f'Your question could refer to more than one project matching **"{reference}"**:\n\n'
        f"{candidate_list}\n\n"
        "Could you clarify which project you mean?"
    )


def _fuzzy_match_prefix(matched_project: str) -> str:
    return f"> Matched your question to project **{matched_project}**.\n\n"


# ── Context building ───────────────────────────────────────────────────────────

def _build_context(
    *,
    project_dashboard: dict[str, Any] | None,
    portfolio: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    ranked = _portfolio_summary(portfolio)
    priority_projects = [entry for entry in ranked if entry.get("urgency_tier") != "stable"][:5]
    context: dict[str, Any] = {
        "analyst_directive": (
            "Provide grounded decision support only. Interpret delivery signals — do not invent "
            "staffing numbers, resource allocations, budgets, or business impacts not in the data. "
            "Every recommendation must trace to evidence: confidence levels, risks, bottlenecks, "
            "milestones, or portfolio patterns. State confidence (High/Medium/Low) for conclusions. "
            "Use Immediate / Near-Term / Strategic action categories. When uncertain, say so."
        ),
        "available_data_scope": {
            "has_staffing_data": False,
            "has_budget_data": False,
            "has_sla_data": False,
            "supported_signals": [
                "schedule_confidence_pct",
                "traffic_light_status",
                "open_risks",
                "active_bottlenecks",
                "milestones",
                "root_cause_factors",
                "throughput_metrics",
                "portfolio_pattern_counts",
            ],
        },
        "question_scope": _classify_question(message),
        "portfolio_ranked_by_severity": ranked,
        "leadership_priority_projects": priority_projects,
        "portfolio_patterns": _detect_portfolio_patterns(portfolio),
        "at_risk_project_count": sum(
            1 for entry in ranked if str(entry.get("traffic_light")) != "green"
        ),
    }
    if context["question_scope"] == "project":
        del context["portfolio_ranked_by_severity"]
        context["portfolio_patterns"] = _portfolio_patterns_summary(context["portfolio_patterns"])
    if project_dashboard is not None:
        brief = _project_operational_brief(project_dashboard, None)
        context["focused_project"] = {
            **brief,
            "milestones": project_dashboard.get("milestones"),
            "risks": project_dashboard.get("risks"),
            "bottlenecks": project_dashboard.get("bottlenecks"),
        }
    return context


async def _load_conversation_history(
    session: AsyncSession,
    current_user: CurrentUser,
    anchor: AgentQuery | None,
) -> list[dict[str, str]]:
    # TODO(perf): agent_queries only has an index on org_id (see
    # 20260622090000_initial_backend_schema.sql); this query and
    # load_delivery_chat_conversation's equivalent filter on
    # (user_id, agent_name, project_id, created_at). A composite index would help once a
    # user accumulates a large conversation history. Not added here — needs a migration.
    if anchor is None or anchor.user_id != current_user.id or anchor.agent_name != AGENT_NAME:
        return []

    rows = await session.execute(
        select(AgentQuery)
        .where(
            AgentQuery.user_id == current_user.id,
            AgentQuery.agent_name == AGENT_NAME,
            AgentQuery.project_id == anchor.project_id,
            AgentQuery.created_at >= anchor.created_at,
        )
        .order_by(AgentQuery.created_at.asc())
        .limit(MAX_HISTORY_TURNS * 2)
    )
    history: list[dict[str, str]] = []
    for row in rows.scalars():
        history.append({"role": "user", "content": row.query_text})
        history.append(
            {"role": "assistant", "content": row.answer_text[:MAX_HISTORY_ANSWER_CHARS]}
        )
    return history


def _not_configured_answer() -> str:
    return (
        "## Executive Assessment\n"
        "Delivery AI is not configured — leadership decision support is unavailable.\n\n"
        "## Recommended Leadership Actions\n"
        "1. Set OPENAI_API_KEY to enable the Delivery Agent."
    )


def _empty_answer_fallback() -> str:
    return (
        "## Executive Assessment\n"
        "Delivery analysis could not be generated from current data.\n\n"
        "## Recommended Leadership Actions\n"
        "1. Verify delivery data is loaded and retry."
    )


def _sse(data: dict[str, Any]) -> str:
    """Format a dict as a single SSE line for the streaming chat endpoint."""
    return f"data: {json.dumps(data, default=str)}\n\n"


@dataclass(frozen=True)
class _ChatRequestContext:
    resolved_project_id: UUID | None
    context: dict[str, Any]
    history: list[dict[str, str]]
    evidence_catalog_sent: list[DeliveryChatSource]
    anchor: AgentQuery | None
    available_projects: list[_AvailableProject]


async def _prepare_chat_request(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    message: str,
    project_id: UUID | None,
    conversation_id: UUID | None,
) -> _ChatRequestContext:
    """Shared grounding/context-building logic for both the streaming and
    non-streaming chat paths. Does not call the LLM or persist anything."""
    question_scope = _classify_question(message)

    anchor: AgentQuery | None = None
    if conversation_id is not None:
        anchor = await session.get(AgentQuery, conversation_id)

    resolved_project_id = project_id
    if resolved_project_id is None and anchor is not None and anchor.user_id == current_user.id:
        resolved_project_id = anchor.project_id

    project_dashboard: dict[str, Any] | None = None
    if resolved_project_id is not None:
        project_dashboard = await get_dashboard_data(
            session=session,
            project_id=resolved_project_id,
            current_user=current_user,
        )

    # Project-scoped questions already have the focused project's dashboard above —
    # avoid recomputing the full portfolio (all-projects scoring) on every chat turn.
    if question_scope == "portfolio" or resolved_project_id is None:
        portfolio = await get_portfolio_data(session=session, current_user=current_user)
    else:
        portfolio = {"projects": []}

    context = _build_context(
        project_dashboard=project_dashboard,
        portfolio=portfolio,
        message=message,
    )

    evidence_catalog: list[DeliveryChatSource] = []
    if project_dashboard is not None:
        evidence_catalog = _collect_sources(project_dashboard)
    for entry in portfolio.get("projects") or []:
        if len(evidence_catalog) >= 20:
            break
        if not isinstance(entry, dict):
            continue
        dashboard = entry.get("dashboard")
        if isinstance(dashboard, dict):
            evidence_catalog.extend(_collect_sources(dashboard))

    history = await _load_conversation_history(session, current_user, anchor)
    available_projects = _list_available_projects(portfolio, project_dashboard, resolved_project_id)

    return _ChatRequestContext(
        resolved_project_id=resolved_project_id,
        context=context,
        history=history,
        evidence_catalog_sent=evidence_catalog[:20],
        anchor=anchor,
        available_projects=available_projects,
    )


def _persist_chat_turn(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    resolved_project_id: UUID | None,
    message: str,
    answer: str,
    model_used: str,
    started: float,
    response_sources: list[DeliveryChatSource],
) -> AgentQuery:
    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=resolved_project_id,
        agent_name=AGENT_NAME,
        query_text=message,
        answer_text=answer,
        model_used=model_used,
        latency_ms=int((perf_counter() - started) * 1000),
    )
    session.add(query)
    for source in response_sources:
        if source.id is not None:
            table = EVIDENCE_SOURCE_TABLE_BY_TYPE.get(source.type, "delivery_evidence")
            session.add(
                AgentQueryEvidenceLink(
                    agent_query_id=query.id,
                    source_table=table,
                    source_row_id=source.id,
                    description=source.title,
                )
            )
    return query


def _log_llm_failure(
    current_user: CurrentUser,
    *,
    project_id: UUID | None,
    conversation_id: UUID | None,
    error_type: str,
) -> None:
    """Log an LLM call failure with identifying context only — never message content."""
    logger.warning(
        "Delivery chat LLM call failed user_id=%s org_id=%s project_id=%s conversation_id=%s exception_type=%s",
        current_user.id,
        current_user.org_id,
        project_id,
        conversation_id,
        error_type,
    )


async def answer_delivery_chat(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    message: str,
    project_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> DeliveryChatRead:
    """Answer a delivery operations question using live dashboard context."""
    message = message.strip()
    settings = get_settings()
    if not (settings.openai_api_key or settings.llm_api_key):
        return DeliveryChatRead(
            answer=_not_configured_answer(),
            sources=[],
            conversation_id=conversation_id or uuid4(),
        )

    started = perf_counter()
    prepared = await _prepare_chat_request(
        session, current_user, message=message, project_id=project_id, conversation_id=conversation_id,
    )

    # Resolve project references before calling the LLM.
    # Skip when a project_id was already provided — the reference is already
    # resolved at the UI/API level and re-checking would only produce false positives.
    resolution: _ProjectMatchResult | None = None
    if prepared.resolved_project_id is None and prepared.available_projects:
        resolution = _resolve_project_references(message, prepared.available_projects)
        if resolution.status == "not_found":
            return DeliveryChatRead(
                answer=_project_not_found_answer(resolution.reference, prepared.available_projects),
                sources=[],
                conversation_id=conversation_id or uuid4(),
            )
        if resolution.status == "ambiguous":
            return DeliveryChatRead(
                answer=_project_ambiguous_answer(resolution.reference, resolution.candidates),
                sources=[],
                conversation_id=conversation_id or uuid4(),
            )

    llm_result = await LLMClient().generate_delivery_answer(
        query=message,
        context=prepared.context,
        history=prepared.history,
        evidence_sources=[source.model_dump(mode="json") for source in prepared.evidence_catalog_sent],
    )

    error_type = llm_result.get("error_type")
    if error_type:
        _log_llm_failure(
            current_user,
            project_id=prepared.resolved_project_id,
            conversation_id=conversation_id,
            error_type=str(error_type),
        )

    answer = str(llm_result.get("answer", "")).strip() or _empty_answer_fallback()

    # Prepend a transparent match notice so the user knows which project was resolved.
    if resolution is not None and resolution.status == "fuzzy" and resolution.matched_project:
        answer = _fuzzy_match_prefix(resolution.matched_project) + answer

    cited_titles = llm_result.get("cited_source_titles")
    cited_title_list = [str(title) for title in cited_titles] if isinstance(cited_titles, list) else []
    response_sources = _match_cited_sources(prepared.evidence_catalog_sent, cited_title_list, answer)

    query = _persist_chat_turn(
        session,
        current_user,
        resolved_project_id=prepared.resolved_project_id,
        message=message,
        answer=answer,
        model_used=str(llm_result.get("model") or ""),
        started=started,
        response_sources=response_sources,
    )
    await session.flush()

    return DeliveryChatRead(
        answer=answer,
        sources=response_sources,
        conversation_id=conversation_id or query.id,
    )


async def stream_delivery_chat(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    message: str,
    project_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> AsyncGenerator[str, None]:
    """SSE-streaming counterpart to answer_delivery_chat.

    Emits `delta` events as answer tokens arrive, then a single `done` event with the
    final answer, sources, and conversation_id. The full turn is persisted once
    streaming completes, exactly as the non-streaming path persists it.
    """
    message = message.strip()
    settings = get_settings()
    if not (settings.openai_api_key or settings.llm_api_key):
        yield _sse(
            {
                "type": "done",
                "answer": _not_configured_answer(),
                "sources": [],
                "conversation_id": str(conversation_id or uuid4()),
            }
        )
        return

    started = perf_counter()
    prepared = await _prepare_chat_request(
        session, current_user, message=message, project_id=project_id, conversation_id=conversation_id,
    )

    # Resolve project references before streaming — same rules as the non-streaming path.
    resolution: _ProjectMatchResult | None = None
    if prepared.resolved_project_id is None and prepared.available_projects:
        resolution = _resolve_project_references(message, prepared.available_projects)
        if resolution.status == "not_found":
            yield _sse(
                {
                    "type": "done",
                    "answer": _project_not_found_answer(resolution.reference, prepared.available_projects),
                    "sources": [],
                    "conversation_id": str(conversation_id or uuid4()),
                }
            )
            return
        if resolution.status == "ambiguous":
            yield _sse(
                {
                    "type": "done",
                    "answer": _project_ambiguous_answer(resolution.reference, resolution.candidates),
                    "sources": [],
                    "conversation_id": str(conversation_id or uuid4()),
                }
            )
            return

    # For fuzzy matches emit the notice as the very first delta so the user sees
    # which project was resolved before the LLM tokens start arriving.
    fuzzy_prefix = ""
    if resolution is not None and resolution.status == "fuzzy" and resolution.matched_project:
        fuzzy_prefix = _fuzzy_match_prefix(resolution.matched_project)
        yield _sse({"type": "delta", "text": fuzzy_prefix})

    accumulated_answer = fuzzy_prefix
    final_answer = ""
    model_used = ""
    cited_title_list: list[str] = []
    error_type: str | None = None

    async for event in LLMClient().stream_delivery_answer(
        query=message,
        context=prepared.context,
        history=prepared.history,
        evidence_sources=[source.model_dump(mode="json") for source in prepared.evidence_catalog_sent],
    ):
        if event.get("type") == "delta":
            text = str(event.get("text") or "")
            if text:
                accumulated_answer += text
                yield _sse({"type": "delta", "text": text})
        elif event.get("type") == "done":
            model_used = str(event.get("model") or "")
            error_type = event.get("error_type")
            cited = event.get("cited_source_titles")
            cited_title_list = [str(title) for title in cited] if isinstance(cited, list) else []
            final_answer = str(event.get("answer") or "").strip()

    if error_type:
        _log_llm_failure(
            current_user,
            project_id=prepared.resolved_project_id,
            conversation_id=conversation_id,
            error_type=str(error_type),
        )

    # On success the deltas already form the full answer; `final_answer` is the
    # parser's authoritative version (handles trailing JSON artifacts). On failure,
    # no deltas were sent — `final_answer` is the only text and becomes the answer.
    answer = (final_answer or accumulated_answer).strip() or _empty_answer_fallback()
    response_sources = _match_cited_sources(prepared.evidence_catalog_sent, cited_title_list, answer)

    query = _persist_chat_turn(
        session,
        current_user,
        resolved_project_id=prepared.resolved_project_id,
        message=message,
        answer=answer,
        model_used=model_used,
        started=started,
        response_sources=response_sources,
    )
    await session.flush()

    yield _sse(
        {
            "type": "done",
            "answer": answer,
            "sources": [source.model_dump(mode="json") for source in response_sources],
            "conversation_id": str(conversation_id or query.id),
        }
    )


async def load_delivery_chat_conversation(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID,
) -> DeliveryChatConversationRead | None:
    """Reload a persisted conversation thread for display after a page refresh.

    Returns None if the conversation does not exist or does not belong to the
    requesting user (super admins may read any conversation, matching the
    elevated-access pattern used elsewhere, e.g. recommendation mutations).
    """
    anchor = await session.get(AgentQuery, conversation_id)
    if anchor is None or anchor.agent_name != AGENT_NAME:
        return None

    is_super_admin = current_user.role == AppRole.SUPER_ADMIN
    if not is_super_admin and anchor.user_id != current_user.id:
        return None

    # Conversation ownership alone is not enough: the user (or a project reassignment
    # since the conversation was recorded) may mean they no longer have access to the
    # project this conversation is scoped to. Reuse the shared project-visibility helper
    # rather than duplicating org/assignment logic here.
    if anchor.project_id is not None:
        try:
            await get_visible_project(session, anchor.project_id, current_user)
        except ApiError:
            return None

    rows = (
        await session.execute(
            select(AgentQuery)
            .where(
                AgentQuery.user_id == anchor.user_id,
                AgentQuery.agent_name == AGENT_NAME,
                AgentQuery.project_id == anchor.project_id,
                AgentQuery.created_at >= anchor.created_at,
            )
            .order_by(AgentQuery.created_at.asc())
            .limit(MAX_CONVERSATION_TURNS_RETURNED)
        )
    ).scalars().all()

    query_ids = [row.id for row in rows]
    evidence_by_query: dict[UUID, list[AgentQueryEvidenceLink]] = defaultdict(list)
    if query_ids:
        evidence_rows = (
            await session.execute(
                select(AgentQueryEvidenceLink).where(AgentQueryEvidenceLink.agent_query_id.in_(query_ids))
            )
        ).scalars().all()
        for link in evidence_rows:
            evidence_by_query[link.agent_query_id].append(link)

    turns = [
        DeliveryChatTurnRead(
            id=row.id,
            query_text=row.query_text,
            answer_text=row.answer_text,
            created_at=row.created_at,
            sources=[
                DeliveryChatSource(
                    title=link.description,
                    type=EVIDENCE_TYPE_BY_SOURCE_TABLE.get(link.source_table, link.source_table),
                    id=link.source_row_id,
                )
                for link in evidence_by_query.get(row.id, [])
            ],
        )
        for row in rows
    ]

    return DeliveryChatConversationRead(
        conversation_id=anchor.id,
        project_id=anchor.project_id,
        turns=turns,
    )
