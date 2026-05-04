"""JWT and bcrypt security helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt."""

    encoded = plain_password.encode("utf-8")
    hashed = bcrypt.hashpw(encoded, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify plaintext password against a bcrypt hash."""

    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


def create_access_token(
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token for a user subject and role."""

    settings = get_settings()
    expire_delta = expires_delta or timedelta(
        minutes=settings.access_token_expire_minutes,
    )
    expire_at = datetime.now(UTC) + expire_delta

    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "exp": expire_at,
        "iat": datetime.now(UTC),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify JWT access token."""

    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


def create_service_token(
    service_name: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT for trusted internal service-to-service calls."""

    settings = get_settings()
    expire_delta = expires_delta or timedelta(minutes=15)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": service_name,
        "iss": settings.service_jwt_issuer,
        "aud": settings.service_jwt_audience,
        "typ": "service",
        "iat": now,
        "exp": now + expire_delta,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(
        payload,
        settings.service_jwt_secret,
        algorithm=settings.service_jwt_algorithm,
    )


def decode_service_token(token: str) -> dict[str, Any]:
    """Decode and verify service JWT including issuer/audience constraints."""

    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.service_jwt_secret,
        algorithms=[settings.service_jwt_algorithm],
        audience=settings.service_jwt_audience,
        issuer=settings.service_jwt_issuer,
    )
    if payload.get("typ") != "service":
        raise jwt.InvalidTokenError("Token type is not service")
    return payload


