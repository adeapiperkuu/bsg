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
    allowed_origins: str = (
        "http://localhost:5173,http://localhost:3000,http://localhost:8080,http://localhost:8081"
    )
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
    # Governance AI recommendations (Phase 6) — disabled by default for safe rollout.
    governance_ai_recommendations_enabled: bool = False
    governance_ai_recommendation_model: str | None = None
    governance_ai_recommendation_max_items: int = 5
    governance_ai_recommendation_cooldown_seconds: int = 600
    governance_ai_recommendation_max_evidence_items: int = 20
    governance_ai_recommendation_timeout_seconds: float = 45.0
    governance_ai_recommendation_prompt_version: str = "v1"
    # Phase D — UTC daily register summary rollover refresh (hourly catch-up, once/day idempotent).
    governance_register_daily_refresh_enabled: bool = True
    # Phase F — durable Governance background jobs.
    governance_job_poll_interval_seconds: int = 5
    governance_job_poll_batch_size: int = 3
    governance_job_stale_seconds: int = 180
    governance_job_heartbeat_seconds: int = 30
    governance_job_worker_id: str = ""
    governance_job_export_dir: str = str(BACKEND_ROOT / "data" / "governance-exports")
    # Quality BR-06 — promote unresolved quality drift into governance_escalations.
    governance_quality_auto_escalation_enabled: bool = True
    # Optional outbound delivery for critical governance notifications (no-op when unset).
    governance_outbound_notifications_enabled: bool = False
    slack_webhook_url: str | None = None
    # Phase 12 — recommendation effectiveness & learning (read-only analytics + bounded rules).
    governance_recommendation_effectiveness_enabled: bool = True
    governance_recommendation_effectiveness_cache_seconds: int = 180
    governance_recommendation_effectiveness_min_sample: int = 5
    governance_recommendation_calibration_min_sample: int = 10
    governance_recommendation_quality_score_version: str = "v1"
    governance_recommendation_calibration_version: str = "v1"
    governance_recommendation_learning_rules_enabled: bool = False
    governance_recommendation_explanation_version: str = "v2"
    governance_recommendation_optimization_enabled: bool = True
    governance_recommendation_optimization_cache_seconds: int = 180
    governance_recommendation_strategy_version: str = "v1"
    governance_recommendation_confidence_version: str = "v1"
    governance_recommendation_drift_acceptance_drop_pp: float = 15.0
    governance_recommendation_drift_fp_rise_pp: float = 10.0
    governance_recommendation_drift_volume_ratio: float = 2.0
    governance_recommendation_shadow_sample_limit: int = 200
    # Phase 14 — publish approved Project Charters into Operational Knowledge.
    governance_charter_knowledge_publish_enabled: bool = True
    auto_publish_approved_charters: bool = True

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
        if self.environment in {"staging", "prod"} and (
            not self.supabase_jwt_secret or not self.supabase_jwt_secret.strip()
        ):
            msg = "SUPABASE_JWT_SECRET must be set when ENVIRONMENT is staging or production."
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
    def jwt_secret(self) -> str:
        if self.supabase_jwt_secret and not self.supabase_jwt_secret.startswith(
            ("http://", "https://")
        ):
            return self.supabase_jwt_secret
        if self.environment == "dev":
            return self.secret_key
        msg = "SUPABASE_JWT_SECRET must be set to the Supabase JWT secret in non-dev environments."
        raise ValueError(msg)

    @property
    def jwt_uses_jwks(self) -> bool:
        return bool(
            self.supabase_jwt_secret
            and self.supabase_jwt_secret.startswith(("http://", "https://"))
        )

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
