"""Campaign service with RBAC-aware ownership enforcement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re

from app.core.rbac import Principal, RBACError, ensure_scope_access
from app.repositories.campaigns import CampaignRepository
from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignUpdate, GATrackingType, CampaignCreatorInfo

CompanyNameResolver = Callable[[int], Awaitable[str | None]]
GA_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]{4,20}$")


class CampaignValidationError(ValueError):
    """Raised when campaign payload violates GA configuration rules."""


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

        normalized_payload = self._normalize_campaign_create_payload(payload)

        if principal.role == "admin":
            campaign = await self.repository.create(target_owner, normalized_payload)
            # Enrich with creator info
            creator_info = await self._resolve_creator_info(campaign.user_id)
            campaign.creator = creator_info
            return campaign

        company_name = await self._resolve_owner_company_name(
            target_owner,
            fallback=owner_company_name,
        )
        ensure_scope_access(
            principal,
            owner_user_id=target_owner,
            owner_company_name=company_name,
        )
        return await self.repository.create(target_owner, normalized_payload)

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

        # Enrich campaign with creator info for admin users
        if principal.role == "admin":
            creator_info = await self._resolve_creator_info(campaign.user_id)
            campaign.creator = creator_info

        return campaign

    async def list_campaigns_by_owner(
        self,
        principal: Principal,
        *,
        owner_user_id: int | None,
        owner_company_name: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CampaignRead]:
        """List campaigns for one owner or across all owners (admin) if owner_user_id is None.

        If owner_user_id is None and the principal is an admin, return campaigns across all users.
        Otherwise enforce scope checks and return campaigns for the specific owner.
        """

        # If admin and no owner filter provided => return all campaigns
        if owner_user_id is None and principal.role == "admin":
            campaigns = await self.repository.list_all(
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            )
        else:
            target_owner = owner_user_id if owner_user_id is not None else principal.user_id
            resolved_company_name = await self._resolve_owner_company_name(
                target_owner,
                fallback=owner_company_name,
            )
            ensure_scope_access(
                principal,
                owner_user_id=target_owner,
                owner_company_name=resolved_company_name,
            )
            campaigns = await self.repository.list_by_user(
                target_owner,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            )

        # Enrich campaigns with creator info for admin users
        if principal.role == "admin":
            for campaign in campaigns:
                creator_info = await self._resolve_creator_info(campaign.user_id)
                campaign.creator = creator_info

        return campaigns

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
        normalized_payload = self._normalize_campaign_update_payload(existing, payload)
        campaign = await self.repository.update(campaign_id, normalized_payload)

        # Enrich campaign with creator info for admin users
        if campaign and principal.role == "admin":
            creator_info = await self._resolve_creator_info(campaign.user_id)
            campaign.creator = creator_info

        return campaign

    def _normalize_campaign_create_payload(self, payload: CampaignCreate) -> CampaignCreate:
        """Normalize campaign GA fields and validate OAUTH/MANUAL/NO rules."""

        data = payload.model_dump()
        normalized = self._normalize_ga_values(
            ga_type=data.get("ga_type"),
            ga_measurement_id=data.get("ga_measurement_id"),
            ga_property_id=data.get("ga_property_id"),
        )
        data.update(normalized)
        return CampaignCreate.model_validate(data)

    def _normalize_campaign_update_payload(
        self,
        existing: CampaignRead,
        payload: CampaignUpdate,
    ) -> CampaignUpdate:
        """Normalize campaign patch GA fields and enforce consistent combinations."""

        data = payload.model_dump(exclude_unset=True)
        if not {"ga_type", "ga_measurement_id", "ga_property_id"}.intersection(data.keys()):
            return payload

        resolved_type = data.get("ga_type", existing.ga_type)
        resolved_measurement = data.get("ga_measurement_id", existing.ga_measurement_id)
        resolved_property = data.get("ga_property_id", existing.ga_property_id)

        normalized = self._normalize_ga_values(
            ga_type=resolved_type,
            ga_measurement_id=resolved_measurement,
            ga_property_id=resolved_property,
        )

        if "ga_type" in data or normalized["ga_type"] is not None:
            data["ga_type"] = normalized["ga_type"]
        if "ga_measurement_id" in data or normalized["ga_type"] == GATrackingType.no:
            data["ga_measurement_id"] = normalized["ga_measurement_id"]
        if "ga_property_id" in data or normalized["ga_type"] == GATrackingType.no:
            data["ga_property_id"] = normalized["ga_property_id"]

        return CampaignUpdate.model_validate(data)

    def _normalize_ga_values(
        self,
        *,
        ga_type: GATrackingType | str | None,
        ga_measurement_id: str | None,
        ga_property_id: str | None,
    ) -> dict[str, GATrackingType | str | None]:
        """Normalize GA values with inference and strict mode validation rules."""

        resolved_type = ga_type
        if isinstance(resolved_type, str):
            resolved_type = GATrackingType(resolved_type)

        if resolved_type is None:
            if ga_property_id:
                resolved_type = GATrackingType.oauth
            elif ga_measurement_id:
                resolved_type = GATrackingType.manual

        if resolved_type == GATrackingType.oauth and not ga_property_id:
            raise CampaignValidationError("ga_property_id is required when ga_type is OAUTH")

        if resolved_type == GATrackingType.manual:
            if not ga_measurement_id:
                raise CampaignValidationError("ga_measurement_id is required when ga_type is MANUAL")
            if not GA_MEASUREMENT_ID_PATTERN.match(ga_measurement_id):
                raise CampaignValidationError("ga_measurement_id must match pattern G-<ALPHANUM>")

        if resolved_type == GATrackingType.no:
            ga_measurement_id = None
            ga_property_id = None

        return {
            "ga_type": resolved_type,
            "ga_measurement_id": ga_measurement_id,
            "ga_property_id": ga_property_id,
        }

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

    async def _resolve_creator_info(self, user_id: int) -> CampaignCreatorInfo | None:
        """Resolve creator information (username and email) from repository."""

        if not hasattr(self.repository, 'get_creator_info'):
            return None

        try:
            creator_data = await self.repository.get_creator_info(user_id)
            if creator_data is None:
                return None

            return CampaignCreatorInfo(
                username=creator_data.get("username"),
                email=creator_data.get("email"),
            )
        except (AttributeError, TypeError, Exception):
            # Handle cases where get_creator_info is mocked or unavailable
            return None


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
    "CampaignValidationError",
    "CompanyNameResolver",
    "RBACError",
    "require_campaign_access",
]

