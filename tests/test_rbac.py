"""Unit tests for RBAC role and scope guard helpers."""

import pytest

from app.core.rbac import (
    RBACError,
    Principal,
    ensure_scope_access,
    principal_from_claims,
    require_any_role,
    scope_filter,
)


def test_principal_from_claims_parses_valid_claims() -> None:
    principal = principal_from_claims(
        {
            "sub": "42",
            "role": "employee",
        }
    )

    assert principal == Principal(user_id=42, role="employee")


def test_principal_from_claims_rejects_invalid_role() -> None:
    with pytest.raises(ValueError):
        principal_from_claims({"sub": "1", "role": "manager"})


def test_admin_can_access_any_scope() -> None:
    admin = Principal(user_id=1, role="admin")

    ensure_scope_access(
        admin,
        owner_user_id=999,
        owner_company_name="Other Co",
    )


def test_employee_scope_requires_creator_match() -> None:
    user = Principal(user_id=7, role="employee")

    ensure_scope_access(
        user,
        owner_user_id=7,
        owner_company_name="Acme",
    )

    with pytest.raises(RBACError):
        ensure_scope_access(
            user,
            owner_user_id=8,
            owner_company_name="Acme",
        )


def test_scope_filter_by_role() -> None:
    assert scope_filter(Principal(user_id=1, role="admin")) == {}
    assert scope_filter(Principal(user_id=4, role="employee")) == {"user_id": 4}


def test_require_any_role_enforces_allowed_roles() -> None:
    require_any_role(Principal(user_id=1, role="admin"), ["admin", "employee"])

    with pytest.raises(RBACError):
        require_any_role(Principal(user_id=8, role="employee"), ["admin"])

