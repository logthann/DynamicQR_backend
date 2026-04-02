"""Redis cache helpers for QR short-code lookups."""

from __future__ import annotations

import json
import logging
from typing import Any

from redis import asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SHORT_CODE_CACHE_PREFIX = "qr:short_code:"

_redis_client: Redis | None = None
_redis_error_logged = False


def _cache_enabled() -> bool:
    return bool(get_settings().redis_enabled)


def _log_redis_unavailable_once(operation: str, short_code: str) -> None:
    global _redis_error_logged
    if _redis_error_logged:
        return
    logger.warning(
        "Redis %s failed for short code '%s'. Cache disabled for this process until restart.",
        operation,
        short_code,
    )
    _redis_error_logged = True


def short_code_cache_key(short_code: str) -> str:
    """Build a stable Redis key for a short code."""

    return f"{SHORT_CODE_CACHE_PREFIX}{short_code}"


def get_redis_client() -> Redis:
    """Return a singleton Redis async client."""

    global _redis_client

    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            encoding="utf-8",
        )

    return _redis_client


async def get_cached_short_code(short_code: str) -> dict[str, Any] | None:
    """Fetch cached QR payload for a short code."""

    if not _cache_enabled():
        return None

    cache_key = short_code_cache_key(short_code)

    try:
        payload = await get_redis_client().get(cache_key)
    except RedisError:
        _log_redis_unavailable_once("get", short_code)
        return None

    if not payload:
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload found in cache key '%s'", cache_key)
        return None

    return data if isinstance(data, dict) else None


async def set_cached_short_code(
    short_code: str,
    payload: dict[str, Any],
    ttl_seconds: int | None = None,
) -> bool:
    """Cache QR payload for a short code with a TTL."""

    if not _cache_enabled():
        return False

    cache_key = short_code_cache_key(short_code)
    settings = get_settings()
    resolved_ttl = ttl_seconds or settings.redis_short_code_ttl_seconds

    try:
        raw_payload = json.dumps(payload)
        await get_redis_client().set(cache_key, raw_payload, ex=resolved_ttl)
        return True
    except (RedisError, TypeError, ValueError):
        _log_redis_unavailable_once("set", short_code)
        return False


async def invalidate_short_code_cache(short_code: str) -> None:
    """Remove a short-code cache entry when destination data changes."""

    if not _cache_enabled():
        return

    cache_key = short_code_cache_key(short_code)

    try:
        await get_redis_client().delete(cache_key)
    except RedisError:
        _log_redis_unavailable_once("delete", short_code)


async def close_redis_client() -> None:
    """Close and reset the singleton Redis client."""

    global _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None

