"""Campaign analytics service combining scan logs and GA4 data."""

from __future__ import annotations

from datetime import date, datetime

from app.core.rbac import Principal, RBACError
from app.repositories.campaigns import CampaignRepository
from app.repositories.scan_logs import ScanLogRepository
from app.repositories.user_integrations import UserIntegrationRepository
from app.repositories.qr_codes import QRCodeRepository
from app.schemas.analytics import (
    CampaignComparisonQRCode,
    CampaignComparisonResponse,
    CampaignKPISummaryResponse,
    GA4InsightsResponse,
    GA4RealtimeResponse,
    GA4RealtimeAggregated,
    GA4RealtimeDataPoint,
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
        qr_code_repo: QRCodeRepository | None = None,
    ) -> None:
        self.campaign_repo = campaign_repo
        self.scan_log_repo = scan_log_repo
        self.user_integration_repo = user_integration_repo
        self.ga4_service = ga4_service
        self.cache_service = cache_service or CacheService()
        self.qr_code_repo = qr_code_repo

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
                property_id = await self._get_user_ga4_property_id(principal.user_id, campaign_id)
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
        """Get GA4 real-time data for a campaign, aggregating across its QR codes."""
        # Verify campaign access
        await self._ensure_campaign_access(campaign_id, principal)

        if not self.qr_code_repo:
            raise CampaignAnalyticsServiceError("QRCodeRepository is required for get_ga4_realtime")

        empty_response = GA4RealtimeResponse(
            campaign_id=campaign_id,
            aggregated=GA4RealtimeAggregated(total_active_users=0, data=[]),
            sources={},
        )

        # Helper function for sorting time labels
        def sort_time_label(time_label: str) -> int:
            """Parse time_label to minutes for sorting. 'Now' = 0, '5m ago' = 5, etc."""
            if time_label == "Now":
                return 0
            if "m ago" in time_label:
                try:
                    minutes_str = time_label.replace("m ago", "").strip()
                    return int(minutes_str)
                except (ValueError, AttributeError):
                    return 999
            return 999

        # Fetch all QR codes for the campaign
        qr_codes = await self.qr_code_repo.list_by_user(principal.user_id, campaign_id=campaign_id)
        if not qr_codes:
            return empty_response

        # Extract unique tracking combinations (ga_property_id, utm_campaign)
        # Fallback to campaign defaults if QR code doesn't override them
        campaign_context = await self.campaign_repo.get_by_id(campaign_id)
        default_property_id = None
        default_utm_campaign = None
        if campaign_context:
            default_property_id = campaign_context.ga_property_id
            default_utm_campaign = campaign_context.name

        if not default_property_id:
             integration = await self.user_integration_repo.get_by_user_and_provider(
                 principal.user_id, IntegrationProvider.google_analytics
             )
             if not integration:
                 return empty_response

        unique_combinations = {}
        for qr in qr_codes:
            # Skip if tracking is manually disabled or oauth is required but missing property
            ga_type = qr.ga_type.value if hasattr(qr.ga_type, 'value') else qr.ga_type
            if ga_type == 'MANUAL':
                continue

            prop_id = qr.ga_property_id or default_property_id
            utm_camp = qr.utm_campaign or default_utm_campaign

            if prop_id and utm_camp:
                 combo_key = f"{prop_id}|{utm_camp}"
                 if combo_key not in unique_combinations:
                     unique_combinations[combo_key] = {
                         'property_id': prop_id,
                         'utm_campaign': utm_camp,
                         'qr_codes': []
                     }
                 unique_combinations[combo_key]['qr_codes'].append(qr.name or qr.short_code)

        if not unique_combinations:
            return empty_response

        # Fetch data for each unique combination and aggregate
        aggregated_data_map: dict[str, int] = {}
        total_active_users_all = 0
        sources_data: dict[str, GA4RealtimeAggregated] = {}

        for combo_key, info in unique_combinations.items():
            try:
                data_points = await self.ga4_service.get_realtime_data(
                    principal.user_id, info['property_id'], info['utm_campaign'], minutes_back
                )
                
                source_total_users = 0
                source_data_map = {}

                for point in data_points:
                    time_label = point.time_label
                    users = point.active_users
                    
                    # Accumulate for overall aggregation
                    aggregated_data_map[time_label] = aggregated_data_map.get(time_label, 0) + users
                    total_active_users_all += users
                    
                    # Accumulate for source breakdown
                    source_data_map[time_label] = users
                    source_total_users += users

                # Format source data sorted by time
                source_data_list = [
                    GA4RealtimeDataPoint(time_label=tl, active_users=au)
                    for tl, au in sorted(source_data_map.items(), key=lambda item: sort_time_label(item[0]))
                ]
                
                # Use a combined name for the source if multiple QRs share the combination
                source_name = ", ".join(info['qr_codes'])
                sources_data[source_name] = GA4RealtimeAggregated(
                    total_active_users=source_total_users,
                    data=source_data_list
                )

            except GA4ServiceError:
                # Log or handle error for a specific combination, but continue aggregating others
                pass

        # Format aggregated data sorted by time

        aggregated_data_list = [
            GA4RealtimeDataPoint(time_label=tl, active_users=au)
            for tl, au in sorted(aggregated_data_map.items(), key=lambda item: sort_time_label(item[0]))
        ]

        return GA4RealtimeResponse(
            campaign_id=campaign_id,
            aggregated=GA4RealtimeAggregated(
                total_active_users=total_active_users_all,
                data=aggregated_data_list
            ),
            sources=sources_data
        )

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
            property_id = await self._get_user_ga4_property_id(principal.user_id, campaign_id)
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

    async def _get_user_ga4_property_id(self, user_id: int, campaign_id: int) -> str | None:
        """Resolve GA4 property id with campaign-first precedence."""
        campaign = await self.campaign_repo.get_by_id(campaign_id)
        if campaign and campaign.ga_property_id:
            return str(campaign.ga_property_id)

        integration = await self.user_integration_repo.get_by_user_and_provider(
            user_id, IntegrationProvider.google_analytics
        )
        if not integration:
            return None

        # Current integration schema stores tokens/scopes only; no property-id mapping.
        return None
