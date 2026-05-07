"""User/Employee management endpoints for dashboard accounts module."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Principal
from app.core.security import decode_access_token, hash_password, verify_password
from app.db.session import get_db_session

router = APIRouter(prefix="/api/v1/users", tags=["users"])
bearer_scheme = HTTPBearer(auto_error=False)

UserRole = Literal["admin", "employee"]


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    x_user_id: int | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Principal:
    """Resolve authenticated principal from JWT bearer token.

    A temporary header-based fallback can be enabled only for local dev/tests with
    ALLOW_HEADER_PRINCIPAL_AUTH=true.
    """

    if credentials is not None and credentials.scheme.lower() == "bearer":
        try:
            token = str(credentials.credentials)
            payload = decode_access_token(token)
            subject = payload.get("sub")
            role = str(payload.get("role", "")).strip().lower()
            if subject is None or role not in {"admin", "employee"}:
                raise ValueError("Token payload missing required claims")

            return Principal(
                user_id=int(str(subject)),
                role=role,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            ) from exc

    allow_header_fallback = os.getenv("ALLOW_HEADER_PRINCIPAL_AUTH", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if allow_header_fallback and x_user_id is not None and x_role:
        role = x_role.strip().lower()
        if role not in {"admin", "employee"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role header")
        return Principal(user_id=x_user_id, role=role)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def _format_user_id(user_id: int) -> str:
    """Format integer user ID to string format 'u_{id}'."""
    return f"u_{user_id}"


def _parse_user_id(user_id: str) -> int:
    """Parse user ID from either `u_{id}` or a raw numeric path segment."""

    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("Invalid user ID format")

    if normalized_user_id.startswith("u_"):
        normalized_user_id = normalized_user_id[2:]

    if not normalized_user_id.isdigit():
        raise ValueError("Invalid user ID format")

    return int(normalized_user_id)


class PaginationMeta(BaseModel):
    """Pagination metadata for list responses."""

    page: int = Field(..., ge=1)
    limit: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)


class UserListItem(BaseModel):
    """User item for list response."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    username: str | None = None
    email: str
    full_name: str | None = None
    phone: str | None = Field(default=None, alias="phone_number")
    role: str
    campaigns_created: int
    qr_codes_created: int
    created_at: datetime


class UserListResponse(BaseModel):
    """Response for listing users."""

    users: list[UserListItem]
    pagination: PaginationMeta


class UserCampaignItem(BaseModel):
    """Campaign item in user detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    created_at: datetime


class UserQRCodeItem(BaseModel):
    """QR code item in user detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    scans: int
    created_at: datetime


class UserDetail(UserListItem):
    """Extended user detail with password metadata."""

    password_masked: str = "********"
    password_editable: bool = True


class UserDetailResponse(BaseModel):
    """Response for getting user detail."""

    user: UserDetail
    campaigns: list[UserCampaignItem]
    qr_codes: list[UserQRCodeItem]


class UpdateUserRequest(BaseModel):
    """Request to update user profile."""

    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=3, max_length=64)
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(
        default=None,
        max_length=32,
        validation_alias=AliasChoices("phone", "phone_number"),
    )
    email: str | None = Field(
        default=None,
        pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        max_length=255,
    )


class ChangePasswordRequest(BaseModel):
    """Request body for password updates."""

    model_config = ConfigDict(extra="forbid")

    current_password: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordChangeResponse(BaseModel):
    """Response after a password update."""

    message: str


class UpdateUserResponse(BaseModel):
    """Response after updating user."""

    user: UserListItem


class ErrorResponse(BaseModel):
    """Standard error response."""

    message: str
    code: str | None = None
    details: dict | None = None


def _require_admin(principal: Principal) -> None:
    """Require admin role, raise 403 if not."""
    if principal.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can perform this operation")


def _require_owner_or_admin(principal: Principal, target_user_id: int) -> None:
    """Require a caller to be the user themselves or an admin."""

    if principal.role == "admin" or principal.user_id == target_user_id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Cannot access other users' profiles",
    )


def _can_access_user(principal: Principal, target_user_id: int) -> bool:
    """Check if principal can access target user."""
    if principal.role == "admin":
        return True
    return principal.user_id == target_user_id


