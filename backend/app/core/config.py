from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


def origins_are_unsafe_for_credentialed_cors(origins: list[str]) -> bool:
    """Wildcard or empty CORS origins are unsafe when cookies/credentials are enabled."""
    if not origins:
        return True
    return any(origin == "*" for origin in origins)


class Settings(BaseSettings):
    database_url: str
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    secret_key: str
    environment: Literal["dev", "staging", "prod"] = "dev"
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:8080,http://localhost:8081"
    supabase_jwt_secret: str | None = None
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_intent_routing: bool = False
    # Quality Intelligence Agent: LLM reasoning over evidence (see
    # docs/agents/quality_reasoning_upgrade_plan.md). Dark-launch flag — when
    # False, root-cause analysis uses the deterministic engine only.
    quality_llm_reasoning: bool = True
    # When True, run the LLM reasoning engine alongside the deterministic
    # engine even while quality_llm_reasoning is False, logging divergence
    # for evaluation without affecting the response returned to users.
    quality_llm_reasoning_shadow: bool = False
    quality_reasoning_model: str | None = None
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
    log_level: str = "INFO"
    knowledge_storage_bucket: str = "knowledge-documents"
    knowledge_upload_dir: str = str(BACKEND_ROOT / "data" / "knowledge")
    # When true, the user who submitted a document cannot also approve it.
    knowledge_separation_of_duties: bool = False
    # Delivery chat hardening (see app/agents/delivery/routes/chat.py)
    delivery_chat_user_rate_limit_per_minute: int = 10
    delivery_chat_org_rate_limit_per_minute: int = 60
    delivery_chat_max_message_length: int = 2000
    delivery_chat_retry_max_attempts: int = 3
    delivery_chat_retry_base_delay_seconds: float = 0.5
    # DEVELOPMENT_PLAN.md Workstream E: comma-separated app_role values
    # (e.g. "delivery_manager,bsg_leadership,super_admin") that must complete
    # Supabase Auth TOTP MFA (aal2) to finish POST /auth/login. Empty by
    # default -- MFA enforcement is off until this is explicitly set, since
    # the Supabase MFA REST API shape this integration relies on hasn't been
    # verified against a live sandbox yet (see docs/13. Security & Compliance.md §3).
    mfa_required_roles: str = ""

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

    @model_validator(mode="after")
    def validate_security_settings(self) -> Self:
        if self.environment in {"staging", "prod"}:
            if not self.supabase_jwt_secret or not self.supabase_jwt_secret.strip():
                msg = (
                    "SUPABASE_JWT_SECRET must be set when ENVIRONMENT is staging or production."
                )
                raise ValueError(msg)

        if self.environment == "prod":
            if not self.auth_cookie_secure:
                msg = "AUTH_COOKIE_SECURE must be true when ENVIRONMENT=prod."
                raise ValueError(msg)
            if origins_are_unsafe_for_credentialed_cors(self.cors_allowed_origins):
                msg = (
                    "ALLOWED_ORIGINS must list explicit origins in production; "
                    "wildcard (*) and empty values are not allowed with credentialed cookies."
                )
                raise ValueError(msg)
            if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
                msg = "AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true in production."
                raise ValueError(msg)

        return self

    @property
    def mfa_required_role_values(self) -> set[str]:
        """Plain role-value strings (not AppRole) to avoid importing db models
        into this low-level settings module -- callers compare against
        `user.role.value`."""
        return {r.strip() for r in self.mfa_required_roles.split(",") if r.strip()}

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
