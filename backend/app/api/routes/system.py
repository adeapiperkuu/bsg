from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "operations-tower-api", "version": "0.1.0"}


@router.get("/ready")
async def ready() -> dict[str, object]:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text("select 1"))
        except Exception as exc:
            raise ApiError(503, "DATABASE_UNAVAILABLE", "Database is not available.") from exc
    return {
        "status": "ready",
        "checks": {
            "database": "ok",
            "llm_provider": "configured" if settings.llm_api_key else "not_configured",
        },
    }
