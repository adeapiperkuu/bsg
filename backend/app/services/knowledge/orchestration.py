from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeRoutingDecision:
    handle_locally: bool
    context_agents: tuple[str, ...]
    reason: str
    client_safe: bool


_AGENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("delivery_performance", ("delivery", "milestone", "throughput", "blocker", "timeline")),
    ("quality_intelligence", ("quality", "defect", "qa", "rework", "escape")),
    ("project_governance", ("governance", "charter", "approval", "decision", "escalation")),
    ("workforce_capability", ("staffing", "capacity", "skills", "coverage", "utilization")),
)

_LOCAL_KNOWLEDGE_KEYWORDS = ("sop", "procedure", "policy", "guide", "standard", "version")


def route_knowledge_question(
    query_text: str,
    *,
    answer_mode: str = "internal",
    project: str | None = None,
) -> KnowledgeRoutingDecision:
    normalized = query_text.lower()
    client_safe = answer_mode == "client_safe"
    local_match = any(keyword in normalized for keyword in _LOCAL_KNOWLEDGE_KEYWORDS)
    agents = tuple(
        agent
        for agent, keywords in _AGENT_KEYWORDS
        if any(keyword in normalized for keyword in keywords)
    )
    if client_safe:
        agents = tuple(agent for agent in agents if agent != "workforce_capability")
    if local_match and not agents:
        return KnowledgeRoutingDecision(
            handle_locally=True,
            context_agents=(),
            reason="The question is answerable from governed knowledge documents.",
            client_safe=client_safe,
        )
    if agents:
        selected = agents[:1]
        scope = f" for {project}" if project else ""
        return KnowledgeRoutingDecision(
            handle_locally=True,
            context_agents=selected,
            reason=f"Use governed knowledge first, then request bounded {selected[0]} context{scope}.",
            client_safe=client_safe,
        )
    return KnowledgeRoutingDecision(
        handle_locally=True,
        context_agents=(),
        reason="No cross-agent operational context is needed.",
        client_safe=client_safe,
    )
