"""QR service for URL/event flows with short-code generation and persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re

from app.core.rbac import Principal, RBACError, ensure_scope_access
from app.repositories.qr_codes import QRCodeRepository
from app.schemas.qr_code import (
    GATrackingType,
    QRCodeCreate,
    QRCodeListItem,
    QRCodeRead,
    QRCodeStatus,
    QRCodeUpdate,
    QRType,
)
from app.services.short_code_service import ExistsChecker, generate_unique_base62_code

CompanyNameResolver = Callable[[int], Awaitable[str | None]]
UniqueCodeGenerator = Callable[[ExistsChecker], Awaitable[str]]
EventQRHandler = Callable[[int, QRCodeCreate], Awaitable[None]]
GA_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]{4,20}$")


class QRValidationError(ValueError):
    """Raised when QR payload violates GA configuration rules."""


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

        if payload.use_campaign_defaults and payload.campaign_id is None:
            raise QRValidationError("campaign_id is required when use_campaign_defaults is true")

        if payload.campaign_id is not None:
            campaign_context = await self._ensure_campaign_in_owner_scope(target_owner, payload.campaign_id)
        else:
            campaign_context = None

        normalized_payload = self._normalize_qr_create_payload(payload, campaign_context)

        short_code = await self.short_code_generator(self._short_code_exists)
        try:
            created = await self.repository.create(target_owner, short_code, normalized_payload)
        except ValueError as exc:
            raise QRValidationError(str(exc)) from exc

        if normalized_payload.qr_type == QRType.event and self.event_qr_handler is not None:
            await self.event_qr_handler(created.id, normalized_payload)

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
    ) -> list[QRCodeListItem]:
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

        # Admin gets employee info, employee does not
        include_employee = principal.role == "admin"

        return await self.repository.list_by_user_with_joins(
            owner_user_id,
            campaign_id=campaign_id,
            status=status,
            include_deleted=include_deleted,
            include_employee=include_employee,
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

        campaign_context: dict[str, str | None] | None = None
        target_campaign_id = payload.campaign_id
        if payload.use_campaign_defaults and target_campaign_id is None:
            target_campaign_id = existing.campaign_id
            if target_campaign_id is None:
                raise QRValidationError("campaign_id is required when use_campaign_defaults is true")

        if target_campaign_id is not None:
            campaign_context = await self._ensure_campaign_in_owner_scope(existing.user_id, target_campaign_id)

        normalized_payload = self._normalize_qr_update_payload(existing, payload, campaign_context)
        try:
            return await self.repository.update(qr_id, normalized_payload)
        except ValueError as exc:
            raise QRValidationError(str(exc)) from exc

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

    async def _ensure_campaign_in_owner_scope(
        self,
        owner_user_id: int,
        campaign_id: int,
    ) -> dict[str, str | None]:
        """Fail when campaign is outside scope; otherwise return campaign GA defaults."""

        campaign_context = await self.repository.get_campaign_context(campaign_id)
        if campaign_context is None or int(campaign_context["user_id"]) != owner_user_id:
            raise RBACError("Campaign is outside principal scope")

        return {
            "ga_type": campaign_context.get("ga_type"),
            "ga_measurement_id": campaign_context.get("ga_measurement_id"),
            "ga_property_id": campaign_context.get("ga_property_id"),
        }

    def _normalize_qr_create_payload(
        self,
        payload: QRCodeCreate,
        campaign_context: dict[str, str | None] | None,
    ) -> QRCodeCreate:
        """Normalize QR create payload, inheriting campaign GA defaults when omitted."""

        data = payload.model_dump()
        use_campaign_defaults = bool(data.pop("use_campaign_defaults", False))
        has_explicit_ga = any(data.get(field) is not None for field in ("ga_type", "ga_measurement_id", "ga_property_id"))

        if campaign_context is not None and (use_campaign_defaults or not has_explicit_ga):
            data["ga_type"] = campaign_context.get("ga_type")
            data["ga_measurement_id"] = campaign_context.get("ga_measurement_id")
            data["ga_property_id"] = campaign_context.get("ga_property_id")

        normalized = self._normalize_ga_values(
            ga_type=data.get("ga_type"),
            ga_measurement_id=data.get("ga_measurement_id"),
            ga_property_id=data.get("ga_property_id"),
        )
        data.update(normalized)
        return QRCodeCreate.model_validate(data)

    def _normalize_qr_update_payload(
        self,
        existing: QRCodeRead,
        payload: QRCodeUpdate,
        campaign_context: dict[str, str | None] | None,
    ) -> QRCodeUpdate:
        """Normalize QR patch payload and apply GA inheritance/override semantics."""

        data = payload.model_dump(exclude_unset=True)
        use_campaign_defaults = bool(data.pop("use_campaign_defaults", False))
        ga_fields = {"ga_type", "ga_measurement_id", "ga_property_id"}
        has_explicit_ga = bool(ga_fields.intersection(data.keys()))

        if campaign_context is not None and (use_campaign_defaults or not has_explicit_ga):
            data["ga_type"] = campaign_context.get("ga_type")
            data["ga_measurement_id"] = campaign_context.get("ga_measurement_id")
            data["ga_property_id"] = campaign_context.get("ga_property_id")
            has_explicit_ga = True

        if not has_explicit_ga:
            return payload

        resolved_type = data.get("ga_type", existing.ga_type)
        resolved_measurement = data.get("ga_measurement_id", existing.ga_measurement_id)
        resolved_property = data.get("ga_property_id", existing.ga_property_id)

        normalized = self._normalize_ga_values(
            ga_type=resolved_type,
            ga_measurement_id=resolved_measurement,
            ga_property_id=resolved_property,
        )

        data["ga_type"] = normalized["ga_type"]
        data["ga_measurement_id"] = normalized["ga_measurement_id"]
        data["ga_property_id"] = normalized["ga_property_id"]

        return QRCodeUpdate.model_validate(data)

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
            raise QRValidationError("ga_property_id is required when ga_type is OAUTH")

        if resolved_type == GATrackingType.manual:
            if not ga_measurement_id:
                raise QRValidationError("ga_measurement_id is required when ga_type is MANUAL")
            if not GA_MEASUREMENT_ID_PATTERN.match(ga_measurement_id):
                raise QRValidationError("ga_measurement_id must match pattern G-<ALPHANUM>")

        if resolved_type == GATrackingType.no:
            ga_measurement_id = None
            ga_property_id = None

        return {
            "ga_type": resolved_type,
            "ga_measurement_id": ga_measurement_id,
            "ga_property_id": ga_property_id,
        }
