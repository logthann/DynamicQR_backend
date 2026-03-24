"""FastAPI application bootstrap and top-level router registration."""

from fastapi import APIRouter, FastAPI


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
    return app


app = create_application()

