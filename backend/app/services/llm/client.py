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

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        context: str,
        json_mode: bool = False,
    ) -> str:
        settings = get_settings()
        if not settings.llm_api_key:
            raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", "LLM provider is not configured.")

        base_url = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        model = settings.llm_model or "gpt-4o-mini"

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if context:
            messages.append({"role": "system", "content": f"Grounded context (cite only this data):\n{context}"})
        messages.append({"role": "user", "content": user})

        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
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
