"""FastAPI application bootstrap and top-level router registration."""

from fastapi import APIRouter, FastAPI

from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.qr_codes import router as qr_codes_router
from app.api.v1.redirect import router as redirect_router


def create_application() -> FastAPI:
    """Build and configure the FastAPI application instance."""

    app = FastAPI(
        title="Dynamic QR Platform API",
        version="0.1.0",
        description="Backend API for Dynamic QR campaigns and analytics.",
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
    return app


app = create_application()

