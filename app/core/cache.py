"""In-memory cache helpers for QR short-code lookups."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

SHORT_CODE_CACHE_PREFIX = "qr:short_code:"
DEFAULT_SHORT_CODE_CACHE_TTL_SECONDS = 300

_short_code_cache: dict[str, tuple[str, float | None]] = {}


def _cache_enabled() -> bool:
    return True


def _is_expired(expires_at: float | None) -> bool:
    return expires_at is not None and time.monotonic() >= expires_at


def _store_value(cache_key: str, raw_payload: str, ttl_seconds: int | None) -> None:
    expires_at = None if ttl_seconds is None else time.monotonic() + max(ttl_seconds, 0)
    _short_code_cache[cache_key] = (raw_payload, expires_at)


def _get_value(cache_key: str) -> str | None:
    cached_entry = _short_code_cache.get(cache_key)
    if cached_entry is None:
        return None

    raw_payload, expires_at = cached_entry
    if _is_expired(expires_at):
        _short_code_cache.pop(cache_key, None)
        return None

    return raw_payload


def short_code_cache_key(short_code: str) -> str:
    """Build a stable cache key for a short code."""

    return f"{SHORT_CODE_CACHE_PREFIX}{short_code}"


async def get_cached_short_code(short_code: str) -> dict[str, Any] | None:
    """Fetch cached QR payload for a short code."""

    if not _cache_enabled():
        return None

    cache_key = short_code_cache_key(short_code)

    payload = _get_value(cache_key)

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
    resolved_ttl = ttl_seconds or DEFAULT_SHORT_CODE_CACHE_TTL_SECONDS

    try:
        raw_payload = json.dumps(payload)
        _store_value(cache_key, raw_payload, resolved_ttl)
        return True
    except (TypeError, ValueError):
        logger.warning("Failed to cache short code '%s' in memory", short_code)
        return False


async def invalidate_short_code_cache(short_code: str) -> None:
    """Remove a short-code cache entry when destination data changes."""

    if not _cache_enabled():
        return

    cache_key = short_code_cache_key(short_code)
    _short_code_cache.pop(cache_key, None)


async def clear_short_code_cache_store() -> None:
    """Clear the in-memory short-code cache store."""

    _short_code_cache.clear()

