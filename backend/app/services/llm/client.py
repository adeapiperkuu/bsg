<<<<<<< HEAD
import httpx

from app.core.config import get_settings
from app.core.exceptions import ApiError


class LLMClient:
    async def generate(self, prompt: str) -> str:
        return await self.generate_structured(
            system="You are a helpful assistant.",
            user=prompt,
            context="",
        )

    async def generate_structured(self, *, system: str, user: str, context: str) -> str:
        settings = get_settings()
        if not settings.llm_api_key:
            raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", "LLM provider is not configured.")

        base_url = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        model = settings.llm_model or "gpt-4o-mini"

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if context:
            messages.append({"role": "system", "content": f"Grounded context (cite only this data):\n{context}"})
        messages.append({"role": "user", "content": user})

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                },
            )

        if response.status_code >= 400:
            raise ApiError(
                503,
                "LLM_PROVIDER_ERROR",
                f"LLM request failed with status {response.status_code}.",
            )

        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError(503, "LLM_PROVIDER_ERROR", "LLM returned an unexpected response.") from exc
=======
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.llm.openai_client import get_openai_client

# ── Prompts ───────────────────────────────────────────────────────────────────

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

_CLIENT_SAFE_PROMPT = """\
You are the BSG Operational Knowledge Agent writing a client-safe answer.

Rules:
- Answer only from the provided client-safe chunks and structured facts.
- Do NOT expose internal-only rationale, staffing details, confidential risks, or unsupported operational steps.
- Keep the answer concise, reassuring, and action-oriented for a client audience.
- If the chunks contain no relevant information, set answer to exactly: \
"I could not find this information in the uploaded knowledge base."
- Cite which document each key fact comes from, using the [Doc: <title>] format inline.

Return ONLY valid JSON in this exact shape (no markdown fences):
{
  "answer": "<client-safe answer, citing sources inline as [Doc: title]>",
  "next_step": "<single client-safe next step, or empty string if not applicable>",
  "confidence": <float 0.0-1.0 reflecting how well the chunks answer the question>,
  "structured": {
    "policy": "<client-safe policy or rule from chunks, or empty string>",
    "steps": "<client-safe summary steps from chunks, or empty string>",
    "owner": "<client-facing owner/role from chunks, or empty string>",
    "evidence": "<supporting evidence or document references from chunks, or empty string>",
    "next_action": "<immediate client-safe next action, or empty string>"
  }
}"""

# Used when top-chunk score > FAST_PATH_THRESHOLD — skips structured fields, fewer tokens.
_FAST_SYSTEM_PROMPT = """\
You are the BSG Operational Knowledge Agent. Answer the question EXCLUSIVELY from the \
document chunks below. Cite sources inline as [Doc: title]. \
If no relevant information is found, answer: \
"I could not find this information in the uploaded knowledge base."

Return ONLY valid JSON (no markdown fences):
{
  "answer": "<answer text>",
  "next_step": "<single action or empty string>",
  "confidence": <float 0.0-1.0>
}"""

# ── Constants ──────────────────────────────────────────────────────────────────

RAG_CONTEXT_CHUNK_CHARS = 1200
RAG_MAX_OUTPUT_TOKENS = 700
FAST_PATH_MAX_TOKENS = 400
FAST_PATH_THRESHOLD = 0.85  # top chunk score above which fast path is used


def _truncate_chunk_text(text: str, limit: int = RAG_CONTEXT_CHUNK_CHARS) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _build_user_message(
    query: str,
    chunks: list[dict[str, str]],
    structured_context: str | None,
) -> str:
    context_parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        body = _truncate_chunk_text(chunk["text"])
        context_parts.append(
            f"[{i}] Document: {chunk['title']} ({chunk['source_type']})\n"
            f"    Folder: {chunk['folder']} | Page: {chunk.get('page') or 'N/A'}\n"
            f"    Content: {body}"
        )
    context = "\n\n".join(context_parts)
    structured_section = (
        f"\n\nStructured operational facts:\n{structured_context.strip()}"
        if structured_context and structured_context.strip()
        else ""
    )
    return f"Question: {query}\n\nDocument chunks:\n{context}{structured_section}"


def _select_system_prompt(answer_mode: str, fast_path: bool) -> str:
    if fast_path:
        return _FAST_SYSTEM_PROMPT
    return _CLIENT_SAFE_PROMPT if answer_mode == "client_safe" else _SYSTEM_PROMPT


# ── Parser for streaming answer extraction ─────────────────────────────────────

