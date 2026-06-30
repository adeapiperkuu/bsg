"""Delivery Agent chat — grounded answers from live delivery performance data."""

from __future__ import annotations

from collections import Counter
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.schemas.chat_schema import DeliveryChatRead, DeliveryChatSource
from app.agents.delivery.services.dashboard_service import get_dashboard_data, get_portfolio_data
from app.core.config import get_settings
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink
from app.services.llm.client import LLMClient

AGENT_NAME = "delivery_performance_agent"
MAX_HISTORY_TURNS = 3
MAX_HISTORY_ANSWER_CHARS = 450


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


async def answer_delivery_chat(
    session: AsyncSession,
    current_user: CurrentUser,
    *,
    message: str,
    project_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> DeliveryChatRead:
    """Answer a delivery operations question using live dashboard context."""
    settings = get_settings()
    if not (settings.openai_api_key or settings.llm_api_key):
        return DeliveryChatRead(
            answer=(
                "## Executive Assessment\n"
                "Delivery AI is not configured — leadership decision support is unavailable.\n\n"
                "## Recommended Leadership Actions\n"
                "1. Set OPENAI_API_KEY to enable the Delivery Agent."
            ),
            sources=[],
            conversation_id=conversation_id or uuid4(),
        )

    started = perf_counter()
    portfolio = await get_portfolio_data(session=session, current_user=current_user)

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

    context = _build_context(
        project_dashboard=project_dashboard,
        portfolio=portfolio,
        message=message.strip(),
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
    llm_result = await LLMClient().generate_delivery_answer(
        query=message.strip(),
        context=context,
        history=history,
        evidence_sources=[source.model_dump(mode="json") for source in evidence_catalog[:20]],
    )

    answer = str(llm_result.get("answer", "")).strip()
    if not answer:
        answer = (
            "## Executive Assessment\n"
            "Delivery analysis could not be generated from current data.\n\n"
            "## Recommended Leadership Actions\n"
            "1. Verify delivery data is loaded and retry."
        )

    cited_titles = llm_result.get("cited_source_titles")
    cited_title_list = [str(title) for title in cited_titles] if isinstance(cited_titles, list) else []
    response_sources = _match_cited_sources(evidence_catalog, cited_title_list, answer)

    query = AgentQuery(
        user_id=current_user.id,
        org_id=current_user.org_id,
        project_id=resolved_project_id,
        agent_name=AGENT_NAME,
        query_text=message.strip(),
        answer_text=answer,
        model_used=str(llm_result.get("model") or ""),
        latency_ms=int((perf_counter() - started) * 1000),
    )
    session.add(query)
    await session.flush()

    for source in response_sources:
        if source.id is not None:
            table = {
                "risk": "risk_alerts",
                "bottleneck": "bottlenecks",
                "milestone": "milestones",
            }.get(source.type, "delivery_evidence")
            session.add(
                AgentQueryEvidenceLink(
                    agent_query_id=query.id,
                    source_table=table,
                    source_row_id=source.id,
                    description=source.title,
                )
            )

    return DeliveryChatRead(
        answer=answer,
        sources=response_sources,
        conversation_id=conversation_id or query.id,
    )
