"""Persistent storage abstraction for Spectre.

This module introduces a backend layer so persistence can be moved from
DigitalOcean Spaces to a Railway-hosted database incrementally.

Current capabilities:
- ``spaces`` backend (default): delegates to ``storage_spaces``.
- ``railway`` backend: key-value JSON persistence using ``DATABASE_URL``.
  - Supports ``sqlite:///...`` for local development and tests.
  - Supports PostgreSQL URLs via ``asyncpg`` in a sync-safe wrapper.

The public API mirrors the subset currently used by config modules:
``read_json`` and ``save_json``.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from storage_spaces import read_json as spaces_read_json
from storage_spaces import save_json as spaces_save_json


class JsonPersistenceBackend(Protocol):
    def read_json(self, path: str) -> dict[str, Any]: ...

    def save_json(self, path: str, payload: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class SpacesPersistenceBackend:
    """Persistence backend backed by DigitalOcean Spaces/local storage fallback."""

    def read_json(self, path: str) -> dict[str, Any]:
        return spaces_read_json(path)

    def save_json(self, path: str, payload: dict[str, Any]) -> None:
        spaces_save_json(path, payload)


class RailwayPersistenceBackend:
    """Persistence backend backed by an SQL database referenced by ``DATABASE_URL``."""

    def __init__(self, database_url: str):
        parsed = urlparse(database_url)
        if parsed.scheme not in {"sqlite", "postgres", "postgresql"}:
            raise ValueError(
                "Unsupported DATABASE_URL scheme for railway backend. "
                "Use sqlite://, postgres:// or postgresql://"
            )
        self.database_url = database_url
        self._is_sqlite = parsed.scheme == "sqlite"
        self._sqlite_path = self._resolve_sqlite_path(parsed) if self._is_sqlite else None
        self._ensure_schema()

    @staticmethod
    def _resolve_sqlite_path(parsed) -> str:
        if parsed.netloc:
            # sqlite://localhost/path.db -> //localhost/path.db is unusual but valid
            raw_path = f"//{parsed.netloc}{parsed.path}"
        else:
            raw_path = parsed.path
        if not raw_path:
            raise ValueError("sqlite DATABASE_URL must include a database path")
        if raw_path == ":memory:":
            return raw_path
        return str(Path(raw_path).expanduser().resolve())

    def _ensure_schema(self) -> None:
        query = (
            "CREATE TABLE IF NOT EXISTS spectre_kv ("
            "storage_key TEXT PRIMARY KEY,"
            "value_json TEXT NOT NULL,"
            "updated_at TEXT NOT NULL"
            ")"
        )
        if self._is_sqlite:
            if self._sqlite_path != ":memory:":
                Path(self._sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._sqlite_path) as conn:
                conn.execute(query)
                conn.commit()
            return

        async def _create() -> None:
            import asyncpg

            conn = await asyncpg.connect(self.database_url)
            try:
                await conn.execute(query)
            finally:
                await conn.close()

        self._run_async(_create())

    def read_json(self, path: str) -> dict[str, Any]:
        if self._is_sqlite:
            with sqlite3.connect(self._sqlite_path) as conn:
                row = conn.execute(
                    "SELECT value_json FROM spectre_kv WHERE storage_key = ?",
                    (path,),
                ).fetchone()
            if not row:
                raise FileNotFoundError(path)
            return json.loads(row[0])

        async def _read() -> dict[str, Any]:
            import asyncpg

            conn = await asyncpg.connect(self.database_url)
            try:
                row = await conn.fetchrow(
                    "SELECT value_json FROM spectre_kv WHERE storage_key = $1", path
                )
            finally:
                await conn.close()
            if not row:
                raise FileNotFoundError(path)
            return json.loads(row["value_json"])

        return self._run_async(_read())

    def save_json(self, path: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

        if self._is_sqlite:
            with sqlite3.connect(self._sqlite_path) as conn:
                conn.execute(
                    """
                    INSERT INTO spectre_kv(storage_key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(storage_key)
                    DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                    """,
                    (path, payload_json, now),
                )
                conn.commit()
            return

        async def _write() -> None:
            import asyncpg

            conn = await asyncpg.connect(self.database_url)
            try:
                await conn.execute(
                    """
                    INSERT INTO spectre_kv(storage_key, value_json, updated_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT(storage_key)
                    DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at
                    """,
                    path,
                    payload_json,
                    now,
                )
            finally:
                await conn.close()

        self._run_async(_write())

    @staticmethod
    def _run_async(coro):
        """Run coroutine safely even if caller already runs inside an event loop."""

        try:
            asyncio.get_running_loop()
            has_running_loop = True
        except RuntimeError:
            has_running_loop = False

        if not has_running_loop:
            return asyncio.run(coro)

        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def _runner():
            try:
                value = asyncio.run(coro)
                result_queue.put((True, value))
            except Exception as exc:  # pragma: no cover - defensive bridge
                result_queue.put((False, exc))

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        ok, value = result_queue.get()
        if ok:
            return value
        raise value


def get_backend() -> JsonPersistenceBackend:
    backend_name = (os.getenv("PERSISTENCE_BACKEND") or "").strip().lower()
    database_url = (os.getenv("DATABASE_URL") or "").strip()

    # Auto-detect the Railway backend when a DATABASE_URL is present but no
    # explicit PERSISTENCE_BACKEND is configured. This makes hosted
    # environments like Railway pick the database-backed storage by default
    # while keeping the original behaviour for existing deployments.
    if not backend_name:
        if database_url:
            backend_name = "railway"
        else:
            backend_name = "spaces"

    if backend_name == "spaces":
        return SpacesPersistenceBackend()
    if backend_name == "railway":
        if not database_url:
            raise RuntimeError("PERSISTENCE_BACKEND=railway requires DATABASE_URL")
        return RailwayPersistenceBackend(database_url)
    raise RuntimeError(f"Unknown persistence backend: {backend_name}")


def read_json(path: str) -> dict[str, Any]:
    return get_backend().read_json(path)


def save_json(path: str, payload: dict[str, Any]) -> None:
    get_backend().save_json(path, payload)
