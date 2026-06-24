from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.delivery.routes import dashboard as delivery_dashboard
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
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.exceptions import register_exception_handlers
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
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

    app.add_middleware(CsrfMiddleware)
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
    app.include_router(quality.router, prefix=api_prefix)
    app.include_router(agents.router, prefix=api_prefix)
    app.include_router(communications.router, prefix=api_prefix)
    app.include_router(metrics.router, prefix=api_prefix)
    app.include_router(csat.router, prefix=api_prefix)
    app.include_router(knowledge.router, prefix=api_prefix)
    return app


app = create_app()
