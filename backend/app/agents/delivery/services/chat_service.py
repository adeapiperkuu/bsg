"""Delivery Agent chat — grounded answers from live delivery performance data."""

from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.delivery.schemas.chat_schema import DeliveryChatRead, DeliveryChatSource
from app.agents.delivery.services.dashboard_service import get_dashboard_data, get_portfolio_data
from app.core.security import CurrentUser
from app.db.models import AgentQuery, AgentQueryEvidenceLink
from app.services.llm.client import LLMClient

AGENT_NAME = "delivery_performance_agent"
MAX_HISTORY_TURNS = 6


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


def _collect_sources(dashboard: dict[str, Any]) -> list[DeliveryChatSource]:
    sources: list[DeliveryChatSource] = []
    for risk in dashboard.get("risks") or []:
        if isinstance(risk, dict):
            sources.append(_source_from_risk(risk))
    for bottleneck in dashboard.get("bottlenecks") or []:
        if isinstance(bottleneck, dict):
            sources.append(_source_from_bottleneck(bottleneck))
    for milestone in dashboard.get("milestones") or []:
        if isinstance(milestone, dict):
            sources.append(_source_from_milestone(milestone))
    return sources


def _portfolio_summary(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for entry in portfolio.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        dashboard = entry.get("dashboard")
        if not isinstance(dashboard, dict):
            continue
        overview = dashboard.get("overview")
        project_name = None
        if isinstance(overview, dict):
            project = overview.get("project")
            if isinstance(project, dict):
                project_name = project.get("name")
        summaries.append(
            {
                "project_id": entry.get("project_id"),
                "project_name": project_name,
                "traffic_light": dashboard.get("traffic_light"),
                "confidence": dashboard.get("confidence"),
                "open_risks": len(dashboard.get("risks") or []),
                "open_bottlenecks": len(dashboard.get("bottlenecks") or []),
            }
        )
    return summaries


def _build_context(
    *,
    project_dashboard: dict[str, Any] | None,
    portfolio: dict[str, Any],
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "portfolio_summary": _portfolio_summary(portfolio),
        "portfolio_milestones": portfolio.get("milestones") or [],
    }
    if project_dashboard is not None:
        context["focused_project"] = {
            "overview": project_dashboard.get("overview"),
            "milestones": project_dashboard.get("milestones"),
            "confidence": project_dashboard.get("confidence"),
            "traffic_light": project_dashboard.get("traffic_light"),
            "risks": project_dashboard.get("risks"),
            "bottlenecks": project_dashboard.get("bottlenecks"),
        }
    return context


async def _load_conversation_history(
    session: AsyncSession,
    current_user: CurrentUser,
    conversation_id: UUID | None,
) -> list[dict[str, str]]:
    if conversation_id is None:
        return []

    anchor = await session.get(AgentQuery, conversation_id)
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
        history.append({"role": "assistant", "content": row.answer_text})
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
    started = perf_counter()
    portfolio = await get_portfolio_data(session=session, current_user=current_user)

    resolved_project_id = project_id
    if resolved_project_id is None and conversation_id is not None:
        anchor = await session.get(AgentQuery, conversation_id)
        if anchor is not None and anchor.user_id == current_user.id:
            resolved_project_id = anchor.project_id

    project_dashboard: dict[str, Any] | None = None
    if resolved_project_id is not None:
        project_dashboard = await get_dashboard_data(
            session=session,
            project_id=resolved_project_id,
            current_user=current_user,
        )

    context = _build_context(project_dashboard=project_dashboard, portfolio=portfolio)
    evidence_sources = _collect_sources(project_dashboard) if project_dashboard else []
    if not evidence_sources:
        for entry in portfolio.get("projects") or []:
            if not isinstance(entry, dict):
                continue
            dashboard = entry.get("dashboard")
            if isinstance(dashboard, dict):
                evidence_sources.extend(_collect_sources(dashboard))
                if len(evidence_sources) >= 12:
                    break

    history = await _load_conversation_history(session, current_user, conversation_id)
    llm_result = await LLMClient().generate_delivery_answer(
        query=message.strip(),
        context=context,
        history=history,
        evidence_sources=[source.model_dump(mode="json") for source in evidence_sources[:12]],
    )

    answer = str(llm_result.get("answer", "")).strip()
    if not answer:
        answer = (
            "I could not generate a delivery analysis right now. "
            "Please verify delivery data is available and try again."
        )

    llm_sources = llm_result.get("sources")
    response_sources = list(evidence_sources[:6])
    if isinstance(llm_sources, list) and llm_sources:
        for item in llm_sources:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            response_sources.append(
                DeliveryChatSource(
                    title=title,
                    type=str(item.get("type") or "evidence"),
                    description=str(item.get("description") or "") or None,
                )
            )

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

    for source in response_sources[:8]:
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

    # Deduplicate sources by title for the API response
    seen: set[str] = set()
    unique_sources: list[DeliveryChatSource] = []
    for source in response_sources:
        key = source.title.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(source)

    return DeliveryChatRead(
        answer=answer,
        sources=unique_sources[:8],
        conversation_id=conversation_id or query.id,
    )
