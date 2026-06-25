from openai import AsyncOpenAI

from app.core.config import get_settings

_SYSTEM_PROMPT = """\
You are the BSG Operational Knowledge Agent — an internal assistant that answers questions \
EXCLUSIVELY from the document chunks provided below.

Rules:
- Answer only from the provided chunks. Do NOT use outside knowledge.
- If the chunks contain no relevant information, set answer to exactly: \
"I could not find this information in the uploaded knowledge base."
- Keep answers direct, operational, and practical.
- Cite which document each key fact comes from, using the [Doc: <title>] format inline.
- Do not hallucinate, speculate, or infer beyond what the chunks state.

For operational questions, also populate structured fields from the chunks only.

Return ONLY valid JSON in this exact shape (no markdown fences):
{
  "answer": "<direct answer, citing sources inline as [Doc: title]>",
  "next_step": "<single recommended operational action, or empty string if not applicable>",
  "confidence": <float 0.0-1.0 reflecting how well the chunks answer the question>,
  "structured": {
    "policy": "<governing policy or rule from chunks, or empty string>",
    "steps": "<numbered operational steps from chunks, or empty string>",
    "owner": "<responsible owner/role from chunks, or empty string>",
    "evidence": "<supporting evidence or document references from chunks, or empty string>",
    "next_action": "<immediate next action for the operator, or empty string>"
  }
}"""


_DELIVERY_SYSTEM_PROMPT = """\
You are the BSG Delivery Agent — a senior Portfolio Delivery Director providing grounded decision support \
across multiple projects.

You are NOT a reporting assistant. You are NOT a generic chatbot.

Your mandate:
- Help leadership interpret delivery signals and prioritize attention.
- Identify patterns, rank priorities, and assess impact using ONLY available evidence.
- Provide insight beyond dashboard tiles — through interpretation, not invention.
- Write as a trusted operations advisor briefing leadership in under 60 seconds of reading time.

GROUNDING RULE — CRITICAL:
Never fabricate operational details. Only make recommendations supported by available evidence.
When data is insufficient, explicitly state assumptions and uncertainty.
Prefer evidence-backed guidance over speculative recommendations.

You must NEVER invent:
- Headcount numbers or staffing allocations (e.g. "move 3 reviewers", "add 2 FTEs")
- Budget decisions or cost figures
- Resource counts not present in the data
- SLA impacts, revenue impact, or business consequences not supported by evidence
- Specific operational orders the system cannot verify (e.g. "freeze intake", "halt new work")

Available evidence types (only reference what appears in the provided data):
- Schedule confidence percentages
- Traffic-light status (red/yellow/green)
- Open risks (titles and details)
- Active bottlenecks (titles and details)
- Milestone status and dates
- Root-cause contributing factors from scoring
- Throughput metrics where provided
- Cross-project pattern counts from portfolio_patterns

Recommendation style — evidence-backed, not fabricated:
- BAD: "Reallocate 3 reviewers from Project A to Project B."
- BAD: "Freeze new intake on green-status projects."
- GOOD: "Reviewer capacity constraints appear to be a primary risk driver. Consider evaluating \
reviewer allocation across red-status projects."
- GOOD: "Prioritize a delivery recovery review for Annotation Sprint 13 due to extremely low confidence \
(2.6%) combined with 3 open risks and 2 active bottlenecks."
- GOOD: "Escalate projects below 10% schedule confidence where active bottlenecks are present."

Forbidden language:
- Never say: "Based on the provided information", "It appears that", "As an AI", "The data shows".
- Never recommend empty platitudes: "monitor risks", "schedule a meeting", "continue to track".
- Never repeat portfolio KPI totals unless the question is specifically about that metric.

Use clean markdown with ## and ### headings. Never use <markdown> tags or code fences.

---

PORTFOLIO-LEVEL QUESTIONS:

## Executive Assessment
2-3 sentences. State the portfolio conclusion and primary driver using evidence. No bullet lists.

---

## Priority Projects
Rank top 3-5 projects by urgency. For each:

### N. <Project Name> (<Highest Priority | High Priority | Elevated>)
**Why it matters:**
* <interpreted signal citing actual metrics, risks, or bottlenecks by name>

**Potential impact:**
* <only consequences inferable from evidence — e.g. milestone slippage risk, delivery delay risk>
* Use cautious language when impact is inferred, not stated in data

---

## Portfolio Pattern
State the dominant cross-project pattern in 1-2 sentences.

**Confidence:** <High | Medium | Low>

**Supporting signals:**
* <quantified evidence from data — e.g. "Present in 4 of 5 highest-risk projects">
* <recurring risk or bottleneck themes from portfolio_patterns>

One sentence on whether this suggests a systemic issue vs isolated failures. \
State uncertainty if the pattern is weak.

---

## Recommended Leadership Actions

### Immediate Actions
Bullet list of 2-3 actions leadership should consider now. Each must trace to a specific \
evidence signal (confidence threshold, bottleneck, risk title). Use "consider", "prioritize", \
"escalate", "review" — not fabricated staffing numbers.

### Near-Term Actions
Bullet list of 2-3 actions for the coming cycle. May include assessing capacity distribution, \
milestone sequencing, or bottleneck resolution — without inventing resource counts.

### Strategic Actions
Bullet list of 1-2 portfolio-level investigations if patterns suggest systemic issues. \
Explicitly note when strategic conclusions have lower confidence due to limited data.

---

PROJECT-FOCUSED QUESTIONS:

## Executive Assessment
2-3 sentences on this project's delivery posture citing actual confidence, status, and evidence.

## Situation Analysis
Interpret signals from the data — what confidence, risks, and bottlenecks mean operationally.

## Root Causes
Bullet list of drivers from top_root_causes and evidence. Reference risks/bottlenecks by name.

**Confidence:** <High | Medium | Low> with brief rationale.

## Recommended Actions

### Immediate Actions
Evidence-backed steps for this project (2-3 bullets).

### Near-Term Actions
Follow-up considerations (1-2 bullets).

### Strategic Actions
Only if warranted by recurring patterns; note uncertainty if data is limited.

---

Evidence integration:
- Name specific risks, bottlenecks, and milestones inside the narrative.
- Every recommendation must be traceable to at least one evidence signal in the data.
- In cited_source_titles, list ONLY evidence catalog titles you referenced (exact titles).

Return ONLY valid JSON (no markdown fences around the JSON):
{
  "answer": "<markdown following the appropriate structure above>",
  "cited_source_titles": ["<exact title from evidence catalog>"]
}"""


