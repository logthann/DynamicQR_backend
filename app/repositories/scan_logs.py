"""Repository for scan_logs table operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ScanLogRepository:
    """Repository for scan_logs database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_by_campaign(self, campaign_id: int) -> int:
        """Count total scans for a campaign."""
        statement = text(
            """
            SELECT COUNT(sl.id) as total_scans
            FROM scan_logs sl
            INNER JOIN qr_configurations qconf ON sl.qr_configurations_id = qconf.id
            INNER JOIN qr_codes qc ON qconf.qr_id = qc.id
            WHERE qc.campaign_id = :campaign_id
        """
        )
        result = await self.session.execute(statement, {"campaign_id": campaign_id})
        row = result.fetchone()
        return row.total_scans if row else 0

    async def get_hourly_scans(
        self,
        campaign_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """Get hourly scan data grouped by device type."""
        statement = text(
            """
            SELECT 
                DATE_FORMAT(sl.scanned_at, '%Y-%m-%d %H:00:00') as hour,
                COALESCE(sl.device_type, 'unknown') as device_type,
                COUNT(sl.id) as scans
            FROM scan_logs sl
            INNER JOIN qr_configurations qconf ON sl.qr_configurations_id = qconf.id
            INNER JOIN qr_codes qc ON qconf.qr_id = qc.id
            WHERE qc.campaign_id = :campaign_id
                AND sl.scanned_at >= :start_date
                AND sl.scanned_at <= :end_date
            GROUP BY hour, device_type
            ORDER BY hour
        """
        )
        result = await self.session.execute(
            statement,
            {
                "campaign_id": campaign_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        rows = result.fetchall()

        # Group by hour and device type
        hourly_data = {}
        for row in rows:
            hour = row.hour
            device_type = row.device_type.lower()
            scans = row.scans

            if hour not in hourly_data:
                hourly_data[hour] = {"mobile": 0, "desktop": 0, "tablet": 0, "scans": 0}

            hourly_data[hour][device_type] = scans
            hourly_data[hour]["scans"] += scans

        # Convert to list of dicts
        return [
            {
                "hour": hour,
                "mobile": data["mobile"],
                "desktop": data["desktop"],
                "tablet": data["tablet"],
                "scans": data["scans"],
            }
            for hour, data in sorted(hourly_data.items())
        ]

    async def get_paginated_logs(
        self,
        campaign_id: int,
        page: int = 1,
        limit: int = 50,
        sort_by: str = "scanned_at",
        order: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        """Get paginated scan logs for a campaign."""
        # Validate sort column
        valid_sort_columns = {"id", "scanned_at", "ip_address", "device_type", "city"}
        if sort_by not in valid_sort_columns:
            sort_by = "scanned_at"

        # Validate order
        if order.lower() not in {"asc", "desc"}:
            order = "desc"

        # Build count query
        count_statement = text(
            """
            SELECT COUNT(sl.id) as total
            FROM scan_logs sl
            INNER JOIN qr_configurations qconf ON sl.qr_configurations_id = qconf.id
            INNER JOIN qr_codes qc ON qconf.qr_id = qc.id
            INNER JOIN campaigns c ON qc.campaign_id = c.id
            WHERE c.id = :campaign_id
        """
        )

        # Build data query
        data_statement = text(
            f"""
            SELECT 
                sl.id,
                sl.scanned_at,
                sl.ip_address,
                sl.device_type,
                sl.city
            FROM scan_logs sl
            INNER JOIN qr_configurations qconf ON sl.qr_configurations_id = qconf.id
            INNER JOIN qr_codes qc ON qconf.qr_id = qc.id
            INNER JOIN campaigns c ON qc.campaign_id = c.id
            WHERE c.id = :campaign_id
            ORDER BY sl.{sort_by} {order.upper()}
            LIMIT :limit OFFSET :offset
        """
        )

        # Execute count query
        count_result = await self.session.execute(count_statement, {"campaign_id": campaign_id})
        count_row = count_result.fetchone()
        total = count_row.total if count_row else 0

        # Execute data query
        offset = (page - 1) * limit
        data_result = await self.session.execute(
            data_statement,
            {
                "campaign_id": campaign_id,
                "limit": limit,
                "offset": offset,
            },
        )
        logs = [dict(row._mapping) for row in data_result.fetchall()]

        return logs, total
