from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec
from simplymz_mcp.ledger.ledger import Ledger, digest
from simplymz_mcp.state.store import Store


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(Store(tmp_path))


def test_record_and_get_roundtrip(ledger: Ledger) -> None:
    res = envelope.ok("Loaded.", {"n": 3})
    ev = ledger.record(
        "load_run", {"path": "a.mzML"}, res, input_hashes=["b", "a"], parents=["run:X"]
    )
    rec = ledger.get(ev)
    assert rec is not None
    assert rec["op"] == "load_run" and rec["params"] == {"path": "a.mzML"}
    assert rec["input_hashes"] == ["a", "b"] and rec["parents"] == ["run:X"]
    body = {k: v for k, v in res.items() if k != "provenance_id"}  # id is assigned after hashing
    assert rec["result_digest"] == digest(body) and rec["result"]["data"] == {"n": 3}
    assert {"simplymz-mcp", "numpy", "pyteomics"} <= rec["versions"].keys()
    assert rec["ts_utc"].endswith("+00:00")
    assert ledger.get("ev:01ARZ3NDEKTSV4RRFFQ69G5FAV") is None


@pytest.mark.parametrize("sql", ["UPDATE ledger SET op = 'x'", "DELETE FROM ledger"])
def test_rows_are_immutable(ledger: Ledger, sql: str) -> None:
    ledger.record("op", {}, envelope.ok("x"))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.store.db.execute(sql)
    assert ledger.count() == 1


def test_immutable_through_a_separate_connection(ledger: Ledger, tmp_path: Path) -> None:
    ledger.record("op", {}, envelope.ok("x"))
    other = sqlite3.connect(tmp_path / "state.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        other.execute("DELETE FROM ledger")


def test_export_jsonl(ledger: Ledger, tmp_path: Path) -> None:
    for i in range(3):
        ledger.record("op", {"i": i}, envelope.ok(f"r{i}"))
    out = tmp_path / "ledger.jsonl"
    assert ledger.export_jsonl(out) == 3
    assert len(out.read_text().splitlines()) == 3


def _tool(mz: float, label: str = "a") -> dict[str, Any]:
    env = envelope.ok(f"{label} {mz}")
    env["_provenance"] = {"input_hashes": ["sha1"], "parents": ["run:P"]}
    return env


def test_registry_writes_one_entry_per_successful_call(ledger: Ledger) -> None:
    reg = Registry(ledger=ledger)
    fn = reg.register(ToolSpec("demo", "d", _tool))
    out = fn(mz=1.5)
    assert "_provenance" not in out
    rec = ledger.get(out["provenance_id"])
    assert rec is not None and rec["params"] == {"mz": 1.5, "label": "a"}
    assert rec["input_hashes"] == ["sha1"] and rec["parents"] == ["run:P"]
    assert ledger.count() == 1


def test_errors_are_not_ledgered(ledger: Ledger) -> None:
    def bad() -> dict[str, Any]:
        raise SimplyMZError(ErrorCode.FILE_NOT_FOUND, "x", "y")

    out = Registry(ledger=ledger).register(ToolSpec("bad", "d", bad))()
    assert out["status"] == "error" and out["provenance_id"] is None
    assert ledger.count() == 0


def test_ledger_failure_becomes_instructive_error(ledger: Ledger) -> None:
    fn = Registry(ledger=ledger).register(ToolSpec("demo", "d", _tool))
    ledger.store.close()
    out = fn(mz=1.0)
    assert out["error"]["code"] == "INTERNAL" and "ledger" in out["verdict"]
