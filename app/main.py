"""FastAPI application entrypoint.

Run (dev):   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import settings
from app.core.logging import (
    configure_logging,
    get_logger,
    log_extra,
    request_id_ctx,
)
from app.db.session import init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.assert_production_ready()
    if not settings.is_production:
        # Dev/CI convenience: build tables from the ORM metadata.
        # Production uses the reviewed SQL migrations (incl. RLS).
        init_db()
    logger.info(
        "app.startup",
        extra=log_extra(version=__version__, environment=settings.environment),
    )
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Lead capture, AI qualification, CRM and growth automation for "
            "MassageVIP Riyadh. Scores are triage heuristics, not predictions."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    )

    @app.middleware("http")
    async def correlation_and_timing(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
        logger.exception("unhandled_error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id_ctx.get()},
        )

    # --- Routes -----------------------------------------------------------
    from app.api.routes import auth, bookings, followups, health, leads, whatsapp

    app.include_router(health.router)  # /health is unprefixed by design
    app.include_router(leads.router, prefix=settings.api_v1_prefix)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(whatsapp.router, prefix=settings.api_v1_prefix)
    app.include_router(bookings.router, prefix=settings.api_v1_prefix)
    app.include_router(followups.router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
