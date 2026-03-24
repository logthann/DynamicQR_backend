"""Shared pytest fixtures for API and async client setup."""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_application


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """Create a single application instance for the full test session."""

    return create_application()


@pytest.fixture()
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client bound to the in-memory ASGI app."""

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client

