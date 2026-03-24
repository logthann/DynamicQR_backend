"""RBAC helpers for role and scope enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

Role = Literal["admin", "agency", "user"]


class RBACError(PermissionError):
    """Raised when an action violates role-based access control rules."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated actor claims used by authorization checks."""

    user_id: int
    role: Role
    company_name: str | None = None


def _normalize_role(role_value: str) -> Role:
    """Normalize and validate a role string from auth claims."""

    role = role_value.strip().lower()
    if role in {"admin", "agency", "user"}:
        return role
    raise ValueError("Unsupported role claim")


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """Build a Principal from JWT claims.

    Expected claims:
    - sub: user identifier
    - role: one of admin|agency|user
    - company_name (optional): required for agency-scoped checks
    """

    if "sub" not in claims or "role" not in claims:
        raise ValueError("Token claims must include 'sub' and 'role'")

    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Token claim 'sub' must be an integer user id") from exc

    role_value = claims["role"]
    if not isinstance(role_value, str):
        raise ValueError("Token claim 'role' must be a string")

    company_name = claims.get("company_name")
    if company_name is not None and not isinstance(company_name, str):
        raise ValueError("Token claim 'company_name' must be a string when provided")

    return Principal(
        user_id=user_id,
        role=_normalize_role(role_value),
        company_name=company_name,
    )


def require_any_role(principal: Principal, allowed_roles: Iterable[Role]) -> None:
    """Ensure the principal has one of the allowed roles."""

    if principal.role not in set(allowed_roles):
        raise RBACError("Principal role is not allowed to access this operation")


def ensure_scope_access(
    principal: Principal,
    *,
    owner_user_id: int,
    owner_company_name: str | None,
) -> None:
    """Enforce tenant/ownership boundaries for a target resource.

    Scope rules:
    - admin: full cross-tenant access
    - agency: only resources from the same company_name
    - user: only resources they created (owner_user_id)
    """

    if principal.role == "admin":
        return

    if principal.role == "agency":
        if not principal.company_name:
            raise RBACError("Agency principal is missing company scope")
        if owner_company_name is None or owner_company_name != principal.company_name:
            raise RBACError("Agency principal cannot access resources outside company scope")
        return

    if owner_user_id != principal.user_id:
        raise RBACError("User principal cannot access resources outside creator scope")


def scope_filter(
    principal: Principal,
    *,
    owner_field: str = "user_id",
    company_field: str = "company_name",
) -> dict[str, Any]:
    """Return a repository-level filter that applies principal scope by role."""

    if principal.role == "admin":
        return {}

    if principal.role == "agency":
        if not principal.company_name:
            raise RBACError("Agency principal is missing company scope")
        return {company_field: principal.company_name}

    return {owner_field: principal.user_id}

