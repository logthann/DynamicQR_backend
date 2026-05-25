"""Tests for in-memory cache helpers."""

from __future__ import annotations

import asyncio

from app.core import cache


def test_short_code_cache_roundtrip() -> None:
    async def scenario() -> None:
        await cache.invalidate_short_code_cache("abc123")

        stored = await cache.set_cached_short_code("abc123", {"id": 1})
        result = await cache.get_cached_short_code("abc123")

        assert stored is True
        assert result == {"id": 1}

    asyncio.run(scenario())

def test_short_code_cache_invalidate_clears_entry() -> None:
    async def scenario() -> None:
        await cache.set_cached_short_code("abc123", {"id": 1})
        await cache.invalidate_short_code_cache("abc123")

        result = await cache.get_cached_short_code("abc123")

        assert result is None

    asyncio.run(scenario())

def test_short_code_cache_close_clears_store() -> None:
    async def scenario() -> None:
        await cache.set_cached_short_code("abc123", {"id": 1})
        await cache.clear_short_code_cache_store()

        result = await cache.get_cached_short_code("abc123")

        assert result is None

    asyncio.run(scenario())

