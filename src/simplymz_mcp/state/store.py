"""SQLite-backed handle store (ADR 0002). Shared by the ledger (same database file)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.handles import new_handle, parse_handle

SCHEMA = """
CREATE TABLE IF NOT EXISTS handles (
    handle TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    last_used_utc TEXT NOT NULL,
    released INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS handles_kind ON handles(kind);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Store:
    """Thread-safe wrapper around one SQLite file under the cache directory."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            cache_dir / "state.sqlite", check_same_thread=False, isolation_level=None
        )
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def create(self, kind: str, meta: dict[str, Any]) -> str:
        handle = new_handle(kind)
        now = utcnow()
        with self.lock:
            self.db.execute(
                "INSERT INTO handles VALUES (?, ?, ?, ?, 0, ?)",
                (handle, kind, now, now, json.dumps(meta, sort_keys=True)),
            )
        return handle

    def find(self, kind: str, key: str, value: str) -> str | None:
        """Live handle of ``kind`` whose meta[key] == value (e.g. a run by sha256)."""
        with self.lock:
            row = self.db.execute(
                "SELECT handle FROM handles WHERE kind = ? AND released = 0 "
                "AND json_extract(meta, ?) = ? ORDER BY created_utc LIMIT 1",
                (kind, f"$.{key}", value),
            ).fetchone()
        return row[0] if row else None

    def get(self, handle: str, kind: str | None = None) -> dict[str, Any]:
        try:
            hkind, _ = parse_handle(handle)
        except ValueError as exc:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"{handle!r} is not a SimplyMZ handle.",
                "Handles look like 'run:01J…'; get one from load_run.",
            ) from exc
        if kind is not None and hkind != kind:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"Expected a {kind}: handle, got {hkind}:.",
                f"Pass a {kind}: handle here.",
            )
        with self.lock:
            row = self.db.execute(
                "SELECT meta, released FROM handles WHERE handle = ?", (handle,)
            ).fetchone()
            if row is None or row[1]:
                raise SimplyMZError(
                    ErrorCode.UNKNOWN_HANDLE,
                    f"Handle {handle} is unknown or was released.",
                    "Load the file again with load_run to get a fresh handle.",
                )
            self.db.execute(
                "UPDATE handles SET last_used_utc = ? WHERE handle = ?", (utcnow(), handle)
            )
        meta: dict[str, Any] = json.loads(row[0])
        return meta

    def release(self, handle: str) -> bool:
        with self.lock:
            cur = self.db.execute(
                "UPDATE handles SET released = 1 WHERE handle = ? AND released = 0", (handle,)
            )
        return cur.rowcount == 1

    def expire(self, ttl_days: float) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat(timespec="milliseconds")
        with self.lock:
            cur = self.db.execute(
                "UPDATE handles SET released = 1 WHERE released = 0 AND last_used_utc < ?",
                (cutoff,),
            )
        return cur.rowcount
