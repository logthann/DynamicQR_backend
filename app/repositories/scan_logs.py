"""Repository for scan_logs table operations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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

    async def get_campaign_qr_comparison_totals(
        self,
        campaign_id: int,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Return per-QR total scans and unique scans in date range."""

        statement = text(
            """
            SELECT
                q.id AS qr_id,
                COALESCE(qc.name, q.short_code) AS qr_name,
                c.name AS campaign_name,
                COALESCE(qc.destination_url, '') AS destination_url,
                COUNT(sl.id) AS total_scans,
                COUNT(DISTINCT COALESCE(sl.ip_address, CONCAT('scan-', sl.id))) AS unique_scans
            FROM qr_codes q
            INNER JOIN campaigns c ON c.id = q.campaign_id
            LEFT JOIN qr_configurations qc
                ON qc.qr_id = q.id
               AND qc.is_current = 1
            LEFT JOIN scan_logs sl
                ON sl.qr_configurations_id = qc.id
               AND sl.scanned_at >= :start_dt
               AND sl.scanned_at < :end_dt
            WHERE q.campaign_id = :campaign_id
              AND q.deleted_at IS NULL
              AND c.deleted_at IS NULL
            GROUP BY q.id, qr_name, campaign_name, destination_url
            ORDER BY q.id ASC
            """
        )
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        start_dt = datetime.combine(start_date, datetime.min.time())
        result = await self.session.execute(
            statement,
            {
                "campaign_id": campaign_id,
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_campaign_qr_comparison_totals_for_previous_period(
        self,
        campaign_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[int, int]:
        """Return per-QR total scans for previous period of equal length."""

        period_days = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)
        prev_start_dt = datetime.combine(prev_start, datetime.min.time())
        prev_end_dt = datetime.combine(prev_end + timedelta(days=1), datetime.min.time())

        statement = text(
            """
            SELECT
                q.id AS qr_id,
                COUNT(sl.id) AS total_scans
            FROM qr_codes q
            INNER JOIN qr_configurations qc
                ON qc.qr_id = q.id
               AND qc.is_current = 1
            LEFT JOIN scan_logs sl
                ON sl.qr_configurations_id = qc.id
               AND sl.scanned_at >= :start_dt
               AND sl.scanned_at < :end_dt
            WHERE q.campaign_id = :campaign_id
              AND q.deleted_at IS NULL
            GROUP BY q.id
            """
        )
        result = await self.session.execute(
            statement,
            {
                "campaign_id": campaign_id,
                "start_dt": prev_start_dt,
                "end_dt": prev_end_dt,
            },
        )
        return {int(row.qr_id): int(row.total_scans) for row in result.fetchall()}

    async def get_campaign_qr_sparkline(
        self,
        campaign_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[int, list[int]]:
        """Return per-QR daily scan counts between start_date and end_date."""

        statement = text(
            """
            SELECT
                q.id AS qr_id,
                DATE(sl.scanned_at) AS scan_date,
                COUNT(sl.id) AS scans
            FROM qr_codes q
            INNER JOIN qr_configurations qc
                ON qc.qr_id = q.id
               AND qc.is_current = 1
            LEFT JOIN scan_logs sl
                ON sl.qr_configurations_id = qc.id
               AND sl.scanned_at >= :start_dt
               AND sl.scanned_at < :end_dt
            WHERE q.campaign_id = :campaign_id
              AND q.deleted_at IS NULL
            GROUP BY q.id, DATE(sl.scanned_at)
            """
        )
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        start_dt = datetime.combine(start_date, datetime.min.time())
        result = await self.session.execute(
            statement,
            {
                "campaign_id": campaign_id,
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        rows = result.fetchall()

        index_by_date: dict[date, int] = {}
        cursor = start_date
        i = 0
        while cursor <= end_date:
            index_by_date[cursor] = i
            i += 1
            cursor += timedelta(days=1)

        sparkline_map: dict[int, list[int]] = {}
        for row in rows:
            qr_id = int(row.qr_id)
            if qr_id not in sparkline_map:
                sparkline_map[qr_id] = [0] * len(index_by_date)
            if row.scan_date is None:
                continue
            day = row.scan_date if isinstance(row.scan_date, date) else row.scan_date.date()
            if day in index_by_date:
                sparkline_map[qr_id][index_by_date[day]] = int(row.scans)

        return sparkline_map

    async def get_campaign_qr_versions(
        self,
        campaign_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[int, list[dict[str, Any]]]:
        """Return configuration versions and scan counts in range for each QR."""

        statement = text(
            """
            SELECT
                q.id AS qr_id,
                qc.id AS config_id,
                qc.version_number,
                qc.name,
                qc.destination_url,
                qc.created_at AS active_start,
                LEAD(qc.created_at) OVER (PARTITION BY q.id ORDER BY qc.version_number) AS active_end,
                qc.is_current,
                COUNT(sl.id) AS total_scans
            FROM qr_codes q
            INNER JOIN qr_configurations qc ON qc.qr_id = q.id
            LEFT JOIN scan_logs sl
                ON sl.qr_configurations_id = qc.id
               AND sl.scanned_at >= :start_dt
               AND sl.scanned_at < :end_dt
            WHERE q.campaign_id = :campaign_id
              AND q.deleted_at IS NULL
            GROUP BY
                q.id,
                qc.id,
                qc.version_number,
                qc.name,
                qc.destination_url,
                qc.created_at,
                qc.is_current
            ORDER BY q.id ASC, qc.version_number ASC
            """
        )
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        start_dt = datetime.combine(start_date, datetime.min.time())
        result = await self.session.execute(
            statement,
            {
                "campaign_id": campaign_id,
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        version_map: dict[int, list[dict[str, Any]]] = {}
        for row in result.fetchall():
            qr_id = int(row.qr_id)
            version_map.setdefault(qr_id, []).append(dict(row._mapping))
        return version_map
