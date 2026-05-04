"""Tests for auth endpoints and OpenAPI-visible response payloads."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.security import create_access_token, create_service_token


@pytest.mark.asyncio
async def test_register_returns_created_user_payload(app: FastAPI, async_client: AsyncClient) -> None:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secret-pass-123",
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "full_name": "Demo Employee",
            "phone_number": "+84123456789",
            "address": "HCM City",
            "role": "employee",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["role"] == "employee"


@pytest.mark.asyncio
async def test_login_returns_bearer_token(app: FastAPI, async_client: AsyncClient) -> None:
    email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    register_response = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secret-pass-123",
            "username": f"login_{uuid.uuid4().hex[:8]}",
            "full_name": "Login Employee",
            "phone_number": "+84987654321",
            "address": "Hanoi",
            "role": "employee",
        },
    )
    assert register_response.status_code == 201

    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secret-pass-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert len(body["access_token"]) > 10


@pytest.mark.asyncio
async def test_tracking_event_requires_service_token(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/tracking/event",
        json={
            "campaign_id": 1,
            "qr_id": 2,
            "ga_measurement_id": "G-ABC12345",
            "event_name": "qr_scan",
            "event_params": {"short_code": "abc123"},
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tracking_event_rejects_user_access_token(async_client: AsyncClient) -> None:
    user_token = create_access_token(subject="42", role="employee")
    response = await async_client.post(
        "/api/v1/tracking/event",
        json={
            "campaign_id": 1,
            "qr_id": 2,
            "ga_measurement_id": "G-ABC12345",
            "event_name": "qr_scan",
            "event_params": {"short_code": "abc123"},
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tracking_event_accepts_service_token(async_client: AsyncClient) -> None:
    service_token = create_service_token("tracking-worker")
    response = await async_client.post(
        "/api/v1/tracking/event",
        json={
            "campaign_id": 1,
            "qr_id": 2,
            "ga_measurement_id": "G-ABC12345",
            "event_name": "qr_scan",
            "event_params": {"short_code": "abc123"},
        },
        headers={"Authorization": f"Bearer {service_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["event_name"] == "qr_scan"


