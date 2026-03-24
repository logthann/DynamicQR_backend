"""Tests for auth endpoints and OpenAPI-visible response payloads."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_returns_created_user_payload(app: FastAPI, async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "secret-pass-123",
            "role": "user",
            "company_name": "Acme",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["role"] == "user"


@pytest.mark.asyncio
async def test_login_returns_bearer_token(app: FastAPI, async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "secret-pass-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert len(body["access_token"]) > 10

