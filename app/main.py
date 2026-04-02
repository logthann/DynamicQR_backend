"""FastAPI application bootstrap and top-level router registration."""

import asyncio
import logging
import os

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.qr_codes import router as qr_codes_router
from app.api.v1.redirect import router as redirect_router
from app.core.config import get_settings
from app.workers.dev_scan_worker import run_scan_log_worker

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Build and configure the FastAPI application instance."""

    app = FastAPI(
        title="Dynamic QR Platform API",
        version="0.1.0",
        description="Backend API for Dynamic QR campaigns and analytics.",
    )

    allow_origins_env = os.getenv("CORS_ALLOW_ORIGINS")
    allow_origins = (
        [origin.strip() for origin in allow_origins_env.split(",") if origin.strip()]
        if allow_origins_env
        else ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_v1_router = APIRouter(prefix="/api/v1")

    @api_v1_router.get("/health", summary="Health check")
    async def health_check() -> dict[str, str]:
        """Return a basic liveness response for infrastructure checks."""

        return {"status": "ok"}

    app.include_router(api_v1_router)
    app.include_router(analytics_router)
    app.include_router(auth_router)
    app.include_router(campaigns_router)
    app.include_router(integrations_router)
    app.include_router(qr_codes_router)
    app.include_router(redirect_router)

    @app.on_event("startup")
    async def _start_embedded_scan_worker_if_needed() -> None:
        settings = get_settings()
        queue_backend = settings.queue_backend.lower().strip()
        if settings.app_env != "local" or queue_backend != "memory":
            return

        # In-memory queue is process-local, so local dev needs same-process consumer.
        task = asyncio.create_task(run_scan_log_worker(poll_interval_seconds=0.1))
        app.state.scan_worker_task = task
        logger.info("Started embedded scan worker for local memory queue")

    @app.on_event("shutdown")
    async def _stop_embedded_scan_worker_if_running() -> None:
        task = getattr(app.state, "scan_worker_task", None)
        if task is None:
            return

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        logger.info("Stopped embedded scan worker")

    return app


app = create_application()

