from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    secret_key: str
    environment: Literal["dev", "staging", "prod"] = "dev"
    allowed_origins: str = "http://localhost:5173"
    supabase_jwt_secret: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    email_api_key: str | None = None
    email_from_address: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def jwt_secret(self) -> str:
        return self.supabase_jwt_secret or self.secret_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
