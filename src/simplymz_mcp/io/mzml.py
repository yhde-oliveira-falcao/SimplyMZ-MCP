"""mzML / mzML.gz reader (plan M1.T2).

Produces a columnar :class:`RunData`: a scan table (one row per spectrum) plus all peaks
packed into flat arrays with per-scan offsets. Nothing here returns raw arrays to MCP
clients; tools summarise them.
"""

from __future__ import annotations

import functools
import gzip
import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import numpy as np

from simplymz_mcp.config import Limits
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

log = logging.getLogger("simplymz_mcp")

POLARITY_CODE = {"positive": 1, "negative": -1, "unknown": 0}
CENTROID, PROFILE, UNKNOWN_MODE = 1, 0, -1


@dataclass
class ScanTable:
    native_id: list[str]
    rt_min: np.ndarray  # float64
    ms_level: np.ndarray  # int8
    polarity: np.ndarray  # int8: +1 / -1 / 0
    centroided: np.ndarray  # int8: 1 centroid, 0 profile, -1 unknown
    tic: np.ndarray  # float64
    base_peak_mz: np.ndarray  # float64 (nan if empty)
    base_peak_intensity: np.ndarray  # float64
    n_peaks: np.ndarray  # int32
    precursor_mz: np.ndarray  # float64 (nan for MS1)

    def __len__(self) -> int:
        return len(self.native_id)


@dataclass
class RunData:
    path: Path
    sha256: str
    scans: ScanTable
    offsets: np.ndarray  # int64, len n_scans + 1
    mz: np.ndarray  # float64, all peaks
    intensity: np.ndarray  # float32, all peaks
    meta: dict[str, Any] = field(default_factory=dict)

    def peaks(self, i: int) -> tuple[np.ndarray, np.ndarray]:
        a, b = int(self.offsets[i]), int(self.offsets[i + 1])
        return self.mz[a:b], self.intensity[a:b]


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def rt_minutes(value: Any) -> float:
    """Scan start time in minutes; pyteomics returns a unitfloat with unit_info."""
    unit = str(getattr(value, "unit_info", "minute") or "minute").lower()
    v = float(value)
    if unit in ("second", "s", "sec", "uo:0000010"):
        return v / 60.0
    if unit in ("hour", "h"):
        return v * 60.0
    return v


def guess_centroided(mz: np.ndarray) -> int:
    """Fallback when no CV term says centroid/profile: profile data are dense and regular."""
    if mz.size < 50:
        return UNKNOWN_MODE
    spacing = np.diff(mz)
    return PROFILE if float(np.median(spacing)) < 0.02 else CENTROID


@functools.lru_cache(maxsize=1)
def psi_ms_cv() -> Any:
    """The PSI-MS controlled vocabulary from psims' vendored copy, loaded once, offline.

    Without this, pyteomics asks psims to fetch the vocabulary from purl.obolibrary.org on
    every file it opens (12 network attempts per run seen in Final Verification D16), and
    offline users wait for timeouts. Falls back to psims' public loader if the private
    vendored helper ever disappears.
    """
    try:
        from psims.controlled_vocabulary.controlled_vocabulary import ControlledVocabulary
        from psims.controlled_vocabulary.vendor import _use_vendored_psims_obo

        return ControlledVocabulary.from_obo(_use_vendored_psims_obo())
    except ImportError:  # pragma: no cover - depends on psims internals
        from psims.controlled_vocabulary.controlled_vocabulary import load_psims

        return load_psims()


def _open(path: Path) -> IO[bytes] | gzip.GzipFile:
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rb")
    return open(path, "rb")


