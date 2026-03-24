"""Tests for Base62 short-code generation and collision retry behavior."""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.services.short_code_service import (
    BASE62_ALPHABET,
    generate_base62_code,
    generate_unique_base62_code,
)


def test_generate_base62_code_uses_expected_charset_and_length() -> None:
    code = generate_base62_code(length=12)

    assert len(code) == 12
    assert re.fullmatch(r"[0-9A-Za-z]{12}", code) is not None
    assert set(code).issubset(set(BASE62_ALPHABET))


@pytest.mark.asyncio
async def test_generate_unique_base62_code_returns_on_first_non_collision() -> None:
    async def exists_checker(candidate: str) -> bool:
        return False

    code = await generate_unique_base62_code(exists_checker, length=8, max_attempts=3)

    assert len(code) == 8


@pytest.mark.asyncio
async def test_generate_unique_base62_code_calls_collision_hook() -> None:
    calls: list[tuple[str, int]] = []
    state: dict[str, Any] = {"count": 0}

    async def exists_checker(candidate: str) -> bool:
        state["count"] += 1
        return state["count"] == 1

    def on_collision(candidate: str, attempt: int) -> None:
        calls.append((candidate, attempt))

    code = await generate_unique_base62_code(
        exists_checker,
        length=8,
        max_attempts=3,
        on_collision=on_collision,
    )

    assert len(code) == 8
    assert len(calls) == 1
    assert calls[0][1] == 1


@pytest.mark.asyncio
async def test_generate_unique_base62_code_raises_when_attempts_exhausted() -> None:
    async def exists_checker(candidate: str) -> bool:
        return True

    with pytest.raises(RuntimeError, match="Could not generate unique short code"):
        await generate_unique_base62_code(exists_checker, length=6, max_attempts=2)

