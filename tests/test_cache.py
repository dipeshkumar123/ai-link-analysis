from __future__ import annotations

import asyncio

from app.config import Settings
from app.services.cache import AnalysisCache, cache_key


def test_cache_round_trip(tmp_path) -> None:
    settings = Settings(
        cache_enabled=True,
        cache_path=str(tmp_path / "cache.sqlite3"),
        cache_ttl_seconds=3600,
    )
    cache = AnalysisCache(settings)
    key = cache_key(
        url="https://example.com/",
        provider="groq",
        model="openai/gpt-oss-120b",
        prompt_version="v1",
        max_input_chars=9000,
    )

    async def run() -> None:
        assert await cache.get(key) is None
        await cache.set(key, {"success": True, "website": "https://example.com/"})
        value = await cache.get(key)
        assert value == {"success": True, "website": "https://example.com/"}
        await cache.aclose()

    asyncio.run(run())


def test_cache_disabled_returns_nothing() -> None:
    settings = Settings(cache_enabled=False)
    cache = AnalysisCache(settings)

    async def run() -> None:
        await cache.set("key", {"a": 1})
        assert await cache.get("key") is None

    asyncio.run(run())