def read_mzml(path: Path, limits: Limits | None = None) -> RunData:
    from pyteomics import mzml

    limits = limits or Limits()
    native: list[str] = []
    rt: list[float] = []
    level: list[int] = []
    pol: list[int] = []
    cen: list[int] = []
    tic: list[float] = []
    bpm: list[float] = []
    bpi: list[float] = []
    npk: list[int] = []
    prec: list[float] = []
    mz_parts: list[np.ndarray] = []
    int_parts: list[np.ndarray] = []
    try:
        with _open(path) as fh:
            # mzml.read() drops its cv argument (pyteomics 5.0.1), so build MzML directly.
            for spec in mzml.MzML(fh, use_index=False, cv=psi_ms_cv()):
                if len(native) >= limits.max_scans:
                    raise SimplyMZError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"Run has more than {limits.max_scans} spectra.",
                        "Raise max_scans in the server config, or filter the file with msconvert.",
                    )
                mz = np.asarray(spec.get("m/z array", ()), dtype=np.float64)
                it = np.asarray(spec.get("intensity array", ()), dtype=np.float32)
                if mz.shape != it.shape:
                    raise ValueError(f"spectrum {spec.get('id')}: m/z and intensity lengths differ")
                native.append(str(spec.get("id", f"index={len(native)}")))
                scan = spec.get("scanList", {}).get("scan", [{}])[0]
                if "scan start time" not in scan:
                    raise ValueError(f"spectrum {native[-1]} has no scan start time")
                rt.append(rt_minutes(scan["scan start time"]))
                level.append(int(spec.get("ms level", 1)))
                pol.append(1 if "positive scan" in spec else -1 if "negative scan" in spec else 0)
                if "centroid spectrum" in spec:
                    cen.append(CENTROID)
                elif "profile spectrum" in spec:
                    cen.append(PROFILE)
                else:
                    cen.append(guess_centroided(mz))
                tic.append(float(spec.get("total ion current", it.sum(dtype=np.float64))))
                if it.size:
                    j = int(np.argmax(it))
                    bpm.append(float(mz[j]))
                    bpi.append(float(it[j]))
                else:
                    bpm.append(float("nan"))
                    bpi.append(0.0)
                npk.append(int(mz.size))
                p = float("nan")
                if level[-1] > 1:
                    try:
                        ion = spec["precursorList"]["precursor"][0]["selectedIonList"][
                            "selectedIon"
                        ][0]
                        p = float(ion["selected ion m/z"])
                    except (KeyError, IndexError, TypeError):
                        pass
                prec.append(p)
                mz_parts.append(mz)
                int_parts.append(it)
    except SimplyMZError:
        raise
    except Exception as exc:  # lxml, gzip, pyteomics errors all mean "can't read this"
        log.warning("failed to read %s: %s", path, exc)
        raise SimplyMZError(
            ErrorCode.MALFORMED_FILE,
            f"Could not read {path.name} as mzML ({type(exc).__name__}).",
            "The file may be truncated or not mzML. Re-export it with msconvert and check that "
            "the copy finished.",
        ) from exc
    if not native:
        raise SimplyMZError(
            ErrorCode.MALFORMED_FILE,
            f"{path.name} contains no spectra.",
            "Check the export settings (MS levels, scan filters) and re-convert.",
        )
    offsets = np.zeros(len(native) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(npk)
    scans = ScanTable(
        native_id=native,
        rt_min=np.asarray(rt, dtype=np.float64),
        ms_level=np.asarray(level, dtype=np.int8),
        polarity=np.asarray(pol, dtype=np.int8),
        centroided=np.asarray(cen, dtype=np.int8),
        tic=np.asarray(tic, dtype=np.float64),
        base_peak_mz=np.asarray(bpm, dtype=np.float64),
        base_peak_intensity=np.asarray(bpi, dtype=np.float64),
        n_peaks=np.asarray(npk, dtype=np.int32),
        precursor_mz=np.asarray(prec, dtype=np.float64),
    )
    run = RunData(
        path=path,
        sha256=sha256_file(path),
        scans=scans,
        offsets=offsets,
        mz=np.concatenate(mz_parts) if mz_parts else np.empty(0),
        intensity=np.concatenate(int_parts) if int_parts else np.empty(0, np.float32),
    )
    run.meta = validate(run)
    return run


def validate(run: RunData) -> dict[str, Any]:
    """Summarise structure and note issues a chemist would want to know about."""
    s = run.scans
    levels = Counter(int(v) for v in s.ms_level)
    pols = {int(v) for v in s.polarity}
    if pols == {1}:
        polarity = "positive"
    elif pols == {-1}:
        polarity = "negative"
    elif {1, -1} <= pols:
        polarity = "switching"
    else:
        polarity = "unknown"
    modes = {int(v) for v in s.centroided}
    mode = (
        "centroid"
        if modes == {CENTROID}
        else "profile"
        if modes == {PROFILE}
        else "unknown"
        if modes == {UNKNOWN_MODE}
        else "mixed"
    )
    warnings: list[str] = []
    if np.any(np.diff(s.rt_min) < 0):
        warnings.append("Scan times are not monotonically increasing.")
    if mode in ("profile", "mixed"):
        warnings.append("Profile-mode spectra present; peak-based tools expect centroided data.")
    if polarity == "unknown":
        warnings.append("Polarity is not annotated in the file.")
    return {
        "n_spectra": len(s),
        "ms_level_counts": {str(k): v for k, v in sorted(levels.items())},
        "polarity": polarity,
        "spectrum_mode": mode,
        "rt_range_min": [round(float(s.rt_min.min()), 4), round(float(s.rt_min.max()), 4)],
        "warnings": warnings,
    }
