from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    database_url: str
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    secret_key: str
    environment: Literal["dev", "staging", "prod"] = "dev"
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:8080"
    supabase_jwt_secret: str | None = None
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    oka_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    knowledge_embedding_model: str = "text-embedding-3-small"
    knowledge_embedding_dimensions: int = 1536
    # Model used for low-confidence retry (more capable, slower)
    knowledge_strong_model: str = "gpt-4o"
    email_api_key: str | None = None
    email_from_address: str | None = None
    knowledge_storage_bucket: str = "knowledge-documents"
    knowledge_upload_dir: str = str(BACKEND_ROOT / "data" / "knowledge")

    model_config = SettingsConfigDict(
        env_file=(
            BACKEND_ROOT / ".env",
            REPO_ROOT / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def jwt_secret(self) -> str:
        if self.supabase_jwt_secret and not self.supabase_jwt_secret.startswith(("http://", "https://")):
            return self.supabase_jwt_secret
        if self.environment == "dev":
            return self.secret_key
        msg = "SUPABASE_JWT_SECRET must be set to the Supabase JWT secret in non-dev environments."
        raise ValueError(msg)

    @property
    def jwt_uses_jwks(self) -> bool:
        return bool(self.supabase_jwt_secret and self.supabase_jwt_secret.startswith(("http://", "https://")))

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
