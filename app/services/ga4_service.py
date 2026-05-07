"""GA4 Data API service for campaign analytics."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.analytics import GA4InsightEntry, GA4RealtimeDataPoint
from app.services.cache_service import CacheService


class GA4ServiceError(RuntimeError):
    """Raised when GA4 API operations fail."""


class GA4Service:
    """Service for interacting with Google Analytics Data API."""

    def __init__(self, user_integration_repo: UserIntegrationRepository, cache_service: CacheService | None = None) -> None:
        self.user_integration_repo = user_integration_repo
        self.settings = get_settings()
        self.cache_service = cache_service or CacheService()

    async def get_active_users(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None = None,
    ) -> int:
        """Get active users from GA4 real-time report."""
        # Check cache first
        cached_value = await self.cache_service.get_cached_ga4_active_users(
            user_id, property_id, campaign_utm_name
        )
        if cached_value is not None:
            return cached_value

        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                Dimension,
                Metric,
                RunRealtimeReportRequest,
            )
        except ImportError as exc:
            raise GA4ServiceError("Google Analytics Data API client not installed") from exc

        # Get user's Google OAuth token
        integration = await self.user_integration_repo.get_by_user_and_provider(
            user_id, "google_analytics"
        )
        if not integration:
            raise GA4ServiceError("Google Analytics integration not found")

        # Initialize client with OAuth credentials
        client = BetaAnalyticsDataClient(credentials=self._create_credentials(integration.access_token))

        # Build request
        request = RunRealtimeReportRequest(
            property=f"properties/{property_id}",
            metrics=[Metric(name="activeUsers")],
        )

        # Add campaign filter if provided
        if campaign_utm_name:
            request.dimension_filters = [
                {
                    "filter": {
                        "field_name": "sessionCampaignName",
                        "string_filter": {"value": campaign_utm_name},
                    }
                }
            ]

        try:
            response = client.run_realtime_report(request)
            active_users = int(response.rows[0].metric_values[0].value) if response.rows else 0
            
            # Cache the result
            await self.cache_service.cache_ga4_active_users(
                user_id, property_id, campaign_utm_name, active_users
            )
            
            return active_users
        except Exception as exc:
            raise GA4ServiceError(f"Failed to fetch active users: {exc}") from exc

    async def get_realtime_data(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None = None,
        minutes_back: int = 30,
    ) -> list[GA4RealtimeDataPoint]:
        """Get real-time data for the past N minutes."""
        # Check cache first
        cached_data = await self.cache_service.get_cached_ga4_realtime(
            user_id, property_id, campaign_utm_name, minutes_back
        )
        if cached_data:
            return [GA4RealtimeDataPoint(**point) for point in cached_data]

        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                Dimension,
                Metric,
                RunRealtimeReportRequest,
            )
        except ImportError as exc:
            raise GA4ServiceError("Google Analytics Data API client not installed") from exc

        # Get user's Google OAuth token
        integration = await self.user_integration_repo.get_by_user_and_provider(
            user_id, "google_analytics"
        )
        if not integration:
            raise GA4ServiceError("Google Analytics integration not found")

        client = BetaAnalyticsDataClient(credentials=self._create_credentials(integration.access_token))

        # Build request with minutesAgo dimension
        request = RunRealtimeReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="minutesAgo")],
            metrics=[Metric(name="activeUsers")],
        )

        # Add campaign filter if provided
        if campaign_utm_name:
            request.dimension_filters = [
                {
                    "filter": {
                        "field_name": "sessionCampaignName",
                        "string_filter": {"value": campaign_utm_name},
                    }
                }
            ]

        try:
            response = client.run_realtime_report(request)
            data_points = []
            
            # Process response rows
            for row in response.rows:
                minutes_ago = int(row.dimension_values[0].value)
                active_users = int(row.metric_values[0].value)
                
                # Create time label
                if minutes_ago == 0:
                    time_label = "Now"
                elif minutes_ago == 1:
                    time_label = "1m ago"
                else:
                    time_label = f"{minutes_ago}m ago"
                
                data_points.append(
                    GA4RealtimeDataPoint(
                        time_label=time_label,
                        active_users=active_users,
                    )
                )
            
            # Sort by time (oldest first)
            data_points.sort(key=lambda x: int(x.time_label.replace("m ago", "").replace("Now", "0")))
            
            result = data_points[-minutes_back:]  # Return last N minutes
            
            # Cache the result
            await self.cache_service.cache_ga4_realtime(
                user_id, property_id, campaign_utm_name, minutes_back,
                [point.model_dump() for point in result]
            )
            
            return result
            
        except Exception as exc:
            raise GA4ServiceError(f"Failed to fetch real-time data: {exc}") from exc

    async def get_insights(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None = None,
    ) -> list[GA4InsightEntry]:
        """Get detailed behavioral insights from GA4."""
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                Dimension,
                Metric,
                RunReportRequest,
            )
        except ImportError as exc:
            raise GA4ServiceError("Google Analytics Data API client not installed") from exc

        # Get user's Google OAuth token
        integration = await self.user_integration_repo.get_by_user_and_provider(
            user_id, "google_analytics"
        )
        if not integration:
            raise GA4ServiceError("Google Analytics integration not found")

        client = BetaAnalyticsDataClient(credentials=self._create_credentials(integration.access_token))

        # Build request for behavioral insights
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="pagePath"),
                Dimension(name="sessionSource"),
                Dimension(name="deviceCategory"),
            ],
            metrics=[Metric(name="engagementTime")],
            date_ranges=[{"start_date": "7daysAgo", "end_date": "today"}],
        )

        # Add campaign filter if provided
        if campaign_utm_name:
            request.dimension_filter_expressions = [
                {
                    "filter": {
                        "field_name": "sessionCampaignName",
                        "string_filter": {"value": campaign_utm_name},
                    }
                }
            ]

        try:
            response = client.run_report(request)
            insights = []
            
            for row in response.rows:
                insights.append(
                    GA4InsightEntry(
                        page_path=row.dimension_values[0].value,
                        session_source=row.dimension_values[1].value,
                        device_category=row.dimension_values[2].value,
                        engagement_time=float(row.metric_values[0].value),
                    )
                )
            
            return insights
            
        except Exception as exc:
            raise GA4ServiceError(f"Failed to fetch insights: {exc}") from exc

    async def get_average_session_duration(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None = None,
    ) -> float:
        """Get average session duration from GA4."""
        # Check cache first
        cached_value = await self.cache_service.get_cached_ga4_avg_session_duration(
            user_id, property_id, campaign_utm_name
        )
        if cached_value is not None:
            return cached_value

        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                Metric,
                RunReportRequest,
            )
        except ImportError as exc:
            raise GA4ServiceError("Google Analytics Data API client not installed") from exc

        # Get user's Google OAuth token
        integration = await self.user_integration_repo.get_by_user_and_provider(
            user_id, "google_analytics"
        )
        if not integration:
            raise GA4ServiceError("Google Analytics integration not found")

        client = BetaAnalyticsDataClient(credentials=self._create_credentials(integration.access_token))

        # Build request for average session duration
        request = RunReportRequest(
            property=f"properties/{property_id}",
            metrics=[Metric(name="averageSessionDuration")],
            date_ranges=[{"start_date": "7daysAgo", "end_date": "today"}],
        )

        # Add campaign filter if provided
        if campaign_utm_name:
            request.dimension_filter_expressions = [
                {
                    "filter": {
                        "field_name": "sessionCampaignName",
                        "string_filter": {"value": campaign_utm_name},
                    }
                }
            ]

        try:
            response = client.run_report(request)
            avg_duration = float(response.rows[0].metric_values[0].value) if response.rows else 0.0
            
            # Cache the result
            await self.cache_service.cache_ga4_avg_session_duration(
                user_id, property_id, campaign_utm_name, avg_duration
            )
            
            return avg_duration
            
        except Exception as exc:
            raise GA4ServiceError(f"Failed to fetch average session duration: {exc}") from exc

    def _create_credentials(self, access_token: str) -> Any:
        """Create Google credentials from OAuth access token."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            # Create credentials from access token
            credentials = Credentials(
                token=access_token,
                scopes=["https://www.googleapis.com/auth/analytics.readonly"],
            )
            
            # Refresh if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            return credentials
            
        except ImportError as exc:
            raise GA4ServiceError("Google Auth library not installed") from exc
        except Exception as exc:
            raise GA4ServiceError(f"Failed to create credentials: {exc}") from exc
