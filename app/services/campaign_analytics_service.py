"""Campaign analytics service combining scan logs and GA4 data."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core.rbac import Principal, RBACError
from app.repositories.campaigns import CampaignRepository
from app.repositories.scan_logs import ScanLogRepository
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.analytics import (
    CampaignComparisonQRCode,
    CampaignComparisonResponse,
    CampaignKPISummaryResponse,
    GA4InsightsResponse,
    GA4RealtimeResponse,
    QRVersionActivePeriod,
    QRVersionComparison,
    HourlyScansResponse,
    ScanLogEntry,
    ScanLogsResponse,
)
from app.schemas.integrations import IntegrationProvider
from app.services.cache_service import CacheService
from app.services.ga4_service import GA4Service, GA4ServiceError


class CampaignAnalyticsServiceError(RuntimeError):
    """Raised when campaign analytics operations fail."""


class CampaignAnalyticsService:
    """Service for campaign analytics combining internal and GA4 data."""

    def __init__(
        self,
        campaign_repo: CampaignRepository,
        scan_log_repo: ScanLogRepository,
        user_integration_repo: UserIntegrationRepository,
        ga4_service: GA4Service,
        cache_service: CacheService | None = None,
    ) -> None:
        self.campaign_repo = campaign_repo
        self.scan_log_repo = scan_log_repo
        self.user_integration_repo = user_integration_repo
        self.ga4_service = ga4_service
        self.cache_service = cache_service or CacheService()

    async def get_kpi_summary(
        self,
        campaign_id: int,
        principal: Principal,
    ) -> CampaignKPISummaryResponse:
        """Get KPI summary for a campaign."""
        # Verify campaign access
        await self._ensure_campaign_access(campaign_id, principal)

        # Get total scans from internal data
        total_scans = await self.scan_log_repo.count_by_campaign(campaign_id)

        # Get GA4 data if available
        active_users_ga4 = 0
        avg_session_duration = 0.0
        campaign_utm_name = await self._get_campaign_utm_name(campaign_id)

        if campaign_utm_name:
            try:
                # Get user's GA4 property ID
                property_id = await self._get_user_ga4_property_id(principal.user_id)
                if property_id:
                    active_users_ga4 = await self.ga4_service.get_active_users(
                        principal.user_id, property_id, campaign_utm_name
                    )
                    avg_session_duration = await self.ga4_service.get_average_session_duration(
                        principal.user_id, property_id, campaign_utm_name
                    )
            except GA4ServiceError:
                # Log error but continue with GA4 data as 0
                pass

        # Calculate conversion rate
        conversion_rate = (active_users_ga4 / total_scans * 100) if total_scans > 0 else 0.0

        return CampaignKPISummaryResponse(
            campaign_id=campaign_id,
            total_scans=total_scans,
            active_users_ga4=active_users_ga4,
            conversion_rate=conversion_rate,
            avg_session_duration=avg_session_duration,
        )

    async def get_hourly_scans(
        self,
        campaign_id: int,
        start_date: datetime,
        end_date: datetime,
        principal: Principal,
    ) -> HourlyScansResponse:
        """Get hourly scan data for a campaign."""
        # Verify campaign access
        await self._ensure_campaign_access(campaign_id, principal)

        # Get hourly scan data
        hourly_data = await self.scan_log_repo.get_hourly_scans(campaign_id, start_date, end_date)

        return HourlyScansResponse(campaign_id=campaign_id, data=hourly_data)

    async def get_ga4_realtime(
        self,
        campaign_id: int,
        principal: Principal,
        minutes_back: int = 30,
    ) -> GA4RealtimeResponse:
        """Get GA4 real-time data for a campaign."""
        # Verify campaign access
        await self._ensure_campaign_access(campaign_id, principal)

        # Get campaign UTM name
        campaign_utm_name = await self._get_campaign_utm_name(campaign_id)
        if not campaign_utm_name:
            return GA4RealtimeResponse(campaign_id=campaign_id, data=[])

        try:
            # Get user's GA4 property ID
            property_id = await self._get_user_ga4_property_id(principal.user_id)
            if not property_id:
                return GA4RealtimeResponse(campaign_id=campaign_id, data=[])

            # Get real-time data
            data = await self.ga4_service.get_realtime_data(
                principal.user_id, property_id, campaign_utm_name, minutes_back
            )

            return GA4RealtimeResponse(campaign_id=campaign_id, data=data)

        except GA4ServiceError:
            return GA4RealtimeResponse(campaign_id=campaign_id, data=[])

    async def get_scan_logs(
        self,
        campaign_id: int,
        principal: Principal,
        page: int = 1,
        limit: int = 50,
        sort_by: str = "scanned_at",
        order: str = "desc",
    ) -> ScanLogsResponse:
        """Get paginated scan logs for a campaign."""
        # Verify campaign access
        await self._ensure_campaign_access(campaign_id, principal)

        # Get paginated logs
        log_dicts, total = await self.scan_log_repo.get_paginated_logs(
            campaign_id, page, limit, sort_by, order
        )

        # Convert dictionaries to ScanLogEntry objects
        logs = [ScanLogEntry(**log_dict) for log_dict in log_dicts]

        return ScanLogsResponse(
            campaign_id=campaign_id,
            page=page,
            limit=limit,
            total=total,
            logs=logs,
        )

    async def get_ga4_insights(
        self,
        campaign_id: int,
        principal: Principal,
    ) -> GA4InsightsResponse:
        """Get GA4 insights for a campaign."""
        # Verify campaign access
        await self._ensure_campaign_access(campaign_id, principal)

        # Get campaign UTM name
        campaign_utm_name = await self._get_campaign_utm_name(campaign_id)
        if not campaign_utm_name:
            return GA4InsightsResponse(campaign_id=campaign_id, insights=[])

        try:
            # Get user's GA4 property ID
            property_id = await self._get_user_ga4_property_id(principal.user_id)
            if not property_id:
                return GA4InsightsResponse(campaign_id=campaign_id, insights=[])

            # Get insights data
            insights = await self.ga4_service.get_insights(
                principal.user_id, property_id, campaign_utm_name
            )

            return GA4InsightsResponse(campaign_id=campaign_id, insights=insights)

        except GA4ServiceError:
            return GA4InsightsResponse(campaign_id=campaign_id, insights=[])

    async def get_campaign_comparison(
        self,
        campaign_id: int,
        start_date: date,
        end_date: date,
        principal: Principal,
    ) -> CampaignComparisonResponse:
        """Build campaign QR comparison payload for frontend analytics view."""

        if end_date < start_date:
            raise CampaignAnalyticsServiceError("end_date must be greater than or equal to start_date")

        await self._ensure_campaign_access(campaign_id, principal)

        totals = await self.scan_log_repo.get_campaign_qr_comparison_totals(
            campaign_id, start_date, end_date
        )
        previous_totals = await self.scan_log_repo.get_campaign_qr_comparison_totals_for_previous_period(
            campaign_id, start_date, end_date
        )
        sparkline_map = await self.scan_log_repo.get_campaign_qr_sparkline(
            campaign_id, start_date, end_date
        )
        versions_map = await self.scan_log_repo.get_campaign_qr_versions(
            campaign_id, start_date, end_date
        )

        qr_codes: list[CampaignComparisonQRCode] = []
        for row in totals:
            qr_id = int(row["qr_id"])
            total_scans = int(row["total_scans"] or 0)
            previous_total = int(previous_totals.get(qr_id, 0))
            growth: float | None = None
            if previous_total > 0:
                growth = round(((total_scans - previous_total) / previous_total) * 100, 2)

            version_rows = versions_map.get(qr_id, [])
            previous_version_scans: int | None = None
            versions: list[QRVersionComparison] = []
            for version_row in version_rows:
                version_total = int(version_row["total_scans"] or 0)
                scan_diff = None if previous_version_scans is None else version_total - previous_version_scans
                previous_version_scans = version_total
                versions.append(
                    QRVersionComparison(
                        version=f"v{version_row['version_number']}",
                        title=str(version_row["name"] or ""),
                        active_period=QRVersionActivePeriod(
                            start=version_row["active_start"],
                            end=version_row["active_end"],
                        ),
                        destination_url=str(version_row["destination_url"] or ""),
                        total_scans=version_total,
                        scan_diff=scan_diff,
                        status="current" if int(version_row["is_current"] or 0) == 1 else "archived",
                    )
                )

            qr_codes.append(
                CampaignComparisonQRCode(
                    id=str(qr_id),
                    name=str(row["qr_name"] or ""),
                    campaign=str(row["campaign_name"] or ""),
                    destination_url=str(row["destination_url"] or ""),
                    total_scans=total_scans,
                    unique_scans=int(row["unique_scans"] or 0),
                    growth=growth,
                    sparkline=sparkline_map.get(
                        qr_id, [0] * ((end_date - start_date).days + 1)
                    ),
                    versions=versions,
                )
            )

        return CampaignComparisonResponse(campaign_id=campaign_id, qr_codes=qr_codes)

    async def _ensure_campaign_access(self, campaign_id: int, principal: Principal) -> None:
        """Ensure the principal has access to the campaign."""
        campaign = await self.campaign_repo.get_by_id(campaign_id)
        if not campaign:
            raise CampaignAnalyticsServiceError(f"Campaign {campaign_id} not found")

        if campaign.user_id != principal.user_id and principal.role != "admin":
            raise RBACError("Access denied to campaign")

    async def _get_campaign_utm_name(self, campaign_id: int) -> str | None:
        """Get UTM campaign name for the campaign."""
        # This would typically come from the campaign table or related QR codes
        # For now, we'll use the campaign name as the UTM name
        campaign = await self.campaign_repo.get_by_id(campaign_id)
        return campaign.name if campaign else None

    async def _get_user_ga4_property_id(self, user_id: int) -> str | None:
        """Get the user's GA4 property ID from their integrations."""
        # This is a simplified approach - in reality, you'd need to store
        # the selected property ID per user or campaign
        integration = await self.user_integration_repo.get_by_user_and_provider(
            user_id, IntegrationProvider.google_analytics
        )
        
        if not integration:
            return None

        # For now, return a default property ID or extract from integration metadata
        # In a real implementation, you'd store the selected property ID
        return None  # Would return actual property ID
