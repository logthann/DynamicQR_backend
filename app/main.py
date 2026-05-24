"""FastAPI application bootstrap and top-level router registration."""

import asyncio
import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.analytics import router as analytics_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.auth import router as auth_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.integrations import ga4_router, router as integrations_router
from app.api.v1.qr_codes import router as qr_codes_router
from app.api.v1.redirect import router as redirect_router
from app.api.v1.tracking import router as tracking_router
from app.api.v1.users import router as users_router
from app.core.config import get_settings
from app.workers.dev_scan_worker import run_scan_log_worker

# Sanity check: if this line never appears, the process entrypoint/console wiring is wrong.
print("!!! BACKEND BOOTSTRAP COMPLETE !!!", flush=True)

logger = logging.getLogger(__name__)


def _ensure_runtime_log_visibility() -> None:
    """Keep runtime logs visible without replacing Uvicorn's logging config."""

    root_logger = logging.getLogger()
    if root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        target_logger = logging.getLogger(logger_name)
        if target_logger.level > logging.INFO:
            target_logger.setLevel(logging.INFO)


def create_application() -> FastAPI:
    """Build and configure the FastAPI application instance."""

    _ensure_runtime_log_visibility()

    app = FastAPI(
        title="Dynamic QR Platform API",
        version="0.1.0",
        description="Backend API for Dynamic QR campaigns and analytics.",
    )

    settings = get_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    api_v1_router = APIRouter(prefix="/api/v1")

    @api_v1_router.get("/health", summary="Health check")
    async def health_check() -> dict[str, str]:
        """Return a basic liveness response for infrastructure checks."""

        return {"status": "ok"}

    app.include_router(api_v1_router)
    app.include_router(analytics_router)
    app.include_router(dashboard_router)
    app.include_router(auth_router)
    app.include_router(campaigns_router)
    app.include_router(integrations_router)
    app.include_router(ga4_router)
    app.include_router(qr_codes_router)
    app.include_router(redirect_router)
    app.include_router(tracking_router)
    app.include_router(users_router)

    @app.on_event("startup")
    async def _start_embedded_scan_worker_if_needed() -> None:
        logger.info("Application startup hook running")
        queue_backend = settings.queue_backend.lower().strip()
        # Only start an embedded worker when the configured backend is the in-memory
        # implementation. In production this is discouraged, but for single-instance
        # deployments (e.g. a single Render web instance) it is a pragmatic shortcut.
        if queue_backend != "memory":
            return

        if settings.app_env != "local":
            logger.warning(
                "QUEUE_BACKEND=memory and APP_ENV=%s: starting embedded worker in non-local environment. "
                "This is not durable or scalable — consider using a Redis-backed queue and a separate worker.",
                settings.app_env,
            )

        # In-memory queue is process-local, so same-process consumer is required.
        task = asyncio.create_task(run_scan_log_worker(poll_interval_seconds=0.1))
        app.state.scan_worker_task = task
        logger.info("Started embedded scan worker for memory queue (process-local)")

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

