"""Test GA4 realtime API with real data from database."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.rbac import Principal
from app.models.campaigns import Campaign
from app.models.base import Base
from app.repositories.campaigns import CampaignRepository
from app.repositories.qr_codes import QRCodeRepository
from app.repositories.scan_logs import ScanLogRepository
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.integrations import IntegrationProvider
from app.services.cache_service import CacheService
from app.services.campaign_analytics_service import CampaignAnalyticsService
from app.services.ga4_service import GA4Service


async def main():
    """Test GA4 realtime API with actual database data."""

    settings = get_settings()

    # Create async engine
    engine = create_async_engine(
        str(settings.database_url),
        echo=False,
    )

    # Create async session factory
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        # Step 1: Find campaigns with GA4 property set
        async with async_session() as session:
            print("=" * 80)
            print("STEP 1: Finding campaigns with GA4 property...")
            print("=" * 80)

            result = await session.execute(
                text("""
                    SELECT id, name, user_id, ga_property_id 
                    FROM campaigns 
                    WHERE ga_property_id IS NOT NULL 
                    AND deleted_at IS NULL
                    LIMIT 5
                """)
            )
            campaigns = result.mappings().all()

            if not campaigns:
                print("❌ No campaigns found with GA4 property!")
                return

            print(f"✅ Found {len(campaigns)} campaign(s) with GA4 property:\n")
            for idx, campaign in enumerate(campaigns, 1):
                print(f"  {idx}. Campaign: {campaign['name']}")
                print(f"     - ID: {campaign['id']}")
                print(f"     - User ID: {campaign['user_id']}")
                print(f"     - GA4 Property: {campaign['ga_property_id']}")
                print()

        # Step 2: Test GA4 realtime for each campaign
        for campaign in campaigns:
            campaign_id = campaign["id"]
            user_id = campaign["user_id"]
            ga_property_id = campaign["ga_property_id"]
            campaign_name = campaign["name"]

            print("=" * 80)
            print(f"STEP 2: Testing GA4 Realtime API for Campaign: {campaign_name}")
            print("=" * 80)

            async with async_session() as session:
                try:
                    # Create repositories and services
                    campaign_repo = CampaignRepository(session)
                    scan_log_repo = ScanLogRepository(session)
                    user_integration_repo = UserIntegrationRepository(session)
                    qr_code_repo = QRCodeRepository(session)
                    cache_service = CacheService()
                    ga4_service = GA4Service(user_integration_repo, cache_service)

                    # Create analytics service
                    analytics_service = CampaignAnalyticsService(
                        campaign_repo,
                        scan_log_repo,
                        user_integration_repo,
                        ga4_service,
                        cache_service,
                        qr_code_repo,
                    )

                    # Create principal
                    principal = Principal(user_id=user_id, role="employee")

                    # Call GA4 realtime
                    print(f"\nCalling get_ga4_realtime(campaign_id={campaign_id})...\n")
                    response = await analytics_service.get_ga4_realtime(
                        campaign_id=campaign_id,
                        principal=principal,
                        minutes_back=30,
                    )

                    # Print response
                    print("✅ Response received:")
                    print(json.dumps(
                        {
                            "campaign_id": response.campaign_id,
                            "aggregated": {
                                "total_active_users": response.aggregated.total_active_users,
                                "data_points_count": len(response.aggregated.data),
                                "data": [
                                    {
                                        "time_label": dp.time_label,
                                        "active_users": dp.active_users,
                                    }
                                    for dp in response.aggregated.data
                                ]
                            },
                            "sources_count": len(response.sources),
                            "sources": {
                                name: {
                                    "total_active_users": agg.total_active_users,
                                    "data_points_count": len(agg.data),
                                }
                                for name, agg in response.sources.items()
                            }
                        },
                        indent=2,
                    ))

                    # Check if we got real data
                    if response.aggregated.total_active_users > 0:
                        print(f"\n🎉 SUCCESS: Got {response.aggregated.total_active_users} active user(s)!")
                    else:
                        print("\n⚠️  WARNING: Got 0 active users (might be normal if no one is on page now)")

                except Exception as exc:
                    print(f"❌ Error: {exc}")
                    import traceback
                    traceback.print_exc()

            print()

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

