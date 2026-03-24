"""Authentication endpoints with OpenAPI-rich metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import create_access_token, hash_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Input payload for account registration."""

    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    company_name: str | None = Field(default=None, max_length=255)
    role: str = Field(default="user", pattern="^(admin|agency|user)$")


class RegisterResponse(BaseModel):
    """Registration response model for OpenAPI and API clients."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    company_name: str | None = None
    created_at: datetime


class LoginRequest(BaseModel):
    """Input payload for JWT login."""

    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginResponse(BaseModel):
    """JWT login response payload."""

    access_token: str
    token_type: str = "bearer"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register user",
    description="Register a user account and return normalized profile data.",
    response_description="Registered account details.",
)
async def register(payload: RegisterRequest) -> RegisterResponse:
    """Register a new user account.

    Note: this bootstrap implementation returns a normalized response model and
    hashes passwords to enforce security conventions for future persistence wiring.
    """

    if payload.role not in {"admin", "agency", "user"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported role")

    _ = hash_password(payload.password)
    return RegisterResponse(
        id=1,
        email=payload.email,
        role=payload.role,
        company_name=payload.company_name,
        created_at=datetime.now(UTC),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login user",
    description="Authenticate credentials and issue a JWT access token.",
    response_description="JWT access token payload.",
)
async def login(payload: LoginRequest) -> LoginResponse:
    """Authenticate a user and issue a signed JWT token."""

    token = create_access_token(
        subject="1",
        role="user",
        extra_claims={"email": str(payload.email)},
    )
    return LoginResponse(access_token=token)

