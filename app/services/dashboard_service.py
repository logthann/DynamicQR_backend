"""Dashboard overview aggregation service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone as datetime_timezone, tzinfo as datetime_tzinfo
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Principal, RBACError
from app.schemas.dashboard import (
    DashboardCampaignRow,
    DashboardCampaignTable,
    DashboardChartsSection,
    DashboardKPI,
    DashboardKPISection,
    DashboardMetadata,
    DashboardOverviewResponse,
    DashboardRange,
    DashboardScansPerCampaignItem,
    DashboardTrafficDistributionItem,
    TrendDirection,
)


@dataclass(frozen=True, slots=True)
class DashboardOverviewResult:
    """Rendered dashboard payload and response metadata."""

    payload: DashboardOverviewResponse
    etag: str


@dataclass(frozen=True, slots=True)
class DashboardScanStats:
    """Aggregated scan totals for one period."""

    total_scans: int
    unique_users: int


@dataclass(frozen=True, slots=True)
class DashboardPeriod:
    """Resolved date and UTC boundaries for one dashboard period."""

    start_date: date
    end_date: date
    start_utc: datetime
    end_utc: datetime


class DashboardService:
    """Build dashboard overview payloads from transactional tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_overview(
        self,
        principal: Principal,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        compare_previous: bool = True,
        timezone: str = "Asia/Ho_Chi_Minh",
        top_campaigns_limit: int = 5,
        include_inactive: bool = True,
    ) -> DashboardOverviewResult:
        """Return aggregated dashboard metrics for one principal scope."""

        resolved_timezone = self._resolve_timezone(timezone)
        resolved_end_date = end_date or datetime.now(resolved_timezone).date()
        resolved_start_date = start_date or (resolved_end_date - timedelta(days=30))
        if resolved_start_date > resolved_end_date:
            raise ValueError("start_date must be on or before end_date")

        current_period = self._build_period(resolved_start_date, resolved_end_date, resolved_timezone)
        previous_period = (
            self._previous_period(current_period, resolved_timezone)
            if compare_previous
            else None
        )
        earlier_period = (
            self._previous_period(previous_period, resolved_timezone)
            if previous_period is not None
            else None
        )

        current_start_date = current_period.start_date
        current_end_date = current_period.end_date
        assert current_start_date is not None
        assert current_end_date is not None

        current_scans = await self._fetch_scan_stats(
            principal,
            start_utc=current_period.start_utc,
            end_utc=current_period.end_utc,
            include_inactive=include_inactive,
        )
        previous_scans = (
            await self._fetch_scan_stats(
                principal,
                start_utc=previous_period.start_utc,
                end_utc=previous_period.end_utc,
                include_inactive=include_inactive,
            )
            if previous_period is not None
            else None
        )
        earlier_scans = (
            await self._fetch_scan_stats(
                principal,
                start_utc=earlier_period.start_utc,
                end_utc=earlier_period.end_utc,
                include_inactive=include_inactive,
            )
            if earlier_period is not None
            else None
        )

        current_active_campaigns = await self._fetch_active_campaign_count(
            principal,
            start_date=current_start_date,
            end_date=current_end_date,
        )
        if previous_period is not None:
            previous_start_date = previous_period.start_date
            previous_end_date = previous_period.end_date
            assert previous_start_date is not None
            assert previous_end_date is not None
            previous_active_campaigns = await self._fetch_active_campaign_count(
                principal,
                start_date=previous_start_date,
                end_date=previous_end_date,
            )
        else:
            previous_active_campaigns = None

        campaign_rows = await self._fetch_campaign_rows(
            principal,
            start_utc=current_period.start_utc,
            end_utc=current_period.end_utc,
            include_inactive=include_inactive,
        )
        campaign_scan_total = sum(row.scans for row in campaign_rows)
        chart_rows = campaign_rows[: max(1, min(top_campaigns_limit, len(campaign_rows)))]

        total_scans_kpi = self._build_kpi(current_scans.total_scans, previous_scans.total_scans if previous_scans else None)
        active_campaigns_kpi = self._build_kpi(
            current_active_campaigns,
            previous_active_campaigns,
        )
        total_unique_users_kpi = self._build_kpi(
            current_scans.unique_users,
            previous_scans.unique_users if previous_scans else None,
        )

        if compare_previous and previous_scans is not None:
            current_growth = self._percentage_change(current_scans.total_scans, previous_scans.total_scans)
            previous_growth = (
                self._percentage_change(previous_scans.total_scans, earlier_scans.total_scans)
                if earlier_scans is not None
                else None
            )
            system_growth = DashboardKPI(
                value=current_growth,
                previous_value=previous_growth,
                change_abs=(current_growth - previous_growth) if previous_growth is not None else None,
                change_pct=self._percentage_change(current_growth, previous_growth) if previous_growth is not None else None,
                trend=self._trend(current_growth, previous_growth),
            )
        else:
            system_growth = DashboardKPI(value=0.0, trend=TrendDirection.flat)

        payload = DashboardOverviewResponse(
            range=DashboardRange(
                start_date=cast(date, current_start_date),
                end_date=cast(date, current_end_date),
                timezone=timezone,
                compare_previous=compare_previous,
            ),
            metadata=DashboardMetadata(
                top_campaigns_limit=max(1, min(top_campaigns_limit, 50)),
                include_inactive=include_inactive,
            ),
            kpis=DashboardKPISection(
                total_scans=total_scans_kpi,
                active_campaigns=active_campaigns_kpi,
                total_unique_users=total_unique_users_kpi,
                system_growth=system_growth,
            ),
            charts=DashboardChartsSection(
                scans_per_campaign=[
                    DashboardScansPerCampaignItem(
                        campaign_id=row.campaign_id,
                        campaign_name=row.campaign_name,
                        scans=row.scans,
                        traffic_share_pct=self._share_percentage(row.scans, campaign_scan_total),
                    )
                    for row in chart_rows
                ],
                traffic_distribution=[
                    DashboardTrafficDistributionItem(
                        campaign_id=row.campaign_id,
                        campaign_name=row.campaign_name,
                        traffic_share_pct=self._share_percentage(row.scans, campaign_scan_total),
                    )
                    for row in chart_rows
                ],
            ),
            campaigns=DashboardCampaignTable(
                total=len(campaign_rows),
                items=campaign_rows,
            ),
        )

        return DashboardOverviewResult(payload=payload, etag=self._build_etag(payload))

    async def _fetch_scan_stats(
        self,
        principal: Principal,
        *,
        start_utc: datetime,
        end_utc: datetime,
        include_inactive: bool,
    ) -> DashboardScanStats:
        """Aggregate scan totals and distinct visitors for a date window."""

        scope_clause, params = self._scope_filters(principal)
        statement = text(
            f"""
            SELECT
                COUNT(sl.id) AS total_scans,
                COUNT(DISTINCT COALESCE(sl.ip_address, CONCAT('unknown-', sl.id))) AS unique_users
            FROM scan_logs sl
            JOIN qr_codes q
              ON q.id = sl.qr_id
             AND q.deleted_at IS NULL
            JOIN users owner
              ON owner.id = q.user_id
             AND owner.deleted_at IS NULL
            LEFT JOIN campaigns c
              ON c.id = q.campaign_id
             AND c.deleted_at IS NULL
            WHERE sl.scanned_at >= :start_utc
              AND sl.scanned_at < :end_utc
              AND {scope_clause}
              AND (:include_inactive = 1 OR q.campaign_id IS NULL OR c.status = 'active')
            """
        )

        result = await self.session.execute(
            statement,
            {
                **params,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "include_inactive": 1 if include_inactive else 0,
            },
        )
        row = result.mappings().first() or {}
        return DashboardScanStats(
            total_scans=int(row.get("total_scans") or 0),
            unique_users=int(row.get("unique_users") or 0),
        )

    async def _fetch_active_campaign_count(
        self,
        principal: Principal,
        *,
        start_date: date,
        end_date: date,
    ) -> int:
        """Count active campaigns that overlap the requested period."""

        scope_clause, params = self._scope_filters(principal)
        statement = text(
            f"""
            SELECT COUNT(*) AS total
            FROM campaigns c
            JOIN users owner
              ON owner.id = c.user_id
             AND owner.deleted_at IS NULL
            WHERE c.deleted_at IS NULL
              AND c.status = 'active'
              AND (c.start_date IS NULL OR c.start_date <= :end_date)
              AND (c.end_date IS NULL OR c.end_date >= :start_date)
              AND {scope_clause}
            """
        )

        result = await self.session.execute(
            statement,
            {
                **params,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.mappings().first() or {}
        return int(row.get("total") or 0)

    async def _fetch_campaign_rows(
        self,
        principal: Principal,
        *,
        start_utc: datetime,
        end_utc: datetime,
        include_inactive: bool,
    ) -> list[DashboardCampaignRow]:
        """Return per-campaign rows ordered by scan volume."""

        scope_clause, params = self._scope_filters(principal)
        statement = text(
            f"""
            SELECT
                c.id AS campaign_id,
                c.name AS campaign_name,
                c.status AS status,
                COUNT(sl.id) AS scans,
                COUNT(DISTINCT COALESCE(sl.ip_address, CONCAT('unknown-', sl.id))) AS unique_users
            FROM campaigns c
            JOIN users owner
              ON owner.id = c.user_id
             AND owner.deleted_at IS NULL
            LEFT JOIN qr_codes q
              ON q.campaign_id = c.id
             AND q.deleted_at IS NULL
            LEFT JOIN scan_logs sl
              ON sl.qr_id = q.id
             AND sl.scanned_at >= :start_utc
             AND sl.scanned_at < :end_utc
            WHERE c.deleted_at IS NULL
              AND {scope_clause}
              AND (:include_inactive = 1 OR c.status = 'active')
            GROUP BY c.id, c.name, c.status
            ORDER BY scans DESC, c.name ASC
            """
        )

        result = await self.session.execute(
            statement,
            {
                **params,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "include_inactive": 1 if include_inactive else 0,
            },
        )

        rows = []
        for row in result.mappings().all():
            rows.append(
                DashboardCampaignRow(
                    campaign_id=str(row["campaign_id"]),
                    campaign_name=str(row["campaign_name"]),
                    status=str(row["status"]),
                    scans=int(row.get("scans") or 0),
                    unique_users=int(row.get("unique_users") or 0),
                )
            )
        return rows

    def _scope_filters(self, principal: Principal) -> tuple[str, dict[str, object]]:
        """Return SQL filters for the caller's ownership scope."""

        if principal.role == "admin":
            return "1 = 1", {}


        return "owner.id = :user_id", {"user_id": principal.user_id}

    @staticmethod
    def _build_period(start_date: date, end_date: date, timezone: datetime_tzinfo) -> DashboardPeriod:
        """Convert inclusive date boundaries into a UTC query window."""

        start_utc = datetime.combine(start_date, time.min, tzinfo=timezone).astimezone(UTC)
        end_utc = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
        return DashboardPeriod(
            start_date=start_date,
            end_date=end_date,
            start_utc=start_utc,
            end_utc=end_utc,
        )

    @classmethod
    def _previous_period(
        cls,
        period: DashboardPeriod | None,
        timezone: datetime_tzinfo,
    ) -> DashboardPeriod | None:
        """Build the immediately preceding period with the same length."""

        if period is None:
            return None

        length_days = (period.end_date - period.start_date).days + 1
        previous_end = period.start_date - timedelta(days=1)
        previous_start = previous_end - timedelta(days=length_days - 1)
        return cls._build_period(previous_start, previous_end, timezone)

    @staticmethod
    def _resolve_timezone(timezone: str) -> datetime_tzinfo:
        """Resolve a user-supplied IANA timezone name."""

        try:
            return ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            if timezone in {"Asia/Ho_Chi_Minh", "Asia/Saigon", "ICT"}:
                return datetime_timezone(timedelta(hours=7), name=timezone)
            raise ValueError(f"Unknown timezone: {timezone}") from exc

    @staticmethod
    def _build_kpi(current: int | float, previous: int | float | None) -> DashboardKPI:
        """Create a KPI card with comparison fields when available."""

        if previous is None:
            return DashboardKPI(value=current, trend=TrendDirection.flat)

        change_abs = current - previous
        change_pct = DashboardService._percentage_change(current, previous)
        return DashboardKPI(
            value=current,
            previous_value=previous,
            change_abs=change_abs,
            change_pct=change_pct,
            trend=DashboardService._trend(current, previous),
        )

    @staticmethod
    def _percentage_change(current: int | float, previous: int | float) -> float:
        """Compute the percentage delta between two values."""

        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100.0, 2)

    @staticmethod
    def _share_percentage(part: int, whole: int) -> float:
        """Compute a share percentage suitable for dashboard charts."""

        if whole <= 0:
            return 0.0
        return round((part / whole) * 100.0, 2)

    @staticmethod
    def _trend(current: int | float, previous: int | float | None) -> TrendDirection:
        """Resolve the trend direction from a comparison pair."""

        if previous is None:
            return TrendDirection.flat
        if current > previous:
            return TrendDirection.up
        if current < previous:
            return TrendDirection.down
        return TrendDirection.flat

    @staticmethod
    def _build_etag(payload: DashboardOverviewResponse) -> str:
        """Generate a strong ETag from the serialized payload."""

        serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f'"{digest}"'

