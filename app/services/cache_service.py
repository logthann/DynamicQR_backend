"""In-memory caching service for GA4 real-time data."""

from __future__ import annotations

import json
import time
from typing import Any


class CacheService:
    """In-memory caching service for GA4 real-time data."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _expiry(self, ttl_seconds: int | None) -> float | None:
        if ttl_seconds is None:
            return None
        return time.monotonic() + max(ttl_seconds, 0)

    def _get_cached_value(self, cache_key: str) -> str | None:
        cached_entry = self._store.get(cache_key)
        if cached_entry is None:
            return None

        raw_value, expires_at = cached_entry
        if expires_at is not None and time.monotonic() >= expires_at:
            self._store.pop(cache_key, None)
            return None

        return raw_value

    def _set_cached_value(self, cache_key: str, value: str, ttl_seconds: int | None) -> None:
        self._store[cache_key] = (value, self._expiry(ttl_seconds))

    async def get_cached_ga4_realtime(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
        minutes_back: int = 30,
    ) -> list[dict[str, Any]] | None:
        """Get cached GA4 real-time data."""
        cache_key = f"ga4_realtime:{user_id}:{property_id}:{campaign_utm_name}:{minutes_back}"
        cached_data = self._get_cached_value(cache_key)
        if cached_data:
            return json.loads(cached_data)

        return None

    async def cache_ga4_realtime(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
        minutes_back: int,
        data: list[dict[str, Any]],
        ttl_seconds: int = 10,
    ) -> None:
        """Cache GA4 real-time data with TTL."""
        cache_key = f"ga4_realtime:{user_id}:{property_id}:{campaign_utm_name}:{minutes_back}"
        self._set_cached_value(cache_key, json.dumps(data, default=str), ttl_seconds)

    async def get_cached_ga4_active_users(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
    ) -> int | None:
        """Get cached GA4 active users count."""
        cache_key = f"ga4_active_users:{user_id}:{property_id}:{campaign_utm_name}"
        cached_data = self._get_cached_value(cache_key)
        if cached_data:
            return int(cached_data)

        return None

    async def cache_ga4_active_users(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
        active_users: int,
        ttl_seconds: int = 10,
    ) -> None:
        """Cache GA4 active users count with TTL."""
        cache_key = f"ga4_active_users:{user_id}:{property_id}:{campaign_utm_name}"
        self._set_cached_value(cache_key, str(active_users), ttl_seconds)

    async def get_cached_ga4_avg_session_duration(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
    ) -> float | None:
        """Get cached GA4 average session duration."""
        cache_key = f"ga4_avg_session:{user_id}:{property_id}:{campaign_utm_name}"
        cached_data = self._get_cached_value(cache_key)
        if cached_data:
            return float(cached_data)

        return None

    async def cache_ga4_avg_session_duration(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
        avg_duration: float,
        ttl_seconds: int = 60,
    ) -> None:
        """Cache GA4 average session duration with TTL."""
        cache_key = f"ga4_avg_session:{user_id}:{property_id}:{campaign_utm_name}"
        self._set_cached_value(cache_key, str(avg_duration), ttl_seconds)

    async def close(self) -> None:
        """Clear in-memory cache entries."""

        self._store.clear()
