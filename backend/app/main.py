import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.delivery.routes import chat as delivery_chat
from app.agents.delivery.routes import dashboard as delivery_dashboard
from app.agents.governance.escalation import check_quality_escalations
from app.agents.governance.routes import governance as governance_routes
from app.agents.governance.services.job_service import process_governance_job_queue
from app.agents.governance.services.project_governance_summary_service import (
    refresh_stale_governance_summary_counts,
)
from app.agents.governance.services.register_service import invalidate_register_list_cache
from app.api.routes import (
    admin_audit,
    agents,
    auth,
    client_intelligence,
    communications,
    csat,
    dashboard,
    delivery,
    knowledge,
    kpis,
    me,
    metrics,
    organisations,
    programs,
    projects,
    quality,
    reports,
    system,
    time_series,
    users,
    workforce,
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.exceptions import register_exception_handlers
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.models import ScanTrigger
from app.db.rls import set_service_role_context
from app.db.session import dispose_engine, session_scope
from app.reports.scheduler import run_report_planner, run_report_queue_poll
from app.services.knowledge_ingestion_jobs import process_ingestion_job_queue
from app.services.quality import scan_all_projects
from app.services.quality_thresholds import warm_thresholds_cache
from app.services.signal_dispatcher import dispatch_pending_signals
from app.time_series.scheduler import (
    run_time_series_planner,
    run_time_series_queue_poll,
    run_time_series_retention,
)

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
            await set_service_role_context(session)
            run = await scan_all_projects(session, trigger=ScanTrigger.SCHEDULER)
            logger.info("Scheduled quality scan complete run_id=%s status=%s", run.id, run.status)
            totals = await dispatch_pending_signals(session)
            logger.info("Post-scan signal dispatch: %s", totals)
        except Exception:
            logger.exception("Scheduled quality scan failed")


async def _scheduled_quality_governance_escalation() -> None:
    """BR-06: escalate unresolved quality drift into the governance register."""
    settings = get_settings()
    if not settings.governance_quality_auto_escalation_enabled:
        return
    async with session_scope() as session:
        try:
            created = await check_quality_escalations(session)
            logger.info("Scheduled quality→governance escalation created=%s", created)
        except Exception:
            logger.exception("Scheduled quality→governance escalation failed")


async def _scheduled_ingestion_queue_poll() -> None:
    try:
        dispatched = await process_ingestion_job_queue()
        if dispatched:
            logger.info("Dispatched %s knowledge ingestion job(s) from queue poll.", dispatched)
    except Exception:
        logger.exception("Knowledge ingestion queue poll failed")


async def _scheduled_governance_queue_poll() -> None:
    try:
        processed = await process_governance_job_queue()
        if processed:
            logger.info("Processed %s Governance background job(s).", processed)
    except Exception:
        logger.exception("Governance background job queue poll failed")


async def _scheduled_report_planner() -> None:
    async with session_scope() as session:
        try:
            await run_report_planner(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Report planner failed")


async def _scheduled_report_queue_poll() -> None:
    async with session_scope() as session:
        try:
            await run_report_queue_poll(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Report queue poll failed")


async def _scheduled_governance_register_summary_refresh() -> None:
    """Refresh UTC-day register counts outside GET; retry hourly after failures/missed startup."""
    settings = get_settings()
    if not settings.governance_register_daily_refresh_enabled:
        return
    async with session_scope() as session:
        try:
            result = await refresh_stale_governance_summary_counts(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Scheduled Governance register summary refresh failed")
            return

    removed = sum(invalidate_register_list_cache(org_id=org_id) for org_id in result.org_ids)
    logger.info(
        "governance_register_summary_refresh business_date=%s rows_refreshed=%s "
        "org_count=%s execute_count=%s refresh_ms=%s register_cache_removed=%s timezone=UTC",
        result.business_date,
        result.rows_refreshed,
        len(result.org_ids),
        result.execute_count,
        result.duration_ms,
        removed,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_scheduled_quality_scan, "cron", day_of_week="mon", hour=2)
    scheduler.add_job(
        _scheduled_quality_governance_escalation, "cron", day_of_week="mon", hour=2, minute=30
    )
    scheduler.add_job(
        _scheduled_governance_register_summary_refresh,
        "cron",
        minute=5,
        timezone=UTC,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(_scheduled_ingestion_queue_poll, "interval", seconds=30)
    scheduler.add_job(
        _scheduled_governance_queue_poll,
        "interval",
        seconds=get_settings().governance_job_poll_interval_seconds,
        coalesce=True,
        max_instances=1,
    )
    settings = get_settings()
    scheduler.add_job(
        run_time_series_planner,
        "interval",
        seconds=settings.time_series_plan_interval_seconds,
        coalesce=True,
        max_instances=1,
        id="time_series_planner",
    )
    scheduler.add_job(
        run_time_series_queue_poll,
        "interval",
        seconds=settings.time_series_job_poll_interval_seconds,
        coalesce=True,
        max_instances=1,
        id="time_series_queue_poll",
    )
    scheduler.add_job(
        run_time_series_retention,
        "cron",
        hour=settings.time_series_retention_cron_hour_utc,
        minute=15,
        timezone=UTC,
        coalesce=True,
        max_instances=1,
        id="time_series_retention",
    )
    scheduler.add_job(
        _scheduled_report_planner,
        "interval",
        seconds=settings.report_plan_interval_seconds,
        coalesce=True,
        max_instances=1,
        id="report_planner",
    )
    scheduler.add_job(
        _scheduled_report_queue_poll,
        "interval",
        seconds=settings.report_job_poll_interval_seconds,
        coalesce=True,
        max_instances=1,
        id="report_queue_poll",
    )
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
    app.include_router(programs.router, prefix=api_prefix)
    app.include_router(projects.router, prefix=api_prefix)
    app.include_router(dashboard.router, prefix=api_prefix)
    app.include_router(delivery.router, prefix=api_prefix)
    app.include_router(delivery_dashboard.router, prefix=api_prefix)
    app.include_router(delivery_chat.router, prefix=api_prefix)
    app.include_router(quality.router, prefix=api_prefix)
    app.include_router(workforce.router, prefix=api_prefix)
    app.include_router(agents.router, prefix=api_prefix)
    app.include_router(communications.router, prefix=api_prefix)
    app.include_router(metrics.router, prefix=api_prefix)
    app.include_router(kpis.router, prefix=api_prefix)
    app.include_router(time_series.router, prefix=api_prefix)
    app.include_router(reports.router, prefix=api_prefix)
    app.include_router(csat.router, prefix=api_prefix)
    app.include_router(knowledge.router, prefix=api_prefix)
    app.include_router(governance_routes.router, prefix=api_prefix)
    app.include_router(client_intelligence.router, prefix=api_prefix)
    app.include_router(admin_audit.router, prefix=api_prefix)
    return app


app = create_app()
