"""QR service for URL/event flows with short-code generation and persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.rbac import Principal, RBACError, ensure_scope_access
from app.repositories.qr_codes import QRCodeRepository
from app.schemas.qr_code import QRCodeCreate, QRCodeRead, QRCodeStatus, QRCodeUpdate, QRType
from app.services.short_code_service import ExistsChecker, generate_unique_base62_code

CompanyNameResolver = Callable[[int], Awaitable[str | None]]
UniqueCodeGenerator = Callable[[ExistsChecker], Awaitable[str]]
EventQRHandler = Callable[[int, QRCodeCreate], Awaitable[None]]


class QRService:
    """Coordinate QR lifecycle operations with RBAC and short-code generation."""

    def __init__(
        self,
        repository: QRCodeRepository,
        *,
        company_name_resolver: CompanyNameResolver | None = None,
        short_code_generator: UniqueCodeGenerator | None = None,
        event_qr_handler: EventQRHandler | None = None,
    ) -> None:
        self.repository = repository
        self.company_name_resolver = company_name_resolver
        self.short_code_generator = short_code_generator or self._default_short_code_generator
        self.event_qr_handler = event_qr_handler

    async def create_qr(
        self,
        principal: Principal,
        payload: QRCodeCreate,
        *,
        owner_user_id: int | None = None,
        owner_company_name: str | None = None,
    ) -> QRCodeRead:
        """Create one QR code and trigger event hook for event-type payloads."""

        target_owner = owner_user_id if owner_user_id is not None else principal.user_id

        if principal.role != "admin":
            resolved_company_name = await self._resolve_owner_company_name(
                target_owner,
                fallback=owner_company_name,
            )
            ensure_scope_access(
                principal,
                owner_user_id=target_owner,
                owner_company_name=resolved_company_name,
            )

        if payload.campaign_id is not None:
            await self._ensure_campaign_in_owner_scope(target_owner, payload.campaign_id)

        short_code = await self.short_code_generator(self._short_code_exists)
        created = await self.repository.create(target_owner, short_code, payload)

        if payload.qr_type == QRType.event and self.event_qr_handler is not None:
            await self.event_qr_handler(created.id, payload)

        return created

    async def get_qr(
        self,
        principal: Principal,
        qr_id: int,
        *,
        include_deleted: bool = False,
    ) -> QRCodeRead | None:
        """Return one QR code when principal can access its ownership scope."""

        qr_code = await self.repository.get_by_id(qr_id, include_deleted=include_deleted)
        if qr_code is None:
            return None

        owner_company_name = await self._resolve_owner_company_name(qr_code.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=qr_code.user_id,
            owner_company_name=owner_company_name,
        )
        return qr_code

    async def list_qrs_by_owner(
        self,
        principal: Principal,
        *,
        owner_user_id: int,
        owner_company_name: str | None = None,
        campaign_id: int | None = None,
        status: QRCodeStatus | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[QRCodeRead]:
        """List QR codes for one owner when principal can access the ownership scope."""

        resolved_company_name = await self._resolve_owner_company_name(
            owner_user_id,
            fallback=owner_company_name,
        )
        ensure_scope_access(
            principal,
            owner_user_id=owner_user_id,
            owner_company_name=resolved_company_name,
        )

        if campaign_id is not None:
            await self._ensure_campaign_in_owner_scope(owner_user_id, campaign_id)

        return await self.repository.list_by_user(
            owner_user_id,
            campaign_id=campaign_id,
            status=status,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )

    async def update_qr(
        self,
        principal: Principal,
        qr_id: int,
        payload: QRCodeUpdate,
    ) -> QRCodeRead | None:
        """Update one QR code when principal can access the QR owner scope."""

        existing = await self.repository.get_by_id(qr_id)
        if existing is None:
            return None

        owner_company_name = await self._resolve_owner_company_name(existing.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=existing.user_id,
            owner_company_name=owner_company_name,
        )
        return await self.repository.update(qr_id, payload)

    async def set_qr_status(
        self,
        principal: Principal,
        qr_id: int,
        status: QRCodeStatus,
    ) -> QRCodeRead | None:
        """Set QR status when principal can access the QR owner scope."""

        existing = await self.repository.get_by_id(qr_id)
        if existing is None:
            return None

        owner_company_name = await self._resolve_owner_company_name(existing.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=existing.user_id,
            owner_company_name=owner_company_name,
        )
        return await self.repository.set_status(qr_id, status)

    async def delete_qr(self, principal: Principal, qr_id: int) -> bool:
        """Soft-delete one QR code when principal can access the QR owner scope."""

        existing = await self.repository.get_by_id(qr_id)
        if existing is None:
            return False

        owner_company_name = await self._resolve_owner_company_name(existing.user_id)
        ensure_scope_access(
            principal,
            owner_user_id=existing.user_id,
            owner_company_name=owner_company_name,
        )
        return await self.repository.soft_delete(qr_id)

    async def _short_code_exists(self, short_code: str) -> bool:
        """Return whether a short code is already present in storage/cache lookup path."""

        return await self.repository.resolve_by_short_code(short_code) is not None

    async def _default_short_code_generator(self, exists_checker: ExistsChecker) -> str:
        """Generate a unique Base62 short code with default retry policy."""

        return await generate_unique_base62_code(exists_checker)

    async def _resolve_owner_company_name(
        self,
        owner_user_id: int,
        *,
        fallback: str | None = None,
    ) -> str | None:
        """Resolve owner company for agency-scope checks if resolver is available."""

        if fallback is not None:
            return fallback

        if self.company_name_resolver is None:
            return None

        return await self.company_name_resolver(owner_user_id)

    async def _ensure_campaign_in_owner_scope(self, owner_user_id: int, campaign_id: int) -> None:
        """Fail with RBAC error when a campaign filter does not belong to the requested owner."""

        campaign_owner_user_id = await self.repository.get_campaign_owner_user_id(campaign_id)
        if campaign_owner_user_id is None or campaign_owner_user_id != owner_user_id:
            raise RBACError("Campaign is outside principal scope")

