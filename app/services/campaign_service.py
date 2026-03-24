"""Campaign service with RBAC-aware ownership enforcement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.rbac import Principal, RBACError, ensure_scope_access
from app.repositories.campaigns import CampaignRepository
from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignUpdate

CompanyNameResolver = Callable[[int], Awaitable[str | None]]


class CampaignService:
    """Coordinate campaign workflows with role/scope authorization checks."""

    def __init__(
        self,
        repository: CampaignRepository,
        *,
        company_name_resolver: CompanyNameResolver | None = None,
    ) -> None:
        self.repository = repository
        self.company_name_resolver = company_name_resolver

    async def create_campaign(
        self,
        principal: Principal,
        payload: CampaignCreate,
        *,
        owner_user_id: int | None = None,
        owner_company_name: str | None = None,
    ) -> CampaignRead:
        """Create a campaign after validating principal ownership scope."""

        target_owner = owner_user_id if owner_user_id is not None else principal.user_id

        if principal.role == "admin":
            return await self.repository.create(target_owner, payload)

        company_name = await self._resolve_owner_company_name(
            target_owner,
            fallback=owner_company_name,
        )
        ensure_scope_access(
            principal,
            owner_user_id=target_owner,
            owner_company_name=company_name,
        )
        return await self.repository.create(target_owner, payload)

    async def get_campaign(
        self,
        principal: Principal,
        campaign_id: int,
        *,
        include_deleted: bool = False,
    ) -> CampaignRead | None:
        """Return one campaign if principal is authorized for its ownership scope."""

        campaign = await self.repository.get_by_id(campaign_id, include_deleted=include_deleted)
        if campaign is None:
            return None

        owner_company_name = await self._resolve_owner_company_name(campaign.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=campaign.user_id,
            owner_company_name=owner_company_name,
        )
        return campaign

    async def list_campaigns_by_owner(
        self,
        principal: Principal,
        *,
        owner_user_id: int,
        owner_company_name: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CampaignRead]:
        """List campaigns for one owner if principal can access the owner scope."""

        resolved_company_name = await self._resolve_owner_company_name(
            owner_user_id,
            fallback=owner_company_name,
        )
        ensure_scope_access(
            principal,
            owner_user_id=owner_user_id,
            owner_company_name=resolved_company_name,
        )
        return await self.repository.list_by_user(
            owner_user_id,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )

    async def update_campaign(
        self,
        principal: Principal,
        campaign_id: int,
        payload: CampaignUpdate,
    ) -> CampaignRead | None:
        """Update one campaign if principal can access the campaign ownership scope."""

        existing = await self.repository.get_by_id(campaign_id)
        if existing is None:
            return None

        owner_company_name = await self._resolve_owner_company_name(existing.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=existing.user_id,
            owner_company_name=owner_company_name,
        )
        return await self.repository.update(campaign_id, payload)

    async def delete_campaign(self, principal: Principal, campaign_id: int) -> bool:
        """Soft-delete one campaign if principal can access campaign ownership scope."""

        existing = await self.repository.get_by_id(campaign_id)
        if existing is None:
            return False

        owner_company_name = await self._resolve_owner_company_name(existing.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=existing.user_id,
            owner_company_name=owner_company_name,
        )
        return await self.repository.soft_delete(campaign_id)

    async def _resolve_owner_company_name(
        self,
        owner_user_id: int,
        *,
        fallback: str | None = None,
    ) -> str | None:
        """Resolve owner company name for agency-scope checks when available."""

        if fallback is not None:
            return fallback

        if self.company_name_resolver is None:
            return None

        return await self.company_name_resolver(owner_user_id)


def require_campaign_access(
    principal: Principal,
    campaign: CampaignRead,
    *,
    owner_company_name: str | None,
) -> None:
    """Standalone access guard that can be reused in route-level compositions."""

    ensure_scope_access(
        principal,
        owner_user_id=campaign.user_id,
        owner_company_name=owner_company_name,
    )


__all__ = [
    "CampaignService",
    "CompanyNameResolver",
    "RBACError",
    "require_campaign_access",
]

