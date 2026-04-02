"""Authentication endpoints with OpenAPI-rich metadata."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db_session

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
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RegisterResponse:
    """Register a new user account in the users table."""

    if payload.role not in {"admin", "agency", "user"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported role")

    password_hash = hash_password(payload.password)

    insert_statement = text(
        """
        INSERT INTO users (
            email,
            password_hash,
            company_name,
            role,
            created_at,
            updated_at,
            deleted_at
        ) VALUES (
            :email,
            :password_hash,
            :company_name,
            :role,
            UTC_TIMESTAMP(),
            UTC_TIMESTAMP(),
            NULL
        )
        """
    )

    try:
        await session.execute(
            insert_statement,
            {
                "email": payload.email.strip().lower(),
                "password_hash": password_hash,
                "company_name": payload.company_name,
                "role": payload.role,
            },
        )
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        ) from exc

    select_statement = text(
        """
        SELECT id, email, role, company_name, created_at
        FROM users
        WHERE email = :email
          AND deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = (
        await session.execute(
            select_statement,
            {"email": payload.email.strip().lower()},
        )
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registered user could not be loaded",
        )

    return RegisterResponse.model_validate(dict(row))


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login user",
    description="Authenticate credentials and issue a JWT access token.",
    response_description="JWT access token payload.",
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """Authenticate a user against persisted credentials and issue JWT."""

    statement = text(
        """
        SELECT id, email, password_hash, role, company_name
        FROM users
        WHERE email = :email
          AND deleted_at IS NULL
        LIMIT 1
        """
    )
    row = (
        await session.execute(
            statement,
            {"email": payload.email.strip().lower()},
        )
    ).mappings().first()

    if row is None or not verify_password(payload.password, str(row["password_hash"])):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(
        subject=str(row["id"]),
        role=str(row["role"]),
        extra_claims={
            "email": str(row["email"]),
            "company_name": row["company_name"],
        },
    )
    return LoginResponse(access_token=token)

