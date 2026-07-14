import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.agents.delivery.routes import chat as delivery_chat
from app.agents.delivery.routes import dashboard as delivery_dashboard
from app.agents.governance.routes import governance as governance_routes
from app.agents.governance.services.escalation_suggestion_service import (
    run_scheduled_escalation_suggestion_scan,
)
from app.api.routes import (
    agents,
    auth,
    communications,
    csat,
    delivery,
    knowledge,
    me,
    metrics,
    organisations,
    projects,
    quality,
    system,
    users,
    workforce,
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.security import CurrentUser
from app.core.exceptions import register_exception_handlers
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.models import AppRole, Organisation, ScanTrigger, User
from app.db.session import dispose_engine, session_scope
from app.services.quality import scan_all_projects
from app.services.quality_thresholds import warm_thresholds_cache
from app.services.knowledge_ingestion_jobs import process_ingestion_job_queue
from app.services.signal_dispatcher import dispatch_pending_signals

logger = logging.getLogger(__name__)


def configure_logging(level: str = "INFO") -> None:
    """Ensure app loggers emit to the uvicorn console (default root level is WARNING)."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s:     %(name)s - %(message)s",
        force=True,
    )
    logging.getLogger("app").setLevel(log_level)


async def _scheduled_quality_scan() -> None:
    """Scheduler wrapper: opens its own DB session (no FastAPI DI)."""
    async with session_scope() as session:
        try:
            run = await scan_all_projects(session, trigger=ScanTrigger.SCHEDULER)
            logger.info("Scheduled quality scan complete run_id=%s status=%s", run.id, run.status)
            totals = await dispatch_pending_signals(session)
            logger.info("Post-scan signal dispatch: %s", totals)
        except Exception:
            logger.exception("Scheduled quality scan failed")


async def _scheduled_ingestion_queue_poll() -> None:
    try:
        dispatched = await process_ingestion_job_queue()
        if dispatched:
            logger.info("Dispatched %s knowledge ingestion job(s) from queue poll.", dispatched)
    except Exception:
        logger.exception("Knowledge ingestion queue poll failed")


async def _scheduled_governance_escalation_scan() -> None:
    settings = get_settings()
    if not settings.governance_escalation_suggestion_scheduled_enabled:
        return
    async with session_scope() as session:
        try:
            orgs = list((await session.execute(select(Organisation))).scalars())
            for org in orgs[: settings.governance_escalation_suggestion_max_projects_per_scan]:
                user = (
                    await session.execute(
                        select(User)
                        .where(
                            User.org_id == org.id,
                            User.is_active.is_(True),
                            User.role.in_(
                                {
                                    AppRole.DELIVERY_MANAGER,
                                    AppRole.BSG_LEADERSHIP,
                                    AppRole.SUPER_ADMIN,
                                }
                            ),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if user is None:
                    logger.info(
                        "Skipping scheduled governance escalation scan for org=%s: no internal user",
                        org.id,
                    )
                    continue
                current_user = CurrentUser(
                    id=user.id,
                    org_id=org.id,
                    email=user.email,
                    role=user.role,
                    is_active=user.is_active,
                )
                result = await run_scheduled_escalation_suggestion_scan(session, current_user)
                logger.info(
                    "Scheduled governance escalation scan org=%s created=%s reused=%s",
                    org.id,
                    result.suggestions_created,
                    result.suggestions_reused,
                )
        except Exception:
            logger.exception("Scheduled governance escalation scan failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_scheduled_quality_scan, "cron", day_of_week="mon", hour=2)
    scheduler.add_job(_scheduled_governance_escalation_scan, "cron", day_of_week="mon", hour=3)
    scheduler.add_job(_scheduled_ingestion_queue_poll, "interval", seconds=30)
    scheduler.start()
    try:
        await warm_thresholds_cache()
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not pre-warm quality thresholds cache at startup",
            exc_info=True,
        )
    yield
    scheduler.shutdown()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="BSG Operations Tower API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url="/redoc" if settings.environment != "prod" else None,
    )

    app.add_middleware(CsrfMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    app.include_router(system.router)
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(me.router, prefix=api_prefix)
    app.include_router(organisations.router, prefix=api_prefix)
    app.include_router(users.router, prefix=api_prefix)
    app.include_router(projects.router, prefix=api_prefix)
    app.include_router(delivery.router, prefix=api_prefix)
    app.include_router(delivery_dashboard.router, prefix=api_prefix)
    app.include_router(delivery_chat.router, prefix=api_prefix)
    app.include_router(quality.router, prefix=api_prefix)
    app.include_router(workforce.router, prefix=api_prefix)
    app.include_router(agents.router, prefix=api_prefix)
    app.include_router(communications.router, prefix=api_prefix)
    app.include_router(metrics.router, prefix=api_prefix)
    app.include_router(csat.router, prefix=api_prefix)
    app.include_router(knowledge.router, prefix=api_prefix)
    app.include_router(governance_routes.router, prefix=api_prefix)
    return app


app = create_app()
