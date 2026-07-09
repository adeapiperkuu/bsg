import pytest
from pydantic import ValidationError

from app.core.config import Settings, origins_are_unsafe_for_credentialed_cors


def _base_settings_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "database_url": "postgresql://postgres:pass@localhost:5432/postgres",
        "supabase_url": "https://example.supabase.co",
        "supabase_anon_key": "anon-key",
        "supabase_service_role_key": "service-key",
        "secret_key": "test-secret-key",
        "environment": "dev",
        "allowed_origins": "http://localhost:5173",
        "supabase_jwt_secret": None,
        "auth_cookie_secure": False,
    }
    values.update(overrides)
    return values


def test_origins_are_unsafe_for_credentialed_cors() -> None:
    assert origins_are_unsafe_for_credentialed_cors([]) is True
    assert origins_are_unsafe_for_credentialed_cors(["*"]) is True
    assert origins_are_unsafe_for_credentialed_cors(["https://app.example.com"]) is False


def test_dev_allows_insecure_cookie_defaults() -> None:
    settings = Settings(**_base_settings_kwargs())
    assert settings.environment == "dev"
    assert settings.auth_cookie_secure is False


def test_staging_requires_supabase_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_JWT_SECRET"):
        Settings(**_base_settings_kwargs(environment="staging", supabase_jwt_secret=None))


def test_prod_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="AUTH_COOKIE_SECURE"):
        Settings(
            **_base_settings_kwargs(
                environment="prod",
                auth_cookie_secure=False,
                supabase_jwt_secret="jwt-secret",
                allowed_origins="https://app.example.com",
            ),
        )


def test_prod_rejects_wildcard_cors_origins() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(
            **_base_settings_kwargs(
                environment="prod",
                auth_cookie_secure=True,
                supabase_jwt_secret="jwt-secret",
                allowed_origins="*",
            ),
        )


def test_prod_rejects_empty_cors_origins() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(
            **_base_settings_kwargs(
                environment="prod",
                auth_cookie_secure=True,
                supabase_jwt_secret="jwt-secret",
                allowed_origins=" , ",
            ),
        )


def test_prod_accepts_explicit_cors_and_secure_cookies() -> None:
    settings = Settings(
        **_base_settings_kwargs(
            environment="prod",
            auth_cookie_secure=True,
            supabase_jwt_secret="https://example.supabase.co/auth/v1/.well-known/jwks.json",
            allowed_origins="https://app.example.com,https://admin.example.com",
        ),
    )
    assert settings.environment == "prod"
    assert settings.auth_cookie_secure is True
    assert settings.jwt_uses_jwks is True
