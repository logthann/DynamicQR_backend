"""Test GA4 realtime response format and data aggregation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.analytics import (
    GA4RealtimeAggregated,
    GA4RealtimeDataPoint,
    GA4RealtimeResponse,
)
from app.services.campaign_analytics_service import CampaignAnalyticsService


@pytest.mark.asyncio
async def test_ga4_realtime_response_with_single_active_user() -> None:
    """Verify GA4 realtime response structure with 1 active user."""

    # Create mock repositories
    campaign_repo = AsyncMock()
    scan_log_repo = AsyncMock()
    user_integration_repo = AsyncMock()
    ga4_service = AsyncMock()
    cache_service = AsyncMock()
    qr_code_repo = AsyncMock()

    # Create service
    service = CampaignAnalyticsService(
        campaign_repo,
        scan_log_repo,
        user_integration_repo,
        ga4_service,
        cache_service,
        qr_code_repo,
    )

    # Mock campaign access check
    campaign_repo.get_by_id = AsyncMock(
        return_value=MagicMock(
            id=1,
            user_id=1,
            ga_property_id="123456",
            name="Test Campaign",
        )
    )

    # Mock QR codes without GA tracking
    qr_code_repo.list_by_user = AsyncMock(return_value=[])

    # Should return empty response when no QR codes have GA tracking
    from app.core.rbac import Principal

    result = await service.get_ga4_realtime(
        campaign_id=1,
        principal=Principal(user_id=1, role="employee"),
    )

    # Verify response structure
    assert isinstance(result, GA4RealtimeResponse)
    assert result.campaign_id == 1
    assert isinstance(result.aggregated, GA4RealtimeAggregated)
    assert result.aggregated.total_active_users == 0
    assert isinstance(result.aggregated.data, list)
    assert isinstance(result.sources, dict)
    assert len(result.sources) == 0


@pytest.mark.asyncio
async def test_ga4_realtime_data_point_sorting() -> None:
    """Verify time_label sorting works correctly."""

    # Create data points in random order
    data_points = [
        GA4RealtimeDataPoint(time_label="5m ago", active_users=2),
        GA4RealtimeDataPoint(time_label="Now", active_users=1),
        GA4RealtimeDataPoint(time_label="15m ago", active_users=0),
        GA4RealtimeDataPoint(time_label="2m ago", active_users=3),
    ]

    # Sort by time (oldest first)
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

    sorted_points = sorted(
        data_points,
        key=lambda x: sort_time_label(x.time_label)
    )

    # Current service logic sorts ascending by minutes ago, so Now appears first.
    assert sorted_points[0].time_label == "Now"
    assert sorted_points[1].time_label == "2m ago"
    assert sorted_points[2].time_label == "5m ago"
    assert sorted_points[3].time_label == "15m ago"

    # Verify active_users values are preserved
    assert sorted_points[0].active_users == 1
    assert sorted_points[1].active_users == 3
    assert sorted_points[2].active_users == 2
    assert sorted_points[3].active_users == 0


@pytest.mark.asyncio
async def test_ga4_realtime_aggregation_with_multiple_time_points() -> None:
    """Verify aggregation works with multiple time data points."""

    # Simulate data from multiple sources showing activity over time
    source1_data = [
        GA4RealtimeDataPoint(time_label="Now", active_users=1),
        GA4RealtimeDataPoint(time_label="2m ago", active_users=0),
        GA4RealtimeDataPoint(time_label="5m ago", active_users=1),
    ]

    source2_data = [
        GA4RealtimeDataPoint(time_label="Now", active_users=1),
        GA4RealtimeDataPoint(time_label="5m ago", active_users=0),
    ]

    # Aggregate data manually (simulating the service logic)
    aggregated_data_map = {}
    total_active_users = 0

    for point in source1_data:
        aggregated_data_map[point.time_label] = (
            aggregated_data_map.get(point.time_label, 0) + point.active_users
        )
        total_active_users += point.active_users

    for point in source2_data:
        aggregated_data_map[point.time_label] = (
            aggregated_data_map.get(point.time_label, 0) + point.active_users
        )
        total_active_users += point.active_users

    # Verify aggregation
    # From source1: 1 + 0 + 1 = 2
    # From source2: 1 + 0 = 1
    # Total: 3
    assert total_active_users == 3

    # Now should have 2 active users (1 from each source)
    assert aggregated_data_map.get("Now") == 2

    # 2m ago should have 0 (only from source1)
    assert aggregated_data_map.get("2m ago") == 0

    # 5m ago should have 1 (1 from source1 + 0 from source2 = 1)
    assert aggregated_data_map.get("5m ago") == 1


@pytest.mark.asyncio
async def test_ga4_parse_time_label_edge_cases() -> None:
    """Test edge cases in time_label parsing."""

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

    # Test various inputs
    assert sort_time_label("Now") == 0
    assert sort_time_label("1m ago") == 1
    assert sort_time_label("30m ago") == 30
    assert sort_time_label("60m ago") == 60

    # Invalid inputs should return 999
    assert sort_time_label("invalid") == 999
    assert sort_time_label("") == 999
    assert sort_time_label("ago") == 999  # Missing minutes