class _StreamParser:
    """
    Incrementally extract the "answer" field value from a streaming JSON response.
    Feed raw token deltas; call .new_chars() to get newly parseable answer characters.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._state = "find_key"  # find_key | find_open_quote | in_value | done
        self._answer: list[str] = []

    def feed(self, text: str) -> str:
        """Feed a raw token chunk; return newly extracted answer characters."""
        self._buf += text
        out: list[str] = []

        while self._buf:
            if self._state == "find_key":
                marker = '"answer"'
                idx = self._buf.find(marker)
                if idx == -1:
                    # Keep a short tail to handle marker split across chunks
                    if len(self._buf) > len(marker):
                        self._buf = self._buf[-len(marker):]
                    break
                self._buf = self._buf[idx + len(marker):]
                self._state = "find_open_quote"

            elif self._state == "find_open_quote":
                # Skip whitespace, colon, then look for opening "
                idx = self._buf.find('"')
                if idx == -1:
                    break
                # Ensure the colon comes before the opening quote
                colon = self._buf.find(':')
                if colon == -1 or colon > idx:
                    break
                self._buf = self._buf[idx + 1:]
                self._state = "in_value"

            elif self._state == "in_value":
                i = 0
                while i < len(self._buf):
                    ch = self._buf[i]
                    if ch == '\\':
                        if i + 1 >= len(self._buf):
                            # Incomplete escape — wait for more data
                            self._buf = self._buf[i:]
                            i = len(self._buf)
                            break
                        escaped = self._buf[i + 1]
                        char_map = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
                        out.append(char_map.get(escaped, escaped))
                        i += 2
                    elif ch == '"':
                        self._state = "done"
                        self._buf = self._buf[i + 1:]
                        i = len(self._buf)
                        break
                    else:
                        out.append(ch)
                        i += 1
                else:
                    self._buf = ""
                break

            elif self._state == "done":
                break

        result = "".join(out)
        self._answer.extend(out)
        return result

    @property
    def done(self) -> bool:
        return self._state == "done"

    def accumulated_answer(self) -> str:
        return "".join(self._answer)


# ── LLMClient ─────────────────────────────────────────────────────────────────

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
        *,
        model: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        answer_mode: str = "internal",
        structured_context: str | None = None,
        fast_path: bool = False,
    ) -> dict[str, object]:
        """Generate a cited RAG answer (non-streaming)."""
        settings = get_settings()
        api_key = settings.openai_api_key or settings.llm_api_key
        if not api_key:
            return {
                "answer": "I could not find this information in the uploaded knowledge base.",
                "next_step": "",
                "confidence": 0.0,
                "structured": {},
            }

        resolved_model = model or settings.openai_model or settings.llm_model or "gpt-4o-mini"
        max_tokens = FAST_PATH_MAX_TOKENS if fast_path else RAG_MAX_OUTPUT_TOKENS
        system_prompt = _select_system_prompt(answer_mode, fast_path)
        user_message = _build_user_message(query, chunks, structured_context)
        chat_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for turn in (conversation_history or [])[-4:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                chat_messages.append({"role": role, "content": str(content)[:2000]})
        chat_messages.append({"role": "user", "content": user_message})

        try:
            client = get_openai_client()
            response = await client.chat.completions.create(
                model=resolved_model,
                messages=chat_messages,
                temperature=0.1,
                max_tokens=max_tokens,
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
                "model": resolved_model,
            }
        except Exception as exc:
            return {
                "answer": "I could not find this information in the uploaded knowledge base.",
                "next_step": "",
                "confidence": 0.0,
                "structured": {},
                "error": str(exc),
            }

    async def stream_rag_answer(
        self,
        query: str,
        chunks: list[dict[str, str]],
        *,
        model: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        answer_mode: str = "internal",
        structured_context: str | None = None,
        fast_path: bool = False,
    ) -> AsyncGenerator[dict[str, object], None]:
        """
        Stream a cited RAG answer.

        Yields dicts of two shapes:
        - {"type": "delta", "text": "<token>"}   — answer text tokens as they arrive
        - {"type": "done", "answer_text": "...", "next_step": "...", "confidence": float,
           "structured": dict | None, "model": str}  — final structured result
        """
        settings = get_settings()
        api_key = settings.openai_api_key or settings.llm_api_key
        if not api_key:
            yield {"type": "done", "answer_text": "I could not find this information in the uploaded knowledge base.",
                   "next_step": "", "confidence": 0.0, "structured": None, "model": ""}
            return

        resolved_model = model or settings.openai_model or settings.llm_model or "gpt-4o-mini"
        max_tokens = FAST_PATH_MAX_TOKENS if fast_path else RAG_MAX_OUTPUT_TOKENS
        system_prompt = _select_system_prompt(answer_mode, fast_path)
        user_message = _build_user_message(query, chunks, structured_context)
        chat_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for turn in (conversation_history or [])[-4:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                chat_messages.append({"role": role, "content": str(content)[:2000]})
        chat_messages.append({"role": "user", "content": user_message})

        accumulated = ""
        parser = _StreamParser()
        try:
            client = get_openai_client()
            # Stream without json_object format — we parse answer field ourselves
            async with await client.chat.completions.create(
                model=resolved_model,
                messages=chat_messages,
                temperature=0.1,
                max_tokens=max_tokens,
                stream=True,
            ) as stream:
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or "" if chunk.choices else ""
                    if not token:
                        continue
                    accumulated += token
                    new_text = parser.feed(token)
                    if new_text:
                        yield {"type": "delta", "text": new_text}
        except Exception as exc:
            yield {"type": "done", "answer_text": "I could not find this information in the uploaded knowledge base.",
                   "next_step": "", "confidence": 0.0, "structured": None, "model": resolved_model,
                   "error": str(exc)}
            return

        # Parse final structured metadata from accumulated JSON
        answer_text = parser.accumulated_answer()
        next_step = ""
        confidence = 0.0
        structured: dict[str, object] | None = None
        try:
            data = json.loads(accumulated)
            if not answer_text:
                answer_text = str(data.get("answer", ""))
            next_step = str(data.get("next_step", ""))
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
            raw_struct = data.get("structured")
            if isinstance(raw_struct, dict):
                structured = raw_struct
        except (json.JSONDecodeError, ValueError):
            pass

        if not answer_text.strip():
            stripped = accumulated.strip()
            if stripped and not stripped.startswith("{"):
                answer_text = stripped
            else:
                answer_text = "I could not find this information in the uploaded knowledge base."

        yield {
            "type": "done",
            "answer_text": answer_text,
            "next_step": next_step,
            "confidence": confidence,
            "structured": structured,
            "model": resolved_model,
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
>>>>>>> 5dbfdec1dd5fc32986d7d6d91b317bb9b4543a30
