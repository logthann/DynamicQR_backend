"""Redis caching service for GA4 real-time data."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings


class CacheService:
    """Redis-based caching service for GA4 real-time data."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._redis: redis.Redis | None = None

    async def get_redis(self) -> redis.Redis:
        """Get Redis connection, creating it if needed."""
        if self._redis is None:
            self._redis = redis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def get_cached_ga4_realtime(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
        minutes_back: int = 30,
    ) -> list[dict[str, Any]] | None:
        """Get cached GA4 real-time data."""
        try:
            redis_client = await self.get_redis()
            cache_key = f"ga4_realtime:{user_id}:{property_id}:{campaign_utm_name}:{minutes_back}"
            
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
            
            return None
        except Exception:
            # Cache errors should not break the flow
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
        try:
            redis_client = await self.get_redis()
            cache_key = f"ga4_realtime:{user_id}:{property_id}:{campaign_utm_name}:{minutes_back}"
            
            await redis_client.setex(
                cache_key,
                ttl_seconds,
                json.dumps(data, default=str)
            )
        except Exception:
            # Cache errors should not break the flow
            pass

    async def get_cached_ga4_active_users(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
    ) -> int | None:
        """Get cached GA4 active users count."""
        try:
            redis_client = await self.get_redis()
            cache_key = f"ga4_active_users:{user_id}:{property_id}:{campaign_utm_name}"
            
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return int(cached_data)
            
            return None
        except Exception:
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
        try:
            redis_client = await self.get_redis()
            cache_key = f"ga4_active_users:{user_id}:{property_id}:{campaign_utm_name}"
            
            await redis_client.setex(cache_key, ttl_seconds, str(active_users))
        except Exception:
            pass

    async def get_cached_ga4_avg_session_duration(
        self,
        user_id: int,
        property_id: str,
        campaign_utm_name: str | None,
    ) -> float | None:
        """Get cached GA4 average session duration."""
        try:
            redis_client = await self.get_redis()
            cache_key = f"ga4_avg_session:{user_id}:{property_id}:{campaign_utm_name}"
            
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return float(cached_data)
            
            return None
        except Exception:
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
        try:
            redis_client = await self.get_redis()
            cache_key = f"ga4_avg_session:{user_id}:{property_id}:{campaign_utm_name}"
            
            await redis_client.setex(cache_key, ttl_seconds, str(avg_duration))
        except Exception:
            pass

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
