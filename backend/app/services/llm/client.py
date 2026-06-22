from app.core.exceptions import ApiError


class LLMClient:
    async def generate(self, prompt: str) -> str:
        raise ApiError(503, "LLM_PROVIDER_UNAVAILABLE", "LLM provider is not configured.")
