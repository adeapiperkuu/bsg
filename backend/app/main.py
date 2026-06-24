import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agents,
    auth,
    communications,
    csat,
    delivery,
    me,
    metrics,
    organisations,
    projects,
    quality,
    system,
    users,
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.exceptions import register_exception_handlers
from app.db.session import AsyncSessionLocal, dispose_engine
from app.services.quality import scan_all_projects

logger = logging.getLogger(__name__)


async def _scheduled_quality_scan() -> None:
    """Scheduler wrapper: opens its own DB session (no FastAPI DI)."""
    async with AsyncSessionLocal() as session:
        try:
            totals = await scan_all_projects(session)
            logger.info("Scheduled quality scan complete: %s", totals)
        except Exception:
            logger.exception("Scheduled quality scan failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_scheduled_quality_scan, "cron", day_of_week="mon", hour=2)
    scheduler.start()
    yield
    scheduler.shutdown()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="BSG Operations Tower API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url="/redoc" if settings.environment != "prod" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CsrfMiddleware)
    register_exception_handlers(app)

    app.include_router(system.router)
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(me.router, prefix=api_prefix)
    app.include_router(organisations.router, prefix=api_prefix)
    app.include_router(users.router, prefix=api_prefix)
    app.include_router(projects.router, prefix=api_prefix)
    app.include_router(delivery.router, prefix=api_prefix)
    app.include_router(quality.router, prefix=api_prefix)
    app.include_router(agents.router, prefix=api_prefix)
    app.include_router(communications.router, prefix=api_prefix)
    app.include_router(metrics.router, prefix=api_prefix)
    app.include_router(csat.router, prefix=api_prefix)
    return app


app = create_app()
