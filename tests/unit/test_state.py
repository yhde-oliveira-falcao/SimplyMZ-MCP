from __future__ import annotations

import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from simplymz_mcp.config import Config
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.state.cache import RunCache
from simplymz_mcp.state.runs import RunRegistry
from simplymz_mcp.state.store import Store
from tests.conftest import FIXTURES


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "data"
    r.mkdir()
    shutil.copy(FIXTURES / "runs" / "clean_pos.mzML", r)
    shutil.copy(FIXTURES / "runs" / "ms2_dda.mzML.gz", r)
    return r


def _registry(root: Path, max_mb: float = 2048) -> tuple[RunRegistry, Store]:
    cache_dir = root / ".simplymz"
    store = Store(cache_dir)
    return RunRegistry(Config(root=root), store, RunCache(cache_dir, max_mb)), store


def test_handles_create_get_release(tmp_path: Path) -> None:
    s = Store(tmp_path)
    h = s.create("run", {"sha256": "abc", "path": "x.mzML"})
    assert s.get(h, "run")["path"] == "x.mzML"
    assert s.find("run", "sha256", "abc") == h
    with pytest.raises(SimplyMZError) as ei:
        s.get(h, "batch")
    assert ei.value.code == ErrorCode.INVALID_ARGUMENT
    assert s.release(h) and not s.release(h)
    with pytest.raises(SimplyMZError) as ei:
        s.get(h)
    assert ei.value.code == ErrorCode.UNKNOWN_HANDLE and "load_run" in ei.value.hint
    with pytest.raises(SimplyMZError):
        s.get("not-a-handle")


def test_ttl_expiry(tmp_path: Path) -> None:
    s = Store(tmp_path)
    h = s.create("run", {"sha256": "a", "path": "p"})
    assert s.expire(ttl_days=1) == 0
    time.sleep(0.01)
    assert s.expire(ttl_days=0) == 1
    with pytest.raises(SimplyMZError):
        s.get(h)


def test_first_load_parses_second_load_reuses(root: Path) -> None:
    reg, _ = _registry(root)
    a = reg.load("clean_pos.mzML")
    assert not a.cache_hit and not a.reused_handle
    b = reg.load("clean_pos.mzML")
    assert b.handle == a.handle and b.reused_handle and b.cache_hit


def test_restart_resolves_handle_from_parquet_without_reparsing(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg1, store1 = _registry(root)
    first = reg1.load("ms2_dda.mzML.gz")
    store1.close()
    # Simulated restart: brand-new objects on the same cache dir. Parsing is forbidden.
    import simplymz_mcp.state.runs as runs_mod

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("re-parsed the mzML instead of using the cache")

    monkeypatch.setattr(runs_mod, "read_mzml", boom)
    reg2, _ = _registry(root)
    run = reg2.get(first.handle)
    assert np.array_equal(run.mz, first.run.mz)
    assert np.array_equal(run.scans.precursor_mz, first.run.scans.precursor_mz, equal_nan=True)
    assert run.scans.native_id == first.run.scans.native_id
    assert run.meta == first.run.meta


def test_cache_eviction_keeps_newest(root: Path) -> None:
    reg, _ = _registry(root, max_mb=0.000001)  # everything over budget
    reg.load("clean_pos.mzML")
    reg.load("ms2_dda.mzML.gz")
    remaining = {p.name.split(".")[0] for p in (root / ".simplymz" / "runs").glob("*.parquet")}
    assert len(remaining) == 1  # only the run just saved survives


def test_changed_file_detected_after_eviction(root: Path) -> None:
    reg, _ = _registry(root, max_mb=0.000001)
    a = reg.load("clean_pos.mzML")
    reg.load("ms2_dda.mzML.gz")  # evicts clean_pos from parquet cache
    reg._mem.clear()
    (root / "clean_pos.mzML").write_bytes(b"changed")
    with pytest.raises(SimplyMZError) as ei:
        reg.get(a.handle)
    assert ei.value.code == ErrorCode.UNKNOWN_HANDLE and "changed" in ei.value.message
