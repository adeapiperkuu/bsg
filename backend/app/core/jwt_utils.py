from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings

JWT_CLOCK_SKEW_SECONDS = 30


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    if settings.jwt_uses_jwks and settings.supabase_jwt_secret:
        jwks_client = PyJWKClient(settings.supabase_jwt_secret)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "HS256"],
            audience="authenticated",
            leeway=JWT_CLOCK_SKEW_SECONDS,
        )
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
        leeway=JWT_CLOCK_SKEW_SECONDS,
    )
