"""Append-only evidence ledger stored in the state database (ADR 0006).

Every successful tool result gets one row; its id (``ev:<ULID>``) is the envelope's
``provenance_id``. SQLite triggers abort any UPDATE or DELETE, so rows are immutable even
if a future bug (or a curious user with sqlite3) tries to change them.
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from simplymz_mcp.core.handles import new_handle
from simplymz_mcp.state.store import Store, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    op TEXT NOT NULL,
    params TEXT NOT NULL,
    input_hashes TEXT NOT NULL,
    parents TEXT NOT NULL,
    versions TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""
TRACKED_PACKAGES = ("simplymz-mcp", "mcp", "numpy", "scipy", "pyteomics", "pyarrow")


def package_versions() -> dict[str, str]:
    out = {}
    for name in TRACKED_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover
            out[name] = "unknown"
    return out


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


class Ledger:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.versions = package_versions()
        with store.lock:
            store.db.executescript(SCHEMA)

    def record(
        self,
        op: str,
        params: dict[str, Any],
        result: dict[str, Any],
        *,
        input_hashes: list[str] | None = None,
        parents: list[str] | None = None,
    ) -> str:
        ev = new_handle("ev")
        body = {k: v for k, v in result.items() if k != "provenance_id"}
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO ledger (id, op, params, input_hashes, parents, versions, ts_utc, "
                "status, result_digest, result) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    ev,
                    op,
                    canonical_json(params),
                    canonical_json(sorted(input_hashes or [])),
                    canonical_json(parents or []),
                    canonical_json(self.versions),
                    utcnow(),
                    str(result.get("status")),
                    digest(body),
                    canonical_json(body),
                ),
            )
        return ev

    def get(self, ev: str) -> dict[str, Any] | None:
        with self.store.lock:
            cur = self.store.db.execute("SELECT * FROM ledger WHERE id = ?", (ev,))
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
        if row is None:
            return None
        rec = dict(zip(cols, row, strict=True))
        for k in ("params", "input_hashes", "parents", "versions", "result"):
            rec[k] = json.loads(rec[k])
        return rec

    def count(self) -> int:
        with self.store.lock:
            n: int = self.store.db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        return n

    def ids(self) -> list[str]:
        with self.store.lock:
            return [r[0] for r in self.store.db.execute("SELECT id FROM ledger ORDER BY seq")]

    def export_jsonl(self, path: Path) -> int:
        n = 0
        with open(path, "w", encoding="utf-8") as fh:
            for ev in self.ids():
                fh.write(canonical_json(self.get(ev)) + "\n")
                n += 1
        return n
