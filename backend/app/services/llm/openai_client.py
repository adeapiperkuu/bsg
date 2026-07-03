import threading

from openai import AsyncOpenAI

from app.core.config import get_settings

_client: AsyncOpenAI | None = None
# AsyncOpenAI construction itself is synchronous, so a plain threading.Lock (not an
# asyncio.Lock) is enough to make the check-then-set below atomic across concurrent
# requests without needing to await anything while holding it.
_client_lock = threading.Lock()


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        settings = get_settings()
        api_key = settings.openai_api_key or settings.llm_api_key
        if not api_key:
            raise RuntimeError("OpenAI API key is not configured.")
        client_kwargs: dict[str, str] = {"api_key": api_key}
        base_url = settings.openai_base_url or settings.llm_base_url
        if base_url:
            client_kwargs["base_url"] = base_url
        _client = AsyncOpenAI(**client_kwargs)
        return _client
