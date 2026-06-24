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

Return ONLY valid JSON in this exact shape (no markdown fences):
{
  "answer": "<direct answer, citing sources inline as [Doc: title]>",
  "next_step": "<single recommended operational action, or empty string if not applicable>",
  "confidence": <float 0.0-1.0 reflecting how well the chunks answer the question>
}"""


class LLMClient:
    async def generate_rag_answer(
        self,
        query: str,
        chunks: list[dict[str, str]],
    ) -> dict[str, object]:
        """Generate a cited RAG answer using OpenAI chat completion.

        chunks items have keys: title, source_type, folder, page, text.
        Returns dict with keys: answer, next_step, confidence.
        """
        settings = get_settings()
        api_key = settings.openai_api_key or settings.llm_api_key
        if not api_key:
            return {
                "answer": "I could not find this information in the uploaded knowledge base.",
                "next_step": "",
                "confidence": 0.0,
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
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return {
                "answer": str(data.get("answer", "")),
                "next_step": str(data.get("next_step", "")),
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
                "model": model,
            }
        except Exception as exc:
            # Surface extraction errors as a graceful fallback, not a 500.
            return {
                "answer": "I could not find this information in the uploaded knowledge base.",
                "next_step": "",
                "confidence": 0.0,
                "error": str(exc),
            }
