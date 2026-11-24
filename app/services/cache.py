"""Small TTL cache for completed analyses (SQLite with in-memory fallback)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


def cache_key(
    *,
    url: str,
    provider: str,
    model: str,
    prompt_version: str,
    max_input_chars: int,
) -> str:
    material = f"{url}|{provider}|{model}|{prompt_version}|{max_input_chars}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AnalysisCache:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = settings.cache_enabled
        self.ttl = max(0, settings.cache_ttl_seconds)
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}
        self._sqlite_path: Path | None = None
        if self.enabled:
            self._initialise_sqlite()

    def _initialise_sqlite(self) -> None:
        if self.ttl <= 0:
            self.enabled = False
            return
        try:
            path = self.settings.resolved_cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analysis_cache (
                        key TEXT PRIMARY KEY,
                        created_at REAL NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_analysis_cache_created_at "
                    "ON analysis_cache (created_at)"
                )
            self._sqlite_path = path
            logger.info("Analysis cache enabled at %s (ttl=%ss)", path, self.ttl)
        except Exception as exc:
            logger.warning("SQLite cache unavailable (%s); using in-memory cache.", exc)
            self._sqlite_path = None

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    async def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        if self._sqlite_path is not None:
            return await asyncio.to_thread(self._get_sqlite, key)
        return self._get_memory(key)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if self._sqlite_path is not None:
            await asyncio.to_thread(self._set_sqlite, key, value)
            return
        self._memory[key] = (time.time(), value)

    def _get_sqlite(self, key: str) -> dict[str, Any] | None:
        assert self._sqlite_path is not None
        cutoff = time.time() - self.ttl
        try:
            with self._connect(self._sqlite_path) as connection:
                row = connection.execute(
                    "SELECT created_at, payload FROM analysis_cache WHERE key = ?", (key,)
                ).fetchone()
                if row is None:
                    return None
                created_at, payload = row
                if created_at < cutoff:
                    connection.execute("DELETE FROM analysis_cache WHERE key = ?", (key,))
                    return None
                return json.loads(payload)
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            logger.warning("Cache read failed: %s", exc)
            return None

    def _set_sqlite(self, key: str, value: dict[str, Any]) -> None:
        assert self._sqlite_path is not None
        cutoff = time.time() - self.ttl
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            with self._connect(self._sqlite_path) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO analysis_cache (key, created_at, payload) "
                    "VALUES (?, ?, ?)",
                    (key, time.time(), payload),
                )
                connection.execute(
                    "DELETE FROM analysis_cache WHERE created_at < ?", (cutoff,)
                )
        except (sqlite3.Error, TypeError) as exc:
            logger.warning("Cache write failed: %s", exc)

    def _get_memory(self, key: str) -> dict[str, Any] | None:
        item = self._memory.get(key)
        if item is None:
            return None
        created_at, value = item
        if created_at < time.time() - self.ttl:
            self._memory.pop(key, None)
            return None
        return value

    async def aclose(self) -> None:
        self._memory.clear()