@router.get(
    "",
    response_model=UserListResponse,
    summary="List users (employees)",
    description="Returns paginated users with activity counters for table rendering.",
    response_description="Paginated users",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "Invalid request"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "Insufficient permissions"},
    },
)
@router.get(
    "/",
    include_in_schema=False,
)
async def list_users(
    q: str | None = Query(default=None, max_length=255, description="Search by username/email/full name"),
    role: UserRole | None = Query(default=None, description="Filter by user role"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: Literal["created_at", "username", "campaigns_created", "qr_codes_created"] = Query(
        default="created_at", description="Sort field"
    ),
    sort_order: Literal["asc", "desc"] = Query(default="desc", description="Sort order"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
) -> UserListResponse:
    """List users with pagination, search, filter, and sorting."""

    _require_admin(principal)

    offset = (page - 1) * limit

    valid_sort_fields = {
        "created_at": "u.created_at",
        "username": "u.username",
        "campaigns_created": "campaigns_created",
        "qr_codes_created": "qr_codes_created",
    }
    sort_field = valid_sort_fields.get(sort_by, "u.created_at")
    sort_direction = "ASC" if sort_order == "asc" else "DESC"

    where_clauses = ["u.deleted_at IS NULL"]
    params: dict = {}

    if q:
        where_clauses.append(
            "(u.username LIKE :q OR u.email LIKE :q OR u.full_name LIKE :q)"
        )
        params["q"] = f"%{q}%"

    if role:
        where_clauses.append("u.role = :role")
        params["role"] = role

    where_sql = " AND ".join(where_clauses)

    count_sql = f"""
        SELECT COUNT(*) as total
        FROM users u
        WHERE {where_sql}
    """
    count_result = await session.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    users_sql = f"""
        SELECT
            u.id,
            u.username,
            u.email,
            u.full_name,
            u.phone_number,
            u.role,
            u.created_at,
            COALESCE(c.campaign_count, 0) as campaigns_created,
            COALESCE(q.qr_count, 0) as qr_codes_created
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) as campaign_count
            FROM campaigns
            WHERE deleted_at IS NULL
            GROUP BY user_id
        ) c ON c.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) as qr_count
            FROM qr_codes
            WHERE deleted_at IS NULL
            GROUP BY user_id
        ) q ON q.user_id = u.id
        WHERE {where_sql}
        ORDER BY {sort_field} {sort_direction}
        LIMIT :limit OFFSET :offset
    """
    query_params = {**params, "limit": limit, "offset": offset}
    result = await session.execute(text(users_sql), query_params)
    rows = result.mappings().all()

    users = [
        UserListItem(
            id=_format_user_id(row["id"]),
            username=row["username"],
            email=row["email"],
            full_name=row["full_name"],
            phone=row["phone_number"],
            role=row["role"],
            campaigns_created=row["campaigns_created"],
            qr_codes_created=row["qr_codes_created"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

    total_pages = (total + limit - 1) // limit

    return UserListResponse(
        users=users,
        pagination=PaginationMeta(
            page=page,
            limit=limit,
            total=total,
            total_pages=total_pages,
        ),
    )


@router.get(
    "/{user_id}",
    response_model=UserDetailResponse,
    summary="Get user detail",
    description="Returns profile + activity lists for detail screen.",
    response_description="User detail with campaigns and qr codes",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def get_user_detail(
    user_id: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
) -> UserDetailResponse:
    """Get user detail with campaigns and QR codes."""

    try:
        target_user_id = _parse_user_id(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    if not _can_access_user(principal, target_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access other users' profiles",
        )

    user_sql = """
        SELECT
            u.id,
            u.username,
            u.email,
            u.full_name,
            u.phone_number,
            u.role,
            u.created_at,
            COALESCE(c.campaign_count, 0) as campaigns_created,
            COALESCE(q.qr_count, 0) as qr_codes_created
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) as campaign_count
            FROM campaigns
            WHERE deleted_at IS NULL
            GROUP BY user_id
        ) c ON c.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) as qr_count
            FROM qr_codes
            WHERE deleted_at IS NULL
            GROUP BY user_id
        ) q ON q.user_id = u.id
        WHERE u.id = :user_id AND u.deleted_at IS NULL
    """
    user_result = await session.execute(text(user_sql), {"user_id": target_user_id})
    user_row = user_result.mappings().first()

    if user_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    campaigns_sql = """
        SELECT
            id,
            name,
            status,
            created_at
        FROM campaigns
        WHERE user_id = :user_id AND deleted_at IS NULL
        ORDER BY created_at DESC
    """
    campaigns_result = await session.execute(text(campaigns_sql), {"user_id": target_user_id})
    campaign_rows = campaigns_result.mappings().all()

    campaigns = [
        UserCampaignItem(
            id=str(row["id"]),
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
        )
        for row in campaign_rows
    ]

    qr_codes_sql = """
        SELECT
            q.id,
            COALESCE(cfg.name, CONCAT('QR #', q.id)) as name,
            COALESCE(s.total_scans, 0) as scans,
            q.created_at
        FROM qr_codes q
        LEFT JOIN qr_configurations cfg
            ON cfg.qr_id = q.id
            AND cfg.is_current = 1
        LEFT JOIN (
            SELECT qc.qr_id, COUNT(*) as total_scans
            FROM scan_logs sl
            JOIN qr_configurations qc ON qc.id = sl.qr_configurations_id
            GROUP BY qc.qr_id
        ) s ON s.qr_id = q.id
        WHERE q.user_id = :user_id AND q.deleted_at IS NULL
        ORDER BY q.created_at DESC
    """
    qr_result = await session.execute(text(qr_codes_sql), {"user_id": target_user_id})
    qr_rows = qr_result.mappings().all()

    qr_codes = [
        UserQRCodeItem(
            id=str(row["id"]),
            name=row["name"],
            scans=row["scans"],
            created_at=row["created_at"],
        )
        for row in qr_rows
    ]

    user_detail = UserDetail(
        id=_format_user_id(user_row["id"]),
        username=user_row["username"],
        email=user_row["email"],
        full_name=user_row["full_name"],
        phone=user_row["phone_number"],
        role=user_row["role"],
        campaigns_created=user_row["campaigns_created"],
        qr_codes_created=user_row["qr_codes_created"],
        created_at=user_row["created_at"],
    )

    return UserDetailResponse(
        user=user_detail,
        campaigns=campaigns,
        qr_codes=qr_codes,
    )


@router.patch(
    "/{user_id}",
    response_model=UpdateUserResponse,
    summary="Update user profile",
    description="Updates editable fields from employee detail form. Password is optional.",
    response_description="Updated user",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "Invalid request"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "User not found"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Duplicate email/username"},
    },
)
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
) -> UpdateUserResponse:
    """Update user profile."""

    try:
        target_user_id = _parse_user_id(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    _require_owner_or_admin(principal, target_user_id)

    check_sql = "SELECT id FROM users WHERE id = :user_id AND deleted_at IS NULL"
    check_result = await session.execute(text(check_sql), {"user_id": target_user_id})
    if check_result.scalar() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    update_fields = []
    params: dict = {"user_id": target_user_id}

    if payload.username is not None:
        update_fields.append("username = :username")
        params["username"] = payload.username.strip()
    if payload.full_name is not None:
        update_fields.append("full_name = :full_name")
        params["full_name"] = payload.full_name.strip()
    if payload.phone is not None:
        update_fields.append("phone_number = :phone")
        params["phone"] = payload.phone.strip()
    if payload.email is not None:
        update_fields.append("email = :email")
        params["email"] = payload.email.strip().lower()

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    update_fields.append("updated_at = UTC_TIMESTAMP()")

    update_sql = f"""
        UPDATE users
        SET {', '.join(update_fields)}
        WHERE id = :user_id
    """

    try:
        await session.execute(text(update_sql), params)
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already exists",
        ) from exc

    select_sql = """
        SELECT
            u.id,
            u.username,
            u.email,
            u.full_name,
            u.phone_number,
            u.role,
            u.created_at,
            COALESCE(c.campaign_count, 0) as campaigns_created,
            COALESCE(q.qr_count, 0) as qr_codes_created
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) as campaign_count
            FROM campaigns
            WHERE deleted_at IS NULL
            GROUP BY user_id
        ) c ON c.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) as qr_count
            FROM qr_codes
            WHERE deleted_at IS NULL
            GROUP BY user_id
        ) q ON q.user_id = u.id
        WHERE u.id = :user_id
    """
    result = await session.execute(text(select_sql), {"user_id": target_user_id})
    row = result.mappings().first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load updated user",
        )

    return UpdateUserResponse(
        user=UserListItem(
            id=_format_user_id(row["id"]),
            username=row["username"],
            email=row["email"],
            full_name=row["full_name"],
            phone=row["phone_number"],
            role=row["role"],
            campaigns_created=row["campaigns_created"],
            qr_codes_created=row["qr_codes_created"],
            created_at=row["created_at"],
        )
    )


@router.patch(
    "/{user_id}/password",
    response_model=PasswordChangeResponse,
    summary="Change user password",
    description="Change the authenticated user's password or let an admin reset it.",
    response_description="Password changed successfully.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "Invalid request"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "User not found"},
    },
)
@router.post(
    "/{user_id}/password",
    response_model=PasswordChangeResponse,
    include_in_schema=False,
)
async def change_user_password(
    user_id: str,
    payload: ChangePasswordRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
) -> PasswordChangeResponse:
    """Change a user's password with owner/admin access control."""

    try:
        target_user_id = _parse_user_id(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    _require_owner_or_admin(principal, target_user_id)

    check_sql = "SELECT password_hash FROM users WHERE id = :user_id AND deleted_at IS NULL"
    check_result = await session.execute(text(check_sql), {"user_id": target_user_id})
    row = check_result.mappings().first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if principal.user_id == target_user_id:
        if not payload.current_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is required",
            )
        if not verify_password(payload.current_password, str(row["password_hash"])):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

    update_sql = """
        UPDATE users
        SET password_hash = :password_hash,
            updated_at = UTC_TIMESTAMP()
        WHERE id = :user_id
    """
    await session.execute(
        text(update_sql),
        {"user_id": target_user_id, "password_hash": hash_password(payload.new_password)},
    )
    await session.flush()

    return PasswordChangeResponse(message="Password updated successfully")


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user",
    description="Soft-delete user by setting deleted_at timestamp.",
    response_description="User deleted",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def delete_user(
    user_id: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Soft-delete a user."""

    _require_admin(principal)

    try:
        target_user_id = _parse_user_id(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    check_sql = "SELECT id FROM users WHERE id = :user_id AND deleted_at IS NULL"
    check_result = await session.execute(text(check_sql), {"user_id": target_user_id})
    if check_result.scalar() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    delete_sql = """
        UPDATE users
        SET deleted_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
        WHERE id = :user_id
    """
    await session.execute(text(delete_sql), {"user_id": target_user_id})

    return Response(status_code=status.HTTP_204_NO_CONTENT)