def _sanitize_delivery_answer(text: str) -> str:
    import re

    cleaned = text.strip()
    cleaned = re.sub(r"</?markdown>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```(?:markdown)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def _is_portfolio_question(query: str) -> bool:
    q = query.lower()
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
    return any(signal in q for signal in portfolio_signals)


class LLMClient:
    async def generate_rag_answer(
        self,
        query: str,
        chunks: list[dict[str, str]],
    ) -> dict[str, object]:
        """Generate a cited RAG answer using OpenAI chat completion."""
        settings = get_settings()
        api_key = settings.openai_api_key or settings.llm_api_key
        if not api_key:
            return {
                "answer": "I could not find this information in the uploaded knowledge base.",
                "next_step": "",
                "confidence": 0.0,
                "structured": {},
            }

        context_parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[{i}] Document: {chunk['title']} ({chunk['source_type']})\n"
                f"    Folder: {chunk['folder']} | Page: {chunk.get('page') or 'N/A'}\n"
                f"    Content: {chunk['text']}"
            )
        context = "\n\n".join(context_parts)
        user_message = f"Question: {query}\n\nDocument chunks:\n{context}"

        client_kwargs: dict[str, str] = {"api_key": api_key}
        if settings.openai_base_url or settings.llm_base_url:
            client_kwargs["base_url"] = (settings.openai_base_url or settings.llm_base_url or "")

        model = settings.openai_model or settings.llm_model or "gpt-4o-mini"

        import json
        try:
            client = AsyncOpenAI(**client_kwargs)
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            structured = data.get("structured") if isinstance(data.get("structured"), dict) else {}
            return {
                "answer": str(data.get("answer", "")),
                "next_step": str(data.get("next_step", "")),
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
                "structured": structured,
                "model": model,
            }
        except Exception as exc:
            return {
                "answer": "I could not find this information in the uploaded knowledge base.",
                "next_step": "",
                "confidence": 0.0,
                "structured": {},
                "error": str(exc),
            }

    async def generate_delivery_answer(
        self,
        query: str,
        context: dict[str, object],
        *,
        history: list[dict[str, str]] | None = None,
        evidence_sources: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        """Generate a delivery operations answer grounded in dashboard context."""
        settings = get_settings()
        api_key = settings.openai_api_key or settings.llm_api_key
        model = settings.openai_model or settings.llm_model or "gpt-4o-mini"

        if not api_key:
            return {
                "answer": (
                    "## Executive Assessment\n"
                    "Delivery AI is not configured — leadership decision support is unavailable.\n\n"
                    "## Recommended Leadership Actions\n"
                    "1. Set OPENAI_API_KEY to enable the Delivery Agent."
                ),
                "cited_source_titles": [],
                "model": model,
            }

        import json

        question_scope = "portfolio"
        if isinstance(context.get("question_scope"), str):
            question_scope = str(context["question_scope"])
        elif not _is_portfolio_question(query):
            question_scope = "project"

        context_json = json.dumps(context, default=str, indent=2)
        evidence_json = json.dumps(evidence_sources or [], default=str, indent=2)
        scope_instruction = (
            "Use the PORTFOLIO-LEVEL response structure."
            if question_scope == "portfolio"
            else "Use the PROJECT-FOCUSED response structure."
        )
        user_message = (
            f"Question: {query}\n"
            f"Response mode: {scope_instruction}\n"
            f"Grounding: Do not invent headcount, staffing moves, budgets, or SLA impacts. "
            f"Only recommend actions traceable to evidence below. State confidence levels.\n\n"
            f"Delivery performance data:\n{context_json}\n\n"
            f"Evidence catalog (use exact titles in cited_source_titles when referenced):\n{evidence_json}"
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": _DELIVERY_SYSTEM_PROMPT}]
        for turn in history or []:
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        client_kwargs: dict[str, str] = {"api_key": api_key}
        if settings.openai_base_url or settings.llm_base_url:
            client_kwargs["base_url"] = (settings.openai_base_url or settings.llm_base_url or "")

        try:
            client = AsyncOpenAI(**client_kwargs)
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=1300 if question_scope == "portfolio" else 900,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            cited = data.get("cited_source_titles")
            cited_titles = [str(title).strip() for title in cited] if isinstance(cited, list) else []
            return {
                "answer": _sanitize_delivery_answer(str(data.get("answer", ""))),
                "cited_source_titles": [title for title in cited_titles if title],
                "model": model,
            }
        except Exception as exc:
            return {
                "answer": (
                    "## Executive Assessment\n"
                    "Delivery analysis could not be completed at this time.\n\n"
                    "## Recommended Leadership Actions\n"
                    "1. Retry the query.\n"
                    "2. Confirm delivery data is loaded for the selected project scope."
                ),
                "cited_source_titles": [],
                "model": model,
                "error": str(exc),
            }
