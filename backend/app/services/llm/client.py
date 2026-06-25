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
                    "The delivery AI service is not configured. "
                    "Please set OPENAI_API_KEY to enable evidence-backed delivery analysis."
                ),
                "sources": evidence_sources or [],
                "model": model,
            }

        import json

        system_prompt = (
            "You are the BSG Delivery Agent. You analyze delivery performance, project execution, "
            "milestones, bottlenecks, risks, forecasts, and operational health. Provide concise "
            "evidence-based recommendations for delivery managers.\n\n"
            "Rules:\n"
            "- Answer ONLY from the delivery data provided. Do not invent metrics.\n"
            "- Never behave like a generic chatbot. Stay focused on delivery operations.\n"
            "- Structure every answer with these sections in markdown:\n"
            "  1. **Summary** — direct answer in 1-3 sentences\n"
            "  2. **Key Evidence** — bullet points citing specific metrics, projects, or signals\n"
            "  3. **Risks** — detected delivery risks (or state none identified)\n"
            "  4. **Recommended Actions** — numbered, actionable steps for delivery managers\n"
            "- Reference project names and numbers from the data when available.\n"
            "- If data is insufficient, say what is missing and recommend the next operational check.\n\n"
            "Return ONLY valid JSON in this exact shape (no markdown fences):\n"
            "{\n"
            '  "answer": "<markdown answer with Summary, Key Evidence, Risks, Recommended Actions>",\n'
            '  "sources": [{"title": "<evidence title>", "type": "<risk|bottleneck|milestone|throughput|project>", "description": "<short detail>"}]\n'
            "}"
        )

        context_json = json.dumps(context, default=str, indent=2)
        evidence_json = json.dumps(evidence_sources or [], default=str, indent=2)
        user_message = (
            f"Question: {query}\n\n"
            f"Delivery performance data:\n{context_json}\n\n"
            f"Evidence catalog:\n{evidence_json}"
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
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
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            sources = data.get("sources") if isinstance(data.get("sources"), list) else []
            return {
                "answer": str(data.get("answer", "")),
                "sources": sources,
                "model": model,
            }
        except Exception as exc:
            return {
                "answer": (
                    "I could not complete the delivery analysis right now. "
                    "Please try again in a moment."
                ),
                "sources": evidence_sources or [],
                "model": model,
                "error": str(exc),
            }
