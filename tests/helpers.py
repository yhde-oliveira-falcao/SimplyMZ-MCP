"""Shared helpers for tests (raw stdio JSON-RPC client)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

PROTOCOL = "2025-06-18"


class RawStdioSession:
    """Talks JSON-RPC to ``simplymz-mcp`` over stdio and records every stdout line."""

    def __init__(self, root: Path, extra_args: list[str] | None = None) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "simplymz_mcp.server",
                "--root",
                str(root),
                *(extra_args or []),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self.stdout_lines: list[str] = []
        self._q: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._next_id = 0

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.stdout_lines.append(line)
            self._q.put(line)

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        self._next_id += 1
        rid = self._next_id
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            line = self._q.get(timeout=timeout)
            msg = json.loads(line)
            if msg.get("id") == rid:
                return msg

    def initialize(self) -> dict[str, Any]:
        res = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def close(self) -> str:
        assert self.proc.stdin is not None and self.proc.stderr is not None
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        return self.proc.stderr.read()


def make_run(spectra: list[tuple[float, list[float], list[float]]], polarity: int = 1):  # type: ignore[no-untyped-def]
    """Build an in-memory MS1 RunData from (rt_min, mz list, intensity list) tuples."""
    import numpy as np

    from simplymz_mcp.io.mzml import RunData, ScanTable

    n = len(spectra)
    mz = [np.asarray(s[1], float) for s in spectra]
    it = [np.asarray(s[2], np.float32) for s in spectra]
    order = [np.argsort(m) for m in mz]
    mz = [m[o] for m, o in zip(mz, order, strict=True)]
    it = [i[o] for i, o in zip(it, order, strict=True)]
    npk = np.array([len(m) for m in mz], dtype=np.int32)
    offsets = np.zeros(n + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(npk)
    st = ScanTable(
        native_id=[f"scan={i + 1}" for i in range(n)],
        rt_min=np.array([s[0] for s in spectra]),
        ms_level=np.ones(n, dtype=np.int8),
        polarity=np.full(n, polarity, dtype=np.int8),
        centroided=np.ones(n, dtype=np.int8),
        tic=np.array([float(x.sum()) for x in it]),
        base_peak_mz=np.array(
            [m[np.argmax(i)] if len(m) else np.nan for m, i in zip(mz, it, strict=True)]
        ),
        base_peak_intensity=np.array([float(i.max()) if len(i) else 0.0 for i in it]),
        n_peaks=npk,
        precursor_mz=np.full(n, np.nan),
    )
    return RunData(
        Path("mem.mzML"),
        "mem",
        st,
        offsets,
        np.concatenate(mz) if n else np.empty(0),
        np.concatenate(it) if n else np.empty(0, np.float32),
    )


def score_features(
    features: list[dict], truth: dict, ppm: float = 10.0, rt_tol: float = 0.1
) -> tuple[set[str], int, int]:
    """(matched compound names, true-positive monoisotopic features, all monoisotopic)."""
    mono = [f for f in features if f.get("isotope_of") is None]
    matched: set[str] = set()
    good = 0
    for f in mono:
        hits = [
            c["name"]
            for c in truth["compounds"]
            if abs(f["mz"] - c["ion_mz"]) / c["ion_mz"] * 1e6 <= ppm
            and abs(f["rt_min"] - c["rt_min"]) <= rt_tol
        ]
        good += bool(hits)
        matched.update(hits)
    return matched, good, len(mono)


def measurable_truth(truth: dict) -> dict:
    """Truth minus compounds whose apex lies inside an injected dropout (not in the data)."""
    drop = truth["dropout_ms1_indices"]
    if not drop:
        return truth
    lo = truth["rt_range_min"][0] + min(drop) * truth["scan_interval_min"]
    hi = truth["rt_range_min"][0] + max(drop) * truth["scan_interval_min"]
    keep = [c for c in truth["compounds"] if not lo <= c["rt_min"] <= hi]
    return {**truth, "compounds": keep}
