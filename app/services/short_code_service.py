"""Base62 short-code generation with collision retry handling."""

from __future__ import annotations

import inspect
import random
from collections.abc import Awaitable, Callable

BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

CollisionHook = Callable[[str, int], None | Awaitable[None]]
ExistsChecker = Callable[[str], Awaitable[bool]]


def generate_base62_code(
    *,
    length: int = 8,
    rng: random.Random | None = None,
) -> str:
    """Generate one random Base62 short code."""

    if length <= 0:
        raise ValueError("length must be greater than 0")

    random_source = rng or random.SystemRandom()
    return "".join(random_source.choice(BASE62_ALPHABET) for _ in range(length))


async def generate_unique_base62_code(
    exists_checker: ExistsChecker,
    *,
    length: int = 8,
    max_attempts: int = 10,
    on_collision: CollisionHook | None = None,
    rng: random.Random | None = None,
) -> str:
    """Generate a unique Base62 code and retry on collisions up to `max_attempts`."""

    if max_attempts <= 0:
        raise ValueError("max_attempts must be greater than 0")

    for attempt in range(1, max_attempts + 1):
        candidate = generate_base62_code(length=length, rng=rng)
        if not await exists_checker(candidate):
            return candidate

        if on_collision is not None:
            hook_result = on_collision(candidate, attempt)
            if inspect.isawaitable(hook_result):
                await hook_result

    raise RuntimeError(
        f"Could not generate unique short code after {max_attempts} attempts",
    )

