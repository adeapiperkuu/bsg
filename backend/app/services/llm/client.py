from __future__ import annotations

import json
from collections.abc import AsyncGenerator

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
