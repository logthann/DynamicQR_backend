"""Tests for Redis cache helpers in degraded local-dev mode."""

from __future__ import annotations

import pytest

from app.core import cache


@pytest.mark.asyncio
async def test_get_cached_short_code_returns_none_when_cache_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.cache._cache_enabled", lambda: False)
    monkeypatch.setattr(
        "app.core.cache.get_redis_client",
        lambda: (_ for _ in ()).throw(AssertionError("redis client should not be used")),
    )

    result = await cache.get_cached_short_code("abc123")

    assert result is None


@pytest.mark.asyncio
async def test_set_cached_short_code_returns_false_when_cache_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.cache._cache_enabled", lambda: False)
    monkeypatch.setattr(
        "app.core.cache.get_redis_client",
        lambda: (_ for _ in ()).throw(AssertionError("redis client should not be used")),
    )

    stored = await cache.set_cached_short_code("abc123", {"id": 1})

    assert stored is False


@pytest.mark.asyncio
async def test_invalidate_short_code_cache_noop_when_cache_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.cache._cache_enabled", lambda: False)
    monkeypatch.setattr(
        "app.core.cache.get_redis_client",
        lambda: (_ for _ in ()).throw(AssertionError("redis client should not be used")),
    )

    await cache.invalidate_short_code_cache("abc123")

