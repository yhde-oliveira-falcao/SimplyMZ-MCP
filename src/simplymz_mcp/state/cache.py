"""Parquet run cache keyed by file SHA-256, bounded by size (least recently used evicted)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from simplymz_mcp.io.mzml import RunData, ScanTable

log = logging.getLogger("simplymz_mcp")
SCAN_COLUMNS = (
    "rt_min",
    "ms_level",
    "polarity",
    "centroided",
    "tic",
    "base_peak_mz",
    "base_peak_intensity",
    "n_peaks",
    "precursor_mz",
)


class RunCache:
    def __init__(self, cache_dir: Path, max_mb: float = 2048) -> None:
        self.dir = cache_dir / "runs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_mb * 1024 * 1024)

    def _paths(self, sha: str) -> tuple[Path, Path]:
        return self.dir / f"{sha}.scans.parquet", self.dir / f"{sha}.peaks.parquet"

    def has(self, sha: str) -> bool:
        return all(p.exists() for p in self._paths(sha))

    def save(self, run: RunData) -> None:
        scans_p, peaks_p = self._paths(run.sha256)
        s = run.scans
        cols = {c: getattr(s, c) for c in SCAN_COLUMNS}
        table = pa.table({"native_id": pa.array(s.native_id, pa.string()), **cols})
        meta = {
            b"simplymz_meta": json.dumps(run.meta).encode(),
            b"source_path": str(run.path).encode(),
        }
        table = table.replace_schema_metadata(meta)
        tmp_s, tmp_p = scans_p.with_suffix(".tmp"), peaks_p.with_suffix(".tmp")
        pq.write_table(table, tmp_s)
        pq.write_table(pa.table({"mz": run.mz, "intensity": run.intensity}), tmp_p)
        os.replace(tmp_s, scans_p)  # atomic: a crash never leaves a half-written cache entry
        os.replace(tmp_p, peaks_p)
        self.evict(keep=run.sha256)

    def load(self, sha: str) -> RunData:
        scans_p, peaks_p = self._paths(sha)
        t = pq.read_table(scans_p)
        meta = t.schema.metadata or {}
        cols = {c: t.column(c).to_numpy() for c in SCAN_COLUMNS}
        scans = ScanTable(native_id=t.column("native_id").to_pylist(), **cols)
        pk = pq.read_table(peaks_p)
        offsets = np.zeros(len(scans) + 1, dtype=np.int64)
        offsets[1:] = np.cumsum(scans.n_peaks)
        now = None  # touch for LRU
        for p in (scans_p, peaks_p):
            os.utime(p, now)
        return RunData(
            path=Path(meta.get(b"source_path", b"").decode()),
            sha256=sha,
            scans=scans,
            offsets=offsets,
            mz=pk.column("mz").to_numpy(),
            intensity=pk.column("intensity").to_numpy().astype(np.float32, copy=False),
            meta=json.loads(meta.get(b"simplymz_meta", b"{}")),
        )

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.dir.glob("*.parquet"))

    def evict(self, keep: str | None = None) -> list[str]:
        """Remove least-recently-used runs until the cache fits; never removes ``keep``."""
        groups: dict[str, list[Path]] = {}
        for p in self.dir.glob("*.parquet"):
            groups.setdefault(p.name.split(".")[0], []).append(p)
        total = sum(p.stat().st_size for ps in groups.values() for p in ps)
        evicted = []
        by_age = sorted(groups.items(), key=lambda kv: max(p.stat().st_mtime for p in kv[1]))
        for sha, files in by_age:
            if total <= self.max_bytes:
                break
            if sha == keep:
                continue
            for p in files:
                total -= p.stat().st_size
                p.unlink(missing_ok=True)
            evicted.append(sha)
            log.info("evicted run %s from cache", sha[:12])
        return evicted
